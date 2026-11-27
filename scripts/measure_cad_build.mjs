/** Measure a real AutoCAD viewport while equivalent Windows and Linux jobs execute. */
import { constants } from "node:fs";
import { copyFile, mkdir, mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { setTimeout as sleep } from "node:timers/promises";
import { comparePairs, inspectFrames } from "./cad_frame_metrics.mjs";
import { child, exists, marker, probeService, qpcMs, sha256, startCapture } from "./cad_probe_runtime.mjs";
import { startPeerCapture } from "./cad_peer_capture.mjs";
import { comparePeerPair, peerLimits, reduceArm } from "./cad_peer_metrics.mjs";

const scripts = dirname(fileURLToPath(import.meta.url));
const root = dirname(scripts);
const powerShell = "powershell.exe";
const ps = ["-NoLogo", "-NoProfile", "-NonInteractive"];
const options = {
  "secondary-display": { type: "string" }, "deferred-retries": { type: "string", default: "0" },
  "capture-retries": { type: "string", default: "0" },
  out: { type: "string" }, dwg: { type: "string" }, presentmon: { type: "string" },
  "prog-id": { type: "string", default: "AutoCAD.Application" },
  jobs: { type: "string" }, peer: { type: "string", default: "svhome" }, python: { type: "string", default: "python" },
  "local-build": { type: "string", default: "independent" }, "cpu-quota-pct": { type: "string" },
  pairs: { type: "string", default: "10" }, seconds: { type: "string", default: "30" },
  rounds: { type: "string", default: "240" }, timeout: { type: "string", default: "180" },
  "service-url": { type: "string" }, "service-p95-ms": { type: "string" }, "swap-chain": { type: "string" },
  "check-jobs": { type: "boolean" }, "reference-ssh": { type: "boolean" }, help: { type: "boolean" },
};
const usage = `node scripts/measure_cad_build.mjs preflight [--out NEW_DIR] [--check-jobs]
node scripts/measure_cad_build.mjs peer-preflight --service-p95-ms LIMIT [--out NEW_DIR]
node scripts/measure_cad_build.mjs run --service-p95-ms LIMIT [--out NEW_DIR] [--secondary-display DEVICE]
  [--pairs 10] [--seconds 30] [--rounds 240] [--peer svhome] [--python python] [--cpu-quota-pct 95] [--deferred-retries N] [--capture-retries N]
  [--dwg PATH] [--prog-id AutoCAD.Application] [--presentmon PATH] [--swap-chain 0x...]
  [--service-url http://host/service] [--jobs FILE] [--timeout 180] [--local-build shared|independent]

preflight records the Windows compositor as an ETW instrumentation check. run opens
a separate visible AutoCAD instance with a read-only copy of an Autodesk sample.
One warmup precedes alternating local/remote then remote/local pairs. Keep the
viewport in front. Each condition needs 100 displayed intervals and 20 service
samples per machine during compiler/scene overlap. Default probes read Radar's
health from Windows via an SSH forward and its health and CSS from Linux loopback.
peer-preflight runs one actual local/remote build pair and measures both machines
without AutoCAD or PresentMon. Set the workstation P95 budget before the experiment.

The default workload submits two simultaneous builds of the same four sources.
Windows runs both directly or shares one build with --local-build shared. The guarded
Swarm API coalesces the two Linux requests. Both senders verify the artifact.
--cpu-quota-pct limits only the guarded Linux job to 1..100 percent of one CPU.
Each sender must receive the kernel quota and verified admission in its receipt.
With --deferred-retries, replay an entire deferred pair on the same CAD instance.
Every deferral is recorded, counts against automatic placement, and is followed by a cooldown.
Use --reference-ssh to measure one bare compile per site without the scheduler.
For another build pass a JSON object with "local" and "remote".
Each contains "argv" (a command argument array) and optionally "cwd", relative to
the JSON file. Each must emit one JSON object with input_sha256 and result_sha256
from the actual job. Report compiler_windows_ms as [start,end] pairs in milliseconds
from Windows QueryPerformanceCounter or Linux CLOCK_MONOTONIC. Set compiler_clock to
"windows_qpc" or "linux_monotonic" respectively. The acceptance gate needs these
times independently of input delivery, admission and artifact return.
Outputs include raw PresentMon CSV, the drawing copy, samples and report.json.
The destination directory must be new. No package installation is performed.`;

function numberIn(value, name, min, max, whole = false) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < min || n > max || (whole && !Number.isInteger(n))) {
    throw new Error(name + " must be " + min + ".." + max);
  }
  return n;
}

async function makeOutput(value) {
  if (!value) return mkdtemp(join(tmpdir(), "chimera-cad-"));
  const p = resolve(value);
  await mkdir(p);
  return p;
}

async function defaultDrawing() {
  const base = join(process.env.ProgramFiles || "C:/Program Files", "Autodesk");
  const versions = (await readdir(base)).filter(n => /^AutoCAD \d{4}$/.test(n)).sort().reverse();
  for (const version of versions) {
    const file = join(base, version, "Sample", "Database Connectivity", "Floor Plan Sample.dwg");
    if (await exists(file)) return file;
  }
  throw new Error("No installed Autodesk Floor Plan Sample.dwg; specify --dwg");
}

async function toolPath(value) {
  if (value) return resolve(value);
  if (process.env.PRESENTMON) return resolve(process.env.PRESENTMON);
  const local = join(tmpdir(), "chimera-performance-tools", "PresentMon-2.6.0-x64.exe");
  if (await exists(local)) return local;
  const located = await child("where.exe", ["PresentMon.exe"], { timeout: 2500 }).done.catch(() => null);
  if (located?.stdout.trim()) return located.stdout.trim().split(/\r?\n/)[0];
  throw new Error("Set PRESENTMON or --presentmon to a PresentMon console executable supporting --v2_metrics");
}

async function endpoint(value) {
  if (value) {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      throw new Error("Expected an HTTP service endpoint without embedded credentials");
    }
    return url.href;
  }
  const beacon = await (await fetch("http://127.0.0.1:9780/.well-known/chimera.json", {
    signal: AbortSignal.timeout(2500),
  })).json();
  if (!beacon.peer_ipv4) throw new Error("Specify --service-url; peer discovery returned no address");
  return new URL("/.well-known/chimera.json", "http://" + beacon.peer_ipv4 + ":9780").href;
}

async function configureJobs(a, dir) {
  if (a.jobs) {
    const location = resolve(a.jobs);
    const config = JSON.parse(await readFile(location, "utf8"));
    for (const site of ["local", "remote"]) {
      const job = config[site];
      if (!Array.isArray(job?.argv) || !job.argv.length || !job.argv.every(s => typeof s === "string" && !s.includes("\0"))) {
        throw new Error("A command argument array is required for " + site);
      }
      job.cwd = resolve(dirname(location), job.cwd ?? ".");
    }
    return config;
  }
  const target = join(dir, "input.json");
  const prefix = ["-E", "-B", "-S", join(scripts, "cad_build_job.py")];
  await child(a.python, [...prefix, "prepare", target, "--rounds", String(a.rounds)], { cwd: root, timeout: 15000 }).done;
  if (!a["reference-ssh"]) {
    const pair = ["-E", "-B", "-S", join(scripts, "cad_swarm_job.py")];
    await child(a.python, [...pair, "prepare", target], { cwd: root, timeout: 15000 }).done;
    const local = a["local-build"] === "shared" ? "local-shared" : "local";
    const args = [target, "--peer", a.peer, "--timeout", String(Math.min(300, Math.floor(a.timeout)))];
    const quota = a["cpu-quota-pct"];
    const remoteOptions = quota === undefined ? [] : ["--cpu-quota-pct", String(quota)];
    return {
      local: { cwd: root, argv: [a.python, ...pair, local, ...args] },
      remote: { cwd: root, argv: [a.python, ...pair, "remote", ...args, ...remoteOptions] },
    };
  }
  return Object.fromEntries(["local", "remote"].map(site => [site, { cwd: root,
    argv: [a.python, ...prefix, site, target, "--peer", a.peer, "--timeout", String(a.timeout)] }]));
}

async function runJob(job, timeout, signal) {
  const [exe, ...args] = job.argv;
  const p = await child(exe, args, { cwd: job.cwd, timeout: timeout * 1000, signal }).done;
  const receipt = JSON.parse(p.stdout.trim().replace(/^\uFEFF/, ""));
  const hashes = [receipt.input_sha256, receipt.result_sha256];
  if (!hashes.every(h => typeof h === "string" && /^[0-9a-f]{64}$/i.test(h))) {
    throw new Error("A build receipt must identify the inputs and a verified result with SHA-256");
  }
  return {
    started_qpc_ms: p.started_qpc_ms, ended_qpc_ms: p.ended_qpc_ms, wall_ms: p.wall_ms,
    identity: hashes.map(h => h.toLowerCase()).join(":"), receipt,
  };
}

async function observedArm(a, jobs, site, signal, sceneWindow) {
  const observer = await startPeerCapture(a, signal);
  try {
    const active = runJob(jobs[site], a.timeout, signal);
    const [job, sweep] = await Promise.all([active, sceneWindow?.()]);
    const window = sweep ?? { from_qpc_ms: job.started_qpc_ms, until_qpc_ms: job.ended_qpc_ms };
    const records = await observer.finish();
    const metrics = reduceArm(observer.ready, records, site, job, window, !a.jobs && !a["reference-ssh"]);
    return { site, job, sweep: sweep ?? null, ...metrics };
  } catch (error) {
    await observer.close().catch(() => {});
    throw error;
  }
}

async function peerPreflight(a, dir, info) {
  const jobs = await configureJobs(a, dir);
  const rows = [];
  for (const site of ["local", "remote"]) rows.push(await observedArm(a, jobs, site));
  const [local, remote] = rows;
  const peer = comparePeerPair(local.peer, remote.peer);
  const issues = [...peer.issues], breaches = [...peer.breaches];
  if (local.job.identity !== remote.job.identity) issues.push("job inputs or outputs differ");
  if (!(a["service-p95-ms"] > 0)) issues.push("workstation service budget missing");
  for (const arm of rows) {
    if (arm.service.errors || arm.service.good < peerLimits.min_samples) issues.push(arm.site + ": missing workstation samples");
    if (arm.service.p95_ms > a["service-p95-ms"]) breaches.push(arm.site + ": workstation service P95");
  }
  return { ...info, state: "peer_preflight", cad_trials: 0, cad_decision: "not_measured", rows,
    receiver_limits: peerLimits, workstation_p95_budget_ms: a["service-p95-ms"],
    peer_check: { passed: !issues.length && !breaches.length, issues, breaches } };
}

async function preflight(a, dir, info, binary, serviceUrl) {
  const file = join(dir, "compositor.csv");
  const command = "(Get-Process dwm | Where-Object SessionId -eq (Get-Process -Id $PID).SessionId | Select-Object -First 1).Id";
  const pid = Number((await child(powerShell, [...ps, "-Command", command], { timeout: 5000 }).done).stdout.trim());
  if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error("No compositor in the current Windows session");
  const etw = await startCapture(binary, pid, file, 7);
  const t0 = qpcMs();
  let t1, service;
  const net = probeService(serviceUrl);
  try {
    await sleep(4500);
    t1 = qpcMs();
  } finally {
    try { await etw.stop(); } finally { service = await net.stop(t0, t1 ?? qpcMs()); }
  }
  const frames = await inspectFrames(file, pid, t0, t1);
  if (!frames.displayed_intervals) throw new Error("ETW saw no displayed compositor intervals in the QPC window");
  const jobChecks = {};
  if (a["check-jobs"]) {
    const jobs = await configureJobs(a, dir);
    for (const site of ["local", "remote"]) jobChecks[site] = await runJob(jobs[site], a.timeout);
    if (jobChecks.local.identity !== jobChecks.remote.identity) throw new Error("Independent local/peer job receipts differ");
  }
  return { ...info, state: "preflight", measured_process: "dwm.exe", etw_pid: pid, frames, service,
    job_checks: jobChecks, cad_trials: 0, cad_decision: "not_measured" };
}

async function benchmark(a, dir, info, binary) {
  const jobs = await configureJobs(a, dir);
  await copyFile(info.drawing, join(dir, "scene.dwg"), constants.COPYFILE_EXCL);
  if (sha256(await readFile(join(dir, "scene.dwg"))) !== info.drawing_sha256) throw new Error("Drawing changed during copy");
  const args = [...ps, "-ExecutionPolicy", "RemoteSigned", "-File", join(scripts, "cad_viewport.ps1"),
    "-RunDirectory", dir, "-ProgId", a["prog-id"], "-OwnerPid", String(process.pid),
    "-Arms", String((a.pairs + a["deferred-retries"] + a["capture-retries"]) * 2), "-Seconds", String(a.seconds)];
  if (a["secondary-display"]) args.push("-SecondaryDisplay", a["secondary-display"]);
  const scene = child(powerShell, args);
  const controller = new AbortController();
  const onCancel = () => controller.abort(new Error("CAD benchmark cancelled"));
  process.once("SIGINT", onCancel);
  process.once("SIGTERM", onCancel);
  let collector;
  const csv = join(dir, "acad.csv"), rows = [];
  try {
    const ready = await marker(dir, "ready.json", 120000, scene, controller.signal);
    info.cad = ready;
    if (a["secondary-display"] && ready.display !== a["secondary-display"])
      throw new Error("CAD did not confirm the requested secondary display");
    if (ready.warmup.exposure_misses) throw new Error("The dedicated CAD viewport was obscured during warmup");
    const maxArms = 2 * (a.pairs + a["deferred-retries"] + a["capture-retries"]);
    collector = await startCapture(binary, Number(ready.pid), csv, maxArms * (a.timeout + 55) + 15);
    const deferrals = info.guard_deferrals = [];
    const invalidCaptures = info.invalid_captures = [];
    let attemptIndex = 0;
    for (let pair = 1; pair <= a.pairs; pair++) {
      const order = pair % 2 ? ["local", "remote"] : ["remote", "local"];
      const pairRows = [];
      for (const site of order) {
        const idx = attemptIndex++;
        let sweepDone, arm;
        try {
          arm = await observedArm(a, jobs, site, controller.signal, () => {
            sweepDone = writeFile(join(dir, "arm-" + idx + ".go"), "go", { flag: "wx" })
              .then(() => marker(dir, "arm-" + idx + ".done.json", (a.seconds + 15) * 1000, scene, controller.signal));
            return sweepDone;
          });
        } catch (error) {
          const reason = /Swarm deferred: ([a-z0-9_]+)/.exec(error.message)?.[1];
          if (site !== "remote" || !reason || !sweepDone) throw error;
          const deferred = { pair, site, arm_index: idx, reason, sweep: await sweepDone,
            discarded_completed_arms: pairRows.map(r => r.arm_index) };
          deferrals.push(deferred);
          await writeFile(join(dir, "deferred-" + idx + ".json"), JSON.stringify(deferred, null, 2), { flag: "wx" });
          if (deferrals.length > a["deferred-retries"]) throw error;
          await sleep(15000, undefined, { signal: controller.signal });
          break;
        }
        const measured = { pair, arm_index: idx, ...arm };
        await writeFile(join(dir, "arm-" + idx + ".json"), JSON.stringify(measured, null, 2), { flag: "wx" });
        const frameIssues = [...arm.overlap.issues];
        if (arm.sweep.exposure_misses) frameIssues.push("viewport was obscured during camera sweep");
        if (!frameIssues.length) {
          const { from_qpc_ms: from, until_qpc_ms: until } = arm.overlap;
          let live;
          for (let attempt = 0; attempt < 5; attempt++) {
            if (attempt) await sleep(500, undefined, { signal: controller.signal });
            if (await exists(csv)) live = await inspectFrames(csv, Number(ready.pid), from, until, a["swap-chain"] ?? null);
            if (live && !live.issues.length) break;
          }
          frameIssues.push(...(live?.issues ?? ["PresentMon did not deliver frame data"]));
        }
        if (frameIssues.length) {
          const invalid = { pair, site, arm_index: idx, issues: frameIssues,
            discarded_completed_arms: [...pairRows.map(r => r.arm_index), idx] };
          invalidCaptures.push(invalid);
          await writeFile(join(dir, "invalid-" + idx + ".json"), JSON.stringify(invalid, null, 2), { flag: "wx" });
          if (invalidCaptures.length > a["capture-retries"]) throw new Error(frameIssues.join(", "));
          await sleep(5000, undefined, { signal: controller.signal });
          break;
        }
        pairRows.push(measured);
      }
      if (pairRows.length === 2) rows.push(...pairRows);
      else pair--; // Preserve the assigned AB/BA order when replaying a complete pair.
    }
    const trace = await collector.stop();
    collector = null;
    info.presentmon_trace = {
      pid: Number(ready.pid), display: ready.display ?? null,
      events_lost: Number(/(\d+) ETW events were lost/i.exec(trace.stderr)?.[1] ?? 0),
      buffers_lost: Number(/(\d+) ETW buffers were lost/i.exec(trace.stderr)?.[1] ?? 0),
    };
    for (const r of rows) {
      const { from_qpc_ms: from, until_qpc_ms: until, issues } = r.overlap;
      r.frames = issues.length ? { issues: [...issues], p99_ms: null, displayed_intervals: 0 }
        : await inspectFrames(csv, Number(ready.pid), from, until, a["swap-chain"] ?? null);
      if (r.sweep.exposure_misses) r.frames.issues.push("viewport was obscured during camera sweep");
    }
    const summary = comparePairs(rows, a["service-p95-ms"] ?? null, deferrals);
    if (info.presentmon_trace.events_lost || info.presentmon_trace.buffers_lost) {
      summary.issues.push("PresentMon reported ETW loss during capture");
      summary.decision = "insufficient_evidence";
    }
    return { ...info, state: "completed", cad_trials: rows.length, rows, summary };
  } finally {
    controller.abort();
    process.removeListener("SIGINT", onCancel);
    process.removeListener("SIGTERM", onCancel);
    await writeFile(join(dir, rows.length === a.pairs * 2 ? "finish" : "stop"), "");
    if (collector) await collector.stop().catch(() => {});
    await Promise.race([scene.done.catch(() => {}), sleep(2500)]);
  }
}

async function main() {
  const { values: a, positionals } = parseArgs({ options, allowPositionals: true });
  if (a.help) { console.log(usage); return; }
  const mode = positionals[0] ?? "preflight";
  if (!["shared", "independent"].includes(a["local-build"])
      || (a["local-build"] === "shared" && (a.jobs || a["reference-ssh"]))) {
    throw new Error("Choose shared or independent for the built-in two-agent workload");
  }
  if (positionals.length > 1 || !["preflight", "peer-preflight", "run"].includes(mode)) throw new Error(usage);
  if (process.platform !== "win32") throw new Error("Requires Windows, desktop AutoCAD and PresentMon");
  if (a["cpu-quota-pct"] !== undefined) {
    if (a.jobs || a["reference-ssh"] || (mode === "preflight" && !a["check-jobs"])) {
      throw new Error("--cpu-quota-pct requires the built-in guarded peer workload");
    }
    a["cpu-quota-pct"] = numberIn(a["cpu-quota-pct"], "cpu-quota-pct", 1, 100, true);
  }
  a.rounds = numberIn(a.rounds, "rounds", 1, 3000, true);
  a.pairs = numberIn(a.pairs, "pairs", 1, 30, true);
  a["deferred-retries"] = numberIn(a["deferred-retries"], "deferred-retries", 0, 10, true);
  a["capture-retries"] = numberIn(a["capture-retries"], "capture-retries", 0, 10, true);
  a.seconds = numberIn(a.seconds, "seconds", 3, 120);
  a.timeout = numberIn(a.timeout, "timeout", a.seconds + 2, 900);
  if (a["service-p95-ms"] !== undefined) a["service-p95-ms"] = numberIn(a["service-p95-ms"], "service-p95-ms", 0.01, 60000);
  const dir = await makeOutput(a.out);
  const report = join(dir, "report.json");
  const info = { schema: 2, started_utc: new Date().toISOString(), mode,
    workload: a.jobs ? "configured job pair" : a["reference-ssh"] ?
      "single reference CPython compile per site" : a["local-build"] === "shared" ?
        "two concurrent senders share one guarded build on each host" :
        "two independent Windows builds versus one guarded Linux build",
    requested_peer_cpu_quota_pct: a["cpu-quota-pct"] ?? null, output_directory: dir };
  info.local_build_strategy = a.jobs ? "custom" : a["reference-ssh"] ? "single-reference" : a["local-build"];
  if (mode !== "preflight") {
    info.protocol = {
      viewport: a["secondary-display"] ? { device: a["secondary-display"], focus: "unclaimed", visibility: "nine window hit tests on each camera step" } : { focus: "foreground" },
      rounds: a.rounds, peer: a.peer, sweep_seconds: mode === "run" ? a.seconds : null,
      cache: a.jobs ? "operator-defined" : a["reference-ssh"] ? "fresh compile" : "fresh Swarm action key in each arm",
      receiver: "Two fresh HTTP GETs on Linux loopback, verified Radar health and linked CSS; host counters read on that same sample.",
      workstation: a["service-url"] ?? "Fresh Radar health GET through an existing authenticated SSH forward; SSH setup is outside the measurement.",
      timing: "Sampling begins before the compiler. Requests must start and end within every compiler window and the scene. Total job time includes admission, transfer and receipt verification.",
      timing_alignment: "Smallest of three starting and two ending round trips bound monotonic-clock offsets. A 500 ppm margin covers drift during observation.",
      storage: "Each device reports its last counter minus its first within the measured interval. Counters include other host activity. The disk and partition overlap.",
      service_budget_scope: "Experimental thresholds for this single-user measurement; both endpoints, each arm and each pair are evaluated.",
      receiver_limits: peerLimits, workstation_p95_limit_ms: a["service-p95-ms"] ?? null,
    };
  }
  try {
    let data;
    if (mode === "peer-preflight") {
      data = await peerPreflight(a, dir, info);
    } else {
      const bin = await toolPath(a.presentmon), drawing = a.dwg ? resolve(a.dwg) : await defaultDrawing();
      const drawingData = await readFile(drawing);
      if (!/^AC10\d{2}/.test(drawingData.subarray(0, 6).toString("ascii"))) throw new Error("Invalid DWG file signature");
      Object.assign(info, { drawing, drawing_sha256: sha256(drawingData),
        presentmon: basename(bin), presentmon_sha256: sha256(await readFile(bin)) });
      data = mode === "run" ? await benchmark(a, dir, info, bin)
        : await preflight(a, dir, info, bin, await endpoint(a["service-url"]));
    }
    await writeFile(report, JSON.stringify(data, null, 2) + "\n", { flag: "wx" });
    console.log(JSON.stringify({ report, state: data.state, cad_trials: data.cad_trials, decision: data.summary?.decision ?? data.cad_decision }));
    if ((data.summary && data.summary.decision !== "pass") || data.peer_check?.passed === false) process.exitCode = 2;
  } catch (error) {
    const cad = mode === "run" ? {} : { cad_trials: 0, cad_decision: "not_measured" };
    await writeFile(report, JSON.stringify({ ...info, ...cad, state: "failed", error: error.message }, null, 2) + "\n", { flag: "wx" });
    throw new Error(error.message + "; diagnostic report: " + report, { cause: error });
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
