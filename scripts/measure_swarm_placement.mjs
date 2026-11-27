/** Compare independent Windows compilers with two CLI clients sharing a build on either host. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import { parseArgs, promisify } from "node:util";

const root = fileURLToPath(new URL("../", import.meta.url));
const swarm = join(root, "scripts", "cad_swarm_job.py");
const accounted = join(root, "scripts", "placement_windows_cpu.py");
const build = join(root, "scripts", "cad_build_job.py");
const exec = promisify(execFile);
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const sites = ["local", "local-shared", "remote"];
const schedule = [
  [0, 1, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0], [0, 2, 1], [1, 0, 2],
];
const cpuArchive = {
  release: "https://www.python.org/downloads/release/python-3144/",
  url: "https://www.python.org/ftp/python/3.14.4/python-3.14.4-embed-amd64.zip",
  sha256: "cda80a9b1e75c0f1b4f9872ca1b417f0d19bce32facc811aea9180e70fad5fb9",
};

async function execute(file, args, timeout = 60000) {
  const result = await exec(file, args, { cwd: root, timeout, windowsHide: true, maxBuffer: 4 * 1024 * 1024 });
  return result.stdout.trim();
}

const quoteSh = value => "'" + value.replaceAll("'", "'\\''") + "'";
function peerCommand(peer, argv) {
  return execute("ssh", ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
    "UpdateHostKeys=no", "-o", "ConnectTimeout=6", peer, argv.map(quoteSh).join(" ")], 20000);
}

const identity = `import hashlib, json, marshal, pathlib, platform, sys
print(json.dumps({"version": list(sys.version_info[:3]), "implementation": platform.python_implementation(),
                  "build": sys.version, "marshal": marshal.version, "architecture": platform.machine(),
                  "executable_sha256": hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest()}))`;

const makeOracle = `import hashlib, json, marshal, pathlib, sys
bundle = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
manifest = {}
for name, source in bundle["files"]:
    bytecode = compile(source, name, "exec", flags=0, dont_inherit=True, optimize=0)
    manifest[name] = hashlib.sha256(marshal.dumps(bytecode)).hexdigest()
print(json.dumps(manifest))`;

async function markerCounter(python, op, folder) {
  const query = "import json,sys;sys.path.insert(0,'scripts');from verify_guarded_build import counter;" +
    "print(json.dumps(counter(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)))";
  return JSON.parse(await execute(python, ["-B", "-c", query, op, ...(folder ? [folder] : [])], 25000));
}

async function localMarkers(folder) {
  const files = await readdir(folder);
  const records = [];
  for (const name of files) {
    assert.match(name, /^[0-9a-f]{32}\.json$/);
    const record = JSON.parse(await readFile(join(folder, name), "utf8"));
    assert.equal(name, record.instance + ".json");
    records.push(record);
  }
  return records;
}

function median(vals) {
  const sorted = vals.toSorted((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function summarize(rows) {
  const methods = {};
  for (const name of sites) {
    const selected = rows.filter(row => row.site === name);
    methods[name] = {
      completed_sets: selected.length,
      compiler_processes: selected.reduce((n, r) => n + r.independent_markers.length, 0),
      median_wall_s: median(selected.map(r => r.wall_s)),
      median_longest_worker_s: median(selected.map(r => Math.max(...r.compiler_instances.map(w => w.wall_s)))),
      median_compiler_cpu_s: median(selected.map(r => r.compiler_cpu_s)),
      median_windows_tree_cpu_s: median(selected.map(r => r.windows_process_tree.total_cpu_s)),
    };
  }
  const pairs = [...new Set(rows.map(r => r.set))].map(set => {
    const times = Object.fromEntries(rows.filter(r => r.set === set).map(r => [r.site, r.wall_s]));
    const cpu = Object.fromEntries(rows.filter(r => r.set === set).map(r => [r.site, r.windows_process_tree.total_cpu_s]));
    return {
      set,
      shared_windows_vs_independent_windows: times["local-shared"] / times.local,
      linux_vs_shared_windows: times.remote / times["local-shared"],
      linux_vs_independent_windows: times.remote / times.local,
      windows_cpu_shared_vs_independent: cpu["local-shared"] / cpu.local,
      windows_cpu_remote_vs_local_shared: cpu.remote / cpu["local-shared"],
    };
  });
  const comparison = {};
  for (const metric of Object.keys(pairs[0]).filter(k => k !== "set")) {
    const ratios = pairs.map(r => r[metric]);
    comparison[metric] = { median_ratio: median(ratios), range: [Math.min(...ratios), Math.max(...ratios)],
      numerator_faster_sets: ratios.filter(r => r < 1).length };
  }
  return { methods, paired_ratios: pairs, comparison };
}

async function run(a) {
  const folder = await mkdtemp(join(tmpdir(), "chimera-placement-trials-"));
  const winCounter = join(folder, "markers");
  const input = join(folder, "input.json");
  const oraclePath = join(folder, "oracle.json");
  const cfgPath = join(folder, "counters.json");
  const ssh = "svhome";
  let receiver;
  let final;
  try {
    const beacon = await fetch("http://127.0.0.1:9780/.well-known/chimera.json",
      { signal: AbortSignal.timeout(5000) }).then(r => r.json());
    assert.equal(beacon.cartridges.hyper_desk.status, "active");
    const [win, linux] = await Promise.all([
      execute(a.compiler, ["-I", "-B", "-S", "-c", identity]).then(JSON.parse),
      peerCommand(ssh, ["python3", "-I", "-B", "-S", "-c", identity]).then(JSON.parse),
    ]);
    assert.deepEqual(win.version, linux.version, "exact CPython patch version must match");
    assert.equal(win.implementation, "CPython");
    assert.equal(win.implementation, linux.implementation);
    assert.equal(win.marshal, linux.marshal);
    const executables = { windows: win, linux };
    if (a["compiler-archive"]) {
      assert.equal(sha(await readFile(a["compiler-archive"])), cpuArchive.sha256);
      executables.windows.archive = cpuArchive;
    }
    await mkdir(winCounter);
    receiver = (await markerCounter(a.python, "start")).directory;
    await writeFile(cfgPath, JSON.stringify({ windows: winCounter, linux: receiver }), { flag: "wx" });
    const inputs = JSON.parse(await execute(a.python, ["-B", build, "prepare", input, "--rounds", String(a.rounds)]));
    const raw = await readFile(input);
    assert.equal(sha(raw), inputs.input_sha256);
    const bundle = JSON.parse(raw);
    const sources = Object.fromEntries(bundle.files.map(([file, text]) => [file, sha(Buffer.from(text))]));
    const oracle = JSON.parse(await execute(a.compiler, ["-I", "-B", "-S", "-c", makeOracle, input]));
    assert.deepEqual(Object.keys(oracle).sort(), Object.keys(sources).sort());
    await writeFile(oraclePath, JSON.stringify(oracle), { flag: "wx" });
    await execute(a.python, ["-B", swarm, "prepare", input, "--verify-bytecode", "--counter-paths", cfgPath]);
    const rows = [];
    const seen = new Set();
    const keys = new Set();
    const started = new Date().toISOString();
    const sweep = a["smoke-only"] ? [schedule[0]] : schedule;
    for (const [index, sequence] of sweep.entries()) {
      for (const slot of sequence) {
        const site = sites[slot];
        const start = performance.now();
        const printed = await execute(a.python, ["-B", accounted, site, input, "--peer", ssh, "--compiler",
          a.compiler, "--bytecode-oracle", oraclePath, "--timeout", "120"], 240000);
        const wall = (performance.now() - start) / 1000;
        const record = JSON.parse(printed);
        assert.equal(record.windows_process_tree.active_at_close, 0);
        assert(record.windows_process_tree.total_cpu_s > 0);
        if (site !== "remote") assert(record.windows_process_tree.total_cpu_s + 0.05 >= record.compiler_cpu_s);
        assert.equal(record.input_sha256, inputs.input_sha256);
        if (rows.length) assert.equal(record.result_sha256, rows[0].result_sha256);
        assert(!keys.has(record.cold_environment_id));
        keys.add(record.cold_environment_id);
        const [local, remote] = await Promise.all([localMarkers(winCounter), markerCounter(a.python, "read", receiver)]);
        const all = [...local.map(r => ({ ...r, host: "windows" })), ...remote.map(r => ({ ...r, host: "linux" }))];
        const added = all.filter(r => !seen.has(r.instance));
        assert.equal(added.length, site === "local" ? 2 : 1, "unexpected number of actual compiler outputs");
        assert.deepEqual(added.map(r => r.instance).sort(), record.compiler_instances.map(w => w.id).sort());
        for (const mark of added) {
          assert.equal(mark.host, site === "remote" ? "linux" : "windows");
          const worker = record.compiler_instances.find(w => w.id === mark.instance);
          assert.equal(worker.pid, mark.pid);
          assert.equal(worker.python, win.version.join("."));
          assert.equal(mark.cpu_s, worker.cpu_s);
          assert(mark.cpu_s > 0);
          assert.equal(mark.result_sha256, record.result_sha256);
          seen.add(mark.instance);
        }
        const row = { set: index + 1, position: sequence.indexOf(slot) + 1, site, wall_s: wall,
          independent_markers: added, ...record };
        rows.push(row);
        process.stdout.write(JSON.stringify({ set: row.set, site, wall_s: +wall.toFixed(3),
          compilers: added.length, cpu_s: +record.compiler_cpu_s.toFixed(3) }) + "\n");
      }
    }
    const guardArgs = ["-B", "-c", "import json; from chimera_tp.platform.work_admission import peer_assessment;" +
      "d=peer_assessment({});print(json.dumps({k:d.get(k) for k in ('reason','effective_policy')}))"];
    const policy = JSON.parse(await execute(a.python, guardArgs, 25000));
    final = { schema: "chimera.swarm-placement/1", started_utc: started, ended_utc: new Date().toISOString(),
      environment: { beacon_version: beacon.version, desktop: beacon.node_name, peer: ssh, compilers: executables,
        receiver_policy_after_run: policy }, workload: { ...inputs, source_utf8_sha256: sources,
        bytecode_sha256: oracle, units_per_request: a.rounds * bundle.files.length },
      protocol: { sets: sweep.length, requests_per_arm: 2, arms: sites, order: sweep.map(x => x.map(i => sites[i])),
        cache: "Fresh randomized build environment identifier per arm and set. OS, executable and file caches uncontrolled.",
        intervals: "Each wall interval starts before the Windows accountant and its gated launcher and ends after both requests and receipt validation. Preparation, cleanup and independent marker reads are outside these intervals.",
        cpu: "Compiler CPU is process_time per unique compiler. Windows Job Object BasicAccountingInfo independently covers the full local trial tree including its launcher, wrapper, clients, local compilers and SSH. The Node recorder, outer Python accountant, unrelated processes and remote Linux ancestors are excluded. The two CPU counters overlap for local builds and must not be added.",
        product: "Last-round marshal bytes of each of four shipped Python modules hashed; every pair validates every digest against an independent interpreter invocation.",
        guard: "Remote jobs entered through normal Swarm receiver admission. No foreground CAD frames, production changes or cloud runtimes." },
      rows, summary: summarize(rows), source_sha256: {} };
    for (const name of ["scripts/measure_swarm_placement.mjs", "scripts/cad_swarm_job.py", "scripts/placement_windows_cpu.py",
      "scripts/cad_build_job.py", "scripts/verify_guarded_build.py", "chimera_tp/platform/guarded_build.py",
      "chimera_tp/platform/local_build.py", "chimera_tp/platform/windows_build_job.py",
      "chimera_tp/platform/build_worker.py", "chimera_tp/platform/peer_guard.py"]) {
      final.source_sha256[name] = sha(await readFile(join(root, name)));
    }
  } finally {
    try {
      if (receiver) await markerCounter(a.python, "finish", receiver);
    } finally {
      assert.equal(dirname(folder), tmpdir());
      assert.match(basename(folder), /^chimera-placement-trials-[a-z0-9]+$/i);
      await rm(folder, { recursive: true, force: false, maxRetries: 3, retryDelay: 200 });
    }
  }
  await assert.rejects(access(folder), { code: "ENOENT" });
  final.temporary_counters_removed = true;
  if (a.out) await writeFile(resolve(a.out), JSON.stringify(final, null, 2) + "\n");
  console.log(JSON.stringify(final.summary.methods));
}

const { values } = parseArgs({ options: {
  compiler: { type: "string" }, "compiler-archive": { type: "string" }, python: { type: "string", default: "python" },
  rounds: { type: "string", default: "120" }, out: { type: "string" }, "smoke-only": { type: "boolean" },
} });
values.rounds = Number(values.rounds);
if (process.platform !== "win32" || !values.compiler || !Number.isInteger(values.rounds) ||
    values.rounds < 1 || values.rounds > 600 || (!values["smoke-only"] && !values.out)) {
  throw new Error("Requires Windows, --compiler matching svhome CPython exactly, --rounds 1..600 and --out FILE (or --smoke-only).");
}
await run(values);
