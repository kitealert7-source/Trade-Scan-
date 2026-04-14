"""
configure_portfolio.py — Set IN_PORTFOLIO flags via ledger.db.

Uses set_in_portfolio() from ledger_db — the single authoritative writer.
Excel is regenerated as a derived view after DB update.

Usage:
    python tools/configure_portfolio.py --add <run_id> [<run_id> ...]
    python tools/configure_portfolio.py --list
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.ledger_db import (
    _connect, create_tables, set_in_portfolio,
    export_master_filter, read_master_filter,
)


def cmd_add(run_ids: list[str]) -> None:
    """Add run_ids to IN_PORTFOLIO (union with existing)."""
    conn = _connect()
    create_tables(conn)
    existing = {
        r[0] for r in conn.execute(
            'SELECT run_id FROM master_filter WHERE "IN_PORTFOLIO" = 1'
        ).fetchall()
    }
    conn.close()

    new_ids = set(run_ids) - existing
    if not new_ids:
        print(f"[SKIP] All {len(run_ids)} run_id(s) already IN_PORTFOLIO.")
        return

    combined = existing | set(run_ids)
    synced = set_in_portfolio(combined)
    print(f"[OK] IN_PORTFOLIO: {synced} run_id(s) flagged ({len(new_ids)} added).")
    for rid in sorted(new_ids):
        print(f"  + {rid}")

    export_master_filter()


def cmd_list() -> None:
    """List current IN_PORTFOLIO run_ids from DB."""
    df = read_master_filter()
    if df.empty:
        print("[LIST] Master Filter is empty.")
        return
    in_port = df[df["IN_PORTFOLIO"] == 1]
    if in_port.empty:
        print("[LIST] No IN_PORTFOLIO flags set.")
        return
    print(f"[LIST] {len(in_port)} IN_PORTFOLIO run_id(s):")
    for _, row in in_port.iterrows():
        label = row.get("strategy", row["run_id"])
        print(f"  {row['run_id']}  {label}  ({row.get('symbol', '?')})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure IN_PORTFOLIO flags via DB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", nargs="+", metavar="RUN_ID",
                       help="Add run_id(s) to IN_PORTFOLIO")
    group.add_argument("--list", action="store_true",
                       help="List current IN_PORTFOLIO run_ids")
    args = parser.parse_args()

    if args.add:
        cmd_add(args.add)
    elif args.list:
        cmd_list()


if __name__ == "__main__":
    main()
