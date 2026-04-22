"""
cleanup_ledger.py -- Remove stale rows from Strategy_Master_Filter.xlsx by strategy_id prefix.

Recovery tool for F03 (ORPHANED_LEDGER_STAGE3). Human-initiated only.

Usage:
    python tools/cleanup_ledger.py --strategy-id <ID>              # preview only (default)
    python tools/cleanup_ledger.py --strategy-id <ID> --dry-run    # preview only (explicit)
    python tools/cleanup_ledger.py --strategy-id <ID> --confirm    # mutate

Safety contract:
    - Default (no --confirm) = preview-only. Shows row count + sample, exits WITHOUT writing.
    - --confirm is REQUIRED to mutate. --dry-run and --confirm are mutually exclusive.
    - Writes timestamped .xlsx.bak.<UTC> backup before mutating.
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.state_paths import MASTER_FILTER_PATH

_PREVIEW_COLS = ["run_id", "strategy", "symbol"]
_SAMPLE_N = 5


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove stale rows from Strategy_Master_Filter.xlsx by strategy_id prefix (F03 recovery)."
    )
    parser.add_argument(
        "--strategy-id",
        required=True,
        help="Strategy ID prefix to drop (e.g. 23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only (explicit). Default behavior without --confirm.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to mutate. Mutually exclusive with --dry-run.",
    )
    args = parser.parse_args()

    if args.dry_run and args.confirm:
        print("[cleanup_ledger][ERROR] --dry-run and --confirm are mutually exclusive.", file=sys.stderr)
        return 2

    path = MASTER_FILTER_PATH
    if not path.exists():
        print(f"[cleanup_ledger][ERROR] Master Filter not found: {path}", file=sys.stderr)
        return 1

    df = pd.read_excel(path)
    if "strategy" not in df.columns:
        print(f"[cleanup_ledger][ERROR] 'strategy' column missing in {path}", file=sys.stderr)
        return 1

    mask = df["strategy"].astype(str).str.startswith(args.strategy_id)
    to_drop = int(mask.sum())

    print(f"[cleanup_ledger] Path         : {path}")
    print(f"[cleanup_ledger] Strategy ID  : {args.strategy_id}")
    print(f"[cleanup_ledger] Total rows   : {len(df)}")
    print(f"[cleanup_ledger] Rows to drop : {to_drop}")

    if to_drop == 0:
        print("[cleanup_ledger] Nothing to do.")
        return 0

    # Always print sample preview before acting
    preview_cols = [c for c in _PREVIEW_COLS if c in df.columns]
    sample = df.loc[mask, preview_cols].head(_SAMPLE_N)
    print(f"[cleanup_ledger] Sample preview (first {_SAMPLE_N} of {to_drop}):")
    print(sample.to_string(index=False))

    if not args.confirm:
        reason = "DRY RUN" if args.dry_run else "NO --confirm"
        print(f"[cleanup_ledger] {reason} -- no changes written. Re-run with --confirm to mutate.")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(f".xlsx.bak.{ts}")
    shutil.copy(path, backup)
    print(f"[cleanup_ledger] Backup       : {backup}")

    cleaned = df[~mask]
    cleaned.to_excel(path, index=False)
    print(f"[cleanup_ledger] Wrote        : {len(cleaned)} rows -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
