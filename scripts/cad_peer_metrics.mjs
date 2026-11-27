/** Reduce only rows fully enclosed by the compiler, viewport and calling process. */

export const peerLimits = Object.freeze({
  linux_p95_ms: 20, linux_p95_added_ms: 5, min_samples: 20, ram_reserve_mib: 2560,
  max_load1: 1.8, max_cpu_temp_c: 70, max_psi_some_avg10_pct: { cpu: 25, memory: 1, io: 5 },
});

const finite = Number.isFinite;
const pressures = Object.keys(peerLimits.max_psi_some_avg10_pct);

function clockBounds(open, close) {
  function best(samples) {
    return (samples ?? []).filter(s => [s.sent_ms, s.linux_ms, s.received_ms].every(finite)
      && s.received_ms >= s.sent_ms).sort((a, b) =>
      (a.received_ms - a.sent_ms) - (b.received_ms - b.sent_ms))[0];
  }
  const a = best(open), b = best(close);
  if (!a || !b || b.sent_ms < a.received_ms) return null;
  // Widen the observed offsets by 500 ppm for clock slew between calibration points.
  const margin = (b.received_ms - a.sent_ms) * 0.0005;
  const low = Math.min(a.linux_ms - a.received_ms, b.linux_ms - b.received_ms) - margin;
  const high = Math.max(a.linux_ms - a.sent_ms, b.linux_ms - b.sent_ms) + margin;
  return { low, high, uncertainty_ms: high - low };
}

function compilerOverlap(job, sweep, result, site) {
  const clocks = clockBounds(result.linux_sync_open, result.linux_sync_close);
  const windows = job.receipt?.compiler_windows_ms;
  const issues = [];
  let from = Math.max(job.started_qpc_ms, sweep.from_qpc_ms);
  let until = Math.min(job.ended_qpc_ms, sweep.until_qpc_ms);
  const expected = site === "remote" ? "linux_monotonic" : "windows_qpc";
  if (!clocks || clocks.uncertainty_ms > 1500) issues.push("peer clock synchronization missing or too uncertain");
  if (!Array.isArray(windows) || !windows.length || job.receipt.compiler_clock !== expected
      || !windows.every(w => Array.isArray(w) && w.length === 2 && w.every(finite) && w[1] > w[0])) {
    issues.push("actual compiler times or clock are missing from the job receipt");
  } else if (site === "local" || clocks) {
    for (const [start, end] of windows) {
      from = Math.max(from, start - (site === "remote" ? clocks.low : 0));
      until = Math.min(until, end - (site === "remote" ? clocks.high : 0));
    }
  }
  if (!(until > from)) issues.push("no measurable compiler and scene overlap");
  return { from_qpc_ms: from, until_qpc_ms: until, duration_ms: Math.max(0, until - from),
    linux_minus_windows_clock_ms: clocks, issues };
}

function nearestP95(values) {
  if (!values.length) return null;
  return [...values].sort((a, b) => a - b)[Math.ceil(values.length * 0.95) - 1];
}

export function reduceArm(ready, result, site, job, sweep, guarded = true) {
  const overlap = compilerOverlap(job, sweep, result, site);
  const contains = row => finite(row.start_ms) && finite(row.end_ms) && row.end_ms >= row.start_ms
    && row.start_ms >= overlap.from_qpc_ms && row.end_ms <= overlap.until_qpc_ms;
  const linux = result.linux.filter(contains), windows = result.windows.filter(contains);
  const issues = [...overlap.issues], breaches = [];
  if (!result.identity?.same_service || !ready.service?.unit_declares_port || !ready.service?.entry_links_asset) {
    issues.push("Radar service identity or route changed during capture");
  }
  const devices = ready.service?.device_names ?? [];
  const valid = linux.filter(r => !r.error && [r.linux_http_ms?.health, r.linux_http_ms?.asset,
    r.host?.mem_available_mib, r.host?.load1, r.host?.cpu_temp_c].every(v => finite(v) && v >= 0)
    && pressures.every(k => finite(r.host?.psi?.[k]?.avg10_pct) && r.host.psi[k].avg10_pct >= 0)
    && devices.every(d => Number.isSafeInteger(r.host?.device_write_bytes?.[d]) && r.host.device_write_bytes[d] >= 0));
  if (!devices.length || !valid.length) issues.push("receiver storage or resource telemetry missing");
  if (linux.length !== valid.length || valid.length < peerLimits.min_samples) {
    issues.push("receiver requires 20 complete error-free samples inside the measured window");
  }
  if (site === "local" && valid.some(r => r.guest_before !== false)) issues.push("peer busy during local baseline");
  if (site === "remote" && guarded && valid.some(r => r.guest_before !== true)) issues.push("peer guest absent during remote compiler window");
  const http = windows.filter(r => !r.error && finite(r.http_ms) && r.http_ms >= 0);
  const service = { endpoint: ready.windows_endpoint, good: http.length, errors: windows.length - http.length,
    p95_ms: nearestP95(http.map(r => r.http_ms)), samples: windows };
  if (service.errors || http.length < peerLimits.min_samples) issues.push("workstation service probes incomplete");
  const writes = {};
  for (const device of devices) {
    const series = valid.map(r => r.host.device_write_bytes[device]);
    const reset = series.some((v, i) => i && v < series[i - 1]);
    if (reset || series.length < 2) issues.push("missing or reset storage counter for " + device);
    writes[device] = !reset && series.length >= 2 ? series.at(-1) - series[0] : null;
  }
  const lowRam = valid.length ? Math.min(...valid.map(r => r.host.mem_available_mib)) : null;
  const highLoad = valid.length ? Math.max(...valid.map(r => r.host.load1)) : null;
  const highTemp = valid.length ? Math.max(...valid.map(r => r.host.cpu_temp_c)) : null;
  const maxPsi = Object.fromEntries(pressures.map(k => [k, valid.length
    ? Math.max(...valid.map(r => r.host.psi[k].avg10_pct)) : null]));
  const health = nearestP95(valid.map(r => r.linux_http_ms.health));
  const asset = nearestP95(valid.map(r => r.linux_http_ms.asset));
  if (lowRam !== null && lowRam < peerLimits.ram_reserve_mib) breaches.push("receiver RAM reserve");
  if (highLoad !== null && highLoad > peerLimits.max_load1) breaches.push("receiver load");
  if (highTemp !== null && highTemp >= peerLimits.max_cpu_temp_c) breaches.push("receiver temperature");
  for (const k of pressures) {
    if (maxPsi[k] !== null && maxPsi[k] >= peerLimits.max_psi_some_avg10_pct[k]) breaches.push("receiver PSI " + k);
  }
  for (const [name, value] of Object.entries({ health, asset })) {
    if (value !== null && value > peerLimits.linux_p95_ms) breaches.push("receiver P95 " + name);
  }
  return { overlap, service, peer: { identity: ready.service, probe_sha256: ready.source_sha256,
    identity_at_close: result.identity, clock_sync: { open: result.linux_sync_open, close: result.linux_sync_close },
    issues, breaches, good: valid.length, health_p95_ms: health, asset_p95_ms: asset,
    min_mem_available_mib: lowRam, max_load1: highLoad, max_cpu_temp_c: highTemp, max_psi_some_avg10_pct: maxPsi,
    host_write_delta_bytes_per_device: writes, first_host_sample_ms: valid[0]?.start_ms ?? null,
    last_host_sample_ms: valid.at(-1)?.end_ms ?? null, samples: linux } };
}

export function comparePeerPair(local, remote, limits = peerLimits) {
  const issues = [], breaches = [];
  for (const entry of [local, remote]) {
    const devices = entry?.identity?.device_names;
    if (!entry || !Array.isArray(entry.issues) || !Array.isArray(entry.breaches)
        || !(Number.isInteger(entry.good) && entry.good >= limits.min_samples)
        || ![entry.health_p95_ms, entry.asset_p95_ms, entry.min_mem_available_mib,
          entry.max_load1, entry.max_cpu_temp_c].every(v => finite(v) && v >= 0)
        || !pressures.every(k => finite(entry.max_psi_some_avg10_pct?.[k]) && entry.max_psi_some_avg10_pct[k] >= 0)
        || !Number.isInteger(entry.identity?.unit_pid) || !entry.identity?.asset_sha256
        || !Array.isArray(devices) || !devices.length || !devices.every(d =>
          Number.isSafeInteger(entry.host_write_delta_bytes_per_device?.[d]) && entry.host_write_delta_bytes_per_device[d] >= 0)) {
      issues.push("receiver measurements are missing or incomplete");
    }
    if (Array.isArray(entry?.issues)) issues.push(...entry.issues);
    if (Array.isArray(entry?.breaches)) breaches.push(...entry.breaches);
  }
  if (local?.identity?.unit_pid !== remote?.identity?.unit_pid
      || local?.identity?.asset_sha256 !== remote?.identity?.asset_sha256
      || JSON.stringify(local?.identity?.device_names) !== JSON.stringify(remote?.identity?.device_names)) {
    issues.push("receiver service or storage devices changed between arms");
  }
  for (const field of ["health_p95_ms", "asset_p95_ms"]) {
    if (finite(remote?.[field]) && finite(local?.[field]) && remote[field] - local[field] > limits.linux_p95_added_ms) {
      breaches.push("pair exceeds allowed receiver latency increase for " + field);
    }
  }
  return { issues, breaches };
}
