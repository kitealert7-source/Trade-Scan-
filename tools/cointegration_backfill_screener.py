"""cointegration_backfill_screener.py — retrospective daily-snapshot fill.

Replays the cointegration screener for every business day in a window
(default: today - 1 year through today), writing one as_of snapshot per
iteration to SQLite. Each iteration is methodologically equivalent to
what the screener WOULD have computed on that date — the underlying
`run(as_of=...)` truncates input data to bars ≤ as_of, so no look-ahead.

BC2 (2026-05-30) extension for the v2 eligibility backfill:
  * --tfs 1d,4h           multi-TF support (was 1d-only)
  * --max-parallel N      ProcessPoolExecutor over (as_of, tf) tasks; the
                          upsert step remains chronological + serial so
                          the hysteresis classifier composes correctly
  * --resume              resume from max(as_of) WHERE methodology_version
                          IN ('v2_log_eg','v2_log_adf') per TF; skips
                          truncate + backup
  * --workdir PATH        override the per-(as_of, tf) parquet workdir
  * mandatory pre-flight: refuses to start if
                          CointegrationScreener_DailyRun scheduled task
                          is enabled (concurrent-write race protection)

Why backfill instead of waiting for natural accumulation?
    Without backfill: realised-backtest analysis has to wait ~3 months
    for enough daily snapshots to accumulate.
    With backfill (1y): ~250 trading days of history populate in ~30-45
    minutes of compute. Hysteresis classifier engages naturally as
    priors build up through the loop (because we go chronologically).

The cointegration_triggers ledger is rebuilt at the end from the now-
populated cointegration_daily table (TRIGGER_Z_FLOOR floors at 1.5).

Safety: existing tables are backed up (CREATE TABLE … AS SELECT) before
truncation, so a failed mid-run can be recovered by RENAMing the backup
tables back. Backup tables suffixed with the timestamp of the run.

Usage:
    python tools/cointegration_backfill_screener.py                # default: 1y back, 1d only, serial
    python tools/cointegration_backfill_screener.py --years 2      # 2y back
    python tools/cointegration_backfill_screener.py --start 2024-01-01
    python tools/cointegration_backfill_screener.py --tfs 1d,4h --max-parallel 8
    python tools/cointegration_backfill_screener.py --resume       # resume after a kill
    python tools/cointegration_backfill_screener.py --dry-run      # plan only
    python tools/cointegration_backfill_screener.py --skip-backup  # advanced
"""
from __future__ import annotations

import argparse
import concurrent.futures as _cf
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout — arrows and other non-cp1252 chars used in log lines.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from tools.cointegration_db import (
    SQLITE_DB, TABLE_NAME, SINGLES_TABLE_NAME, TRIGGERS_TABLE_NAME,
    connect, create_tables, rebuild_triggers_from_history,
    upsert_from_parquet, upsert_singles_from_parquet,
)
from tools.cointegration_screen import (
    SUPPORTED_TFS, run, run_singles,
)


# Production scheduled task name (registered by
# outputs/cointegration_screener_v1/phase4/register_daily_task.ps1). The
# mandatory pre-flight check below queries Task Scheduler for this name
# and refuses to start the backfill if the task is enabled.
SCHEDULED_TASK_NAME = "CointegrationScreener_DailyRun"

# BC2 §6.7: leave at least this many cores free for the parent + OS.
PARALLEL_RESERVE_CORES = 2


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}",
          flush=True)


# ---------------------------------------------------------------------------
# Mandatory pre-flight — scheduled-writer pause check (BC1 §6.7)
# ---------------------------------------------------------------------------


class SchedulerStillEnabledError(RuntimeError):
    """Raised when the production daily-runner scheduled task is enabled at
    backfill-start time. No bypass — operator must explicitly disable the
    task before running the backfill, then re-enable after BC4 verify."""


def _check_scheduler_paused(task_name: str = SCHEDULED_TASK_NAME) -> None:
    """Refuse to start backfill if the production daily-runner scheduled
    task is enabled. Mandatory per BC1 §6.7; no override flag.

    Returns silently if:
      - The platform is not Windows (no Task Scheduler).
      - The task is not registered.
      - The schtasks query reports state 'Disabled'.

    Raises SchedulerStillEnabledError if the task is reported in any state
    other than Disabled. The caller is expected to surface the error and
    exit non-zero before any DB connection is opened.
    """
    if os.name != "nt":
        _log("scheduler check: non-Windows platform, no schtasks — OK")
        return

    schtasks = shutil.which("schtasks")
    if not schtasks:
        _log("WARN  scheduler check: schtasks not found on PATH — "
             "cannot verify scheduled writer state; proceeding at operator risk")
        return

    try:
        result = subprocess.run(
            [schtasks, "/Query", "/TN", task_name, "/V", "/FO", "LIST"],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise SchedulerStillEnabledError(
            f"scheduler check timed out querying '{task_name}' — refusing to "
            f"start backfill while task state is unknown")

    if result.returncode != 0:
        # Task not registered → no scheduled writer to race with.
        _log(f"scheduler check: '{task_name}' not registered — OK")
        return

    state_line = next(
        (l for l in result.stdout.splitlines() if "Scheduled Task State" in l),
        None,
    )
    if state_line is None:
        raise SchedulerStillEnabledError(
            f"scheduler check could not parse state for '{task_name}' — "
            f"refusing to start backfill while task state is unknown")

    state = state_line.split(":", 1)[1].strip()
    if state.lower() == "disabled":
        _log(f"scheduler check: '{task_name}' Disabled — OK")
        return

    raise SchedulerStillEnabledError(
        f"scheduled task '{task_name}' is '{state}' — concurrent writes "
        f"could race the backfill. Disable it first:\n"
        f"  schtasks /Change /TN {task_name} /DISABLE\n"
        f"Re-enable after BC4 verify:\n"
        f"  schtasks /Change /TN {task_name} /ENABLE"
    )


# ---------------------------------------------------------------------------
# Argparse helpers
# ---------------------------------------------------------------------------


def _parse_tfs(s: str) -> list[str]:
    """Parse `--tfs 1d,4h` into a validated list. Raises argparse.ArgumentTypeError
    on any unsupported TF — prevents scope-creep before the screener supports
    additional timeframes."""
    tfs = [tok.strip() for tok in s.split(",") if tok.strip()]
    if not tfs:
        raise argparse.ArgumentTypeError("--tfs must list at least one TF")
    bad = [tf for tf in tfs if tf not in SUPPORTED_TFS]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unsupported TF(s) {bad}; allowed: {sorted(SUPPORTED_TFS)}")
    # De-dupe while preserving order
    seen, out = set(), []
    for tf in tfs:
        if tf not in seen:
            seen.add(tf)
            out.append(tf)
    return out


def _bounded_parallel(requested: int) -> int:
    """Clamp `--max-parallel N` to leave PARALLEL_RESERVE_CORES free.
    Floor at 1 (serial mode). Per BC1 §6.1."""
    if requested <= 1:
        return 1
    cap = max(1, (os.cpu_count() or 2) - PARALLEL_RESERVE_CORES)
    return min(requested, cap)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def _find_resume_point(conn, tfs: list[str]) -> dict[str, str | None]:
    """Per-TF, return the max(as_of) where methodology_version is one of the
    post-C3 cohorts. None if no v2 rows for that TF.

    The chronological order constraint applies per-TF (the daily and singles
    tables are TF-keyed; hysteresis priors are TF-specific). We compute the
    per-TF resume frontier so a partially-completed backfill picks up exactly
    where it left off without re-doing the already-upserted snapshots."""
    out: dict[str, str | None] = {}
    for tf in tfs:
        row = conn.execute(
            f"SELECT MAX(as_of) FROM {TABLE_NAME} "
            f"WHERE tf = ? AND methodology_version IN ('v2_log_eg', 'v2_log_adf')",
            (tf,),
        ).fetchone()
        out[tf] = row[0] if row and row[0] else None
    return out


# ---------------------------------------------------------------------------
# Backup + truncate (preserved from pre-BC2 behavior)
# ---------------------------------------------------------------------------


def _backup_tables(conn, suffix: str) -> None:
    """Snapshot cointegration_daily and singles_daily to backup tables.

    The backup tables are named <table>_backup_<suffix>. If a previous
    backup with the same suffix exists, it's dropped first.
    """
    for tbl in (TABLE_NAME, SINGLES_TABLE_NAME, TRIGGERS_TABLE_NAME):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if row is None:
            _log(f"  (no {tbl} to backup — skipping)")
            continue
        backup = f"{tbl}_backup_{suffix}"
        conn.execute(f"DROP TABLE IF EXISTS {backup}")
        conn.execute(f"CREATE TABLE {backup} AS SELECT * FROM {tbl}")
        n = conn.execute(f"SELECT COUNT(*) FROM {backup}").fetchone()[0]
        _log(f"  backed up {tbl} → {backup}  ({n} rows)")
    conn.commit()


def _truncate_tables(conn) -> None:
    """Wholesale wipe of cointegration_daily, singles_daily,
    cointegration_triggers (BC1 §6.5 default). Backup tables (created
    separately) preserve the pre-backfill state."""
    for tbl in (TABLE_NAME, SINGLES_TABLE_NAME, TRIGGERS_TABLE_NAME):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()
    _log(f"  truncated {TABLE_NAME}, {SINGLES_TABLE_NAME}, "
         f"{TRIGGERS_TABLE_NAME}")


# ---------------------------------------------------------------------------
# Compute phase (worker-side; module-level so ProcessPoolExecutor can pickle)
# ---------------------------------------------------------------------------


def _parquet_paths(workdir: Path, tf: str, as_of: pd.Timestamp,
                    ) -> tuple[Path, Path]:
    """Canonical per-(as_of, tf) parquet paths inside the workdir."""
    stamp = as_of.strftime("%Y-%m-%d")
    return (workdir / f"coint_{tf}_{stamp}.parquet",
            workdir / f"singles_{tf}_{stamp}.parquet")


def _compute_one(as_of_iso: str, tf: str, workdir_str: str) -> tuple[str, str]:
    """Worker: compute the screener for one (as_of, tf) pair and write per-task
    parquets to the workdir. Returns (coint_parquet_path, singles_parquet_path).

    No DB access. No shared state between workers. Pure compute → isolated
    output, per the validated `shard-per-worker + parent merge` pattern
    (feedback_parallelization_selectivity).
    """
    as_of = pd.Timestamp(as_of_iso)
    workdir = Path(workdir_str)
    coint_path, singles_path = _parquet_paths(workdir, tf, as_of)

    coint_df = run(as_of=as_of, tf=tf)
    coint_df.to_parquet(coint_path, index=False)

    singles_df = run_singles(
        as_of=as_of, tf=tf,
        synthetic_specs=[("BTCUSD", "ETHUSD")],
    )
    singles_df.to_parquet(singles_path, index=False)

    return (str(coint_path), str(singles_path))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def backfill(start_date: pd.Timestamp, end_date: pd.Timestamp,
              *, tfs: list[str] | None = None,
              max_parallel: int = 1,
              do_backup: bool = True,
              dry_run: bool = False,
              resume: bool = False,
              workdir: Path | None = None,
              ) -> None:
    """Run the screener for every business day in [start_date, end_date]
    across all requested timeframes.

    Compute is parallel (ProcessPoolExecutor over (as_of, tf) tasks); the
    upsert step is sequential and chronological so the hysteresis classifier
    composes correctly with same-methodology priors.
    """
    # Mandatory pre-flight — refuse to start if the daily-runner task is
    # enabled (no override). Run BEFORE any DB connection opens.
    _check_scheduler_paused()

    tfs = tfs or ["1d"]
    bounded = _bounded_parallel(max_parallel)
    if bounded != max_parallel:
        _log(f"NOTE  max_parallel {max_parallel} clamped to {bounded} "
             f"(cpu_count={os.cpu_count()}, reserve={PARALLEL_RESERVE_CORES})")

    dates = pd.bdate_range(start_date, end_date)

    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir = workdir or (PROJECT_ROOT / "tmp" / f"backfill_{suffix}")
    workdir.mkdir(parents=True, exist_ok=True)

    _log(f"backfill plan: {len(dates)} business days from "
         f"{dates[0].date()} → {dates[-1].date()}")
    _log(f"  tfs={tfs}  max_parallel={bounded}  workdir={workdir}  "
         f"resume={resume}  do_backup={do_backup and not resume}  "
         f"dry_run={dry_run}")

    if dry_run:
        _log("--dry-run: no compute, no DB writes")
        return

    conn = connect()
    create_tables(conn)

    if resume:
        # Skip backup + truncate; trim the work-list to what's missing.
        resume_points = _find_resume_point(conn, tfs)
        _log(f"resume: per-TF max as_of = {resume_points}")
    else:
        if do_backup:
            _log(f"backing up existing tables (suffix _backup_{suffix})...")
            _backup_tables(conn, suffix)
        _log("truncating live tables (backups preserved for rollback)...")
        _truncate_tables(conn)
        resume_points = {tf: None for tf in tfs}

    # Build the worker task list: (as_of, tf) pairs that still need compute.
    # Resume: skip any (as_of, tf) where as_of <= the per-TF resume point.
    tasks: list[tuple[str, str]] = []
    for as_of in dates:
        as_of_iso = as_of.strftime("%Y-%m-%d")
        for tf in tfs:
            rp = resume_points.get(tf)
            if rp is not None and as_of_iso <= rp:
                continue
            tasks.append((as_of_iso, tf))

    if not tasks:
        _log("resume: nothing to do — live tables already cover the requested range")
        conn.close()
        return

    _log(f"compute phase: {len(tasks)} (as_of, tf) tasks queued")
    t_start = time.time()
    n_fail = 0
    workdir_str = str(workdir)

    if bounded <= 1:
        # Serial mode (preserves deterministic behavior + makes the
        # determinism-guard test simple).
        for i, (as_of_iso, tf) in enumerate(tasks, start=1):
            try:
                _compute_one(as_of_iso, tf, workdir_str)
                if i == 1 or i % 25 == 0 or i == len(tasks):
                    elapsed = time.time() - t_start
                    avg = elapsed / i
                    eta = avg * (len(tasks) - i)
                    _log(f"  [{i:4d}/{len(tasks)}]  {as_of_iso}/{tf}  "
                         f"elapsed={elapsed:.0f}s  eta≈{eta:.0f}s")
            except Exception as exc:
                n_fail += 1
                _log(f"  [{i:4d}/{len(tasks)}]  {as_of_iso}/{tf}  FAIL: "
                     f"{type(exc).__name__}: {exc}")
                if n_fail >= 5:
                    _log("ABORT: 5+ failures, aborting backfill")
                    raise
    else:
        # Parallel mode — workers write per-task parquets to the workdir.
        with _cf.ProcessPoolExecutor(max_workers=bounded) as pool:
            futures = {
                pool.submit(_compute_one, as_of_iso, tf, workdir_str):
                    (as_of_iso, tf)
                for as_of_iso, tf in tasks
            }
            done = 0
            for fut in _cf.as_completed(futures):
                as_of_iso, tf = futures[fut]
                done += 1
                try:
                    fut.result()
                except Exception as exc:
                    n_fail += 1
                    _log(f"  [{done:4d}/{len(tasks)}]  {as_of_iso}/{tf}  "
                         f"FAIL: {type(exc).__name__}: {exc}")
                    if n_fail >= 5:
                        _log("ABORT: 5+ failures, aborting backfill")
                        for f in futures:
                            f.cancel()
                        raise
                else:
                    if done == 1 or done % 25 == 0 or done == len(tasks):
                        elapsed = time.time() - t_start
                        avg = elapsed / done
                        eta = avg * (len(tasks) - done)
                        _log(f"  [{done:4d}/{len(tasks)}]  {as_of_iso}/{tf}  "
                             f"elapsed={elapsed:.0f}s  eta≈{eta:.0f}s")

    _log(f"compute complete in {time.time() - t_start:.0f}s "
         f"({n_fail} failures)")

    # Upsert phase: strictly chronological + serial. Hysteresis classifier
    # reads same-methodology priors from the DB, so order matters: as_of N
    # must be upserted before as_of N+1 within the same (pair, tf, lookback).
    _log(f"upsert phase: walking {len(tasks)} parquets chronologically...")
    t_up = time.time()
    upserted = 0
    for as_of in dates:
        as_of_iso = as_of.strftime("%Y-%m-%d")
        for tf in tfs:
            rp = resume_points.get(tf)
            if rp is not None and as_of_iso <= rp:
                continue
            coint_p, singles_p = _parquet_paths(workdir, tf, as_of)
            if not coint_p.is_file():
                # Compute-side failure — skip; parquet doesn't exist
                continue
            upsert_from_parquet(conn, coint_p)
            upsert_singles_from_parquet(conn, singles_p)
            upserted += 1
    _log(f"upsert complete: {upserted} (as_of, tf) snapshots in "
         f"{time.time() - t_up:.0f}s")

    _log("rebuilding cointegration_triggers from full history...")
    n_trig = rebuild_triggers_from_history(conn)
    _log(f"  populated {n_trig} trigger events")

    # Summary
    row = conn.execute(
        f"SELECT COUNT(*), MIN(as_of), MAX(as_of) FROM {TABLE_NAME}"
    ).fetchone()
    _log(f"final state: {row[0]} cointegration_daily rows from "
         f"{row[1]} to {row[2]}")
    row = conn.execute(
        f"SELECT COUNT(*) FROM {SINGLES_TABLE_NAME}"
    ).fetchone()
    _log(f"final state: {row[0]} singles_daily rows")
    row = conn.execute(
        f"SELECT COUNT(*) FROM {TRIGGERS_TABLE_NAME}"
    ).fetchone()
    _log(f"final state: {row[0]} cointegration_triggers rows")

    conn.close()
    _log("DONE.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Retrospective fill of cointegration screener history.")
    p.add_argument("--years", type=float, default=1.0,
                   help="Years of history to backfill (default: 1.0).")
    p.add_argument("--start", type=str, default=None,
                   help="Override start date (YYYY-MM-DD). Overrides --years.")
    p.add_argument("--end", type=str, default=None,
                   help="End date (YYYY-MM-DD); default today.")
    p.add_argument("--tfs", type=_parse_tfs, default=["1d"],
                   help="Comma-separated TFs (e.g. '1d,4h'); "
                        f"supported: {sorted(SUPPORTED_TFS)}. Default: 1d.")
    p.add_argument("--max-parallel", type=int, default=1,
                   help="ProcessPoolExecutor worker count. Clamped to "
                        f"cpu_count - {PARALLEL_RESERVE_CORES}. Default: 1 (serial).")
    p.add_argument("--resume", action="store_true",
                   help="Resume from max(as_of) per TF where methodology is v2. "
                        "Skips backup + truncate.")
    p.add_argument("--workdir", type=Path, default=None,
                   help="Override per-(as_of, tf) parquet workdir.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan only; no compute or DB writes.")
    p.add_argument("--skip-backup", action="store_true",
                   help="Skip the backup-tables step (advanced; loses rollback).")
    args = p.parse_args(argv)

    end_date = (pd.Timestamp(args.end) if args.end
                else pd.Timestamp.now().normalize())
    end_date = end_date.tz_localize(None) if end_date.tzinfo else end_date
    if args.start:
        start_date = pd.Timestamp(args.start)
        start_date = (start_date.tz_localize(None)
                      if start_date.tzinfo else start_date)
    else:
        start_date = end_date - pd.Timedelta(days=int(args.years * 365))

    try:
        backfill(
            start_date, end_date,
            tfs=args.tfs,
            max_parallel=args.max_parallel,
            do_backup=not args.skip_backup,
            dry_run=args.dry_run,
            resume=args.resume,
            workdir=args.workdir,
        )
    except SchedulerStillEnabledError as exc:
        _log(f"FATAL  {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
