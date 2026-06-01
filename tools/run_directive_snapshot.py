"""run_directive_snapshot.py — co-locate the source directive with each run.

A run's strategy.py (single-strategy) or leg+rule code (basket) can only be
produced AFTER reading the directive, so the directive is the irreproducible
source. This module drops a byte-for-byte copy of that source directive into
the run folder (`runs/<run_id>/directive.txt`, write-once) so every run is
self-describing and reproducible standalone — immune to a later `completed/`
cleanup that quarantines the original. Parallel to the strategy.py snapshot
(`runs/<id>/strategy.py`) and the basket `basket_code/` snapshot.

Used by:
  - run_stage1 single-strategy snapshot (forward, resolves by strategy_id)
  - run_pipeline basket dispatch (forward, directive path in hand)
  - tools/backfill_run_directives.py (existing runs)
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

DIRECTIVE_SNAPSHOT_NAME = "directive.txt"
# Live directive locations searched by directive_id, most-authoritative last.
_LIVE_SUBDIRS = ("INBOX", "active", "active_backup", "completed")


def find_live_directive(directive_id: str, project_root) -> Path | None:
    """Return the on-disk `<directive_id>.txt` from the live backtest_directives
    subdirs, or None. (For runs where the directive is still live — the forward
    path. Backfill extends this to quarantine + git history.)"""
    base = Path(project_root) / "backtest_directives"
    for sub in _LIVE_SUBDIRS:
        p = base / sub / f"{directive_id}.txt"
        if p.is_file():
            return p
    return None


def directive_sha256(directive_path) -> str:
    return hashlib.sha256(Path(directive_path).read_bytes()).hexdigest()


def snapshot_run_directive(run_dir, directive_path, *, write_once: bool = True) -> dict | None:
    """Copy `directive_path` -> `run_dir/directive.txt` (write-once) and return
    {"filename", "sha256", "written"}.

    Returns None if `directive_path` is missing/None. Write-once: if the
    snapshot already exists, it is NOT overwritten; the existing file's hash is
    returned with written=False (mirrors Snapshot Immutability).
    """
    if not directive_path:
        return None
    src = Path(directive_path)
    if not src.is_file():
        return None
    run_dir = Path(run_dir)
    dest = run_dir / DIRECTIVE_SNAPSHOT_NAME

    if dest.exists() and write_once:
        return {
            "filename": src.name,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "written": False,
        }

    run_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    shutil.copy2(src, dest)  # byte-exact copy, mirrors the strategy.py snapshot
    return {"filename": src.name, "sha256": sha, "written": True}
