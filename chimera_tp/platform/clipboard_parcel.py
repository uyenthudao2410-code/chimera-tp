"""Explicit encrypted clipboard/file transfer. The relay stores only sealed bytes."""

from __future__ import annotations

import os
import re
import shlex
import struct
import subprocess
import time
from pathlib import Path

_HEADER = struct.Struct(">4sQ12s")
_MAX = 8 * 1024 * 1024


def create_key(path: Path):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(os.urandom(32))


def seal(payload: bytes, key: bytes, ttl: int) -> bytes:
    from ._parcel_gcm import transform

    if len(key) != 32 or not 1 <= ttl <= 3600 or len(payload) > _MAX:
        raise ValueError("expected 32-byte key, 1..3600 seconds and up to 8 MiB")
    nonce = os.urandom(12)
    header = _HEADER.pack(b"CHP1", int(time.time()) + ttl, nonce)
    return header + transform(key, nonce, header, payload, encrypt=True)


def unseal(parcel: bytes, key: bytes, now=None) -> bytes:
    from ._parcel_gcm import transform

    if len(key) != 32 or not _HEADER.size + 16 <= len(parcel) <= _HEADER.size + 16 + _MAX:
        raise ValueError("invalid parcel size or key")
    header = parcel[:_HEADER.size]
    magic, expiry, nonce = _HEADER.unpack(header)
    if magic != b"CHP1":
        raise ValueError("unknown parcel format")
    clear = transform(key, nonce, header, parcel[_HEADER.size:], encrypt=False)
    if (time.time() if now is None else now) >= expiry:
        raise ValueError("parcel expired")
    return clear


_RELAY = """
import os, re, struct, sys, tempfile, time, uuid
from pathlib import Path
root = Path(os.environ.get('XDG_RUNTIME_DIR', str(Path.home() / '.cache'))) / 'chimera-parcels'
root.mkdir(mode=0o700, parents=True, exist_ok=True)
now = time.time()
for item in root.glob('*.sealed'):
    try:
        if item.stat().st_mtime <= now:
            item.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
action = sys.argv[1]
if action == 'put':
    data = sys.stdin.buffer.read(8 * 1024**2 + 41)
    if not 40 <= len(data) <= 8 * 1024**2 + 40:
        raise ValueError('size')
    magic, expiry = struct.unpack('>4sQ', data[:12])
    if magic != b'CHP1' or not now < expiry <= now + 3601:
        raise ValueError('expiry')
    identity = uuid.uuid4().hex
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
        tmp.write(data)
    try:
        os.utime(tmp.name, (now, expiry))
        os.link(tmp.name, root / (identity + '.sealed'))
    finally:
        os.unlink(tmp.name)
    print(identity)
elif action == 'get':
    identity = sys.argv[2]
    if not re.fullmatch('[a-f0-9]{32}', identity):
        raise ValueError('invalid id')
    sys.stdout.buffer.write((root / (identity + '.sealed')).read_bytes())
"""


def _ssh(peer, action, identity=None, payload=None):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", peer):
        raise ValueError("provide a configured SSH host alias")
    args = ["python3", "-I", "-c", _RELAY, action]
    if identity:
        args.append(identity)
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", peer, shlex.join(args)],
        input=payload or b"", capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-400:])
    return result.stdout


def send(peer, payload, key, ttl):
    identity = _ssh(peer, "put", payload=seal(payload, key, ttl)).decode("ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("invalid relay receipt")
    return identity


def receive(peer, identity, key):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("invalid parcel identity")
    return unseal(_ssh(peer, "get", identity), key)


def read_clipboard_text():
    if os.name != "nt":
        raise ValueError("text clipboard input currently requires Windows")
    script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);[Console]::Write((Get-Clipboard -Raw))"
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout


def convert_table(payload, output_format):
    import csv
    import io
    import json

    text = payload.decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters="\t,;")
    except csv.Error as exc:
        raise ValueError("provide delimited columns; OCR text without column boundaries needs review") from exc
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    if not rows or len(rows[0]) < 2 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("ambiguous table shape")
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False).encode()
    # Spreadsheet exports treat selected text as data even if a cell starts with a formula.
    if output_format == "xlsx":
        from ._table_xlsx import text_workbook
        return text_workbook(rows)
    if output_format == "csv":
        csv_text = io.StringIO(newline="")
        writer = csv.writer(csv_text)
        for row in rows:
            writer.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
        return csv_text.getvalue().encode("utf-8-sig")
    if output_format == "markdown":
        def markdown_row(row):
            return "| " + " | ".join(v.replace("\\", "\\\\").replace("|", r"\|").replace("\n", "<br>")
                                     for v in row) + " |"
        return "\n".join(map(markdown_row, [rows[0], ["---"] * len(rows[0]), *rows[1:]])).encode()
    raise ValueError("unsupported format")
