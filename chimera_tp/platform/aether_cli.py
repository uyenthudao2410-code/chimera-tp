"""User-invoked Aether tools. Each command acts only on its selected inputs."""

import argparse
import json
from pathlib import Path


def _new_file(path, data):
    with path.open("xb") as out:
        out.write(data)
    return {"output": str(path), "bytes": len(data)}


def _revision(a):
    from .file_revisions import FileRevisions
    repo = FileRevisions(a.state / "revisions.sqlite")
    if a.action == "capture":
        return repo.capture(a.file)
    if a.action == "history":
        return repo.history(a.file)
    if a.action == "watch":
        return repo.watch(a.file, a.seconds)
    if a.action == "warm":
        return repo.prewarm(a.file, a.budget)
    if a.action == "export":
        return repo.export(a.id, a.output, a.base, force_delta=a.force_delta)
    if a.action == "receive":
        return repo.receive(a.file)
    return repo.restore(a.id, a.output)


def _workspace(a):
    from .agent_workspace import open_workspace, read_workspace, workspace_manifest
    if a.action == "save":
        data = workspace_manifest(a.file, a.url, a.terminal)
        return _new_file(a.manifest, json.dumps(data, ensure_ascii=False, indent=2).encode())
    result = read_workspace(a.manifest)
    if a.apply:
        open_workspace(result)
    return {"opened": a.apply, "workspace": result}


def _capsule(a):
    import sqlite3
    import zipfile

    from . import workspace_capsule
    from .file_revisions import FileRevisions

    try:
        if a.action == "verify":
            result = workspace_capsule.verify(a.archive, a.id, a.directory)
            return {**result, "exit_code": 0 if result["ok"] else 1}
        store = FileRevisions(a.state / "revisions.sqlite")
        if a.action == "capture":
            return workspace_capsule.capture(store, a.root, a.graph, a.archive)
        return workspace_capsule.restore(store, a.archive, a.id, a.directory)
    except (ValueError, OSError, KeyError, sqlite3.DatabaseError, zipfile.BadZipFile) as error:
        return {"ok": False, "error": str(error), "exit_code": 1}


def _lease(a):
    from .agent_workspace import run_leased
    cmd = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
    code = run_leased(a.repo, a.file, cmd, a.isolate_at)
    return {"exit_code": code}


def _reuse(a):
    from .result_reuse import ResultReuse
    cache = ResultReuse(a.state / "results.sqlite")
    context = json.loads(a.context.read_text(encoding="utf-8-sig"))
    if a.action == "put":
        return cache.put(context, a.question, a.file.read_bytes(), a.ttl)
    if a.action == "suggest":
        return {"questions": cache.suggest(context, a.question)}
    result = cache.get(context, a.question)
    return {"hit": False} if result is None else {"hit": True, **_new_file(a.output, result)}


def _frame(a):
    from . import frame_notes
    db = a.state / "frames.sqlite"
    if a.action == "record":
        return frame_notes.record(db, a.file, a.screen, a.ocr_peer)
    if a.action == "find":
        return frame_notes.search(db, a.query)
    return frame_notes.replay(db, a.id, a.output)


def _recall(a):
    from . import source_recall

    db = a.state / "recall.sqlite"
    try:
        if a.action == "save":
            return source_recall.save(db, file=a.file, url=a.url, text=a.text, context=a.context,
                                      locator=a.locator, page=a.page, line=a.line, scope=a.scope,
                                      quote_text=a.quote)
        if a.action == "find":
            return source_recall.find(db, a.query, scope=a.scope, limit=a.limit)
        if a.action == "show":
            return source_recall.show(db, a.id, scope=a.scope)
        from .recall_open import open_source
        return open_source(db, a.id, scope=a.scope)
    except (ValueError, OSError, LookupError) as exc:
        return {"error": str(exc), "exit_code": 2}


def _parcel(a):
    from . import clipboard_parcel as parcels
    if a.action == "key":
        parcels.create_key(a.key)
        return {"key_file": str(a.key)}
    if a.action == "get":
        payload = parcels.receive(a.peer, a.id, a.key.read_bytes())
        if a.format:
            payload = parcels.convert_table(payload, a.format)
        return _new_file(a.output, payload)
    payload = a.file.read_bytes() if a.file else parcels.read_clipboard_text()
    if a.action == "convert":
        return _new_file(a.output, parcels.convert_table(payload, a.format))
    return {"id": parcels.send(a.peer, payload, a.key.read_bytes(), a.ttl), "ttl_seconds": a.ttl}


def _admission(a):
    from .work_admission import plan, run_batch
    policy = json.loads(a.guard_policy.read_text(encoding="utf-8-sig")) if a.guard_policy else {}
    if not isinstance(policy, dict):
        raise ValueError("guard policy must be a JSON object")
    result = plan(a.state / "admission.sqlite", a.observe_seconds, policy=policy)
    if a.run or a.feature == "batch":
        result["job"] = run_batch(result, a.repo, a.remote_root, policy=policy)
    return result


def _colab(a):
    from .colab_on_peer import headless
    return headless(a.profile, a.peer_script, a.run)


def _bond(a):
    from ..hyper_wire import ImmortalMultiPathReceiver, ImmortalMultiPathSender
    import hashlib
    import random
    data = random.Random(27).randbytes(128 * 1024)
    rx = ImmortalMultiPathReceiver([("127.0.0.1", 0), ("127.0.0.1", 0)], gen_k=32).start()
    try:
        rep = ImmortalMultiPathSender(rx.addrs, gen_k=32, source_ips=a.source).send_stream(
            data, stream_id=27, chaos_kill_lane=0 if a.cut else None, chaos_kill_after_gens=1, timeout_s=12)
        received, _ = rx.wait_stream_stats(27, timeout_s=5)
        ok = received == data and rep.sha256_match
        return {"loopback_lanes": len(rx.addrs), "cut_lane": a.cut, "bytes": len(data), "match": ok,
                "sha256": hashlib.sha256(data).hexdigest(), "elapsed_ms": rep.elapsed_ms,
                "lane_tx": rep.lane_tx_counts, "reconnects": rep.reconnects, "exit_code": 0 if ok else 1}
    finally:
        rx.close()


def configure(parser):
    parser.add_argument("--state", type=Path, default=Path.home() / ".chimera" / "aether")
    groups = parser.add_subparsers(dest="feature", required=True)

    def group(name, handler, help):
        p = groups.add_parser(name, help=help)
        p.set_defaults(aether_handler=handler)
        return p

    rev = group("revision", _revision, "Capture or exchange content-defined file revisions")
    actions = rev.add_subparsers(dest="action", required=True)
    for name in ("capture", "history", "watch", "warm", "receive"):
        p = actions.add_parser(name)
        p.add_argument("file", type=Path)
        if name == "watch":
            p.add_argument("--seconds", type=int, default=300)
        if name == "warm":
            p.add_argument("--budget", type=int, default=8 * 1024 * 1024)
    for name in ("restore", "export"):
        p = actions.add_parser(name)
        p.add_argument("id")
        p.add_argument("output", type=Path)
        if name == "export":
            p.add_argument("--base", help="A revision the recipient already has")
            p.add_argument("--force-delta", action="store_true", help="Measure the delta even when a full ZIP is smaller")

    capsule = group("capsule", _capsule, "Exchange a hash-pinned workspace with its relative dependencies")
    actions = capsule.add_subparsers(dest="action", required=True)
    save = actions.add_parser("capture", help="Package files from a hash-pinned dependency graph")
    save.add_argument("root", type=Path)
    save.add_argument("graph", type=Path)
    save.add_argument("archive", type=Path, help="New portable archive")
    for name in ("verify", "restore"):
        help_text = ("Check the archive's bytes and optionally the files in an existing directory"
                     if name == "verify" else "Restore all members into a new directory")
        operation = actions.add_parser(name, help=help_text)
        operation.add_argument("archive", type=Path)
        operation.add_argument("id", help="Capsule SHA-256 returned at capture")
        if name == "verify":
            operation.add_argument("directory", type=Path, nargs="?", help="Also check this existing directory")
        else:
            operation.add_argument("directory", type=Path, help="New destination directory")

    work = group("workspace", _workspace, "Save or reopen a selected set of desktop documents, URLs and terminals")
    actions = work.add_subparsers(dest="action", required=True)
    save = actions.add_parser("save")
    save.add_argument("manifest", type=Path)
    save.add_argument("--file", action="append", default=[])
    save.add_argument("--url", action="append", default=[])
    save.add_argument("--terminal", action="append", default=[])
    reopen = actions.add_parser("restore")
    reopen.add_argument("manifest", type=Path)
    reopen.add_argument("--apply", action="store_true", help="Open the entries on this desktop")

    lease = group("lease", _lease, "Hold cooperative file locks while an agent command runs")
    lease.add_argument("--repo", type=Path, default=Path.cwd())
    lease.add_argument("--file", action="append", required=True)
    lease.add_argument("--isolate-at", type=Path, help="New detached worktree for a conflict on a clean repository")
    lease.add_argument("argv", nargs=argparse.REMAINDER)

    reuse = group("reuse", _reuse, "Share verified results within a selected inference context")
    actions = reuse.add_subparsers(dest="action", required=True)
    for name in ("put", "get", "suggest"):
        p = actions.add_parser(name)
        p.add_argument("--context", required=True, type=Path)
        p.add_argument("--question", required=True)
        if name == "put":
            p.add_argument("file", type=Path)
            p.add_argument("--ttl", type=int, default=3600)
        if name == "get":
            p.add_argument("output", type=Path)

    frame = group("frame", _frame, "Encode one selected image on Quick Sync and search OCR")
    actions = frame.add_subparsers(dest="action", required=True)
    rec = actions.add_parser("record")
    source = rec.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--screen", action="store_true")
    rec.add_argument("--ocr-peer", action="store_true", help="Send only this image to svhome for OCR")
    actions.add_parser("find").add_argument("query")
    replay = actions.add_parser("replay")
    replay.add_argument("id")
    replay.add_argument("output", type=Path)

    recall = group("recall", _recall, "Save, find and reopen passages from selected local files or HTTPS pages")
    actions = recall.add_subparsers(dest="action", required=True)
    save = actions.add_parser("save", help="Save one source and its selected passage or note")
    source = save.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Local document selected for fingerprinting")
    source.add_argument("--url", help="Exact HTTPS URL, including any existing fragment")
    save.add_argument("--text", help="Selected passage or note; defaults to a selected local text line")
    save.add_argument("--quote", help="Exact words selected on an HTTPS page for a browser text fragment")
    save.add_argument("--context", default="", help="Additional context to keep with this passage")
    save.add_argument("--locator", default="", help="Section label, or a web anchor if the URL has no fragment")
    position = save.add_mutually_exclusive_group()
    position.add_argument("--page", type=int, help="One-based page (PDF links reopen at this page)")
    position.add_argument("--line", type=int, help="One-based source line")
    find = actions.add_parser("find", help="Search saved text and locators without opening sources")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=10)
    show = actions.add_parser("show", help="Show the passage and verify its selected local file")
    reopen = actions.add_parser("open", help="Verify and open this source in a viewer")
    for command in (show, reopen):
        command.add_argument("id")
    for command in (save, find, show, reopen):
        command.add_argument("--scope", default="default", help="Name of the local collection (default: default)")

    parcel = group("parcel", _parcel, "Send a selected payload or convert delimited clipboard data")
    actions = parcel.add_subparsers(dest="action", required=True)
    for name in ("key", "send", "get", "convert"):
        p = actions.add_parser(name)
        if name != "convert":
            p.add_argument("--key", type=Path, required=True)
        if name in ("send", "get"):
            p.add_argument("--peer", default="svhome")
        if name in ("send", "convert"):
            source = p.add_mutually_exclusive_group(required=True)
            source.add_argument("--file", type=Path)
            source.add_argument("--clipboard", action="store_true")
        if name == "get":
            p.add_argument("id")
        if name == "send":
            p.add_argument("--ttl", type=int, default=60)
        if name in ("get", "convert"):
            p.add_argument("output", type=Path)
            p.add_argument("--format", choices=("csv", "json", "xlsx", "markdown"), required=name == "convert")

    admission = groups.add_parser("admit", aliases=["batch"], help="Assess capacity; batch also runs syntax checks")
    admission.set_defaults(aether_handler=_admission)
    admission.add_argument("--repo", type=Path, default=Path.cwd(),
                           help="Local workspace to check. A peer job receives this working snapshot.")
    admission.add_argument("--remote-root", help="Check this existing svhome checkout instead of --repo")
    admission.add_argument("--observe-seconds", type=int, default=0)
    admission.add_argument("--guard-policy", type=Path, help="Receiver limits and loopback service health URLs as JSON")
    admission.add_argument("--run", action="store_true")
    colab = group("colab", _colab, "Inspect or run a selected job through svhome's Colab CLI")
    colab.add_argument("--profile", choices=("CPU", "CPU_HIGH_MEM", "T4", "L4"), default="CPU")
    colab.add_argument("--peer-script", default="")
    colab.add_argument("--run", action="store_true", help="Start a provider runtime using your account")
    bond = group("bond", _bond, "Measure a CHIMERA transfer over two independent loopback UDP sockets")
    bond.add_argument("--cut", action="store_true", help="Cut the first logical lane after one generation")
    bond.add_argument("--source", nargs=2, metavar=("IP_A", "IP_B"), help="Bind the two test lanes to local IPv4 addresses")


def execute(args):
    result = args.aether_handler(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result.get("exit_code", 0) if isinstance(result, dict) else 0
