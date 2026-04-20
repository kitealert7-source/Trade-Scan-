"""
backfill_run_index.py — One-time backfill of research/index.csv with legacy runs.

Scans BACKTESTS_DIR for all completed Stage-1 folders that pre-date the provenance
patch (schema_version < 1.3.0). Appends one row per valid folder to index.csv.

STRICT RULES:
  - Read-only scan of BACKTESTS_DIR (zero modifications to any existing file)
  - Append-only write to index.csv
  - Does NOT recompute anything
  - Does NOT guess missing fields — leaves them empty
  - Skips PF_* portfolio folders (broken, no metadata)
  - Skips any folder missing the three required files
  - content_hash = "" (do not propagate even if present — legacy runs untrusted)
  - git_commit   = "" (not capturable retroactively)
  - schema_version = "legacy" (key identifier for pre-patch rows)

Run once from Trade_Scan root:
    python tools/backfill_run_index.py [--dry-run]

Output:
    TradeScan_State/research/index.csv  (appended)
    Console summary: scanned / appended / skipped counts
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap path so config.state_paths is importable when run from repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).resolve().parent          # tools/
PROJECT_ROOT = SCRIPT_DIR.parent                       # Trade_Scan/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import BACKTESTS_DIR, STATE_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Constants — must stay in sync with run_index.py
# ---------------------------------------------------------------------------
INDEX_PATH = STATE_ROOT / "research" / "index.csv"
INDEX_FIELDS = [
    "run_id", "strategy_id", "symbol", "timeframe",
    "date_start", "date_end",
    "profit_factor", "max_drawdown_pct", "net_pnl_usd", "total_trades",
    "win_rate", "content_hash", "git_commit", "execution_timestamp_utc",
    "schema_version",
]

try:
    from filelock import FileLock as _FileLock
    _HAVE_FILELOCK = True
except ImportError:
    _HAVE_FILELOCK = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_symbol_suffix(folder_name: str, symbol: str) -> str:
    """Return strategy_id by stripping trailing _{symbol} from folder name."""
    suffix = f"_{symbol}"
    if folder_name.endswith(suffix):
        return folder_name[: -len(suffix)]
    # Fallback — symbol not found as suffix; return folder name as-is
    return folder_name


def _already_indexed(run_id: str) -> bool:
    """Return True if run_id already present in index.csv (duplicate guard)."""
    if not INDEX_PATH.exists():
        return False
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("run_id") == run_id:
                    return True
    except Exception:
        pass
    return False


def _append_row(row: dict, dry_run: bool) -> None:
    """Append one row to index.csv using FileLock if available."""
    if dry_run:
        return  # nothing written in dry-run mode

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    if _HAVE_FILELOCK:
        lock = _FileLock(str(INDEX_PATH) + ".lock", timeout=30)
        with lock:
            write_header = not INDEX_PATH.exists()
            with open(INDEX_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
    else:
        write_header = not INDEX_PATH.exists()
        with open(INDEX_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Main backfill loop
# ---------------------------------------------------------------------------

def backfill(dry_run: bool = False) -> None:
    if not BACKTESTS_DIR.exists():
        print(f"[BACKFILL] BACKTESTS_DIR not found: {BACKTESTS_DIR}")
        sys.exit(1)

    folders = sorted(BACKTESTS_DIR.iterdir())

    n_scanned  = 0
    n_appended = 0
    n_skipped_pf      = 0
    n_skipped_missing = 0
    n_skipped_empty   = 0
    n_skipped_dup     = 0
    n_skipped_new     = 0   # already post-patch (schema_version = 1.3.0)
    n_errors   = 0

    for folder in folders:
        if not folder.is_dir():
            continue

        n_scanned += 1
        name = folder.name

        # --- Skip PF_ portfolio folders ---
        if name.startswith("PF_"):
            n_skipped_pf += 1
            continue

        # --- Required files ---
        meta_path = folder / "metadata" / "run_metadata.json"
        std_path  = folder / "raw" / "results_standard.csv"
        risk_path = folder / "raw" / "results_risk.csv"

        if not meta_path.exists() or not std_path.exists() or not risk_path.exists():
            print(f"[BACKFILL] Skip (missing files): {name}")
            n_skipped_missing += 1
            continue

        try:
            meta      = json.loads(meta_path.read_text(encoding="utf-8"))
            std_rows  = list(csv.DictReader(std_path.open(encoding="utf-8")))
            risk_rows = list(csv.DictReader(risk_path.open(encoding="utf-8")))
        except Exception as e:
            print(f"[BACKFILL] Error reading {name}: {e}")
            n_errors += 1
            continue

        if not std_rows or not risk_rows:
            print(f"[BACKFILL] Skip (empty results): {name}")
            n_skipped_empty += 1
            continue

        # --- Skip post-patch runs (already captured by live pipeline) ---
        if meta.get("schema_version") == "1.3.0":
            n_skipped_new += 1
            continue

        # --- Extract symbol and strategy_id ---
        symbol      = meta.get("symbol", "")
        strategy_id = _strip_symbol_suffix(name, symbol)

        # --- Duplicate guard ---
        run_id = meta.get("run_id", "")
        if run_id and _already_indexed(run_id):
            n_skipped_dup += 1
            continue

        s = std_rows[0]
        r = risk_rows[0]

        row = {
            "run_id":                  run_id,
            "strategy_id":             strategy_id,
            "symbol":                  symbol,
            "timeframe":               meta.get("timeframe", ""),
            "date_start":              meta.get("date_range", {}).get("start", ""),
            "date_end":                meta.get("date_range", {}).get("end", ""),
            "profit_factor":           s.get("profit_factor", ""),
            "max_drawdown_pct":        r.get("max_drawdown_pct", ""),
            "net_pnl_usd":             s.get("net_pnl_usd", ""),
            "total_trades":            s.get("trade_count", ""),
            "win_rate":                s.get("win_rate", ""),
            "content_hash":            "",   # intentionally blank — legacy runs
            "git_commit":              "",   # not capturable retroactively
            "execution_timestamp_utc": meta.get("execution_timestamp_utc", ""),
            "schema_version":          "legacy",
        }

        if dry_run:
            print(f"[DRY-RUN] Would append: {strategy_id} / {symbol}  PF={row['profit_factor']}  DD={row['max_drawdown_pct']}")
        else:
            _append_row(row, dry_run=False)
            print(f"[BACKFILL] Appended: {strategy_id} / {symbol}")

        n_appended += 1

    # --- Summary ---
    print()
    print("=" * 60)
    print(f"  Backfill {'DRY-RUN ' if dry_run else ''}complete")
    print(f"  Folders scanned : {n_scanned}")
    print(f"  Rows appended   : {n_appended}")
    print(f"  Skipped PF_*    : {n_skipped_pf}")
    print(f"  Skipped missing : {n_skipped_missing}")
    print(f"  Skipped empty   : {n_skipped_empty}")
    print(f"  Skipped dup     : {n_skipped_dup}")
    print(f"  Skipped new(1.3): {n_skipped_new}")
    print(f"  Errors          : {n_errors}")
    print("=" * 60)

    if not dry_run and n_appended > 0:
        # Verify row count in file
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            print(f"\n  index.csv now contains {len(rows)} data rows.")
            # Spot-check: count legacy rows
            legacy = [r for r in rows if r.get("schema_version") == "legacy"]
            new    = [r for r in rows if r.get("schema_version") == "1.3.0"]
            print(f"  schema_version='legacy' : {len(legacy)}")
            print(f"  schema_version='1.3.0'  : {len(new)}")
            print(f"  other / blank           : {len(rows) - len(legacy) - len(new)}")
        except Exception as e:
            print(f"  [WARN] Could not verify index.csv: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="One-time backfill of research/index.csv with legacy Stage-1 runs."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be appended without writing anything."
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
