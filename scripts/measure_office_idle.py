"""Run a cold office print transaction in a disposable archive and queue."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch
from uuid import uuid4

import psutil
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from examples.office_print_on_demand import dispatcher_pool


def fixture(path):
    canvas = Canvas(str(path), pagesize=A4, invariant=1)
    for n in range(1, 5):
        canvas.setFont("Helvetica", 20)
        canvas.drawString(60, 730, f"Office raster test sheet {n}")
        canvas.line(60, 700, 460, 630 - n * 20)
        canvas.showPage()
    canvas.save()


def gdi_file_job(queue, output, source, plan, state, archive, replica):
    """Measure the existing GDI transport separately from the software PCL route."""
    import win32print
    import office_service
    import office_store
    import office_transport
    from office_fleet import Printer, Timing, RICOH_DRIVER

    handle = win32print.OpenPrinter(queue)
    try:
        props = win32print.GetPrinter(handle, 2)
        if props["pPortName"] != "FILE:" or props["pServerName"] or props["pShareName"] or output.exists():
            raise ValueError("expected a private local FILE: queue and a new output file")
    finally:
        win32print.ClosePrinter(handle)
    driver = props["pDriverName"]
    if driver not in {RICOH_DRIVER, "HP LaserJet P205X series PCL6 Class Driver"}:
        raise ValueError("expected the office application's PCL driver on the private FILE: queue")
    device = Printer("gdi-test", "isolated GDI", queue, "FILE:", driver, True, True, True, 0)
    receipt = {"port": "FILE:", "driver": driver}
    native = office_transport._library()

    class ObservedGDI:
        def __getattr__(self, name):
            return getattr(native, name)

        def StartDocW(self, *args):
            spool = native.StartDocW(*args)
            if spool > 0:
                receipt.update(spool_id=spool, request_to_spooler_ms=round((time.perf_counter() - start) * 1000, 2))
            return spool

    def deliver(printer, path, digest, sizes, duplex, title, begin):
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("archive digest changed")
        return office_transport.gdi_copy(printer, data, sizes, duplex, title, begin, output=output)

    start = time.perf_counter()
    office_store.submit(source, plan, "off", {device.key: (1, 0)}, archive, state, replica,
                        token="file-gdi")
    row = office_store.claim(device.key, state)
    if not row:
        raise RuntimeError("isolated GDI print job not claimed")
    with patch.object(office_transport, "_library", return_value=ObservedGDI()):
        office_service.deliver(row, device, Timing(60, 0), state, replica, deliver)
    with office_store.session(state) as db:
        sent = db.execute("SELECT state,spool,reason FROM sets WHERE job='file-gdi'").fetchone()
    if not receipt.get("spool_id") or sent["state"] != "sent" or sent["spool"] != receipt["spool_id"]:
        raise RuntimeError(f"Windows did not acknowledge the fixture job: {dict(sent)}")
    until = time.monotonic() + 40
    while time.monotonic() < until:
        try:
            data = output.read_bytes()
            if len(data) > 1024 and b"PCL" in data[:5000].upper() and b"\x1b%-12345X" in data[-1000:]:
                break
        except OSError:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("spooler supplied a job ID but the driver file is incomplete")
    return {**receipt, "driver_file_bytes": len(data), "driver_file_sha256": hashlib.sha256(data).hexdigest(),
            "request_to_complete_driver_file_ms": round((time.perf_counter() - start) * 1000, 2)}


def raster_children(parent):
    children = []
    for proc in parent.children():
        try:
            if proc.name().lower() in {"python.exe", "pythonw.exe"} and "--multiprocessing-fork" in proc.cmdline():
                children.append(proc)
        except psutil.NoSuchProcess:
            continue
    return children


def measure(app_dir, file_queue, idle_seconds):
    report = {"sink": "local_pcl_file", "physical_printer_jobs": 0, "windows_gdi": None}
    own = psutil.Process()
    with tempfile.TemporaryDirectory(prefix="chimera-office-queue-") as raw:
        root = Path(raw)
        source, output = root / "test.pdf", root / "output.prn"
        state, archive, replica = root / "queue", root / "archive", root / "replica"
        fixture(source)
        with dispatcher_pool(app_dir, workers=2, idle_seconds=idle_seconds) as pool:
            import office_pdl as pdl
            import office_service as service
            import office_store as store
            from office_fleet import Printer, Timing
            from pdf_preflight import inspect_pdf

            # Keep wake notifications within the disposable queue, even when the
            # workstation's regular dispatcher is running.
            wake = store.signal_wake
            event = "Local\\ChimeraOfficeTest-" + uuid4().hex
            store.signal_wake = lambda: wake(event)
            try:
                plan = inspect_pdf(source)
                device = Printer("fixture", "private file", file_queue or "", "FILE:", "",
                                 True, True, True, 0)
                assignment = {device.key: (1, 0)}
                barrier = threading.Barrier(2)

                def submit_once():
                    barrier.wait(timeout=10)
                    return store.submit(source, plan, "off", assignment, archive, state, replica,
                                        token="same-click")

                # Exclude schema initialization and file fixture construction from the click.
                with store.session(state):
                    pass
                pdl.warmup_pool()
                if pool.ready() or raster_children(own):
                    raise RuntimeError("standby dispatcher already has a raster process")
                start = time.perf_counter()

                def ms():
                    return round((time.perf_counter() - start) * 1000, 2)

                with ThreadPoolExecutor(max_workers=2) as producers:
                    submitted = list(producers.map(lambda _: submit_once(), range(2)))
                if submitted != ["same-click", "same-click"]:
                    raise RuntimeError("submitters received different transaction identities")
                row = store.claim(device.key, state)
                if row is None or store.claim(device.key, state) is not None:
                    raise RuntimeError("queue did not give exclusive ownership of one copy")

                def transport(printer, path, digest, sizes, duplex, title, begin):
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise RuntimeError("archive and queue digest differ")
                    pieces = []
                    for chunk in pdl.compile_pcl_stream(data, tuple(sizes), title, duplex, dpi=96):
                        if len(pieces) == 1:
                            report["request_to_first_pcl_page_ms"] = ms()
                            children = raster_children(own)
                            report["raster_children_seen"] = len(children)
                            report["raster_private_mib"] = round(sum(
                                proc.memory_info().private for proc in children) / 2**20, 2)
                        pieces.append(chunk)
                    payload = b"".join(pieces)
                    report["pcl_sha256"] = hashlib.sha256(payload).hexdigest()
                    report["pcl_bytes"] = len(payload)
                    begin()
                    with output.open("xb") as sink:
                        sink.write(payload)
                    return None

                service.deliver(row, device, Timing(60, 0), state, replica, transport)
                with store.session(state) as db:
                    rows = db.execute("SELECT state,spool,reason FROM sets").fetchall()
                if len(rows) != 1 or rows[0]["state"] != "sent":
                    raise RuntimeError(f"queue completion failed: {[dict(item) for item in rows]}")
                report["request_to_queue_receipt_ms"] = ms()
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if hashlib.sha256(output.read_bytes()).hexdigest() == report["pcl_sha256"]:
                            break
                    except OSError:
                        pass
                    time.sleep(0.05)
                else:
                    size = output.stat().st_size if output.exists() else None
                    raise RuntimeError(f"expected {report['pcl_bytes']} exact bytes at file sink, got {size}")
                report.update(concurrent_submits=len(submitted), queued_copies=len(rows),
                              sink_verified=True)
                # Simulate a second job interrupted after crossing the send boundary.
                store.submit(source, plan, "off", assignment, archive, state, replica,
                             token="interrupted", again=True)
                second = store.claim(device.key, state, now=time.time() + 120)
                store.starting(second["job"], second["num"], state)
                store.recover(state)
                with store.session(state) as db:
                    interrupted = db.execute("SELECT state FROM sets WHERE job='interrupted'").fetchone()[0]
                if interrupted != "uncertain" or store.claim(device.key, state, now=time.time() + 180):
                    raise RuntimeError("interrupted send was replayed without reconciliation")
                report["interrupted_send_state"] = interrupted
                deadline = time.monotonic() + idle_seconds + 20
                while (pool.ready() or raster_children(own)) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if pool.ready() or raster_children(own):
                    raise RuntimeError("raster processes did not drain")
                report["children_after_idle"] = 0
                if file_queue:
                    report["windows_gdi"] = gdi_file_job(file_queue, root / "driver.prn", source,
                                                         plan, state, archive, replica)
            finally:
                store.signal_wake = wake
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--file-queue", help="optional existing private local Windows FILE: queue")
    parser.add_argument("--idle-seconds", type=float, default=1)
    args = parser.parse_args()
    print(json.dumps(measure(args.app_dir, args.file_queue, args.idle_seconds)))


if __name__ == "__main__":
    main()
