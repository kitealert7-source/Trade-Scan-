"""portfolio_select — Step 7 authority + status classification.

Choke-point 1: `_resolve_deployed_profile` is the SOLE selector for
`deployed_profile` in the Master Portfolio Sheet. Any drift in its scoring
or tie-break logic silently reshuffles which capital profile is deployed
for live strategies — a quiet governance breach.

Choke-point 2: `_compute_portfolio_status` classifies every MPS row as
CORE / WATCH / FAIL. Any drift in its gates changes which strategies are
deemed deployable.

Scenario: feed 4 synthesized profile_comparison shapes into
`_resolve_deployed_profile` and 6 synthesized row shapes into
`_compute_portfolio_status`; compare outputs against frozen goldens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tools.portfolio.portfolio_profile_selection import (
    _compute_portfolio_status,
    _resolve_deployed_profile,
)
from tools.regression.compare import compare_json
from tools.regression.runner import Result


# --------------------------------------------------------------------------
# Profile selection cases — shape mirrors deployable/profile_comparison.json
# --------------------------------------------------------------------------
def _profile(realized, accepted, rejected, pf, ret_dd, avg_risk=1.5,
             rej_pct=0.0, years=2.0, capital_valid=True, max_dd=200.0):
    return {
        "realized_pnl": realized,
        "total_accepted": accepted,
        "total_rejected": rejected,
        "rejection_rate_pct": rej_pct,
        "pf": pf,
        "return_dd_ratio": ret_dd,
        "max_dd_usd": max_dd,
        "avg_risk_multiple": avg_risk,
        "simulation_years": years,
        "capital_validity_flag": capital_valid,
        "starting_capital": 1000.0,
    }


_PROFILE_CASES = {
    # Case A: REAL_MODEL_V1 has best Return/DD — expect it selected.
    "A_clear_winner": {
        "RAW_MIN_LOT_V1":  _profile(100.0,  250, 10, 1.1, 0.5),
        "FIXED_USD_V1":    _profile(500.0,  250, 10, 1.3, 1.2),
        "REAL_MODEL_V1":   _profile(1200.0, 250, 10, 1.6, 3.5),
    },
    # Case B: Only RAW_MIN_LOT_V1 is profitable — should still select it.
    "B_only_raw_profitable": {
        "RAW_MIN_LOT_V1":  _profile(50.0,   250, 10, 1.1, 0.4),
        "FIXED_USD_V1":    _profile(-300.0, 250, 10, 0.7, -0.5, capital_valid=False),
        "REAL_MODEL_V1":   _profile(-500.0, 250, 10, 0.5, -1.0, capital_valid=False),
    },
    # Case C: no valid profile — should return None.
    "C_all_invalid": {
        "RAW_MIN_LOT_V1":  _profile(-50.0,  250, 10, 0.8, -0.3, capital_valid=False),
        "FIXED_USD_V1":    _profile(-300.0, 250, 10, 0.7, -0.5, capital_valid=False),
        "REAL_MODEL_V1":   _profile(-500.0, 250, 10, 0.5, -1.0, capital_valid=False),
    },
    # Case D: reliable_valid tie — deterministic sort picks alpha-first
    # (assuming equal scores, same accepted/rej). Tests tie-break stability.
    "D_tied_scores": {
        "RAW_MIN_LOT_V1":  _profile(500.0, 250, 10, 1.3, 2.0),
        "FIXED_USD_V1":    _profile(500.0, 250, 10, 1.3, 2.0),
        "REAL_MODEL_V1":   _profile(500.0, 250, 10, 1.3, 2.0),
    },
}


# --------------------------------------------------------------------------
# Status classification cases — exercise each gate
# --------------------------------------------------------------------------
_STATUS_CASES = [
    # (case_id, kwargs) — status must match golden.
    ("S01_core_portfolio", dict(
        realized_pnl=5000.0, total_accepted=400, rejection_rate_pct=10.0,
        expectancy=12.0, portfolio_id="PF_ABC", trade_density_min=100,
        edge_quality=0.15, is_single_asset=False)),
    ("S02_watch_portfolio", dict(
        realized_pnl=500.0, total_accepted=150, rejection_rate_pct=15.0,
        expectancy=3.0, portfolio_id="PF_XYZ", trade_density_min=75,
        edge_quality=0.09, is_single_asset=False)),
    ("S03_fail_low_trades", dict(
        realized_pnl=100.0, total_accepted=30, rejection_rate_pct=10.0,
        expectancy=3.0, portfolio_id="PF_XYZ", trade_density_min=20,
        edge_quality=0.15)),
    ("S04_fail_negative_pnl", dict(
        realized_pnl=-500.0, total_accepted=200, rejection_rate_pct=10.0,
        expectancy=-2.0, portfolio_id="PF_XYZ", trade_density_min=100,
        edge_quality=0.20)),
    ("S05_core_single_asset", dict(
        realized_pnl=1500.0, total_accepted=250, rejection_rate_pct=15.0,
        expectancy=6.0, portfolio_id="03_TREND_XAUUSD_1H", trade_density_min=80,
        sqn=3.0, is_single_asset=True)),
    ("S06_fail_low_sqn_single", dict(
        realized_pnl=800.0, total_accepted=200, rejection_rate_pct=10.0,
        expectancy=4.0, portfolio_id="03_TREND_XAUUSD_1H", trade_density_min=70,
        sqn=1.5, is_single_asset=True)),
]


def run(tmp_dir: Path, baseline_dir: Path, budget) -> list[Result]:
    # --- resolve_deployed_profile outputs ------------------------------------
    empty_ledger = pd.DataFrame()
    profile_outputs = {}
    for case_id, profiles in _PROFILE_CASES.items():
        name, _, source, _ = _resolve_deployed_profile(case_id, profiles, empty_ledger)
        profile_outputs[case_id] = {"deployed_profile": name, "source": source}

    # --- status classification outputs ---------------------------------------
    status_outputs = {
        case_id: _compute_portfolio_status(**kwargs)
        for case_id, kwargs in _STATUS_CASES
    }

    # --- write tmp outputs ----------------------------------------------------
    prof_path = tmp_dir / "profile_selection.json"
    prof_path.write_text(json.dumps(profile_outputs, indent=2, sort_keys=True), encoding="utf-8")
    stat_path = tmp_dir / "status_classification.json"
    stat_path.write_text(json.dumps(status_outputs, indent=2, sort_keys=True), encoding="utf-8")

    # Candidates for --update-baseline
    cand_root = tmp_dir / "golden_candidate"
    cand_root.mkdir(parents=True, exist_ok=True)
    (cand_root / "profile_selection.json").write_text(
        json.dumps(profile_outputs, indent=2, sort_keys=True), encoding="utf-8")
    (cand_root / "status_classification.json").write_text(
        json.dumps(status_outputs, indent=2, sort_keys=True), encoding="utf-8")

    # --- compare --------------------------------------------------------------
    results: list[Result] = []
    for artifact in ("profile_selection.json", "status_classification.json"):
        got = tmp_dir / artifact
        golden = baseline_dir / "golden" / artifact
        passed, diff = compare_json(got, golden)
        results.append(Result(
            scenario="portfolio_select",
            artifact=artifact,
            passed=passed,
            diff=diff,
        ))
    return results
