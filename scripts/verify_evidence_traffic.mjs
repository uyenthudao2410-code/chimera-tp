/** Exercise real SDK, Pulse and proxy traffic through disposable loopback daemons. */
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";
import { setTimeout as delay } from "node:timers/promises";

const root = fileURLToPath(new URL("../", import.meta.url));
const run = promisify(execFile);
const { values: options } = parseArgs({ options: {
  python: { type: "string", default: "python" },
  out: { type: "string" },
} });

const isolatedDaemon = String.raw`
import json
from pathlib import Path
import sys
from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
work, node, peer = sys.argv[1:]
cfg = OpsConfig(node_name=node, role="controller", dashboard_bind="127.0.0.1:0",
                beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1,
                edge_proxy_port=-1, edge_targets={}, allowed_query_roots=[work], search_roots=[work],
                phantom_enabled=False)
daemon = ChimeraDaemon(config=cfg, ops_dir=Path(work), auto_seed_on_empty=False).start()
try:
    api = daemon.platform
    assert api.ephemeral
    wired = callable(api.pulse.on_activity) and callable(api.egress.on_activity)
    assert wired, "daemon traffic observers must be configured by its normal constructor"
    api.pulse.peer_base_resolver = (lambda: peer) if peer else None
    api.pulse.fallback_peer_resolver = None
    print(json.dumps({"ready": True, "anchor": api.anchor_url, "proxy": api.egress.url,
                      "native_wiring": wired}), flush=True)
    sys.stdin.readline()
finally:
    daemon.close()
    daemon.platform.evidence.flush_traffic()
`;

async function startDaemon(directory, node, peer = "") {
  await mkdir(directory);
  const proc = spawn(options.python, ["-B", "-u", "-c", isolatedDaemon, directory, node, peer],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  let diagnostics = "";
  proc.stderr.on("data", data => { diagnostics = (diagnostics + data).slice(-3000); });
  const exited = new Promise(resolveExit => proc.once("exit", code => resolveExit(code)));
  const lines = createInterface({ input: proc.stdout });
  const ready = new Promise((resolveReady, reject) => {
    proc.once("error", reject);
    const timer = setTimeout(() => reject(new Error("isolated daemon startup timed out")), 30000);
    exited.then(code => {
      clearTimeout(timer);
      reject(new Error("isolated daemon exited " + code + " " + diagnostics));
    });
    lines.on("line", line => {
      if (line.startsWith('{"ready":')) {
        clearTimeout(timer);
        resolveReady(JSON.parse(line));
      }
    });
  });
  const stop = async () => {
    if (proc.exitCode === null && proc.signalCode === null) proc.stdin.end();
    const timer = setTimeout(() => proc.kill(), 18000);
    try { assert.equal(await exited, 0, diagnostics); }
    finally { clearTimeout(timer); lines.close(); }
  };
  try { return { ...await ready, stop }; }
  catch (error) { await stop().catch(() => {}); throw error; }
}

async function httpFixture(handle) {
  const server = http.createServer((req, res) => {
    Promise.resolve(handle(req, res)).catch(() => { res.writeHead(500); res.end(); });
  });
  await new Promise((yes, no) => { server.once("error", no); server.listen(0, "127.0.0.1", yes); });
  return { url: "http://127.0.0.1:" + server.address().port, stop: () => new Promise(resolveClose => {
    server.close(resolveClose);
    server.closeAllConnections();
  }) };
}

async function getJson(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
  assert.equal(response.status, 200, new URL(url).pathname);
  return response.json();
}

async function evidence(daemon, capability) {
  return (await getJson(daemon.anchor + "/v1/evidence?capability=" + encodeURIComponent(capability))).evidence;
}

async function until(read, test) {
  for (let i = 0; i < 100; i++) {
    const result = await read();
    if (test(result)) return result;
    await delay(40);
  }
  assert.fail("a traffic receipt did not reach the expected state");
}

async function publish(daemon, secret) {
  const sdk = [
    "import json,sys", "from chimera_tp.platform.client import ChimeraClient",
    "c=ChimeraClient(app='evidence-fixture',anchor_url=sys.argv[1],auto_register=False)",
    "assert c.available", "print(json.dumps(c.pulse_publish('fixture.message',{'value':sys.argv[2]})))",
  ].join("\n");
  const { stdout } = await run(options.python, ["-B", "-c", sdk, daemon.anchor, secret],
    { cwd: root, timeout: 8000, windowsHide: true });
  const row = JSON.parse(stdout);
  assert.equal(row.ok, true);
  return row.event.seq;
}

async function proxyRequest(proxy, url, bypass = false) {
  return new Promise((done, fail) => {
    const req = http.get(proxy, { path: url, agent: false, headers: bypass ? { "X-Chimera-Bypass": "1" } : {} }, res => {
      const chunks = [];
      res.on("data", part => chunks.push(part));
      res.once("error", fail);
      res.on("end", () => done({ status: res.statusCode, tag: res.headers["x-chimera-membrane"],
        body: Buffer.concat(chunks).toString() }));
    });
    req.once("error", fail);
    req.setTimeout(4000, () => req.destroy(new Error("proxy fixture timeout")));
  });
}

async function verifyPersistence(directory) {
  const program = String.raw`
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import json, sys, time
from chimera_tp.platform.evidence import EvidenceLedger
ledger = EvidenceLedger(Path(sys.argv[1]))
note = ledger.activity_observer("fixture", synthetic=True, ttl_s=0.4, flush_interval_s=0.05)
with patch.object(ledger, "_save_locked", wraps=ledger._save_locked) as writes:
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda n: note("pulse.publish", True, n), range(1, 49)))
    # Assert coalescing without relying on all writes fitting one 50 ms interval.
    count = writes.call_count
    assert 0 < count < 48
    row = ledger.evaluate("pulse")
    assert row["verification_status"] == "verified" and row["sample_count"] == 48
    mtime = ledger.path.stat().st_mtime_ns
    for _ in range(25):
        assert ledger.truth_matrix({"pulse": True})["capabilities"]["pulse"]["receipt_id"] == row["receipt_id"]
    assert ledger.path.stat().st_mtime_ns == mtime
    started = time.monotonic()
    while ledger.evaluate("pulse")["verification_status"] == "verified":
        assert time.monotonic() - started < 2
        time.sleep(.025)
    elapsed = time.monotonic() - started
    assert ledger.evaluate("pulse")["stale"] and ledger.evaluate("pulse")["receipt_id"] == row["receipt_id"]
    note("pulse.publish", True, 49)
    assert ledger.evaluate("pulse")["receipt_id"] != row["receipt_id"]
    ledger.flush_traffic()
    prior = EvidenceLedger(Path(sys.argv[1])).evaluate("pulse")
    assert prior["previous_process"] and prior["verification_status"] == "unverified" and prior["sample_count"] == 49
    print(json.dumps({"concurrent_events": 48, "disk_flushes_for_burst": count, "ttl_s": 0.4,
                      "wait_until_stale_s": round(elapsed, 4), "status_reads": 25,
                      "reads_changed_disk": False, "old_session_verified_after_restart": False,
                      "persisted_events": prior["sample_count"]}))
`;
  const { stdout } = await run(options.python, ["-B", "-c", program, join(directory, "persist")],
    { cwd: root, timeout: 8000, windowsHide: true });
  return JSON.parse(stdout);
}

async function verify(directory) {
  const cleanup = [];
  const secret = "fixture-private-do-not-record-83dc";
  let routeMode = "deliver";
  let upstreamCount = 0;
  try {
    const receiver = await startDaemon(join(directory, "receiver"), "receiver");
    cleanup.push(receiver);
    const upstream = await httpFixture(async (req, res) => {
      if (req.method === "POST" && req.url === "/v1/pulse/publish") {
        const chunks = [];
        for await (const part of req) chunks.push(part);
        if (routeMode === "bare-200") { res.end('{"ok":true}'); return; }
        const ack = await fetch(receiver.anchor + req.url, { method: "POST", body: Buffer.concat(chunks),
          headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(2500) });
        res.writeHead(ack.status);
        res.end(await ack.text());
        return;
      }
      upstreamCount++;
      const status = req.url.startsWith("/unavailable") ? 503 : 200;
      res.writeHead(status, { "Cache-Control": status === 200 ? "max-age=60" : "no-store" });
      res.end(status === 200 ? secret : "unavailable");
    });
    cleanup.push(upstream);
    const sender = await startDaemon(join(directory, "sender"), "sender", upstream.url);
    cleanup.push(sender);
    const start = await evidence(sender, "pulse");
    for (const path of ["/api/health", "/.well-known/chimera.json", "/v1/pulse", "/v1/evidence"]) {
      await getJson(sender.anchor + path);
    }
    assert.deepEqual(await evidence(sender, "pulse"), start);
    const seq = await publish(sender, secret);
    const delivered = await until(() => evidence(sender, "pulse.relay"),
      row => row?.metrics?.sequence === seq && row.verification_status === "verified");
    const subscriber = await getJson(receiver.anchor + "/v1/pulse/events?topic=fixture.message");
    assert.equal(subscriber.events.some(event => event.origin === "sender" && event.payload.value === secret), true);
    routeMode = "bare-200";
    const failedSeq = await publish(sender, secret);
    const failed = await until(() => evidence(sender, "pulse.relay"),
      row => row?.metrics?.sequence === failedSeq && row.verification_status === "unverified");
    assert.equal(failed.last_verified_at, delivered.last_verified_at);
    const observed = await evidence(sender, "pulse");
    assert.equal(observed.evidence_source, "fixture_traffic");
    assert.equal(observed.verification_status, "verified");
    assert.notEqual(observed.receipt_id, failed.receipt_id);

    const url = upstream.url + "/data?q=" + secret;
    const beforeEgress = await evidence(sender, "egress_membrane");
    assert.deepEqual(await proxyRequest(sender.proxy, url), { status: 200, tag: "MISS", body: secret });
    const ok = await until(() => evidence(sender, "egress_membrane"), row => row?.metrics?.operation === "egress.forward");
    assert.equal(ok.sample_count, beforeEgress.sample_count + 1);
    assert.equal(ok.evidence_source, "fixture_traffic");
    assert.equal((await proxyRequest(sender.proxy, url)).tag, "HIT");
    assert.deepEqual(await evidence(sender, "egress_membrane"), ok);
    assert.equal((await proxyRequest(sender.proxy, upstream.url + "/unavailable", true)).status, 503);
    const refused = await until(() => evidence(sender, "egress_membrane"), row => row?.metrics?.http_status === 503);
    assert.equal(refused.verification_status, "unverified");
    assert.equal((await proxyRequest(sender.proxy, url)).tag, "HIT");
    assert.deepEqual(await evidence(sender, "egress_membrane"), refused);
    assert.deepEqual(await proxyRequest(sender.proxy, url, true), { status: 200, tag: "BYPASS", body: secret });
    const recovered = await until(() => evidence(sender, "egress_membrane"),
      row => row?.sample_count === refused.sample_count + 1 && row.verification_status === "verified");
    assert.equal(upstreamCount, 3);
    const matrix = await getJson(sender.anchor + "/v1/truth-matrix");
    assert.equal(matrix.capabilities.egress_membrane.basis, "fixture_traffic");
    assert.equal(matrix.capabilities["pulse.relay"].basis, "unverified");
    assert.equal(JSON.stringify(matrix).includes(secret), false);
    const entries = await getJson(sender.anchor + "/v1/evidence");
    assert.equal(JSON.stringify(entries).includes(secret), false);
    return { isolated_daemons: 2, daemon_wired_without_fixture: sender.native_wiring && receiver.native_wiring,
      heartbeat_changed_pulse: false, sdk_publish_count: 2, receiver_observed_first_payload: true,
      later_bare_200_confirmed_relay: false, cache_hits_refreshed_evidence: false, upstream_http_requests: upstreamCount,
      independent_egress_responses: [200, 200, 503, 200, 200], secret_present_in_evidence: false,
      ledger_expiry_and_storage: await verifyPersistence(directory),
      selected_receipts: { relay_delivered: delivered, relay_failed: failed, egress_ok: ok, egress_failed: refused, egress_recovered: recovered } };
  } finally {
    for (const service of cleanup.reverse()) await service.stop();
  }
}

const directory = await mkdtemp(join(tmpdir(), "chimera-traffic-evidence-"));
let report;
try { report = await verify(directory); }
finally { await rm(directory, { recursive: true, force: true }); }
await assert.rejects(access(directory), { code: "ENOENT" });
const hashes = {};
for (const file of ["chimera_tp/platform/evidence.py", "chimera_tp/platform/pulse_bus.py",
  "chimera_tp/platform/egress_membrane.py", "chimera_tp/platform/substrate.py",
  "scripts/verify_evidence_traffic.mjs", "tests/test_evidence_traffic.py"]) {
  hashes[file] = createHash("sha256").update(await readFile(join(root, file))).digest("hex");
}
const evidenceFile = { schema: "chimera.traffic-verification/1", verified_utc: new Date().toISOString(),
  scope: "Real local HTTP with synthetic events and responses, two ephemeral daemons", ...report,
  temporary_state_removed: true, source_sha256: hashes };
if (options.out) await writeFile(resolve(options.out), JSON.stringify(evidenceFile, null, 2) + "\n");
console.log(JSON.stringify({ verified: true, wired: report.daemon_wired_without_fixture,
  upstream_http_requests: report.upstream_http_requests, sdk_publish_count: report.sdk_publish_count }));
