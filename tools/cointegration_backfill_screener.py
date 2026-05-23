"""cointegration_backfill_screener.py — retrospective daily-snapshot fill.

Replays the cointegration screener for every business day in a window
(default: today - 1 year through today), writing one as_of snapshot per
iteration to SQLite. Each iteration is methodologically equivalent to
what the screener WOULD have computed on that date — the underlying
`run(as_of=...)` truncates input data to bars ≤ as_of, so no look-ahead.

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
    python tools/cointegration_backfill_screener.py                # default: 1y back
    python tools/cointegration_backfill_screener.py --years 2      # 2y back
    python tools/cointegration_backfill_screener.py --start 2025-01-01
    python tools/cointegration_backfill_screener.py --dry-run      # plan only
    python tools/cointegration_backfill_screener.py --skip-backup  # advanced
"""
from __future__ import annotations

import argparse
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
    PARQUET_PATH, SINGLES_PARQUET_PATH,
    run, run_singles, write_parquet, write_singles_parquet,
)


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}",
          flush=True)


def _backup_tables(conn, suffix: str) -> None:
    """Snapshot cointegration_daily and singles_daily to backup tables.

    The backup tables are named <table>_backup_<suffix>. If a previous
    backup with the same suffix exists, it's dropped first.
    """
    for tbl in (TABLE_NAME, SINGLES_TABLE_NAME, TRIGGERS_TABLE_NAME):
        # Check table exists first; TRIGGERS_TABLE_NAME may not on old DBs
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
    """Wipe cointegration_daily, singles_daily, cointegration_triggers."""
    for tbl in (TABLE_NAME, SINGLES_TABLE_NAME, TRIGGERS_TABLE_NAME):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()
    _log(f"  truncated {TABLE_NAME}, {SINGLES_TABLE_NAME}, "
         f"{TRIGGERS_TABLE_NAME}")


def backfill(start_date: pd.Timestamp, end_date: pd.Timestamp,
              *, do_backup: bool = True, dry_run: bool = False) -> None:
    """Run the screener for every business day in [start_date, end_date]."""
    dates = pd.bdate_range(start_date, end_date)
    _log(f"backfill plan: {len(dates)} business days from "
         f"{dates[0].date()} → {dates[-1].date()}")

    if dry_run:
        _log("--dry-run: no compute, no DB writes")
        return

    conn = connect()
    create_tables(conn)

    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if do_backup:
        _log(f"backing up existing tables (suffix _backup_{suffix})...")
        _backup_tables(conn, suffix)

    _log("truncating live tables (backups preserved for rollback)...")
    _truncate_tables(conn)

    t_start = time.time()
    n_fail = 0

    for i, as_of in enumerate(dates, start=1):
        try:
            as_of_str = as_of.strftime("%Y-%m-%d")
            df = run(as_of=as_of)
            write_parquet(df)
            n_pair = upsert_from_parquet(conn, PARQUET_PATH)

            df_singles = run_singles(
                as_of=as_of,
                synthetic_specs=[("BTCUSD", "ETHUSD")],
            )
            write_singles_parquet(df_singles)
            n_sing = upsert_singles_from_parquet(conn, SINGLES_PARQUET_PATH)

            if i == 1 or i % 25 == 0 or i == len(dates):
                elapsed = time.time() - t_start
                avg = elapsed / i
                eta = avg * (len(dates) - i)
                _log(f"  [{i:3d}/{len(dates)}]  as_of={as_of_str}  "
                     f"pair={n_pair} sing={n_sing}  elapsed={elapsed:.0f}s  "
                     f"eta≈{eta:.0f}s")
        except Exception as exc:
            n_fail += 1
            _log(f"  [{i:3d}/{len(dates)}]  as_of={as_of_str}  FAIL: "
                 f"{type(exc).__name__}: {exc}")
            if n_fail >= 5:
                _log("ABORT: 5+ consecutive failures, aborting backfill")
                raise

    _log(f"compute complete in {time.time() - t_start:.0f}s "
         f"({n_fail} failures)")

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
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan only; no compute or DB writes.")
    p.add_argument("--skip-backup", action="store_true",
                   help="Skip the backup-tables step (advanced; loses rollback).")
    args = p.parse_args(argv)

    end_date = pd.Timestamp(args.end) if args.end else pd.Timestamp.utcnow().normalize()
    if args.start:
        start_date = pd.Timestamp(args.start)
    else:
        start_date = end_date - pd.Timedelta(days=int(args.years * 365))

    backfill(start_date, end_date,
              do_backup=not args.skip_backup, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
