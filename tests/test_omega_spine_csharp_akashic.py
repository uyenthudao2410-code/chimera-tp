"""Unit & integration tests for CHIMERA Omega-Spine: csharp_xray + akashic_cortex."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import chimera_tp.omega_spine as omega_spine
from chimera_tp.omega_spine import (
    AkashicCortex,
    callgraph_slice,
    get_akashic_cortex,
    impacted_dotnet_tests,
    outline_file,
    resolve_safe_repo,
    surgical_bundle,
    syntax_gate_csharp,
)


_COMPLEX_CSHARP = r'''using System;
using System.Collections.Generic;

namespace Acme.Piping.Core;

public sealed record PipeInput(
    string Handle,
    Vec3 Start,
    Vec3 End,
    int Dn = 100);

public readonly struct Vec3
{
    public double X { get; init; }
    public double Y { get; init; }
    public double Z { get; init; }
}

public enum RouteMode
{
    Auto,
    Manual
}

public interface IRoutingEngine
{
    PlanResult Plan(PipeInput input);
}

public sealed record PlanResult(bool Ok, string Summary)
{
    public bool HasSummary => !string.IsNullOrEmpty(Summary);
}

public static partial class PipeSolver
{
    // Fake comment: public class ShouldNotAppear { public void FakeMethod() {} }
    /* Block comment:
       public struct FakeStruct { public int FakeProp { get; set; } }
    */
    private const string TrapRegular = "public class FakeInStr { void Nope() { } }";
    private const string TrapVerbatim = @"
        public class FakeVerbatim {
            void Nope2() { var x = ""quoted {""; }
        }";
    private static readonly string TrapRaw = """
        public class FakeRaw { void Nope3() {} }
        """;

    public static int MaxIterations { get; set; } = 64;
    public static string EngineTag => $"PipeSolver-{MaxIterations:D2}-{("ok" + "{{braces}}")}";

    public static (double Score, int Rank) ComputeScore(PipeInput input, RouteMode mode)
    {
        var msg = $"Handle={input.Handle}, Mode={(mode == RouteMode.Auto ? "A{1}" : "M}2")}";
        return (msg.Length * 1.5, 1);
    }

    public static PlanResult FailPlan(string reason) => new(false, reason)
    {
    };

    public static PlanResult TopEntry(PipeInput input)
    {
        return MidStep(input);
    }

    private sealed class NestedCandidate
    {
        public NestedCandidate(string id)
        {
            Id = id;
        }

        public string Id { get; }
    }
}
'''

_PARTIAL_CSHARP_2 = r'''namespace Acme.Piping.Core;

public static partial class PipeSolver
{
    internal static PlanResult MidStep(PipeInput input)
    {
        var score = ComputeScore(input, RouteMode.Auto);
        return LeafHelper(input, score.Score);
    }

    private static PlanResult LeafHelper(PipeInput input, double weight)
    {
        return LowCore(input.Handle, weight);
    }

    private static PlanResult LowCore(string handle, double weight)
    {
        string tag = DeepUtil(handle);
        return new PlanResult(weight > 0, tag);
    }

    private static string DeepUtil(string handle) => handle.Trim();
}
'''

_TESTS_CSHARP = r'''using Xunit;
using Acme.Piping.Core;

namespace Acme.Piping.Core.Tests;

public sealed class PipeSolverTests
{
    [Fact]
    public void TopEntry_WithValidPipeInput_ReturnsOkPlanResult()
    {
        var input = new PipeInput("H1", new Vec3 { X = 0, Y = 0, Z = 0 }, new Vec3 { X = 1000, Y = 0, Z = 0 });
        var result = PipeSolver.TopEntry(input);
        Assert.True(result.Ok);
    }

    [Theory]
    [InlineData(RouteMode.Auto)]
    [InlineData(RouteMode.Manual)]
    public void ComputeScore_WorksForAllModes(RouteMode mode)
    {
        var input = new PipeInput("H2", default, default);
        var (score, rank) = PipeSolver.ComputeScore(input, mode);
        Assert.True(score > 0 && rank == 1);
    }
}
'''


class TestOmegaSpineCsharpXray(unittest.TestCase):
    def test_01_package_reexports(self) -> None:
        for attr in (
            "outline_file",
            "callgraph_slice",
            "surgical_bundle",
            "syntax_gate_csharp",
            "impacted_dotnet_tests",
            "resolve_safe_repo",
            "AkashicCortex",
            "get_akashic_cortex",
        ):
            self.assertTrue(hasattr(omega_spine, attr), f"Missing export: {attr}")

    def test_02_outline_csharp_comprehensive_and_ignores_strings_comments(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "PipeSolver.cs"
            p.write_text(_COMPLEX_CSHARP, encoding="utf-8")

            res = outline_file(p)
            self.assertTrue(res["ok"])
            self.assertEqual(res["lang"], "csharp")
            self.assertGreater(res["lines"], 60)
            self.assertIsInstance(res["ms"], float)

            by_name_kind = {(s["name"], s["kind"]): s for s in res["symbols"]}
            by_name = {s["name"]: s for s in res["symbols"]}

            # Must extract real types & members with accurate kinds
            self.assertIn(("Acme.Piping.Core", "namespace"), by_name_kind)
            self.assertIn(("PipeInput", "record"), by_name_kind)
            self.assertEqual(by_name_kind[("PipeInput", "record")]["container"], "Acme.Piping.Core")
            self.assertIn(("Vec3", "struct"), by_name_kind)
            self.assertIn(("RouteMode", "enum"), by_name_kind)
            self.assertIn(("IRoutingEngine", "interface"), by_name_kind)
            self.assertIn(("PlanResult", "record"), by_name_kind)
            self.assertIn(("HasSummary", "property"), by_name_kind)
            self.assertEqual(by_name_kind[("HasSummary", "property")]["container"], "PlanResult")
            self.assertIn(("PipeSolver", "partial class"), by_name_kind)
            self.assertIn(("MaxIterations", "property"), by_name_kind)
            self.assertIn(("EngineTag", "property"), by_name_kind)
            self.assertIn(("ComputeScore", "method"), by_name_kind)
            self.assertEqual(by_name_kind[("ComputeScore", "method")]["container"], "PipeSolver")
            self.assertIn(("FailPlan", "method"), by_name_kind)
            self.assertIn(("NestedCandidate", "class"), by_name_kind)
            self.assertEqual(by_name_kind[("NestedCandidate", "class")]["container"], "PipeSolver")

            # Constructor inside nested class
            self.assertIn(("NestedCandidate", "constructor"), by_name_kind)
            self.assertEqual(by_name_kind[("NestedCandidate", "constructor")]["container"], "PipeSolver.NestedCandidate")

            # Exact line span checks
            lines = _COMPLEX_CSHARP.splitlines()
            cs_sym = by_name["ComputeScore"]
            self.assertIn("ComputeScore(", lines[cs_sym["start_line"] - 1])
            self.assertEqual(lines[cs_sym["end_line"] - 1].strip(), "}")

            pi_sym = by_name["PipeInput"]
            self.assertIn("record PipeInput(", lines[pi_sym["start_line"] - 1])
            self.assertTrue(lines[pi_sym["end_line"] - 1].rstrip().endswith(");"))

            # Must NOT extract any fake symbols from comments, verbatim, regular, or raw strings
            for forbidden in ("ShouldNotAppear", "FakeMethod", "FakeStruct", "FakeProp", "FakeInStr", "FakeVerbatim", "FakeRaw", "Nope", "Nope2", "Nope3"):
                self.assertNotIn(forbidden, by_name, f"Leak from string/comment: {forbidden}")

    def test_03_outline_python_js_ts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            py_file = root / "engine.py"
            py_file.write_text(
                "class Engine:\n"
                "    def __init__(self, x: int) -> None:\n"
                "        self.x = x\n\n"
                "    @property\n"
                "    def value(self) -> int:\n"
                "        return self.x\n\n"
                "    async def compute(self) -> int:\n"
                "        return self.x * 2\n\n"
                "def helper(a, b):\n"
                "    return a + b\n",
                encoding="utf-8",
            )
            py_out = outline_file(py_file)
            self.assertTrue(py_out["ok"])
            self.assertEqual(py_out["lang"], "python")
            py_map = {(s["name"], s["kind"]): s for s in py_out["symbols"]}
            self.assertIn(("Engine", "class"), py_map)
            self.assertIn(("__init__", "constructor"), py_map)
            self.assertIn(("value", "property"), py_map)
            self.assertIn(("compute", "method"), py_map)
            self.assertIn(("helper", "function"), py_map)
            self.assertEqual(py_map[("compute", "method")]["container"], "Engine")

            js_file = root / "widget.mjs"
            js_file.write_text(
                "// function fake() { return 1; }\n"
                "export class Widget {\n"
                "  constructor(id) { this.id = id; }\n"
                "  render() { const s = `class Fake { }`; return s; }\n"
                "}\n"
                "export const formatLabel = (x) => {\n"
                "  return String(x);\n"
                "};\n"
                "function boot() {\n"
                "  return new Widget(1);\n"
                "}\n",
                encoding="utf-8",
            )
            js_out = outline_file(js_file)
            self.assertTrue(js_out["ok"])
            self.assertEqual(js_out["lang"], "javascript")
            js_names = {(s["name"], s["kind"]) for s in js_out["symbols"]}
            self.assertIn(("Widget", "class"), js_names)
            self.assertIn(("constructor", "constructor"), js_names)
            self.assertIn(("render", "method"), js_names)
            self.assertIn(("formatLabel", "function"), js_names)
            self.assertIn(("boot", "function"), js_names)
            self.assertNotIn(("fake", "function"), js_names)
            self.assertNotIn(("Fake", "class"), js_names)

            ts_file = root / "panel.tsx"
            ts_file.write_text(
                "export interface PanelProps { title: string; }\n"
                "export class PanelController {\n"
                "  public mount(props: PanelProps): void {\n"
                "    console.log(props.title);\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )
            ts_out = outline_file(ts_file)
            self.assertTrue(ts_out["ok"])
            self.assertEqual(ts_out["lang"], "typescript")
            ts_names = {(s["name"], s["kind"]) for s in ts_out["symbols"]}
            self.assertIn(("PanelProps", "interface"), ts_names)
            self.assertIn(("PanelController", "class"), ts_names)
            self.assertIn(("mount", "method"), ts_names)

    def test_04_syntax_gate_csharp_valid_and_broken(self) -> None:
        ok_res = syntax_gate_csharp(_COMPLEX_CSHARP, "PipeSolver.cs")
        self.assertTrue(ok_res["ok"], f"Unexpected errors: {ok_res['errors']}")
        self.assertEqual(ok_res["errors"], [])

        # Unclosed brace
        bad_brace = "namespace A;\npublic class B {\n    void C() {\n        int x = 1;\n}\n"
        r1 = syntax_gate_csharp(bad_brace)
        self.assertFalse(r1["ok"])
        self.assertTrue(any("{" in e["message"] for e in r1["errors"]))

        # Mismatched bracket/paren
        bad_mismatch = "public class B { void C() { var arr = new int[(1 + 2]); } }"
        r2 = syntax_gate_csharp(bad_mismatch)
        self.assertFalse(r2["ok"])
        self.assertGreaterEqual(len(r2["errors"]), 1)

        # Unterminated regular string
        bad_str = 'public class B {\n    string s = "unterminated;\n}\n'
        r3 = syntax_gate_csharp(bad_str)
        self.assertFalse(r3["ok"])
        self.assertTrue(any(e["line"] == 2 and "string" in e["message"].lower() for e in r3["errors"]))

        # Unterminated verbatim string
        bad_verb = 'public class B {\n    string s = @"never ends\n}\n'
        r4 = syntax_gate_csharp(bad_verb)
        self.assertFalse(r4["ok"])
        self.assertTrue(any("verbatim" in e["message"].lower() for e in r4["errors"]))

        # Unterminated block comment
        bad_comment = "public class B {\n    /* forgot to close\n}\n"
        r5 = syntax_gate_csharp(bad_comment)
        self.assertFalse(r5["ok"])
        self.assertTrue(any("comment" in e["message"].lower() for e in r5["errors"]))

    def test_05_callgraph_slice_partial_classes_2hop_and_skip_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "Core").mkdir(parents=True)
            (root / "tests" / "Core.Tests").mkdir(parents=True)
            (root / "src" / "Core" / "bin" / "Debug").mkdir(parents=True)
            (root / "src" / "Core" / "obj").mkdir(parents=True)

            (root / "src" / "Core" / "PipeSolver.cs").write_text(_COMPLEX_CSHARP, encoding="utf-8")
            (root / "src" / "Core" / "PipeSolver.Combine.cs").write_text(_PARTIAL_CSHARP_2, encoding="utf-8")
            (root / "tests" / "Core.Tests" / "PipeSolverTests.cs").write_text(_TESTS_CSHARP, encoding="utf-8")
            # Decoy files inside bin/ and obj/ MUST be skipped
            (root / "src" / "Core" / "bin" / "Debug" / "PipeSolver.cs").write_text(_COMPLEX_CSHARP, encoding="utf-8")
            (root / "src" / "Core" / "obj" / "PipeSolver.g.cs").write_text(_PARTIAL_CSHARP_2, encoding="utf-8")

            # Partial class across two files
            cg_cls = callgraph_slice(root, "PipeSolver", hops=2)
            self.assertTrue(cg_cls["ok"])
            self.assertEqual(len(cg_cls["definitions"]), 2)
            self.assertEqual(len(cg_cls["partial_files"]), 2)
            for d in cg_cls["definitions"]:
                self.assertNotIn("/bin/", d["file"])
                self.assertNotIn("/obj/", d["file"])

            # 2-hop callers & callees of LeafHelper:
            # TopEntry (hop 2) -> MidStep (hop 1) -> LeafHelper -> LowCore (hop 1) -> DeepUtil (hop 2)
            cg_leaf = callgraph_slice(root, "LeafHelper", hops=2)
            self.assertTrue(cg_leaf["ok"])
            self.assertEqual(len(cg_leaf["definitions"]), 1)
            self.assertEqual(cg_leaf["definitions"][0]["file"], "src/Core/PipeSolver.Combine.cs")

            caller_hops = {(c["symbol"], c["hop"]) for c in cg_leaf["callers"]}
            self.assertIn(("MidStep", 1), caller_hops)
            self.assertIn(("TopEntry", 2), caller_hops)

            callee_hops = {(c["symbol"], c["hop"]) for c in cg_leaf["callees"]}
            self.assertIn(("LowCore", 1), callee_hops)
            self.assertIn(("DeepUtil", 2), callee_hops)

    def test_06_surgical_bundle_budget_related_types_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "Core").mkdir(parents=True)
            (root / "tests" / "Core.Tests").mkdir(parents=True)
            (root / "src" / "Core" / "PipeSolver.cs").write_text(_COMPLEX_CSHARP, encoding="utf-8")
            (root / "src" / "Core" / "PipeSolver.Combine.cs").write_text(_PARTIAL_CSHARP_2, encoding="utf-8")
            (root / "tests" / "Core.Tests" / "PipeSolverTests.cs").write_text(_TESTS_CSHARP, encoding="utf-8")

            bundle = surgical_bundle(root, "LeafHelper", max_bytes=8192)
            self.assertTrue(bundle["ok"])
            raw_bytes = len(json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
            self.assertLessEqual(raw_bytes, 8192)
            self.assertEqual(len(bundle["definitions"]), 1)
            self.assertIn("LowCore(input.Handle, weight)", bundle["definitions"][0]["body"])

            # Related types referenced in signature: PipeInput, PlanResult
            rel_names = {t["name"] for t in bundle["related_types"]}
            self.assertIn("PipeInput", rel_names)
            self.assertIn("PlanResult", rel_names)

            # Matching test discovered via 2-hop caller TopEntry!
            test_names = {t["name"] for t in bundle["tests"]}
            self.assertIn("TopEntry_WithValidPipeInput_ReturnsOkPlanResult", test_names)

            # Strict tight max_bytes cap enforcement
            tight = surgical_bundle(root, "LeafHelper", max_bytes=1200)
            tight_bytes = len(json.dumps(tight, ensure_ascii=False).encode("utf-8"))
            self.assertLessEqual(tight_bytes, 1200)
            self.assertTrue(tight["truncated"])

    def test_07_impacted_dotnet_tests_project_reference_and_filter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src" / "Core").mkdir(parents=True)
            (root / "tests" / "Core.Tests").mkdir(parents=True)
            (root / "tests" / "Unrelated.Tests").mkdir(parents=True)

            (root / "src" / "Core" / "Core.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>',
                encoding="utf-8",
            )
            (root / "src" / "Core" / "PipeSolver.cs").write_text(_COMPLEX_CSHARP, encoding="utf-8")
            (root / "tests" / "Core.Tests" / "Core.Tests.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk">'
                '<ItemGroup><PackageReference Include="xunit" Version="2.9.0" /></ItemGroup>'
                '<ItemGroup><ProjectReference Include="..\\..\\src\\Core\\Core.csproj" /></ItemGroup>'
                "</Project>",
                encoding="utf-8",
            )
            (root / "tests" / "Core.Tests" / "PipeSolverTests.cs").write_text(_TESTS_CSHARP, encoding="utf-8")
            (root / "tests" / "Unrelated.Tests" / "Unrelated.Tests.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk">'
                '<ItemGroup><PackageReference Include="xunit" Version="2.9.0" /></ItemGroup>'
                "</Project>",
                encoding="utf-8",
            )

            res = impacted_dotnet_tests(root, ["src/Core/PipeSolver.cs"])
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["test_projects"]), 2)
            self.assertEqual(len(res["impacted_projects"]), 1)
            proj = res["impacted_projects"][0]
            self.assertEqual(proj["project"], "tests/Core.Tests/Core.Tests.csproj")
            self.assertIn("--no-restore", proj["command"])
            self.assertIn("--filter", proj["command"])
            self.assertIn("PipeSolverTests", proj["filter"])

    def test_08_resolve_safe_repo_guards_chimera_release_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            user_ws = root / "my_project"
            user_ws.mkdir()

            win_release = root / "AppData" / "Local" / "chimera" / "releases" / "2026.11" / "scripts"
            win_release.mkdir(parents=True)
            lin_release = root / ".local" / "share" / "chimera" / "releases" / "2026.11" / "scripts"
            lin_release.mkdir(parents=True)

            # Reject implicit fallback into Windows or Linux Chimera releases dir
            for rel_dir in (win_release, lin_release):
                for bad_repo in (None, "", ".", "./", "scripts"):
                    with self.assertRaises(ValueError) as ctx:
                        resolve_safe_repo(bad_repo, fallback_cwd=str(rel_dir))
                    self.assertIn("chimera", str(ctx.exception).lower())

            # Allow normal workspace via explicit repo or safe fallback_cwd
            self.assertEqual(resolve_safe_repo(str(user_ws)), user_ws.resolve())
            self.assertEqual(resolve_safe_repo(None, fallback_cwd=str(user_ws)), user_ws.resolve())

            # Allow explicit absolute path to the release dir itself when explicitly requested
            self.assertEqual(resolve_safe_repo(str(win_release)), win_release.resolve())

            # Reject nonexistent path
            with self.assertRaises(ValueError):
                resolve_safe_repo(str(root / "does_not_exist_xyz"))


class TestOmegaSpineAkashicCortex(unittest.TestCase):
    def test_09_capsule_bounded_upsert_recall_and_stale_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "akashic.sqlite"
            cortex = AkashicCortex(db_path=db)
            try:
                # Verify SQLite WAL mode
                con = sqlite3.connect(str(db))
                try:
                    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                    self.assertEqual(str(mode).lower(), "wal")
                finally:
                    con.close()

                sha_v1 = hashlib.sha256(b"version-1").hexdigest()
                sha_v2 = hashlib.sha256(b"version-2").hexdigest()

                # Oversized summary + invariants must be strictly bounded < 1024 B
                giant_summary = "Invariant summary " + ("X" * 2000)
                giant_invariants = [f"Inv-{i}: " + ("Y" * 200) for i in range(12)]
                cap = cortex.put_symbol_capsule(
                    repo="E:/dev/Autocad",
                    rel_path="src/SmartEditSolver.cs",
                    file_sha256=sha_v1,
                    symbol="RewirePlanPartLink",
                    summary=giant_summary,
                    invariants=giant_invariants,
                    line_range="11000-11055",
                    author="csharp-xray",
                )
                self.assertTrue(cap["ok"])
                self.assertLess(cap["byte_size"], 1024)

                # Recall with matching SHA returns capsule
                recalled = cortex.recall_for_files(
                    "E:/dev/Autocad",
                    {"src/SmartEditSolver.cs": sha_v1},
                    limit=8,
                )
                self.assertEqual(len(recalled), 1)
                self.assertEqual(recalled[0]["symbol"], "RewirePlanPartLink")
                self.assertFalse(recalled[0]["stale"])

                st1 = cortex.status()
                self.assertEqual(st1["capsule_count"], 1)
                self.assertEqual(st1["stale_count"], 0)

                # Recall with changed SHA returns empty AND marks capsule stale=1
                recalled_v2 = cortex.recall_for_files(
                    "E:/dev/Autocad",
                    {"src/SmartEditSolver.cs": sha_v2},
                    limit=8,
                )
                self.assertEqual(recalled_v2, [])
                st2 = cortex.status()
                self.assertEqual(st2["capsule_count"], 1)
                self.assertEqual(st2["stale_count"], 1)

                # Upsert with new SHA clears stale flag
                cortex.put_symbol_capsule(
                    repo="E:/dev/Autocad",
                    rel_path="src/SmartEditSolver.cs",
                    file_sha256=sha_v2,
                    symbol="RewirePlanPartLink",
                    summary="Rewires CreateParts/UpdateParts/Existing links after split",
                    invariants=["Preserves StringComparer.OrdinalIgnoreCase"],
                    line_range="11000-11055",
                )
                recalled_fresh = cortex.recall_for_files("E:/dev/Autocad", {"src/SmartEditSolver.cs": sha_v2})
                self.assertEqual(len(recalled_fresh), 1)
                self.assertEqual(cortex.status()["stale_count"], 0)
            finally:
                cortex.close()

    def test_10_immune_antibody_auto_distillation_matching_and_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "akashic_ab.sqlite"
            cortex = AkashicCortex(db_path=db)
            try:
                # 1. Command family: PowerShell 5.1 '&&' failure -> fixed with ';' within 5 steps
                r_fail = cortex.record_tool_outcome(
                    conversation_id="conv-1",
                    repo="E:/dev/Autocad",
                    tool_name="run_command",
                    args={"CommandLine": "dotnet build && dotnet test"},
                    ok=False,
                    error="ParserError: The token '&&' is not a valid statement separator in this version.",
                )
                self.assertIsNone(r_fail)

                r_distilled = cortex.record_tool_outcome(
                    conversation_id="conv-1",
                    repo="E:/dev/Autocad",
                    tool_name="run_command",
                    args={"CommandLine": "dotnet build; dotnet test"},
                    ok=True,
                )
                self.assertIsNotNone(r_distilled)
                assert r_distilled is not None
                self.assertIn("&&", r_distilled["error_sig"])
                self.assertIn(";", r_distilled["fix_hint"])
                self.assertGreater(r_distilled["confidence"], 0.5)
                self.assertGreater(r_distilled["ttl"], 0)

                # 2. File family: CS0103 error on SmartEditSolver.cs -> fixed 2 steps later
                cortex.record_tool_outcome(
                    conversation_id="conv-1",
                    repo="E:/dev/Autocad",
                    tool_name="edit_file",
                    args={"path": "src/SmartEditSolver.cs"},
                    ok=False,
                    error="error CS0103: The name 'RewireHelper' does not exist in the current context",
                )
                # Intervening unrelated tool call (still within 5 steps)
                cortex.record_tool_outcome(
                    conversation_id="conv-1",
                    repo="E:/dev/Autocad",
                    tool_name="read_file",
                    args={"path": "src/Other.cs"},
                    ok=True,
                )
                ab_cs = cortex.record_tool_outcome(
                    conversation_id="conv-1",
                    repo="E:/dev/Autocad",
                    tool_name="edit_file",
                    args={"path": "src/SmartEditSolver.cs"},
                    ok=True,
                    diff_hint="Use RewirePlanPartLink instead of RewireHelper",
                )
                self.assertIsNotNone(ab_cs)
                assert ab_cs is not None
                self.assertIn("CS0103", ab_cs["error_sig"])
                self.assertEqual(ab_cs["file_pattern"], "src/SmartEditSolver.cs")
                self.assertEqual(ab_cs["fix_hint"], "Use RewirePlanPartLink instead of RewireHelper")

                # 3. Failure > 5 steps ago MUST NOT distill
                cortex.record_tool_outcome(
                    conversation_id="conv-2",
                    repo="E:/dev/Autocad",
                    tool_name="edit_file",
                    args={"path": "src/Late.cs"},
                    ok=False,
                    error="error CS9999: Old failure",
                )
                for i in range(5):
                    cortex.record_tool_outcome(
                        conversation_id="conv-2",
                        repo="E:/dev/Autocad",
                        tool_name="read_file",
                        args={"path": f"src/Filler{i}.cs"},
                        ok=True,
                    )
                too_late = cortex.record_tool_outcome(
                    conversation_id="conv-2",
                    repo="E:/dev/Autocad",
                    tool_name="edit_file",
                    args={"path": "src/Late.cs"},
                    ok=True,
                )
                self.assertIsNone(too_late)

                # 4. Match antibodies & verify hit_count bumps + status telemetry
                hits_ps = cortex.match_antibodies("dotnet build && dotnet test")
                self.assertGreaterEqual(len(hits_ps), 1)
                self.assertEqual(hits_ps[0]["hit_count"], 1)

                hits_cs = cortex.match_antibodies("src/SmartEditSolver.cs")
                self.assertGreaterEqual(len(hits_cs), 1)
                self.assertIn("CS0103", hits_cs[0]["error_sig"])
                self.assertEqual(hits_cs[0]["hit_count"], 1)

                # Second hit bumps hit_count to 2
                hits_cs_2 = cortex.match_antibodies("CS0103 in SmartEditSolver.cs")
                self.assertEqual(hits_cs_2[0]["hit_count"], 2)

                st = cortex.status()
                self.assertEqual(st["active_antibodies_count"], 2)
                self.assertGreaterEqual(st["total_antibody_hits"], 3)
            finally:
                cortex.close()

    def test_11_singleton_accessor(self) -> None:
        a = get_akashic_cortex()
        b = get_akashic_cortex()
        self.assertIs(a, b)


if __name__ == "__main__":
    unittest.main()
