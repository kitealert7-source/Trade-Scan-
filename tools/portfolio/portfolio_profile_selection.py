"""Step 7 authority — sole owner of deployed_profile selection + portfolio_status.

CRITICAL INVARIANT:
  _resolve_deployed_profile is the ONLY function allowed to select deployed_profile.
  All other modules must treat deployed_profile as read-only.

All quality-gate thresholds, scoring weights, tie-breaks, and reliability
fallbacks live here. Changes must carry DB-row + selection-debug parity checks.
"""

from __future__ import annotations

import json

import pandas as pd

from config.asset_classification import (
    EXP_FAIL_GATES as _EXP_FAIL_GATES,
    classify_asset as _detect_asset_class,
    parse_strategy_name as _parse_strategy_name,
)
from tools.portfolio.portfolio_config import (
    RELIABILITY_MIN_ACCEPTED,
    RELIABILITY_MIN_SIM_YEARS,
    STRATEGIES_ROOT,
)


# Re-exported so ledger writer can inline strategy-name parsing without another import.
__all__ = [
    "_safe_float",
    "_safe_bool",
    "_execution_health",
    "_profile_return_dd",
    "_per_symbol_realized_density",
    "_compute_portfolio_status",
    "_empty_selection_debug",
    "_load_profile_comparison",
    "_score_profile_candidate",
    "_resolve_deployed_profile",
    "_get_deployed_profile_metrics",
    "_detect_asset_class",
    "_EXP_FAIL_GATES",
    "_parse_strategy_name",
]


def _safe_float(value, default=0.0):
    """Best-effort numeric coercion for ledger writes."""
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_bool(value, default=False):
    """Best-effort boolean coercion for profile validity checks."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"true", "1", "yes", "y"}:
        return True
    if token in {"false", "0", "no", "n"}:
        return False
    return default


def _execution_health(rejection_rate_pct):
    """Classify execution regime from rejection rate."""
    rej = _safe_float(rejection_rate_pct, 0.0)
    if rej > 60.0:
        return "DEGRADED"
    if rej > 30.0:
        return "WARNING"
    return "HEALTHY"


def _profile_return_dd(profile_metrics):
    """Base Return/DD helper used to resolve deployed profile deterministically."""
    realized = _safe_float(profile_metrics.get("realized_pnl"), 0.0)
    max_dd = abs(_safe_float(profile_metrics.get("max_drawdown_usd"), 0.0))
    return realized / max(max_dd, 1.0)


def _per_symbol_realized_density(strategy_id, sim_years, rejection_rate_pct=0.0, mf_df=None):
    """Return {symbol: trades_per_year_int} — per-symbol density AFTER deployed
    profile's rejection filter.

    Two-stage derivation:
      1. Raw per-symbol density = portfolio_tradelevel.csv trade count per
         symbol / deployed profile's simulation_years.
      2. Apply deployed profile's portfolio-wide rejection_rate_pct uniformly.

    Returns None if the tradelevel file is missing / unreadable / empty.
    """
    try:
        sim_years = float(sim_years) if sim_years is not None else 0.0
    except (TypeError, ValueError):
        sim_years = 0.0
    if sim_years <= 0:
        return None
    try:
        rej = float(rejection_rate_pct) if rejection_rate_pct is not None else 0.0
    except (TypeError, ValueError):
        rej = 0.0
    retention = max(0.0, 1.0 - rej / 100.0)
    tl_path = (STRATEGIES_ROOT / str(strategy_id)
               / "portfolio_evaluation" / "portfolio_tradelevel.csv")
    if not tl_path.exists():
        return None
    try:
        import pandas as _pd
        tl = _pd.read_csv(tl_path)
        if tl.empty or "source_run_id" not in tl.columns:
            return None
        if mf_df is None:
            from tools.ledger_db import read_master_filter
            mf_df = read_master_filter()
        if mf_df is None or mf_df.empty:
            return None
        if "run_id" not in mf_df.columns or "symbol" not in mf_df.columns:
            return None
        run_to_sym = dict(zip(mf_df["run_id"].astype(str),
                              mf_df["symbol"].astype(str)))
        tl = tl.copy()
        tl["_symbol"] = tl["source_run_id"].astype(str).map(run_to_sym)
        tl = tl.dropna(subset=["_symbol"])
        if tl.empty:
            return None
        per_sym = (tl.groupby("_symbol").size() / sim_years) * retention
        return {str(k): int(round(v)) for k, v in per_sym.items()}
    except Exception as e:
        print(f"  [WARN] per-symbol realized density failed for {strategy_id}: {e}")
        return None


def _compute_portfolio_status(realized_pnl, total_accepted, rejection_rate_pct,
                              expectancy=0.0, portfolio_id="",
                              trade_density_min=None,
                              edge_quality=None, sqn=None,
                              is_single_asset=False):
    """Deterministic portfolio status classification for ledger rows.

    Quality gates (additive — on top of all existing FAIL gates):
      Portfolios tab  → edge_quality >= 0.12 for CORE, >= 0.08 for WATCH
      Single-Asset tab → sqn >= 2.5 for CORE, >= 2.0 for WATCH
    """
    realized = _safe_float(realized_pnl, 0.0)
    accepted = int(round(_safe_float(total_accepted, 0.0)))
    rejection = _safe_float(rejection_rate_pct, 0.0)
    exp = _safe_float(expectancy, 0.0)
    td = _safe_float(trade_density_min, None)
    eq = _safe_float(edge_quality, None)
    sq = _safe_float(sqn, None)

    asset_class = _detect_asset_class(portfolio_id)
    exp_gate = _EXP_FAIL_GATES.get(asset_class, 0.0)

    # ── FAIL gates (any one triggers) ────────────────────────────────
    if realized <= 0.0 or accepted < 50:
        return "FAIL"
    if td is not None and td < 50:
        return "FAIL"
    if exp < exp_gate:
        return "FAIL"

    # ── CORE gate (all conditions required) ──────────────────────────
    core_base = (realized > 1000.0 and accepted >= 200 and rejection <= 30.0)
    if core_base:
        if eq is not None and eq >= 0.12:
            return "CORE"
        if sq is not None and sq >= 2.5:
            return "CORE"
        if eq is None and sq is None:
            return "CORE"

    # ── WATCH gate (quality floor required) ──────────────────────────
    if is_single_asset:
        if sq is not None:
            return "WATCH" if sq >= 2.0 else "FAIL"
        if eq is not None:
            return "WATCH" if eq >= 0.08 else "FAIL"
    else:
        if eq is not None:
            return "WATCH" if eq >= 0.08 else "FAIL"
        if sq is not None:
            return "WATCH" if sq >= 2.0 else "FAIL"
    return "WATCH"


def _empty_selection_debug(previous_profile=None):
    """Build default selection diagnostics payload."""
    return {
        "candidates": [],
        "selected_profile": None,
        "selection_reason": "fallback",
        "previous_profile": previous_profile,
        "persistence_used": False,
        "reliability_override": False,
    }


def _load_profile_comparison(strategy_id):
    """Load strategies/<id>/deployable/profile_comparison.json."""
    comparison_path = STRATEGIES_ROOT / strategy_id / "deployable" / "profile_comparison.json"
    if not comparison_path.exists():
        return None, comparison_path
    try:
        payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] Failed to parse profile comparison for {strategy_id}: {e}")
        return None, comparison_path
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        print(f"  [WARN] Invalid profile comparison schema for {strategy_id}: missing non-empty 'profiles'.")
        return None, comparison_path

    # Invariant: all profiles must share the same starting_capital.
    _caps = {
        name: m.get("starting_capital")
        for name, m in profiles.items()
        if isinstance(m, dict) and m.get("starting_capital") is not None
    }
    _cap_values = {round(float(v), 6) for v in _caps.values()}
    if len(_cap_values) > 1:
        raise ValueError(
            f"PROFILE_CAPITAL_MISMATCH: profile_comparison.json for {strategy_id} "
            f"has inconsistent starting_capital across profiles: {_caps}. "
            f"All profiles must share the same starting_capital for valid "
            f"CAGR/ROI/score comparison."
        )
    return profiles, comparison_path


def _score_profile_candidate(name, metrics):
    """Score a single profile candidate — returns (candidate_row | None, debug_row)."""
    if not isinstance(metrics, dict):
        return None, {
            "profile": name,
            "valid": False,
            "flags": {
                "pnl_invalid": True,
                "capital_invalid": True,
                "low_samples": True,
                "low_years": True,
            },
            "base_score": 0.0,
            "penalty_multiplier": 0.0,
            "final_score": 0.0,
            "rejection_rate": 0.0,
            "total_accepted": 0,
        }

    realized = _safe_float(metrics.get("realized_pnl"), 0.0)
    capital_valid = _safe_bool(metrics.get("capital_validity_flag"), False)
    avg_risk = _safe_float(metrics.get("avg_risk_multiple"), 0.0)
    rej = _safe_float(metrics.get("rejection_rate_pct"), 0.0)
    # Execution-health penalty uses execution_rejection_rate_pct when present:
    # excludes RETAIL_MAX_LOT_EXCEEDED skips (capital-ceiling saturation is
    # evidence of outstanding returns, not weak execution — penalizing it
    # was upside-down logic). Falls back to raw rej for legacy metrics.
    rej_health = _safe_float(
        metrics.get("execution_rejection_rate_pct", rej), rej
    )
    accepted = int(round(_safe_float(metrics.get("total_accepted"), 0.0)))
    sim_years = _safe_float(metrics.get("simulation_years"), 0.0)
    base_score = _profile_return_dd(metrics)

    health = _execution_health(rej_health)
    if health == "DEGRADED":
        penalty = 0.4
    elif health == "WARNING":
        penalty = 0.7
    else:
        penalty = 1.0
    score = base_score * penalty

    flags = {
        "pnl_invalid": realized <= 0.0,
        "capital_invalid": not capital_valid,
        # Retail-realistic oversizing tolerance: compounding small-account profiles
        # (REAL_MODEL_V1 tier-ramp) exceed 1.5× early in the curve before equity
        # grows past the min-lot barrier. 2.5 matches industry realistic-retail norm.
        "risk_overextended": avg_risk > 2.5,
        "low_samples": accepted < RELIABILITY_MIN_ACCEPTED,
        "low_years": sim_years < RELIABILITY_MIN_SIM_YEARS,
    }
    hard_valid = (not flags["pnl_invalid"]) and (not flags["capital_invalid"]) and (not flags["risk_overextended"])
    reliable_valid = hard_valid and (not flags["low_samples"]) and (not flags["low_years"])

    candidate_row = {
        "name": name,
        "metrics": metrics,
        "score": score,
        "base_score": base_score,
        "rejection_rate_pct": rej,
        "total_accepted": accepted,
        "health": health,
        "flags": flags,
        "hard_valid": hard_valid,
        "reliable_valid": reliable_valid,
    }
    debug_row = {
        "profile": name,
        "valid": False,  # finalized after reliability override decision
        "flags": flags,
        "base_score": round(base_score, 6),
        "penalty_multiplier": penalty,
        "final_score": round(score, 6),
        "rejection_rate": round(rej, 4),
        "total_accepted": accepted,
    }
    return candidate_row, debug_row


# CRITICAL INVARIANT:
# This is the ONLY function allowed to select deployed_profile.
# All other modules must treat deployed_profile as read-only.
def _resolve_deployed_profile(strategy_id, profiles, df_ledger):
    """
    Resolve deployed profile using:
      1) Hard validity filter (realized_pnl > 0 and capital_validity_flag is True).
      2) Penalized Return/DD score with execution health bands.
      3) Similar-score stabilization tie-breaks.

    STATELESS: selection is computed purely from profile_comparison.json.
    No hint or persistence from existing ledger values.
    """
    selection_debug = _empty_selection_debug(previous_profile=None)
    reliable_candidates = []
    hard_valid_candidates = []
    debug_candidates = []
    for name in sorted(profiles.keys()):
        candidate_row, debug_row = _score_profile_candidate(name, profiles.get(name))
        debug_candidates.append(debug_row)
        if candidate_row is None:
            continue
        if candidate_row["hard_valid"]:
            hard_valid_candidates.append(candidate_row)
            if candidate_row["reliable_valid"]:
                reliable_candidates.append(candidate_row)

    if reliable_candidates:
        candidates = reliable_candidates
        reliability_override = False
    elif hard_valid_candidates:
        candidates = hard_valid_candidates
        reliability_override = True
    else:
        candidates = []
        reliability_override = False

    selection_debug["reliability_override"] = reliability_override
    for dbg in debug_candidates:
        profile_name = dbg["profile"]
        src = next((c for c in hard_valid_candidates if c["name"] == profile_name), None)
        if src is None:
            dbg["valid"] = False
        elif reliability_override:
            dbg["valid"] = True
        else:
            dbg["valid"] = bool(src["reliable_valid"])
    selection_debug["candidates"] = debug_candidates

    if not candidates:
        return None, None, "no_valid_profiles", selection_debug

    # Stable deterministic ordering for tie handling.
    candidates.sort(
        key=lambda c: (
            -c["score"],
            c["rejection_rate_pct"],
            -c["total_accepted"],
            c["name"],
        )
    )

    # Similar-score stabilization window (within 15% of current best score).
    best = candidates[0]
    for cand in candidates[1:]:
        denom = max(best["score"], cand["score"])
        rel_gap = 0.0 if denom <= 1e-12 else abs(best["score"] - cand["score"]) / denom
        if rel_gap < 0.15:
            tie_key_best = (best["rejection_rate_pct"], -best["total_accepted"], best["name"])
            tie_key_cand = (cand["rejection_rate_pct"], -cand["total_accepted"], cand["name"])
            if tie_key_cand < tie_key_best:
                best = cand
        else:
            break

    best_name = best["name"]
    best_metrics = best["metrics"]
    best_score = best["score"]

    selection_debug["selected_profile"] = best_name
    selection_debug["selection_reason"] = "fallback" if reliability_override else "highest_score"
    selection_debug["persistence_used"] = False
    return best_name, best_metrics, "best_scored", selection_debug


def _get_deployed_profile_metrics(strategy_id, df_ledger):
    """Return deployed profile payload for ledger injection, or None."""
    profiles, comparison_path = _load_profile_comparison(strategy_id)
    if profiles is None:
        debug = _empty_selection_debug(previous_profile=None)
        if comparison_path.exists():
            print(f"  [WARN] Profile comparison unusable for {strategy_id}: {comparison_path}")
        else:
            print(f"  [WARN] Profile comparison not found for {strategy_id}: {comparison_path}")
        return {
            "profile_name": None,
            "realized_pnl": 0.0,
            "trades_accepted": None,
            "trades_rejected": None,
            "rejection_rate_pct": None,
            "source": "missing_profile_comparison",
            "selection_debug": debug,
        }

    profile_name, profile_metrics, source, selection_debug = _resolve_deployed_profile(strategy_id, profiles, df_ledger)
    if profile_name is None or profile_metrics is None:
        print(f"  [WARN] Could not resolve deployed profile for {strategy_id} (no valid profile).")
        return {
            "profile_name": None,
            "realized_pnl": 0.0,
            "trades_accepted": None,
            "trades_rejected": None,
            "rejection_rate_pct": None,
            "source": source,
            "selection_debug": selection_debug,
        }

    deployed = {
        "profile_name": profile_name,
        "realized_pnl": round(_safe_float(profile_metrics.get("realized_pnl"), 0.0), 2),
        "trades_accepted": int(round(_safe_float(profile_metrics.get("total_accepted"), 0.0))),
        "trades_rejected": int(round(_safe_float(profile_metrics.get("total_rejected"), 0.0))),
        "rejection_rate_pct": round(_safe_float(profile_metrics.get("rejection_rate_pct"), 0.0), 2),
        "simulation_years": _safe_float(profile_metrics.get("simulation_years"), 0.0),
        "source": source,
        "selection_debug": selection_debug,
    }
    print(
        f"  [PROFILE] Using {deployed['profile_name']} ({deployed['source']}) "
        f"for ledger PnL/trade counts."
    )
    return deployed
