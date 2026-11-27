/** Observe a standalone CUDA worker and report hot-path latency and WDDM PID memory separately. */
import { execFile, spawn } from 'node:child_process';
import { readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { parseArgs, promisify } from 'node:util';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const workerPath = fileURLToPath(new URL('./cuda_vmm_worker.py', import.meta.url));
const targetMs = 1.5;
const options = parseArgs({
  options: {
    trials: { type: 'string', default: '12' },
    out: { type: 'string', default: fileURLToPath(new URL('../tasks/cuda_vmm_shadow.json', import.meta.url)) },
    python: { type: 'string', default: 'python' },
  },
}).values;
const count = Number(options.trials);
if (!Number.isInteger(count) || count < 2 || count > 100) {
  throw new Error('--trials must be an integer from 2 to 100');
}

const hidden = { windowsHide: true, encoding: 'utf8', timeout: 12000 };

async function gpuSnapshot(device) {
  const fields = [
    'name', 'pci.bus_id', 'driver_version', 'driver_model.current', 'memory.total',
    'memory.used', 'memory.free', 'temperature.gpu', 'utilization.gpu',
  ];
  const args = ['--id=' + device.pci_bus, '--query-gpu=' + fields.join(','), '--format=csv,noheader,nounits'];
  const { stdout } = await run('nvidia-smi.exe', args, hidden);
  const parts = stdout.trim().split(',').map(v => v.trim());
  if (parts.length !== fields.length) throw new Error('unexpected nvidia-smi output');
  return Object.fromEntries(fields.map((name, i) => {
    const key = { 'memory.total': 'total_mib', 'memory.used': 'used_mib', 'memory.free': 'free_mib',
      'temperature.gpu': 'temperature_c', 'utilization.gpu': 'utilization_pct' }[name] ?? name;
    const value = Number(parts[i]);
    return [key, i >= 4 ? (Number.isFinite(value) ? value : null) : parts[i]];
  }));
}

async function processDedicated(pid, device) {
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)",
    "$all = @((Get-Counter -Counter '\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples)",
    "if (-not $all.Count) { throw 'GPU Process Memory counter returned no instances' }",
    "$rows = @($all | Where-Object { $_.InstanceName -like $env:CHIMERA_CUDA_VMM_INSTANCE } | ForEach-Object {",
    '  [pscustomobject]@{ name = $_.InstanceName; bytes = [long]$_.CookedValue; status = [long]$_.Status }',
    '})',
    '[pscustomobject]@{ enumerated = $all.Count; matches = $rows } | ConvertTo-Json -Depth 4 -Compress',
  ].join('\n');
  const { stdout } = await run('powershell.exe',
    ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], {
      ...hidden, env: { ...process.env, CHIMERA_CUDA_VMM_INSTANCE: 'pid_' + pid + '_' + device.luid + '_phys_*' },
    });
  const { enumerated, matches } = JSON.parse(stdout.trim());
  if (!matches.length) return { status: 'no_pid_instance', dedicated_bytes: null, enumerated };
  if (matches.some(row => row.status !== 0 && row.status !== 1)) {
    return { status: 'invalid_counter_sample', dedicated_bytes: null, matches };
  }
  return { status: 'observed', dedicated_bytes: matches.reduce((sum, row) => sum + row.bytes, 0), matches };
}

async function recordMemory(pid, device) {
  const [processRecord, deviceRecord] = await Promise.allSettled([processDedicated(pid, device), gpuSnapshot(device)]);
  const read = item => item.status === 'fulfilled' ? item.value : { status: 'unavailable', error: String(item.reason) };
  return { collected_utc: new Date().toISOString(), process: read(processRecord), device: read(deviceRecord) };
}

function statistic(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return {
    median_ms: sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2,
    p95_ms: sorted[Math.ceil(0.95 * sorted.length) - 1], max_ms: sorted.at(-1),
  };
}

function evaluate(report) {
  const rows = report.trials;
  if (rows.length !== count || !report.context || !report.observed || !report.allocation) {
    throw new Error('worker returned an incomplete trial set');
  }
  const all = [...rows, report.observed];
  for (const row of all) {
    if (!/^[a-f0-9]{64}$/.test(row.sha256_before) || row.sha256_before !== row.sha256_migrated ||
        row.sha256_before !== row.sha256_restored) throw new Error('round-trip digest validation failed');
    if (!Object.values(row.phase_ms).every(v => Number.isFinite(v) && v >= 0)) {
      throw new Error('worker returned an invalid duration');
    }
  }
  if (new Set(all.map(row => row.sha256_before)).size !== all.length ||
      !/^[a-f0-9]{64}$/.test(report.observed.rejected_staging_sha256) ||
      report.observed.rejected_staging_sha256 === report.observed.sha256_before) {
    throw new Error('invalid fixture identity or negative control');
  }
  const phases = Object.keys(rows[0].phase_ms);
  report.summary = Object.fromEntries(phases.map(key => [key, statistic(rows.map(r => r.phase_ms[key]))]));
  const threshold = key => {
    const n = rows.filter(r => r.phase_ms[key] < targetMs).length;
    return { under_target: n, measured: rows.length, all_under_target: n === rows.length };
  };
  report.target = {
    max_exclusive_ms: targetMs, metric: 'unmap_plus_release',
    definition: 'Synchronous host clock around consecutive cuMemUnmap and final cuMemRelease on this allocation. The context stays alive.',
    allocator_release: threshold('unmap_plus_release'),
    verified_migration: threshold('copy_verify_unmap_release'),
  };
  report.corrupt_copy_control = {
    observed_run: report.observed.run, outcome: 'rejected',
    retained_original_mapping_and_handle: true, retried_from_original_and_restored: true,
  };
  const at = stage => report.memory_observations[stage]?.process.dedicated_bytes;
  const resident = at('resident_page'), released = at('released_page_keep_context');
  report.pid_memory = {
    difference_resident_minus_released_bytes:
      Number.isFinite(resident) && Number.isFinite(released) ? resident - released : null,
    with_released_page_and_live_context_bytes: released ?? null,
    after_context_destruction_bytes: at('context_destroyed') ?? null,
    after_process_exit_bytes: at('process_exited') ?? null,
    missing_instance_means: 'No numeric PID attribution at this sample; it is not a measured zero.',
  };
}

const report = {
  schema: 'chimera.cuda-vmm-shadow/1', measured_utc: new Date().toISOString(), requested_trials: count,
  mode: 'standalone diagnostic process', trials: [], memory_observations: {},
  timing_scope: 'Uncompressed 2 MiB deterministic synthetic bytes; twelve by default, one preceding observed round excluded. No CAD timing or production allocator change.',
  telemetry_scope: 'WDDM Dedicated Usage matches the worker PID and CUDA adapter LUID. nvidia-smi is adapter-wide. Observations run outside timed trials.',
  p95_method: 'nearest rank', api_reference: 'https://docs.nvidia.com/cuda/cuda-driver-api/group__CUDA__VA.html',
};
const child = spawn(options.python, ['-B', workerPath, '--trials', String(count)], {
  stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
});
let stderr = '';
child.stderr.setEncoding('utf8').on('data', chunk => { stderr = (stderr + chunk).slice(-4000); });
child.stdin.on('error', () => {}); // A closed worker is reported by its exit status.
const closed = new Promise(resolveClose => {
  child.on('error', error => resolveClose({ error: String(error) }));
  child.on('close', (code, signal) => resolveClose({ code, signal }));
});
const timeout = setTimeout(() => { child.kill(); }, 120000);
try {
  const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
  for await (const line of lines) {
    const { type, ...data } = JSON.parse(line);
    if (type === 'device' || type === 'allocation' || type === 'observed') report[type] = data;
    else if (type === 'trial') report.trials.push(data);
    else if (type === 'completed') report.context = data;
    else if (type === 'unsupported' || type === 'failed') Object.assign(report, { status: type, ...data });
    else if (type === 'sample') {
      if (!report.device || data.pid !== child.pid) throw new Error('invalid observation target');
      report.worker_pid = data.pid;
      const sample = await recordMemory(data.pid, report.device);
      if (data.cuda_memory) sample.cuda_memory = data.cuda_memory;
      report.memory_observations[data.stage] = sample;
      child.stdin.write('continue\n');
    } else throw new Error('unknown worker event: ' + type);
  }
  const exit = await closed;
  report.worker_exit = exit;
  if (report.device) {
    report.memory_observations.process_exited = await recordMemory(child.pid, report.device);
  }
  if (exit.code === 0) {
    evaluate(report);
    report.status = 'measured';
  } else if (!report.status) {
    throw new Error(exit.error || stderr.trim() || 'worker terminated unexpectedly');
  }
} catch (error) {
  child.kill();
  await closed;
  Object.assign(report, { status: 'failed', error: String(error) });
} finally {
  clearTimeout(timeout);
}
const out = resolve(options.out);
const temp = out + '.' + process.pid + '.tmp';
await writeFile(temp, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
try {
  JSON.parse(await readFile(temp, 'utf8'));
  await rename(temp, out);
} finally {
  await unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw error; });
}
console.log(JSON.stringify({ out, status: report.status, error: report.error, target: report.target,
  release: report.summary?.unmap_plus_release, migration: report.summary?.copy_verify_unmap_release,
  pid_memory: report.pid_memory }));
process.exitCode = report.status === 'measured' ? 0 : report.status === 'unsupported' ? 2 : 1;
