#!/usr/bin/env python3
"""
check_guard_drift.py -- EARLY-WARNING for guarded-tool / manifest drift.

Why this exists
---------------
Editing a guarded tool (any key in tools/tools_manifest.json) without
regenerating the manifest does NOT fail at edit time -- it surfaces LATE, at
run_pipeline.py startup, where verify_tools_timestamp_guard hard-blocks with
"Tool content hash mismatch ...". On 2026-06-24 that opaque late hard-fail bit
a real pipeline run three times in one session. The pre-commit lint
(lint_guard_manifest_sync) only fires at COMMIT; the gap is the window BETWEEN
editing a guarded file and committing, when running the pipeline first yields
the late block.

This tool moves the signal EARLIER: one command lists every guarded tool whose
on-disk (working-tree) canonical hash != the hash recorded in the manifest, so
you can regen before the pipeline (or CI) ever rejects it. It is the working-
tree twin of the commit-time lint and the run-time guard, and it is what the
PostToolUse edit-time hook (.claude/hooks/post_write_reminder.py) calls to warn
the moment a guarded file is edited.

ADVISORY ONLY -- an early warning, NOT a gate. The authoritative checks remain
run_pipeline.verify_tools_timestamp_guard (runtime) and lint_guard_manifest_sync
(pre-commit). For that reason this file is itself deliberately NOT in the
Critical Guard Set (it never runs inside a pipeline, so no chicken-and-egg).

Hashing
-------
A local LF-normalized sha256 (CRLF->LF before hashing) -- byte-for-byte
identical to tools.verify_engine_integrity.canonical_sha256, but reimplemented
here so the module stays dependency-light: importing verify_engine_integrity
drags pandas, which is far too heavy for the per-edit PostToolUse hook that
calls find_drift(). Pinned to the authoritative hasher by
tests/test_check_guard_drift.py::test_canonical_hash_matches_authoritative --
if the canonical definition ever diverges there, that test fails and forces
this to follow (same discipline as lint_guard_manifest_sync).

Iterating the manifest's recorded file_hashes (NOT generate_guard_manifest's
GUARD_FILES) is deliberate: the manifest IS the list of what the runtime guard
checks, and reading it keeps this module free of the pandas-importing
generate_guard_manifest. The one gap -- a brand-new guard file added to
GUARD_FILES but not yet in the manifest -- is owned by the generator and the
pre-commit lint, not the recurring edit-an-existing-guarded-tool pain.

Usage
-----
  python tools/check_guard_drift.py           # report; exit 0 = clean, 1 = drift
  python tools/check_guard_drift.py --quiet    # exit code only; no stdout when clean

Exit: 0 = no drift (MISSING entries are reported WARN-level, faithful to the
runtime guard which WARNs-and-continues on a missing file); 1 = at least one
guarded tool's content drifted from the manifest.

Authority: AGENT.md -- Protected Infrastructure Policy. Companion to
generate_guard_manifest.py (the regen) and lint_guard_manifest_sync.py (the
commit gate).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "tools" / "tools_manifest.json"


def canonical_sha256_path(filepath: Path) -> str:
    """LF-normalized sha256 (uppercase hex) of *filepath*.

    Mirrors tools.verify_engine_integrity.canonical_sha256 but with no heavy
    imports (see module docstring). CRLF->LF normalization makes the digest
    identical on autocrlf (CRLF) and LF working trees -- the Windows trap that
    would otherwise produce spurious mismatches. Pinned to the authoritative
    implementation by the unit test.
    """
    data = filepath.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()


def find_drift(
    project_root: Path | None = None,
    manifest_path: Path | None = None,
) -> list[dict]:
    """Return a list of drift records (empty == in sync).

    Each record:
      {"file": <manifest key>, "status": "DRIFT"|"MISSING",
       "disk": <uppercase hex|None>, "manifest": <uppercase hex>}

    Iterates the manifest's recorded file_hashes. A guarded file present on disk
    whose canonical hash differs -> DRIFT; recorded but absent on disk ->
    MISSING (mirrors the runtime guard's WARN-on-missing). An absent or
    unreadable manifest yields [] (nothing to compare) -- the runtime guard
    owns that failure mode, and the edit-time hook must never crash on it.
    """
    project_root = project_root or PROJECT_ROOT
    manifest_path = manifest_path or (project_root / "tools" / "tools_manifest.json")
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    recorded = manifest.get("file_hashes", {})

    drift: list[dict] = []
    for filename, rec_hash in recorded.items():
        rec = (rec_hash or "").upper()
        # Resolve relative to PROJECT_ROOT, then fall back to tools/ -- the same
        # two-step resolution run_pipeline.verify_tools_timestamp_guard uses, so
        # this checker and the runtime guard agree on which file each key names.
        filepath = project_root / filename
        if not filepath.exists():
            filepath = project_root / "tools" / filename
        if not filepath.exists():
            drift.append(
                {"file": filename, "status": "MISSING", "disk": None, "manifest": rec}
            )
            continue
        actual = canonical_sha256_path(filepath)
        if rec and rec != actual:
            drift.append(
                {"file": filename, "status": "DRIFT", "disk": actual, "manifest": rec}
            )
    return drift


def _manifest_entry_count(manifest_path: Path) -> int:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return len(data.get("file_hashes", {}))
    except Exception:  # noqa: BLE001 -- count is cosmetic; never fail the CLI on it
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Early-warning: list guarded tools whose on-disk canonical hash "
            "differs from tools/tools_manifest.json. Exit 1 on content drift, "
            "0 if clean."
        )
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="No stdout when clean (exit code only).",
    )
    args = parser.parse_args(argv)

    if not MANIFEST_PATH.exists():
        print(f"[WARN] manifest not found: {MANIFEST_PATH} -- nothing to check.")
        return 0

    drift = find_drift()
    drifted = [d for d in drift if d["status"] == "DRIFT"]
    missing = [d for d in drift if d["status"] == "MISSING"]

    if not drift:
        if not args.quiet:
            n = _manifest_entry_count(MANIFEST_PATH)
            print(f"[OK] {n} guarded tools in sync with tools_manifest.json")
        return 0

    if drifted:
        print("[DRIFT] guarded tool(s) out of sync with tools_manifest.json:")
        for d in drifted:
            print(
                f"  tools/{d['file']}: disk={d['disk'][:12]}... "
                f"manifest={d['manifest'][:12]}..."
            )
    if missing:
        print("[WARN] guarded tool(s) recorded in manifest but absent on disk:")
        for d in missing:
            print(f"  tools/{d['file']}")

    if drifted:
        print("")
        print(
            "The run_pipeline startup guard will hard-block the next pipeline run."
        )
        print("Fix:")
        print("    python tools/generate_guard_manifest.py")
        print("    git add tools/tools_manifest.json")
        return 1

    # MISSING only -> WARN-level, faithful to the runtime guard (warns, continues).
    return 0


if __name__ == "__main__":
    sys.exit(main())
