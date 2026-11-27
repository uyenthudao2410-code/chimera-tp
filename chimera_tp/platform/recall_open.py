"""Dispatch one verified source only after an explicit 'recall open' request."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

from ..code_search import TEXT_EXTENSIONS
from .source_recall import show


def _code_editor():
    command = shutil.which("code")
    if not command:
        return None
    # Launch the Windows executable directly. A source filename must never enter cmd.exe.
    if os.name == "nt" and Path(command).suffix.lower() != ".exe":
        binary = Path(command).resolve().parent.parent / "Code.exe"
        return str(binary) if binary.is_file() else None
    return command


def _open_document(path):
    if os.name == "nt":
        os.startfile(str(path), "open")
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([command, str(path)])


def _dispatch(record):
    target = record["target"]
    if record["kind"] == "https" or target.startswith("file:"):
        if not webbrowser.open_new_tab(target):
            raise OSError("the desktop browser did not accept the selected URL")
        return "browser"
    path = Path(target)
    if record["line"] or path.suffix.lower() in TEXT_EXTENSIONS:
        if editor := _code_editor():
            command = ([editor, "--goto", f"{path}:{record['line']}:1"]
                       if record["line"] else [editor, str(path)])
            subprocess.Popen(command)
            return "editor_line" if record["line"] else "editor"
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", str(path)])
            return "editor_manual_position" if record["line"] else "editor"
        if path.suffix.lower() not in {".txt", ".md", ".log"}:
            raise ValueError("install the VS Code command to open this source as text")
    elif path.suffix.lower() not in {
        ".dwg", ".dxf", ".pdf", ".csv", ".xlsx", ".docx", ".pptx", ".odt", ".ods",
        ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
    }:
        raise ValueError("desktop opening supports document formats and text sources only")
    _open_document(path)
    return "document_manual_position" if any(record[k] for k in ("locator", "page", "line")) else "document"


def open_source(database, identity, *, scope="default"):
    result = show(database, identity, scope=scope)
    if result["continuity"] not in {"verified", "unverified_https"}:
        return {**result, "opened": False, "exit_code": 2}
    # “Opened” records acceptance by the OS/browser, not an acknowledgement from a rendered tab.
    return {**result, "viewer": _dispatch(result), "opened": True}
