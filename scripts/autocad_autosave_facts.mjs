/** Read the recovery copy's creation GUID and XREFs in native AutoCAD. */
import { mkdtemp, open, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { coreFacts, defaultConsole, lispPath, readXrefs } from "./cad_xref_console.mjs";

async function fingerprint(headerFile) {
  // Autodesk's ASCII DXF HEADER precedes all entities. Never load a full
  // exported drawing in memory just to read two GUID records.
  const file = await open(headerFile, "r");
  try {
    const chunk = Buffer.alloc(512 * 1024);
    const { bytesRead } = await file.read(chunk);
    const pairs = chunk.toString("latin1", 0, bytesRead).split(/\r?\n/);
    let header = false;
    let guid, version;
    for (let i = 0; i + 1 < pairs.length; i += 2) {
      const code = pairs[i].trim();
      const value = pairs[i + 1].trim();
      if (code === "2" && value === "HEADER") header = true;
      if (header && code === "0" && value === "ENDSEC") break;
      if (!header || code !== "9" || pairs[i + 2]?.trim() !== "2") continue;
      if (value === "$FINGERPRINTGUID") guid = pairs[i + 3]?.trim().toUpperCase();
      if (value === "$VERSIONGUID") version = pairs[i + 3]?.trim().toUpperCase();
    }
    const valid = /^\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$/;
    if (!valid.test(guid) || /^\{0{8}(?:-0{4}){3}-0{12}\}$/.test(guid)) {
      throw Error("drawing_creation_guid_unavailable");
    }
    return { fingerprint_guid: guid, version_guid: valid.test(version) ? version : null };
  } finally {
    await file.close();
  }
}

export async function drawingFacts(drawing, { consolePath = defaultConsole } = {}) {
  // AutoCAD exposes this GUID through DXF HEADER rather than GETVAR.
  const base = await realpath(tmpdir());
  const scratch = await mkdtemp(join(base, "chimera-autosave-facts-"));
  const header = join(scratch, "observation.dxf");
  try {
    const result = await coreFacts(resolve(drawing), facts => [
      '(setvar "FILEDIA" 0)',
      '(command "_.DXFOUT" ' + lispPath(header) + ' "")',
      ...readXrefs(facts),
    ], { consolePath });
    const identity = await fingerprint(header);
    if (result.lines.length % 3 !== 0) throw Error("invalid_dwg_xref_inventory");
    const xrefs = [];
    for (let i = 0; i < result.lines.length; i += 3) {
      const flags = Number(result.lines[i + 1]);
      if (!Number.isSafeInteger(flags)) throw Error("invalid_xref_status");
      xrefs.push({ block: result.lines[i], flags, saved_path: result.lines[i + 2] });
    }
    return { ...identity, xrefs, native_open_ms: result.elapsed_ms };
  } finally {
    if (dirname(await realpath(scratch)) !== base) throw Error("unexpected DXF directory");
    await rm(scratch, { recursive: true, force: true, maxRetries: 3 });
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const { values } = parseArgs({ options: {
    file: { type: "string" }, console: { type: "string", default: defaultConsole },
  } });
  drawingFacts(values.file, { consolePath: values.console }).then(
    value => console.log(JSON.stringify(value)),
    error => { console.error(error.message); process.exitCode = 1; },
  );
}
