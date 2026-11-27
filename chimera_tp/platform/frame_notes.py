"""An opt-in frame journal. Each entry is a selected still image and searchable OCR."""

from __future__ import annotations

import hashlib
from importlib import metadata
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path


def _codec():
    for configured in (os.environ.get("CHIMERA_FFMPEG"), os.environ.get("IMAGEIO_FFMPEG_EXE"), "ffmpeg"):
        if configured:
            executable = shutil.which(configured)
            if executable:
                return executable
    # The optional imageio-ffmpeg distribution ships a standalone executable.
    # Only its binary asset is used. FFmpeg on PATH is sufficient for the base install.
    try:
        package = metadata.distribution("imageio-ffmpeg")
    except metadata.PackageNotFoundError:
        package = None
    if package:
        for entry in package.files or ():
            if (entry.parts[:2] == ("imageio_ffmpeg", "binaries")
                    and entry.name.startswith("ffmpeg-")
                    and (os.name != "nt" or entry.suffix.lower() == ".exe")):
                executable = package.locate_file(entry)
                if executable.is_file() and os.access(executable, os.X_OK):
                    return os.fspath(executable)
    raise RuntimeError("install FFmpeg with hevc_qsv or set CHIMERA_FFMPEG to its executable")


def _run(command, data, timeout=35):
    proc = subprocess.run(
        command, input=data, capture_output=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-500:])
    return proc.stdout


def _local_ocr():
    candidates = [os.environ.get("CHIMERA_TESSERACT"), "tesseract"]
    if os.name == "nt":
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(key):
                candidates.append(str(Path(os.environ[key], "Tesseract-OCR", "tesseract.exe")))
    for command in candidates:
        if command and (resolved := shutil.which(command)):
            return resolved
    raise RuntimeError("install Tesseract, set CHIMERA_TESSERACT, or explicitly choose peer OCR")


def _png(path, screen):
    opts = [_codec(), "-v", "error", "-nostdin"]
    if screen:
        if os.name == "nt":
            input_args = ["-f", "gdigrab", "-framerate", "1", "-draw_mouse", "0", "-i", "desktop"]
        else:
            display = os.environ.get("DISPLAY")
            if not display:
                raise RuntimeError("screen capture requires an interactive X11 display")
            input_args = ["-f", "x11grab", "-framerate", "1", "-draw_mouse", "0", "-i", display]
        data = None
    else:
        if path is None:
            raise ValueError("select one image or explicitly request a screenshot")
        data = Path(path).read_bytes()
        input_args = ["-protocol_whitelist", "pipe", "-f", "image2pipe", "-i", "pipe:0"]
    return _run([*opts, *input_args, "-frames:v", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1"], data)


def record(database: Path, path: Path | None, screen=False, ocr_peer=False):
    raw = _png(path, screen)
    codec = _codec()
    video = _run([codec, "-v", "error", "-f", "image2pipe", "-i", "pipe:0", "-frames:v", "1",
                  "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=nv12", "-c:v", "hevc_qsv",
                  "-global_quality", "20", "-f", "hevc", "pipe:1"], raw)
    if not video:
        raise RuntimeError("empty HEVC output")
    if ocr_peer:
        ocr = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "svhome",
               "tesseract stdin stdout -l eng+vie"]
    else:
        ocr = [_local_ocr(), "stdin", "stdout", "-l", "eng+vie"]
    text = _run(ocr, raw).decode("utf-8", "replace").strip()
    identity = hashlib.sha256(raw).hexdigest()
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS frames (id TEXT UNIQUE, utc TEXT, video BLOB NOT NULL)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS ocr USING fts5(id UNINDEXED, text)")
        db.execute("BEGIN IMMEDIATE")
        inserted = db.execute("INSERT OR IGNORE INTO frames VALUES(?,CURRENT_TIMESTAMP,?)", (identity, video))
        if inserted.rowcount:
            db.execute("INSERT INTO ocr VALUES(?,?)", (identity, text))
    return {"id": identity, "encoder": "hevc_qsv", "hevc_bytes": len(video), "ocr_chars": len(text)}


def _reader(database):
    return sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)


def search(database, query):
    with closing(_reader(database)) as db:
        match = '"' + query.replace('"', '""') + '"'
        rows = db.execute("SELECT id,snippet(ocr,1,'[',']','...',18) FROM ocr WHERE ocr MATCH ? LIMIT 25", (match,))
        return [{"id": i, "match": text} for i, text in rows]


def replay(database, identity, output: Path):
    with closing(_reader(database)) as db:
        row = db.execute("SELECT video FROM frames WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise ValueError("frame missing")
    png = _run([_codec(), "-v", "error", "-f", "hevc", "-i", "pipe:0", "-frames:v", "1",
                "-f", "image2pipe", "-c:v", "png", "pipe:1"], row[0])
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("frame did not decode")
    with output.open("xb") as stream:
        stream.write(png)
    return {"output": os.fspath(output), "decoded_png_bytes": len(png)}
