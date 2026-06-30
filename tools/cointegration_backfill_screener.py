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
                          AntiGravity_Daily_Preflight scheduled task
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
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
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


# Production scheduled task name. The cointegration screener is NOT
# triggered directly by Task Scheduler — DATA_INGRESS's daily pipeline
# (invoke_preflight.ps1 → invoke_daily_pipeline.ps1) invokes
# tools/cointegration_daily_runner.py as a downstream consumer of the
# data-update phase (DATA_INGRESS/engines/ops/invoke_daily_pipeline.ps1
# line ~300-334). So the real concurrent-write risk is the AntiGravity
# preflight task, which is what we check here. The legacy task name
# 'AntiGravity_Daily_Preflight' (registered by
# outputs/cointegration_screener_v1/phase4/register_daily_task.ps1) is
# no longer the production path and is typically not registered.
SCHEDULED_TASK_NAME = "AntiGravity_Daily_Preflight"

# BC2 §6.7: leave at least this many cores free for the parent + OS.
PARALLEL_RESERVE_CORES = 2


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}",
          flush=True)


# Transient parquet workdirs (tmp/backfill_<ts>/) accumulate — the screener runs on a
# boot+4h cadence and historically never cleaned them (500+ dirs / 3000+ parquet by
# 2026-06-30). The parquet are P1 intermediates (consumed into SQLite/Excel by the
# daily runner; recoverable via `cointegration_excel.py --export`), so completed-run
# workdirs are safe to age-prune. Default 7d retention keeps a week for debugging;
# override with the COINT_BACKFILL_RETENTION_DAYS env var.
BACKFILL_RETENTION_DAYS = int(os.environ.get("COINT_BACKFILL_RETENTION_DAYS", "7"))


def _prune_old_backfill_workdirs(tmp_root: Path,
                                 retention_days: int = BACKFILL_RETENTION_DAYS) -> int:
    """Delete `tmp/backfill_*` workdirs older than retention_days (by mtime).

    Housekeeping at the source for the standard accumulation location. Touches ONLY
    the `backfill_*` glob — never other tmp/ contents (logs, test dirs, run output).
    Recent / in-flight runs (< retention_days) are preserved. `rmtree(ignore_errors)`
    so a locked or concurrently-written dir is skipped, not fatal. Returns the count
    removed.
    """
    if retention_days < 0 or not tmp_root.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for d in sorted(tmp_root.glob("backfill_*")):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


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


def _compute_one(as_of_iso: str, tf: str, workdir_str: str,
                  profile: bool = False) -> tuple[str, str]:
    """Worker: compute the screener for one (as_of, tf) pair and write per-task
    parquets to the workdir. Returns (coint_parquet_path, singles_parquet_path).

    No DB access. No shared state between workers. Pure compute → isolated
    output, per the validated `shard-per-worker + parent merge` pattern
    (feedback_parallelization_selectivity).

    When profile=True, the worker monkey-patches `cointegration_screen._load_native_closes`
    to record per-call duration + (symbol, tf) key, then emits one JSONL row per task to
    `workdir/_timings_pid<PID>.jsonl`. The patch is restored in `finally` so the worker
    is identical to the non-profile path on completion. NO behavior change otherwise.
    """
    as_of = pd.Timestamp(as_of_iso)
    workdir = Path(workdir_str)
    coint_path, singles_path = _parquet_paths(workdir, tf, as_of)

    if not profile:
        coint_df = run(as_of=as_of, tf=tf)
        coint_df.to_parquet(coint_path, index=False)

        singles_df = run_singles(
            as_of=as_of, tf=tf,
            synthetic_specs=[("BTCUSD", "ETHUSD")],
        )
        singles_df.to_parquet(singles_path, index=False)

        return (str(coint_path), str(singles_path))

    # --- profile path: monkey-patch loader for per-call counting + timing ---
    import tools.cointegration_screen as _cs
    original_load = _cs._load_native_closes
    load_log: list[tuple[str, str, float]] = []

    def _wrapped_load(symbol, tf_in, start, end):
        _t = time.perf_counter()
        _r = original_load(symbol, tf_in, start, end)
        load_log.append((symbol, tf_in, time.perf_counter() - _t))
        return _r

    _cs._load_native_closes = _wrapped_load
    try:
        # run() — pair-pair compute over universe, includes loader calls
        n_before = len(load_log)
        t0 = time.perf_counter()
        coint_df = run(as_of=as_of, tf=tf)
        run_total_s = time.perf_counter() - t0
        run_load_s = sum(d for _, _, d in load_log[n_before:])
        run_compute_s = max(0.0, run_total_s - run_load_s)

        # parquet write pair
        t0 = time.perf_counter()
        coint_df.to_parquet(coint_path, index=False)
        pw_pair_s = time.perf_counter() - t0

        # run_singles() — single-series ADF, also calls loader
        n_before = len(load_log)
        t0 = time.perf_counter()
        singles_df = run_singles(
            as_of=as_of, tf=tf,
            synthetic_specs=[("BTCUSD", "ETHUSD")],
        )
        singles_total_s = time.perf_counter() - t0
        singles_load_s = sum(d for _, _, d in load_log[n_before:])
        singles_compute_s = max(0.0, singles_total_s - singles_load_s)

        # parquet write singles
        t0 = time.perf_counter()
        singles_df.to_parquet(singles_path, index=False)
        pw_singles_s = time.perf_counter() - t0

        task_wall_s = run_total_s + pw_pair_s + singles_total_s + pw_singles_s
        record = {
            "worker_pid": os.getpid(),
            "as_of": as_of_iso,
            "tf": tf,
            "task_wall_s": task_wall_s,
            "spans_s": {
                "data_load_pair": run_load_s,
                "compute_pair": run_compute_s,
                "data_load_singles": singles_load_s,
                "compute_singles": singles_compute_s,
                "parquet_write_pair": pw_pair_s,
                "parquet_write_singles": pw_singles_s,
            },
            "load_count": len(load_log),
            "load_keys": [[s, t] for s, t, _ in load_log],
        }
        jsonl_path = workdir / f"_timings_pid{os.getpid()}.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return (str(coint_path), str(singles_path))
    finally:
        _cs._load_native_closes = original_load


def _aggregate_timings(workdir: Path) -> str:
    """Read all `_timings_pid*.jsonl` shards in workdir; emit Markdown report.

    Sections: per-span median + p95 + %; tasks-per-worker; first-task vs rest;
    load-count census per (symbol, tf); verdict hints driven by thresholds.
    """
    records: list[dict] = []
    for f in sorted(workdir.glob("_timings_pid*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        return "# BC backfill timing report\n\n(no timing records — `--profile` may not have run)\n"

    span_names = ["data_load_pair", "compute_pair", "data_load_singles",
                  "compute_singles", "parquet_write_pair", "parquet_write_singles"]
    samples = {s: [r["spans_s"][s] for r in records] for s in span_names}
    medians = {s: statistics.median(v) for s, v in samples.items()}
    p95s: dict[str, float] = {}
    for s, v in samples.items():
        if len(v) >= 20:
            p95s[s] = statistics.quantiles(v, n=20)[18]
        else:
            p95s[s] = max(v) if v else 0.0
    total_median = sum(medians.values())

    worker_tasks = Counter(r["worker_pid"] for r in records)
    load_keys: Counter = Counter()
    for r in records:
        for k in r["load_keys"]:
            load_keys[tuple(k)] += 1

    worker_walls: dict[int, list[float]] = defaultdict(list)
    for r in records:
        worker_walls[r["worker_pid"]].append(r["task_wall_s"])

    first_vs_rest = []
    for pid, walls in worker_walls.items():
        if len(walls) >= 2:
            first_vs_rest.append((pid, walls[0], statistics.median(walls[1:]),
                                   walls[0] - statistics.median(walls[1:])))

    lines: list[str] = []
    lines.append("# BC backfill timing report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Tasks: {len(records)} | Workers: {len(worker_tasks)} | "
                 f"Total `_load_native_closes` calls: {sum(load_keys.values())}")
    lines.append("")
    lines.append("## Per-task spans (median across all tasks)")
    lines.append("")
    lines.append("| Component | Median (ms) | p95 (ms) | % of task |")
    lines.append("|---|---:|---:|---:|")
    for s in span_names:
        pct = (100 * medians[s] / total_median) if total_median > 0 else 0
        lines.append(f"| {s} | {medians[s]*1000:.0f} | {p95s[s]*1000:.0f} | {pct:.1f}% |")
    lines.append(f"| **Total (sum of medians)** | **{total_median*1000:.0f}** | | 100% |")
    lines.append("")
    lines.append("## Tasks per worker")
    lines.append("")
    for pid in sorted(worker_tasks):
        lines.append(f"- worker {pid}: {worker_tasks[pid]} tasks")
    lines.append("")
    lines.append("## First-task vs rest (per worker)")
    lines.append("")
    if first_vs_rest:
        lines.append("| worker_pid | first task (s) | median of rest (s) | first-call overhead (s) |")
        lines.append("|---|---:|---:|---:|")
        for pid, first, rest, delta in first_vs_rest:
            lines.append(f"| {pid} | {first:.2f} | {rest:.2f} | {delta:.2f} |")
    else:
        lines.append("(insufficient samples — need ≥2 tasks per worker)")
    lines.append("")
    lines.append("## Load-count census per (symbol, tf) — top 20")
    lines.append("")
    lines.append("| symbol | tf | loads |")
    lines.append("|---|---|---:|")
    for (sym, tf_k), cnt in sorted(load_keys.items(), key=lambda x: -x[1])[:20]:
        lines.append(f"| {sym} | {tf_k} | {cnt} |")
    lines.append("")
    lines.append("## Verdict hints")
    lines.append("")
    load_share = ((medians["data_load_pair"] + medians["data_load_singles"]) / total_median * 100
                   if total_median > 0 else 0)
    if load_share >= 60:
        lines.append(f"- Data loading dominates: **{load_share:.1f}%** of per-task wall. "
                     f"Cache hypothesis viable.")
    elif load_share >= 30:
        lines.append(f"- Data loading is significant ({load_share:.1f}%) but not dominant. "
                     f"Cache fix would help but is not the largest lever.")
    else:
        lines.append(f"- Data loading is only {load_share:.1f}% of per-task wall. "
                     f"Cache hypothesis **WEAK**. Look elsewhere.")
    max_tpw = max(worker_tasks.values()) if worker_tasks else 0
    if max_tpw <= 1:
        lines.append(f"- Each worker processes ≤1 task. Cache **CANNOT** help — "
                     f"each worker only loads once anyway.")
    elif max_tpw >= 5:
        lines.append(f"- Workers process up to {max_tpw} tasks each. Cache amortization is applicable.")
    else:
        lines.append(f"- Workers process up to {max_tpw} tasks each. Cache helps moderately.")
    if load_keys:
        max_loads = max(load_keys.values())
        if max_loads >= max_tpw * 2 and max_tpw > 1:
            cache_savings = (1 - 1 / max_loads) * 100 if max_loads else 0
            lines.append(f"- Same (symbol, tf) loaded up to {max_loads}× — heavy redundancy. "
                         f"Worker-local cache would catch ~{cache_savings:.0f}% of loads.")
    return "\n".join(lines) + "\n"


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
              profile: bool = False,
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
    used_default_workdir = not workdir
    workdir = workdir or (PROJECT_ROOT / "tmp" / f"backfill_{suffix}")
    if used_default_workdir:
        # Housekeeping at the source: prune accumulated old tmp/backfill_* before
        # creating this run's workdir (skipped when an explicit --workdir is given).
        _pruned = _prune_old_backfill_workdirs(PROJECT_ROOT / "tmp")
        if _pruned:
            _log(f"housekeeping: pruned {_pruned} tmp/backfill_* workdir(s) older "
                 f"than {BACKFILL_RETENTION_DAYS}d")
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
                _compute_one(as_of_iso, tf, workdir_str, profile)
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
                pool.submit(_compute_one, as_of_iso, tf, workdir_str, profile):
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

    if profile:
        report_md = _aggregate_timings(workdir)
        perf_dir = PROJECT_ROOT / "outputs" / "perf"
        perf_dir.mkdir(parents=True, exist_ok=True)
        report_path = perf_dir / f"bc_timing_{suffix}.md"
        report_path.write_text(report_md, encoding="utf-8")
        _log(f"PROFILE  report written to {report_path}")

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
    p.add_argument("--profile", action="store_true",
                   help="Instrument workers to capture per-task span timings, "
                        "tasks-per-worker distribution, and (symbol, tf) "
                        "load-count census. Emits Markdown report to "
                        "outputs/perf/bc_timing_<UTC_TS>.md. Zero behavior "
                        "change otherwise (monkey-patch restored in finally).")
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
            profile=args.profile,
        )
    except SchedulerStillEnabledError as exc:
        _log(f"FATAL  {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
