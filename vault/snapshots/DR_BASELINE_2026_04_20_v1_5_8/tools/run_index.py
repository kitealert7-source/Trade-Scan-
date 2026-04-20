"""
run_index.py — Append-only global run index.

Writes one row per completed Stage-1 run to TradeScan_State/research/index.csv.
Failure is non-blocking — never raises to caller.
Uses FileLock to prevent corruption under parallel directive runs.
"""
import csv
import json
from pathlib import Path

from config.state_paths import BACKTESTS_DIR, STATE_ROOT

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


def append_run_to_index(strategy_id: str, symbol: str) -> None:
    """Append one row to the global index. Non-blocking — all errors are caught."""
    try:
        folder = BACKTESTS_DIR / f"{strategy_id}_{symbol}"
        meta_path = folder / "metadata" / "run_metadata.json"
        std_path  = folder / "raw" / "results_standard.csv"
        risk_path = folder / "raw" / "results_risk.csv"

        if not meta_path.exists() or not std_path.exists() or not risk_path.exists():
            print(f"[INDEX] Skipping {strategy_id}_{symbol} — required files missing")
            return

        meta      = json.loads(meta_path.read_text(encoding="utf-8"))
        std_rows  = list(csv.DictReader(std_path.open(encoding="utf-8")))
        risk_rows = list(csv.DictReader(risk_path.open(encoding="utf-8")))

        if not std_rows or not risk_rows:
            print(f"[INDEX] Skipping {strategy_id}_{symbol} — empty result files")
            return

        s = std_rows[0]
        r = risk_rows[0]

        row = {
            "run_id":                  meta.get("run_id", ""),
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
            "content_hash":            meta.get("content_hash", ""),
            "git_commit":              meta.get("git_commit", ""),
            "execution_timestamp_utc": meta.get("execution_timestamp_utc", ""),
            "schema_version":          meta.get("schema_version", "1.3.0"),
        }

        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

        if _HAVE_FILELOCK:
            lock = _FileLock(str(INDEX_PATH) + ".lock", timeout=30)
            with lock:
                write_header = not INDEX_PATH.exists()  # check INSIDE lock
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

    except Exception as e:
        print(f"[INDEX] Non-blocking write failure for {strategy_id}_{symbol}: {e}")
