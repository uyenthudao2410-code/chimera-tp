import { createReadStream } from "node:fs";
import { open } from "node:fs/promises";
import { comparePeerPair, peerLimits } from "./cad_peer_metrics.mjs";
import { createInterface } from "node:readline";

export function quantile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(fraction * sorted.length) - 1)];
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function parseRow(line) {
  const values = [];
  let value = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') {
      if (quoted && line[i + 1] === '"') {
        value += '"';
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (c === "," && !quoted) {
      values.push(value.trim());
      value = "";
    } else {
      value += c;
    }
  }
  if (quoted) throw new Error("Incomplete CSV record");
  values.push(value.trim());
  return values;
}

function numeric(cell) {
  if (!cell || cell === "NA") return NaN;
  return Number(cell);
}

/** PresentMon 2.x metrics with --qpc_time_ms. Keep complete displayed intervals only. */
export async function inspectFrames(csvPath, pid, fromMs, untilMs, requestedChain = null) {
  if (!Number.isSafeInteger(pid) || pid <= 0 || !(untilMs > fromMs)) {
    throw new Error("A process ID and a positive QPC interval are required");
  }
  // PresentMon 2.6 writes UTF-16LE with a BOM to redirected stdout on Windows.
  // Its --output_file mode and previously recorded traces use UTF-8.
  const file = await open(csvPath, "r");
  const bom = Buffer.alloc(2);
  try {
    await file.read(bom, 0, bom.length, 0);
  } finally {
    await file.close();
  }
  const encoding = bom.readUInt16LE() === 0xfeff ? "utf16le" : "utf8";
  const reader = createInterface({ input: createReadStream(csvPath, { encoding }), crlfDelay: Infinity });
  const samples = new Map();
  let columns;
  let dropped = 0;
  for await (const line of reader) {
    if (!line.trim()) continue;
    const fields = parseRow(line.replace(/^\uFEFF/, ""));
    if (!columns) {
      columns = Object.fromEntries(fields.map((name, index) => [name, index]));
      for (const key of ["ProcessID", "SwapChainAddress", "CPUStartQPCTime", "DisplayLatency", "DisplayedTime"]) {
        if (!(key in columns)) throw new Error("PresentMon CSV lacks " + key + " (use --v2_metrics --qpc_time_ms)");
      }
      continue;
    }
    if (Number(fields[columns.ProcessID]) !== pid) continue;
    const cpuStart = numeric(fields[columns.CPUStartQPCTime]);
    const latency = numeric(fields[columns.DisplayLatency]);
    const duration = numeric(fields[columns.DisplayedTime]);
    if (!Number.isFinite(duration) || duration <= 0) {
      if (cpuStart >= fromMs && cpuStart <= untilMs) dropped++;
      continue;
    }
    const displayed = cpuStart + latency;
    if (!Number.isFinite(displayed) || displayed < fromMs || displayed + duration > untilMs) continue;
    const key = fields[columns.SwapChainAddress].toLowerCase();
    if (!samples.has(key)) samples.set(key, []);
    samples.get(key).push(duration);
  }
  if (!columns) throw new Error("PresentMon did not write its CSV header");
  const chains = [...samples].map(([address, intervals]) => ({
    address, count: intervals.length, covered_ms: intervals.reduce((sum, n) => sum + n, 0),
  })).sort((a, b) => b.count - a.count);
  const selected = requestedChain === null ? chains[0] : chains.find(c => c.address === requestedChain.toLowerCase());
  const durations = selected ? samples.get(selected.address) : [];
  const seconds = (untilMs - fromMs) / 1000;
  const faults = [];
  if (!selected) faults.push("no displayed swap chain in the measured window");
  if (!requestedChain && chains.length > 1 && chains[1].count >= chains[0].count * 0.8) {
    faults.push("multiple similarly active swap chains; identify the viewport and specify --swap-chain");
  }
  if (durations.length < 100) faults.push("fewer than 100 complete displayed intervals");
  const coverage = (selected?.covered_ms ?? 0) / (untilMs - fromMs);
  if (coverage < 0.7 || coverage > 1.05) faults.push("display-time coverage outside 70–105% of the overlap");
  const stalls = durations.filter(ms => ms > 50).length;
  return {
    source: "PresentMon ETW, CPUStartQPCTime + DisplayLatency, DisplayedTime",
    qpc_from_ms: fromMs, qpc_until_ms: untilMs, overlap_s: seconds,
    chains, selected_chain: selected?.address ?? null, displayed_intervals: durations.length,
    non_displayed_rows_all_chains: dropped, coverage, p95_ms: quantile(durations, 0.95),
    p99_ms: quantile(durations, 0.99), stalls_over_50_ms: stalls, stalls_per_s: stalls / seconds,
    issues: faults,
  };
}

export function comparePairs(rows, serviceBudgetMs, deferrals = []) {
  const pairs = new Map();
  for (const run of rows) {
    if (!pairs.has(run.pair)) pairs.set(run.pair, {});
    const p = pairs.get(run.pair);
    if (p[run.site]) throw new Error("Duplicate condition in pair " + run.pair);
    p[run.site] = run;
  }
  const p99Reduction = [], jobIncrease = [];
  const issues = [];
  const peerBreaches = deferrals.map(d => `pair ${d.pair}, attempt arm ${d.arm_index}: receiver deferred ${d.reason}`);
  if (rows.some((r, i) => {
    const pair = Math.floor(i / 2) + 1;
    const localFirst = (pair % 2) === 1;
    const localSlot = (i % 2 === 0) === localFirst;
    return r.pair !== pair || r.site !== (localSlot ? "local" : "remote");
  })) issues.push("condition order does not follow AB/BA alternation");
  const identities = new Set();
  for (const [pair, { local, remote }] of pairs) {
    if (!local || !remote) { issues.push("incomplete pair " + pair); continue; }
    const receiver = comparePeerPair(local.peer, remote.peer);
    for (const issue of new Set(receiver.issues)) issues.push("pair " + pair + ": " + issue);
    for (const breach of new Set(receiver.breaches)) peerBreaches.push("pair " + pair + ": " + breach);
    const comparable = [local, remote].every(r => Array.isArray(r.frames?.issues) && !r.frames.issues.length
      && Number.isFinite(r.frames.p99_ms) && r.frames.p99_ms > 0);
    if (!comparable) issues.push("insufficient display evidence in pair " + pair);
    if (comparable) p99Reduction.push(100 * (1 - remote.frames.p99_ms / local.frames.p99_ms));
    if ([local, remote].every(r => Number.isFinite(r.job?.wall_ms) && r.job.wall_ms > 0)) {
      jobIncrease.push(100 * (remote.job.wall_ms / local.job.wall_ms - 1));
    } else {
      issues.push("end-to-end job duration missing for pair " + pair);
    }
    identities.add(local.job?.identity);
    identities.add(remote.job?.identity);
  }
  if (pairs.size < 10) issues.push("fewer than 10 complete alternating pairs requested");
  if (identities.size !== 1 || ![...identities][0]) issues.push("workload receipts differ or are missing");
  const invalidService = rows.filter(r => !r.service || !Number.isInteger(r.service.good) || r.service.good < 20
    || r.service.errors !== 0 || !Number.isFinite(r.service.p95_ms) || r.service.p95_ms < 0);
  if (invalidService.length) issues.push("each condition needs at least 20 successful service probes and zero probe failures");
  if (!(serviceBudgetMs > 0)) issues.push("service P95 budget has not been set");
  const serviceValues = rows.map(r => r.service?.p95_ms).filter(Number.isFinite);
  const serviceWorst = serviceValues.length ? Math.max(...serviceValues) : null;
  const p99 = p99Reduction.length ? median(p99Reduction) : null;
  const job = jobIncrease.length ? median(jobIncrease) : null;
  const passed = !issues.length && !peerBreaches.length && p99 >= 20 && job <= 10 && serviceWorst <= serviceBudgetMs;
  return {
    decision: issues.length ? "insufficient_evidence" : passed ? "pass" : "below_criteria",
    pairs: pairs.size, valid_frame_pairs: p99Reduction.length, issues, receiver_threshold_breaches: peerBreaches,
    median_paired_p99_reduction_pct: p99, median_paired_job_increase_pct: job,
    worst_service_p95_ms: serviceWorst, service_budget_ms: serviceBudgetMs,
    thresholds: { min_p99_reduction_pct: 20, max_job_increase_pct: 10, min_pairs: 10, receiver: peerLimits },
  };
}
