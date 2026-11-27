/** Run a private Core Console script and read its explicit UTF-8 observation file. */
import { execFile } from "node:child_process";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { promisify } from "node:util";

const execute = promisify(execFile);
export const defaultConsole = join(process.env.ProgramFiles ?? "C:/Program Files", "Autodesk",
  "AutoCAD 2027", "accoreconsole.exe");

export function lispPath(value) {
  return JSON.stringify(value.replaceAll("\\", "/"));
}

export async function coreFacts(drawing, commands, { consolePath = defaultConsole, writable = false } = {}) {
  const base = await realpath(tmpdir());
  const scratch = await mkdtemp(join(base, "chimera-xref-core-"));
  try {
    const script = join(scratch, "observe.scr");
    const facts = join(scratch, "facts.txt");
    const instructions = commands(facts);
    await writeFile(script, instructions.join("\r\n") + "\r\n", { flag: "wx", encoding: "utf8" });
    const args = ["/i", drawing, "/s", script, "/l", "en-US"];
    if (!writable) args.push("/readonly");
    const started = performance.now();
    const result = await execute(consolePath, args, { cwd: dirname(drawing), encoding: "buffer",
      windowsHide: true, timeout: 60000, maxBuffer: 8 * 1024 * 1024 });
    let lines;
    try {
      lines = (await readFile(facts, "utf8")).replace(/^\uFEFF/, "").split(/\r?\n/);
      if (lines.pop() !== "" || lines.pop() !== "CHIMERA-DONE") throw Error("missing completion record");
    } catch (error) {
      const buffer = Buffer.concat([result.stdout, result.stderr]);
      const encoding = buffer.subarray(0, 96).includes(0) ? "utf16le" : "utf8";
      throw Error("Core Console did not finish " + basename(drawing) + ". " +
        buffer.toString(encoding).slice(-2400), { cause: error });
    }
    return { lines, elapsed_ms: Math.round((performance.now() - started) * 100) / 100 };
  } finally {
    const checked = await realpath(scratch);
    if (dirname(checked) !== base || !basename(checked).startsWith("chimera-xref-core-")) {
      throw Error("Unexpected Core Console temporary directory");
    }
    await rm(checked, { recursive: true, force: true, maxRetries: 3 });
  }
}

export function readXrefs(facts) {
  // The DXF BLOCK record stores flags (70) and its saved DWG path (1).
  // Core Console may expose nested records with unqualified block names and
  // paths rebased to the current host. Preserve every saved path it exposes.
  return [
    `(setq out (open ${lispPath(facts)} "w" "utf8"))`,
    '(setq rec (tblnext "BLOCK" T))',
    '(while rec (setq bname (cdr (assoc 2 rec)) flags (cdr (assoc 70 rec))) ' +
      '(if (/= 0 (logand 12 flags)) ' +
      '(progn (write-line bname out) (write-line (itoa flags) out) ' +
      '(write-line (if (assoc 1 rec) (cdr (assoc 1 rec)) "") out))) (setq rec (tblnext "BLOCK")))',
    '(write-line "CHIMERA-DONE" out)', "(close out)",
  ];
}
