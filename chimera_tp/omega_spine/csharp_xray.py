"""CHIMERA Omega-Spine: Polyglot C#/.NET X-Ray, Callgraph Slice, Surgical Bundle & Safe Repo Guard.

Zero external dependencies (pure Python stdlib). Designed for sub-second cold and <50ms warm
X-Ray and surgical context teleportation across multi-thousand-file C#/.NET, Python, and JS/TS repos.
"""

from __future__ import annotations

import ast
from bisect import bisect_left
from collections import OrderedDict
import json
import os
from pathlib import Path
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "bin",
        "obj",
        ".git",
        "node_modules",
        "artifacts",
        "__pycache__",
        ".vs",
        ".idea",
        ".pytest_cache",
        ".venv",
        "venv",
        "packages",
        "TestResults",
        "dist",
        "build",
        "target",
    }
)

_LANG_BY_EXT: dict[str, str] = {
    ".cs": "csharp",
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

_SUPPORTED_EXTS: frozenset[str] = frozenset(_LANG_BY_EXT.keys())

_CS_CONTROL_KEYWORDS: frozenset[str] = frozenset(
    {
        "if",
        "else",
        "for",
        "foreach",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "try",
        "catch",
        "finally",
        "lock",
        "using",
        "fixed",
        "checked",
        "unchecked",
        "return",
        "throw",
        "yield",
        "await",
        "new",
        "typeof",
        "nameof",
        "sizeof",
        "stackalloc",
        "when",
        "where",
        "get",
        "set",
        "init",
        "add",
        "remove",
        "delegate",
        "namespace",
        "class",
        "struct",
        "record",
        "interface",
        "enum",
        "var",
        "ref",
        "out",
        "in",
        "is",
        "as",
        "with",
    }
)

_BUILTIN_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "Object",
        "String",
        "Int32",
        "Int64",
        "Double",
        "Single",
        "Decimal",
        "Boolean",
        "Byte",
        "Char",
        "Guid",
        "DateTime",
        "DateTimeOffset",
        "TimeSpan",
        "Uri",
        "Type",
        "Exception",
        "ArgumentException",
        "ArgumentNullException",
        "InvalidOperationException",
        "NotSupportedException",
        "FileNotFoundException",
        "Task",
        "ValueTask",
        "CancellationToken",
        "Action",
        "Func",
        "Predicate",
        "List",
        "IList",
        "IReadOnlyList",
        "ICollection",
        "IReadOnlyCollection",
        "IEnumerable",
        "Dictionary",
        "IDictionary",
        "IReadOnlyDictionary",
        "HashSet",
        "ISet",
        "IReadOnlySet",
        "Queue",
        "Stack",
        "KeyValuePair",
        "Span",
        "ReadOnlySpan",
        "Memory",
        "ReadOnlyMemory",
        "Array",
        "Tuple",
        "Nullable",
        "Math",
        "Console",
        "File",
        "Path",
        "Directory",
        "StringBuilder",
        "StringComparer",
        "StringComparison",
        "CultureInfo",
        "Enum",
        "Convert",
        "Assert",
        "Fact",
        "Theory",
        "InlineData",
        "MemberData",
        "Test",
        "TestMethod",
        "TestClass",
        "T",
        "TKey",
        "TValue",
        "TResult",
        "TItem",
    }
)

_NOISE_CALLEES: frozenset[str] = (
    _CS_CONTROL_KEYWORDS
    | _BUILTIN_TYPE_NAMES
    | frozenset(
        {
            "Equals",
            "ToString",
            "GetType",
            "GetHashCode",
            "ReferenceEquals",
            "Add",
            "AddRange",
            "Remove",
            "RemoveAt",
            "Clear",
            "Contains",
            "ContainsKey",
            "TryGetValue",
            "Count",
            "Any",
            "All",
            "Select",
            "SelectMany",
            "Where",
            "ToList",
            "ToArray",
            "ToDictionary",
            "ToHashSet",
            "First",
            "FirstOrDefault",
            "Last",
            "LastOrDefault",
            "Single",
            "SingleOrDefault",
            "OrderBy",
            "OrderByDescending",
            "ThenBy",
            "GroupBy",
            "Distinct",
            "Concat",
            "Skip",
            "Take",
            "Sum",
            "Min",
            "Max",
            "Abs",
            "Round",
            "Floor",
            "Ceiling",
            "Sqrt",
            "Atan2",
            "Sin",
            "Cos",
            "Hypot",
            "Clamp",
            "IsNullOrEmpty",
            "IsNullOrWhiteSpace",
            "Format",
            "Join",
            "Split",
            "Trim",
            "Replace",
            "StartsWith",
            "EndsWith",
            "Substring",
            "Append",
            "AppendLine",
            "WriteLine",
            "Write",
            "Compare",
            "CompareTo",
            "print",
            "len",
            "str",
            "int",
            "float",
            "bool",
            "list",
            "dict",
            "set",
            "tuple",
            "range",
            "enumerate",
            "zip",
            "isinstance",
            "issubclass",
            "getattr",
            "setattr",
            "hasattr",
            "super",
            "min",
            "max",
            "sum",
            "abs",
            "round",
            "sorted",
            "reversed",
            "append",
            "extend",
            "items",
            "keys",
            "values",
            "pop",
            "push",
            "map",
            "filter",
            "reduce",
            "forEach",
            "log",
            "warn",
            "error",
        }
    )
)

# Bounded LRU outline cache keyed by (resolved_path_str, mtime_ns, size) -> (result_dict, content, masked, nl_offsets)
_OUTLINE_CACHE_LOCK = threading.Lock()
_OUTLINE_CACHE: OrderedDict[tuple[str, int, int], tuple[dict[str, Any], str, str, list[int]]] = OrderedDict()
_OUTLINE_CACHE_MAX = 512

# Bounded LRU repo snapshot cache for large repos (>= 150 files) to make warm queries < 25 ms
_REPO_CACHE_LOCK = threading.Lock()
_REPO_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_REPO_CACHE_MAX = 6
_REPO_CACHE_TTL_S = 15.0
_REPO_CACHE_MIN_FILES = 150

# Bounded LRU surgical bundle cache validated by file mtime_ns/size of all referenced files
_BUNDLE_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE: OrderedDict[tuple[str, str, int], tuple[float, list[tuple[Path, int, int]], dict[str, Any]]] = OrderedDict()
_BUNDLE_CACHE_MAX = 128

# Compiled C-speed regexes (no per-newline backtracking!)
_CS_LEX_RE = re.compile(r"//[^\n]*|/\*|\$+@\"|@\$+\"|\$+\"{3,}|\"{3,}|\$\"|@\"|\"|'|#[^\n]*")
_CS_STRUCT_RE = re.compile(r"\{|\}|;|\(|\)|\[|\]|=>")
_CS_BRACE_ONLY_RE = re.compile(r"[{}]")
_CS_GATE_RE = re.compile(
    r"//[^\n]*|/\*|\$+@\"|@\$+\"|\$+\"{3,}|\"{3,}|\$\"|@\"|\"|'|[{}()\[\]]"
)
_CS_TYPE_KW_RE = re.compile(r"\b(class|struct|record|interface|enum)\b")
_CS_IDENT_RE = re.compile(r"[A-Za-z_@]\w*")
_CS_CALL_RE = re.compile(r"(?:\.|(?<![A-Za-z0-9_]))([A-Za-z_]\w*)\s*(?:<[^;{}()=\n]{1,64}>)?\s*\(")
_PASCAL_TYPE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\b")

# JS/TS lexer & structural regexes
_JS_LEX_RE = re.compile(r"//[^\n]*|/\*|\"|'|`")
_JS_STRUCT_RE = re.compile(r"\{|\}|;|\(|\)|\[|\]")


def _build_newline_offsets(text: str) -> list[int]:
    return [m.start() for m in re.finditer("\n", text)]


def _line_at(nl_offsets: list[int], pos: int) -> int:
    return bisect_left(nl_offsets, pos) + 1


def _blank_preserving_newlines(segment: str) -> str:
    if "\n" not in segment:
        return " " * len(segment)
    return "\n".join(" " * len(part) for part in segment.split("\n"))


def _collapse_ws(text: str, max_len: int = 240) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) > max_len:
        return s[: max_len - 3].rstrip() + "..."
    return s


def _skip_brace_body(masked: str, open_end: int) -> int:
    """Starting immediately after `{`, fast-skip to the index of its matching `}` using brace-only regex."""
    depth = 1
    for bm in _CS_BRACE_ONLY_RE.finditer(masked, open_end):
        if bm.group(0) == "{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return bm.start()
    return len(masked)


def _scan_raw_string(text: str, start: int, dollar_count: int, quote_count: int) -> tuple[int, bool]:
    """Scan a C# 11+ raw string literal starting at `start` (at first `$` or `"`)."""
    n = len(text)
    pos = start + dollar_count + quote_count
    closing = '"' * quote_count
    while pos < n:
        idx = text.find(closing, pos)
        if idx == -1:
            return n, False
        end = idx + quote_count
        if end < n and text[end] == '"':
            run_end = end
            while run_end < n and text[run_end] == '"':
                run_end += 1
            return run_end, True
        return end, True
    return n, False


def _scan_interpolated_string(
    text: str,
    start: int,
    *,
    is_verbatim: bool,
    dollar_count: int,
    nl_offsets: list[int] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> tuple[int, bool]:
    """Scan C# interpolated string ($"...", $@"...", @$"...") including nested {expr} holes."""
    n = len(text)
    pos = start
    while pos < n and text[pos] in ("$", "@"):
        pos += 1
    if pos >= n or text[pos] != '"':
        return pos, False
    pos += 1

    start_line = _line_at(nl_offsets, start) if nl_offsets is not None else 1
    while pos < n:
        ch = text[pos]
        if ch == '"':
            if is_verbatim and pos + 1 < n and text[pos + 1] == '"':
                pos += 2
                continue
            return pos + 1, True
        if not is_verbatim:
            if ch == "\\":
                if pos + 1 < n:
                    pos += 2
                    continue
                return n, False
            if ch in ("\n", "\r"):
                return pos, False
        if ch == "{":
            run = 1
            while pos + run < n and text[pos + run] == "{":
                run += 1
            if run >= 2 and dollar_count == 1:
                pos += (run // 2) * 2
                if run % 2 == 0:
                    continue
            elif run < dollar_count:
                pos += run
                continue
            else:
                pos += dollar_count - 1
            hole_open_pos = pos
            pos += 1
            brace_d = 1
            paren_d = 0
            bracket_d = 0
            ternary_d = 0
            in_format = False
            while pos < n and brace_d > 0:
                c = text[pos]
                if in_format:
                    if c == "}":
                        brace_d -= 1
                        pos += 1
                        break
                    if not is_verbatim and c in ("\n", "\r"):
                        return pos, False
                    pos += 1
                    continue
                if c == '"':
                    if pos + 2 < n and text[pos : pos + 3] == '"""':
                        qlen = 3
                        while pos + qlen < n and text[pos + qlen] == '"':
                            qlen += 1
                        pos, ok_raw = _scan_raw_string(text, pos, 0, qlen)
                        if not ok_raw:
                            return pos, False
                        continue
                    pos += 1
                    while pos < n:
                        sc = text[pos]
                        if sc == "\\":
                            pos += 2
                            continue
                        if sc == '"':
                            pos += 1
                            break
                        if sc in ("\n", "\r"):
                            return pos, False
                        pos += 1
                    continue
                if c == "@" and pos + 1 < n and text[pos + 1] == '"':
                    pos += 2
                    while pos < n:
                        if text[pos] == '"':
                            if pos + 1 < n and text[pos + 1] == '"':
                                pos += 2
                                continue
                            pos += 1
                            break
                        pos += 1
                    continue
                if c == "$" and pos + 1 < n and (
                    text[pos + 1] == '"' or (text[pos + 1] == "@" and pos + 2 < n and text[pos + 2] == '"')
                ):
                    sub_verb = text[pos + 1] == "@"
                    pos, ok_sub = _scan_interpolated_string(
                        text, pos, is_verbatim=sub_verb, dollar_count=1, nl_offsets=nl_offsets, errors=errors
                    )
                    if not ok_sub:
                        return pos, False
                    continue
                if c == "'":
                    pos += 1
                    if pos < n and text[pos] == "\\":
                        pos += 2
                    else:
                        pos += 1
                    while pos < n and text[pos] != "'" and text[pos] not in ("\n", "\r"):
                        pos += 1
                    if pos < n and text[pos] == "'":
                        pos += 1
                    continue
                if c == "/" and pos + 1 < n and text[pos + 1] == "/":
                    nl = text.find("\n", pos + 2)
                    pos = n if nl == -1 else nl + 1
                    continue
                if c == "/" and pos + 1 < n and text[pos + 1] == "*":
                    end_c = text.find("*/", pos + 2)
                    if end_c == -1:
                        return n, False
                    pos = end_c + 2
                    continue
                if c == "(":
                    paren_d += 1
                elif c == ")":
                    paren_d = max(0, paren_d - 1)
                elif c == "[":
                    bracket_d += 1
                elif c == "]":
                    bracket_d = max(0, bracket_d - 1)
                elif c == "{":
                    brace_d += 1
                elif c == "}":
                    brace_d -= 1
                    pos += 1
                    continue
                elif c == "?" and brace_d == 1 and paren_d == 0 and bracket_d == 0:
                    nxt = text[pos + 1] if pos + 1 < n else ""
                    if nxt not in (".", "[", "?"):
                        ternary_d += 1
                elif c == ":" and brace_d == 1 and paren_d == 0 and bracket_d == 0:
                    if ternary_d > 0:
                        ternary_d -= 1
                    else:
                        in_format = True
                pos += 1
            if brace_d > 0:
                if errors is not None and nl_offsets is not None:
                    errors.append(
                        {
                            "line": _line_at(nl_offsets, hole_open_pos),
                            "message": "Unclosed '{' in interpolated string",
                        }
                    )
                return pos, False
            continue
        if ch == "}":
            if pos + 1 < n and text[pos + 1] == "}":
                pos += 2
                continue
        pos += 1

    if errors is not None and nl_offsets is not None:
        errors.append({"line": start_line, "message": "Unterminated interpolated string literal"})
    return n, False


def _mask_csharp(content: str) -> str:
    """Replace C# comments, strings, char literals, and preprocessor lines with spaces (preserving newlines)."""
    n = len(content)
    out: list[str] = []
    pos = 0
    while pos < n:
        m = _CS_LEX_RE.search(content, pos)
        if not m:
            out.append(content[pos:])
            break
        start, end = m.start(), m.end()
        if start > pos:
            out.append(content[pos:start])
        tok = m.group(0)

        if tok.startswith("//"):
            out.append(" " * (end - start))
            pos = end
        elif tok == "/*":
            close = content.find("*/", end)
            stop = n if close == -1 else close + 2
            out.append(_blank_preserving_newlines(content[start:stop]))
            pos = stop
        elif tok[0] == "#":
            # Mask only if `#` is the first non-whitespace char on its line (preprocessor directive)
            line_start = content.rfind("\n", 0, start) + 1
            if content[line_start:start].strip() == "":
                out.append(" " * (end - start))
                pos = end
            else:
                out.append("#")
                pos = start + 1
        elif tok.endswith('"""'):
            d_cnt = len(tok) - len(tok.lstrip("$"))
            q_cnt = len(tok) - d_cnt
            stop, _ = _scan_raw_string(content, start, d_cnt, q_cnt)
            out.append(_blank_preserving_newlines(content[start:stop]))
            pos = stop
        elif tok.startswith('$"') or ("$" in tok and "@" in tok):
            is_verb = "@" in tok
            d_cnt = tok.count("$")
            stop, _ = _scan_interpolated_string(content, start, is_verbatim=is_verb, dollar_count=d_cnt)
            out.append(_blank_preserving_newlines(content[start:stop]))
            pos = stop
        elif tok == '@"':
            p = end
            while p < n:
                q = content.find('"', p)
                if q == -1:
                    p = n
                    break
                if q + 1 < n and content[q + 1] == '"':
                    p = q + 2
                    continue
                p = q + 1
                break
            out.append(_blank_preserving_newlines(content[start:p]))
            pos = p
        elif tok == '"':
            p = end
            while p < n:
                ch = content[p]
                if ch == "\\":
                    p += 2
                    continue
                if ch == '"':
                    p += 1
                    break
                if ch in ("\n", "\r"):
                    break
                p += 1
            out.append(_blank_preserving_newlines(content[start:p]))
            pos = p
        elif tok == "'":
            p = end
            while p < n:
                ch = content[p]
                if ch == "\\":
                    p += 2
                    continue
                if ch == "'":
                    p += 1
                    break
                if ch in ("\n", "\r"):
                    break
                p += 1
            out.append(_blank_preserving_newlines(content[start:p]))
            pos = p
        else:
            out.append(" " * (end - start))
            pos = end

    return "".join(out)


def syntax_gate_csharp(content: str, path: str = "") -> dict[str, Any]:
    """String/comment-aware C# brace {}, paren (), bracket [] balance + unterminated literal check."""
    if not isinstance(content, str):
        return {"ok": False, "errors": [{"line": 1, "message": "Content must be a string"}]}

    nl_offsets = _build_newline_offsets(content)
    errors: list[dict[str, Any]] = []
    stack: list[tuple[str, int]] = []
    match_open = {"}": "{", ")": "(", "]": "["}
    expected_close = {"{": "}", "(": ")", "[": "]"}

    n = len(content)
    pos = 0
    while pos < n:
        m = _CS_GATE_RE.search(content, pos)
        if not m:
            break
        start, end = m.start(), m.end()
        tok = m.group(0)

        if tok in ("{", "(", "["):
            stack.append((tok, _line_at(nl_offsets, start)))
            pos = end
            continue
        if tok in ("}", ")", "]"):
            ln = _line_at(nl_offsets, start)
            need = match_open[tok]
            if not stack:
                errors.append({"line": ln, "message": f"Unmatched closing '{tok}'"})
            elif stack[-1][0] == need:
                stack.pop()
            else:
                found_idx = -1
                for idx in range(len(stack) - 1, max(-1, len(stack) - 4), -1):
                    if stack[idx][0] == need:
                        found_idx = idx
                        break
                if found_idx >= 0:
                    while len(stack) - 1 > found_idx:
                        unclosed_ch, unclosed_ln = stack.pop()
                        errors.append(
                            {
                                "line": unclosed_ln,
                                "message": f"Unclosed '{unclosed_ch}' (expected '{expected_close[unclosed_ch]}' before '{tok}' at line {ln})",
                            }
                        )
                    stack.pop()
                else:
                    top_ch, top_ln = stack[-1]
                    errors.append(
                        {
                            "line": ln,
                            "message": f"Mismatched closing '{tok}' (expected '{expected_close[top_ch]}' for '{top_ch}' opened at line {top_ln})",
                        }
                    )
            pos = end
            continue

        if tok.startswith("//"):
            pos = end
        elif tok == "/*":
            close = content.find("*/", end)
            if close == -1:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated block comment '/*'"})
                pos = n
            else:
                pos = close + 2
        elif tok.endswith('"""'):
            d_cnt = len(tok) - len(tok.lstrip("$"))
            q_cnt = len(tok) - d_cnt
            stop, ok_raw = _scan_raw_string(content, start, d_cnt, q_cnt)
            if not ok_raw:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated raw string literal"})
            pos = stop
        elif tok.startswith('$"') or ("$" in tok and "@" in tok):
            is_verb = "@" in tok
            d_cnt = tok.count("$")
            pre_errs = len(errors)
            stop, ok_interp = _scan_interpolated_string(
                content, start, is_verbatim=is_verb, dollar_count=d_cnt, nl_offsets=nl_offsets, errors=errors
            )
            if not ok_interp and len(errors) == pre_errs:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated interpolated string literal"})
            pos = stop
        elif tok == '@"':
            p = end
            closed = False
            while p < n:
                q = content.find('"', p)
                if q == -1:
                    p = n
                    break
                if q + 1 < n and content[q + 1] == '"':
                    p = q + 2
                    continue
                p = q + 1
                closed = True
                break
            if not closed:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated verbatim string literal"})
            pos = p
        elif tok == '"':
            p = end
            closed = False
            while p < n:
                ch = content[p]
                if ch == "\\":
                    if p + 1 >= n:
                        p = n
                        break
                    p += 2
                    continue
                if ch == '"':
                    p += 1
                    closed = True
                    break
                if ch in ("\n", "\r"):
                    break
                p += 1
            if not closed:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated string literal"})
            pos = p
        elif tok == "'":
            p = end
            closed = False
            if p < n and content[p] == "\\":
                p += 2
            elif p < n and content[p] not in ("\n", "\r", "'"):
                p += 1
            while p < n:
                ch = content[p]
                if ch == "'":
                    p += 1
                    closed = True
                    break
                if ch in ("\n", "\r"):
                    break
                p += 1
            if not closed:
                errors.append({"line": _line_at(nl_offsets, start), "message": "Unterminated char literal"})
            pos = p
        else:
            pos = end

    for unclosed_ch, unclosed_ln in reversed(stack):
        errors.append(
            {
                "line": unclosed_ln,
                "message": f"Unclosed '{unclosed_ch}' (expected '{expected_close[unclosed_ch]}')",
            }
        )

    errors.sort(key=lambda e: int(e["line"]))
    return {"ok": len(errors) == 0, "errors": errors[:50]}


def _strip_leading_cs_attributes(masked_hdr: str, base_offset: int) -> tuple[str, int]:
    """Strip leading whitespace and C# [Attribute(...)] blocks from a header slice."""
    n = len(masked_hdr)
    i = 0
    while i < n:
        while i < n and masked_hdr[i].isspace():
            i += 1
        if i < n and masked_hdr[i] == "[":
            depth = 1
            i += 1
            while i < n and depth > 0:
                c = masked_hdr[i]
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                i += 1
            continue
        break
    return masked_hdr[i:], base_offset + i


def _strip_top_level_clauses(header: str) -> tuple[str, bool]:
    """Return header up to first top-level single `:` or `where` keyword, plus whether top-level `=` exists."""
    n = len(header)
    paren = 0
    bracket = 0
    angle = 0
    has_top_eq = False
    cut_pos = n
    i = 0
    while i < n:
        ch = header[i]
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        elif ch == "<":
            nxt = header[i + 1] if i + 1 < n else ""
            if nxt not in ("=", "<", " "):
                angle += 1
        elif ch == ">":
            prev = header[i - 1] if i > 0 else ""
            if prev != "=" and angle > 0:
                angle -= 1
        elif paren == 0 and bracket == 0 and angle == 0:
            if ch == "=":
                nxt = header[i + 1] if i + 1 < n else ""
                prev = header[i - 1] if i > 0 else ""
                if nxt not in ("=", ">") and prev not in ("=", "!", "<", ">"):
                    has_top_eq = True
            elif ch == ":":
                nxt = header[i + 1] if i + 1 < n else ""
                prev = header[i - 1] if i > 0 else ""
                if nxt != ":" and prev != ":":
                    cut_pos = min(cut_pos, i)
                    break
            elif ch == "w" and header[i : i + 5] == "where":
                prev_ok = i == 0 or not (header[i - 1].isalnum() or header[i - 1] == "_")
                nxt_ok = i + 5 >= n or not (header[i + 5].isalnum() or header[i + 5] == "_")
                if prev_ok and nxt_ok:
                    cut_pos = min(cut_pos, i)
                    break
        i += 1
    return header[:cut_pos].rstrip(), has_top_eq


def _find_last_top_level_parens(text: str) -> tuple[int, int] | None:
    s = text.rstrip()
    if not s.endswith(")"):
        return None
    depth = 0
    close_idx = len(s) - 1
    for i in range(close_idx, -1, -1):
        ch = s[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                return (i, close_idx)
    return None


def _mask_balanced_groups(text: str) -> str:
    out: list[str] = []
    p = b = a = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ch == "(":
            p += 1
            out.append(" ")
        elif ch == ")":
            p = max(0, p - 1)
            out.append(" ")
        elif ch == "[":
            b += 1
            out.append(" ")
        elif ch == "]":
            b = max(0, b - 1)
            out.append(" ")
        elif ch == "<" and p == 0 and b == 0:
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt not in ("=", "<", " "):
                a += 1
                out.append(" ")
            else:
                out.append(ch)
        elif ch == ">" and a > 0 and p == 0 and b == 0:
            a -= 1
            out.append(" ")
        elif p > 0 or b > 0 or a > 0:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _parse_cs_header(
    masked_slice: str,
    orig_content: str,
    base_offset: int,
    *,
    in_type: str,
    in_namespace: str,
    is_brace_open: bool,
    is_expr_body: bool,
    nl_offsets: list[int],
) -> dict[str, Any] | None:
    cleaned, decl_offset = _strip_leading_cs_attributes(masked_slice, base_offset)
    cleaned_r = cleaned.rstrip()
    if not cleaned_r:
        return None

    first_word_m = _CS_IDENT_RE.match(cleaned_r)
    if not first_word_m:
        return None
    first_word = first_word_m.group(0)
    if first_word in ("using", "extern", "return", "throw", "yield", "break", "continue", "goto"):
        return None

    decl_end_offset = base_offset + len(masked_slice)
    orig_decl = orig_content[decl_offset:decl_end_offset]
    start_line = _line_at(nl_offsets, decl_offset)

    # 1. Namespace declaration
    if first_word == "namespace":
        ns_m = re.match(r"namespace\s+([A-Za-z_][\w.]*)", cleaned_r)
        if ns_m:
            return {
                "name": ns_m.group(1),
                "kind": "namespace",
                "container": "",
                "start_line": start_line,
                "end_line": start_line,
                "signature": _collapse_ws(orig_decl),
            }
        return None

    head_core, has_top_eq = _strip_top_level_clauses(cleaned_r)
    if has_top_eq and not is_expr_body:
        return None
    if re.search(r"\bdelegate\b", head_core):
        return None

    # 2. Type declaration: class, partial class, struct, record, interface, enum
    top_only = _mask_balanced_groups(head_core)
    type_m = _CS_TYPE_KW_RE.search(top_only)
    if type_m:
        kw = type_m.group(1)
        is_partial = bool(re.search(r"\bpartial\b", top_only[: type_m.start()]))
        after_kw = head_core[type_m.end() :].lstrip()
        if kw == "record":
            sub_m = re.match(r"(?:class|struct)\s+", after_kw)
            if sub_m:
                after_kw = after_kw[sub_m.end() :]
        name_m = _CS_IDENT_RE.match(after_kw)
        if name_m:
            tname = name_m.group(0).lstrip("@")
            kind = "partial class" if (kw == "class" and is_partial) else kw
            container = in_type if in_type else in_namespace
            return {
                "name": tname,
                "kind": kind,
                "container": container,
                "start_line": start_line,
                "end_line": start_line,
                "signature": _collapse_ws(orig_decl),
            }
        return None

    if not in_type:
        return None

    enclosing_short = in_type.rsplit(".", 1)[-1]

    # 3. Method or Constructor
    paren_span = _find_last_top_level_parens(head_core)
    if paren_span is not None:
        open_p, _ = paren_span
        before_paren = head_core[:open_p].rstrip()
        if not before_paren:
            return None

        if before_paren.endswith(">"):
            depth = 0
            idx = len(before_paren) - 1
            while idx >= 0:
                if before_paren[idx] == ">":
                    depth += 1
                elif before_paren[idx] == "<":
                    depth -= 1
                    if depth == 0:
                        before_paren = before_paren[:idx].rstrip()
                        break
                idx -= 1

        op_m = re.search(r"\boperator\s+([^\s(]+)\s*$", before_paren)
        if op_m:
            return {
                "name": f"operator {op_m.group(1)}",
                "kind": "method",
                "container": in_type,
                "start_line": start_line,
                "end_line": start_line,
                "signature": _collapse_ws(orig_decl),
            }

        dtor_m = re.search(r"(~[A-Za-z_]\w*)\s*$", before_paren)
        if dtor_m:
            return {
                "name": dtor_m.group(1),
                "kind": "constructor",
                "container": in_type,
                "start_line": start_line,
                "end_line": start_line,
                "signature": _collapse_ws(orig_decl),
            }

        name_m = re.search(r"([A-Za-z_@]\w*(?:\.[A-Za-z_@]\w*)?)\s*$", before_paren)
        if not name_m:
            return None
        raw_name = name_m.group(1).lstrip("@")
        short_name = raw_name.rsplit(".", 1)[-1]
        if short_name in _CS_CONTROL_KEYWORDS:
            return None

        kind = "constructor" if short_name == enclosing_short else "method"
        prefix_before_name = before_paren[: name_m.start()].strip()
        if kind == "method" and not prefix_before_name:
            return None

        return {
            "name": short_name,
            "kind": kind,
            "container": in_type,
            "start_line": start_line,
            "end_line": start_line,
            "signature": _collapse_ws(orig_decl),
        }

    # 4. Property or Indexer
    if is_brace_open or is_expr_body:
        if has_top_eq:
            return None
        if head_core.endswith("]"):
            if re.search(r"\bthis\s*\[", head_core):
                return {
                    "name": "this[]",
                    "kind": "property",
                    "container": in_type,
                    "start_line": start_line,
                    "end_line": start_line,
                    "signature": _collapse_ws(orig_decl),
                }
            return None
        prop_m = re.search(r"([A-Za-z_@]\w*(?:\.[A-Za-z_@]\w*)?)\s*$", head_core)
        if not prop_m:
            return None
        raw_prop = prop_m.group(1).lstrip("@")
        short_prop = raw_prop.rsplit(".", 1)[-1]
        if short_prop in _CS_CONTROL_KEYWORDS:
            return None
        prefix_before_prop = head_core[: prop_m.start()].strip()
        if not prefix_before_prop or re.search(r"\bevent\b", prefix_before_prop):
            return None
        return {
            "name": short_prop,
            "kind": "property",
            "container": in_type,
            "start_line": start_line,
            "end_line": start_line,
            "signature": _collapse_ws(orig_decl),
        }

    return None


def _outline_csharp_content(content: str) -> tuple[list[dict[str, Any]], int, str, list[int]]:
    """Parse C# symbols from source content with exact brace-balanced start_line..end_line.

    Uses brace-only fast-skipping over method/property/enum bodies for ~4x speed on 10k+ line files.
    """
    masked = _mask_csharp(content)
    nl_offsets = _build_newline_offsets(content)
    total_lines = content.count("\n") + (0 if content.endswith("\n") else 1) if content else 0

    symbols: list[dict[str, Any]] = []
    file_namespace = ""
    scopes: list[dict[str, Any]] = []

    def current_namespace() -> str:
        for fr in reversed(scopes):
            if fr["role"] == "namespace":
                return fr["name"]
        return file_namespace

    def current_type() -> str:
        parts = [fr["name"] for fr in scopes if fr["role"] == "type"]
        return ".".join(parts)

    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0
    stmt_start = 0
    in_expr_member: dict[str, Any] | None = None
    pos = 0
    n = len(masked)

    while pos < n:
        m = _CS_STRUCT_RE.search(masked, pos)
        if not m:
            break
        tok = m.group(0)
        tok_start = m.start()
        tok_end = m.end()
        pos = tok_end

        if tok == "(":
            paren_depth += 1
            continue
        if tok == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if tok == "[":
            bracket_depth += 1
            continue
        if tok == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue

        if in_expr_member is not None:
            if tok == "{":
                close_pos = _skip_brace_body(masked, tok_end)
                pos = close_pos + 1 if close_pos < n else n
            elif tok == "}":
                brace_depth = max(0, brace_depth - 1)
                if brace_depth < in_expr_member["base_depth"]:
                    in_expr_member["sym"]["end_line"] = _line_at(nl_offsets, tok_start)
                    in_expr_member = None
                    if scopes and brace_depth == scopes[-1]["target_depth"]:
                        fr = scopes.pop()
                        if fr["sym"] is not None:
                            fr["sym"]["end_line"] = _line_at(nl_offsets, tok_start)
                    stmt_start = tok_end
                    paren_depth = 0
                    bracket_depth = 0
            elif tok == ";" and paren_depth == 0 and bracket_depth == 0:
                in_expr_member["sym"]["end_line"] = _line_at(nl_offsets, tok_start)
                in_expr_member = None
                stmt_start = tok_end
            continue

        if paren_depth > 0 or bracket_depth > 0:
            if tok == "{":
                close_pos = _skip_brace_body(masked, tok_end)
                pos = close_pos + 1 if close_pos < n else n
            continue

        if tok == "=>":
            in_t = current_type()
            if in_t:
                sym = _parse_cs_header(
                    masked[stmt_start:tok_start],
                    content,
                    stmt_start,
                    in_type=in_t,
                    in_namespace=current_namespace(),
                    is_brace_open=False,
                    is_expr_body=True,
                    nl_offsets=nl_offsets,
                )
                if sym is not None:
                    symbols.append(sym)
                    in_expr_member = {"sym": sym, "base_depth": brace_depth}
            continue

        if tok == "{":
            sym = _parse_cs_header(
                masked[stmt_start:tok_start],
                content,
                stmt_start,
                in_type=current_type(),
                in_namespace=current_namespace(),
                is_brace_open=True,
                is_expr_body=False,
                nl_offsets=nl_offsets,
            )
            if sym is not None:
                symbols.append(sym)
                k = sym["kind"]
                if k in ("namespace", "class", "partial class", "struct", "record", "interface"):
                    role = "namespace" if k == "namespace" else "type"
                    scopes.append({"role": role, "name": sym["name"], "sym": sym, "target_depth": brace_depth})
                    brace_depth += 1
                    stmt_start = tok_end
                else:
                    # Method, constructor, property, or enum body -> C-speed brace-only skip!
                    close_pos = _skip_brace_body(masked, tok_end)
                    sym["end_line"] = _line_at(nl_offsets, min(close_pos, max(0, n - 1)))
                    pos = close_pos + 1 if close_pos < n else n
                    stmt_start = pos
                    paren_depth = 0
                    bracket_depth = 0
            else:
                # Anonymous/field initializer block -> fast-skip!
                close_pos = _skip_brace_body(masked, tok_end)
                pos = close_pos + 1 if close_pos < n else n
                stmt_start = pos
                paren_depth = 0
                bracket_depth = 0
            continue

        if tok == ";":
            sym = _parse_cs_header(
                masked[stmt_start:tok_start],
                content,
                stmt_start,
                in_type=current_type(),
                in_namespace=current_namespace(),
                is_brace_open=False,
                is_expr_body=False,
                nl_offsets=nl_offsets,
            )
            if sym is not None:
                if sym["kind"] == "namespace":
                    sym["end_line"] = max(sym["start_line"], total_lines)
                    file_namespace = sym["name"]
                    symbols.append(sym)
                elif sym["kind"] in ("record", "class", "partial class", "struct", "interface", "method", "constructor"):
                    sym["end_line"] = _line_at(nl_offsets, tok_start)
                    symbols.append(sym)
            stmt_start = tok_end
            continue

        if tok == "}":
            brace_depth = max(0, brace_depth - 1)
            if scopes and brace_depth == scopes[-1]["target_depth"]:
                fr = scopes.pop()
                if fr["sym"] is not None:
                    fr["sym"]["end_line"] = _line_at(nl_offsets, tok_start)
            stmt_start = tok_end

    if in_expr_member is not None:
        in_expr_member["sym"]["end_line"] = max(in_expr_member["sym"]["start_line"], total_lines)
    for fr in scopes:
        if fr["sym"] is not None and fr["sym"]["end_line"] <= fr["sym"]["start_line"]:
            fr["sym"]["end_line"] = max(fr["sym"]["start_line"], total_lines)

    return symbols, total_lines, masked, nl_offsets


def _outline_python_content(content: str) -> tuple[list[dict[str, Any]], int, str, list[int]]:
    lines = content.splitlines()
    total_lines = len(lines)
    nl_offsets = _build_newline_offsets(content)
    masked = re.sub(r"#[^\n]*", lambda m: " " * len(m.group(0)), content)
    symbols: list[dict[str, Any]] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        pat = re.compile(r"^([ \t]*)(async\s+def|def|class)\s+([A-Za-z_]\w*)\s*(.*):?")
        for idx, line in enumerate(lines, 1):
            m = pat.match(line)
            if m:
                kw = "class" if m.group(2) == "class" else "function"
                symbols.append(
                    {
                        "name": m.group(3),
                        "kind": kw,
                        "container": "",
                        "start_line": idx,
                        "end_line": idx,
                        "signature": _collapse_ws(line),
                    }
                )
        return symbols, total_lines, masked, nl_offsets

    def extract_sig(node: ast.AST) -> str:
        start = getattr(node, "lineno", 1) - 1
        end = min(len(lines), start + 8)
        buf: list[str] = []
        for ln in lines[start:end]:
            buf.append(ln.strip())
            if ln.rstrip().endswith(":"):
                break
        return _collapse_ws(" ".join(buf))

    def visit(body: list[ast.stmt], containers: list[str], in_class: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "container": ".".join(containers),
                        "start_line": int(node.lineno),
                        "end_line": int(getattr(node, "end_lineno", node.lineno)),
                        "signature": extract_sig(node),
                    }
                )
                visit(node.body, containers + [node.name], True)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_prop = any(
                    (isinstance(d, ast.Name) and d.id == "property")
                    or (isinstance(d, ast.Attribute) and d.attr in ("setter", "getter", "deleter"))
                    for d in node.decorator_list
                )
                if in_class:
                    if node.name == "__init__":
                        kind = "constructor"
                    elif is_prop:
                        kind = "property"
                    else:
                        kind = "method"
                else:
                    kind = "function"
                symbols.append(
                    {
                        "name": node.name,
                        "kind": kind,
                        "container": ".".join(containers),
                        "start_line": int(node.lineno),
                        "end_line": int(getattr(node, "end_lineno", node.lineno)),
                        "signature": extract_sig(node),
                    }
                )
                visit(node.body, containers + [node.name], False)

    visit(tree.body, [], False)
    return symbols, total_lines, masked, nl_offsets


def _mask_js_ts(content: str) -> str:
    n = len(content)
    out: list[str] = []
    pos = 0
    while pos < n:
        m = _JS_LEX_RE.search(content, pos)
        if not m:
            out.append(content[pos:])
            break
        start, end = m.start(), m.end()
        if start > pos:
            out.append(content[pos:start])
        tok = m.group(0)
        if tok.startswith("//"):
            out.append(" " * (end - start))
            pos = end
        elif tok == "/*":
            close = content.find("*/", end)
            stop = n if close == -1 else close + 2
            out.append(_blank_preserving_newlines(content[start:stop]))
            pos = stop
        elif tok in ('"', "'", "`"):
            q = tok
            p = end
            while p < n:
                ch = content[p]
                if ch == "\\":
                    p += 2
                    continue
                if ch == q:
                    p += 1
                    break
                if q != "`" and ch in ("\n", "\r"):
                    break
                p += 1
            out.append(_blank_preserving_newlines(content[start:p]))
            pos = p
        else:
            out.append(" " * (end - start))
            pos = end
    return "".join(out)


def _outline_js_ts_content(content: str) -> tuple[list[dict[str, Any]], int, str, list[int]]:
    masked = _mask_js_ts(content)
    nl_offsets = _build_newline_offsets(content)
    total_lines = content.count("\n") + (0 if content.endswith("\n") else 1) if content else 0
    symbols: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []

    def cur_class() -> str:
        return ".".join(fr["name"] for fr in scopes if fr["role"] == "type")

    brace_depth = 0
    paren_depth = 0
    bracket_depth = 0
    stmt_start = 0

    type_re = re.compile(r"\b(class|interface|enum|namespace)\s+([A-Za-z_$][\w$]*)")
    func_re = re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(")
    arrow_re = re.compile(
        r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"
    )
    method_re = re.compile(
        r"^(?:(?:public|private|protected|static|readonly|override|abstract|async|get|set)\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\("
    )
    js_kw = {"if", "for", "while", "switch", "catch", "with", "return", "function", "class", "else", "try", "finally"}

    pos = 0
    n = len(masked)
    while pos < n:
        m = _JS_STRUCT_RE.search(masked, pos)
        if not m:
            break
        tok = m.group(0)
        tok_start, tok_end = m.start(), m.end()
        pos = tok_end

        if tok == "(":
            paren_depth += 1
            continue
        if tok == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if tok == "[":
            bracket_depth += 1
            continue
        if tok == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue

        if paren_depth > 0 or bracket_depth > 0:
            if tok == "{":
                close_pos = _skip_brace_body(masked, tok_end)
                pos = close_pos + 1 if close_pos < n else n
            continue

        if tok == "{":
            hdr_masked = masked[stmt_start:tok_start]
            stripped = hdr_masked.lstrip()
            lead = len(hdr_masked) - len(stripped)
            decl_off = stmt_start + lead
            orig_hdr = content[decl_off:tok_start]
            start_line = _line_at(nl_offsets, decl_off)
            in_cls = cur_class()

            sym: dict[str, Any] | None = None
            is_type_scope = False

            tm = type_re.search(stripped)
            if tm and not in_cls:
                sym = {
                    "name": tm.group(2),
                    "kind": tm.group(1),
                    "container": "",
                    "start_line": start_line,
                    "end_line": start_line,
                    "signature": _collapse_ws(orig_hdr),
                }
                is_type_scope = tm.group(1) in ("class", "namespace")
            else:
                fm = func_re.search(stripped)
                am = arrow_re.search(stripped) if not fm else None
                if fm:
                    sym = {
                        "name": fm.group(1),
                        "kind": "function",
                        "container": in_cls,
                        "start_line": start_line,
                        "end_line": start_line,
                        "signature": _collapse_ws(orig_hdr),
                    }
                elif am:
                    sym = {
                        "name": am.group(1),
                        "kind": "function",
                        "container": in_cls,
                        "start_line": start_line,
                        "end_line": start_line,
                        "signature": _collapse_ws(orig_hdr),
                    }
                elif in_cls:
                    mm = method_re.match(stripped)
                    if mm and mm.group(1) not in js_kw:
                        mname = mm.group(1)
                        kind = "constructor" if mname == "constructor" else "method"
                        sym = {
                            "name": mname,
                            "kind": kind,
                            "container": in_cls,
                            "start_line": start_line,
                            "end_line": start_line,
                            "signature": _collapse_ws(orig_hdr),
                        }

            if sym is not None:
                symbols.append(sym)
            if is_type_scope and sym is not None:
                scopes.append({"role": "type", "name": sym["name"], "sym": sym, "target_depth": brace_depth})
                brace_depth += 1
                stmt_start = tok_end
            else:
                close_pos = _skip_brace_body(masked, tok_end)
                if sym is not None:
                    sym["end_line"] = _line_at(nl_offsets, min(close_pos, max(0, n - 1)))
                pos = close_pos + 1 if close_pos < n else n
                stmt_start = pos
                paren_depth = 0
                bracket_depth = 0
            continue

        if tok == ";":
            stmt_start = tok_end
            continue

        if tok == "}":
            brace_depth = max(0, brace_depth - 1)
            if scopes and brace_depth == scopes[-1]["target_depth"]:
                fr = scopes.pop()
                if fr["sym"] is not None:
                    fr["sym"]["end_line"] = _line_at(nl_offsets, tok_start)
            stmt_start = tok_end

    return symbols, total_lines, masked, nl_offsets


def _outline_file_full(path: Path, raw_bytes: bytes | None = None) -> tuple[dict[str, Any], str, str, list[int]]:
    """Cached outline returning (result_dict, content, masked, nl_offsets)."""
    t0 = time.perf_counter()
    p = Path(path)
    ext = p.suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "unknown")

    try:
        st = p.stat()
    except OSError as exc:
        return (
            {
                "ok": False,
                "error": str(exc),
                "lang": lang,
                "path": str(p),
                "lines": 0,
                "symbols": [],
                "ms": round((time.perf_counter() - t0) * 1000.0, 3),
            },
            "",
            "",
            [],
        )

    cache_key = (str(p.resolve()), int(st.st_mtime_ns), int(st.st_size))
    with _OUTLINE_CACHE_LOCK:
        cached = _OUTLINE_CACHE.get(cache_key)
        if cached is not None:
            _OUTLINE_CACHE.move_to_end(cache_key)
            c_res, c_content, c_masked, c_nl = cached
            res = dict(c_res)
            res["ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            return res, c_content, c_masked, c_nl

    if raw_bytes is not None:
        content = raw_bytes.decode("utf-8-sig", errors="replace")
    else:
        try:
            content = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return (
                {
                    "ok": False,
                    "error": str(exc),
                    "lang": lang,
                    "path": str(p),
                    "lines": 0,
                    "symbols": [],
                    "ms": round((time.perf_counter() - t0) * 1000.0, 3),
                },
                "",
                "",
                [],
            )

    if lang == "csharp":
        symbols, total_lines, masked, nl_offsets = _outline_csharp_content(content)
    elif lang == "python":
        symbols, total_lines, masked, nl_offsets = _outline_python_content(content)
    elif lang in ("javascript", "typescript"):
        symbols, total_lines, masked, nl_offsets = _outline_js_ts_content(content)
    else:
        symbols = []
        total_lines = content.count("\n") + (0 if content.endswith("\n") else 1) if content else 0
        masked = content
        nl_offsets = _build_newline_offsets(content)

    result = {
        "ok": True,
        "lang": lang,
        "path": str(p),
        "lines": total_lines,
        "symbols": symbols,
        "ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }
    with _OUTLINE_CACHE_LOCK:
        _OUTLINE_CACHE[cache_key] = (result, content, masked, nl_offsets)
        _OUTLINE_CACHE.move_to_end(cache_key)
        while len(_OUTLINE_CACHE) > _OUTLINE_CACHE_MAX:
            _OUTLINE_CACHE.popitem(last=False)

    return dict(result), content, masked, nl_offsets


def outline_file(path: str | Path) -> dict[str, Any]:
    """Fast zero-external-dep parser supporting .cs, .py, .js, .mjs, .ts, .tsx."""
    res, _, _, _ = _outline_file_full(Path(path))
    return res


def _is_chimera_release_dir(path: Path) -> bool:
    """Detect whether path sits inside Chimera's own install/release directory."""
    norm = str(path).replace("\\", "/").lower().rstrip("/")
    markers = (
        "/appdata/local/chimera/releases",
        "/.local/share/chimera/releases",
    )
    for marker in markers:
        idx = norm.find(marker)
        if idx != -1:
            after = idx + len(marker)
            if after == len(norm) or norm[after] == "/":
                return True
    return False


def resolve_safe_repo(repo: str | None, fallback_cwd: str | None = None) -> Path:
    """Resolve a workspace repository safely, rejecting accidental fallback to Chimera's install/release dir."""
    raw_repo = (repo or "").strip()
    raw_fallback = (fallback_cwd or "").strip()

    if not raw_repo or raw_repo in (".", "./", ".\\"):
        base_str = raw_fallback if raw_fallback else os.getcwd()
        base_path = Path(base_str).expanduser()
        try:
            resolved = base_path.resolve()
        except OSError:
            resolved = base_path
        if _is_chimera_release_dir(resolved) or _is_chimera_release_dir(base_path):
            raise ValueError(
                f"Refusing to resolve workspace to Chimera's own install/release directory ({resolved}). "
                "Pass an explicit `repo` path (e.g. repo='E:/dev/your-project') instead of relying on the daemon CWD."
            )
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Repository path does not exist or is not a directory: {resolved}")
        return resolved

    p = Path(raw_repo).expanduser()
    if p.is_absolute():
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Repository path does not exist or is not a directory: {resolved}")
        return resolved

    anchor_str = raw_fallback if raw_fallback else os.getcwd()
    anchor = Path(anchor_str).expanduser()
    try:
        anchor_resolved = anchor.resolve()
    except OSError:
        anchor_resolved = anchor

    candidate = anchor_resolved / p
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate

    if _is_chimera_release_dir(anchor_resolved) or _is_chimera_release_dir(resolved):
        raise ValueError(
            f"Refusing to resolve relative repo '{raw_repo}' inside Chimera's own install/release directory ({resolved}). "
            "Pass an explicit absolute `repo` path for your workspace."
        )
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {resolved}")
    return resolved


def _iter_code_files(repo: Path) -> list[Path]:
    """Fast os.scandir recursive walk over supported code files, skipping build/vendor dirs."""
    files: list[Path] = []
    stack: list[str] = [str(repo)]
    skip = _SKIP_DIRS
    exts = _SUPPORTED_EXTS
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    name = entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if name not in skip:
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            dot = name.rfind(".")
                            if dot != -1 and name[dot:].lower() in exts:
                                files.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return files


def _is_test_file(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith("tests.cs") or name.endswith("test.cs") or name.endswith("specs.cs"):
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    parts_low = {part.lower() for part in path.parts}
    return bool(parts_low & {"tests", "test", "__tests__"})


def _rel_posix(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _get_repo_snapshot(repo_path: Path) -> dict[str, Any]:
    """Single-read snapshot of repo code files + raw bytes (cached briefly for large repos >= 150 files)."""
    key = str(repo_path)
    now = time.monotonic()
    with _REPO_CACHE_LOCK:
        cached = _REPO_CACHE.get(key)
        if cached is not None and (now - cached["ts"]) <= _REPO_CACHE_TTL_S:
            _REPO_CACHE.move_to_end(key)
            return cached

    files = _iter_code_files(repo_path)
    raw_map: dict[Path, bytes] = {}
    rel_map: dict[Path, str] = {}
    test_flags: dict[Path, bool] = {}
    repo_prefix = str(repo_path).replace("\\", "/").rstrip("/") + "/"

    for f in files:
        try:
            raw_map[f] = f.read_bytes()
        except OSError:
            continue
        f_norm = str(f).replace("\\", "/")
        rel_map[f] = f_norm[len(repo_prefix) :] if f_norm.startswith(repo_prefix) else _rel_posix(f, repo_path)
        test_flags[f] = _is_test_file(f)

    snap = {
        "ts": now,
        "files": list(raw_map.keys()),
        "raw": raw_map,
        "rel": rel_map,
        "is_test": test_flags,
    }
    if len(snap["files"]) >= _REPO_CACHE_MIN_FILES:
        with _REPO_CACHE_LOCK:
            _REPO_CACHE[key] = snap
            _REPO_CACHE.move_to_end(key)
            while len(_REPO_CACHE) > _REPO_CACHE_MAX:
                _REPO_CACHE.popitem(last=False)
    return snap


def _find_enclosing_symbol(symbols: list[dict[str, Any]], line: int) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_span = 10**9
    for sym in symbols:
        if sym["kind"] == "namespace":
            continue
        s, e = sym["start_line"], sym["end_line"]
        if s <= line <= e:
            span = e - s
            if span < best_span or (span == best_span and sym["kind"] in ("method", "constructor", "property", "function")):
                best = sym
                best_span = span
    return best


def _extract_body_lines(lines: list[str], start_line: int, end_line: int) -> str:
    s = max(0, start_line - 1)
    e = min(len(lines), end_line)
    return "\n".join(lines[s:e])


def _extract_callees_from_masked(
    masked_lines: list[str],
    start_line: int,
    end_line: int,
    self_name: str,
) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    s = max(0, start_line - 1)
    e = min(len(masked_lines), end_line)
    body_start = s
    for idx in range(s, min(e, s + 12)):
        ln_txt = masked_lines[idx]
        if "{" in ln_txt or "=>" in ln_txt or ln_txt.rstrip().endswith(":"):
            body_start = idx
            break
    for idx in range(body_start, e):
        ln_txt = masked_lines[idx]
        scan_txt = ln_txt
        if idx == s:
            brace_i = ln_txt.find("{")
            arrow_i = ln_txt.find("=>")
            cut = brace_i if brace_i != -1 else (arrow_i + 2 if arrow_i != -1 else -1)
            if cut == -1:
                continue
            scan_txt = ln_txt[cut:]
        for m in _CS_CALL_RE.finditer(scan_txt):
            cname = m.group(1)
            if cname == self_name or cname in _NOISE_CALLEES or len(cname) < 2:
                continue
            if cname not in seen:
                seen[cname] = idx + 1
    return list(seen.items())


def _callgraph_slice_with_snapshot(
    repo_path: Path,
    symbol: str,
    hops: int,
    max_files: int,
    snap: dict[str, Any],
) -> tuple[dict[str, Any], dict[Path, tuple[dict[str, Any], str, str, list[int]]]]:
    t0 = time.perf_counter()
    raw_symbol = str(symbol or "").strip()
    if not raw_symbol:
        return (
            {
                "ok": False,
                "error": "Symbol must be non-empty",
                "repo": str(repo_path),
                "symbol": raw_symbol,
                "hops": hops,
                "definitions": [],
                "partial_files": [],
                "callers": [],
                "callees": [],
                "ms": 0.0,
            },
            {},
        )

    hops = max(1, min(3, int(hops)))
    max_files = max(1, int(max_files))

    if "." in raw_symbol:
        target_container, target_name = raw_symbol.rsplit(".", 1)
    else:
        target_container, target_name = "", raw_symbol

    all_files: list[Path] = snap["files"]
    raw_map: dict[Path, bytes] = snap["raw"]
    rel_map: dict[Path, str] = snap["rel"]
    test_flags: dict[Path, bool] = snap["is_test"]

    needle_bytes = target_name.encode("utf-8")
    def_hint_re = re.compile(
        rb"(?:class|struct|record|interface|enum|def|function|void|static|public|private|internal|protected)\s+[^\n;]{0,80}\b"
        + re.escape(needle_bytes)
        + rb"\b"
    )

    # Pass 1: C-speed bytes prefilter across in-RAM snapshot
    candidate_files: list[tuple[int, int, int, Path]] = []
    t_low = target_name.lower()
    c_low = target_container.lower()
    for f in all_files:
        raw = raw_map[f]
        if needle_bytes not in raw:
            continue
        is_t = 1 if test_flags[f] else 0
        stem = f.stem.lower()
        # Definitions & filename matches come first!
        has_def_hint = 0 if def_hint_re.search(raw) else 1
        name_boost = 0 if (t_low in stem or (c_low and c_low in stem)) else 1
        candidate_files.append((is_t, name_boost, has_def_hint, f))

    candidate_files.sort(key=lambda item: (item[0], item[1], item[2], len(raw_map[item[3]])))
    selected = [item[3] for item in candidate_files[:max_files]]

    parsed_cache: dict[Path, tuple[dict[str, Any], str, str, list[int]]] = {}

    def get_parsed(f: Path) -> tuple[dict[str, Any], str, str, list[int]]:
        if f in parsed_cache:
            return parsed_cache[f]
        res = _outline_file_full(f, raw_bytes=raw_map.get(f))
        parsed_cache[f] = res
        return res

    definitions: list[dict[str, Any]] = []
    partial_files: list[str] = []
    callers: list[dict[str, Any]] = []
    seen_callers: set[tuple[str, str, int]] = set()
    word_re = re.compile(rf"\b{re.escape(target_name)}\b")

    for f in selected:
        out, content, masked, nl_offsets = get_parsed(f)
        if not out.get("ok"):
            continue
        rel = rel_map[f]
        syms = out["symbols"]

        def_ranges: list[tuple[int, int]] = []
        for sym in syms:
            if sym["name"] == target_name:
                if target_container and not (
                    sym["container"] == target_container
                    or sym["container"].endswith("." + target_container)
                ):
                    continue
                d_entry = {
                    "name": sym["name"],
                    "kind": sym["kind"],
                    "container": sym["container"],
                    "file": rel,
                    "abs_path": str(f),
                    "start_line": sym["start_line"],
                    "end_line": sym["end_line"],
                    "signature": sym["signature"],
                }
                definitions.append(d_entry)
                def_ranges.append((sym["start_line"], sym["end_line"]))
                if "partial" in sym["kind"] and rel not in partial_files:
                    partial_files.append(rel)

        # Hop-1 callers in this file (skip huge test sweeps once we already have abundant callers)
        if len(callers) < 80 or not test_flags[f]:
            for wm in word_re.finditer(masked):
                ln = _line_at(nl_offsets, wm.start())
                if any(ds <= ln <= de for ds, de in def_ranges):
                    continue
                enc = _find_enclosing_symbol(syms, ln)
                if enc is None:
                    continue
                if enc["name"] == target_name and any(ds <= enc["start_line"] <= de for ds, de in def_ranges):
                    continue
                ckey = (rel, enc["name"], enc["start_line"])
                if ckey in seen_callers:
                    continue
                seen_callers.add(ckey)
                callers.append(
                    {
                        "symbol": enc["name"],
                        "container": enc["container"],
                        "kind": enc["kind"],
                        "file": rel,
                        "abs_path": str(f),
                        "start_line": enc["start_line"],
                        "end_line": enc["end_line"],
                        "call_line": ln,
                        "signature": enc["signature"],
                        "hop": 1,
                        "target": target_name,
                        "is_test": test_flags[f],
                    }
                )

    definitions.sort(key=lambda d: (1 if test_flags.get(Path(d["abs_path"]), False) else 0, d["file"], d["start_line"]))

    # Locate sibling partial files if target is inside a partial class
    sibling_files: list[Path] = []
    primary_containers = {d["container"].split(".")[0] for d in definitions if d.get("container")}
    if definitions and definitions[0]["kind"] == "partial class":
        primary_containers.add(target_name)
    if primary_containers:
        for f in all_files:
            stem = f.stem
            if any(stem == pc or stem.startswith(pc + ".") for pc in primary_containers):
                sibling_files.append(f)

    # Hop-1 Callees from target definition bodies
    callees: list[dict[str, Any]] = []
    seen_callees: set[tuple[str, str, int]] = set()
    raw_callee_hits: list[tuple[str, int, str]] = []

    for d in definitions[:6]:
        if d["kind"] in ("method", "constructor", "property", "function"):
            f = Path(d["abs_path"])
            _, _, masked, _ = get_parsed(f)
            masked_lines = masked.splitlines()
            for cname, cln in _extract_callees_from_masked(masked_lines, d["start_line"], d["end_line"], d["name"]):
                raw_callee_hits.append((cname, cln, d["name"]))

    def resolve_symbols_batch(names: list[str], *, budget_files: int) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        remaining = [nm for nm in dict.fromkeys(names) if nm not in _NOISE_CALLEES]
        if not remaining:
            return found

        rem_set = set(remaining)
        rem_bytes = {nm: nm.encode("utf-8") for nm in remaining}

        # 1. Check already-parsed files first (zero cost!)
        for pf in list(parsed_cache.keys()):
            if not rem_set:
                break
            out, _, _, _ = parsed_cache[pf]
            rel = rel_map[pf]
            for sym in out.get("symbols", []):
                if sym["name"] in rem_set and sym["kind"] != "namespace":
                    found[sym["name"]] = {
                        "name": sym["name"],
                        "kind": sym["kind"],
                        "container": sym["container"],
                        "file": rel,
                        "abs_path": str(pf),
                        "start_line": sym["start_line"],
                        "end_line": sym["end_line"],
                        "signature": sym["signature"],
                    }
                    rem_set.discard(sym["name"])

        if not rem_set:
            return found

        # 2. Check sibling partial files ONLY if raw bytes actually contain a remaining name!
        checked = set(parsed_cache.keys())
        for sf in sibling_files:
            if not rem_set:
                break
            if sf in checked:
                continue
            checked.add(sf)
            raw = raw_map.get(sf, b"")
            if not any(rem_bytes[nm] in raw for nm in rem_set):
                continue
            out, _, _, _ = get_parsed(sf)
            rel = rel_map[sf]
            for sym in out.get("symbols", []):
                if sym["name"] in rem_set and sym["kind"] != "namespace":
                    found[sym["name"]] = {
                        "name": sym["name"],
                        "kind": sym["kind"],
                        "container": sym["container"],
                        "file": rel,
                        "abs_path": str(sf),
                        "start_line": sym["start_line"],
                        "end_line": sym["end_line"],
                        "signature": sym["signature"],
                    }
                    rem_set.discard(sym["name"])

        if not rem_set or budget_files <= 0:
            return found

        # 3. Fast raw-bytes prefilter over remaining non-test repo files
        hits: list[Path] = []
        active_bytes = [rem_bytes[nm] for nm in list(rem_set)[:14]]
        for f in all_files:
            if f in checked or test_flags[f]:
                continue
            raw = raw_map[f]
            if any(b in raw for b in active_bytes):
                hits.append(f)
        hits.sort(key=lambda p: len(raw_map[p]))

        for f in hits[:budget_files]:
            if not rem_set:
                break
            out, _, _, _ = get_parsed(f)
            rel = rel_map[f]
            for sym in out.get("symbols", []):
                if sym["name"] in rem_set and sym["kind"] != "namespace":
                    found[sym["name"]] = {
                        "name": sym["name"],
                        "kind": sym["kind"],
                        "container": sym["container"],
                        "file": rel,
                        "abs_path": str(f),
                        "start_line": sym["start_line"],
                        "end_line": sym["end_line"],
                        "signature": sym["signature"],
                    }
                    rem_set.discard(sym["name"])
        return found

    callee_names_hop1 = [nm for nm, _, _ in raw_callee_hits[:16]]
    resolved_hop1 = resolve_symbols_batch(callee_names_hop1, budget_files=min(10, max(4, max_files // 4)))
    for cname, cln, caller_nm in raw_callee_hits:
        info = resolved_hop1.get(cname)
        if info is not None:
            key = (info["file"], info["name"], info["start_line"])
            if key not in seen_callees:
                seen_callees.add(key)
                callees.append(
                    {
                        "symbol": info["name"],
                        "container": info["container"],
                        "kind": info["kind"],
                        "file": info["file"],
                        "abs_path": info["abs_path"],
                        "start_line": info["start_line"],
                        "end_line": info["end_line"],
                        "call_line": cln,
                        "signature": info["signature"],
                        "hop": 1,
                        "caller": caller_nm,
                    }
                )

    # Hop 2: callers of hop-1 callers AND callees of hop-1 callees
    if hops >= 2:
        hop1_caller_names = [
            c["symbol"]
            for c in callers
            if c["hop"] == 1
            and not c.get("is_test")
            and c["symbol"] != target_name
            and c["symbol"] not in _NOISE_CALLEES
            and len(c["symbol"]) >= 3
        ]
        hop1_caller_names = list(dict.fromkeys(hop1_caller_names))[:6]
        if hop1_caller_names:
            hop1_bytes = [nm.encode("utf-8") for nm in hop1_caller_names]
            hop2_word_re = re.compile(r"\b(" + "|".join(re.escape(nm) for nm in hop1_caller_names) + r")\b")
            hop1_def_set = {(c["file"], c["symbol"], c["start_line"]) for c in callers if c["hop"] == 1}

            # First check already-parsed files, then select up to 10 best extra files (non-test & smaller first!)
            hop2_parsed_first = [p for p in parsed_cache.keys() if any(b in raw_map.get(p, b"") for b in hop1_bytes)]
            extra_hits: list[Path] = []
            for f in all_files:
                if f in parsed_cache:
                    continue
                raw = raw_map[f]
                if any(b in raw for b in hop1_bytes):
                    extra_hits.append(f)
            extra_hits.sort(key=lambda p: (1 if test_flags[p] else 0, len(raw_map[p])))
            extra_cap = min(10, max(4, max_files // 4))
            hop2_candidates = hop2_parsed_first + extra_hits[:extra_cap]

            hop2_added = 0
            for f in hop2_candidates:
                if hop2_added >= 24:
                    break
                out, _, masked, nl_offsets = get_parsed(f)
                if not out.get("ok"):
                    continue
                rel = rel_map[f]
                syms = out["symbols"]
                for wm in hop2_word_re.finditer(masked):
                    hit_name = wm.group(1)
                    ln = _line_at(nl_offsets, wm.start())
                    enc = _find_enclosing_symbol(syms, ln)
                    if enc is None:
                        continue
                    if enc["name"] in (hit_name, target_name):
                        continue
                    if (rel, enc["name"], enc["start_line"]) in hop1_def_set:
                        continue
                    ckey = (rel, enc["name"], enc["start_line"])
                    if ckey in seen_callers:
                        continue
                    seen_callers.add(ckey)
                    callers.append(
                        {
                            "symbol": enc["name"],
                            "container": enc["container"],
                            "kind": enc["kind"],
                            "file": rel,
                            "abs_path": str(f),
                            "start_line": enc["start_line"],
                            "end_line": enc["end_line"],
                            "call_line": ln,
                            "signature": enc["signature"],
                            "hop": 2,
                            "target": hit_name,
                            "is_test": test_flags[f],
                        }
                    )
                    hop2_added += 1
                    if hop2_added >= 24:
                        break

        # Hop-2 callees
        raw_callee_hop2: list[tuple[str, int, str]] = []
        for ce in callees[:6]:
            if ce["hop"] != 1 or ce["kind"] not in ("method", "constructor", "property", "function"):
                continue
            f = Path(ce["abs_path"])
            _, _, masked, _ = get_parsed(f)
            masked_lines = masked.splitlines()
            for cname, cln in _extract_callees_from_masked(
                masked_lines, ce["start_line"], ce["end_line"], ce["symbol"]
            )[:8]:
                if cname != target_name:
                    raw_callee_hop2.append((cname, cln, ce["symbol"]))

        if raw_callee_hop2:
            resolved_hop2 = resolve_symbols_batch(
                [nm for nm, _, _ in raw_callee_hop2[:10]],
                budget_files=min(6, max(2, max_files // 6)),
            )
            for cname, cln, caller_nm in raw_callee_hop2:
                info = resolved_hop2.get(cname)
                if info is None:
                    continue
                key = (info["file"], info["name"], info["start_line"])
                if key in seen_callees:
                    continue
                seen_callees.add(key)
                callees.append(
                    {
                        "symbol": info["name"],
                        "container": info["container"],
                        "kind": info["kind"],
                        "file": info["file"],
                        "abs_path": info["abs_path"],
                        "start_line": info["start_line"],
                        "end_line": info["end_line"],
                        "call_line": cln,
                        "signature": info["signature"],
                        "hop": 2,
                        "caller": caller_nm,
                    }
                )

    callers.sort(key=lambda c: (c["hop"], 1 if c.get("is_test") else 0, c["file"], c["start_line"]))
    callees.sort(key=lambda c: (c["hop"], c["file"], c["start_line"]))

    res = {
        "ok": True,
        "repo": str(repo_path),
        "symbol": raw_symbol,
        "hops": hops,
        "files_scanned": len(all_files),
        "files_parsed": len(parsed_cache),
        "definitions": definitions,
        "partial_files": partial_files,
        "callers": callers,
        "callees": callees,
        "ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }
    return res, parsed_cache


def callgraph_slice(
    repo: str | Path,
    symbol: str,
    hops: int = 2,
    max_files: int = 40,
) -> dict[str, Any]:
    """Scan repo for definitions (including C# partial classes), 2-hop callers & callees with file+line ranges."""
    repo_path = Path(repo).resolve()
    snap = _get_repo_snapshot(repo_path)
    res, _ = _callgraph_slice_with_snapshot(repo_path, symbol, hops, max_files, snap)
    return res


def _find_related_types(
    signatures: list[str],
    exclude_names: set[str],
    snap: dict[str, Any],
    parsed_cache: dict[Path, tuple[dict[str, Any], str, str, list[int]]],
    max_types: int = 8,
) -> list[dict[str, Any]]:
    """Find type/struct/record/enum/interface definitions referenced in signature(s)."""
    cand_names: list[str] = []
    for sig in signatures:
        for m in _PASCAL_TYPE_RE.finditer(sig):
            tname = m.group(1)
            if tname not in exclude_names and tname not in _BUILTIN_TYPE_NAMES and tname not in cand_names:
                cand_names.append(tname)
    if not cand_names:
        return []
    cand_names = cand_names[:12]

    found: dict[str, dict[str, Any]] = {}
    rem_set = set(cand_names)
    rel_map: dict[Path, str] = snap["rel"]
    raw_map: dict[Path, bytes] = snap["raw"]
    test_flags: dict[Path, bool] = snap["is_test"]
    type_kinds = {"class", "partial class", "struct", "record", "interface", "enum"}

    # 1. Check already-parsed files first (0 extra work!)
    for pf, (out, _, _, _) in parsed_cache.items():
        if not rem_set:
            break
        if not out.get("ok"):
            continue
        rel = rel_map[pf]
        for sym in out["symbols"]:
            if sym["name"] in rem_set and sym["kind"] in type_kinds:
                found[sym["name"]] = {
                    "name": sym["name"],
                    "kind": sym["kind"],
                    "file": rel,
                    "range": f"{sym['start_line']}-{sym['end_line']}",
                    "signature": sym["signature"],
                }
                rem_set.discard(sym["name"])

    if not rem_set:
        return [found[nm] for nm in cand_names if nm in found][:max_types]

    # 2. Fast bytes `in` prefilter + lightweight type-declaration check on remaining non-test files
    #    Check filename-stem matches first and remove each type from `pending` as soon as located.
    decl_res = {
        nm: re.compile(rb"(?:class|struct|record|interface|enum)\s+(?:(?:class|struct)\s+)?" + re.escape(nm.encode("utf-8")) + rb"\b")
        for nm in rem_set
    }
    name_bytes = {nm: nm.encode("utf-8") for nm in rem_set}
    pending = set(rem_set)
    low_pending = {nm.lower() for nm in pending}

    non_test_files = [f for f in snap["files"] if f not in parsed_cache and not test_flags[f]]
    non_test_files.sort(key=lambda f: (0 if f.stem.lower() in low_pending else 1, len(raw_map[f])))

    matched_files: list[Path] = []
    for f in non_test_files:
        if not pending or len(matched_files) >= 8:
            break
        raw = raw_map[f]
        hit_nms = [nm for nm in pending if name_bytes[nm] in raw and decl_res[nm].search(raw)]
        if hit_nms:
            matched_files.append(f)
            for nm in hit_nms:
                pending.discard(nm)

    for f in matched_files:
        if not rem_set:
            break
        out, _, _, _ = _outline_file_full(f, raw_bytes=raw_map.get(f))
        if not out.get("ok"):
            continue
        rel = rel_map[f]
        for sym in out["symbols"]:
            if sym["name"] in rem_set and sym["kind"] in type_kinds:
                found[sym["name"]] = {
                    "name": sym["name"],
                    "kind": sym["kind"],
                    "file": rel,
                    "range": f"{sym['start_line']}-{sym['end_line']}",
                    "signature": sym["signature"],
                }
                rem_set.discard(sym["name"])

    return [found[nm] for nm in cand_names if nm in found][:max_types]


def _find_matching_tests(
    symbol_name: str,
    caller_names: list[str],
    container_names: list[str],
    snap: dict[str, Any],
    parsed_cache: dict[Path, tuple[dict[str, Any], str, str, list[int]]],
    max_tests: int = 8,
) -> list[dict[str, Any]]:
    """Locate matching test methods from *Tests.cs / test_*.py / *.test.js covering symbol or its callers."""
    test_flags: dict[Path, bool] = snap["is_test"]
    raw_map: dict[Path, bytes] = snap["raw"]
    rel_map: dict[Path, str] = snap["rel"]
    test_files = [f for f in snap["files"] if test_flags[f]]
    if not test_files:
        return []

    search_terms: list[tuple[str, int]] = [(symbol_name, 1)]
    for cn in caller_names[:6]:
        if cn != symbol_name and len(cn) >= 3 and cn not in _NOISE_CALLEES:
            search_terms.append((cn, 2))
    for cont in container_names[:2]:
        if cont != symbol_name and len(cont) >= 3:
            search_terms.append((cont, 3))

    term_list = list(dict.fromkeys(t for t, _ in search_terms))
    prio_map = {t: p for t, p in reversed(search_terms)}
    sym_bytes = symbol_name.encode("utf-8")
    caller_bytes = [t.encode("utf-8") for t, p in search_terms if p == 2]
    cont_bytes = [t.encode("utf-8") for t, p in search_terms if p == 3]

    matched_test_files: list[tuple[int, int, Path]] = []
    for tf in test_files:
        raw = raw_map[tf]
        if sym_bytes in raw:
            matched_test_files.append((0, len(raw), tf))
        elif any(b in raw for b in caller_bytes):
            matched_test_files.append((1, len(raw), tf))
        elif any(b in raw for b in cont_bytes):
            matched_test_files.append((2, len(raw), tf))

    # Prioritize direct symbol hits, then caller hits; smaller test files first after priority
    matched_test_files.sort(key=lambda item: (item[0], item[1]))
    word_re = re.compile(r"\b(" + "|".join(re.escape(t) for t in term_list) + r")\b")

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    for _, _, tf in matched_test_files[:4]:
        if tf in parsed_cache:
            out, _, masked, nl_offsets = parsed_cache[tf]
        else:
            out, _, masked, nl_offsets = _outline_file_full(tf, raw_bytes=raw_map.get(tf))
        if not out.get("ok"):
            continue
        rel = rel_map[tf]
        syms = out["symbols"]

        for wm in word_re.finditer(masked):
            matched_term = wm.group(1)
            ln = _line_at(nl_offsets, wm.start())
            enc = _find_enclosing_symbol(syms, ln)
            if enc is None or enc["kind"] not in ("method", "function"):
                continue
            key = (rel, enc["name"], enc["start_line"])
            if key in seen:
                continue
            seen.add(key)
            # Prioritize actual runnable test methods (public in C#, test_* in Python) over private helpers
            sig_low = enc["signature"].lower()
            is_private_helper = ("private " in sig_low or "internal " in sig_low) and not enc["name"].lower().startswith("test")
            results.append(
                {
                    "name": enc["name"],
                    "container": enc["container"],
                    "file": rel,
                    "range": f"{enc['start_line']}-{enc['end_line']}",
                    "match_line": ln,
                    "via": matched_term,
                    "priority": (prio_map.get(matched_term, 3), 1 if is_private_helper else 0),
                    "signature": enc["signature"],
                }
            )
            if len(results) >= max_tests * 3:
                break
        if sum(1 for r in results if r["priority"][1] == 0) >= max_tests:
            break

    results.sort(key=lambda r: (r["priority"][1], r["priority"][0], r["file"], int(r["range"].split("-")[0])))
    trimmed = []
    for r in results[:max_tests]:
        r2 = dict(r)
        r2.pop("priority", None)
        trimmed.append(r2)
    return trimmed


def surgical_bundle(
    repo: str | Path,
    symbol: str,
    max_bytes: int = 8192,
) -> dict[str, Any]:
    """Return ONE compact surgical packet (<= max_bytes serialized JSON):
    target definition body, 2-hop caller/callee signatures + file:line anchors,
    related types/structs referenced in signature, AND matching test methods.
    """
    t0 = time.perf_counter()
    max_bytes = max(512, int(max_bytes))
    repo_path = Path(repo).resolve()
    snap = _get_repo_snapshot(repo_path)

    # Fast stat-validated bundle cache for large repos (guarantees < 5 ms warm while invalidating on any file edit)
    bkey = (str(repo_path), str(symbol or "").strip(), max_bytes)
    if len(snap["files"]) >= _REPO_CACHE_MIN_FILES:
        with _BUNDLE_CACHE_LOCK:
            bcached = _BUNDLE_CACHE.get(bkey)
            if bcached is not None and bcached[0] == snap["ts"]:
                st_ok = True
                for ref_p, exp_mtime, exp_sz in bcached[1]:
                    try:
                        st = ref_p.stat()
                        if int(st.st_mtime_ns) != exp_mtime or int(st.st_size) != exp_sz:
                            st_ok = False
                            break
                    except OSError:
                        st_ok = False
                        break
                if st_ok:
                    _BUNDLE_CACHE.move_to_end(bkey)
                    hit_pkt = json.loads(json.dumps(bcached[2], ensure_ascii=False))
                    hit_pkt["ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                    return hit_pkt

    cg, parsed_cache = _callgraph_slice_with_snapshot(repo_path, symbol, hops=2, max_files=24, snap=snap)
    if not cg.get("ok"):
        return cg

    target_short = symbol.rsplit(".", 1)[-1]

    bundle_defs: list[dict[str, Any]] = []
    signatures: list[str] = []
    containers: list[str] = []
    max_initial_body_chars = max(600, min(4000, max_bytes // 2))

    for d in cg["definitions"][:4]:
        signatures.append(d["signature"])
        if d.get("container") and d["container"] not in containers:
            containers.append(d["container"].split(".")[0])
        if d["kind"] in ("class", "partial class", "struct", "record", "interface") and d["name"] not in containers:
            containers.append(d["name"])
        p = Path(d["abs_path"])
        if p in parsed_cache:
            lines = parsed_cache[p][1].splitlines()
        else:
            try:
                lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                lines = []
        body = _extract_body_lines(lines, d["start_line"], d["end_line"])
        if len(body) > max_initial_body_chars:
            cut = body[:max_initial_body_chars].rsplit("\n", 1)[0]
            body = cut + "\n// ... (truncated)"
        bundle_defs.append(
            {
                "name": d["name"],
                "kind": d["kind"],
                "container": d["container"],
                "file": d["file"],
                "range": f"{d['start_line']}-{d['end_line']}",
                "signature": d["signature"],
                "body": body,
            }
        )

    compact_callers = [
        {
            "symbol": c["symbol"],
            "container": c["container"],
            "file": c["file"],
            "anchor": f"{c['file']}:{c['call_line']}",
            "range": f"{c['start_line']}-{c['end_line']}",
            "hop": c["hop"],
            "signature": c["signature"],
        }
        for c in cg["callers"][:12]
    ]
    compact_callees = [
        {
            "symbol": c["symbol"],
            "container": c["container"],
            "file": c["file"],
            "anchor": f"{c['file']}:{c['start_line']}",
            "range": f"{c['start_line']}-{c['end_line']}",
            "hop": c["hop"],
            "signature": c["signature"],
        }
        for c in cg["callees"][:12]
    ]

    related_types = _find_related_types(
        signatures,
        exclude_names={target_short},
        snap=snap,
        parsed_cache=parsed_cache,
        max_types=8,
    )

    non_test_callers = [c["symbol"] for c in cg["callers"] if not c.get("is_test")]
    matching_tests = _find_matching_tests(
        target_short,
        non_test_callers,
        containers,
        snap=snap,
        parsed_cache=parsed_cache,
        max_tests=8,
    )

    packet: dict[str, Any] = {
        "ok": True,
        "repo": str(repo_path),
        "symbol": symbol,
        "partial_files": cg.get("partial_files", [])[:12],
        "definitions": bundle_defs,
        "callers": compact_callers,
        "callees": compact_callees,
        "related_types": related_types,
        "tests": matching_tests,
        "truncated": False,
        "bytes": 0,
        "ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }

    def measure(obj: dict[str, Any]) -> int:
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    if measure(packet) > max_bytes:
        packet["truncated"] = True

        if measure(packet) > max_bytes:
            packet["callers"] = [c for c in packet["callers"] if c["hop"] == 1][:8] or packet["callers"][:4]
            packet["callees"] = [c for c in packet["callees"] if c["hop"] == 1][:8] or packet["callees"][:4]

        for limit_n in (6, 4, 2, 1):
            if measure(packet) <= max_bytes:
                break
            packet["callers"] = packet["callers"][:limit_n]
            packet["callees"] = packet["callees"][:limit_n]
            packet["related_types"] = packet["related_types"][:limit_n]
            packet["tests"] = packet["tests"][:limit_n]
            packet["partial_files"] = packet["partial_files"][:limit_n]

        if measure(packet) > max_bytes:
            for lst_key in ("callers", "callees", "related_types", "tests"):
                for item in packet[lst_key]:
                    if "signature" in item and len(item["signature"]) > 96:
                        item["signature"] = item["signature"][:93] + "..."

        if measure(packet) > max_bytes and len(packet["definitions"]) > 1:
            packet["definitions"] = packet["definitions"][:1]

        while measure(packet) > max_bytes and packet["definitions"]:
            body = packet["definitions"][0].get("body", "")
            if not body:
                break
            over = measure(packet) - max_bytes
            new_len = max(0, len(body) - max(over + 64, len(body) // 3))
            if new_len <= 32:
                packet["definitions"][0]["body"] = ""
            else:
                trimmed_body = body[:new_len].rsplit("\n", 1)[0]
                packet["definitions"][0]["body"] = trimmed_body + "\n// ... (truncated)"

        for drop_key in ("partial_files", "related_types", "callees", "callers", "tests"):
            if measure(packet) <= max_bytes:
                break
            packet[drop_key] = []

    packet["ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    packet["bytes"] = 999999
    packet["bytes"] = measure(packet)
    packet["bytes"] = measure(packet)
    if measure(packet) > max_bytes and packet["definitions"] and packet["definitions"][0].get("body"):
        packet["truncated"] = True
        b = packet["definitions"][0]["body"]
        over = measure(packet) - max_bytes + 16
        packet["definitions"][0]["body"] = b[: max(0, len(b) - over)]
        packet["bytes"] = measure(packet)

    if len(snap["files"]) >= _REPO_CACHE_MIN_FILES:
        ref_rels: set[str] = set()
        for d in packet.get("definitions", []):
            ref_rels.add(d["file"])
        for c in packet.get("callers", []):
            ref_rels.add(c["file"])
        for c in packet.get("callees", []):
            ref_rels.add(c["file"])
        for rt in packet.get("related_types", []):
            ref_rels.add(rt["file"])
        for t in packet.get("tests", []):
            ref_rels.add(t["file"])
        stat_fp: list[tuple[Path, int, int]] = []
        for rel in sorted(ref_rels):
            rp = repo_path / rel
            try:
                st = rp.stat()
                stat_fp.append((rp, int(st.st_mtime_ns), int(st.st_size)))
            except OSError:
                continue
        with _BUNDLE_CACHE_LOCK:
            _BUNDLE_CACHE[bkey] = (snap["ts"], stat_fp, json.loads(json.dumps(packet, ensure_ascii=False)))
            _BUNDLE_CACHE.move_to_end(bkey)
            while len(_BUNDLE_CACHE) > _BUNDLE_CACHE_MAX:
                _BUNDLE_CACHE.popitem(last=False)

    return packet


def _is_test_csproj(csproj: Path) -> tuple[bool, list[Path]]:
    refs: list[Path] = []
    name_low = csproj.name.lower()
    is_test = any(tok in name_low for tok in (".tests.", ".test.", "tests.csproj", "test.csproj", ".specs."))
    try:
        raw = csproj.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return is_test, refs

    if not is_test:
        low = raw.lower()
        if any(
            marker in low
            for marker in (
                "microsoft.net.test.sdk",
                "xunit",
                "nunit",
                "mstest.testframework",
                "<istestproject>true</istestproject>",
            )
        ):
            is_test = True

    try:
        root = ET.fromstring(raw)
        for elem in root.iter():
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "ProjectReference":
                inc = elem.attrib.get("Include", "").strip()
                if inc:
                    ref_path = (csproj.parent / inc.replace("\\", "/")).resolve()
                    refs.append(ref_path)
    except ET.ParseError:
        for m in re.finditer(r'ProjectReference\s+Include="([^"]+)"', raw):
            refs.append((csproj.parent / m.group(1).replace("\\", "/")).resolve())

    return is_test, refs


def _find_owning_csproj(file_path: Path, repo_root: Path) -> Path | None:
    cur = file_path.parent if file_path.suffix else file_path
    root_res = repo_root.resolve()
    while True:
        try:
            csprojs = list(cur.glob("*.csproj"))
        except OSError:
            csprojs = []
        if csprojs:
            return csprojs[0].resolve()
        if cur.resolve() == root_res or cur.parent == cur:
            break
        cur = cur.parent
    return None


def impacted_dotnet_tests(repo: str | Path, changed_files: list[str]) -> dict[str, Any]:
    """Locate .csproj test projects and derive targeted `dotnet test --no-restore --filter ...` commands."""
    t0 = time.perf_counter()
    repo_path = Path(repo).resolve()

    all_csprojs: list[Path] = []
    stack = [str(repo_path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in _SKIP_DIRS:
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".csproj"):
                            all_csprojs.append(Path(entry.path).resolve())
                    except OSError:
                        continue
        except OSError:
            continue

    test_projects: list[tuple[Path, list[Path]]] = []
    for cp in sorted(all_csprojs):
        is_t, refs = _is_test_csproj(cp)
        if is_t:
            test_projects.append((cp, refs))

    changed_abs: list[Path] = []
    for cf in changed_files or []:
        p = Path(cf)
        if not p.is_absolute():
            p = repo_path / p
        changed_abs.append(p.resolve())

    owning_projects: set[Path] = set()
    primary_stem_types: list[str] = []
    changed_type_names: list[str] = []
    changed_method_names: list[str] = []
    direct_test_classes: list[str] = []

    for cf in changed_abs:
        owner = _find_owning_csproj(cf, repo_path)
        if owner is not None:
            owning_projects.add(owner)
        stem_base = cf.stem.split(".")[0]

        if cf.suffix.lower() == ".cs" and cf.exists():
            out = outline_file(cf)
            if out.get("ok"):
                is_tf = _is_test_file(cf)
                for sym in out["symbols"]:
                    if sym["kind"] in ("class", "partial class", "struct", "record", "interface"):
                        if is_tf:
                            if sym["name"] not in direct_test_classes:
                                direct_test_classes.append(sym["name"])
                        else:
                            if sym["name"].lower() == stem_base.lower() and sym["name"] not in primary_stem_types:
                                primary_stem_types.append(sym["name"])
                            elif sym["name"] not in changed_type_names:
                                changed_type_names.append(sym["name"])
                    elif sym["kind"] == "method" and not is_tf:
                        if "public " in sym["signature"] and sym["name"] not in changed_method_names:
                            changed_method_names.append(sym["name"])
        elif stem_base and stem_base not in primary_stem_types:
            primary_stem_types.append(stem_base)

    selected_tests: list[Path] = []
    for tp, refs in test_projects:
        if tp in owning_projects:
            selected_tests.append(tp)
            continue
        if any(r in owning_projects for r in refs):
            selected_tests.append(tp)
            continue
        tp_stem = tp.stem.lower()
        for op in owning_projects:
            if tp_stem.startswith(op.stem.lower()):
                selected_tests.append(tp)
                break

    if not selected_tests and test_projects:
        selected_tests = [tp for tp, _ in test_projects]

    filter_symbols = list(
        dict.fromkeys(direct_test_classes + primary_stem_types + changed_type_names[:8] + changed_method_names[:4])
    )
    impacted_projects: list[dict[str, Any]] = []
    commands: list[str] = []

    for tp in selected_tests:
        rel_tp = _rel_posix(tp, repo_path)
        tp_dir = tp.parent
        matched_tests: list[str] = []
        matched_syms: list[str] = []

        if filter_symbols:
            sym_bytes_list = [(s, s.encode("utf-8")) for s in filter_symbols[:12]]
            for tf in sorted(tp_dir.rglob("*.cs")):
                if any(part in _SKIP_DIRS for part in tf.parts):
                    continue
                try:
                    raw = tf.read_bytes()
                except OSError:
                    continue
                hit_syms = [s for s, sb in sym_bytes_list if sb in raw]
                if hit_syms:
                    out = outline_file(tf)
                    for sym in out.get("symbols", []):
                        if sym["kind"] in ("class", "partial class") and sym["name"] not in matched_tests:
                            matched_tests.append(sym["name"])
                    for s in hit_syms:
                        if s not in matched_syms:
                            matched_syms.append(s)

        filter_terms: list[str] = []
        if direct_test_classes:
            filter_terms = direct_test_classes[:6]
        elif matched_tests:
            filter_terms = matched_tests[:6]
        elif filter_symbols:
            filter_terms = filter_symbols[:6]

        filter_expr = "|".join(f"FullyQualifiedName~{t}" for t in filter_terms)
        if filter_expr:
            argv = ["dotnet", "test", rel_tp, "--no-restore", "--filter", filter_expr]
            cmd = f'dotnet test "{rel_tp}" --no-restore --filter "{filter_expr}"'
        else:
            argv = ["dotnet", "test", rel_tp, "--no-restore"]
            cmd = f'dotnet test "{rel_tp}" --no-restore'

        impacted_projects.append(
            {
                "project": rel_tp,
                "abs_path": str(tp),
                "filter": filter_expr,
                "command": cmd,
                "argv": argv,
                "matched_symbols": matched_syms or filter_terms,
                "matched_tests": matched_tests,
            }
        )
        commands.append(cmd)

    # Sort impacted projects so those with actual matched_tests come first
    impacted_projects.sort(key=lambda p: (0 if p["matched_tests"] else 1, p["project"]))
    commands = [p["command"] for p in impacted_projects]

    return {
        "ok": True,
        "repo": str(repo_path),
        "changed_files": [str(cf) for cf in (changed_files or [])],
        "test_projects": [_rel_posix(tp, repo_path) for tp, _ in test_projects],
        "impacted_projects": impacted_projects,
        "commands": commands,
        "symbols": filter_symbols,
        "ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }
