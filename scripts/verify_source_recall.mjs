/** Verify recall against independent source labels and time fresh, end-to-end command invocations. */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, realpath, rename, rm, stat, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual, parseArgs, promisify } from "node:util";

const run = promisify(execFile);
const repo = fileURLToPath(new URL("../", import.meta.url));
const { values } = parseArgs({ options: {
  python: { type: "string", default: "python" },
  out: { type: "string" },
} });

async function python(argv) {
  const start = performance.now();
  const { stdout } = await run(values.python, ["-B", "-X", "utf8", ...argv], {
    cwd: repo, windowsHide: true, timeout: 180000, maxBuffer: 4 * 1024 * 1024,
  });
  const result = JSON.parse(stdout);
  return { result, ms: performance.now() - start };
}

function times(samples) {
  const sorted = samples.toSorted((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return { n: sorted.length, p50_ms: +median.toFixed(3),
    p95_ms: +sorted[Math.ceil(sorted.length * 0.95) - 1].toFixed(3) };
}

function samePassage(hit, expected) {
  const fields = Object.fromEntries(Object.keys(expected).map(key => [key, hit[key]]));
  return isDeepStrictEqual(fields, expected);
}

async function verify(directory) {
  const state = join(directory, "state");
  const cli = (...options) => python(["-m", "chimera_tp", "aether", "--state", state, "recall", ...options]);
  const probe = (stage, ...options) => python(["-m", "scripts.source_recall_probe", stage, state, ...options]);

  const { result: seed } = await probe("seed");
  const { cases, expected } = seed;
  const labels = join(directory, "cases.json");
  await writeFile(labels, JSON.stringify(cases));
  const { result: warm } = await probe("query", labels);
  const coldFind = [], findShow = [], pdfFindRender = [], webFindRender = [];
  const ids = new Map();
  let single = 0, multiple = 0, noHit = 0, required = 0;
  for (const { query, keys, scope } of cases) {
    const start = performance.now();
    const { result: hits, ms } = await cli("find", query, "--scope", scope);
    coldFind.push(ms);
    assert.equal(hits.length, keys.length, query);
    for (const key of keys) {
      const matched = hits.filter(row => samePassage(row, expected[key]));
      assert.equal(matched.length, 1, query + " / " + key);
      ids.set(key, matched[0].id);
      required++;
    }
    if (!keys.length) {
      noHit++;
      continue;
    }
    if (keys.length === 1) single++;
    else multiple++;
    const first = hits[0];
    const { result: shown } = await cli("show", first.id, "--scope", scope);
    assert.equal(shown.id, first.id);
    const key = keys.find(key => samePassage(first, expected[key]));
    assert.ok(samePassage(shown, expected[key]));
    assert.equal(shown.continuity, first.kind === "file" ? "verified" : "unverified_https");
    findShow.push(performance.now() - start);
  }
  const repeat = await cli("save", "--file", expected.north.source, "--line", "2",
    "--context", expected.north.context);
  assert.equal(repeat.result.id, ids.get("north"));
  assert.equal(repeat.result.inserted, false);
  const web = await cli("save", "--url", expected.web1.source, "--quote", expected.web1.excerpt,
    "--text", expected.web1.text, "--context", expected.web1.context);
  assert.equal(web.result.id, ids.get("web1"));

  const physicalPages = new Map();
  let pdfiumBinding;
  for (const key of ["page2", "page4", "page4", "page2", "page2", "page4"]) {
    const start = performance.now();
    const { result: hits } = await cli("find", expected[key].text);
    assert.equal(hits[0].id, ids.get(key));
    const { result: opened } = await probe("pdf", hits[0].id);
    assert.equal(opened.dispatch.opened, true);
    assert.equal(opened.dispatch.continuity, "verified");
    assert.equal(opened.rendered.page, expected[key].page);
    assert.equal(opened.rendered.text, expected[key].text);
    assert.ok(opened.rendered.width > 0 && opened.rendered.height > 0);
    assert.match(opened.rendered.pixel_sha256, /^[0-9a-f]{64}$/);
    if (physicalPages.has(key)) assert.deepEqual(opened.rendered, physicalPages.get(key));
    physicalPages.set(key, opened.rendered);
    pdfiumBinding = opened.pdfium_binding;
    pdfFindRender.push(performance.now() - start);
  }
  assert.equal(new Set([...physicalPages.values()].map(page => page.pixel_sha256)).size, 2);

  const excerpts = new Map();
  let chromeVersion;
  for (const key of ["web1", "web2", "web2", "web1"]) {
    const start = performance.now();
    const { result: hits } = await cli("find", expected[key].excerpt);
    assert.equal(hits[0].id, ids.get(key));
    const { result: opened } = await probe("web", hits[0].id);
    assert.equal(opened.dispatch.continuity, "unverified_https");
    assert.equal(opened.visible.text, expected[key].excerpt);
    assert.ok(opened.visible.scroll_y > 0);
    chromeVersion = opened.visible.chrome;
    excerpts.set(key, { text: opened.visible.text, scroll_y: opened.visible.scroll_y });
    webFindRender.push(performance.now() - start);
  }
  assert.notEqual(excerpts.get("web1").scroll_y, excerpts.get("web2").scroll_y);

  const original = expected.north.source;
  const before = await stat(original);
  const content = await readFile(original, "utf8");
  await writeFile(original, content.replace("42", "43"), "utf8");
  await utimes(original, before.atime, before.mtime);
  assert.equal((await stat(original)).size, before.size);
  assert.equal((await cli("show", ids.get("north"))).result.continuity, "changed");
  const staleFind = await cli("find", "đường kính 42");
  assert.ok(samePassage(staleFind.result[0], expected.north));
  await rm(original);
  assert.equal((await cli("show", ids.get("north"))).result.continuity, "missing");

  return {
    date_utc: new Date().toISOString(), synthetic: true,
    reproduce: "node scripts/verify_source_recall.mjs --out tasks/source_recall_verification.json",
    fixture_dependencies: ["reportlab", "psutil", "pypdfium2", "playwright", "Google Chrome"],
    environment: { platform: seed.platform, python: seed.python, sqlite: seed.sqlite_version,
      node: process.versions.node, pypdfium2: pdfiumBinding, chrome: chromeVersion },
    corpus: { passages: seed.entries, distinct_sources: seed.distinct_sources, scopes: 2,
      queries: cases.length, includes: ["Vietnamese with and without accents", "local files with equal names",
        "two PDF pages", "two quotes in one HTTPS section", "overlapping text in different scopes",
        "1024 recurring maintenance records across 32 source URLs", "no-match queries"] },
    accuracy: { single_target_top1_correct: single, single_target_queries: single,
      complete_multi_hit_sets: multiple, multi_hit_queries: multiple, expected_hits_recovered: required,
      expected_hits_total: cases.reduce((n, c) => n + c.keys.length, 0),
      correct_empty_queries: noHit, exact_id_and_context_on_positive_show: findShow.length },
    continuity: { same_size_replacement: "changed", deleted_source: "missing",
      original_passage_retained: true, repeat_save_same_id: true, web_rechecked_over_network: false },
    latency: { warm_in_process_find: warm.query, cold_cli_find: times(coldFind),
      two_fresh_cli_find_then_show: times(findShow), fresh_find_to_pdfium_render: times(pdfFindRender),
      fresh_find_to_offline_chrome_visible_excerpt: times(webFindRender),
      method: "Wall clock, median and nearest-rank p95. Warm uses 1 discarded plus 20 measured rounds, a fresh read-only SQLite connection per find, OS cache warm. Cold denotes a new Python process per command, no OS-cache flush. Viewer timings include search, open command, rendering/viewport acknowledgement, process cleanup and the verification harness." },
    storage: warm.sqlite_files_bytes, rss_bytes: warm.rss_bytes,
    rss_method: "Fresh query worker separate from corpus seeding. psutil RSS before importing recall, after 21 rounds, maximum sampled at round boundaries and OS peak working set where available. Includes Python and measurement harness.",
    rendered_pages: [...physicalPages.values()], isolated_chrome_visible_quotes: [...excerpts.values()],
    limits: ["Labeled synthetic corpus on one workstation; no personal history or search logs.",
      "At desktop dispatch the harness uses PDFium or a fresh headless Chrome, offline with intercepted authored HTML. Exact PDF pages and viewport text verified. Foreground desktop interaction and live websites are unmeasured."],
  };
}

const base = await realpath(tmpdir());
const directory = await realpath(await mkdtemp(join(base, "chimera-source-recall-")));
try {
  const report = await verify(directory);
  if (values.out) {
    const output = resolve(values.out);
    const draft = output + "." + process.pid + ".tmp";
    await writeFile(draft, JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
    await rename(draft, output);
  }
  process.stdout.write(JSON.stringify(report) + "\n");
} finally {
  assert.equal(dirname(directory), base);
  assert.ok(basename(directory).startsWith("chimera-source-recall-"));
  await rm(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
}
