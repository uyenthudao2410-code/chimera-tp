import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sha = data => createHash("sha256").update(data).digest("hex");

function invoke(args, env, expectedExit = 0) {
  const started = performance.now();
  return new Promise((accept, reject) => {
    const child = execFile("python", args, { cwd: root, env, windowsHide: true, timeout: 40000,
      encoding: "utf8", maxBuffer: 512 * 1024 }, (error, stdout, stderr) => {
      const code = error?.code ?? 0;
      if (code !== expectedExit) {
        reject(new Error("Expected " + expectedExit + ", got " + code + ": " + stderr + stdout.slice(-1000)));
        return;
      }
      accept({ receipt: JSON.parse(stdout), pid: child.pid, wall_ms: Math.round(performance.now() - started) });
    });
  });
}

const fixture = [
  "import os, subprocess, sys, time, uuid",
  "from pathlib import Path",
  "markers = Path(os.environ['SWARM_TEST_MARKERS'])",
  "if sys.argv[1] == 'build':",
  "    token = uuid.uuid4().hex",
  "    (markers / token).write_text(str(Path.cwd()), encoding='utf-8')",
  "    time.sleep(1.2)",
  "    source = Path('source.txt').read_bytes()",
  "    Path('out.bin').write_bytes(b'win-fixture\\n' + source + b'\\n' + os.environ['SWARM_TEST_FLAVOR'].encode())",
  "elif sys.argv[1] == 'noisy':",
  "    sys.stdout.buffer.write(b'A' * 300000 + b'end-out')",
  "    sys.stderr.buffer.write(b'B' * 300000 + b'end-err')",
  "elif sys.argv[1] == 'oversize':",
  "    Path('over.bin').write_bytes(b'x' * (4 * 1024 * 1024 + 1))",
  "elif sys.argv[1] == 'fail':",
  "    raise SystemExit(29)",
  "elif sys.argv[1] == 'timeout':",
  "    subprocess.Popen([sys.executable, '-I','-B','-S',__file__,'grandchild'])",
  "    time.sleep(30)",
  "elif sys.argv[1] == 'grandchild':",
  "    (markers / 'spawned.pid').write_text(str(os.getpid()))",
  "    time.sleep(2.5)",
  "    (markers / 'unexpected.txt').write_text('outlived job')",
].join("\n");

const pidProbe = [
  "import ctypes, json, sys",
  "from ctypes import wintypes",
  "api=ctypes.WinDLL('kernel32',use_last_error=True)",
  "api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]",
  "api.OpenProcess.restype=wintypes.HANDLE",
  "api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]",
  "api.WaitForSingleObject.restype=wintypes.DWORD",
  "api.CloseHandle.argtypes=[wintypes.HANDLE]",
  "h=api.OpenProcess(0x100000,False,int(sys.argv[1]))",
  "if not h and ctypes.get_last_error()!=87: raise ctypes.WinError(ctypes.get_last_error())",
  "print(json.dumps(bool(h) and api.WaitForSingleObject(h,0)==258))",
  "if h: api.CloseHandle(h)",
].join("\n");

test("two Windows clients share one verified build and the kernel owns the full process tree",
  { skip: process.platform !== "win32", timeout: 90000 }, async () => {
    const dir = await mkdtemp(join(tmpdir(), "chimera-local-swarm-"));
    const work = join(dir, "workspace");
    const home = join(dir, "profile");
    const markers = join(dir, "invocations");
    const report = { schema: "chimera.local-swarm.acceptance/1", verified_utc: new Date().toISOString() };
    try {
      await Promise.all([work, home, markers].map(d => mkdir(d)));
      await writeFile(join(work, "fixture build.py"), fixture);
      await writeFile(join(work, "source.txt"), "alpha");
      const env = { ...process.env, USERPROFILE: home, SWARM_TEST_MARKERS: markers,
        SWARM_TEST_FLAVOR: "A", PYTHONUTF8: "1" };
      const interpreter = (await invoke(["-I", "-B", "-S", "-c",
        "import sys,json; print(json.dumps(sys.executable))"], env)).receipt;
      const vector = ["-B", "-m", "chimera_tp", "swarm", "--target", "local", "--cwd", work];
      const command = mode => '"' + interpreter + '" -I -B -S "fixture build.py" ' + mode;
      const build = (version, vars = env) => invoke([...vector, "--reuse", version, "--artifact", "out.bin",
        command("build")], vars);
      const counts = () => readdir(markers);
      const a = await Promise.all([build("abi-v1"), build("abi-v1")]);
      assert.deepEqual(a.map(v => v.receipt.delivery).sort(), ["executed", "joined"]);
      assert.equal(a[0].receipt.attempt_id, a[1].receipt.attempt_id);
      assert.equal(a[0].receipt.snapshot, a[1].receipt.snapshot);
      assert.equal(a[0].receipt.key, a[1].receipt.key);
      const firstMarks = await counts();
      assert.equal(firstMarks.length, 1);
      const isolated = await readFile(join(markers, firstMarks[0]), "utf8");
      assert.match(basename(isolated), /^chimera-local-build-/);
      assert.notEqual(isolated, work);
      await assert.rejects(lstat(isolated), { code: "ENOENT" });
      await assert.rejects(lstat(join(work, "out.bin")), { code: "ENOENT" });
      function verify(result, bytes) {
        assert.equal(result.receipt.target, "local");
        assert.equal(result.receipt.state, "completed");
        assert.equal(result.receipt.artifacts["out.bin"].sha256, sha(bytes));
        assert.deepEqual(Buffer.from(result.receipt.artifacts["out.bin"].base64, "base64"), bytes);
      }
      const oracle = (source, flavor) => Buffer.from("win-fixture\n" + source + "\n" + flavor, "utf8");
      a.forEach(v => verify(v, oracle("alpha", "A")));
      const hit = await build("abi-v1");
      assert.equal(hit.receipt.delivery, "cached");
      assert.equal(hit.receipt.attempt_id, a[0].receipt.attempt_id);
      assert.equal((await counts()).length, 1);
      const dirty = Buffer.from("công trình ✓");
      await writeFile(join(work, "source.txt"), dirty);
      const modified = await build("abi-v1");
      verify(modified, oracle(dirty.toString(), "A"));
      const flavor = await build("abi-v1", { ...env, SWARM_TEST_FLAVOR: "B" });
      verify(flavor, oracle(dirty.toString(), "B"));
      const abi = await build("abi-v2");
      verify(abi, oracle(dirty.toString(), "A"));
      assert.equal(new Set([a[0], modified, flavor, abi].map(v => v.receipt.key)).size, 4);
      assert.equal((await counts()).length, 4);
      const rejected = await invoke([...vector, "--require-io-cap", command("build")], env, 75);
      assert.equal(rejected.receipt.error, "io_cap_unavailable");
      assert.equal((await counts()).length, 4);
      const noise = (await invoke([...vector, command("noisy")], env)).receipt;
      assert.equal(noise.stdout.length, 12000);
      assert.equal(noise.stderr.length, 4000);
      assert.ok(noise.stdout.endsWith("end-out") && noise.stderr.endsWith("end-err"));
      const large = (await invoke([...vector, "--artifact", "over.bin", command("oversize")], env, 1)).receipt;
      assert.equal(large.error, "artifact_return_limit");
      assert.equal(large.artifacts, undefined);
      const failed = (await invoke([...vector, command("fail")], env, 1)).receipt;
      assert.equal(failed.exit_code, 29);
      const aborted = (await invoke([...vector, "--timeout", "2", command("timeout")], env, 1)).receipt;
      assert.equal(aborted.error, "timeout");
      const grandchild = await readFile(join(markers, "spawned.pid"), "utf8");
      assert.equal((await invoke(["-I", "-B", "-S", "-c", pidProbe, grandchild], env)).receipt, false);
      await assert.rejects(lstat(join(markers, "unexpected.txt")), { code: "ENOENT" });
      Object.assign(report, {
        clients: a.map(v => ({ pid: v.pid, wall_ms: v.wall_ms, delivery: v.receipt.delivery,
          attempt_id: v.receipt.attempt_id, snapshot: v.receipt.snapshot, key: v.receipt.key })),
        result_sha256: a[0].receipt.artifacts["out.bin"].sha256, independent_invocations_first_pair: 1,
        cached_wall_ms: hit.wall_ms, independent_invocations_after_source_and_env_changes: 4,
        dirty_bytes_match: true, separate_environment_keys: true, workspace_output_untouched: true,
        caps: { hard_io: rejected.receipt.error, stdout_bytes: noise.stdout.length, stderr_bytes: noise.stderr.length,
          oversized_artifact: large.error }, timeout: { state: aborted.state, error: aborted.error,
          confirmed_grandchild_exited_on_return: true }, command_error_preserved: failed.exit_code,
      });
    } finally {
      assert.equal(dirname(resolve(dir)), resolve(tmpdir()));
      assert.match(basename(dir), /^chimera-local-swarm-/);
      await rm(dir, { recursive: true, force: false });
    }
    await assert.rejects(lstat(dir), { code: "ENOENT" });
    if (process.env.CHIMERA_LOCAL_SWARM_EVIDENCE) {
      const output = resolve(process.env.CHIMERA_LOCAL_SWARM_EVIDENCE);
      assert.equal(relative(root, output).replaceAll("\\", "/"), "tasks/local_swarm_verification.json");
      report.fixture_removed = true;
      const files = ["chimera_tp/platform/local_build.py", "chimera_tp/platform/windows_build_job.py",
        "chimera_tp/platform/guarded_build.py", "tests/test_local_swarm.mjs"];
      report.source_sha256 = Object.fromEntries(await Promise.all(files.map(async f => [f, sha(await readFile(join(root, f)))])));
      await writeFile(output, JSON.stringify(report, null, 2) + "\n");
    }
  });
