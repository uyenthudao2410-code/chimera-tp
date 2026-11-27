import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, mkdtemp, readFile, readdir, realpath, rename, rm, stat, symlink, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");

function processResult(exe, args, cwd, options = {}) {
  const started = performance.now();
  return new Promise((accept, reject) => {
    const child = execFile(exe, args, {
      cwd,
      windowsHide: true,
      timeout: 120000,
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: "1", GIT_CONFIG_NOSYSTEM: "1",
        GIT_CONFIG_GLOBAL: process.platform === "win32" ? "NUL" : "/dev/null" },
    }, (error, stdout, stderr) => {
      const code = error ? error.code : 0;
      if (code !== (options.expectedCode ?? 0)) {
        reject(new Error(`${exe} exited ${code}: ${stderr.slice(-1500)} ${stdout.slice(-250)}`));
        return;
      }
      accept({ pid: child.pid, stdout, duration_ms: Number((performance.now() - started).toFixed(2)) });
    });
  });
}

function git(root, ...args) {
  return processResult("git", ["-c", "user.name=Fixture", "-c", "user.email=fixture@invalid.local",
    "-c", "core.hooksPath=none", "-c", "core.autocrlf=false", "-C", root, ...args], root);
}

async function invoke(root, store, args, expectedCode = 0) {
  const proc = await processResult(process.env.PYTHON || "python",
    ["-B", "-m", "chimera_tp", "swarm-symbols", "--repo", root, "--store", store, ...args],
    repoRoot, { expectedCode });
  return { pid: proc.pid, ms: proc.duration_ms, result: JSON.parse(proc.stdout) };
}

async function createFixture(container) {
  const root = join(container, "worktree");
  const packagePath = join("chimera_tp", "platform");
  const repoPackage = join(repoRoot, packagePath);
  const examplePackage = join(root, packagePath);
  await mkdir(examplePackage, { recursive: true });
  await git(root, "init", "-q", "--template=");
  await git(root, "config", "core.symlinks", "false");
  const inventory = {};
  for (const entry of (await readdir(repoPackage, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isFile() || !entry.name.endsWith(".py")) continue;
    const bytes = await readFile(join(repoPackage, entry.name));
    await writeFile(join(examplePackage, entry.name), bytes);
    inventory[`chimera_tp/platform/${entry.name}`] = sha(bytes);
  }
  const first = "# coding: utf-8\r\n# Note\ftrang\r\nclass LocalProbe:\r\n    async def màu(self):\r\n        return 'az'\r\n";
  await writeFile(join(root, "edited.py"), first);
  await writeFile(join(root, "types.pyi"), "def stub_parameter(street: str) -> bool: ...\n");
  await writeFile(join(root, ".gitignore"), "ignored.py\n");
  await git(root, "add", ".");
  // The Windows core.symlinks=false representation is a plain file with mode 120000 in the index.
  const linkPath = join(root, "outside.py");
  await writeFile(linkPath, "../outside/private.py");
  const linkHash = (await git(root, "hash-object", "-w", "outside.py")).stdout.trim();
  await git(root, "update-index", "--add", "--cacheinfo", `120000,${linkHash},outside.py`);
  await git(root, "commit", "-qm", "Isolated representative Python sources");
  await writeFile(join(root, "ignored.py"), "def excluded_file(): pass\n");
  await writeFile(join(root, "new.py"), "def temporarily_visible(): pass\n");
  const outside = join(container, "outside");
  await mkdir(outside);
  await writeFile(join(outside, "private.py"), "def from_outside(): pass\n");
  await symlink(outside, join(root, "external"), process.platform === "win32" ? "junction" : "dir");
  return { root, first, inventory };
}

async function exercise(container) {
  const { root, first, inventory } = await createFixture(container);
  const cache = join(container, "shared-cache");
  const call = (...args) => invoke(root, cache, args);
  const index = () => call("index");
  const lookup = (id, name, ...extra) => call("find", name, "--snapshot", id, ...extra);
  const rejected = async (target, id, name, pattern) => {
    const { result } = await invoke(target, cache, ["find", name, "--snapshot", id], 1);
    assert.equal(result.ok, false);
    assert.match(result.error, pattern);
    assert.equal(result.matches, undefined);
    return result.error;
  };
  const cold = await Promise.all([index(), index()]);
  const [x, y] = cold.map((r) => r.result);
  assert.notEqual(cold[0].pid, cold[1].pid);
  assert.equal(x.snapshot, y.snapshot);
  assert.equal(x.python_files, Object.keys(inventory).length + 3);
  assert.equal(x.syntax_error_files, 0);
  assert.equal(Math.min(x.parsed_files, y.parsed_files), 0);
  assert.ok(Math.max(x.parsed_files, y.parsed_files) >= Object.keys(inventory).length);
  const pinned = x.snapshot;
  const realPath = "chimera_tp/platform/build_snapshot.py";
  const source = await readFile(join(root, realPath));
  const start = source.toString("utf8").split(/\r\n|\r|\n/).findIndex((l) => /^def capture\(/.test(l)) + 1;
  assert.ok(start > 0);
  const lookupCapture = () => lookup(pinned, "capture", "--path", realPath, "--context-bytes", "79");
  const clients = await Promise.all([lookupCapture(), lookupCapture()]);
  assert.notEqual(clients[0].pid, clients[1].pid);
  assert.deepEqual(clients[0].result, clients[1].result);
  for (const { result } of clients) {
    assert.equal(result.parsed_files, 0);
    assert.equal(result.verified_files, 1);
    assert.equal(result.source_bytes_read, source.length);
    assert.equal(result.matches.length, 1);
    const hit = result.matches[0];
    assert.equal(hit.sha256, inventory[realPath]);
    assert.equal(hit.line, start);
    assert.equal(hit.location, `${realPath}:${start}`);
    assert.match(hit.context, /^def capture\(/);
    assert.ok(hit.context_truncated && Buffer.byteLength(hit.context) <= 79);
  }
  const valid = (await lookup(pinned, "LocalProbe.màu")).result.matches[0];
  assert.equal(valid.line, 4);
  assert.equal(valid.kind, "async def");
  assert.equal(valid.context, "    async def màu(self):\r\n        return 'az'\r\n");
  assert.equal((await lookup(pinned, "stub_parameter")).result.matches[0].file, "types.pyi");
  for (const name of ["excluded_file", "from_outside"]) {
    assert.equal((await lookup(pinned, name)).result.matches.length, 0);
  }
  const edited = join(root, "edited.py");
  const oldStat = await stat(edited);
  await writeFile(edited, first.replace("'az'", "'by'"));
  await utimes(edited, oldStat.atime, oldStat.mtime);
  const stale = await rejected(root, pinned, "LocalProbe.màu", /stale_source/);
  await writeFile(join(root, ".gitignore"), "ignored.py\nnew.py\n");
  await rejected(root, pinned, "temporarily_visible", /stale_source_membership/);
  const refresh = (await index()).result;
  assert.notEqual(refresh.snapshot, pinned);
  assert.equal(refresh.parsed_files, 1);
  assert.match((await lookup(refresh.snapshot, "LocalProbe.màu")).result.matches[0].context, /'by'/);
  const renamedPath = join(root, "renamed.py");
  await rename(edited, renamedPath);
  await rejected(root, refresh.snapshot, "LocalProbe.màu", /stale_source/);
  const renamed = (await index()).result;
  assert.equal(renamed.parsed_files, 0);
  assert.equal((await lookup(renamed.snapshot, "LocalProbe.màu")).result.matches[0].file, "renamed.py");
  await rm(renamedPath);
  const deleted = (await index()).result;
  assert.equal((await lookup(deleted.snapshot, "LocalProbe.màu")).result.matches.length, 0);
  const worktree = join(container, "second-worktree");
  await git(root, "worktree", "add", "--detach", worktree, "HEAD");
  const second = (await invoke(worktree, cache, ["index"])).result;
  assert.equal(second.head, x.head);
  assert.notEqual(second.scope, x.scope);
  await rejected(worktree, pinned, "capture", /snapshot_unavailable_in_this_worktree/);
  const retained = (await lookup(pinned, "capture", "--path", realPath)).result;
  assert.equal(retained.matches[0].sha256, sha(source));
  await writeFile(join(root, "broken.py"), "def invalid(\n");
  const broken = (await index()).result;
  assert.equal(broken.syntax_error_files, 1);
  assert.equal(broken.syntax_errors_sample[0].path, "broken.py");
  return {
    schema: "chimera.swarm-symbols/1", verified_utc: new Date().toISOString(),
    sources: "Isolated Git worktree copied from the current chimera_tp/platform/*.py; plus three local test files.",
    platform_module_count: Object.keys(inventory).length, input_module_digests: inventory,
    tracked_head: x.head, python_snapshot: pinned, linked_worktree_isolated: true,
    simultaneous_indexers: cold.map(({ pid, ms, result }) => ({ pid, cli_wall_ms: ms,
      python_files: result.python_files, parsed_files: result.parsed_files, source_bytes_read: result.source_bytes_read })),
    simultaneous_readers: clients.map(({ pid, ms, result }) => ({ pid, cli_wall_ms: ms,
      parsed_files: result.parsed_files, verified_files: result.verified_files, source_bytes_read: result.source_bytes_read,
      context_utf8_bytes: result.context_utf8_bytes, location: result.matches[0].location,
      sha256: result.matches[0].sha256 })),
    independent_location_and_sha_match: true, retained_snapshot_readable_for_unchanged_member: true,
    dirty_same_size_stale: stale, edited_files_parsed: refresh.parsed_files, renamed_files_parsed: renamed.parsed_files,
    deleted_definition_absent: true, ignored_and_links_excluded: true, partial_syntax_failure_visible: true,
    scope: "Index hashes the Python inventory. Find verifies just the returned files against a pinned snapshot. Excerpts have a shared UTF-8 byte budget. No LLM calls or token measurements.",
  };
}

test("Independent agents share parsing and verify bounded source excerpts", async () => {
  const parent = await realpath(tmpdir());
  const container = await mkdtemp(join(parent, "chimera-symbols-proof-"));
  let report;
  try {
    report = await exercise(container);
  } finally {
    const actual = await realpath(container);
    assert.equal(dirname(actual), parent);
    assert.match(basename(actual), /^chimera-symbols-proof-[A-Za-z0-9_-]+$/);
    await rm(actual, { recursive: true, force: false, maxRetries: 3 });
  }
  await assert.rejects(lstat(container), { code: "ENOENT" });
  if (process.env.CHIMERA_SYMBOLS_EVIDENCE) {
    const output = resolve(process.env.CHIMERA_SYMBOLS_EVIDENCE);
    assert.equal(relative(repoRoot, output).replaceAll("\\", "/"), "tasks/swarm_symbols_verification.json");
    report.fixture_removed = true;
    await writeFile(output, JSON.stringify(report, null, 2) + "\n");
  }
});
