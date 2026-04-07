"""
Strategy Activation (Pre-Trade) vs Regime Filtering (Post-Trade)
=================================================================

Three-pass comparison:
  A: Baseline         — all trades, no regime logic
  B: Post-trade filter — PnL-derived regime gates (reference, expected OOS fail)
  C: Pre-trade activation — universal family×regime rules, NO PnL derivation

The key hypothesis: C should show smaller IS gains than B but significantly
better OOS stability because the activation rules are structural (not fitted).

Universal Activation Rules (COARSE — same for all portfolios):
  Volatility:
    TREND, STR       → active in {normal, high}   (need vol to work)
    REV, MR          → active in {low, normal}     (need calm to revert)
    RSI, PA, CONT, VOL → always active
  Trend:
    REV, MR          → active in {neutral, weak_up, weak_down}
                       (disable in strong trends — reversals fail)
    All others       → always active

Usage: python experiments/activation_vs_filtering.py
"""

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from collections import Counter

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

TEST_PROFILES = {
    k: v for k, v in PROFILES.items()
    if k != "RAW_MIN_LOT_V1" and k != "MIN_LOT_FALLBACK_UNCAPPED_V1"
}

# ──────────────────────────────────────────────────────────────────────
# UNIVERSAL ACTIVATION RULES (structural, NOT fitted)
# ──────────────────────────────────────────────────────────────────────
# Volatility regime: which vol states each family is ACTIVE in.
# Missing family = always active.
_VOL_ACTIVE = {
    "TREND": {"normal", "high"},
    "STR":   {"normal", "high"},
    "REV":   {"low", "normal"},
    "MR":    {"low", "normal"},
    # RSI, PA, CONT, VOL → no restriction (always active)
}

# Trend regime: which trend states each family is ACTIVE in.
# Missing family = always active.
_TREND_ACTIVE = {
    "REV":  {"neutral", "weak_up", "weak_down"},
    "MR":   {"neutral", "weak_up", "weak_down"},
    # TREND, STR, RSI, PA, CONT, VOL → no restriction
}

# Map integer vol codes to string labels
_VOL_INT_MAP = {
    "-1": "low", "-1.0": "low",
    "0": "normal", "0.0": "normal",
    "1": "high", "1.0": "high",
}


def _normalize_vol(raw) -> str:
    """Normalize volatility_regime to {low, normal, high}."""
    s = str(raw).strip().lower()
    if s in ("low", "normal", "high"):
        return s
    return _VOL_INT_MAP.get(s, "")


def _normalize_trend(raw) -> str:
    """Normalize trend_label."""
    return str(raw).strip().lower()


def _extract_family(trade_id: str) -> str:
    """Extract family token from trade_id (position 2 in underscore split).
    e.g. '03_TREND_XAU_1H_CHOCH_...|5' → 'TREND'
    Handles C_ clone prefix: 'C_03_TREND_...' → 'TREND'
    """
    base = trade_id.split("|")[0]
    parts = base.split("_")
    # Handle clone prefix
    if parts[0] == "C" and len(parts) >= 3:
        return parts[2].upper()
    if len(parts) >= 2:
        return parts[1].upper()
    return "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────
# TRADE LOADING (shared with regime_gate_validation.py)
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
# POST-TRADE FILTERING (Test B — from regime_gate_validation.py)
# PnL-derived gates; expected to fail OOS
# ──────────────────────────────────────────────────────────────────────

def derive_regime_affinity(df: pd.DataFrame, min_trades: int = 10) -> Dict[str, dict]:
    gates = {}
    df = df.copy()
    df["strat_prefix"] = df["trade_id"].apply(
        lambda x: "_".join(str(x).split("_")[:2])
    )
    for prefix, grp in df.groupby("strat_prefix"):
        block_vol = set()
        block_trend = set()
        if "volatility_regime" in grp.columns:
            for regime, rg in grp.groupby("volatility_regime"):
                regime_str = str(regime).strip().lower()
                if regime_str in ("", "nan", "none"):
                    continue
                if len(rg) >= min_trades and rg["pnl_usd"].sum() < 0:
                    block_vol.add(regime_str)
        if "trend_label" in grp.columns:
            for label, lg in grp.groupby("trend_label"):
                label_str = str(label).strip().lower()
                if label_str in ("", "nan", "none"):
                    continue
                if len(lg) >= min_trades and lg["pnl_usd"].sum() < 0:
                    block_trend.add(label_str)
        gates[prefix] = {"block_vol": block_vol, "block_trend": block_trend}
    return gates


def apply_post_trade_filter(df: pd.DataFrame, gates: Dict[str, dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
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
# PRE-TRADE ACTIVATION (Test C — universal rules, NOT fitted)
# ──────────────────────────────────────────────────────────────────────

def apply_activation_rules(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Apply universal family×regime activation rules.

    Returns: (active_df, inactive_df, diagnostics)
    where diagnostics = {family: {regime_state: n_blocked, ...}, ...}
    """
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)
    df["vol_norm"] = df["volatility_regime"].apply(_normalize_vol)
    df["trend_norm"] = df["trend_label"].apply(_normalize_trend)

    inactive_mask = pd.Series(False, index=df.index)
    block_reasons = []  # for diagnostics

    for idx, row in df.iterrows():
        family = row["family"]
        vol = row["vol_norm"]
        trend = row["trend_norm"]

        # Volatility activation check
        vol_allowed = _VOL_ACTIVE.get(family)
        if vol_allowed is not None and vol and vol not in vol_allowed:
            inactive_mask.at[idx] = True
            block_reasons.append((family, f"vol={vol}"))
            continue

        # Trend activation check
        trend_allowed = _TREND_ACTIVE.get(family)
        if trend_allowed is not None and trend and trend not in trend_allowed:
            inactive_mask.at[idx] = True
            block_reasons.append((family, f"trend={trend}"))
            continue

    drop_cols = ["family", "vol_norm", "trend_norm"]
    active = df[~inactive_mask].drop(columns=drop_cols)
    inactive = df[inactive_mask].drop(columns=drop_cols)

    # Build diagnostics
    diag = {}
    for fam, reason in block_reasons:
        diag.setdefault(fam, Counter())[reason] += 1
    diag = {fam: dict(counts) for fam, counts in diag.items()}

    return active, inactive, diag


def compute_activation_stats(df: pd.DataFrame) -> dict:
    """Compute per-regime activation statistics (diagnostic)."""
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)
    df["vol_norm"] = df["volatility_regime"].apply(_normalize_vol)
    df["trend_norm"] = df["trend_label"].apply(_normalize_trend)

    families = sorted(df["family"].unique())
    vol_states = sorted(df["vol_norm"].unique())
    trend_states = sorted(df["trend_norm"].unique())

    # Per family×vol: % active
    family_vol_active = {}
    for fam in families:
        fam_df = df[df["family"] == fam]
        vol_allowed = _VOL_ACTIVE.get(fam)
        for v in vol_states:
            if not v:
                continue
            n_total = len(fam_df[fam_df["vol_norm"] == v])
            if n_total == 0:
                continue
            active = vol_allowed is None or v in vol_allowed
            family_vol_active[(fam, v)] = {
                "total": n_total,
                "active": active,
                "pct": 100.0 if active else 0.0,
            }

    return {
        "families": families,
        "vol_states": vol_states,
        "trend_states": trend_states,
        "family_vol_active": {f"{k[0]}|{k[1]}": v for k, v in family_vol_active.items()},
        "avg_active_families": len(families),  # will be refined per-regime below
    }


# ──────────────────────────────────────────────────────────────────────
# SIMULATION + METRICS
# ──────────────────────────────────────────────────────────────────────

def run_sim(events: List[TradeEvent], broker_specs: dict,
            profiles: dict = None) -> Dict[str, dict]:
    if profiles is None:
        profiles = TEST_PROFILES
    if not events:
        return {name: _empty_metrics() for name in profiles}
    states = run_simulation(events, broker_specs, profiles=profiles)

    results = {}
    for name, state in states.items():
        total = state.total_accepted + state.total_rejected
        rej_rate = (state.total_rejected / total * 100) if total > 0 else 0.0
        dd_pct = (state.max_drawdown_usd / state.peak_equity * 100) if state.peak_equity > 0 else 0.0
        gross_profit = sum(t["pnl_usd"] for t in state.closed_trades_log if t["pnl_usd"] > 0)
        gross_loss = abs(sum(t["pnl_usd"] for t in state.closed_trades_log if t["pnl_usd"] < 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        if hasattr(state, "concurrent_log") and state.concurrent_log:
            avg_conc = np.mean(state.concurrent_log)
            max_conc = max(state.concurrent_log)
        else:
            avg_conc = 0.0
            max_conc = state.max_concurrent

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
            "max_concurrent": max_conc,
            "final_equity": round(state.equity, 2),
            "sim_years": round(years, 2),
        }
    return results


def _empty_metrics() -> dict:
    return {
        "net_pnl": 0.0, "profit_factor": 0.0, "max_dd_pct": 0.0,
        "total_trades": 0, "total_rejected": 0, "execution_rate": 0.0,
        "rejection_rate_pct": 0.0, "avg_concurrent": 0.0,
        "max_concurrent": 0, "final_equity": 10000.0, "sim_years": 0.0,
    }


def select_best_profile(results: Dict[str, dict]) -> str:
    best_name = None
    best_score = -1e12
    for name, m in results.items():
        if m["net_pnl"] <= 0:
            continue
        dd_floor = max(abs(m["max_dd_pct"]), 0.01)
        score = m["net_pnl"] / dd_floor
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
    print(f"\n{'='*60}")
    print(f"  {portfolio_id}")
    print(f"{'='*60}")

    df = load_raw_trades(portfolio_id)
    broker_specs = get_broker_specs(df)
    n_trades = len(df)
    print(f"  Loaded {n_trades} raw trades, {df['symbol'].nunique()} symbols")

    # Family distribution
    families = df["trade_id"].apply(_extract_family)
    fam_dist = families.value_counts().to_dict()
    print(f"  Families: {dict(fam_dist)}")

    # ── Pass A: Baseline ──
    print("  [A] Baseline...")
    events_a = df_to_events(df)
    results_a = run_sim(events_a, broker_specs)
    profile_a = select_best_profile(results_a)
    print(f"      Best profile: {profile_a}")

    # ── Pass B: Post-trade filtering (PnL-derived) ──
    print("  [B] Post-trade filtering (PnL-derived)...")
    gates = derive_regime_affinity(df)
    active_gates_b = {k: v for k, v in gates.items()
                      if v["block_vol"] or v["block_trend"]}
    passed_b, blocked_b = apply_post_trade_filter(df, gates)
    n_blocked_b = len(blocked_b)
    blocked_pnl_b = blocked_b["pnl_usd"].sum() if len(blocked_b) > 0 else 0.0
    act_rate_b = len(passed_b) / n_trades * 100 if n_trades > 0 else 100.0
    print(f"      Blocked: {n_blocked_b} trades ({100 - act_rate_b:.1f}%), "
          f"blocked PnL: ${blocked_pnl_b:,.2f}")
    for prefix, g in active_gates_b.items():
        parts = []
        if g["block_vol"]:
            parts.append(f"vol={g['block_vol']}")
        if g["block_trend"]:
            parts.append(f"trend={g['block_trend']}")
        print(f"      {prefix}: {', '.join(parts)}")

    events_b = df_to_events(passed_b)
    results_b = run_sim(events_b, broker_specs)
    profile_b = select_best_profile(results_b)
    print(f"      Best profile: {profile_b}")

    # ── Pass C: Pre-trade activation (universal rules) ──
    print("  [C] Pre-trade activation (universal rules)...")
    active_c, inactive_c, diag_c = apply_activation_rules(df)
    n_blocked_c = len(inactive_c)
    blocked_pnl_c = inactive_c["pnl_usd"].sum() if len(inactive_c) > 0 else 0.0
    act_rate_c = len(active_c) / n_trades * 100 if n_trades > 0 else 100.0
    print(f"      Blocked: {n_blocked_c} trades ({100 - act_rate_c:.1f}%), "
          f"blocked PnL: ${blocked_pnl_c:,.2f}")
    for fam, reasons in diag_c.items():
        print(f"      {fam}: {reasons}")

    events_c = df_to_events(active_c)
    results_c = run_sim(events_c, broker_specs)
    profile_c = select_best_profile(results_c)
    print(f"      Best profile: {profile_c}")

    # ── Concurrency comparison ──
    conc_a = {p: results_a.get(p, {}).get("avg_concurrent", 0) for p in TEST_PROFILES}
    conc_c = {p: results_c.get(p, {}).get("avg_concurrent", 0) for p in TEST_PROFILES}

    # ── OOS Stability: 60/40 split for all three passes ──
    print("  [S] Stability (60/40 OOS)...")
    split_idx = int(len(df) * 0.6)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]
    n_test = len(df_test)

    # A: baseline on test
    events_test_a = df_to_events(df_test)
    results_test_a = run_sim(events_test_a, broker_specs)

    # B: derive gates on train, apply on test
    gates_train = derive_regime_affinity(df_train)
    passed_test_b, blocked_test_b = apply_post_trade_filter(df_test, gates_train)
    events_test_b = df_to_events(passed_test_b)
    results_test_b = run_sim(events_test_b, broker_specs)
    oos_blocked_b = len(blocked_test_b)
    oos_blocked_pnl_b = blocked_test_b["pnl_usd"].sum() if len(blocked_test_b) > 0 else 0.0

    # C: activation rules are universal (no train/test split needed — rules don't change)
    active_test_c, inactive_test_c, _ = apply_activation_rules(df_test)
    events_test_c = df_to_events(active_test_c)
    results_test_c = run_sim(events_test_c, broker_specs)
    oos_blocked_c = len(inactive_test_c)
    oos_blocked_pnl_c = inactive_test_c["pnl_usd"].sum() if len(inactive_test_c) > 0 else 0.0

    print(f"      OOS: {n_test} trades")
    print(f"        B blocked: {oos_blocked_b}, blocked PnL: ${oos_blocked_pnl_b:,.2f}")
    print(f"        C blocked: {oos_blocked_c}, blocked PnL: ${oos_blocked_pnl_c:,.2f}")

    # ── Assemble per-profile deltas ──
    profile_results = {}
    for pname in TEST_PROFILES:
        a = results_a.get(pname, _empty_metrics())
        b = results_b.get(pname, _empty_metrics())
        c = results_c.get(pname, _empty_metrics())
        ta = results_test_a.get(pname, _empty_metrics())
        tb = results_test_b.get(pname, _empty_metrics())
        tc = results_test_c.get(pname, _empty_metrics())

        # B vs A deltas (IS)
        d_pnl_b = b["net_pnl"] - a["net_pnl"]
        d_pf_b = b["profit_factor"] - a["profit_factor"]
        d_dd_b = b["max_dd_pct"] - a["max_dd_pct"]

        # C vs A deltas (IS)
        d_pnl_c = c["net_pnl"] - a["net_pnl"]
        d_pf_c = c["profit_factor"] - a["profit_factor"]
        d_dd_c = c["max_dd_pct"] - a["max_dd_pct"]
        d_trades_c = c["total_trades"] - a["total_trades"]

        # OOS deltas
        oos_d_pnl_b = tb["net_pnl"] - ta["net_pnl"]
        oos_d_pnl_c = tc["net_pnl"] - ta["net_pnl"]
        oos_d_pf_c = tc["profit_factor"] - ta["profit_factor"]
        oos_d_dd_c = tc["max_dd_pct"] - ta["max_dd_pct"]

        # Stability: IS and OOS same sign (or trivial change)
        oos_stable_b = (d_pnl_b >= 0 and oos_d_pnl_b >= 0) or \
                       (d_pnl_b < 0 and oos_d_pnl_b < 0) or \
                       abs(d_pnl_b) < 10
        oos_stable_c = (d_pnl_c >= 0 and oos_d_pnl_c >= 0) or \
                       (d_pnl_c < 0 and oos_d_pnl_c < 0) or \
                       abs(d_pnl_c) < 10

        # Concurrency
        conc_delta = c.get("avg_concurrent", 0) - a.get("avg_concurrent", 0)
        max_conc_delta = c.get("max_concurrent", 0) - a.get("max_concurrent", 0)

        profile_results[pname] = {
            "A": a, "B": b, "C": c,
            "OOS_A": ta, "OOS_B": tb, "OOS_C": tc,
            # B deltas
            "d_pnl_b": round(d_pnl_b, 2),
            "d_pf_b": round(d_pf_b, 2),
            "d_dd_b": round(d_dd_b, 2),
            "oos_d_pnl_b": round(oos_d_pnl_b, 2),
            "oos_stable_b": oos_stable_b,
            # C deltas
            "d_pnl_c": round(d_pnl_c, 2),
            "d_pf_c": round(d_pf_c, 2),
            "d_dd_c": round(d_dd_c, 2),
            "d_trades_c": d_trades_c,
            "oos_d_pnl_c": round(oos_d_pnl_c, 2),
            "oos_d_pf_c": round(oos_d_pf_c, 2),
            "oos_d_dd_c": round(oos_d_dd_c, 2),
            "oos_stable_c": oos_stable_c,
            # Concurrency
            "conc_delta": round(conc_delta, 2),
            "max_conc_delta": max_conc_delta,
        }

    return {
        "portfolio_id": portfolio_id,
        "type": "single_asset" if portfolio_id.startswith("PF_") else "multi_asset",
        "n_trades": n_trades,
        "family_distribution": fam_dist,
        # B summary
        "n_blocked_b": n_blocked_b,
        "blocked_pnl_b": round(blocked_pnl_b, 2),
        "activation_rate_b": round(act_rate_b, 1),
        "profile_b": profile_b,
        "gates_b": {k: {"block_vol": sorted(v["block_vol"]),
                        "block_trend": sorted(v["block_trend"])}
                    for k, v in active_gates_b.items()},
        # C summary
        "n_blocked_c": n_blocked_c,
        "blocked_pnl_c": round(blocked_pnl_c, 2),
        "activation_rate_c": round(act_rate_c, 1),
        "profile_c": profile_c,
        "activation_diag": diag_c,
        # Common
        "profile_a": profile_a,
        "profile_changed_b": profile_a != profile_b,
        "profile_changed_c": profile_a != profile_c,
        "profiles": profile_results,
        "stability": {
            "n_test": n_test,
            "oos_blocked_b": oos_blocked_b,
            "oos_blocked_pnl_b": round(oos_blocked_pnl_b, 2),
            "oos_blocked_c": oos_blocked_c,
            "oos_blocked_pnl_c": round(oos_blocked_pnl_c, 2),
        },
    }


# ──────────────────────────────────────────────────────────────────────
# AGGREGATE REPORT
# ──────────────────────────────────────────────────────────────────────

def print_report(all_results: List[dict]):
    print(f"\n{'='*100}")
    print("  ACTIVATION vs FILTERING — AGGREGATE REPORT")
    print(f"{'='*100}")

    # ── 1. Portfolio Table ──
    print(f"\n{'─'*100}")
    print("  1. PORTFOLIO TABLE (baseline profile per portfolio)")
    print(f"{'─'*100}")
    hdr = (f"  {'Portfolio':<36} "
           f"{'A PnL':>8} {'B PnL':>8} {'C PnL':>8} "
           f"{'dC-A':>8} {'dPF':>6} {'dDD%':>7} "
           f"{'%blkC':>6} {'OOS_B':>5} {'OOS_C':>5}")
    print(hdr)
    print(f"  {'─'*36} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*6} {'─'*7} {'─'*6} {'─'*5} {'─'*5}")

    # Accumulators
    n = len(all_results)
    c_improved_pnl = 0
    c_improved_pf = 0
    b_oos_stable = 0
    c_oos_stable = 0
    c_profile_changed = 0
    total_d_pnl_c = 0
    total_d_dd_c = 0
    total_d_pnl_b = 0
    c_conc_improved = 0
    c_trade_collapse = 0  # >50% trade reduction = collapse

    for r in all_results:
        pname = r["profile_a"] or list(TEST_PROFILES.keys())[0]
        pm = r["profiles"].get(pname, {})

        a_pnl = pm.get("A", {}).get("net_pnl", 0)
        b_pnl = pm.get("B", {}).get("net_pnl", 0)
        c_pnl = pm.get("C", {}).get("net_pnl", 0)
        d_pnl_c = pm.get("d_pnl_c", 0)
        d_pf_c = pm.get("d_pf_c", 0)
        d_dd_c = pm.get("d_dd_c", 0)
        d_pnl_b = pm.get("d_pnl_b", 0)
        pct_blk_c = 100.0 - r["activation_rate_c"]
        oos_b = "PASS" if pm.get("oos_stable_b") else "FAIL"
        oos_c = "PASS" if pm.get("oos_stable_c") else "FAIL"

        total_d_pnl_c += d_pnl_c
        total_d_dd_c += d_dd_c
        total_d_pnl_b += d_pnl_b
        if d_pnl_c > 0:
            c_improved_pnl += 1
        if d_pf_c > 0:
            c_improved_pf += 1
        if pm.get("oos_stable_b"):
            b_oos_stable += 1
        if pm.get("oos_stable_c"):
            c_oos_stable += 1
        if r["profile_changed_c"]:
            c_profile_changed += 1
        if pm.get("conc_delta", 0) < 0:
            c_conc_improved += 1
        d_trades = pm.get("d_trades_c", 0)
        a_trades = pm.get("A", {}).get("total_trades", 1)
        if a_trades > 0 and abs(d_trades) > a_trades * 0.5:
            c_trade_collapse += 1

        print(f"  {r['portfolio_id']:<36} "
              f"{a_pnl:>+8.0f} {b_pnl:>+8.0f} {c_pnl:>+8.0f} "
              f"{d_pnl_c:>+8.0f} {d_pf_c:>+6.2f} {d_dd_c:>+7.2f} "
              f"{pct_blk_c:>6.1f} {oos_b:>5} {oos_c:>5}")

    # ── 2. Aggregate Summary ──
    print(f"\n{'─'*100}")
    print("  2. AGGREGATE SUMMARY")
    print(f"{'─'*100}")
    print(f"  Portfolios tested:              {n}")
    if n == 0:
        print("  [NO RESULTS]")
        return

    print(f"")
    print(f"  --- Post-Trade Filtering (B) ---")
    print(f"  Avg delta PnL (B-A):            ${total_d_pnl_b/n:+,.2f}")
    print(f"  OOS stable:                     {b_oos_stable}/{n} ({b_oos_stable/n*100:.0f}%)")
    print(f"")
    print(f"  --- Pre-Trade Activation (C) ---")
    print(f"  PnL improved (C > A):           {c_improved_pnl}/{n} ({c_improved_pnl/n*100:.0f}%)")
    print(f"  PF improved (C > A):            {c_improved_pf}/{n} ({c_improved_pf/n*100:.0f}%)")
    print(f"  Avg delta PnL (C-A):            ${total_d_pnl_c/n:+,.2f}")
    print(f"  Avg delta DD%:                  {total_d_dd_c/n:+.2f}pp")
    print(f"  OOS stable:                     {c_oos_stable}/{n} ({c_oos_stable/n*100:.0f}%)")
    print(f"  Profile changed:                {c_profile_changed}/{n} ({c_profile_changed/n*100:.0f}%)")
    print(f"  Concurrency improved:           {c_conc_improved}/{n}")
    print(f"  Trade collapse (>50% drop):     {c_trade_collapse}/{n}")

    # ── 3. Head-to-Head: B vs C ──
    print(f"\n{'─'*100}")
    print("  3. HEAD-TO-HEAD: B (filter) vs C (activation)")
    print(f"{'─'*100}")
    print(f"  OOS stability:  B={b_oos_stable}/{n}  vs  C={c_oos_stable}/{n}  "
          f"{'C WINS' if c_oos_stable > b_oos_stable else 'B WINS' if b_oos_stable > c_oos_stable else 'TIE'}")
    print(f"  IS avg dPnL:    B=${total_d_pnl_b/n:+,.0f}  vs  C=${total_d_pnl_c/n:+,.0f}")

    # ── 4. Key Questions ──
    print(f"\n{'─'*100}")
    print("  4. KEY QUESTIONS")
    print(f"{'─'*100}")

    c_improves = c_improved_pnl / n >= 0.4
    c_avoids_flip = c_oos_stable > b_oos_stable
    conc_helps = c_conc_improved / n >= 0.3
    profile_stable = c_profile_changed / n <= 0.2
    consistent = c_improved_pnl / n >= 0.5
    no_collapse = c_trade_collapse == 0

    print(f"  Does C improve PF/DD like B?            {'YES' if c_improves else 'NO'} "
          f"({c_improved_pnl}/{n} improved)")
    print(f"  Does C avoid OOS sign flip of B?        {'YES' if c_avoids_flip else 'NO'} "
          f"(B={b_oos_stable}/{n} vs C={c_oos_stable}/{n})")
    print(f"  Does C reduce concurrency?              {'YES' if conc_helps else 'NO'} "
          f"({c_conc_improved}/{n})")
    print(f"  Does C change profile selection?         {'NO (good)' if profile_stable else 'YES (concerning)'} "
          f"({c_profile_changed}/{n})")
    print(f"  Is improvement consistent?              {'YES' if consistent else 'NO'} "
          f"({c_improved_pnl}/{n})")
    print(f"  Trade count stable (no collapse)?       {'YES' if no_collapse else 'NO'} "
          f"({c_trade_collapse}/{n} collapsed)")

    # ── 5. Final Verdict ──
    print(f"\n{'─'*100}")
    print("  5. FINAL VERDICT")
    print(f"{'─'*100}")

    c_stable_rate = c_oos_stable / n
    if c_avoids_flip and c_stable_rate >= 0.7 and no_collapse:
        print("  => PROMOTE: Pre-trade activation is stable and improves outcomes.")
        print("     Integrate as Stage 4 with universal family×regime rules.")
    elif c_avoids_flip and c_stable_rate >= 0.5 and no_collapse:
        print("  => LIMITED: Activation shows better stability than filtering but needs monitoring.")
        print("     Deploy as diagnostic + soft activation layer.")
    elif c_stable_rate > b_oos_stable / n:
        print("  => MARGINAL: Activation is more stable than filtering but insufficient for integration.")
        print("     Keep as research finding; revisit with more data or refined rules.")
    else:
        print("  => REJECT: Pre-trade activation does not demonstrate sufficient advantage.")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 100)
    print("  STRATEGY ACTIVATION (PRE-TRADE) vs REGIME FILTERING (POST-TRADE)")
    print("=" * 100)

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
    out_path = output_dir / "activation_vs_filtering.json"

    def _ser(obj):
        if isinstance(obj, set):
            return sorted(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, Counter):
            return dict(obj)
        return str(obj)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=_ser)
    print(f"\n  Raw results saved: {out_path}")

    print_report(all_results)


if __name__ == "__main__":
    main()
