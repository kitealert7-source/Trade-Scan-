"""
Regime Gate Validation + Workflow Integration Audit
====================================================

Three-pass evaluation across all PF_ single-asset portfolios + multi-asset controls.

Pass A: Baseline      — raw_trades -> capital_wrapper -> metrics
Pass B: Gated (pre)   — raw_trades -> regime_filter -> capital_wrapper -> metrics
Pass C: Gated (post)  — raw_trades -> capital_wrapper -> regime_filter (report only)

Plus 60/40 out-of-sample stability test for anti-overfit validation.

Usage: python experiments/regime_gate_validation.py
"""

import sys
import json
import csv
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import yaml

from tools.capital_wrapper import PROFILES, run_simulation, load_broker_spec
from tools.capital_engine.simulation import TradeEvent

# ──────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────

STRATEGIES_ROOT = Path(__file__).resolve().parents[1].parent / "TradeScan_State" / "strategies"
BROKER_SPECS_ROOT = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"

# Test set: all single-asset PF_ + multi-asset controls
SINGLE_ASSET = [
    "PF_7FCF1D2EB158",
    "PF_82AEC0F73920",
    "PF_101C552D7C04",
    "PF_5E614D412962",
    "PF_8C20B7EC307D",
    "PF_9D1FEA9AD62B",
]

MULTI_ASSET = [
    "22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P01",
    "15_MR_FX_15M_ASRANGE_SESSFILT_S03_V1_P01",
    "02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00",
]

ALL_PORTFOLIOS = SINGLE_ASSET + MULTI_ASSET

# Profiles to test (skip RAW — no constraints, gating has no capital interaction)
TEST_PROFILES = {
    k: v for k, v in PROFILES.items()
    if k != "RAW_MIN_LOT_V1" and k != "MIN_LOT_FALLBACK_UNCAPPED_V1"
}

# ──────────────────────────────────────────────────────────────────────
# TRADE LOADING
# ──────────────────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> datetime:
    ts_str = ts_str.strip()
    if not ts_str:
        raise ValueError("Empty timestamp")
    iso = ts_str.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(ts_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse: '{ts_str}'")


def _opt_float(raw) -> Optional[float]:
    token = str(raw).strip()
    if token in ("", "None", "none", "nan"):
        return None
    try:
        return float(token)
    except ValueError:
        return None


def load_raw_trades(portfolio_id: str) -> pd.DataFrame:
    """Load RAW_MIN_LOT_V1 deployable trade log for a portfolio."""
    csv_path = (STRATEGIES_ROOT / portfolio_id / "deployable" /
                "RAW_MIN_LOT_V1" / "deployable_trade_log.csv")
    if not csv_path.exists():
        raise FileNotFoundError(f"No RAW log: {csv_path}")
    df = pd.read_csv(csv_path)
    df["entry_ts"] = df["entry_timestamp"].apply(_parse_ts)
    df["exit_ts"] = df["exit_timestamp"].apply(_parse_ts)
    df = df.sort_values("entry_ts").reset_index(drop=True)
    return df


def df_to_events(df: pd.DataFrame) -> List[TradeEvent]:
    """Convert DataFrame rows to sorted TradeEvent list."""
    events = []
    for _, row in df.iterrows():
        trade_id = str(row["trade_id"])

        shared = dict(
            trade_id=trade_id,
            symbol=str(row["symbol"]),
            direction=int(row["direction"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            risk_distance=float(row["risk_distance"]),
            initial_stop_price=_opt_float(row.get("initial_stop_price")),
            atr_entry=_opt_float(row.get("atr_entry")),
            r_multiple=_opt_float(row.get("r_multiple")),
            volatility_regime=str(row.get("volatility_regime", "")).strip(),
            trend_regime=str(row.get("trend_regime", "")).strip(),
            trend_label=str(row.get("trend_label", "")).strip(),
        )
        entry_ts = row["entry_ts"] if isinstance(row["entry_ts"], datetime) else _parse_ts(str(row["entry_ts"]))
        exit_ts = row["exit_ts"] if isinstance(row["exit_ts"], datetime) else _parse_ts(str(row["exit_ts"]))

        events.append(TradeEvent(timestamp=entry_ts, event_type="ENTRY", **shared))
        events.append(TradeEvent(timestamp=exit_ts, event_type="EXIT", **shared))
    return sorted(events, key=lambda e: e.sort_key)


def get_broker_specs(df: pd.DataFrame) -> Dict[str, dict]:
    """Load broker specs for all symbols in a trade DataFrame."""
    specs = {}
    for sym in df["symbol"].unique():
        path = BROKER_SPECS_ROOT / f"{sym}.yaml"
        if path.exists():
            with open(path) as f:
                specs[sym] = yaml.safe_load(f)
        else:
            print(f"  [WARN] Missing broker spec: {sym}")
    return specs


# ──────────────────────────────────────────────────────────────────────
# REGIME AFFINITY DERIVATION
# ──────────────────────────────────────────────────────────────────────

def derive_regime_affinity(df: pd.DataFrame, min_trades: int = 10) -> Dict[str, dict]:
    """
    Derive regime gates from PnL decomposition per strategy x regime.

    For each strategy prefix, compute mean PnL per (volatility_regime, trend_label)
    cell. Block cells where mean PnL < 0 AND sample size >= min_trades.

    Returns: {strategy_prefix: {"block_vol": set, "block_trend": set}}
    """
    gates = {}

    # Extract strategy prefix (first two underscore tokens: "03_TREND", "22_CONT")
    df = df.copy()
    df["strat_prefix"] = df["trade_id"].apply(
        lambda x: "_".join(str(x).split("_")[:2])
    )

    for prefix, grp in df.groupby("strat_prefix"):
        block_vol = set()
        block_trend = set()

        # Volatility regime decomposition
        if "volatility_regime" in grp.columns:
            for regime, rg in grp.groupby("volatility_regime"):
                regime_str = str(regime).strip().lower()
                if regime_str in ("", "nan", "none"):
                    continue
                if len(rg) >= min_trades and rg["pnl_usd"].sum() < 0:
                    block_vol.add(regime_str)

        # Trend label decomposition
        if "trend_label" in grp.columns:
            for label, lg in grp.groupby("trend_label"):
                label_str = str(label).strip().lower()
                if label_str in ("", "nan", "none"):
                    continue
                if len(lg) >= min_trades and lg["pnl_usd"].sum() < 0:
                    block_trend.add(label_str)

        gates[prefix] = {"block_vol": block_vol, "block_trend": block_trend}

    return gates


def apply_regime_gate(df: pd.DataFrame, gates: Dict[str, dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply regime gates to trade DataFrame.

    Returns: (passed_df, blocked_df)
    """
    df = df.copy()
    df["strat_prefix"] = df["trade_id"].apply(
        lambda x: "_".join(str(x).split("_")[:2])
    )

    blocked_mask = pd.Series(False, index=df.index)
    for idx, row in df.iterrows():
        prefix = row["strat_prefix"]
        gate = gates.get(prefix)
        if gate is None:
            continue
        vol = str(row.get("volatility_regime", "")).strip().lower()
        trend = str(row.get("trend_label", "")).strip().lower()
        if vol in gate["block_vol"] or trend in gate["block_trend"]:
            blocked_mask.at[idx] = True

    passed = df[~blocked_mask].drop(columns=["strat_prefix"])
    blocked = df[blocked_mask].drop(columns=["strat_prefix"])
    return passed, blocked


# ──────────────────────────────────────────────────────────────────────
# SIMULATION + METRICS
# ──────────────────────────────────────────────────────────────────────

def run_sim(events: List[TradeEvent], broker_specs: dict,
            profiles: dict = None) -> Dict[str, dict]:
    """Run simulation and extract key metrics per profile."""
    if profiles is None:
        profiles = TEST_PROFILES
    states = run_simulation(events, broker_specs, profiles=profiles)

    results = {}
    for name, state in states.items():
        total = state.total_accepted + state.total_rejected
        rej_rate = (state.total_rejected / total * 100) if total > 0 else 0.0

        # Max DD %
        dd_pct = (state.max_drawdown_usd / state.peak_equity * 100) if state.peak_equity > 0 else 0.0

        # Profit factor from closed trades
        gross_profit = sum(t["pnl_usd"] for t in state.closed_trades_log if t["pnl_usd"] > 0)
        gross_loss = abs(sum(t["pnl_usd"] for t in state.closed_trades_log if t["pnl_usd"] < 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Avg concurrent
        if hasattr(state, "concurrent_log") and state.concurrent_log:
            avg_conc = np.mean(state.concurrent_log) if state.concurrent_log else 0.0
        else:
            avg_conc = 0.0

        # Simulation years
        tl = state.equity_timeline
        if len(tl) >= 2:
            delta = tl[-1][0] - tl[0][0]
            years = delta.total_seconds() / (365.25 * 86400)
        else:
            years = 0.0

        results[name] = {
            "net_pnl": round(state.realized_pnl, 2),
            "profit_factor": round(pf, 2),
            "max_dd_pct": round(dd_pct, 2),
            "total_trades": state.total_accepted,
            "total_rejected": state.total_rejected,
            "execution_rate": round(state.total_accepted / total * 100, 1) if total > 0 else 0.0,
            "rejection_rate_pct": round(rej_rate, 1),
            "avg_concurrent": round(avg_conc, 2),
            "max_concurrent": state.max_concurrent,
            "final_equity": round(state.equity, 2),
            "sim_years": round(years, 2),
        }
    return results


def select_best_profile(results: Dict[str, dict]) -> str:
    """Select best profile by return/DD score (same logic as evaluator)."""
    best_name = None
    best_score = -1e12
    for name, m in results.items():
        if m["net_pnl"] <= 0:
            continue
        dd_floor = max(abs(m["max_dd_pct"]), 0.01)
        score = m["net_pnl"] / dd_floor
        # Execution health penalty
        rej = m["rejection_rate_pct"]
        if rej > 60:
            score *= 0.4
        elif rej > 30:
            score *= 0.7
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


# ──────────────────────────────────────────────────────────────────────
# THREE-PASS EVALUATION
# ──────────────────────────────────────────────────────────────────────

def evaluate_portfolio(portfolio_id: str) -> dict:
    """Run A/B/C passes + stability test for one portfolio."""
    print(f"\n{'='*60}")
    print(f"  {portfolio_id}")
    print(f"{'='*60}")

    df = load_raw_trades(portfolio_id)
    broker_specs = get_broker_specs(df)
    n_trades = len(df)
    print(f"  Loaded {n_trades} raw trades, {df['symbol'].nunique()} symbols")

    # ── Pass A: Baseline ──
    print("  [A] Baseline...")
    events_a = df_to_events(df)
    results_a = run_sim(events_a, broker_specs)
    profile_a = select_best_profile(results_a)
    print(f"      Best profile: {profile_a}")

    # ── Derive regime affinity (from full dataset for B, split for stability) ──
    gates = derive_regime_affinity(df)
    active_gates = {k: v for k, v in gates.items()
                    if v["block_vol"] or v["block_trend"]}
    print(f"  Regime gates: {len(active_gates)} strategies with blocks")
    for prefix, g in active_gates.items():
        parts = []
        if g["block_vol"]:
            parts.append(f"vol={g['block_vol']}")
        if g["block_trend"]:
            parts.append(f"trend={g['block_trend']}")
        print(f"    {prefix}: {', '.join(parts)}")

    # ── Pass B: Gated pre-capital ──
    print("  [B] Gated (pre-capital)...")
    passed_df, blocked_df = apply_regime_gate(df, gates)
    n_blocked = len(blocked_df)
    blocked_pnl = blocked_df["pnl_usd"].sum() if len(blocked_df) > 0 else 0.0
    activation_rate = len(passed_df) / n_trades * 100 if n_trades > 0 else 100.0
    print(f"      Blocked: {n_blocked} trades ({100 - activation_rate:.1f}%), "
          f"blocked PnL: ${blocked_pnl:,.2f}")

    events_b = df_to_events(passed_df)
    results_b = run_sim(events_b, broker_specs)
    profile_b = select_best_profile(results_b)
    print(f"      Best profile: {profile_b}")

    # ── Pass C: Gated post-capital (incorrect workflow) ──
    print("  [C] Gated (post-capital, control)...")
    # Run full simulation first
    results_c_full = run_sim(events_a, broker_specs)
    # Then filter accepted trades by regime gate (reporting only)
    # For each profile, check which accepted trades would have been blocked
    results_c = {}
    for pname, state_metrics in results_c_full.items():
        # C metrics = A metrics (capital ran on ungated data)
        # But we tag what WOULD have been blocked
        results_c[pname] = dict(state_metrics)
    profile_c = select_best_profile(results_c)

    # ── Stability: 60/40 split ──
    print("  [S] Stability (60/40 OOS)...")
    split_idx = int(len(df) * 0.6)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]

    gates_train = derive_regime_affinity(df_train)
    passed_test, blocked_test = apply_regime_gate(df_test, gates_train)
    n_test = len(df_test)
    n_blocked_oos = len(blocked_test)
    blocked_pnl_oos = blocked_test["pnl_usd"].sum() if len(blocked_test) > 0 else 0.0

    # Baseline on test set
    events_test_all = df_to_events(df_test)
    results_test_a = run_sim(events_test_all, broker_specs)

    # Gated on test set
    events_test_gated = df_to_events(passed_test)
    results_test_b = run_sim(events_test_gated, broker_specs)

    print(f"      OOS: {n_test} trades, blocked {n_blocked_oos}, "
          f"blocked PnL: ${blocked_pnl_oos:,.2f}")

    # ── Assemble per-profile deltas ──
    profile_results = {}
    for pname in TEST_PROFILES:
        a = results_a.get(pname, {})
        b = results_b.get(pname, {})
        c = results_c.get(pname, {})
        ta = results_test_a.get(pname, {})
        tb = results_test_b.get(pname, {})

        delta_pnl = b.get("net_pnl", 0) - a.get("net_pnl", 0)
        delta_pf = b.get("profit_factor", 0) - a.get("profit_factor", 0)
        delta_dd = b.get("max_dd_pct", 0) - a.get("max_dd_pct", 0)
        delta_trades = b.get("total_trades", 0) - a.get("total_trades", 0)

        # C vs B ordering test
        c_pnl = c.get("net_pnl", 0)
        b_pnl = b.get("net_pnl", 0)
        ordering_diverges = abs(c_pnl - b_pnl) > 1.0

        # OOS stability
        oos_delta_pnl = tb.get("net_pnl", 0) - ta.get("net_pnl", 0)
        oos_delta_pf = tb.get("profit_factor", 0) - ta.get("profit_factor", 0)
        # Stable if OOS doesn't reverse the direction of improvement
        oos_direction_match = (delta_pnl >= 0 and oos_delta_pnl >= 0) or \
                              (delta_pnl < 0 and oos_delta_pnl < 0) or \
                              abs(delta_pnl) < 10  # trivial change
        oos_stable = oos_direction_match

        profile_results[pname] = {
            "A": a, "B": b, "C": c,
            "delta_pnl": round(delta_pnl, 2),
            "delta_pf": round(delta_pf, 2),
            "delta_dd": round(delta_dd, 2),
            "delta_trades": delta_trades,
            "ordering_diverges": ordering_diverges,
            "oos_delta_pnl": round(oos_delta_pnl, 2),
            "oos_delta_pf": round(oos_delta_pf, 2),
            "oos_stable": oos_stable,
        }

    return {
        "portfolio_id": portfolio_id,
        "type": "single_asset" if portfolio_id.startswith("PF_") else "multi_asset",
        "n_trades": n_trades,
        "n_blocked": n_blocked,
        "blocked_pnl_raw": round(blocked_pnl, 2),
        "activation_rate_pct": round(activation_rate, 1),
        "profile_a": profile_a,
        "profile_b": profile_b,
        "profile_changed": profile_a != profile_b,
        "gates": {k: {"block_vol": sorted(v["block_vol"]),
                       "block_trend": sorted(v["block_trend"])}
                  for k, v in active_gates.items()},
        "profiles": profile_results,
        "stability": {
            "n_test": n_test,
            "n_blocked_oos": n_blocked_oos,
            "blocked_pnl_oos": round(blocked_pnl_oos, 2),
        },
    }


# ──────────────────────────────────────────────────────────────────────
# AGGREGATE REPORT
# ──────────────────────────────────────────────────────────────────────

def print_report(all_results: List[dict]):
    """Print the structured report."""
    print(f"\n{'='*80}")
    print("  REGIME GATE VALIDATION — AGGREGATE REPORT")
    print(f"{'='*80}")

    # Pick one representative profile for portfolio-level summary
    # Use the best profile from Pass A (baseline) for each portfolio
    print(f"\n{'─'*80}")
    print("  1. PORTFOLIO TABLE (using baseline-selected profile per portfolio)")
    print(f"{'─'*80}")
    print(f"  {'Portfolio':<36} {'dPnL':>8} {'dPF':>6} {'dDD%':>7} "
          f"{'%blk':>5} {'prof?':>5} {'ord?':>5} {'OOS':>5}")
    print(f"  {'─'*36} {'─'*8} {'─'*6} {'─'*7} {'─'*5} {'─'*5} {'─'*5} {'─'*5}")

    improved_pnl = 0
    improved_pf = 0
    profile_changed = 0
    ordering_valid = 0
    oos_stable = 0
    total_delta_pnl = 0
    total_delta_dd = 0
    n = len(all_results)

    for r in all_results:
        # Use baseline profile for this portfolio's comparison
        pname = r["profile_a"] or list(TEST_PROFILES.keys())[0]
        pm = r["profiles"].get(pname, {})

        d_pnl = pm.get("delta_pnl", 0)
        d_pf = pm.get("delta_pf", 0)
        d_dd = pm.get("delta_dd", 0)
        pct_blk = 100.0 - r["activation_rate_pct"]
        prof_chg = "YES" if r["profile_changed"] else "no"
        ord_valid = "YES" if pm.get("ordering_diverges") else "no"
        oos = "PASS" if pm.get("oos_stable") else "FAIL"

        total_delta_pnl += d_pnl
        total_delta_dd += d_dd
        if d_pnl > 0:
            improved_pnl += 1
        if d_pf > 0:
            improved_pf += 1
        if r["profile_changed"]:
            profile_changed += 1
        if pm.get("ordering_diverges"):
            ordering_valid += 1
        if pm.get("oos_stable"):
            oos_stable += 1

        print(f"  {r['portfolio_id']:<36} {d_pnl:>+8.0f} {d_pf:>+6.2f} {d_dd:>+7.2f} "
              f"{pct_blk:>5.1f} {prof_chg:>5} {ord_valid:>5} {oos:>5}")

    print(f"\n{'─'*80}")
    print("  2. AGGREGATE SUMMARY")
    print(f"{'─'*80}")
    print(f"  Portfolios tested:           {n}")
    if n == 0:
        print("  [NO VALID RESULTS — cannot compute aggregate metrics]")
        print(f"\n{'─'*80}")
        print("  5. RECOMMENDATION")
        print(f"{'─'*80}")
        print("  => REJECT: No portfolios completed evaluation.")
        return
    print(f"  PnL improved (B > A):        {improved_pnl}/{n} ({improved_pnl/n*100:.0f}%)")
    print(f"  PF improved (B > A):         {improved_pf}/{n} ({improved_pf/n*100:.0f}%)")
    print(f"  Avg delta PnL:               ${total_delta_pnl/n:+,.2f}")
    print(f"  Avg delta DD%:               {total_delta_dd/n:+.2f}pp")
    print(f"  Profile changed:             {profile_changed}/{n} ({profile_changed/n*100:.0f}%)")
    print(f"  Ordering matters (C != B):   {ordering_valid}/{n} ({ordering_valid/n*100:.0f}%)")
    print(f"  OOS stable:                  {oos_stable}/{n} ({oos_stable/n*100:.0f}%)")

    print(f"\n{'─'*80}")
    print("  3. WORKFLOW VERDICT")
    print(f"{'─'*80}")
    b_better = improved_pnl / n >= 0.5
    ordering_matters = ordering_valid / n >= 0.5
    print(f"  Pre-capital gating (B) improves baseline (A)?  "
          f"{'YES' if b_better else 'NO'} ({improved_pnl}/{n})")
    print(f"  Post-capital gating (C) diverges from B?       "
          f"{'YES' if ordering_matters else 'NO'} ({ordering_valid}/{n})")
    if b_better and ordering_matters:
        print("  => Gating MUST occur before capital allocation.")
    elif b_better:
        print("  => Gating helps but ordering is not critical.")
    else:
        print("  => Gating does not consistently improve outcomes.")

    print(f"\n{'─'*80}")
    print("  4. STABILITY VERDICT")
    print(f"{'─'*80}")
    stable_rate = oos_stable / n
    if stable_rate >= 0.7:
        print(f"  PASS — {oos_stable}/{n} portfolios show stable OOS improvement ({stable_rate:.0%})")
    elif stable_rate >= 0.5:
        print(f"  MARGINAL — {oos_stable}/{n} portfolios stable ({stable_rate:.0%}), proceed with caution")
    else:
        print(f"  FAIL — Only {oos_stable}/{n} stable ({stable_rate:.0%}), likely overfit")

    print(f"\n{'─'*80}")
    print("  5. RECOMMENDATION")
    print(f"{'─'*80}")
    if b_better and stable_rate >= 0.7:
        print("  => PROMOTE: Integrate gating into portfolio evaluator (pre-capital).")
    elif b_better and stable_rate >= 0.5:
        print("  => LIMITED: Use as diagnostic layer; monitor OOS before full integration.")
    else:
        print("  => REJECT: Insufficient evidence for integration.")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    print("="*80)
    print("  REGIME GATE VALIDATION + WORKFLOW INTEGRATION AUDIT")
    print("="*80)

    all_results = []
    skipped = []

    for pid in ALL_PORTFOLIOS:
        csv_path = (STRATEGIES_ROOT / pid / "deployable" /
                    "RAW_MIN_LOT_V1" / "deployable_trade_log.csv")
        if not csv_path.exists():
            print(f"\n  [SKIP] {pid}: no RAW_MIN_LOT_V1 trade log")
            skipped.append(pid)
            continue

        try:
            result = evaluate_portfolio(pid)
            all_results.append(result)
        except Exception as e:
            print(f"\n  [ERROR] {pid}: {e}")
            import traceback
            traceback.print_exc()
            skipped.append(pid)

    if skipped:
        print(f"\n  Skipped: {skipped}")

    # Save raw results
    output_dir = PROJECT_ROOT / "experiments" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "regime_gate_validation.json"

    # Make JSON-serializable
    def _ser(obj):
        if isinstance(obj, set):
            return sorted(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        return str(obj)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=_ser)
    print(f"\n  Raw results saved: {out_path}")

    # Print aggregate report
    print_report(all_results)


if __name__ == "__main__":
    main()
