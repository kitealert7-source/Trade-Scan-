"""
burnin_evaluator.py — Universal Burn-In Gate Evaluator

Reads portfolio.yaml (all BURN_IN strategies) + shadow_trades.jsonl (completed
trades) and evaluates each strategy against pass/abort gates.

Data sources:
  - TS_Execution/portfolio.yaml — strategy list, lifecycle status
  - TS_Execution/outputs/shadow_trades.jsonl — EXIT events with net_pnl_usd

Output: per-strategy verdict (CONTINUE / ON_TRACK / WARN / ABORT) + summary.
No MT5 required. Read-only — modifies nothing.

Usage:
  python tools/burnin_evaluator.py              # full report
  python tools/burnin_evaluator.py --json       # machine-readable output
  python tools/burnin_evaluator.py --strategy X # single strategy only

Integration: call from session-close workflow (Step 4) after data source refresh.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT

PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
SHADOW_TRADES  = TS_EXEC_ROOT / "outputs" / "shadow_trades.jsonl"

# Centralised shadow-trade reader — single lifecycle filter point
sys.path.insert(0, str(TS_EXEC_ROOT / "src"))
from shadow_trades_reader import get_valid_trades  # noqa: E402

# ---------------------------------------------------------------------------
# Default gate thresholds (from portfolio.yaml burn-in comments)
# Strategies can override via per-strategy config in future.
# ---------------------------------------------------------------------------

GATES = {
    # Pass gates (all must hold at completion)
    "pass_pf":           1.20,
    "soft_pf":           1.10,   # soft pass: extend 30d, monitor
    "pass_wr_pct":       50.0,
    "pass_max_dd_pct":   10.0,
    "pass_fill_rate":    85.0,

    # Abort gates (halt immediately if breached)
    "abort_pf_after_n":  1.10,   # PF floor after abort_pf_min_trades
    "abort_pf_min_trades": 50,   # PF abort only applies after this many trades
    "abort_max_dd_pct":  12.0,
    "abort_fill_rate":   80.0,
    "abort_consec_loss_weeks": 3,

    # Completion targets
    "target_trades":     90,
    "target_days":       60,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_portfolio() -> list[dict[str, Any]]:
    """Load BURN_IN strategies from portfolio.yaml."""
    if not PORTFOLIO_YAML.exists():
        print(f"  [ERROR] portfolio.yaml not found: {PORTFOLIO_YAML}")
        return []
    try:
        import yaml
        with open(PORTFOLIO_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"  [ERROR] Failed to load portfolio.yaml: {e}")
        return []

    strategies = data.get("portfolio", {}).get("strategies", [])
    return [
        s for s in strategies
        if s.get("lifecycle") == "BURN_IN" and s.get("enabled", False)
    ]


def _load_shadow_trades() -> list[dict[str, Any]]:
    """Load ALL events from shadow_trades.jsonl (SIGNAL, ENTRY, EXIT).

    Delegates to the centralized shadow_trades_reader which enforces
    the global lifecycle filter (INVALIDATED excluded).
    """
    if not SHADOW_TRADES.exists():
        print(f"  [WARN] shadow_trades.jsonl not found: {SHADOW_TRADES}")
        return []
    return get_valid_trades(SHADOW_TRADES)


def _count_shadow_events(
    all_records: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count SIGNAL and ENTRY events per strategy from shadow_trades.jsonl.

    Uses shadow trades as single source (journal files have inconsistent IDs).
    Returns (signal_counts, fill_counts).
    """
    signals: dict[str, int] = defaultdict(int)
    fills: dict[str, int] = defaultdict(int)
    for r in all_records:
        sid = r.get("strategy_id", "")
        if not sid:
            continue
        evt = r.get("event_type", "")
        if evt == "SIGNAL":
            signals[sid] += 1
        elif evt == "ENTRY":
            fills[sid] += 1
    return dict(signals), dict(fills)


# ---------------------------------------------------------------------------
# Per-strategy metrics from shadow trades
# ---------------------------------------------------------------------------

def _compute_metrics(
    trades: list[dict[str, Any]],
    signal_count: int,
    fill_count: int,
) -> dict[str, Any]:
    """Compute burn-in metrics from a list of EXIT records for one strategy."""
    n = len(trades)
    if n == 0:
        return {
            "trades": 0, "pf": None, "wr_pct": None, "net_pnl": 0.0,
            "max_dd_pct": 0.0, "max_dd_usd": 0.0,
            "consec_losing_weeks": 0, "max_consec_losses": 0,
            "fill_rate": None, "signals": signal_count, "fills": fill_count,
        }

    pnls = [float(t.get("net_pnl_usd", 0) or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    wr = len(wins) / n * 100.0

    # Drawdown (USD-based, relative to notional capital)
    notional = 10000.0  # burn_in_notional_capital from portfolio.yaml
    equity = 0.0
    peak = 0.0
    max_dd_usd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd_usd:
            max_dd_usd = dd
    max_dd_pct = (max_dd_usd / notional) * 100.0

    # Max consecutive losses
    max_consec = cur_consec = 0
    for p in pnls:
        if p <= 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    # Weekly PnL for consecutive losing weeks
    weekly_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        event_utc = t.get("event_utc", "")
        try:
            dt = datetime.fromisoformat(event_utc)
            week_key = dt.strftime("%G-W%V")
            weekly_pnl[week_key] += float(t.get("net_pnl_usd", 0) or 0)
        except (ValueError, TypeError):
            pass

    consec_losing = cur_losing = 0
    for wk in sorted(weekly_pnl.keys()):
        if weekly_pnl[wk] < 0:
            cur_losing += 1
            consec_losing = max(consec_losing, cur_losing)
        else:
            cur_losing = 0

    # Fill rate
    fill_rate = (fill_count / signal_count * 100.0) if signal_count > 0 else None

    return {
        "trades": n,
        "pf": round(pf, 3) if pf != float("inf") else float("inf"),
        "wr_pct": round(wr, 1),
        "net_pnl": round(sum(pnls), 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "max_dd_usd": round(max_dd_usd, 2),
        "consec_losing_weeks": consec_losing,
        "max_consec_losses": max_consec,
        "fill_rate": round(fill_rate, 1) if fill_rate is not None else None,
        "signals": signal_count,
        "fills": fill_count,
        "weekly_pnl": dict(weekly_pnl),
    }


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def _evaluate_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    """Evaluate pass/abort gates. Returns verdict + per-gate status."""
    n = metrics["trades"]
    gates: list[dict[str, str]] = []
    abort_reasons: list[str] = []

    # --- Profit Factor ---
    pf = metrics["pf"]
    if pf is None:
        gates.append({"gate": "Profit Factor", "value": "--", "status": "PEND"})
    elif pf == float("inf"):
        gates.append({"gate": "Profit Factor", "value": "inf", "status": "PASS"})
    else:
        if n >= GATES["abort_pf_min_trades"] and pf < GATES["abort_pf_after_n"]:
            gates.append({"gate": "Profit Factor", "value": f"{pf:.2f}", "status": "ABORT"})
            abort_reasons.append(f"PF {pf:.2f} < {GATES['abort_pf_after_n']} after {n} trades")
        elif pf >= GATES["pass_pf"]:
            gates.append({"gate": "Profit Factor", "value": f"{pf:.2f}", "status": "PASS"})
        elif pf >= GATES["soft_pf"]:
            gates.append({"gate": "Profit Factor", "value": f"{pf:.2f}", "status": "SOFT"})
        else:
            gates.append({"gate": "Profit Factor", "value": f"{pf:.2f}", "status": "WARN"})

    # --- Win Rate ---
    wr = metrics["wr_pct"]
    if wr is None:
        gates.append({"gate": "Win Rate", "value": "--", "status": "PEND"})
    elif wr >= GATES["pass_wr_pct"]:
        gates.append({"gate": "Win Rate", "value": f"{wr:.1f}%", "status": "PASS"})
    else:
        gates.append({"gate": "Win Rate", "value": f"{wr:.1f}%", "status": "WARN"})

    # --- Max Drawdown ---
    dd = metrics["max_dd_pct"]
    if dd >= GATES["abort_max_dd_pct"]:
        gates.append({"gate": "Max Drawdown", "value": f"{dd:.2f}%", "status": "ABORT"})
        abort_reasons.append(f"DD {dd:.2f}% >= abort threshold {GATES['abort_max_dd_pct']}%")
    elif dd <= GATES["pass_max_dd_pct"]:
        gates.append({"gate": "Max Drawdown", "value": f"{dd:.2f}%", "status": "PASS"})
    else:
        gates.append({"gate": "Max Drawdown", "value": f"{dd:.2f}%", "status": "WARN"})

    # --- Fill Rate ---
    fr = metrics["fill_rate"]
    if fr is None:
        gates.append({"gate": "Fill Rate", "value": "--", "status": "PEND"})
    elif fr < GATES["abort_fill_rate"]:
        gates.append({"gate": "Fill Rate", "value": f"{fr:.1f}%", "status": "ABORT"})
        abort_reasons.append(f"Fill rate {fr:.1f}% < abort threshold {GATES['abort_fill_rate']}%")
    elif fr >= GATES["pass_fill_rate"]:
        gates.append({"gate": "Fill Rate", "value": f"{fr:.1f}%", "status": "PASS"})
    else:
        gates.append({"gate": "Fill Rate", "value": f"{fr:.1f}%", "status": "WARN"})

    # --- Consecutive Losing Weeks ---
    clw = metrics["consec_losing_weeks"]
    if clw >= GATES["abort_consec_loss_weeks"]:
        gates.append({"gate": "Consec Losing Weeks", "value": str(clw), "status": "ABORT"})
        abort_reasons.append(f"{clw} consecutive losing weeks >= {GATES['abort_consec_loss_weeks']}")
    else:
        gates.append({"gate": "Consec Losing Weeks", "value": str(clw), "status": "PASS"})

    # --- Verdict ---
    statuses = [g["status"] for g in gates]
    if abort_reasons:
        verdict = "ABORT"
    elif n == 0:
        verdict = "CONTINUE"
    elif any(s == "WARN" for s in statuses):
        verdict = "WARN"
    elif any(s == "PEND" for s in statuses):
        verdict = "CONTINUE"
    elif all(s in ("PASS", "SOFT") for s in statuses):
        verdict = "ON_TRACK"
    else:
        verdict = "CONTINUE"

    # Completion progress
    trade_pct = min(n / GATES["target_trades"] * 100.0, 100.0)

    return {
        "verdict": verdict,
        "gates": gates,
        "abort_reasons": abort_reasons,
        "completion_pct": round(trade_pct, 1),
    }


# ---------------------------------------------------------------------------
# Group strategies by base ID (multi-symbol → aggregate)
# ---------------------------------------------------------------------------

def _base_strategy_id(strategy_id: str) -> str:
    """Extract base strategy ID (without symbol suffix) for grouping.

    Example: 22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03_AUDJPY
          -> 22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03
    """
    import re
    # Match _SYMBOL at end (3+ uppercase letters/digits, typical forex/crypto/index)
    m = re.match(r"^(.+?_P\d{2})_([A-Z]{3,}[A-Z0-9]*)$", strategy_id)
    if m:
        return m.group(1)
    return strategy_id


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate_all(
    filter_strategy: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate all BURN_IN strategies. Returns list of evaluation dicts."""
    portfolio = _load_portfolio()
    if not portfolio:
        print("  No BURN_IN strategies found in portfolio.yaml.")
        return []

    all_shadow = _load_shadow_trades()
    signal_counts, fill_counts = _count_shadow_events(all_shadow)

    # Group EXIT events by strategy_id
    exits_by_strat: dict[str, list[dict]] = defaultdict(list)
    for e in all_shadow:
        if e.get("event_type") == "EXIT":
            sid = e.get("strategy_id", "")
            exits_by_strat[sid].append(e)

    # Group portfolio entries by base strategy ID
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in portfolio:
        sid = entry.get("id", "")
        base = _base_strategy_id(sid)
        groups[base].append(entry)

    results: list[dict[str, Any]] = []

    for base_id in sorted(groups.keys()):
        entries = groups[base_id]

        if filter_strategy and filter_strategy not in base_id:
            continue

        # Collect all symbol-level strategy IDs
        symbol_ids = [e["id"] for e in entries]
        symbols = [e.get("symbol", "?") for e in entries]
        timeframe = entries[0].get("timeframe", "?")
        vault_id = entries[0].get("vault_id", "")

        # Aggregate trades across symbols
        all_trades: list[dict] = []
        total_signals = 0
        total_fills = 0
        for sid in symbol_ids:
            all_trades.extend(exits_by_strat.get(sid, []))
            total_signals += signal_counts.get(sid, 0)
            total_fills += fill_counts.get(sid, 0)

        # Sort by time
        all_trades.sort(key=lambda t: t.get("event_utc", ""))

        metrics = _compute_metrics(all_trades, total_signals, total_fills)
        evaluation = _evaluate_gates(metrics)

        results.append({
            "strategy": base_id,
            "symbols": symbols,
            "timeframe": timeframe,
            "vault_id": vault_id,
            "metrics": metrics,
            "evaluation": evaluation,
        })

    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_report(results: list[dict[str, Any]]) -> None:
    """Print burn-in evaluation report."""
    if not results:
        print("\n  No BURN_IN strategies to evaluate.\n")
        return

    verdict_icons = {
        "ON_TRACK": "OK",
        "CONTINUE": "..",
        "WARN":     "~~",
        "ABORT":    "!!",
    }
    gate_icons = {
        "PASS": "OK",
        "SOFT": ">>",
        "WARN": "~~",
        "ABORT": "!!",
        "PEND": "??",
    }

    print()
    print("=" * 70)
    print("  BURN-IN EVALUATION REPORT")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Strategies: {len(results)} groups from portfolio.yaml")
    print("=" * 70)

    for r in results:
        ev = r["evaluation"]
        m = r["metrics"]
        verdict = ev["verdict"]
        icon = verdict_icons.get(verdict, "??")

        print()
        print(f"  [{icon}] {verdict:<10}  {r['strategy']}")
        print(f"      Symbols:    {', '.join(r['symbols'])}  |  TF: {r['timeframe']}")
        print(f"      Trades:     {m['trades']} / {GATES['target_trades']}  "
              f"({ev['completion_pct']:.0f}% complete)")
        print(f"      Net PnL:    ${m['net_pnl']:+,.2f}")

        if m["trades"] > 0:
            pf_str = f"{m['pf']:.2f}" if m["pf"] != float("inf") else "inf"
            print(f"      PF: {pf_str}  |  WR: {m['wr_pct']:.1f}%  |  "
                  f"DD: {m['max_dd_pct']:.2f}%  |  "
                  f"Consec Loss: {m['max_consec_losses']}")

            if m["fill_rate"] is not None:
                print(f"      Fill Rate:  {m['fill_rate']:.1f}%  "
                      f"({m['fills']}/{m['signals']} signals)")

            # Gate details
            print(f"      Gates:")
            for g in ev["gates"]:
                gi = gate_icons.get(g["status"], "??")
                print(f"        [{gi}] {g['status']:<5}  {g['gate']:<25}  {g['value']}")

        if ev["abort_reasons"]:
            print(f"      ABORT REASONS:")
            for reason in ev["abort_reasons"]:
                print(f"        -> {reason}")

    # Summary
    print()
    print("-" * 70)
    verdicts = defaultdict(int)
    for r in results:
        verdicts[r["evaluation"]["verdict"]] += 1

    total_trades = sum(r["metrics"]["trades"] for r in results)
    total_pnl = sum(r["metrics"]["net_pnl"] for r in results)

    print(f"  Summary: {len(results)} strategy groups  |  "
          f"{total_trades} total trades  |  ${total_pnl:+,.2f} net PnL")
    parts = [f"{v}: {c}" for v, c in sorted(verdicts.items())]
    print(f"  Verdicts: {', '.join(parts)}")
    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Universal Burn-In Gate Evaluator"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON"
    )
    parser.add_argument(
        "--strategy", type=str, default=None,
        help="Filter to a specific strategy (substring match)"
    )
    args = parser.parse_args()

    results = evaluate_all(filter_strategy=args.strategy)

    if args.json:
        # Clean up non-serializable values
        def _clean(obj):
            if isinstance(obj, float) and obj == float("inf"):
                return "inf"
            return obj
        print(json.dumps(results, indent=2, default=_clean))
    else:
        print_report(results)

    # Exit code: 2 if any ABORT, 0 otherwise (advisory only)
    has_abort = any(r["evaluation"]["verdict"] == "ABORT" for r in results)
    return 2 if has_abort else 0


if __name__ == "__main__":
    raise SystemExit(main())
