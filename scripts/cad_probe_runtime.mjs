import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { access, open, readFile } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { quantile } from "./cad_frame_metrics.mjs";

// On Windows libuv's hrtime uses QueryPerformanceCounter, expressed in ns.
export const qpcMs = () => Number(process.hrtime.bigint()) / 1e6;
export const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");

export async function exists(path) {
  try { await access(path); return true; } catch (e) { if (e.code === "ENOENT") return false; throw e; }
}

export function child(file, args, { cwd, timeout = 0, signal, input = false, stdoutFd = null } = {}) {
  signal?.throwIfAborted();
  const started = qpcMs();
  const p = spawn(file, args, { cwd, windowsHide: true, shell: false, stdio: [input ? "pipe" : "ignore", stdoutFd ?? "pipe", "pipe"] });
  let stdout = "", stderr = "", failure;
  const collect = (output, chunk) => (output + chunk).slice(-262144);
  p.stdout?.setEncoding("utf8").on("data", chunk => { stdout = collect(stdout, chunk); });
  p.stderr.setEncoding("utf8").on("data", chunk => { stderr = collect(stderr, chunk); });
  function stop(reason) {
    failure = reason;
    if (p.exitCode === null && p.pid) {
      if (process.platform === "win32") {
        const killer = spawn("taskkill.exe", ["/PID", String(p.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
        killer.on("error", () => p.kill());
      } else p.kill();
    }
  }
  const onAbort = () => stop("was cancelled");
  signal?.addEventListener("abort", onAbort, { once: true });
  const timer = timeout && setTimeout(() => stop("exceeded its time limit"), timeout);
  let closed = false;
  const done = new Promise((resolve, reject) => {
    p.on("error", reject);
    p.on("close", (code, exitSignal) => {
      closed = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      const ended = qpcMs();
      const result = { code, stdout, stderr, started_qpc_ms: started, ended_qpc_ms: ended, wall_ms: ended - started };
      if (code !== 0 || failure || exitSignal) {
        reject(new Error(file + " " + (failure ?? "exited " + (code ?? exitSignal)) + ": " +
          (stderr.trim() || stdout.trim() || "no diagnostic output").slice(-900)));
      } else resolve(result);
    });
  });
  done.catch(() => {});
  return { process: p, done, get closed() { return closed; } };
}

export async function marker(dir, name, timeout, owner, signal) {
  const limit = qpcMs() + timeout;
  const path = join(dir, name), problem = join(dir, "error.json");
  while (qpcMs() < limit) {
    signal?.throwIfAborted();
    if (await exists(problem)) {
      const err = JSON.parse(await readFile(problem, "utf8"));
      throw new Error("AutoCAD scene: " + err.message + " (line " + err.line + ")");
    }
    if (await exists(path)) return JSON.parse(await readFile(path, "utf8"));
    if (owner.closed) {
      await owner.done;
      throw new Error("AutoCAD control process ended before " + name);
    }
    await sleep(25);
  }
  throw new Error("Timed out waiting for " + name);
}

export async function startCapture(binary, pid, file, seconds) {
  const session = "ChimeraCad_" + randomUUID().replaceAll("-", "");
  const cmd = ["--v2_metrics", "--process_id", String(pid), "--qpc_time_ms", "--session_name", session,
    "--output_stdout", "--no_console_stats", "--timed", String(Math.ceil(seconds)), "--terminate_after_timed"];
  // PresentMon's own --output_file opens the CSV exclusively on Windows. Give
  // it a shared stdout file handle so the first arm can verify delivery live.
  const output = await open(file, "wx");
  let capture;
  try {
    capture = child(binary, cmd, { timeout: (seconds + 15) * 1000, stdoutFd: output.fd });
  } finally {
    await output.close();
  }
  const limit = qpcMs() + 8000;
  while (qpcMs() < limit) {
    if (capture.closed) { await capture.done; throw new Error("ETW collector ended before the workload"); }
    // Wait for positive proof that this exact ETW session is running.
    try {
      await child("logman.exe", ["query", session, "-ets"], { timeout: 2300 }).done;
      return {
        done: capture.done,
        async stop() {
          if (!capture.closed) {
            await child(binary, ["--session_name", session, "--terminate_existing_session"], { timeout: 7000 }).done;
          }
          return capture.done;
        },
      };
    } catch { await sleep(90); }
  }
  if (!capture.closed) {
    await child(binary, ["--session_name", session, "--terminate_existing_session"], { timeout: 7000 }).done.catch(() => {});
  }
  throw new Error("Could not verify active ETW session " + session);
}

export function probeService(url) {
  if (!url) return { async stop() { return null; } };
  let stopping = false;
  const samples = [];
  const run = (async () => {
    while (!stopping) {
      const start = qpcMs();
      let ok = false;
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(1800), redirect: "error" });
        ok = response.ok;
        await response.arrayBuffer();
      } catch { /* include failed requests in the observed error count */ }
      const end = qpcMs();
      samples.push({ start, end, ok });
      if (!stopping) await sleep(Math.max(0, 200 - (end - start)));
    }
  })();
  return {
    async stop(from, until) {
      stopping = true;
      await run;
      const rows = samples.filter(s => s.start >= from && s.end <= until);
      const good = rows.filter(s => s.ok);
      return { endpoint: url, good: good.length, errors: rows.length - good.length,
        p95_ms: quantile(good.map(s => s.end - s.start), 0.95) };
    },
  };
}
