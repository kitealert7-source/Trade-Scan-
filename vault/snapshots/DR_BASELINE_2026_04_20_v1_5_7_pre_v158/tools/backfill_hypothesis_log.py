"""
backfill_hypothesis_log.py — Reconstruct hypothesis_log.json from backtest results.

For each sweep (S01, S02, ...) that has both a P00 baseline and later passes
(P01, P02, ...), generates a hypothesis entry by comparing metrics.

Data sources:
  - TradeScan_State/backtests/<strategy_Pxx_SYMBOL>/raw/results_standard.csv
  - TradeScan_State/backtests/<strategy_Pxx_SYMBOL>/raw/results_risk.csv

Output:
  - TradeScan_State/hypothesis_log.json (merges with existing entries)

Usage:
  python tools/backfill_hypothesis_log.py --dry-run   # preview only
  python tools/backfill_hypothesis_log.py              # write to file
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import STATE_ROOT

BACKTESTS_DIR = STATE_ROOT / "backtests"
HYPOTHESIS_LOG_PATH = STATE_ROOT / "hypothesis_log.json"

PASS_RE = re.compile(r"^(.+?)_P(\d{2})$")
FOLDER_RE = re.compile(r"^(.+?_P\d{2})_([A-Z]{3,}[A-Z0-9]*)$")


def _load_existing() -> list[dict]:
    """Load existing hypothesis_log.json entries."""
    if not HYPOTHESIS_LOG_PATH.exists():
        return []
    try:
        with open(HYPOTHESIS_LOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _read_metrics(folder: Path) -> dict | None:
    """Read results_standard.csv + results_risk.csv from a backtest folder."""
    std_path = folder / "raw" / "results_standard.csv"
    risk_path = folder / "raw" / "results_risk.csv"
    if not std_path.exists() or not risk_path.exists():
        return None
    try:
        std = list(csv.DictReader(open(std_path, encoding="utf-8")))
        risk = list(csv.DictReader(open(risk_path, encoding="utf-8")))
        if not std or not risk:
            return None
        s, r = std[0], risk[0]
        return {
            "profit_factor": _f(s.get("profit_factor")),
            "trade_count": _i(s.get("trade_count")),
            "net_pnl_usd": _f(s.get("net_pnl_usd")),
            "win_rate": _f(s.get("win_rate")),
            "sharpe_ratio": _f(r.get("sharpe_ratio")),
            "max_drawdown_pct": _f(r.get("max_drawdown_pct")),
            "sqn": _f(r.get("sqn")),
        }
    except Exception:
        return None


def _f(v) -> float:
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _aggregate(metrics_list: list[dict]) -> dict:
    """Average metrics across symbols for a single pass."""
    n = len(metrics_list)
    if n == 0:
        return {}
    return {
        "profit_factor": round(sum(m["profit_factor"] for m in metrics_list) / n, 4),
        "trade_count": sum(m["trade_count"] for m in metrics_list),
        "net_pnl_usd": round(sum(m["net_pnl_usd"] for m in metrics_list), 2),
        "win_rate": round(sum(m["win_rate"] for m in metrics_list) / n, 4),
        "sharpe_ratio": round(sum(m["sharpe_ratio"] for m in metrics_list) / n, 4),
        "max_drawdown_pct": round(max(m["max_drawdown_pct"] for m in metrics_list), 4),
        "sqn": round(sum(m["sqn"] for m in metrics_list) / n, 4),
    }


def _compute_deltas(baseline: dict, result: dict) -> dict:
    """Compute metric deltas between baseline and pass result."""
    deltas = {}
    for key in ("profit_factor", "trade_count", "net_pnl_usd", "win_rate",
                "sharpe_ratio", "max_drawdown_pct", "sqn"):
        b = baseline.get(key, 0)
        r = result.get(key, 0)
        deltas[key] = round(r - b, 4)
    return deltas


def _classify_decision(baseline: dict, result: dict) -> tuple[str, str]:
    """Classify pass as ACCEPT/REJECT based on metric comparison.

    Simple heuristic:
      ACCEPT: PF not decreased AND (sharpe not decreased OR max_dd not increased)
      REJECT: PF decreased OR (sharpe decreased AND max_dd increased)
    """
    pf_ok = result.get("profit_factor", 0) >= baseline.get("profit_factor", 0) - 0.01
    sharpe_ok = result.get("sharpe_ratio", 0) >= baseline.get("sharpe_ratio", 0) - 0.05
    dd_ok = result.get("max_drawdown_pct", 0) <= baseline.get("max_drawdown_pct", 0) + 0.005

    b_trades = baseline.get("trade_count", 1) or 1
    retention = result.get("trade_count", 0) / b_trades * 100

    if pf_ok and (sharpe_ok or dd_ok) and retention >= 50:
        return "ACCEPT", ""
    else:
        reasons = []
        if not pf_ok:
            reasons.append(
                f"PF decreased ({baseline.get('profit_factor',0):.2f} -> "
                f"{result.get('profit_factor',0):.2f})")
        if not sharpe_ok:
            reasons.append(
                f"Sharpe decreased ({baseline.get('sharpe_ratio',0):.2f} -> "
                f"{result.get('sharpe_ratio',0):.2f})")
        if not dd_ok:
            reasons.append(
                f"MaxDD increased ({baseline.get('max_drawdown_pct',0):.2%} -> "
                f"{result.get('max_drawdown_pct',0):.2%})")
        if retention < 50:
            reasons.append(f"Trade retention too low ({retention:.0f}%)")
        return "REJECT", "; ".join(reasons)


def scan_backtests() -> list[dict]:
    """Scan backtest folders and build hypothesis entries for multi-pass sweeps."""
    if not BACKTESTS_DIR.exists():
        print(f"  BACKTESTS_DIR not found: {BACKTESTS_DIR}")
        return []

    # Index: sweep_base -> {(pass, symbol) -> metrics}
    sweep_data: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)

    for folder in BACKTESTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        m = FOLDER_RE.match(folder.name)
        if not m:
            continue
        strategy_with_pass = m.group(1)
        symbol = m.group(2)

        pm = PASS_RE.match(strategy_with_pass)
        if not pm:
            continue
        sweep_base = pm.group(1)
        pass_num = f"P{pm.group(2)}"

        metrics = _read_metrics(folder)
        if metrics:
            sweep_data[sweep_base][(pass_num, symbol)] = metrics

    # Build hypothesis entries for sweeps with P00 + later passes
    entries: list[dict] = []

    for sweep_base in sorted(sweep_data.keys()):
        pass_data = sweep_data[sweep_base]
        passes = sorted(set(p for p, _ in pass_data.keys()))
        symbols = sorted(set(s for _, s in pass_data.keys()))

        if "P00" not in passes or len(passes) <= 1:
            continue

        # Aggregate P00 baseline across symbols
        p00_metrics = [pass_data[(p, s)] for p, s in pass_data if p == "P00"]
        if not p00_metrics:
            continue
        baseline = _aggregate(p00_metrics)

        # Generate entry for each later pass
        for pass_num in passes:
            if pass_num == "P00":
                continue

            pass_metrics = [pass_data[(pass_num, s)]
                           for s in symbols if (pass_num, s) in pass_data]
            if not pass_metrics:
                continue

            result = _aggregate(pass_metrics)
            deltas = _compute_deltas(baseline, result)
            decision, reason = _classify_decision(baseline, result)

            b_trades = baseline.get("trade_count", 1) or 1
            retention = round(result.get("trade_count", 0) / b_trades * 100, 1)

            entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "strategy": f"{sweep_base}_P00",
                "pass_id": pass_num,
                "hypothesis_class": "parameter_sweep",
                "hypothesis": f"Pass {pass_num} vs P00 baseline ({len(pass_metrics)} symbols)",
                "baseline": {
                    "trades": baseline.get("trade_count", 0),
                    "pf": baseline.get("profit_factor", 0),
                    "sharpe": baseline.get("sharpe_ratio", 0),
                    "max_dd_pct": baseline.get("max_drawdown_pct", 0),
                    "net_pnl": baseline.get("net_pnl_usd", 0),
                },
                "result": {
                    "trades": result.get("trade_count", 0),
                    "pf": result.get("profit_factor", 0),
                    "sharpe": result.get("sharpe_ratio", 0),
                    "max_dd_pct": result.get("max_drawdown_pct", 0),
                    "net_pnl": result.get("net_pnl_usd", 0),
                },
                "deltas": {
                    "trades": deltas.get("trade_count", 0),
                    "pf": deltas.get("profit_factor", 0),
                    "sharpe": deltas.get("sharpe_ratio", 0),
                    "max_dd_pct": deltas.get("max_drawdown_pct", 0),
                },
                "trade_retention_pct": retention,
                "decision": decision,
                "rejection_reason": reason if reason else None,
                "source": "backfill",
            })

    return entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill hypothesis_log.json from backtest results"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview entries without writing")
    args = parser.parse_args()

    print("Scanning backtests for multi-pass sweeps...")
    new_entries = scan_backtests()

    if not new_entries:
        print("  No reconstructable entries found.")
        return 0

    # Load existing and find what's already there
    existing = _load_existing()
    existing_keys = set()
    for e in existing:
        key = (e.get("strategy", ""), e.get("pass_id", ""))
        existing_keys.add(key)

    # Filter out duplicates
    to_add = []
    for entry in new_entries:
        key = (entry["strategy"], entry["pass_id"])
        if key not in existing_keys:
            to_add.append(entry)

    # Summary
    decisions = defaultdict(int)
    for e in to_add:
        decisions[e["decision"]] += 1

    print(f"\n  Existing entries:        {len(existing)}")
    print(f"  New entries scanned:     {len(new_entries)}")
    print(f"  Already present (skip):  {len(new_entries) - len(to_add)}")
    print(f"  New entries to add:      {len(to_add)}")
    print(f"  Decisions: {dict(decisions)}")

    if args.dry_run:
        print("\n  --dry-run: showing first 10 entries:\n")
        for entry in to_add[:10]:
            sid = entry["strategy"]
            pid = entry["pass_id"]
            dec = entry["decision"]
            b_pf = entry["baseline"]["pf"]
            r_pf = entry["result"]["pf"]
            ret = entry["trade_retention_pct"]
            reason = entry.get("rejection_reason", "")
            print(f"    {sid} {pid}: {dec}  "
                  f"PF {b_pf:.2f}->{r_pf:.2f}  retention={ret:.0f}%"
                  f"{'  ' + reason if reason else ''}")
        if len(to_add) > 10:
            print(f"    ... and {len(to_add) - 10} more")
        return 0

    # Write merged result
    merged = existing + to_add
    HYPOTHESIS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    import os
    tmp = HYPOTHESIS_LOG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())

    if HYPOTHESIS_LOG_PATH.exists():
        os.replace(tmp, HYPOTHESIS_LOG_PATH)
    else:
        tmp.rename(HYPOTHESIS_LOG_PATH)

    print(f"\n  Written {len(merged)} entries to {HYPOTHESIS_LOG_PATH}")
    print(f"  ({len(existing)} existing + {len(to_add)} new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
