"""
backfill_ledger_db.py — One-time import of existing Excel ledgers into SQLite.

Reads the current Master Filter and MPS Excel files and inserts all rows
into the ledger.db SQLite database.  Safe to re-run (uses INSERT OR REPLACE).

Usage:
  python tools/backfill_ledger_db.py              # backfill both
  python tools/backfill_ledger_db.py --dry-run     # report counts only
  python tools/backfill_ledger_db.py --verify      # backfill + verify round-trip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import MASTER_FILTER_PATH, STRATEGIES_DIR, LEDGER_DB_PATH
from tools.ledger_db import (
    _connect, create_tables,
    upsert_master_filter_df, upsert_mps_df,
    query_master_filter, query_mps,
)

MPS_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"


def backfill(dry_run: bool = False, verify: bool = False) -> int:
    """Import Excel ledgers into SQLite. Returns 0 on success."""

    # --- Load Excel ---
    print(f"  [READ] Master Filter: {MASTER_FILTER_PATH}")
    mf_df = pd.read_excel(str(MASTER_FILTER_PATH), engine="openpyxl")
    print(f"         {len(mf_df)} rows, {len(mf_df.columns)} columns")

    print(f"  [READ] MPS: {MPS_PATH}")
    xl = pd.ExcelFile(str(MPS_PATH), engine="openpyxl")
    mps_port = xl.parse("Portfolios")
    mps_single = xl.parse("Single-Asset Composites")
    print(f"         Portfolios: {len(mps_port)} rows")
    print(f"         Single-Asset Composites: {len(mps_single)} rows")

    if dry_run:
        print("\n  [DRY RUN] Would insert:")
        print(f"    master_filter:    {len(mf_df)} rows")
        print(f"    portfolio_sheet:  {len(mps_port) + len(mps_single)} rows")
        return 0

    # --- Write to SQLite ---
    print(f"\n  [WRITE] Target: {LEDGER_DB_PATH}")
    conn = _connect()
    create_tables(conn)

    print("  [BACKFILL] Master Filter...")
    upsert_master_filter_df(conn, mf_df)
    print(f"             {len(mf_df)} rows inserted")

    print("  [BACKFILL] MPS Portfolios...")
    upsert_mps_df(conn, mps_port, sheet="Portfolios")
    print(f"             {len(mps_port)} rows inserted")

    print("  [BACKFILL] MPS Single-Asset Composites...")
    upsert_mps_df(conn, mps_single, sheet="Single-Asset Composites")
    print(f"             {len(mps_single)} rows inserted")

    # --- Verify ---
    if verify:
        print("\n  [VERIFY] Round-trip check...")
        # Diagnostic/backfill: compare against full DB history, not just live rows.
        db_mf = query_master_filter(conn, include_superseded=True)
        db_port = query_mps(conn, sheet="Portfolios", include_superseded=True)
        db_single = query_mps(conn, sheet="Single-Asset Composites", include_superseded=True)

        ok = True
        if len(db_mf) != len(mf_df):
            print(f"    MISMATCH master_filter: Excel={len(mf_df)}, DB={len(db_mf)}")
            ok = False
        else:
            print(f"    master_filter:    {len(db_mf)} rows  OK")

        if len(db_port) != len(mps_port):
            print(f"    MISMATCH Portfolios: Excel={len(mps_port)}, DB={len(db_port)}")
            ok = False
        else:
            print(f"    Portfolios:       {len(db_port)} rows  OK")

        if len(db_single) != len(mps_single):
            print(f"    MISMATCH Single-Asset: Excel={len(mps_single)}, DB={len(db_single)}")
            ok = False
        else:
            print(f"    Single-Asset:     {len(db_single)} rows  OK")

        if not ok:
            print("\n  [VERIFY] FAILED — row count mismatch")
            conn.close()
            return 1
        print("  [VERIFY] All counts match")

    conn.close()
    print("\n  [DONE] Backfill complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ledger.db from Excel")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts only, don't write")
    parser.add_argument("--verify", action="store_true",
                        help="Verify round-trip after backfill")
    args = parser.parse_args()
    return backfill(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
