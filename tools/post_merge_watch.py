"""
post_merge_watch.py — observer-model post-merge Stage1 admission watch.

Tracks the next N Stage1 admissions after a code merge to flag warmup
fallbacks or run crashes that would indicate the merge introduced
regression. Updated by passive observation of TradeScan_State/runs/ —
NO mutations inside run_stage1.py. Stage1 stays pristine; the observer
guarantees Stage1 cannot be polluted by watchdog logic.

Lifecycle
---------
    --create <commit> [--runs N]    → status=ACTIVE, target=N runs
    reconcile_watch()                → still ACTIVE while observed < target
    reconcile_watch()                → CLOSED_OK or CLOSED_FAIL when target reached
    --archive                        → moves closed watch under archive/

Single active watch: --create errors if one is already ACTIVE or if
a closed-but-not-archived watch exists.

Cleanliness heuristic
---------------------
A run is "clean" iff:
    data/batch_summary.csv exists  AND
    data/run_metadata.json exists  AND
    crash_trace.log does NOT exist

Anything else → "dirty". The presence of batch_summary.csv +
run_metadata.json proves Stage1 reached completion past the warmup
block. Their absence (with a present run_state.json) signals an early
FATAL or crash — exactly what the watch is looking for.

Concurrency
-----------
Atomic writes via tmp + os.replace. Reconcile is monotonic and
de-duplicates by run_id, so concurrent reconciles converge.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE


WATCH_PATH = TRADE_SCAN_STATE / "post_merge_watch.json"
ARCHIVE_DIR = TRADE_SCAN_STATE / "archive" / "post_merge_watches"
RUNS_DIR = TRADE_SCAN_STATE / "runs"

DEFAULT_TARGET_RUNS = 5


# ─── Helpers ─────────────────────────────────────────────────────────────


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp file in same dir + os.replace.

    Same-directory tmp ensures the rename is atomic on the same volume.
    Concurrent writers each replace into the target; last-writer-wins is
    safe here because reconcile is monotonic + de-dup.

    Cleanup uses try/finally with a success flag — if the write or rename
    raises (TypeError on bad payload, OSError on disk full, etc.) the tmp
    file is unlinked and the exception propagates. The `success` guard
    avoids unlinking after `os.replace` (at that point tmp_path no longer
    exists at the source).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_str)
    success = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
        success = True
    finally:
        if not success:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def _read_watch() -> dict | None:
    """Read the current watch file. None if missing or unparseable."""
    if not WATCH_PATH.exists():
        return None
    try:
        return json.loads(WATCH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ─── Run classification ──────────────────────────────────────────────────


def _classify_run(run_dir: Path) -> dict[str, Any]:
    """Decide whether a Stage1 run is clean or dirty for watch purposes.

    See module docstring for the heuristic. Pure file-existence checks;
    cannot fail at runtime under normal filesystem conditions.
    """
    has_batch = (run_dir / "data" / "batch_summary.csv").exists()
    has_metadata = (run_dir / "data" / "run_metadata.json").exists()
    has_crash = (run_dir / "crash_trace.log").exists()

    clean = has_batch and has_metadata and not has_crash

    return {
        "run_id": run_dir.name,
        "status": "clean" if clean else "dirty",
        "has_batch_summary": has_batch,
        "has_crash_trace": has_crash,
        "observed_at_utc": _now_utc(),
    }


# ─── Observer / reconcile ────────────────────────────────────────────────


def reconcile_watch() -> dict | None:
    """Observer pass: scan runs/ for new completions since watch creation
    and update the watch state.

    - Idempotent (re-runs converge).
    - Concurrent-safe (atomic write + per-id de-dup).
    - Best-effort per-run (malformed run_state.json silently skipped).
    - No-op if no watch exists or watch is not ACTIVE.

    Returns the current watch state (or None if no watch file exists).
    """
    watch = _read_watch()
    if watch is None or watch.get("status") != "ACTIVE":
        return watch

    cutoff = watch.get("created_at_utc", "")
    target = int(watch.get("target_runs", DEFAULT_TARGET_RUNS))
    seen = {obs["run_id"] for obs in watch.get("runs_observed", [])}

    if not RUNS_DIR.exists():
        return watch

    # Collect candidate runs newer than cutoff
    candidates: list[tuple[str, Path]] = []
    for d in RUNS_DIR.iterdir():
        if not d.is_dir():
            continue
        if d.name in seen:
            continue
        rs = d / "run_state.json"
        if not rs.exists():
            continue
        try:
            payload = json.loads(rs.read_text(encoding="utf-8"))
            last = payload.get("last_updated", "")
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(last, str) or last < cutoff:
            continue
        candidates.append((last, d))

    # Process oldest-first so observation order = wall-clock order
    candidates.sort(key=lambda t: t[0])
    for _ts, run_dir in candidates:
        if len(watch["runs_observed"]) >= target:
            break
        watch["runs_observed"].append(_classify_run(run_dir))

    # De-dup defensively (race window between concurrent reconciles)
    deduped: list[dict] = []
    seen_now: set[str] = set()
    for obs in watch["runs_observed"]:
        rid = obs.get("run_id", "")
        if not rid or rid in seen_now:
            continue
        seen_now.add(rid)
        deduped.append(obs)
    watch["runs_observed"] = deduped[:target]
    watch["runs_remaining"] = max(0, target - len(watch["runs_observed"]))

    # Auto-close when target reached
    if watch["runs_remaining"] == 0 and watch["status"] == "ACTIVE":
        any_dirty = any(
            o.get("status") == "dirty" for o in watch["runs_observed"]
        )
        watch["status"] = "CLOSED_FAIL" if any_dirty else "CLOSED_OK"
        watch["closed_at_utc"] = _now_utc()
        watch["close_verdict"] = (
            f"warmup regression detected ({sum(1 for o in watch['runs_observed'] if o.get('status') == 'dirty')}/{target} dirty observations)"
            if any_dirty
            else f"all {target} observations clean"
        )

    _atomic_write(WATCH_PATH, watch)
    return watch


# ─── Lifecycle commands ──────────────────────────────────────────────────


def create_watch(commit_hash: str, target_runs: int = DEFAULT_TARGET_RUNS) -> dict:
    """Create a new ACTIVE watch. Refuses if any watch file already exists.

    Refuses both ACTIVE and CLOSED_* — caller must --archive first to
    enforce the "single watch" invariant cleanly.
    """
    existing = _read_watch()
    if existing is not None:
        status = existing.get("status", "?")
        if status == "ACTIVE":
            raise RuntimeError(
                f"Cannot create new watch: an ACTIVE watch already exists "
                f"(watch_id={existing.get('watch_id')!r}, "
                f"commit={existing.get('commit_hash')!r}, "
                f"runs_remaining={existing.get('runs_remaining')}). "
                f"Wait for auto-close or remove the file manually if stale."
            )
        else:
            raise RuntimeError(
                f"A {status} watch exists at {WATCH_PATH}. Run "
                f"`python tools/post_merge_watch.py --archive` to clear "
                f"before creating a new watch."
            )

    if int(target_runs) < 1:
        raise ValueError(f"target_runs must be >= 1 (got {target_runs!r})")

    watch = {
        "watch_id": secrets.token_hex(4),
        "commit_hash": str(commit_hash),
        "created_at_utc": _now_utc(),
        "target_runs": int(target_runs),
        "runs_observed": [],
        "runs_remaining": int(target_runs),
        "status": "ACTIVE",
        "closed_at_utc": None,
        "close_verdict": None,
    }
    _atomic_write(WATCH_PATH, watch)
    return watch


def archive_watch() -> Path:
    """Move a CLOSED_* watch to archive/. Refuses if status == ACTIVE.

    Returns the destination path.
    """
    watch = _read_watch()
    if watch is None:
        raise RuntimeError(f"No watch file at {WATCH_PATH}")
    status = watch.get("status", "?")
    if status == "ACTIVE":
        raise RuntimeError(
            f"Cannot archive ACTIVE watch (runs_remaining="
            f"{watch.get('runs_remaining')}). Wait for auto-close, or run "
            f"`--update` to reconcile if you believe target has been reached."
        )

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / f"{watch['watch_id']}.json"
    os.replace(WATCH_PATH, target)
    return target


# ─── CLI ─────────────────────────────────────────────────────────────────


def _format_status(w: dict) -> str:
    status = w.get("status", "?")
    target = w.get("target_runs", "?")
    observed = len(w.get("runs_observed", []))
    commit = (w.get("commit_hash") or "?")[:8]
    lines = [
        f"watch_id    : {w.get('watch_id')}",
        f"commit      : {commit}",
        f"created_utc : {w.get('created_at_utc')}",
        f"status      : {status}",
        f"observed    : {observed}/{target}",
    ]
    if status.startswith("CLOSED_"):
        lines.append(f"closed_utc  : {w.get('closed_at_utc')}")
        lines.append(f"verdict     : {w.get('close_verdict')}")
    if w.get("runs_observed"):
        lines.append("runs_observed:")
        for o in w["runs_observed"]:
            lines.append(
                f"  - {o.get('run_id'):<24}  {o.get('status'):<6}  "
                f"batch={o.get('has_batch_summary')!s:<5} "
                f"crash={o.get('has_crash_trace')!s:<5} "
                f"at {o.get('observed_at_utc')}"
            )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Post-merge Stage1 admission watch (observer model)."
    )
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--create",
        metavar="COMMIT",
        help="Create new ACTIVE watch for the given commit hash",
    )
    grp.add_argument("--status", action="store_true", help="Print current state")
    grp.add_argument(
        "--update",
        action="store_true",
        help="Run observer reconcile against TradeScan_State/runs/",
    )
    grp.add_argument(
        "--archive",
        action="store_true",
        help="Move CLOSED_* watch to archive/ (refuses ACTIVE)",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_TARGET_RUNS,
        help=f"Target runs for --create (default {DEFAULT_TARGET_RUNS})",
    )
    args = p.parse_args()

    if args.create:
        w = create_watch(args.create, args.runs)
        print(
            f"[CREATE] watch_id={w['watch_id']} commit={w['commit_hash']} "
            f"target_runs={w['target_runs']} created_at={w['created_at_utc']}"
        )
        print(f"        watch file: {WATCH_PATH}")
        return 0

    if args.status:
        w = _read_watch()
        if w is None:
            print("[STATUS] no watch file present")
            return 0
        print(_format_status(w))
        return 0

    if args.update:
        w = reconcile_watch()
        if w is None:
            print("[UPDATE] no watch file present — nothing to do")
            return 0
        print(_format_status(w))
        return 0

    if args.archive:
        try:
            target = archive_watch()
        except RuntimeError as e:
            print(f"[ARCHIVE] refused: {e}")
            return 1
        print(f"[ARCHIVE] moved to {target}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
