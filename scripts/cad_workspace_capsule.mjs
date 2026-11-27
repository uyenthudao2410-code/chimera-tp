/** Discover the native DWG XREF graph for a portable Aether workspace capsule. */
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, realpath, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep, win32 } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { coreFacts, defaultConsole, readXrefs } from "./cad_xref_console.mjs";

export async function fileHash(path) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest("hex");
}

function within(root, full) {
  const name = relative(root, full);
  if (!name || name === ".." || name.startsWith(".." + sep) || isAbsolute(name)) {
    throw Error("external_workspace_path: " + full);
  }
  return name.split(sep).join("/");
}

function signature(st) {
  return [st.dev, st.ino, st.size, st.mtimeNs, st.ctimeNs].join("/");
}

async function member(root, proposed) {
  const name = within(root, proposed);
  const actual = await realpath(proposed).catch(error => {
    if (error.code === "ENOENT") throw Error("missing_workspace_xref: " + name, { cause: error });
    throw error;
  });
  const actualName = within(root, actual);
  let current = root;
  for (const part of name.split("/")) {
    current = resolve(current, part);
    if ((await lstat(current)).isSymbolicLink()) throw Error("linked_workspace_xref: " + name);
  }
  if (actualName.toLowerCase() !== name.toLowerCase()) throw Error("linked_workspace_xref: " + name);
  return { actual, name: actualName };
}

export async function discover(rootPath, entryPath, consolePath = defaultConsole) {
  const root = await realpath(resolve(rootPath));
  if (process.platform !== "win32") throw Error("AutoCAD Core Console requires Windows");
  const entry = await member(root, resolve(root, entryPath));
  const pending = [entry], files = new Map(), stamps = new Map(), observations = [];
  while (pending.length) {
    const { actual, name } = pending.pop();
    if (files.has(name)) continue;
    if (files.size >= 8192) throw Error("Workspace exceeds the supported member count");
    const st = await lstat(actual, { bigint: true });
    if (!st.isFile() || st.size > BigInt(Number.MAX_SAFE_INTEGER)) throw Error("invalid_dwg_member: " + name);
    const before = signature(st);
    const digest = await fileHash(actual);
    const { lines } = await coreFacts(actual, readXrefs, { consolePath });
    if (lines.length % 3 !== 0) throw Error("invalid_native_xref_inventory: " + name);
    const links = new Set();
    for (let index = 0; index < lines.length; index += 3) {
      const [block, flags, saved] = lines.slice(index, index + 3);
      if (!saved || win32.isAbsolute(saved) || /^[A-Za-z]:/.test(saved) || saved.includes(":")) {
        throw Error("xref_path_must_be_relative: " + name + " -> " + saved);
      }
      const child = await member(root, resolve(dirname(actual), saved));
      const nativeFlags = Number(flags);
      if (!Number.isInteger(nativeFlags) || (nativeFlags & 32) === 0) {
        throw Error("unresolved_workspace_xref: " + name + " -> " + saved);
      }
      links.add(child.name);
      pending.push(child);
      observations.push({ source: name, block, saved_path: saved, native_flags: nativeFlags, destination: child.name });
    }
    if (signature(await lstat(actual, { bigint: true })) !== before) throw Error("dwg_changed_during_discovery: " + name);
    stamps.set(actual, before);
    files.set(name, { path: name, sha256: digest, bytes: Number(st.size), links: [...links].sort() });
  }
  for (const [p, expected] of stamps) {
    if (signature(await lstat(p, { bigint: true })) !== expected) throw Error("dwg_changed_during_discovery: " + p);
  }
  return { graph: { schema: "chimera.workspace-graph/1", entry: entry.name,
    files: [...files.values()].sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0) }, observations };
}

async function main() {
  const { values } = parseArgs({ options: {
    root: { type: "string" }, entry: { type: "string" }, out: { type: "string" },
    console: { type: "string", default: defaultConsole }, help: { type: "boolean" },
  } });
  const usage = "node scripts/cad_workspace_capsule.mjs --root DIR --entry DRAWING.dwg --out NEW_GRAPH.json [--console EXE]";
  if (values.help) return console.log(usage);
  if (!values.root || !values.entry || !values.out) throw Error(usage);
  const found = await discover(values.root, values.entry, values.console);
  await writeFile(resolve(values.out), JSON.stringify(found.graph, null, 2) + "\n", { encoding: "utf8", flag: "wx" });
  console.log(JSON.stringify({ members: found.graph.files.length, xrefs: found.observations, graph: resolve(values.out) }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
