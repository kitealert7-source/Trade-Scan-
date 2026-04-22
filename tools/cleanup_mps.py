"""
cleanup_mps.py -- Remove stale row(s) from Master_Portfolio_Sheet.xlsx by portfolio_id.

Recovery tool for F04 (IDEMPOTENT_OVERWRITE_LOCK). Human-initiated only.

Usage:
    python tools/cleanup_mps.py --portfolio-id <ID>              # preview only (default)
    python tools/cleanup_mps.py --portfolio-id <ID> --dry-run    # preview only (explicit)
    python tools/cleanup_mps.py --portfolio-id <ID> --confirm    # mutate

Safety contract:
    - Default (no --confirm) = preview-only. Shows row count + sample per sheet, exits WITHOUT writing.
    - --confirm is REQUIRED to mutate. --dry-run and --confirm are mutually exclusive.
    - Writes timestamped .xlsx.bak.<UTC> backup before mutating.
    - Preserves ALL sheets (Portfolios, Single-Asset, Notes, etc.).
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.state_paths import STRATEGIES_DIR

MPS_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"

_PREVIEW_COLS = ["portfolio_id", "deployed_profile", "portfolio_status", "realized_pnl"]
_SAMPLE_N = 5


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove stale portfolio_id rows from Master_Portfolio_Sheet.xlsx (F04 recovery)."
    )
    parser.add_argument(
        "--portfolio-id",
        required=True,
        help="Portfolio ID to drop (e.g. P001)",
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
        print("[cleanup_mps][ERROR] --dry-run and --confirm are mutually exclusive.", file=sys.stderr)
        return 2

    path = MPS_PATH
    if not path.exists():
        print(f"[cleanup_mps][ERROR] MPS not found: {path}", file=sys.stderr)
        return 1

    xf = pd.ExcelFile(path)
    sheets: dict[str, pd.DataFrame] = {}
    total_dropped = 0

    print(f"[cleanup_mps] Path         : {path}")
    print(f"[cleanup_mps] Portfolio ID : {args.portfolio_id}")

    for name in xf.sheet_names:
        df = pd.read_excel(path, sheet_name=name)
        if "portfolio_id" in df.columns:
            mask = df["portfolio_id"].astype(str) == args.portfolio_id
            n = int(mask.sum())
            if n:
                print(f"[cleanup_mps] Sheet '{name}': {n} row(s) to drop")
                preview_cols = [c for c in _PREVIEW_COLS if c in df.columns]
                sample = df.loc[mask, preview_cols].head(_SAMPLE_N)
                print(f"[cleanup_mps] Sample (first {_SAMPLE_N} of {n}):")
                print(sample.to_string(index=False))
                total_dropped += n
                df = df[~mask]
        sheets[name] = df

    print(f"[cleanup_mps] Total drop   : {total_dropped}")

    if total_dropped == 0:
        print("[cleanup_mps] Nothing to do.")
        return 0

    if not args.confirm:
        reason = "DRY RUN" if args.dry_run else "NO --confirm"
        print(f"[cleanup_mps] {reason} -- no changes written. Re-run with --confirm to mutate.")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(f".xlsx.bak.{ts}")
    shutil.copy(path, backup)
    print(f"[cleanup_mps] Backup       : {backup}")

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    print(f"[cleanup_mps] Wrote        : {len(sheets)} sheet(s) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
