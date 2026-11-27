import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { comparePairs, inspectFrames } from "../scripts/cad_frame_metrics.mjs";
import { comparePeerPair, reduceArm } from "../scripts/cad_peer_metrics.mjs";

const header = "Application,ProcessID,SwapChainAddress,CPUStartQPCTime,DisplayLatency,DisplayedTime";

async function csv(t, lines) {
  const dir = await mkdtemp(join(tmpdir(), "chimera-frame-test-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, "test.csv");
  await writeFile(path, [header, ...lines].join("\n"));
  return path;
}

test("counts only complete displayed intervals for the target PID inside the job/scene overlap", async t => {
  const lines = Array.from({ length: 100 }, (_, i) => '"AutoCAD, Inc",42,0xff,' + (995 + 10 * i) + ",5,10");
  lines.push("other,1,0xff,1000,0,999", "acad,42,0xff,990,0,20", "acad,42,0xff,1995,0,20",
             "acad,42,0xff,1220,NA,NA", "acad,42,0xff,1193,NA,20");
  const result = await inspectFrames(await csv(t, lines), 42, 1000, 2000);
  assert.equal(result.displayed_intervals, 100);
  assert.equal(result.p99_ms, 10);
  assert.equal(result.coverage, 1);
  assert.equal(result.non_displayed_rows_all_chains, 1);
  assert.deepEqual(result.issues, []);
});

test("reads PresentMon Unicode stdout with the same QPC intervals as a CSV file", async t => {
  const lines = Array.from({ length: 100 }, (_, i) => `acad,42,0xff,${i * 10},0,10`);
  const path = await csv(t, lines);
  const expected = await inspectFrames(path, 42, 0, 1000);
  await writeFile(path, "\uFEFF" + [header, ...lines].join("\r\n"), "utf16le");
  assert.deepEqual(await inspectFrames(path, 42, 0, 1000), expected);
});

test("reports ambiguous swap chains unless a measured viewport chain is supplied", async t => {
  const lines = [];
  for (let i = 0; i < 100; i++) {
    for (const id of ["0xa", "0xb"]) lines.push("acad,88," + id + "," + (10 * i) + ",0,10");
  }
  const path = await csv(t, lines);
  assert.match((await inspectFrames(path, 88, 0, 1000)).issues.join(" "), /similarly active/);
  assert.deepEqual((await inspectFrames(path, 88, 0, 1000, "0xb")).issues, []);
  assert.ok((await inspectFrames(path, 88, 0, 1000, "0xf")).issues.length);
});

test("rejects CPU-only timestamps and sparse displayed frames", async t => {
  const path = await csv(t, ["acad,8,0xc,10,1,10"]);
  assert.ok((await inspectFrames(path, 8, 0, 1000)).issues.length);
  await writeFile(path, "ProcessID,CPUStartQPCTime,FrameTime\n8,0,10");
  await assert.rejects(inspectFrames(path, 8, 0, 1000), /PresentMon CSV lacks/);
});

function pairedRuns() {
  const rows = [];
  for (let n = 1; n <= 10; n++) {
    for (const site of n % 2 ? ["local", "remote"] : ["remote", "local"]) {
      rows.push({ pair: n, site, frames: { issues: [], p99_ms: site === "local" ? 100 : 70 },
        job: { identity: "same_inputs_and_results", wall_ms: 1000 },
        peer: { issues: [], breaches: [], good: 40, health_p95_ms: 3, asset_p95_ms: 2, min_mem_available_mib: 6000,
          max_load1: 0.5, max_cpu_temp_c: 60, max_psi_some_avg10_pct: { cpu: 0, memory: 0, io: 0 },
          host_write_delta_bytes_per_device: { sda: 100 }, identity: { unit_pid: 412, asset_sha256: "fixture", device_names: ["sda"] } },
        service: { p95_ms: 30, errors: 0, good: 40 } });
    }
  }
  return rows;
}

test("acceptance gates require alternating pairs, identical receipts, service capacity and frame evidence", () => {
  assert.equal(comparePairs(pairedRuns(), 40).decision, "pass");
  assert.equal(comparePairs(pairedRuns(), 10).decision, "below_criteria");
  const retry = comparePairs(pairedRuns(), 40, [{ pair: 2, arm_index: 2, reason: "running_guard_service_latency" }]);
  assert.equal(retry.valid_frame_pairs, 10);
  assert.equal(retry.decision, "below_criteria");
  assert.match(retry.receiver_threshold_breaches[0], /receiver deferred running_guard_service_latency/);
  assert.equal(comparePairs(pairedRuns(), null).decision, "insufficient_evidence");
  assert.equal(comparePairs(pairedRuns().slice(0, 2), 40).decision, "insufficient_evidence");
  const rows = pairedRuns();
  [rows[0], rows[1]] = [rows[1], rows[0]];
  rows[2].job.identity = "different_inputs";
  rows[3].frames.issues.push("lost foreground");
  rows[4].service.errors = 1;
  const summary = comparePairs(rows, 40);
  assert.equal(summary.decision, "insufficient_evidence");
  assert.ok(summary.issues.some(v => v.includes("AB/BA")));
  assert.ok(summary.issues.some(v => v.includes("receipts")));
  assert.ok(summary.issues.some(v => v.includes("display evidence")));
  assert.ok(summary.issues.some(v => v.includes("successful service probes")));
});

function telemetryCase(site) {
  const ready = { service: { unit_pid: 412, asset_sha256: "fixture", unit_declares_port: true,
    entry_links_asset: true, device_names: ["sda", "sda2"] }, windows_endpoint: "loopback via SSH" };
  const result = { identity: { same_service: true },
    linux_sync_open: [{ sent_ms: 0, linux_ms: 1010, received_ms: 20 }],
    linux_sync_close: [{ sent_ms: 14980, linux_ms: 15990, received_ms: 15000 }],
    linux: [], windows: [] };
  for (let i = 0; i < 24; i++) {
    const times = { start_ms: 2000 + i * 300, end_ms: 2050 + i * 300 };
    result.windows.push({ ...times, http_ms: 211 });
    result.linux.push({ ...times, guest_before: site === "remote", linux_http_ms: { health: 2, asset: 1 },
      host: { mem_available_mib: 6100, load1: 0.5, cpu_temp_c: 59, device_write_bytes: { sda: i * 8192, sda2: i * 4096 },
        psi: Object.fromEntries(["cpu", "memory", "io"].map(k => [k, { avg10_pct: 0 }])) } });
  }
  const remote = site === "remote";
  return { ready, result, job: { started_qpc_ms: 100, ended_qpc_ms: 13500,
    receipt: { compiler_clock: remote ? "linux_monotonic" : "windows_qpc",
      compiler_windows_ms: remote ? [[2000, 11000]] : [[1200, 10000], [1400, 10400]] } },
    sweep: { from_qpc_ms: 1100, until_qpc_ms: 11200 } };
}

const reduce = (c, site) => reduceArm(c.ready, c.result, site, c.job, c.sweep);

test("receiver samples must be inside the compiler/scene overlap on both clocks", () => {
  const c = telemetryCase("remote");
  c.result.windows.unshift({ start_ms: 0, end_ms: 1990, error: "outside" });
  c.result.windows.push({ start_ms: 9500, end_ms: 11000, http_ms: 999 });
  c.result.linux.push({ start_ms: 9400, end_ms: 10200, error: "straddles compiler exit" });
  const { overlap, service, peer } = reduce(c, "remote");
  assert.ok(overlap.until_qpc_ms < 10000);
  assert.deepEqual([peer.good, service.good, service.errors, service.p95_ms], [24, 24, 0, 211]);
  assert.deepEqual(peer.issues, []);
  assert.deepEqual(peer.host_write_delta_bytes_per_device, { sda: 188416, sda2: 94208 });
  assert.deepEqual(peer.breaches, []);
  assert.equal(reduce(telemetryCase("local"), "local").overlap.from_qpc_ms, 1400);
  c.job.receipt.compiler_windows_ms = [];
  assert.ok(reduce(c, "remote").peer.issues.some(s => s.includes("actual compiler")));
});

test("missing RAM, samples, guest identity or reset block counters prevent acceptance", () => {
  const c = telemetryCase("remote");
  delete c.result.linux[0].host.mem_available_mib;
  c.result.linux[2].host.device_write_bytes.sda = 2;
  c.result.linux[3].guest_before = false;
  c.result.linux.splice(16);
  const { peer } = reduce(c, "remote");
  assert.equal(peer.good, 15);
  assert.ok(peer.issues.some(s => s.includes("20 complete")));
  assert.ok(peer.issues.some(s => s.includes("guest absent")));
  assert.equal(peer.host_write_delta_bytes_per_device.sda, null);
  const rows = pairedRuns();
  delete rows[2].peer;
  assert.equal(comparePairs(rows, 40).decision, "insufficient_evidence");
  const missing = pairedRuns();
  delete missing[0].peer.host_write_delta_bytes_per_device;
  assert.equal(comparePairs(missing, 40).decision, "insufficient_evidence");
});

test("receiver temperature, load, PSI, RAM or higher service latency independently fail a complete pair", () => {
  const c = telemetryCase("remote");
  c.result.linux[2].host.mem_available_mib = 2559;
  c.result.linux[3].host.cpu_temp_c = 70;
  c.result.linux[3].host.load1 = 1.81;
  c.result.linux[4].host.psi.io.avg10_pct = 5;
  for (const r of c.result.linux) r.linux_http_ms.health = 10;
  const local = reduce(telemetryCase("local"), "local").peer;
  const remote = reduce(c, "remote").peer;
  const { issues, breaches } = comparePeerPair(local, remote);
  assert.deepEqual(issues, []);
  assert.equal(breaches.length, 5);
  const rows = pairedRuns();
  rows[0].peer = local;
  rows[1].peer = remote;
  assert.equal(comparePairs(rows, 40).decision, "below_criteria");
});
