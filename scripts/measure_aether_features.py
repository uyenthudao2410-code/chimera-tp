"""Measure the additional workstation proposals using only explicitly generated fixtures."""

import hashlib
import io
import json
import os
import random
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from chimera_tp.native import has_native
from chimera_tp.platform import clipboard_parcel, frame_notes
from chimera_tp.platform.file_revisions import FileRevisions
from chimera_tp.platform.result_reuse import ResultReuse


PEER_READER = """
import hashlib, io, json, sys, zipfile
chunks, revisions = {}, {}
for generation in range(2):
    size = int.from_bytes(sys.stdin.buffer.read(8),'big')
    assert 0 < size < 100 * 1024**2
    archive = sys.stdin.buffer.read(size)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        m = json.loads(z.read('revision.json'))
        parts = m['parts']
        if 'base' in m:
            previous = revisions[m['base']]
            parts = previous[:m['prefix']] + parts + previous[len(previous)-m['suffix']:]
        digest = hashlib.sha256()
        n = 0
        for cid in parts:
            if cid not in chunks:
                chunks[cid] = z.read(cid)
                assert hashlib.sha256(chunks[cid]).hexdigest() == cid
            digest.update(chunks[cid])
            n += len(chunks[cid])
        assert digest.hexdigest() == m['sha256'] and n == m['bytes']
        revisions[m['sha256']] = parts
        print(json.dumps({'revision':m['sha256'],'bytes':n}), flush=True)
"""


def peer_transfer(paths, identities):
    command = shlex.join(["python3", "-I", "-u", "-c", PEER_READER])
    times = []
    with subprocess.Popen(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                           "svhome", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as peer:
        try:
            for path, identity in zip(paths, identities):
                start = time.perf_counter()
                peer.stdin.write(path.stat().st_size.to_bytes(8, "big"))
                with path.open("rb") as f:
                    while chunk := f.read(65536):
                        peer.stdin.write(chunk)
                peer.stdin.flush()
                ack = json.loads(peer.stdout.readline())
                assert ack["revision"] == identity
                times.append(round((time.perf_counter() - start) * 1000, 2))
            peer.stdin.close()
            if peer.wait(timeout=15):
                raise RuntimeError(peer.stderr.read().decode(errors="replace")[-240:])
        finally:
            if peer.poll() is None:
                peer.kill()
    return times


def cad(root):
    drawing = root / "synthetic.dwg"
    rng = random.Random(2701)
    with drawing.open("wb") as f:
        for _ in range(80):
            f.write(rng.randbytes(1024 * 1024))
    store = FileRevisions(root / "local.sqlite")
    base = store.capture(drawing)
    with drawing.open("r+b") as f:
        f.seek(40 * 1024 * 1024 + 91)
        f.write(b"CAD-REVISION-B" * 32)
    current = store.capture(drawing)
    full, delta = root / "full.zip", root / "delta.zip"
    before = store.export(base["revision"], full)
    after = store.export(current["revision"], delta, base["revision"])
    other = FileRevisions(root / "receiver.sqlite")
    other.receive(full)
    other.receive(delta)
    restored = root / "restored.dwg"
    other.restore(current["revision"], restored)
    with restored.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == current["revision"]
    transport = peer_transfer([full, delta], [base["revision"], current["revision"]])
    return {"fixture_bytes": current["bytes"], "edited_bytes": len(b"CAD-REVISION-B") * 32,
            "native_fastcdc": has_native(), "full_archive_bytes": before["archive_bytes"],
            "delta_archive_bytes": after["archive_bytes"], "new_chunk_bytes": current["added_bytes"],
            "included_chunks": after["included_chunks"], "full_ack_ms": transport[0], "delta_ack_ms": transport[1],
            "local_restore_sha256": current["revision"], "peer_verified_both": True}


def journal(root):
    from PIL import Image, ImageDraw, ImageFont
    db, png, replay = root / "frames.sqlite", root / "selected.png", root / "replayed.png"
    image = Image.new("RGB", (1000, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/arial.ttf"), 52)
    draw.text((30, 60), "CHIMERA AETHER 7429", font=font, fill="black")
    image.save(png)
    start = time.perf_counter()
    note = frame_notes.record(db, png, ocr_peer=True)
    encode_ocr_ms = (time.perf_counter() - start) * 1000
    times = []
    for _ in range(15):
        start = time.perf_counter()
        found = frame_notes.search(db, "7429")
        times.append((time.perf_counter() - start) * 1000)
        assert len(found) == 1 and found[0]["id"] == note["id"]
    frame_notes.replay(db, note["id"], replay)
    with Image.open(replay) as decoded:
        assert decoded.size == image.size
    return {**note, "encode_plus_peer_ocr_ms": round(encode_ocr_ms, 2),
            "fts_median_ms_15": round(statistics.median(times), 3), "replay_size": list(image.size)}


def parcel(root):
    key = os.urandom(32)
    plain = b"name\tquantity\nAcer\t2\nMSI\t1"
    start = time.perf_counter()
    identity = clipboard_parcel.send("svhome", plain, key, 60)
    raw = clipboard_parcel.receive("svhome", identity, key)
    roundtrip = round((time.perf_counter() - start) * 1000, 2)
    assert raw == plain
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(clipboard_parcel.convert_table(raw, "xlsx")), read_only=True)
    try:
        assert list(book.active.values)[-1] == ("MSI", "1")
    finally:
        book.close()
    return {"roundtrip_ms": roundtrip, "bytes": len(raw), "equal": raw == plain, "ttl_seconds": 60,
            "formats": {kind: len(clipboard_parcel.convert_table(raw, kind))
                       for kind in ("csv", "json", "xlsx", "markdown")}}


def reuse(root):
    cache = ResultReuse(root / "results.sqlite")
    context = dict(workspace="synthetic", principal="measure", provider="local", model="fixture",
                   revision="example-sha", parameters={"temperature": 0})
    question = "Result for module A"
    assert cache.get(context, question) is None
    cache.put(context, question, b"validated output")
    times = []
    for _ in range(30):
        start = time.perf_counter()
        assert cache.get(context, question) == b"validated output"
        times.append((time.perf_counter() - start) * 1000)
    assert cache.get({**context, "model": "other"}, question) is None
    assert cache.suggest(context, "module") == [question]
    return {"first_hits": 0, "repeat_hits": 30, "median_ms_30": round(statistics.median(times), 3),
            "cross_model_hits": 0}


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix="chimera-aether-fixture-") as root:
        for name, test in (("frame", journal), ("revisions", cad), ("parcel", parcel), ("reuse", reuse)):
            try:
                results[name] = test(Path(root))
            except Exception as exc:
                results[name] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(results))
    return int(any("error" in d for d in results.values()))


if __name__ == "__main__":
    sys.exit(main())
