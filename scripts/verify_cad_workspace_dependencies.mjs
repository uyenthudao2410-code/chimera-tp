/** Reopen two independent versions of a relocated nested DWG XREF tree. */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, copyFile, lstat, mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";
import { coreFacts, defaultConsole, lispPath } from "./cad_xref_console.mjs";
import { fileHash } from "./cad_workspace_capsule.mjs";

const run = promisify(execFile);
const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const { values: args } = parseArgs({ options: {
  template: { type: "string" }, console: { type: "string", default: defaultConsole },
  python: { type: "string", default: "python" }, out: { type: "string" }, peer: { type: "string" },
} });
const names = ["Host.dwg", "refs/Assembly.dwg", "refs/parts/Valve.dwg"];
const layer = "CHIMERA_CAPSULE_FEATURE";

async function command(bin, argv, errorCode = 0) {
  try {
    const result = await run(bin, argv, { cwd: repo, windowsHide: true, timeout: 180000, maxBuffer: 1024 * 1024 });
    assert.equal(errorCode, 0, "expected the operation to fail");
    return JSON.parse(result.stdout);
  } catch (error) {
    if (!errorCode || error.code !== errorCode) throw error;
    return error.stdout?.trim() ? JSON.parse(error.stdout) : { error: error.stderr.trim() };
  }
}

function capsule(state, argv, exit = 0) {
  return command(args.python, ["-B", "-m", "chimera_tp", "aether", "--state", state, "capsule", ...argv], exit);
}

function graph(root, name, output, exit = 0) {
  return command(process.execPath, ["scripts/cad_workspace_capsule.mjs", "--root", root, "--entry", name,
    "--out", output, "--console", args.console], exit);
}

async function edit(drawing, commands) {
  await coreFacts(drawing, out => [
    '(setvar "FILEDIA" 0)', ...commands, '(command "_.QSAVE")',
    `(setq f (open ${lispPath(out)} "w" "utf8"))`, '(write-line "CHIMERA-DONE" f)', '(close f)',
  ], { writable: true, consolePath: args.console });
}

function attach(drawing, child) {
  return edit(drawing, ['(setvar "REFPATHTYPE" 1)',
    `(command "_.-XREF" "_Attach" ${lispPath(child)} (list 0.0 0.0 0.0) 1 1 0)`]);
}

async function inspectHost(drawing) {
  const result = await coreFacts(drawing, out => [
    `(setq f (open ${lispPath(out)} "w" "utf8"))`,
    '(setq top (tblsearch "BLOCK" "Assembly") dep (tblsearch "BLOCK" "Valve"))',
    '(write-line (if top (itoa (cdr (assoc 70 top))) "MISSING") f)',
    '(write-line (if dep (itoa (cdr (assoc 70 dep))) "MISSING") f)',
    '(setq ref (ssget "_X" (list (cons 0 "INSERT") (cons 2 "Assembly"))))',
    '(write-line (itoa (if ref (sslength ref) 0)) f)',
    '(setq obj (if top (cdr (assoc -2 top))) inserted 0)',
    '(while obj (setq e (entget obj)) (if (and (= "INSERT" (cdr (assoc 0 e))) ' +
      '(= "VALVE" (strcase (cdr (assoc 2 e))))) (setq inserted (1+ inserted))) (setq obj (entnext obj)))',
    '(write-line (itoa inserted) f)',
    '(setq obj (if dep (cdr (assoc -2 dep))))',
    '(while obj (setq e (entget obj)) ' +
      `(if (and (= "CIRCLE" (cdr (assoc 0 e))) (wcmatch (strcase (cdr (assoc 8 e))) "*${layer}") ` +
      '(equal (cdr (assoc 10 e)) (list 901.25 912.75 0.0) 1e-9)) ' +
      '(progn (write-line (cdr (assoc 5 e)) f) (write-line (cdr (assoc 8 e)) f) ' +
      '(write-line (rtos (cdr (assoc 40 e)) 2 6) f))) (setq obj (entnext obj)))',
    '(write-line "CHIMERA-DONE" f)', '(close f)',
  ], { consolePath: args.console });
  const [top, leaf, inserts, nestedInserts, handle, qualifiedLayer, radius] = result.lines;
  assert.ok((Number(top) & 32) !== 0, "AutoCAD did not resolve the top-level xref: " + result.lines);
  assert.ok((Number(leaf) & 32) !== 0, "AutoCAD did not resolve the nested xref: " + result.lines);
  assert.equal(Number(inserts), 1);
  assert.equal(Number(nestedInserts), 1);
  assert.equal(result.lines.length, 7, "expected exactly one sentinel circle in the loaded nested block: " + result.lines);
  assert.match(handle, /^[\dA-F]+$/i);
  assert.equal(qualifiedLayer.toUpperCase(), "VALVE|" + layer);
  return { direct_native_flags: Number(top), nested_native_flags: Number(leaf), inserted_top_blocks: Number(inserts),
    inserted_leaf_blocks_in_assembly: Number(nestedInserts),
    handle, qualified_layer: qualifiedLayer, radius: Number(radius), center: [901.25, 912.75, 0], open_ms: result.elapsed_ms };
}

async function runTrial(dir, template) {
  const source = join(dir, "source"), sender = join(dir, "sender");
  await mkdir(join(source, "refs/parts"), { recursive: true });
  for (const name of names) await copyFile(template, join(source, name));
  const [host, assembly, valve] = names.map(n => join(source, n));
  await edit(valve, [
    `(entmake '((0 . "LAYER") (2 . "${layer}") (70 . 0) (62 . 3) (6 . "Continuous")))`,
    `(entmake (list (cons 0 "CIRCLE") (cons 8 "${layer}") (cons 10 (list 901.25 912.75 0.0)) (cons 40 17.0)))`,
  ]);
  await attach(assembly, valve);
  await attach(host, assembly);
  const versions = [];
  let stale;
  for (const radius of [17, 29.5]) {
    if (versions.length) {
      await edit(valve, [
        `(setq id (ssname (ssget "_X" (list (cons 0 "CIRCLE") (cons 8 "${layer}"))) 0) item (entget id))`,
        `(entmod (subst (cons 40 ${radius}) (assoc 40 item) item))`, '(entupd id)',
      ]);
      const rejected = join(dir, "stale.zip");
      stale = await capsule(sender, ["capture", source, versions[0].graphFile, rejected], 1);
      assert.equal(stale.error, "stale_workspace_member:" + names[2]);
      await assert.rejects(lstat(rejected), { code: "ENOENT" });
    }
    const graphFile = join(dir, "graph-" + versions.length + ".json");
    const info = await graph(source, names[0], graphFile);
    const spec = JSON.parse(await readFile(graphFile, "utf8"));
    assert.deepEqual(spec.files.map(f => f.path).sort(), [...names].sort());
    const edges = info.xrefs.map(r => [r.source, r.destination]);
    assert.ok(edges.some(([a, b]) => a === names[0] && b === names[1]));
    assert.ok(edges.some(([a, b]) => a === names[1] && b === names[2]));
    assert.ok(edges.every(([a, b]) => names.includes(a) && names.includes(b)));
    const archive = join(dir, "version-" + versions.length + ".zip");
    const saved = await capsule(sender, ["capture", source, graphFile, archive]);
    assert.equal(saved.distinct_objects, 3);
    versions.push({ graphFile, archive, spec, native: info.xrefs, ...saved, radius });
  }
  assert.notEqual(versions[0].capsule, versions[1].capsule);
  assert.equal(versions[0].spec.files[0].sha256, versions[1].spec.files[0].sha256);
  assert.equal(versions[0].spec.files[1].sha256, versions[1].spec.files[1].sha256);
  assert.notEqual(versions[0].spec.files[2].sha256, versions[1].spec.files[2].sha256);

  const outsider = join(dir, "selection");
  await mkdir(outsider);
  const bad = join(outsider, "Outside.dwg");
  await copyFile(template, bad);
  await attach(bad, valve);
  const badOutput = join(dir, "unexpected.json");
  const refusal = await graph(outsider, "Outside.dwg", badOutput, 1);
  assert.match(refusal.error, /external_workspace_path/);
  await assert.rejects(lstat(badOutput), { code: "ENOENT" });
  await rename(source, join(dir, "offline-original-location"));
  await rename(sender, join(dir, "offline-sender-state"));
  await assert.rejects(access(host), { code: "ENOENT" });

  const measurements = [];
  let missing, missingNative;
  for (const [i, v] of versions.entries()) {
    const receiver = join(dir, "receiver-" + i), destination = join(dir, "relocated-version-" + i);
    let archive = v.archive;
    let peerFacts;
    if (args.peer) {
      archive = join(dir, "recaptured-on-linux-" + i + ".zip");
      peerFacts = await command(args.python, ["-B", "scripts/verify_capsule_peer.py",
        v.archive, v.capsule, archive, "--peer", args.peer]);
      const memberMap = list => Object.fromEntries(list.map(item => [item.path, [item.bytes, item.sha256]]));
      assert.deepEqual(memberMap(peerFacts.members_read_from_linux_filesystem), memberMap(v.spec.files));
      assert.equal(peerFacts.input_archive_sha256, await fileHash(v.archive));
      assert.equal(peerFacts.returned_archive_sha256, await fileHash(archive));
      await rename(v.archive, join(dir, "offline-original-archive-" + i + ".zip"));
      await assert.rejects(access(v.archive), { code: "ENOENT" });
    }
    const portable = await capsule(receiver, ["verify", archive, v.capsule]);
    assert.equal(portable.ok, true);
    assert.equal(portable.checked_directory, false);
    assert.equal(portable.verified_objects, 3);
    await capsule(receiver, ["restore", archive, v.capsule, destination]);
    const verified = await capsule(receiver, ["verify", archive, v.capsule, destination]);
    assert.equal(verified.ok, true);
    assert.equal(verified.checked, 3);
    const actual = await inspectHost(join(destination, names[0]));
    assert.equal(actual.radius, v.radius);
    const reopenedGraph = join(dir, "relocated-" + i + ".json");
    const independent = await graph(destination, names[0], reopenedGraph);
    assert.deepEqual(JSON.parse(await readFile(reopenedGraph, "utf8")), v.spec);
    assert.deepEqual(independent.xrefs, v.native);
    measurements.push({ sequence: i + 1, capsule_sha256: v.capsule, archive_bytes: v.archive_bytes,
      capsule_objects_checked_offline: portable.verified_objects, restored_files: verified.checked,
      members: v.spec.files, xrefs: independent.xrefs, native_host: actual,
      ...(peerFacts ? { peer_roundtrip: peerFacts } : {}) });
    if (i === 0) {
      const leaf = join(destination, names[2]);
      await rename(leaf, join(dir, "withheld-leaf.dwg"));
      missing = await capsule(receiver, ["verify", archive, v.capsule, destination], 1);
      assert.deepEqual(missing.problems, [{ path: names[2], reason: "missing" }]);
      missingNative = await graph(destination, names[0], join(dir, "missing.json"), 1);
      assert.match(missingNative.error, /missing_workspace_xref: refs\/parts\/Valve.dwg/);
    }
  }
  assert.equal(measurements[0].native_host.handle, measurements[1].native_host.handle);
  if (args.peer) {
    assert.notEqual(measurements[0].peer_roundtrip.attempt_id, measurements[1].peer_roundtrip.attempt_id);
  }
  return {
    schema: "chimera.cad.workspace-dependencies/1", verified_utc: new Date().toISOString(),
    template, template_sha256: await fileHash(template), console: args.console,
    native_mode: "AutoCAD Core Console read-only open of the restored host, queried through its loaded nested block",
    original_and_sender_unavailable_before_restore: true, receiver_stores: 2, measurements,
    transport: args.peer ? "Windows -> isolated Linux restore and recapture -> clean Windows restore" : "local",
    stale_graph_capture: stale.error, missing_file: missing.problems[0], native_missing_xref: names[2],
    outside_selection: "external_workspace_path", partial_archives_or_destination_after_rejection: false,
    scope: "Selected saved DWG XREF tree. Native fonts, images, PDF underlays, plot styles, unsaved GUI state and first interactive frame are outside this measurement.",
  };
}

async function main() {
  const base = await realpath(tmpdir());
  const dir = await mkdtemp(join(base, "chimera-cad-deps-"));
  const prior = JSON.parse(await readFile(join(repo, "tasks", "cad_revision_adaptive.json"), "utf8"));
  const template = args.template ? resolve(args.template) : prior.template;
  const original = await fileHash(template);
  let evidence;
  try {
    evidence = await runTrial(dir, template);
    assert.equal(original, await fileHash(template));
  } finally {
    const owned = await realpath(dir);
    assert.equal(dirname(owned), base);
    assert.match(basename(owned), /^chimera-cad-deps-/);
    await rm(owned, { recursive: true, force: true, maxRetries: 3 });
  }
  evidence.temporary_fixtures_removed = true;
  evidence.template_unchanged = true;
  evidence.source_sha256 = {};
  for (const name of [
    "chimera_tp/platform/workspace_capsule.py", "chimera_tp/platform/file_revisions.py",
    "scripts/cad_xref_console.mjs", "scripts/cad_workspace_capsule.mjs",
    "scripts/verify_cad_workspace_dependencies.mjs", "tests/test_workspace_capsule.py",
    ...(args.peer ? ["scripts/verify_capsule_peer.py"] : []),
  ]) {
    evidence.source_sha256[name] = await fileHash(join(repo, name));
  }
  if (args.out) await writeFile(resolve(args.out), JSON.stringify(evidence, null, 2) + "\n", { flag: "wx" });
  console.log(JSON.stringify({ versions: evidence.measurements.length, verified: true }));
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });
