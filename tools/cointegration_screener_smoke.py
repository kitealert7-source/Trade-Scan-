"""cointegration_screener_smoke.py — Phase 0a end-to-end I/O probe.

Proves the production execution context can complete one full
read-compute-write-cleanup cycle for the cointegration screener WITHOUT
running any actual cointegration math. Run this from a scheduled task
under the intended run-as identity BEFORE the real compute code lands.

Per COINTEGRATION_SCREENER_V1_SPEC.md §10 Phase 0a:
  1. Read one 1d year-file from each of the 18 symbols' RESEARCH dirs
     (proves MASTER_DATA read access under current identity).
  2. Write a 1-row dummy parquet to
     DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/_smoke.parquet
     (proves SYSTEM_FACTORS write access).
  3. Open DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db, upsert 1 row,
     query it back (proves SQLite full roundtrip + dir creation).
  4. Delete the dummy parquet AND drop the _smoke SQLite table.
  5. Exit 0 on success; non-zero on any failure.

Exit codes (binary pass/fail — no human interpretation):
  0   PASS  — all steps succeeded
  10  FAIL  — MASTER_DATA read denied (PermissionError)
  11  FAIL  — at least one symbol's RESEARCH dir or 1d file missing
  12  FAIL  — parquet write failed (SYSTEM_FACTORS write access)
  13  FAIL  — SQLite open/write/read roundtrip failed
  14  FAIL  — cleanup (file or table drop) failed
  20  FAIL  — unexpected uncaught exception (see tmp/cointegration_smoke.log)

Result log: tmp/cointegration_smoke.log (UTF-8, append-only).

Usage (interactive — will FAIL on MASTER_DATA read; that's the point):
    python tools/cointegration_screener_smoke.py

Usage (scheduled task — should PASS under faraw + RunLevel=Highest,
matching the TradeScan NAS Backup task pattern):
    Register a one-shot task with elevated privileges and have it run
    this script. Inspect tmp/cointegration_smoke.log for the result.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.path_authority import DATA_ROOT


UNIVERSE = [
    "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD",
    "USDCAD", "USDCHF", "USDJPY",
    "AUDJPY", "AUDNZD", "CADJPY", "CHFJPY",
    "EURAUD", "EURGBP", "EURJPY",
    "GBPAUD", "GBPJPY", "GBPNZD", "NZDJPY",
]

# All three SYSTEM_FACTORS/FX_COINTEGRATION/ artifacts co-located
# (parquet + SQLite + Excel) — see cointegration_db.py for the
# 2026-05-20 location-move rationale.
PARQUET_OUT = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / "_smoke.parquet"
SQLITE_DB   = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / "cointegration.db"
LOG_FILE    = PROJECT_ROOT / "tmp" / "cointegration_smoke.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} | {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _step_1_read_master_data() -> int:
    """Read a few rows of a 1d file per symbol. Proves ACL allows read."""
    missing: list[str] = []
    read_errors: list[str] = []
    for sym in UNIVERSE:
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        if not research.is_dir():
            missing.append(f"{sym} (dir)")
            continue
        candidates = sorted(research.glob(f"{sym}_OCTAFX_1d_*_RESEARCH.csv"))
        if not candidates:
            missing.append(f"{sym} (no 1d files)")
            continue
        try:
            df = pd.read_csv(candidates[-1], comment="#", nrows=5)
            if df.empty:
                read_errors.append(f"{sym}: empty df from {candidates[-1].name}")
        except PermissionError as exc:
            _log(f"FAIL READ_DENIED {sym} -> {candidates[-1]}: {exc}")
            return 10
        except Exception as exc:
            read_errors.append(f"{sym}: {type(exc).__name__}: {exc}")
    if missing:
        _log(f"FAIL MISSING: {missing}")
        return 11
    if read_errors:
        _log(f"FAIL READ_ERRORS: {read_errors}")
        return 11
    _log(f"OK STEP_1 read {len(UNIVERSE)} symbols' 1d files")
    return 0


def _step_2_write_parquet() -> int:
    """Write a 1-row dummy parquet to SYSTEM_FACTORS/FX_COINTEGRATION/."""
    try:
        PARQUET_OUT.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([{
            "pair_a": "EURUSD",
            "pair_b": "USDJPY",
            "smoke": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }])
        df.to_parquet(PARQUET_OUT, index=False)
        _log(f"OK STEP_2 wrote {PARQUET_OUT}")
        return 0
    except Exception as exc:
        _log(f"FAIL PARQUET_WRITE: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 12


def _step_3_sqlite_roundtrip() -> int:
    """Open DB, create _smoke table, upsert 1 row, read it back."""
    try:
        SQLITE_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(SQLITE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS _smoke (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                inserted_at TEXT NOT NULL
            )
        """)
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT OR REPLACE INTO _smoke (key, value, inserted_at) VALUES (?, ?, ?)",
            ("phase0a_probe", "ok", now),
        )
        conn.commit()
        cur.execute("SELECT value FROM _smoke WHERE key = ?", ("phase0a_probe",))
        row = cur.fetchone()
        if row is None or row["value"] != "ok":
            _log(f"FAIL SQLITE_ROUNDTRIP value mismatch: {dict(row) if row else None}")
            conn.close()
            return 13
        conn.close()
        _log(f"OK STEP_3 sqlite roundtrip at {SQLITE_DB}")
        return 0
    except Exception as exc:
        _log(f"FAIL SQLITE: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 13


def _step_4_cleanup() -> int:
    """Delete dummy parquet + drop the _smoke SQLite table."""
    try:
        if PARQUET_OUT.exists():
            PARQUET_OUT.unlink()
        conn = sqlite3.connect(str(SQLITE_DB))
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS _smoke")
        conn.commit()
        conn.close()
        _log("OK STEP_4 cleanup complete")
        return 0
    except Exception as exc:
        _log(f"FAIL CLEANUP: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 14


def main() -> int:
    _log("=" * 60)
    _log("START Phase 0a smoke probe")
    _log(f"identity: pid={os.getpid()} user={os.environ.get('USERNAME', '?')}")
    _log(f"cwd: {os.getcwd()}")
    _log(f"data_root: {DATA_ROOT}")

    for step_fn in (
        _step_1_read_master_data,
        _step_2_write_parquet,
        _step_3_sqlite_roundtrip,
        _step_4_cleanup,
    ):
        rc = step_fn()
        if rc != 0:
            _log(f"ABORT exit_code={rc}")
            return rc

    _log("PASS Phase 0a all steps succeeded")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        _log(f"FAIL UNCAUGHT: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        exit_code = 20
    raise SystemExit(exit_code)
