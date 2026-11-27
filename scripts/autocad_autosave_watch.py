"""Retain versions of one explicitly selected AutoCAD autosave during a bounded Windows session."""

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

from autocad_autosave import FileRevisions, SourceBusy, held_reader, recover


class AutosaveVersions(FileRevisions):
    def capture(self, source):
        # FileRevisions.watch retries ordinary read errors, including sharing
        # violations. Its existing kernel directory notification observes
        # in-place writes and replace-on-save without polling the entire TEMP.
        try:
            with held_reader(source) as stream:
                if not re.fullmatch(rb"AC10[0-9]{2}", stream.read(6)):
                    raise OSError("partial_or_invalid_autosave_header")
                return super().capture(source)
        except SourceBusy as error:
            raise BlockingIOError(str(error)) from error


def selected_source(path, must_exist):
    source = path.absolute()
    if source.suffix.casefold() != ".sv$":
        raise ValueError("select_an_sv_dollar_autosave")
    if must_exist and source != source.resolve(strict=True):
        raise ValueError("select_a_regular_unlinked_autosave")
    return source


def run(args):
    if args.action == "watch":
        source = selected_source(args.source, True)
        if args.store.absolute() == source or args.store.suffix.casefold() in {".sv$", ".dwg", ".ac$"}:
            raise ValueError("use_a_dedicated_revision_database")
        if not 1 <= args.seconds <= 86400:
            raise ValueError("watch_duration_must_be_1_to_86400_seconds")
        versions = AutosaveVersions(args.store)
        observed = versions.watch(source, args.seconds)
        return {"ok": True, "selected_source": str(source), "requested_seconds": args.seconds,
                **observed, "versions": versions.history(source)}
    if not args.store.is_file():
        raise FileNotFoundError(args.store)
    versions = FileRevisions(args.store)
    if args.action == "history":
        source = selected_source(args.source, False)
        return {"ok": True, "selected_source": str(source), "versions": versions.history(source)}
    if not re.fullmatch("[a-f0-9]{64}", args.revision):
        raise ValueError("invalid_recorded_revision")
    with tempfile.TemporaryDirectory(prefix="chimera-autosave-replay-") as tmp:
        source = Path(tmp, "Recorded.sv$")
        restored = versions.restore(args.revision, source)
        if restored["revision"] != args.revision:
            raise ValueError("saved_revision_identity_mismatch")
        args.source, args.settle_ms = source, 0
        receipt = recover(args)
    if receipt["autosave_sha256"] != args.revision:
        raise ValueError("restored_autosave_identity_mismatch")
    return {"ok": True, "recorded_revision": args.revision, **receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    watch = actions.add_parser("watch", help="Watch one existing autosave for a finite number of seconds")
    history = actions.add_parser("history", help="List recorded versions even if the autosave is gone")
    restore = actions.add_parser("restore", help="Restore an explicitly selected version into a fresh directory")
    for action in (watch, history, restore):
        action.add_argument("--store", type=Path, required=True, help="Dedicated local revision database")
    for action in (watch, history):
        action.add_argument("--source", type=Path, required=True, help="Exact .sv$ path")
    watch.add_argument("--seconds", type=int, required=True)
    restore.add_argument("--revision", required=True)
    restore.add_argument("--output", type=Path, required=True)
    restore.add_argument("--base", type=Path)
    restore.add_argument("--base-id")
    restore.add_argument("--console", type=Path)
    try:
        args = parser.parse_args()
        print(json.dumps(run(args)))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({"ok": False, "reason": str(error)}))
        return os.EX_DATAERR if hasattr(os, "EX_DATAERR") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
