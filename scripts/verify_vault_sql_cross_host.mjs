/** Verify the Windows HTTP snapshot route and a guarded Linux replica using a private SSH socket. */
import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";

const exec = promisify(execFile);
const root = fileURLToPath(new URL("../", import.meta.url));
const trial = fileURLToPath(new URL("./vault_sql_cross_host.py", import.meta.url));
const { values } = parseArgs({ options: {
  python: { type: "string", default: "python" },
  peer: { type: "string", default: "svhome" },
  out: { type: "string" },
} });
const sshOptions = ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
  "-o", "UpdateHostKeys=no", "-o", "ConnectTimeout=6"];
const execOptions = { cwd: root, windowsHide: true, timeout: 160000, maxBuffer: 2 * 1024 * 1024 };
const phases = ["cold", "damaged", "delta", "unchanged", "stale"];
const safePeer = /^[A-Za-z0-9][\w.-]{0,100}$/u;
assert.ok(safePeer.test(values.peer));

const socketControl = `
import json,os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1])
base=pathlib.Path("/run/user") / str(os.getuid())
if p.parent != base or base.stat().st_mode & 0o077:
    raise RuntimeError("expected private runtime directory")
x=p.lstat()
if not stat.S_ISSOCK(x.st_mode) or x.st_uid != os.getuid():
    raise RuntimeError("invalid forwarded socket")
print(json.dumps({"event":"ready","private_directory":True,"socket_mode":oct(stat.S_IMODE(x.st_mode))}),flush=True)
try:
    sys.stdin.readline()
finally:
    current=p.lstat()
    if (current.st_dev,current.st_ino) != (x.st_dev,x.st_ino):
        raise RuntimeError("private socket changed identity")
    p.unlink()
print(json.dumps({"event":"closed","socket_removed":not p.exists()}),flush=True)
`;

function channel(program, args) {
  const proc = spawn(program, args, { windowsHide: true, cwd: root, stdio: ["pipe", "pipe", "pipe"] });
  const lines = createInterface({ input: proc.stdout, crlfDelay: Infinity })[Symbol.asyncIterator]();
  let stderr = "";
  proc.stderr.setEncoding("utf8").on("data", data => { stderr = (stderr + data).slice(-2000); });
  proc.stdin.on("error", () => {});
  const ended = new Promise((ok, fail) => {
    proc.once("error", fail);
    proc.once("close", (code, signal) => ok({ code, signal }));
  });
  ended.catch(() => {});
  const hardLimit = setTimeout(() => proc.kill(), 170000);
  hardLimit.unref();
  ended.then(() => clearTimeout(hardLimit), () => clearTimeout(hardLimit));
  async function event(expected) {
    const { done, value } = await lines.next();
    if (done) throw new Error(program + " closed before " + expected + ". " + stderr);
    const data = JSON.parse(value);
    assert.equal(data.event, expected);
    return data;
  }
  async function stop(command, expected) {
    proc.stdin.end(command + "\n");
    const value = await event(expected);
    const status = await ended;
    if (status.code !== 0) throw new Error(program + " failed. " + stderr);
    return value;
  }
  async function abort() {
    if (proc.exitCode === null) proc.stdin.end();
    const limit = setTimeout(() => proc.kill(), 4500);
    try { await ended; } finally { clearTimeout(limit); }
  }
  return { event, stop, abort };
}

async function run() {
  assert.equal(process.platform, "win32", "the source acceptance host must be Windows");
  const peer = values.peer;
  const { stdout } = await exec("ssh", [...sshOptions, peer, "id -u"], execOptions);
  const uid = stdout.trim();
  assert.match(uid, /^\d{1,10}$/u);
  const name = "chimera-vault-" + randomBytes(12).toString("hex") + ".sock";
  const path = "/run/user/" + uid + "/" + name;
  const modules = ["chimera_tp/platform/substrate.py", "chimera_tp/platform/vault_sql.py",
    "chimera_tp/platform/vault_sql_pages.py", "chimera_tp/platform/agent_workspace.py",
    "chimera_tp/platform/peer_guard.py", "scripts/vault_sql_cross_host.py",
    "scripts/verify_vault_sql_cross_host.mjs"];
  async function sourceHashes() {
    const entries = await Promise.all(modules.map(async file =>
      [file, createHash("sha256").update(await readFile(join(root, file))).digest("hex")]));
    return Object.fromEntries(entries);
  }
  const hashes = await sourceHashes();
  const source = channel(values.python, ["-I", "-B", "-S", "-u", trial, "--origin"]);
  let tunnel;
  try {
    const ready = await source.event("ready");
    assert.equal(ready.os, "Windows");
    assert.match(ready.token, /^[a-f0-9]{32}$/u);
    assert.ok(Number.isInteger(ready.port) && ready.port >= 1 && ready.port <= 65535);
    const encoded = Buffer.from(socketControl).toString("base64");
    const bootstrap = `python3 -I -B -S -u -c "import base64;exec(base64.b64decode('${encoded}'))" '${path}'`;
    tunnel = channel("ssh", [...sshOptions, "-o", "ExitOnForwardFailure=yes", "-R",
      path + ":127.0.0.1:" + ready.port, peer, bootstrap]);
    const connection = await tunnel.event("ready");
    assert.equal(connection.private_directory, true);
    const job = await exec(values.python, ["-I", "-B", "-S", trial, "--dispatch", peer, path, ready.token], execOptions);
    const transfer = JSON.parse(job.stdout);
    assert.ok(transfer.stage_removed && transfer.linux.temporary_replica_removed && transfer.worker.guard_limits_verified);
    assert.equal(transfer.linux.host, peer);
    assert.equal(transfer.linux.os, "Linux");
    const closed = await tunnel.stop("finish", "closed");
    assert.ok(closed.socket_removed);
    const done = await source.stop("finish", "finished");
    assert.ok(done.temporary_origin_removed);
    const origin = done.origin;
    assert.deepEqual(origin.phases, phases);
    assert.ok(origin.oracle.transaction_open && origin.oracle.wal_bytes > 0);
    assert.equal(origin.oracle.uncommitted_revision, 2);

    const receipts = {};
    for (const phase of phases) {
      const linux = transfer.linux.phases[phase];
      const actual = origin.responses.filter(row => row.phase === phase);
      assert.deepEqual(actual.map(({ body_bytes, body_sha256 }) => ({ body_bytes, body_sha256 })), linux.responses);
      assert.ok(actual.length >= 1);
      const oracle = ["cold", "damaged"].includes(phase) ? origin.oracle.cold : origin.oracle.committed;
      assert.deepEqual(linux.after, oracle, "online independent SQLite backup differs at " + phase);
      receipts[phase] = { ...linux, responses: actual,
        http_json_response_body_bytes: actual.reduce((n, r) => n + r.body_bytes, 0) };
    }
    assert.equal(receipts.cold.receipt.mode, "full");
    assert.ok(receipts.cold.receipt.parts >= 2);
    assert.equal(receipts.damaged.receipt.mode, "rejected");
    assert.equal(receipts.delta.receipt.mode, "delta");
    assert.equal(receipts.delta.receipt.changed_pages, 1);
    assert.equal(receipts.unchanged.receipt.changed_pages, 0);
    assert.equal(receipts.unchanged.receipt.mode, "unchanged");
    assert.equal(receipts.stale.before.selected_rev, 77);
    assert.equal(receipts.stale.receipt.mode, "full");
    assert.equal(receipts.stale.responses[0].since, receipts.stale.before.sha256);
    assert.deepEqual(await sourceHashes(), hashes, "implementation changed while measuring");
    return { schema: "chimera.vault-sql-cross-host/1", verified_utc: new Date().toISOString(),
      source: { os: origin.os, host: origin.host, sqlite: origin.sqlite },
      receiver: { os: transfer.linux.os, host: transfer.linux.host, sqlite: transfer.linux.sqlite },
      transport: "Real HTTP requests from the gated Linux replica across a private reverse SSH stream to the Windows production snapshot handler on isolated loopback ports.",
      byte_scope: "Identical HTTP JSON response bodies were measured and SHA-256 checked at both ends. Headers, SSH framing and setup traffic are excluded.",
      elapsed_scope: "sync_from_peer on Linux, including snapshot generation on Windows, all HTTP requests, receive verification and publication. The oracle and initial job/SSH setup are measured separately or excluded.",
      oracle: origin.oracle, phases: receipts, guarded_job: transfer.worker, socket_private: true,
      socket_removed: true, temporary_source_and_replica_removed: true, source_sha256: hashes };
  } finally {
    if (tunnel) await tunnel.abort();
    await source.abort();
  }
}

const report = await run();
if (values.out) {
  const path = resolve(values.out);
  const stage = await mkdtemp(join(dirname(path), ".vault-result-"));
  try {
    await writeFile(join(stage, basename(path)), JSON.stringify(report, null, 2) + "\n");
    await rename(join(stage, basename(path)), path);
  } finally {
    await rm(stage, { recursive: true, force: true });
  }
}
console.log(JSON.stringify(Object.fromEntries(Object.entries(report.phases).map(
  ([phase, row]) => [phase, { mode: row.receipt.mode, bytes: row.http_json_response_body_bytes, ms: row.elapsed_ms }])),
null, 2));
