"""
Concurrency Diagnostics — Attribution Test
============================================

Determines whether exposure control benefit comes from:
  (a) TREND blocking in vol=low, or
  (b) REV/MR concurrency cap, or
  (c) their interaction

Four variants:
  A:  Baseline (no regime logic)
  D1: TREND block only (no REV/MR cap)
  D2: REV/MR cap only (no TREND block)
  D3: Full system (TREND block + REV/MR cap = previous test D)

Also produces:
  - Per-family concurrency profiles (avg, max, distribution)
  - Cross-family overlap/conflict matrix
  - OOS stability per variant

Usage: python experiments/concurrency_diagnostics.py
"""

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from collections import Counter, defaultdict

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
# REGIME RULES (same as previous experiments)
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

_EXPOSURE_CAP_FAMILIES = {"REV", "MR"}
_TREND_BLOCK_FAMILIES = {"TREND", "STR"}
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


def _is_vol_flagged(family: str, vol: str) -> bool:
    vol_allowed = _VOL_ACTIVE.get(family)
    return vol_allowed is not None and vol != "" and vol not in vol_allowed


def _is_trend_flagged(family: str, trend: str) -> bool:
    trend_allowed = _TREND_ACTIVE.get(family)
    return trend_allowed is not None and trend != "" and trend not in trend_allowed


def _is_flagged(family: str, vol: str, trend: str) -> bool:
    return _is_vol_flagged(family, vol) or _is_trend_flagged(family, trend)


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


def enrich_df(df: pd.DataFrame) -> pd.DataFrame:
    """Add family, vol_norm, trend_norm columns."""
    df = df.copy()
    df["family"] = df["trade_id"].apply(_extract_family)
    df["vol_norm"] = df["volatility_regime"].apply(_normalize_vol)
    df["trend_norm"] = df["trend_label"].apply(_normalize_trend)
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
# STEP 1 — CONCURRENCY PROFILING
# ──────────────────────────────────────────────────────────────────────

def compute_concurrency_profile(df: pd.DataFrame) -> dict:
    """
    Compute detailed concurrency stats: total and per-family.
    Returns {
        "total": {"avg": float, "max": int, "distribution": {n: count}},
        "per_family": {family: {"avg": float, "max": int, "n_trades": int}},
    }
    """
    df = df.sort_values("entry_ts")

    # --- Total concurrency timeline ---
    events = []
    for _, row in df.iterrows():
        events.append((row["entry_ts"], 1, row.get("family", "?")))
        events.append((row["exit_ts"], -1, row.get("family", "?")))
    events.sort(key=lambda x: (x[0], x[1]))  # exits before entries at same ts

    total_conc = 0
    total_samples = []
    for _, delta, _ in events:
        total_conc += delta
        total_samples.append(max(total_conc, 0))

    total_dist = Counter(total_samples)

    # --- Per-family concurrency ---
    families = df["family"].unique() if "family" in df.columns else []
    per_family = {}
    for fam in families:
        fam_df = df[df["family"] == fam].sort_values("entry_ts")
        if len(fam_df) == 0:
            continue
        fam_events = []
        for _, row in fam_df.iterrows():
            fam_events.append((row["entry_ts"], 1))
            fam_events.append((row["exit_ts"], -1))
        fam_events.sort(key=lambda x: (x[0], x[1]))

        conc = 0
        samples = []
        for _, delta in fam_events:
            conc += delta
            samples.append(max(conc, 0))

        per_family[fam] = {
            "n_trades": len(fam_df),
            "avg_concurrent": round(np.mean(samples), 2) if samples else 0.0,
            "max_concurrent": max(samples) if samples else 0,
            "distribution": dict(Counter(samples)),
        }

    return {
        "total": {
            "avg": round(np.mean(total_samples), 2) if total_samples else 0.0,
            "max": max(total_samples) if total_samples else 0,
            "distribution": dict(total_dist),
        },
        "per_family": per_family,
    }


# ──────────────────────────────────────────────────────────────────────
# STEP 2 — CROSS-FAMILY CONFLICT MATRIX
# ──────────────────────────────────────────────────────────────────────

def compute_conflict_matrix(df: pd.DataFrame) -> dict:
    """
    Count how often trades from family_i and family_j overlap in time.
    Returns {(fam_i, fam_j): overlap_count} as a dict with string keys.
    """
    df = df.sort_values("entry_ts")
    families = sorted(df["family"].unique()) if "family" in df.columns else []

    if len(families) <= 1:
        return {"families": families, "overlaps": {}}

    # Build interval list per family
    intervals = {}
    for fam in families:
        fam_df = df[df["family"] == fam]
        intervals[fam] = list(zip(fam_df["entry_ts"], fam_df["exit_ts"]))

    # Count pairwise overlaps (sweep-line approach for each pair)
    overlaps = {}
    for i, fam_i in enumerate(families):
        for j, fam_j in enumerate(families):
            if j <= i:
                continue
            count = 0
            # For each trade in fam_i, count how many fam_j trades overlap
            for entry_i, exit_i in intervals[fam_i]:
                for entry_j, exit_j in intervals[fam_j]:
                    if entry_j < exit_i and entry_i < exit_j:
                        count += 1
            overlaps[f"{fam_i}×{fam_j}"] = count

    return {"families": families, "overlaps": overlaps}


# ──────────────────────────────────────────────────────────────────────
# STEP 3 — FOUR VARIANT FILTERS
# ──────────────────────────────────────────────────────────────────────

def apply_d1_trend_block_only(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """D1: Block TREND/STR in flagged vol regimes only. No REV/MR cap."""
    mask = pd.Series(False, index=df.index)
    for idx, row in df.iterrows():
        fam = row["family"]
        if fam not in _TREND_BLOCK_FAMILIES:
            continue
        if _is_vol_flagged(fam, row["vol_norm"]):
            mask.at[idx] = True
    return df[~mask], int(mask.sum())


def apply_d2_rev_cap_only(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """D2: Cap REV/MR to max_concurrent=1 in flagged regimes. No TREND block."""
    df = df.sort_values("entry_ts").reset_index(drop=True)
    open_positions: Dict[str, List[datetime]] = {}
    limited_mask = pd.Series(False, index=df.index)

    for idx, row in df.iterrows():
        fam = row["family"]
        if fam not in _EXPOSURE_CAP_FAMILIES:
            continue
        if not _is_flagged(fam, row["vol_norm"], row["trend_norm"]):
            continue

        if fam not in open_positions:
            open_positions[fam] = []
        open_positions[fam] = [
            et for et in open_positions[fam] if et > row["entry_ts"]
        ]

        if len(open_positions[fam]) >= _MAX_CONCURRENT_FLAGGED:
            limited_mask.at[idx] = True
        else:
            open_positions[fam].append(row["exit_ts"])

    return df[~limited_mask], int(limited_mask.sum())


def apply_d3_full(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """D3: TREND block + REV/MR cap (full system from previous test D)."""
    df = df.sort_values("entry_ts").reset_index(drop=True)
    open_positions: Dict[str, List[datetime]] = {}
    removed_mask = pd.Series(False, index=df.index)

    for idx, row in df.iterrows():
        fam = row["family"]
        vol = row["vol_norm"]
        trend = row["trend_norm"]
        flagged = _is_flagged(fam, vol, trend)

        if not flagged:
            continue

        # TREND/STR in flagged → binary block
        if fam in _TREND_BLOCK_FAMILIES:
            if _is_vol_flagged(fam, vol):
                removed_mask.at[idx] = True
                continue

        # REV/MR in flagged → concurrency cap
        if fam in _EXPOSURE_CAP_FAMILIES:
            if fam not in open_positions:
                open_positions[fam] = []
            open_positions[fam] = [
                et for et in open_positions[fam] if et > row["entry_ts"]
            ]
            if len(open_positions[fam]) >= _MAX_CONCURRENT_FLAGGED:
                removed_mask.at[idx] = True
            else:
                open_positions[fam].append(row["exit_ts"])

    return df[~removed_mask], int(removed_mask.sum())


# ──────────────────────────────────────────────────────────────────────
# SIMULATION
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
            years = (tl[-1][0] - tl[0][0]).total_seconds() / (365.25 * 86400)
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
# PORTFOLIO EVALUATION
# ──────────────────────────────────────────────────────────────────────

def evaluate_portfolio(portfolio_id: str) -> dict:
    print(f"\n{'='*70}")
    print(f"  {portfolio_id}")
    print(f"{'='*70}")

    df = load_raw_trades(portfolio_id)
    df = enrich_df(df)
    broker_specs = get_broker_specs(df)
    n_trades = len(df)
    fam_dist = df["family"].value_counts().to_dict()
    print(f"  Loaded {n_trades} trades, families: {dict(fam_dist)}")

    # ── Step 1: Concurrency profile ──
    conc_profile = compute_concurrency_profile(df)
    print(f"  Baseline concurrency: avg={conc_profile['total']['avg']}, "
          f"max={conc_profile['total']['max']}")
    for fam, stats in sorted(conc_profile["per_family"].items()):
        print(f"    {fam:>5}: n={stats['n_trades']}, "
              f"avg_conc={stats['avg_concurrent']}, max_conc={stats['max_concurrent']}, "
              f"dist={stats['distribution']}")

    # ── Step 2: Conflict matrix ──
    conflicts = compute_conflict_matrix(df)
    if conflicts["overlaps"]:
        print(f"  Cross-family overlaps:")
        for pair, count in sorted(conflicts["overlaps"].items(), key=lambda x: -x[1]):
            print(f"    {pair}: {count} overlapping trade-pairs")

    # ── Step 3: Four variants ──
    # A: Baseline
    print(f"  [A] Baseline...")
    events_a = df_to_events(df)
    results_a = run_sim(events_a, broker_specs)
    profile_a = select_best_profile(results_a)

    # D1: TREND block only
    print(f"  [D1] TREND block only...")
    df_d1, n_blocked_d1 = apply_d1_trend_block_only(df)
    events_d1 = df_to_events(df_d1)
    results_d1 = run_sim(events_d1, broker_specs)
    profile_d1 = select_best_profile(results_d1)
    print(f"       Blocked: {n_blocked_d1} trades")

    # D2: REV cap only
    print(f"  [D2] REV/MR cap only...")
    df_d2, n_capped_d2 = apply_d2_rev_cap_only(df)
    events_d2 = df_to_events(df_d2)
    results_d2 = run_sim(events_d2, broker_specs)
    profile_d2 = select_best_profile(results_d2)
    print(f"       Capped: {n_capped_d2} trades")

    # D3: Full system
    print(f"  [D3] Full system (TREND block + REV cap)...")
    df_d3, n_removed_d3 = apply_d3_full(df)
    events_d3 = df_to_events(df_d3)
    results_d3 = run_sim(events_d3, broker_specs)
    profile_d3 = select_best_profile(results_d3)
    print(f"       Removed: {n_removed_d3} trades")

    # Concurrency on each variant
    conc_d1 = compute_concurrency_profile(enrich_df(df_d1))
    conc_d2 = compute_concurrency_profile(enrich_df(df_d2))
    conc_d3 = compute_concurrency_profile(enrich_df(df_d3))

    # ── Step 4: OOS stability (60/40) ──
    print(f"  [S] OOS stability...")
    split_idx = int(len(df) * 0.6)
    df_test = df.iloc[split_idx:].copy()
    n_test = len(df_test)

    events_test_a = df_to_events(df_test)
    results_test_a = run_sim(events_test_a, broker_specs)

    df_test_d1, _ = apply_d1_trend_block_only(df_test)
    results_test_d1 = run_sim(df_to_events(df_test_d1), broker_specs)

    df_test_d2, _ = apply_d2_rev_cap_only(df_test)
    results_test_d2 = run_sim(df_to_events(df_test_d2), broker_specs)

    df_test_d3, _ = apply_d3_full(df_test)
    results_test_d3 = run_sim(df_to_events(df_test_d3), broker_specs)

    # ── Assemble per-profile results ──
    profile_results = {}
    for pname in TEST_PROFILES:
        a = results_a.get(pname, _empty_metrics())
        d1 = results_d1.get(pname, _empty_metrics())
        d2 = results_d2.get(pname, _empty_metrics())
        d3 = results_d3.get(pname, _empty_metrics())
        ta = results_test_a.get(pname, _empty_metrics())
        td1 = results_test_d1.get(pname, _empty_metrics())
        td2 = results_test_d2.get(pname, _empty_metrics())
        td3 = results_test_d3.get(pname, _empty_metrics())

        def _deltas(variant, baseline):
            return {
                "d_pnl": round(variant["net_pnl"] - baseline["net_pnl"], 2),
                "d_pf": round(variant["profit_factor"] - baseline["profit_factor"], 2),
                "d_dd": round(variant["max_dd_pct"] - baseline["max_dd_pct"], 2),
                "d_trades": variant["total_trades"] - baseline["total_trades"],
            }

        def _oos_stable(is_d_pnl, oos_d_pnl):
            return (is_d_pnl >= 0 and oos_d_pnl >= 0) or \
                   (is_d_pnl < 0 and oos_d_pnl < 0) or \
                   abs(is_d_pnl) < 10

        d1_is = _deltas(d1, a)
        d2_is = _deltas(d2, a)
        d3_is = _deltas(d3, a)

        oos_d1_pnl = td1["net_pnl"] - ta["net_pnl"]
        oos_d2_pnl = td2["net_pnl"] - ta["net_pnl"]
        oos_d3_pnl = td3["net_pnl"] - ta["net_pnl"]

        profile_results[pname] = {
            "A": a, "D1": d1, "D2": d2, "D3": d3,
            "OOS_A": ta, "OOS_D1": td1, "OOS_D2": td2, "OOS_D3": td3,
            "d1_is": d1_is,
            "d2_is": d2_is,
            "d3_is": d3_is,
            "oos_d1_pnl": round(oos_d1_pnl, 2),
            "oos_d2_pnl": round(oos_d2_pnl, 2),
            "oos_d3_pnl": round(oos_d3_pnl, 2),
            "oos_stable_d1": _oos_stable(d1_is["d_pnl"], oos_d1_pnl),
            "oos_stable_d2": _oos_stable(d2_is["d_pnl"], oos_d2_pnl),
            "oos_stable_d3": _oos_stable(d3_is["d_pnl"], oos_d3_pnl),
        }

    return {
        "portfolio_id": portfolio_id,
        "type": "single_asset" if portfolio_id.startswith("PF_") else "multi_asset",
        "n_trades": n_trades,
        "family_distribution": fam_dist,
        "concurrency_baseline": conc_profile,
        "conflict_matrix": conflicts,
        "n_blocked_d1": n_blocked_d1,
        "n_capped_d2": n_capped_d2,
        "n_removed_d3": n_removed_d3,
        "profile_a": profile_a,
        "profile_d1": profile_d1,
        "profile_d2": profile_d2,
        "profile_d3": profile_d3,
        "concurrency_d1": conc_d1,
        "concurrency_d2": conc_d2,
        "concurrency_d3": conc_d3,
        "profiles": profile_results,
        "n_test": n_test,
    }


# ──────────────────────────────────────────────────────────────────────
# REPORT
# ──────────────────────────────────────────────────────────────────────

def print_report(all_results: List[dict]):
    print(f"\n{'='*110}")
    print("  CONCURRENCY DIAGNOSTICS — ATTRIBUTION REPORT")
    print(f"{'='*110}")

    n = len(all_results)
    if n == 0:
        print("  [NO RESULTS]")
        return

    # ── 1. Variant Comparison Table ──
    print(f"\n{'─'*110}")
    print("  1. VARIANT COMPARISON (baseline profile per portfolio)")
    print(f"{'─'*110}")
    hdr = (f"  {'Portfolio':<36} "
           f"{'A PnL':>9} {'D1 PnL':>9} {'D2 PnL':>9} {'D3 PnL':>9} "
           f"{'OOS_D1':>6} {'OOS_D2':>6} {'OOS_D3':>6}")
    print(hdr)
    print(f"  {'─'*36} {'─'*9} {'─'*9} {'─'*9} {'─'*9} {'─'*6} {'─'*6} {'─'*6}")

    # Accumulators
    d1_improved = 0
    d2_improved = 0
    d3_improved = 0
    d1_oos_stable = 0
    d2_oos_stable = 0
    d3_oos_stable = 0
    total_d1_dpnl = 0
    total_d2_dpnl = 0
    total_d3_dpnl = 0
    total_d1_ddd = 0
    total_d2_ddd = 0
    total_d3_ddd = 0

    for r in all_results:
        pname = r["profile_a"] or list(TEST_PROFILES.keys())[0]
        pm = r["profiles"].get(pname, {})

        a_pnl = pm.get("A", {}).get("net_pnl", 0)
        d1_pnl = pm.get("D1", {}).get("net_pnl", 0)
        d2_pnl = pm.get("D2", {}).get("net_pnl", 0)
        d3_pnl = pm.get("D3", {}).get("net_pnl", 0)
        oos_d1 = "PASS" if pm.get("oos_stable_d1") else "FAIL"
        oos_d2 = "PASS" if pm.get("oos_stable_d2") else "FAIL"
        oos_d3 = "PASS" if pm.get("oos_stable_d3") else "FAIL"

        d1_is = pm.get("d1_is", {})
        d2_is = pm.get("d2_is", {})
        d3_is = pm.get("d3_is", {})

        total_d1_dpnl += d1_is.get("d_pnl", 0)
        total_d2_dpnl += d2_is.get("d_pnl", 0)
        total_d3_dpnl += d3_is.get("d_pnl", 0)
        total_d1_ddd += d1_is.get("d_dd", 0)
        total_d2_ddd += d2_is.get("d_dd", 0)
        total_d3_ddd += d3_is.get("d_dd", 0)

        if d1_is.get("d_pnl", 0) > 0:
            d1_improved += 1
        if d2_is.get("d_pnl", 0) > 0:
            d2_improved += 1
        if d3_is.get("d_pnl", 0) > 0:
            d3_improved += 1
        if pm.get("oos_stable_d1"):
            d1_oos_stable += 1
        if pm.get("oos_stable_d2"):
            d2_oos_stable += 1
        if pm.get("oos_stable_d3"):
            d3_oos_stable += 1

        print(f"  {r['portfolio_id']:<36} "
              f"{a_pnl:>+9.0f} {d1_pnl:>+9.0f} {d2_pnl:>+9.0f} {d3_pnl:>+9.0f} "
              f"{oos_d1:>6} {oos_d2:>6} {oos_d3:>6}")

    # ── 2. Attribution Summary ──
    print(f"\n{'─'*110}")
    print("  2. ATTRIBUTION SUMMARY")
    print(f"{'─'*110}")
    print(f"  {'Variant':<25} {'Avg dPnL':>10} {'Avg dDD':>10} {'PnL+':>8} {'OOS stable':>12}")
    print(f"  {'─'*25} {'─'*10} {'─'*10} {'─'*8} {'─'*12}")
    print(f"  {'D1: TREND block only':<25} "
          f"${total_d1_dpnl/n:>+9.0f} {total_d1_ddd/n:>+9.2f}pp "
          f"{d1_improved:>4}/{n}   {d1_oos_stable:>4}/{n} ({d1_oos_stable/n*100:.0f}%)")
    print(f"  {'D2: REV/MR cap only':<25} "
          f"${total_d2_dpnl/n:>+9.0f} {total_d2_ddd/n:>+9.2f}pp "
          f"{d2_improved:>4}/{n}   {d2_oos_stable:>4}/{n} ({d2_oos_stable/n*100:.0f}%)")
    print(f"  {'D3: Full system':<25} "
          f"${total_d3_dpnl/n:>+9.0f} {total_d3_ddd/n:>+9.2f}pp "
          f"{d3_improved:>4}/{n}   {d3_oos_stable:>4}/{n} ({d3_oos_stable/n*100:.0f}%)")

    # ── 3. Trade Removal Counts ──
    print(f"\n{'─'*110}")
    print("  3. TRADE REMOVAL COUNTS")
    print(f"{'─'*110}")
    print(f"  {'Portfolio':<36} {'D1 blk':>8} {'D2 cap':>8} {'D3 tot':>8} "
          f"{'D3=D1+D2?':>10}")
    print(f"  {'─'*36} {'─'*8} {'─'*8} {'─'*8} {'─'*10}")
    for r in all_results:
        d1b = r["n_blocked_d1"]
        d2c = r["n_capped_d2"]
        d3r = r["n_removed_d3"]
        additive = "YES" if d3r == d1b + d2c else f"NO ({d1b}+{d2c}={d1b+d2c})"
        print(f"  {r['portfolio_id']:<36} {d1b:>8} {d2c:>8} {d3r:>8} {additive:>10}")

    # ── 4. Concurrency Change (REV/MR families) ──
    print(f"\n{'─'*110}")
    print("  4. REV/MR CONCURRENCY: A vs D1 vs D2 vs D3")
    print(f"{'─'*110}")
    for r in all_results:
        ca = r.get("concurrency_baseline", {}).get("per_family", {})
        cd1 = r.get("concurrency_d1", {}).get("per_family", {})
        cd2 = r.get("concurrency_d2", {}).get("per_family", {})
        cd3 = r.get("concurrency_d3", {}).get("per_family", {})
        target_fams = [f for f in ("REV", "MR") if f in ca]
        if not target_fams:
            continue
        print(f"  {r['portfolio_id']}")
        for fam in target_fams:
            a_m = ca.get(fam, {}).get("max_concurrent", 0)
            a_a = ca.get(fam, {}).get("avg_concurrent", 0)
            d1_m = cd1.get(fam, {}).get("max_concurrent", 0)
            d1_a = cd1.get(fam, {}).get("avg_concurrent", 0)
            d2_m = cd2.get(fam, {}).get("max_concurrent", 0)
            d2_a = cd2.get(fam, {}).get("avg_concurrent", 0)
            d3_m = cd3.get(fam, {}).get("max_concurrent", 0)
            d3_a = cd3.get(fam, {}).get("avg_concurrent", 0)
            print(f"    {fam:>5}: "
                  f"A(avg={a_a:.2f} max={a_m})  "
                  f"D1(avg={d1_a:.2f} max={d1_m})  "
                  f"D2(avg={d2_a:.2f} max={d2_m})  "
                  f"D3(avg={d3_a:.2f} max={d3_m})")

    # ── 5. Conflict Matrix Summary ──
    print(f"\n{'─'*110}")
    print("  5. CROSS-FAMILY CONFLICT MATRIX (top overlaps)")
    print(f"{'─'*110}")
    for r in all_results:
        overlaps = r.get("conflict_matrix", {}).get("overlaps", {})
        if not overlaps:
            continue
        top = sorted(overlaps.items(), key=lambda x: -x[1])[:5]
        if top:
            print(f"  {r['portfolio_id']}")
            for pair, count in top:
                print(f"    {pair}: {count} overlapping trade-pairs")

    # ── 6. DIAGNOSTIC VERDICT ──
    print(f"\n{'─'*110}")
    print("  6. DIAGNOSTIC VERDICT")
    print(f"{'─'*110}")

    # Is D1 (TREND block) the main driver?
    d1_is_driver = abs(total_d1_dpnl) > abs(total_d2_dpnl) * 2
    d2_is_meaningful = abs(total_d2_dpnl) > abs(total_d1_dpnl) * 0.1
    d3_is_additive = abs(total_d3_dpnl - total_d1_dpnl) > abs(total_d1_dpnl) * 0.05
    d2_has_effect = d2_improved > 0 or total_d2_dpnl != 0

    print(f"  TREND blocking (D1) is main PnL driver?     "
          f"{'YES' if d1_is_driver else 'NO'} "
          f"(D1 avg dPnL=${total_d1_dpnl/n:+,.0f})")
    print(f"  REV/MR cap (D2) has meaningful PnL effect?   "
          f"{'YES' if d2_is_meaningful else 'NO'} "
          f"(D2 avg dPnL=${total_d2_dpnl/n:+,.0f})")
    print(f"  D3 adds value beyond D1 alone?              "
          f"{'YES' if d3_is_additive else 'NO'} "
          f"(D3-D1 avg=${(total_d3_dpnl-total_d1_dpnl)/n:+,.0f})")
    print(f"  REV/MR cap fires at all?                    "
          f"{'YES' if d2_has_effect else 'NO'}")

    print(f"\n  --- Stability comparison ---")
    print(f"  D1 OOS stable: {d1_oos_stable}/{n} ({d1_oos_stable/n*100:.0f}%)")
    print(f"  D2 OOS stable: {d2_oos_stable}/{n} ({d2_oos_stable/n*100:.0f}%)")
    print(f"  D3 OOS stable: {d3_oos_stable}/{n} ({d3_oos_stable/n*100:.0f}%)")

    print(f"\n  --- Conclusion ---")
    if d1_is_driver and not d2_is_meaningful:
        print("  FINDING: The benefit comes almost entirely from TREND blocking (D1).")
        print("  The REV/MR cap (D2) is REDUNDANT at current concurrency levels.")
        print("  RECOMMENDATION: Implement D1 only (TREND/STR block in vol=low).")
        print("  Do NOT add REV/MR cap — it adds complexity without measurable benefit.")
    elif d1_is_driver and d2_is_meaningful:
        print("  FINDING: TREND blocking (D1) is the primary driver, but REV/MR cap (D2)")
        print("  contributes meaningful additional value.")
        print("  RECOMMENDATION: Implement full D3 system.")
    elif not d1_is_driver and d2_is_meaningful:
        print("  FINDING: REV/MR cap (D2) is the primary driver.")
        print("  RECOMMENDATION: Focus on concurrency control, not family blocking.")
    else:
        print("  FINDING: Neither component shows strong isolated effect.")
        print("  RECOMMENDATION: Re-examine the regime rules or collect more data.")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 110)
    print("  CONCURRENCY DIAGNOSTICS — ATTRIBUTION TEST")
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
    out_path = output_dir / "concurrency_diagnostics.json"

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
