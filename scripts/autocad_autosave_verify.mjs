/** Exercise selected autosave recovery through its public CLI with native DWG observations. */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, copyFile, lstat, mkdir, mkdtemp, open, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { parseArgs, promisify } from "node:util";
import { coreFacts, defaultConsole, lispPath } from "./cad_xref_console.mjs";
import { discover, fileHash } from "./cad_workspace_capsule.mjs";

const run = promisify(execFile);
const { values } = parseArgs({ options: {
  out: { type: "string" }, "native-observation": { type: "string" },
  console: { type: "string", default: defaultConsole }, template: { type: "string" },
  python: { type: "string", default: "python" },
} });
const layer = "CHIMERA_AUTOSAVE_ACCEPT";
const official = "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Understanding-AutoCAD-backup-and-autosave-files.html";

async function jsonCommand(bin, argv, expected = 0) {
  let code = 0, stdout, stderr = "";
  try {
    ({ stdout } = await run(bin, argv, { windowsHide: true, timeout: 420000, maxBuffer: 4000000 }));
  } catch (error) {
    ({ code, stdout, stderr } = error);
  }
  assert.equal(code, expected, (stdout ?? "") + stderr);
  return JSON.parse(stdout);
}

async function edit(dwg, commands) {
  await coreFacts(dwg, out => [
    '(setvar "FILEDIA" 0)', ...commands, '(command "_.QSAVE")',
    '(setq f (open ' + lispPath(out) + ' "w" "utf8"))', '(write-line "CHIMERA-DONE" f)', '(close f)',
  ], { writable: true, consolePath: values.console });
}

async function geometry(dwg) {
  const r = await coreFacts(dwg, out => [
    '(setq f (open ' + lispPath(out) + ' "w" "utf8"))',
    '(setq items (ssget "_X" (list (cons 0 "CIRCLE") (cons 8 "' + layer + '"))))',
    '(write-line (itoa (if items (sslength items) 0)) f)',
    '(if items (progn (setq e (entget (ssname items 0))) (write-line (rtos (cdr (assoc 40 e)) 2 6) f) ' +
      '(write-line (cdr (assoc 5 e)) f)))',
    '(setq dep (tblsearch "BLOCK" "VALVE"))',
    '(write-line (itoa (if dep (cdr (assoc 70 dep)) 0)) f)',
    '(write-line "CHIMERA-DONE" f)', '(close f)',
  ], { consolePath: values.console });
  const count = Number(r.lines[0]);
  return { circles: count, radius: count ? Number(r.lines[1]) : null, handle: count ? r.lines[2] : null,
    valve_resolved: (Number(r.lines.at(-1)) & 32) !== 0, open_ms: r.elapsed_ms };
}

async function trial(dir, template) {
  const source = join(dir, "drawing");
  const host = join(source, "Host.dwg"), valve = join(source, "refs", "Valve.dwg");
  await mkdir(dirname(valve), { recursive: true });
  await Promise.all([copyFile(template, host), copyFile(template, valve)]);
  await edit(host, ['(setvar "REFPATHTYPE" 1)',
    '(command "_.-XREF" "_Attach" ' + lispPath(valve) + ' (list 0.0 0.0 0.0) 1 1 0)']);
  const found = await discover(source, "Host.dwg", values.console);
  assert.equal(found.graph.files.length, 2);
  const graph = join(dir, "base-graph.json"), base = join(dir, "saved.zip");
  await writeFile(graph, JSON.stringify(found.graph), { flag: "wx" });
  const capsule = await jsonCommand(values.python, ["-B", "-m", "chimera_tp", "aether", "--state", join(dir, "sender"),
    "capsule", "capture", source, graph, base]);
  const before = await geometry(host);
  assert.equal(before.circles, 0);
  assert.equal(before.valve_resolved, true);
  await edit(host, ['(entmake \'((0 . "LAYER") (2 . "' + layer + '") (70 . 0) (62 . 3) (6 . "Continuous")))',
    '(entmake (list (cons 0 "CIRCLE") (cons 8 "' + layer + '") (cons 10 (list 730.5 321.25 0.0)) (cons 40 17.25)))']);
  const original = await geometry(host);
  assert.equal(original.radius, 17.25);
  const autosave = join(dir, "Host_1_123.sv$"), destination = join(dir, "Recovered");
  await copyFile(host, autosave);
  const bytes = await fileHash(autosave);
  assert.notEqual(bytes, found.graph.files.find(m => m.path === "Host.dwg").sha256);
  await rename(source, join(dir, "original-offline"));
  const recover = (sourceFile, output, extra = [], code = 0) => jsonCommand(values.python,
    ["-B", "scripts/autocad_autosave.py", "--source", sourceFile, "--output", output,
      "--console", values.console, ...extra], code);
  const pin = ["--base", base, "--base-id", capsule.capsule];
  const noBase = await recover(autosave, destination, [], 1);
  assert.match(noBase.reason, /pinned_xref_capsule_required.*Valve\.dwg/i);
  await assert.rejects(access(destination), { code: "ENOENT" });
  const held = await open(autosave, "r+");
  let busy;
  try { busy = await recover(autosave, destination, pin, 75); }
  finally { await held.close(); }
  assert.equal(busy.reason, "autosave_in_use");
  await assert.rejects(access(destination), { code: "ENOENT" });
  const acDollar = join(dir, "same-content.ac$");
  await copyFile(autosave, acDollar);
  const ac = await recover(acDollar, destination, [], 1);
  assert.match(ac.reason, /select_an_sv_dollar/);
  const bad = await recover(autosave, destination, ["--base", base, "--base-id", "0".repeat(64)], 1);
  assert.match(bad.reason, /identity_mismatch/);
  const invalid = join(dir, "wrong.sv$");
  await writeFile(invalid, "not an AutoCAD drawing", { flag: "wx" });
  assert.match((await recover(invalid, destination, [], 1)).reason, /invalid_autosave_dwg_signature/);
  await assert.rejects(access(destination), { code: "ENOENT" });
  const accepted = await recover(autosave, destination, pin);
  assert.equal(accepted.verified_files, 2);
  const restored = join(destination, "workspace", accepted.entry);
  assert.equal(await fileHash(restored), bytes);
  assert.equal(await fileHash(join(destination, "workspace/refs/Valve.dwg")),
    found.graph.files.find(m => m.path === "refs/Valve.dwg").sha256);
  const after = await geometry(restored);
  assert.deepEqual([after.circles, after.radius, after.handle, after.valve_resolved],
    [1, original.radius, original.handle, true]);
  assert.equal(await fileHash(autosave), bytes);
  const receiptBefore = await fileHash(join(destination, "receipt.json"));
  const duplicate = await recover(autosave, destination, pin, 1);
  assert.equal(await fileHash(join(destination, "receipt.json")), receiptBefore);
  return { fixture_origin: "An independently edited and saved test DWG copied verbatim to .sv$; no timed GUI autosave.",
    initial_drawing: before, independent_candidate_observation: original, recovered_drawing: after,
    selected_autosave_unchanged_sha256: bytes, accepted,
    selected_xref_verified_sha256: await fileHash(join(dir, "original-offline", "refs", "Valve.dwg")),
    no_baseline: noBase.reason, writer_open: busy.reason, ac_dollar: ac.reason, wrong_capsule: bad.reason,
    duplicate_preserved: duplicate.state === "failed", original_drawing_location_unavailable: true };
}

async function main() {
  const template = resolve(values.template ?? join(dirname(values.console), "Sample/Database Connectivity/Floor Plan Sample.dwg"));
  const baselineHash = await fileHash(template);
  const base = await realpath(tmpdir());
  const scratch = await mkdtemp(join(base, "chimera-autosave-accept-"));
  let evidence;
  try {
    evidence = await trial(scratch, template);
  } finally {
    const dest = await realpath(scratch);
    if (dirname(dest) !== base || !basename(dest).startsWith("chimera-autosave-accept-")) throw Error("unexpected test directory");
    await rm(dest, { recursive: true, force: true, maxRetries: 4 });
  }
  assert.equal(await fileHash(template), baselineHash);
  const sources = ["scripts/autocad_autosave.py", "scripts/autocad_autosave_facts.mjs",
    "scripts/autocad_autosave_verify.mjs", "tests/test_autocad_autosave.py",
    "chimera_tp/platform/workspace_capsule.py", "chimera_tp/platform/file_revisions.py"];
  const record = { schema: "chimera.cad.autosave-verification/1", verified_utc: new Date().toISOString(), ...evidence,
    template_hash_unchanged: baselineHash, temporary_fixtures_removed: !(await lstat(scratch).catch(() => null)),
    scope: "Saved drawing bytes and selected DWG XREFs only. No in-memory edits, physical crash, fonts, images or underlays tested.",
    documentation: official, source_sha256: Object.fromEntries(await Promise.all(sources.map(async path => [path, await fileHash(resolve(path))]))) };
  if (values["native-observation"]) record.native_timer_probe = JSON.parse(await readFile(values["native-observation"], "utf8"));
  if (values.out) await writeFile(resolve(values.out), JSON.stringify(record, null, 2) + "\n", { flag: "wx" });
  console.log(JSON.stringify({ verified: true, radius: record.recovered_drawing.radius, files: record.accepted.verified_files }));
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });
