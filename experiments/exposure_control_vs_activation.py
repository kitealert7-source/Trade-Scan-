"""
Exposure Control (D) vs Binary Activation (C) vs Baseline (A)
==============================================================

Instead of binary OFF for REV/MR in disallowed regimes, D applies a
family-level concurrency cap of 1. Trades still participate, but only
one position per family is allowed at a time in flagged regime states.

This preserves participation in mixed-edge regimes while limiting
drawdown exposure from concurrent adverse positions.

Passes:
  A: Baseline         — all trades, no regime logic
  C: Binary Activation — universal rules, OFF in disallowed regimes
  D: Exposure Control  — universal rules, max_concurrent=1 per family
                         in disallowed regimes (all others uncapped)

The exposure cap is applied pre-simulation by scheduling: trades are
processed in entry order, and for flagged family×regime combos, excess
concurrent trades are removed from the dataset before capital simulation.

Usage: python experiments/exposure_control_vs_activation.py
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
# UNIVERSAL RULES (same as activation_vs_filtering.py)
# ──────────────────────────────────────────────────────────────────────

_VOL_ACTIVE = {
    "TREND": {"normal", "high"},
    "STR":   {"normal", "high"},
    "REV":   {"low", "normal"},
    "MR":    {"low", "normal"},
}

_TREND_ACTIVE = {
    "REV":  {"neutral", "weak_up", "weak_down"},
    "MR":   {"neutral", "weak_up", "weak_down"},
}

# Families subject to exposure cap (instead of binary OFF) in test D
_EXPOSURE_CAP_FAMILIES = {"REV", "MR"}

# Max concurrent positions per family in disallowed regimes
_MAX_CONCURRENT_FLAGGED = 1

_VOL_INT_MAP = {
    "-1": "low", "-1.0": "low",
    "0": "normal", "0.0": "normal",
    "1": "high", "1.0": "high",
}


def _normalize_vol(raw) -> str:
    s = str(raw).strip().lower()
    if s in ("low", "normal", "high"):
        return s
    return _VOL_INT_MAP.get(s, "")


def _normalize_trend(raw) -> str:
    return str(raw).strip().lower()


def _extract_family(trade_id: str) -> str:
    base = trade_id.split("|")[0]
    parts = base.split("_")
    if parts[0] == "C" and len(parts) >= 3:
        return parts[2].upper()
    if len(parts) >= 2:
        return parts[1].upper()
    return "UNKNOWN"


def _is_flagged_regime(family: str, vol: str, trend: str) -> bool:
    """Check if this family×regime combo would be BLOCKED in binary activation (C)."""
    vol_allowed = _VOL_ACTIVE.get(family)
    if vol_allowed is not None and vol and vol not in vol_allowed:
        return True
    trend_allowed = _TREND_ACTIVE.get(family)
    if trend_allowed is not None and trend and trend not in trend_allowed:
        return True
    return False


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
# BINARY ACTIVATION (Test C) — identical to previous experiment
# ──────────────────────────────────────────────────────────────────────

def apply_binary_activation(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Binary OFF for flagged family×regime combos. Returns (active, inactive, diag)."""
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)
    df["vol_norm"] = df["volatility_regime"].apply(_normalize_vol)
    df["trend_norm"] = df["trend_label"].apply(_normalize_trend)

    inactive_mask = pd.Series(False, index=df.index)
    block_reasons = []

    for idx, row in df.iterrows():
        if _is_flagged_regime(row["family"], row["vol_norm"], row["trend_norm"]):
            inactive_mask.at[idx] = True
            vol = row["vol_norm"]
            trend = row["trend_norm"]
            vol_allowed = _VOL_ACTIVE.get(row["family"])
            if vol_allowed is not None and vol and vol not in vol_allowed:
                block_reasons.append((row["family"], f"vol={vol}"))
            else:
                block_reasons.append((row["family"], f"trend={trend}"))

    drop_cols = ["family", "vol_norm", "trend_norm"]
    active = df[~inactive_mask].drop(columns=drop_cols)
    inactive = df[inactive_mask].drop(columns=drop_cols)

    diag = {}
    for fam, reason in block_reasons:
        diag.setdefault(fam, Counter())[reason] += 1
    diag = {fam: dict(counts) for fam, counts in diag.items()}

    return active, inactive, diag


# ──────────────────────────────────────────────────────────────────────
# EXPOSURE CONTROL (Test D) — max_concurrent=1 per family in flagged regimes
# ──────────────────────────────────────────────────────────────────────

def apply_exposure_control(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Soft exposure control: in flagged regimes, limit each family to
    max_concurrent=1 position at a time. Non-flagged trades pass freely.

    Uses greedy scheduling: process trades in entry order, track open
    positions per family, skip trades that would exceed the cap.

    Returns: (passed_df, limited_df, diagnostics)
    """
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)
    df["vol_norm"] = df["volatility_regime"].apply(_normalize_vol)
    df["trend_norm"] = df["trend_label"].apply(_normalize_trend)
    df["flagged"] = df.apply(
        lambda r: _is_flagged_regime(r["family"], r["vol_norm"], r["trend_norm"]),
        axis=1,
    )

    # Only apply exposure cap to _EXPOSURE_CAP_FAMILIES (REV, MR)
    # Other families in flagged regimes (TREND, STR) remain binary OFF
    # (they have fewer trades in flagged states and the structural logic is clearer)
    df["cap_eligible"] = df["flagged"] & df["family"].isin(_EXPOSURE_CAP_FAMILIES)

    # For trades that are flagged but NOT cap-eligible (e.g. TREND in vol=low),
    # keep binary OFF behavior
    df["binary_block"] = df["flagged"] & ~df["cap_eligible"]

    # Sort by entry time for scheduling
    df = df.sort_values("entry_ts").reset_index(drop=True)

    # Track open positions per family for cap-eligible trades
    # Key: family, Value: list of exit_ts for currently open trades
    open_positions: Dict[str, List[datetime]] = {}
    limited_mask = pd.Series(False, index=df.index)
    limit_reasons = []

    for idx, row in df.iterrows():
        # Binary block (non-cap-eligible flagged trades)
        if row["binary_block"]:
            limited_mask.at[idx] = True
            limit_reasons.append((row["family"], "binary_off"))
            continue

        # Not flagged at all → pass freely
        if not row["cap_eligible"]:
            continue

        # Cap-eligible: check concurrent positions for this family
        family = row["family"]
        entry_ts = row["entry_ts"]

        # Clean expired positions
        if family not in open_positions:
            open_positions[family] = []
        open_positions[family] = [
            exit_ts for exit_ts in open_positions[family]
            if exit_ts > entry_ts
        ]

        # Check cap
        if len(open_positions[family]) >= _MAX_CONCURRENT_FLAGGED:
            limited_mask.at[idx] = True
            limit_reasons.append((family, "exposure_cap"))
        else:
            open_positions[family].append(row["exit_ts"])

    drop_cols = ["family", "vol_norm", "trend_norm", "flagged",
                 "cap_eligible", "binary_block"]
    passed = df[~limited_mask].drop(columns=drop_cols)
    limited = df[limited_mask].drop(columns=drop_cols)

    # Diagnostics
    diag = {"exposure_capped": {}, "binary_blocked": {}}
    for fam, reason in limit_reasons:
        if reason == "exposure_cap":
            diag["exposure_capped"].setdefault(fam, 0)
            diag["exposure_capped"][fam] += 1
        else:
            diag["binary_blocked"].setdefault(fam, 0)
            diag["binary_blocked"][fam] += 1

    # Concurrency stats for flagged trades that passed
    passed_flagged = df[(~limited_mask) & df["cap_eligible"]]
    diag["n_passed_flagged"] = len(passed_flagged)
    diag["n_total_flagged"] = int(df["cap_eligible"].sum())
    diag["n_binary_blocked"] = int(df["binary_block"].sum())

    return passed, limited, diag


def compute_family_concurrency(df: pd.DataFrame) -> Dict[str, dict]:
    """Compute avg/max concurrent per family (diagnostic for D vs A comparison)."""
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)

    stats = {}
    for fam in df["family"].unique():
        fam_df = df[df["family"] == fam].sort_values("entry_ts")
        if len(fam_df) == 0:
            continue

        # Sweep timeline to count concurrent
        events = []
        for _, row in fam_df.iterrows():
            events.append((row["entry_ts"], 1))
            events.append((row["exit_ts"], -1))
        events.sort(key=lambda x: x[0])

        concurrent = 0
        max_conc = 0
        conc_samples = []
        for _, delta in events:
            concurrent += delta
            conc_samples.append(concurrent)
            max_conc = max(max_conc, concurrent)

        stats[fam] = {
            "n_trades": len(fam_df),
            "avg_concurrent": round(np.mean(conc_samples), 2),
            "max_concurrent": max_conc,
        }
    return stats


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
    families = df["trade_id"].apply(_extract_family)
    fam_dist = families.value_counts().to_dict()
    print(f"  Loaded {n_trades} raw trades, {df['symbol'].nunique()} symbols")
    print(f"  Families: {dict(fam_dist)}")

    # Family concurrency on baseline (A)
    conc_a = compute_family_concurrency(df)

    # ── Pass A: Baseline ──
    print("  [A] Baseline...")
    events_a = df_to_events(df)
    results_a = run_sim(events_a, broker_specs)
    profile_a = select_best_profile(results_a)
    print(f"      Best profile: {profile_a}")
    if conc_a:
        for fam, cs in sorted(conc_a.items()):
            print(f"      {fam}: avg_conc={cs['avg_concurrent']}, max_conc={cs['max_concurrent']}")

    # ── Pass C: Binary Activation ──
    print("  [C] Binary Activation...")
    active_c, inactive_c, diag_c = apply_binary_activation(df)
    n_blocked_c = len(inactive_c)
    blocked_pnl_c = inactive_c["pnl_usd"].sum() if len(inactive_c) > 0 else 0.0
    act_rate_c = len(active_c) / n_trades * 100 if n_trades > 0 else 100.0
    print(f"      Blocked: {n_blocked_c} trades ({100 - act_rate_c:.1f}%), "
          f"blocked PnL: ${blocked_pnl_c:,.2f}")

    events_c = df_to_events(active_c)
    results_c = run_sim(events_c, broker_specs)
    profile_c = select_best_profile(results_c)
    print(f"      Best profile: {profile_c}")

    # Family concurrency on C
    conc_c = compute_family_concurrency(active_c)

    # ── Pass D: Exposure Control ──
    print("  [D] Exposure Control (max_concurrent=1 in flagged regimes)...")
    passed_d, limited_d, diag_d = apply_exposure_control(df)
    n_limited_d = len(limited_d)
    limited_pnl_d = limited_d["pnl_usd"].sum() if len(limited_d) > 0 else 0.0
    act_rate_d = len(passed_d) / n_trades * 100 if n_trades > 0 else 100.0
    print(f"      Limited: {n_limited_d} trades ({100 - act_rate_d:.1f}%), "
          f"limited PnL: ${limited_pnl_d:,.2f}")
    if diag_d["exposure_capped"]:
        print(f"      Exposure-capped: {diag_d['exposure_capped']}")
    if diag_d["binary_blocked"]:
        print(f"      Binary-blocked (TREND/STR): {diag_d['binary_blocked']}")
    print(f"      Flagged trades passed: {diag_d['n_passed_flagged']}/{diag_d['n_total_flagged']}")

    events_d = df_to_events(passed_d)
    results_d = run_sim(events_d, broker_specs)
    profile_d = select_best_profile(results_d)
    print(f"      Best profile: {profile_d}")

    # Family concurrency on D
    conc_d = compute_family_concurrency(passed_d)

    # ── OOS Stability: 60/40 split ──
    print("  [S] Stability (60/40 OOS)...")
    split_idx = int(len(df) * 0.6)
    df_train = df.iloc[:split_idx].copy()
    df_test = df.iloc[split_idx:].copy()
    n_test = len(df_test)

    # A on test
    events_test_a = df_to_events(df_test)
    results_test_a = run_sim(events_test_a, broker_specs)

    # C on test (universal rules — no train dependency)
    active_test_c, _, _ = apply_binary_activation(df_test)
    events_test_c = df_to_events(active_test_c)
    results_test_c = run_sim(events_test_c, broker_specs)

    # D on test (universal rules — no train dependency)
    passed_test_d, limited_test_d, _ = apply_exposure_control(df_test)
    events_test_d = df_to_events(passed_test_d)
    results_test_d = run_sim(events_test_d, broker_specs)

    oos_blocked_c = len(df_test) - len(active_test_c)
    oos_limited_d = len(limited_test_d)
    print(f"      OOS: {n_test} trades, C blocked {oos_blocked_c}, D limited {oos_limited_d}")

    # ── Assemble per-profile results ──
    profile_results = {}
    for pname in TEST_PROFILES:
        a = results_a.get(pname, _empty_metrics())
        c = results_c.get(pname, _empty_metrics())
        d = results_d.get(pname, _empty_metrics())
        ta = results_test_a.get(pname, _empty_metrics())
        tc = results_test_c.get(pname, _empty_metrics())
        td = results_test_d.get(pname, _empty_metrics())

        # IS deltas
        d_pnl_c = c["net_pnl"] - a["net_pnl"]
        d_pnl_d = d["net_pnl"] - a["net_pnl"]
        d_pf_d = d["profit_factor"] - a["profit_factor"]
        d_dd_d = d["max_dd_pct"] - a["max_dd_pct"]
        d_trades_d = d["total_trades"] - a["total_trades"]

        # OOS deltas
        oos_d_pnl_c = tc["net_pnl"] - ta["net_pnl"]
        oos_d_pnl_d = td["net_pnl"] - ta["net_pnl"]
        oos_d_pf_d = td["profit_factor"] - ta["profit_factor"]
        oos_d_dd_d = td["max_dd_pct"] - ta["max_dd_pct"]

        # Stability checks
        oos_stable_c = (d_pnl_c >= 0 and oos_d_pnl_c >= 0) or \
                       (d_pnl_c < 0 and oos_d_pnl_c < 0) or \
                       abs(d_pnl_c) < 10
        oos_stable_d = (d_pnl_d >= 0 and oos_d_pnl_d >= 0) or \
                       (d_pnl_d < 0 and oos_d_pnl_d < 0) or \
                       abs(d_pnl_d) < 10

        # Concurrency deltas (D vs A)
        conc_delta_d = d.get("avg_concurrent", 0) - a.get("avg_concurrent", 0)

        # PnL recovered (D vs C)
        pnl_recovered = d["net_pnl"] - c["net_pnl"]

        profile_results[pname] = {
            "A": a, "C": c, "D": d,
            "OOS_A": ta, "OOS_C": tc, "OOS_D": td,
            "d_pnl_c": round(d_pnl_c, 2),
            "d_pnl_d": round(d_pnl_d, 2),
            "d_pf_d": round(d_pf_d, 2),
            "d_dd_d": round(d_dd_d, 2),
            "d_trades_d": d_trades_d,
            "oos_d_pnl_c": round(oos_d_pnl_c, 2),
            "oos_d_pnl_d": round(oos_d_pnl_d, 2),
            "oos_d_pf_d": round(oos_d_pf_d, 2),
            "oos_d_dd_d": round(oos_d_dd_d, 2),
            "oos_stable_c": oos_stable_c,
            "oos_stable_d": oos_stable_d,
            "conc_delta_d": round(conc_delta_d, 2),
            "pnl_recovered": round(pnl_recovered, 2),
        }

    return {
        "portfolio_id": portfolio_id,
        "type": "single_asset" if portfolio_id.startswith("PF_") else "multi_asset",
        "n_trades": n_trades,
        "family_distribution": fam_dist,
        # C summary
        "n_blocked_c": n_blocked_c,
        "blocked_pnl_c": round(blocked_pnl_c, 2),
        "activation_rate_c": round(act_rate_c, 1),
        "profile_c": profile_c,
        # D summary
        "n_limited_d": n_limited_d,
        "limited_pnl_d": round(limited_pnl_d, 2),
        "activation_rate_d": round(act_rate_d, 1),
        "profile_d": profile_d,
        "exposure_diag": diag_d,
        # Common
        "profile_a": profile_a,
        "profile_changed_c": profile_a != profile_c,
        "profile_changed_d": profile_a != profile_d,
        "profiles": profile_results,
        # Concurrency
        "concurrency_a": conc_a,
        "concurrency_c": conc_c,
        "concurrency_d": conc_d,
        # OOS
        "stability": {
            "n_test": n_test,
            "oos_blocked_c": oos_blocked_c,
            "oos_limited_d": oos_limited_d,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# AGGREGATE REPORT
# ──────────────────────────────────────────────────────────────────────

def print_report(all_results: List[dict]):
    print(f"\n{'='*110}")
    print("  EXPOSURE CONTROL vs BINARY ACTIVATION — AGGREGATE REPORT")
    print(f"{'='*110}")

    # ── 1. Portfolio Table ──
    print(f"\n{'─'*110}")
    print("  1. PORTFOLIO TABLE (baseline profile per portfolio)")
    print(f"{'─'*110}")
    hdr = (f"  {'Portfolio':<36} "
           f"{'A PnL':>9} {'C PnL':>9} {'D PnL':>9} "
           f"{'dD-A':>8} {'dPF':>6} {'dDD%':>7} "
           f"{'%limD':>6} {'OOS_C':>5} {'OOS_D':>5}")
    print(hdr)
    print(f"  {'─'*36} {'─'*9} {'─'*9} {'─'*9} {'─'*8} {'─'*6} {'─'*7} {'─'*6} {'─'*5} {'─'*5}")

    n = len(all_results)
    d_improved_pnl = 0
    d_improved_pf = 0
    c_oos_stable = 0
    d_oos_stable = 0
    d_profile_changed = 0
    total_d_pnl_d = 0
    total_d_dd_d = 0
    total_pnl_recovered = 0
    d_dd_improved = 0
    d_trade_collapse = 0

    for r in all_results:
        pname = r["profile_a"] or list(TEST_PROFILES.keys())[0]
        pm = r["profiles"].get(pname, {})

        a_pnl = pm.get("A", {}).get("net_pnl", 0)
        c_pnl = pm.get("C", {}).get("net_pnl", 0)
        d_pnl = pm.get("D", {}).get("net_pnl", 0)
        d_pnl_d = pm.get("d_pnl_d", 0)
        d_pf_d = pm.get("d_pf_d", 0)
        d_dd_d = pm.get("d_dd_d", 0)
        pct_lim = 100.0 - r["activation_rate_d"]
        oos_c = "PASS" if pm.get("oos_stable_c") else "FAIL"
        oos_d = "PASS" if pm.get("oos_stable_d") else "FAIL"
        pnl_rec = pm.get("pnl_recovered", 0)

        total_d_pnl_d += d_pnl_d
        total_d_dd_d += d_dd_d
        total_pnl_recovered += pnl_rec
        if d_pnl_d > 0:
            d_improved_pnl += 1
        if d_pf_d > 0:
            d_improved_pf += 1
        if d_dd_d < 0:
            d_dd_improved += 1
        if pm.get("oos_stable_c"):
            c_oos_stable += 1
        if pm.get("oos_stable_d"):
            d_oos_stable += 1
        if r["profile_changed_d"]:
            d_profile_changed += 1
        d_trades = pm.get("d_trades_d", 0)
        a_trades = pm.get("A", {}).get("total_trades", 1)
        if a_trades > 0 and abs(d_trades) > a_trades * 0.3:
            d_trade_collapse += 1

        print(f"  {r['portfolio_id']:<36} "
              f"{a_pnl:>+9.0f} {c_pnl:>+9.0f} {d_pnl:>+9.0f} "
              f"{d_pnl_d:>+8.0f} {d_pf_d:>+6.2f} {d_dd_d:>+7.2f} "
              f"{pct_lim:>6.1f} {oos_c:>5} {oos_d:>5}")

    # ── 2. PnL Recovery ──
    print(f"\n{'─'*110}")
    print("  2. PnL RECOVERY (D vs C)")
    print(f"{'─'*110}")
    for r in all_results:
        pname = r["profile_a"] or list(TEST_PROFILES.keys())[0]
        pm = r["profiles"].get(pname, {})
        c_pnl = pm.get("C", {}).get("net_pnl", 0)
        d_pnl = pm.get("D", {}).get("net_pnl", 0)
        a_pnl = pm.get("A", {}).get("net_pnl", 0)
        rec = d_pnl - c_pnl
        lost_c = a_pnl - c_pnl
        pct_rec = (rec / lost_c * 100) if abs(lost_c) > 1 else 0.0
        print(f"  {r['portfolio_id']:<36}  C lost ${lost_c:>+9.0f} vs A  |  "
              f"D recovered ${rec:>+8.0f}  ({pct_rec:>5.1f}%)")

    # ── 3. Concurrency Comparison ──
    print(f"\n{'─'*110}")
    print("  3. CONCURRENCY (REV/MR families: A vs C vs D)")
    print(f"{'─'*110}")
    for r in all_results:
        ca = r.get("concurrency_a", {})
        cc = r.get("concurrency_c", {})
        cd = r.get("concurrency_d", {})
        rev_mr_fams = [f for f in ("REV", "MR") if f in ca]
        if not rev_mr_fams:
            continue
        print(f"  {r['portfolio_id']}")
        for fam in rev_mr_fams:
            a_mc = ca.get(fam, {}).get("max_concurrent", 0)
            a_ac = ca.get(fam, {}).get("avg_concurrent", 0)
            c_mc = cc.get(fam, {}).get("max_concurrent", 0)
            c_ac = cc.get(fam, {}).get("avg_concurrent", 0)
            d_mc = cd.get(fam, {}).get("max_concurrent", 0)
            d_ac = cd.get(fam, {}).get("avg_concurrent", 0)
            print(f"    {fam:>5}: A(avg={a_ac:.1f}, max={a_mc})  "
                  f"C(avg={c_ac:.1f}, max={c_mc})  "
                  f"D(avg={d_ac:.1f}, max={d_mc})")

    # ── 4. Aggregate Summary ──
    print(f"\n{'─'*110}")
    print("  4. AGGREGATE SUMMARY")
    print(f"{'─'*110}")
    print(f"  Portfolios tested:              {n}")
    if n == 0:
        print("  [NO RESULTS]")
        return

    print(f"")
    print(f"  --- Binary Activation (C) ---")
    print(f"  OOS stable:                     {c_oos_stable}/{n} ({c_oos_stable/n*100:.0f}%)")
    print(f"")
    print(f"  --- Exposure Control (D) ---")
    print(f"  PnL improved (D > A):           {d_improved_pnl}/{n} ({d_improved_pnl/n*100:.0f}%)")
    print(f"  PF improved (D > A):            {d_improved_pf}/{n} ({d_improved_pf/n*100:.0f}%)")
    print(f"  DD improved (D < A):            {d_dd_improved}/{n} ({d_dd_improved/n*100:.0f}%)")
    print(f"  Avg delta PnL (D-A):            ${total_d_pnl_d/n:+,.2f}")
    print(f"  Avg delta DD%:                  {total_d_dd_d/n:+.2f}pp")
    print(f"  OOS stable:                     {d_oos_stable}/{n} ({d_oos_stable/n*100:.0f}%)")
    print(f"  Profile changed:                {d_profile_changed}/{n} ({d_profile_changed/n*100:.0f}%)")
    print(f"  Trade collapse (>30% drop):     {d_trade_collapse}/{n}")
    print(f"  Total PnL recovered (D-C):      ${total_pnl_recovered:+,.2f}")

    # ── 5. Key Questions ──
    print(f"\n{'─'*110}")
    print("  5. KEY QUESTIONS")
    print(f"{'─'*110}")

    d_recovers = total_pnl_recovered > 0
    d_oos_target = d_oos_stable / n >= 0.7
    d_dd_ok = d_dd_improved / n >= 0.4
    no_collapse = d_trade_collapse == 0
    profile_stable = d_profile_changed / n <= 0.2

    print(f"  Does D recover PnL lost in C?           {'YES' if d_recovers else 'NO'} "
          f"(${total_pnl_recovered:+,.0f})")
    print(f"  Does D maintain OOS stability (>=70%)?  {'YES' if d_oos_target else 'NO'} "
          f"({d_oos_stable}/{n} = {d_oos_stable/n*100:.0f}%)")
    print(f"  Does D reduce DD vs A?                  {'YES' if d_dd_ok else 'MIXED'} "
          f"({d_dd_improved}/{n})")
    print(f"  No severe trade collapse (<30%)?        {'YES' if no_collapse else 'NO'} "
          f"({d_trade_collapse}/{n})")
    print(f"  Profile selection stable?               {'YES' if profile_stable else 'NO'} "
          f"({d_profile_changed}/{n})")

    # ── 6. Final Verdict ──
    print(f"\n{'─'*110}")
    print("  6. FINAL VERDICT")
    print(f"{'─'*110}")

    d_stable_rate = d_oos_stable / n
    if d_oos_target and d_recovers and no_collapse:
        print("  => PROMOTE: Exposure control is stable, recovers PnL, and safe for integration.")
        print("     Implement as Stage 4 with family-level concurrency caps in flagged regimes.")
    elif d_stable_rate >= 0.6 and d_recovers and no_collapse:
        print("  => LIMITED: Exposure control shows promise but needs more validation.")
        print("     Deploy as diagnostic layer with optional enforcement.")
    elif d_stable_rate > c_oos_stable / n:
        print("  => MARGINAL: Better than binary activation but insufficient for integration.")
    else:
        print("  => REJECT: Exposure control does not improve on binary activation.")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 110)
    print("  EXPOSURE CONTROL vs BINARY ACTIVATION — STRUCTURAL TEST")
    print("=" * 110)

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
    out_path = output_dir / "exposure_control_vs_activation.json"

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
