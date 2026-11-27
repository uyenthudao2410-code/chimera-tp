import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { child } from "./cad_probe_runtime.mjs";

const observer = fileURLToPath(new URL("./cad_peer_observer.py", import.meta.url));

/** The SSH connection is ready before measuring either command or opening its scene window. */
export async function startPeerCapture(options, signal) {
  const control = new AbortController();
  const abort = () => control.abort(signal?.reason);
  signal?.throwIfAborted();
  signal?.addEventListener("abort", abort, { once: true });
  const args = ["-E", "-B", "-S", "-u", observer, "--peer", options.peer];
  if (options["service-url"]) args.push("--service-url", options["service-url"]);
  const handle = child(options.python, args, { input: true, timeout: (options.timeout + 80) * 1000,
    signal: control.signal });
  const input = handle.process.stdin;
  input.on("error", () => {});
  const lines = createInterface({ input: handle.process.stdout, crlfDelay: Infinity });
  const iterator = lines[Symbol.asyncIterator]();
  async function read(expected, timeout) {
    const timer = setTimeout(() => control.abort(new Error("peer observer timeout: " + expected)), timeout);
    try {
      const { done, value } = await iterator.next();
      if (done) {
        await handle.done;
        throw new Error("Missing peer observer message " + expected);
      }
      const message = JSON.parse(value);
      if (message.type !== expected) throw new Error("Unexpected observer message " + message.type);
      return message;
    } finally {
      clearTimeout(timer);
    }
  }
  function release() {
    lines.close();
    signal?.removeEventListener("abort", abort);
  }
  async function close() {
    input.end();
    try { await handle.done; } finally { release(); }
  }
  try {
    const ready = await read("ready", 25000);
    input.write("start\n");
    await read("started", 5000);
    return { ready, close, async finish() {
      input.end("stop\n");
      try {
        const result = await read("result", 20000);
        await handle.done;
        return result;
      } finally {
        release();
      }
    } };
  } catch (error) {
    control.abort(error);
    release();
    await handle.done.catch(() => {});
    throw error;
  }
}
