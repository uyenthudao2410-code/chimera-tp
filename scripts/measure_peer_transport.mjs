/** Compare bounded SHA-256 receipts using existing SSH and PHANTOM connections. */
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { once } from "node:events";
import { createHash, randomBytes } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import http from "node:http";
import { isIP } from "node:net";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { promisify, parseArgs } from "node:util";
import { setTimeout as sleep } from "node:timers/promises";

const execute = promisify(execFile);
const worker = fileURLToPath(new URL("./peer_transport_worker.py", import.meta.url));
const { values } = parseArgs({ options: {
  out: { type: "string" }, rounds: { type: "string", default: "6" },
  python: { type: "string", default: "python" },
} });
const rounds = Number(values.rounds);
assert.ok(Number.isInteger(rounds) && rounds >= 1 && rounds <= 12);
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const now = () => Number(process.hrtime.bigint()) / 1e6;
const tick = start => Math.round((now() - start) * 1000) / 1000;
const sshArgs = ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
  "-o", "UpdateHostKeys=no", "-o", "ConnectTimeout=4", "-o", "ClearAllForwardings=yes"];
const options = { timeout: 12000, maxBuffer: 1024 * 1024, windowsHide: true };
const summary = list => {
  assert.ok(list.length);
  const sorted = [...list].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return { n: list.length, median: list.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2,
    p95: sorted[Math.ceil(sorted.length * 0.95) - 1], min: sorted[0], max: sorted.at(-1) };
};

async function getLocal(port, path) {
  return new Promise((done, fail) => {
    const request = http.get({ hostname: "127.0.0.1", port, path, agent: false }, response => {
      let text = "";
      response.setEncoding("utf8");
      response.on("data", data => {
        text += data;
        if (text.length > 512000) request.destroy(new Error("oversized endpoint"));
      });
      response.on("error", fail);
      response.on("end", () => {
        try {
          assert.equal(response.statusCode, 200);
          done(JSON.parse(text));
        } catch (err) { fail(err); }
      });
    });
    request.setTimeout(5000, () => request.destroy(new Error("beacon request timed out")));
    request.on("error", fail);
  });
}

async function routes() {
  const [home, state, profile] = await Promise.all([
    getLocal(9780, "/.well-known/chimera.json"), getLocal(9780, "/api/phantom/status"),
    execute("ssh", ["-G", "svhome"], options),
  ]);
  assert.equal(home.node_name, "win-desktop");
  assert.equal(home.peer_name, "svhome");
  assert.ok(isIP(home.peer_ipv4));
  const hostname = /^hostname\s+([^\s]+)\s*$/m.exec(profile.stdout)?.[1];
  assert.equal(hostname, home.peer_ipv4);
  const client = state.client;
  const direct = client.connected === true && client.mode === "PHANTOM_5MS_DIRECT" && !client.pong_stale;
  const info = { measured_utc: new Date().toISOString(), ssh_alias: "svhome", peer_ip: hostname,
    phantom: { connected: client.connected, mode: client.mode, rtt_ms: client.direct_rtt_ms,
      pong_age_s: client.last_pong_age_s, pong_stale: client.pong_stale, listeners: client.listeners,
      reconnects: client.reconnect_count, rx_bytes: client.rx_bytes, tx_bytes: client.tx_bytes } };
  if (direct) {
    for (const port of ["22", "9780"]) {
      assert.ok(Number.isInteger(client.listeners[port]) && client.listeners[port] > 0 && client.listeners[port] <= 65535);
    }
    const remote = await getLocal(client.listeners["9780"], "/.well-known/chimera.json");
    assert.equal(remote.node_name, home.peer_name);
    info.tunnelled_peer = { node_name: remote.node_name, pid: remote.pid, version: remote.version, os: remote.os };
  }
  try {
    const ping = await execute("tailscale", ["ping", "--c=3", "--until-direct=false", "--timeout=2s", hostname], options);
    info.tailscale = ping.stdout.trim().split(/\r?\n/).map(line => {
      const through = /via (DERP\([\w-]+\))/.exec(line);
      const ms = / in ([\d.]+)ms/.exec(line);
      return { route: through?.[1] ?? (ms && / via /.test(line) ? "direct" : "unknown"),
        rtt_ms: ms ? Number(ms[1]) : null };
    });
  } catch (err) { info.tailscale = [{ route: "unknown", exit: String(err.code) }]; }
  return info;
}

function session(route, info, pack) {
  const started = now();
  const local = route === "windows";
  const direct = route === "phantom";
  if (direct) assert.ok(info.tunnelled_peer);
  const args = local ? ["-I", "-B", "-S", "-u", worker, "--local"] : [
    ...sshArgs, ...(direct ? ["-o", "HostName=127.0.0.1", "-o", "HostKeyAlias=" + info.peer_ip,
      "-p", String(info.phantom.listeners["22"])] : []), "svhome", pack.shell,
  ];
  const proc = spawn(local ? values.python : "ssh", args, { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
  const lines = createInterface({ input: proc.stdout, crlfDelay: Infinity })[Symbol.asyncIterator]();
  let stderr = "";
  proc.stderr.setEncoding("utf8").on("data", part => { stderr = (stderr + part).slice(-1200); });
  proc.stdin.on("error", () => {});
  const closed = once(proc, "close");
  closed.catch(() => {});
  const watchdog = setTimeout(() => proc.kill(), 40000).unref();
  closed.finally(() => clearTimeout(watchdog)).catch(() => {});
  if (!local) proc.stdin.write(pack.base64 + "\n");
  async function read(type) {
    const record = await lines.next();
    if (record.done) throw new Error("worker ended before " + type + " " + stderr.slice(-400));
    assert.ok(record.value.length < 8192);
    const event = JSON.parse(record.value);
    if (event.type === "failed") throw Object.assign(new Error(event.reason), { refusal: event.reason });
    assert.equal(event.type, type);
    return event;
  }
  return { proc, started, read, closed,
    async end() {
      proc.stdin.end();
      const tail = await read("tail");
      const [code] = await closed;
      assert.equal(code, 0);
      return tail;
    },
    async abort() {
      proc.stdin.destroy();
      if (proc.exitCode === null) proc.kill();
      await closed.catch(() => {});
    } };
}

async function sendFrame(s, fixture, pos) {
  assert.ok(s.proc.exitCode === null && s.proc.stdin.writable, "session is closed");
  const id = randomBytes(12).toString("hex");
  const line = JSON.stringify({ id, payload: fixture.data.toString("base64") }) + "\n";
  const start = now();
  s.proc.stdin.write(line);
  const frame = await s.read("digest");
  const received = now();
  assert.equal(frame.id, id);
  assert.equal(frame.position, pos);
  assert.equal(frame.sha256, fixture.sha256);
  return { warm_ms: received - start, elapsed_from_start_ms: received - s.started, worker_check_ms: frame.check_us / 1000,
    worker_sha_ms: frame.sha_us / 1000, all_other_ms: received - start - (frame.sha_us + frame.check_us) / 1000,
    request_bytes: Buffer.byteLength(line), sha256: frame.sha256, service_p95_ms: frame.service_ms };
}

async function trial(route, info, pack, inputs, forcedBreak = false) {
  const began = now();
  let deferrals = 0;
  for (;;) {
    const s = session(route, info, pack);
    try {
      const ready = await s.read("ready");
      const setup_ms = tick(s.started);
      assert.equal(ready.os, route === "windows" ? "Windows" : "Linux");
      if (route !== "windows") {
        assert.equal(ready.host, "svhome");
        assert.ok(ready.guard.limits_verified && ready.guard.cgroup.endsWith("/chimera-peer-guest.service"));
        assert.ok(ready.guard.services.length > 0 && ready.guard.disk_reserve_mib >= 14306);
      }
      const frames = [];
      for (const [i, input] of inputs.entries()) frames.push(await sendFrame(s, input, i));
      if (forcedBreak) {
        await s.abort();
        await assert.rejects(sendFrame(s, inputs[0], 1), /session is closed/);
        return { setup_ms, frames, host: ready.host, interrupted_session_exited: true };
      }
      const tail = await s.end();
      assert.equal(tail.pid, ready.pid);
      return { setup_ms, closed_ms: tick(s.started), deferrals, host: ready.host, receiver_pid: ready.pid,
        python: ready.python, admission: ready.guard, frames,
        rss_at_ready: ready.rss_bytes, rss_at_tail: tail.rss_bytes };
    } catch (err) {
      await s.abort();
      if (err.refusal !== "guest_slot_busy" || now()-began > 22000) throw err;
      deferrals++;
      await sleep(900 + Math.random() * 700);
    }
  }
}

function inputs() {
  return Array.from({ length: 2 }, () => {
    const data = randomBytes(400);
    return { data, sha256: sha(data) };
  });
}

function aggregate(rows, route) {
  const measurements = rows.map(row => row.arms[route]).filter(Boolean);
  const extract = fn => summary(measurements.map(fn));
  return { setup_ms: extract(m => m.setup_ms),
    fresh_first_receipt_ms: extract(m => m.frames[0].elapsed_from_start_ms),
    warm_receipt_ms: extract(m => m.frames[1].warm_ms),
    warm_guard_ms: extract(m => m.frames[1].worker_check_ms),
    warm_sha_ms: extract(m => m.frames[1].worker_sha_ms),
    warm_remaining_ms: extract(m => m.frames[1].all_other_ms),
    worker_tail_rss_mib: extract(m => m.rss_at_tail.current / 2**20),
    worker_peak_rss_mib: extract(m => m.rss_at_tail.peak / 2**20) };
}

async function main() {
  const status = await routes();
  const {stdout} = await execute(values.python, ["-I", "-B", "-S", worker, "--bundle"], options);
  const pack = JSON.parse(stdout);
  assert.equal(sha(Buffer.from(pack.base64, "base64")), pack.package_sha256);
  const orders = [["windows", "alias", "phantom"], ["alias", "phantom", "windows"], ["phantom", "windows", "alias"],
    ["phantom", "alias", "windows"], ["alias", "windows", "phantom"], ["windows", "phantom", "alias"]];
  const rows = [];
  for (let i = 0; i < rounds; i++) {
    const pair = inputs(), order = orders[i % 6].filter(r => r !== "phantom" || status.tunnelled_peer);
    const arms = {};
    for (const route of order) arms[route] = await trial(route, status, pack, pair);
    rows.push({ round: i+1, order, expected_sha256: pair.map(x => x.sha256), arms });
  }
  const totals = Object.fromEntries(Object.keys(rows[0].arms).map(route => [route, aggregate(rows, route)]));
  let fallback = null;
  if (status.tunnelled_peer) {
    const fixture = inputs()[0];
    const direct = await trial("phantom", status, pack, [fixture], true);
    const alias = await trial("alias", status, pack, [fixture]);
    fallback = { explicit_pure_retry: true, fault: "killed only the benchmark SSH client",
      digest_matched: direct.frames[0].sha256 === alias.frames[0].sha256, sha256: fixture.sha256,
      interrupted_session_exited: direct.interrupted_session_exited, fresh_receiver_pid: alias.receiver_pid,
      warm_session_reused_after_disconnect: false, retry_ms: alias.frames[0].elapsed_from_start_ms };
  }
  const end = await routes();
  const command = "systemctl --user show chimera-peer-guest.service --property=ActiveState,SubState,MainPID";
  const after = await execute("ssh", [...sshArgs, "svhome", command], options);
  const result = { schema: "chimera.peer-transport-comparison/1", recorded_utc: new Date().toISOString(),
    scope: "Fixed 400-byte SHA-256 over authenticated stdio. One measured remote reservation per process and a full peer_guard recheck for each frame. Diagnostic only.",
    definitions: { cold: "From spawning Python/SSH to first verified digest. Includes strict host authentication, module transfer, systemd, admission and first guard check on the peer.",
      warm: "From writing the second digest request to receiving its full line on an already admitted process; each request still probes actual loopback services.",
      remaining: "Entire warm round trip minus worker guard and SHA time; includes framing, queues, scheduling, pipes, network and client parsing.",
      tail_rss: "Current resident bytes of the hash worker read after stdin EOF, before teardown. Peak from VmHWM or PeakWorkingSetSize. Excludes SSH and daemon." },
    content: { operation: "sha256", bytes_per_payload: 400, independent_oracle: "Node.js SHA-256 against CPython hashlib",
      worker_package_sha256: pack.package_sha256, package_bytes: pack.package_bytes, module_sha256: pack.sources,
      harness_sha256: sha(await readFile(fileURLToPath(import.meta.url))) },
    before: status, rows, summary: totals, after: end, disconnect_recovery: fallback,
    guest_unit_at_end: Object.fromEntries(after.stdout.trim().split(/\r?\n/).map(l => l.split("="))),
    limitations: ["No CAS lookup, build execution, durable queue, daemon activation, or production traffic promotion in this fixture.",
      "A retained short-lived session occupies the one guest slot until closed. RSS belongs to workers and service probes only as specified.",
      "The two frame payloads in a session are different random 400-byte messages, matched exactly across routes. No compression or cache hit is credited."] };
  if (totals.phantom) {
    result.paired = { cold_alias_to_warm_direct_speedup: summary(rows.map(r =>
      r.arms.alias.frames[0].elapsed_from_start_ms / r.arms.phantom.frames[1].warm_ms)),
      warm_direct_under_25_ms: rows.filter(r => r.arms.phantom.frames[1].warm_ms < 25).length,
      cold_alias_to_warm_direct_at_least_180x: rows.filter(r =>
        r.arms.alias.frames[0].elapsed_from_start_ms / r.arms.phantom.frames[1].warm_ms >= 180).length };
  }
  if (values.out) await writeFile(resolve(values.out), JSON.stringify(result, null, 2)+"\n", {flag:"wx"});
  console.log(JSON.stringify({rounds, routes:Object.keys(totals),
    medians_ms: Object.fromEntries(Object.entries(totals).map(([route,x])=>[route,
      {cold:x.fresh_first_receipt_ms.median, warm:x.warm_receipt_ms.median}])), paired:result.paired}));
}

main().catch(err => { console.error(err.stack); process.exitCode = 1; });
