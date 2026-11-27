/** Verify a revision chain by reopening DWGs in Autodesk's native headless engine. */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { constants } from "node:fs";
import { chmod, copyFile, mkdir, mkdtemp, readFile, realpath, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";
import { sha256 } from "./cad_probe_runtime.mjs";

const run = promisify(execFile);
const repo = fileURLToPath(new URL("../", import.meta.url));
const layer = "CHIMERA_REVISION_PROBE";
const sampleDefinition = JSON.parse(await readFile(join(repo, "tasks", "cad_build_preflight.json"), "utf8"));
const formats = new Map([
  ["AC1015", "2000"], ["AC1018", "2004"], ["AC1021", "2007"], ["AC1024", "2010"],
  ["AC1027", "2013"], ["AC1032", "2018"],
]);

const { values: args } = parseArgs({ options: {
  dwg: { type: "string", default: sampleDefinition.drawing },
  console: { type: "string", default: join(process.env.ProgramFiles ?? "C:/Program Files",
    "Autodesk", "AutoCAD 2027", "accoreconsole.exe") },
  python: { type: "string", default: "python" },
  out: { type: "string" },
} });

function decode(buffer) {
  return buffer.subarray(0, 80).includes(0) ? buffer.toString("utf16le") : buffer.toString("utf8");
}

function lispString(value) {
  return JSON.stringify(value.replaceAll("\\", "/"));
}

async function revision(state, ...cliArgs) {
  const { stdout } = await run(args.python, ["-B", "-m", "chimera_tp", "aether", "--state", state,
    "revision", ...cliArgs], { cwd: repo, timeout: 30000, windowsHide: true, encoding: "utf8" });
  return JSON.parse(stdout);
}

function entityQuery() {
  return '(progn (setq cs (ssget "_X" (list (cons 0 "CIRCLE") (cons 10 (list 901.25 912.75 0.0)) (cons 410 "Model")))) ' +
    '(setq revcount (if cs (sslength cs) 0)) ' +
    '(setq info (if (= revcount 1) (entget (ssname cs 0)) nil)))';
}

function writeObservation(path) {
  const expr = [
    '(getvar "ACADVER")',
    '(itoa revcount)',
    '(if info (cdr (assoc 5 info)) "-")',
    '(if info (cdr (assoc 8 info)) "-")',
    '(if info (rtos (cdr (assoc 40 info)) 2 6) "-")',
    '(if info (rtos (car (cdr (assoc 10 info))) 2 6) "-")',
    '(if info (rtos (cadr (cdr (assoc 10 info))) 2 6) "-")',
    '(if info (rtos (caddr (cdr (assoc 10 info))) 2 6) "-")',
    '(if lyr (itoa (cdr (assoc 62 lyr))) "-")',
    '(getvar "DWGNAME")',
  ];
  return [
    entityQuery(),
    `(setq lyr (tblsearch "LAYER" "${layer}"))`,
    `(setq fileout (open ${lispString(path)} "w"))`,
    ...expr.map(value => `(write-line ${value} fileout)`),
    "(close fileout)",
  ];
}

function mutate(stage) {
  const change = [];
  if (stage === "add_circle") {
    change.push('(setvar "TILEMODE" 1)',
      `(entmake '((0 . "LAYER") (100 . "AcDbSymbolTableRecord") (100 . "AcDbLayerTableRecord") (2 . "${layer}") (70 . 0) (62 . 2) (6 . "Continuous")))`,
      `(entmake '((0 . "CIRCLE") (8 . "${layer}") (10 901.25 912.75 0.0) (40 . 17.0)))`);
  } else if (stage === "resize_circle") {
    change.push(entityQuery(), "(entmod (subst (cons 40 29.5) (assoc 40 info) info))",
      "(entupd (cdr (assoc -1 info)))");
  } else if (stage === "change_layer_color") {
    change.push(`(setq layerdata (entget (tblobjname "LAYER" "${layer}")))`,
      "(entmod (subst (cons 62 4) (assoc 62 layerdata) layerdata))");
  }
  return change;
}

async function coreConsole(scratch, input, sequence, role, change, saveAs, format) {
  const script = join(scratch, `${sequence}-${role}.scr`);
  const facts = join(scratch, `${sequence}-${role}.txt`);
  const lines = [...change];
  if (saveAs) lines.push(`(command "_.SAVEAS" "${format}" ${lispString(saveAs)})`);
  lines.push(...writeObservation(facts));
  // Reopening uses /readonly, and verification never issues a save.
  await writeFile(script, lines.join("\r\n") + "\r\n", { encoding: "utf8", flag: "wx" });
  const flags = ["/i", input, "/s", script, "/l", "en-US"];
  if (!saveAs) flags.push("/readonly");
  const started = performance.now();
  const { stdout, stderr } = await run(args.console, flags, {
    cwd: scratch, encoding: "buffer", timeout: 60000, maxBuffer: 8 * 1024 * 1024, windowsHide: true,
  });
  const log = decode(stdout) + "\n" + decode(stderr);
  let values;
  try {
    values = (await readFile(facts, "utf8")).replace(/^\uFEFF/, "").trimEnd().split(/\r?\n/);
    assert.equal(values.length, 10);
    assert.equal(values[9].toLowerCase(), basename(saveAs ?? input).toLowerCase());
  } catch (error) {
    throw new Error(`Core Console did not complete ${role} ${sequence}. ${log.slice(-2200)}`, { cause: error });
  }
  const [acadVersion, count, handle, entityLayer, radius, x, y, z, indexedColor] = values;
  return {
    elapsed_ms: Math.round((performance.now() - started) * 100) / 100,
    autocad_version: acadVersion, count: Number(count), handle: handle === "-" ? null : handle,
    layer: entityLayer === "-" ? null : entityLayer, radius: radius === "-" ? null : Number(radius),
    center: x === "-" ? null : [x, y, z].map(Number),
    layer_color: indexedColor === "-" ? null : Number(indexedColor),
  };
}

function validate(observation, sequence, knownHandle) {
  if (sequence === 0) {
    assert.equal(observation.count, 0, "input already contains the selected probe circle");
    assert.equal(observation.layer_color, null, "input already contains the selected probe layer");
    return;
  }
  assert.equal(observation.count, 1);
  assert.match(observation.handle, /^[A-F0-9]+$/i);
  if (knownHandle) assert.equal(observation.handle, knownHandle, "entity handle changed");
  assert.equal(observation.layer, layer);
  assert.equal(observation.radius, sequence === 1 ? 17 : 29.5);
  assert.deepEqual(observation.center, [901.25, 912.75, 0]);
  assert.equal(observation.layer_color, sequence === 3 ? 4 : 2);
}

async function check(source, scratch) {
  const prior = await readFile(source);
  const originalSha = sha256(prior);
  if (resolve(args.dwg) === resolve(sampleDefinition.drawing)) {
    assert.equal(originalSha, sampleDefinition.drawing_sha256, "Autodesk sample no longer matches preflight");
  }
  const header = prior.toString("ascii", 0, 6);
  const format = formats.get(header);
  if (!format) throw new Error("Unsupported input DWG header " + header);

  const working = join(scratch, "working.dwg");
  const sender = join(scratch, "sender");
  const receiver = join(scratch, "receiver");
  await copyFile(source, working, constants.COPYFILE_EXCL);
  await chmod(working, 0o600);

  const rows = [];
  let lastDigest, handle;
  const labels = ["baseline", "add_circle", "resize_circle", "change_layer_color"];
  for (const [sequence, operation] of labels.entries()) {
    let edit;
    if (sequence) {
      const edited = join(scratch, `save-${sequence}.dwg`);
      edit = await coreConsole(scratch, working, sequence, "save", mutate(operation), edited, format);
      validate(edit, sequence, handle);
      await copyFile(edited, working);
    }
    const content = await readFile(working);
    assert.equal(content.toString("ascii", 0, 6), header, "DWG format changed");
    const digest = sha256(content);
    if (lastDigest) assert.notEqual(digest, lastDigest, "edit produced no change");
    const saved = await revision(sender, "capture", working);
    assert.equal(saved.revision, digest);
    const full = join(scratch, `${sequence}.full.zip`);
    const complete = await revision(sender, "export", digest, full);
    const wire = lastDigest ? join(scratch, `${sequence}.selected.zip`) : full;
    const sent = lastDigest ? await revision(sender, "export", digest, wire, "--base", lastDigest) : complete;
    const forced = lastDigest ? await revision(sender, "export", digest, join(scratch, `${sequence}.delta.zip`),
      "--base", lastDigest, "--force-delta") : null;
    if (forced) assert.equal(sent.archive_bytes, Math.min(complete.archive_bytes, forced.archive_bytes));
    assert.equal(sent.archive_bytes, (await stat(wire)).size);
    const received = await revision(receiver, "receive", wire);
    assert.equal(received.revision, digest);
    const reopened = join(scratch, `restored-${sequence}.dwg`);
    await revision(receiver, "restore", digest, reopened);
    assert.equal(sha256(await readFile(reopened)), digest);
    const facts = await coreConsole(scratch, reopened, sequence, "read", [], null, format);
    validate(facts, sequence, handle ?? edit?.handle);
    assert.equal(sha256(await readFile(reopened)), digest, "native verification rewrote the restored input");
    rows.push({ sequence, operation, sha256: digest, base_sha256: lastDigest ?? null,
      bytes: saved.bytes, format_header: header, chunks: saved.chunks, added_chunk_bytes: saved.added_bytes,
      full_archive_bytes: complete.archive_bytes, transferred_archive_bytes: sent.archive_bytes,
      forced_delta_bytes: forced?.archive_bytes ?? null, selected_mode: sent.mode,
      transferred_chunks: sent.included_chunks,
      percent_of_full_archive: Math.round(sent.archive_bytes / complete.archive_bytes * 10000) / 100,
      source_and_restored_sha256_match: true, read_only_reopen: facts, save_elapsed_ms: edit?.elapsed_ms ?? null });
    lastDigest = digest;
    if (sequence === 1) handle = facts.handle;
  }
  const history = await revision(sender, "history", working);
  assert.deepEqual(history.map(row => row.revision), rows.map(row => row.sha256).reverse());
  assert.equal(sha256(await readFile(source)), originalSha, "template checksum changed");
  return { schema: 1, verified_utc: new Date().toISOString(), template: source, template_sha256: originalSha,
    console: await realpath(args.console), input_format: header, save_as_version: format,
    geometry_units: "drawing units", revisions: rows, matched_history_entries: history.length,
    receiver: "Independent local store receives the smaller ZIP for each revision and reopens all restored DWGs",
    timing_scope: "Core Console process wall time for each save or read-only open",
    template_unchanged: true };
}

async function main() {
  const source = await realpath(args.dwg);
  const base = await realpath(tmpdir());
  const scratch = await mkdtemp(join(base, "chimera-cad-revisions-"));
  let report;
  try {
    report = await check(source, scratch);
  } finally {
    const resolved = await realpath(scratch);
    assert.equal(dirname(resolved), base);
    assert.ok(basename(resolved).startsWith("chimera-cad-revisions-"));
    await rm(resolved, { recursive: true, force: true, maxRetries: 3 });
  }
  report.removed_temporary_working_files = true;
  if (args.out) {
    const out = resolve(args.out);
    await mkdir(dirname(out), { recursive: true });
    await writeFile(out, JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
  }
  console.log(JSON.stringify(report));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
