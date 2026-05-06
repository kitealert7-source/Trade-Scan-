"""report_project — DB/metrics -> markdown section projection.

Choke-point: report section builders are pure functions of their inputs.
Any drift in wording, column order, number formatting, or metric math
silently corrupts every published report downstream.

Scenario: feed deterministic inputs to three representative section builders
(`_build_key_metrics_section`, `_build_direction_split_section`,
`_build_path_geometry_section`) and compare the rendered markdown to frozen goldens.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.report.report_sections.path_geometry import _build_path_geometry_section
from tools.report.report_sections.summary import (
    _build_direction_split_section,
    _build_key_metrics_section,
)
from tools.regression.compare import compare_text
from tools.regression.runner import Result


# --------------------------------------------------------------------------
# Synthesized inputs
# --------------------------------------------------------------------------
_TOTALS = {
    "sharpe": 1.834,
    "sortino": 2.251,
    "k_ratio": 0.185,
    "max_dd_usd": 412.50,
    "max_dd_pct": 8.45,
    "ret_dd": 3.42,
    "win_rate": 0.548,
    "avg_r": 0.423,
    "sqn": 2.71,
}

_TRADES_DF = pd.DataFrame([
    # symbol, direction, pnl, bars
    ("XAUUSD",  1,   45.20,  12),
    ("XAUUSD",  1,  -20.10,   8),
    ("XAUUSD", -1,   30.50,  15),
    ("XAUUSD", -1,  -15.00,   6),
    ("XAUUSD",  1,   65.00,  18),
    ("XAUUSD", -1,  -10.25,   4),
    ("XAUUSD",  1,   22.30,   9),
    ("XAUUSD", -1,   18.75,  11),
], columns=["symbol", "direction", "pnl_usd", "bars_held"])

# Path geometry requires mfe_r, mae_r, r_multiple; exit_source and bars_held
# are optional enrichments exercised here to cover the full rendering paths.
_PATH_GEO_DF = pd.DataFrame([
    # exit_source,            dir, r_mult, mfe_r, mae_r, bars_held
    ("ENGINE_STOP",            1,  -1.00,  0.05,  1.00,  6),   # IMMEDIATE_ADVERSE
    ("ENGINE_STOP",            1,  -1.00,  0.05,  1.00,  4),   # IMMEDIATE_ADVERSE
    ("ENGINE_STOP",           -1,  -1.00,  0.30,  1.00,  8),   # STALL_DECAY
    ("ENGINE_STOP",            1,  -1.00,  0.40,  1.00, 18),   # STALL_DECAY
    ("ENGINE_STOP",           -1,  -1.00,  0.45,  1.00, 22),   # STALL_DECAY
    ("ENGINE_STOP",            1,  -1.00,  1.20,  1.00, 15),   # PROFIT_GIVEBACK
    ("ENGINE_STOP",           -1,  -1.00,  1.80,  1.00, 12),   # PROFIT_GIVEBACK
    ("STRATEGY_DAY_CLOSE",     1,   1.20,  1.50,  0.10, 30),   # FAST_EXPAND
    ("STRATEGY_DAY_CLOSE",    -1,   0.80,  0.90,  0.20, 25),   # FAST_EXPAND
    ("STRATEGY_DAY_CLOSE",     1,   2.10,  2.50,  0.50, 40),   # RECOVER_WIN
    ("STRATEGY_DAY_CLOSE",    -1,   1.50,  1.80,  0.60, 35),   # RECOVER_WIN
    ("STRATEGY_DAY_CLOSE",     1,  -0.20,  0.30,  0.40, 50),   # TIME_FLAT
], columns=["exit_source", "direction", "r_multiple", "mfe_r", "mae_r", "bars_held"])


def run(tmp_dir: Path, baseline_dir: Path, budget) -> list[Result]:
    # --- key metrics section --------------------------------------------------
    km_md = _build_key_metrics_section(
        portfolio_pnl=136.40,
        portfolio_trades=8,
        port_pf_str="1.82",
        totals=_TOTALS,
        risk_data_list=[{"dummy": True}],  # non-empty triggers S3 path
    )
    km_path = tmp_dir / "key_metrics_section.md"
    km_path.write_text("\n".join(km_md), encoding="utf-8")

    # --- direction split section ---------------------------------------------
    ds_md = _build_direction_split_section([_TRADES_DF])
    ds_path = tmp_dir / "direction_split_section.md"
    ds_path.write_text("\n".join(ds_md), encoding="utf-8")

    # --- path geometry section -----------------------------------------------
    pg_md = _build_path_geometry_section([_PATH_GEO_DF])
    pg_path = tmp_dir / "path_geometry_section.md"
    pg_path.write_text("\n".join(pg_md), encoding="utf-8")

    # Candidates for --update-baseline
    cand_root = tmp_dir / "golden_candidate"
    cand_root.mkdir(parents=True, exist_ok=True)
    (cand_root / "key_metrics_section.md").write_text("\n".join(km_md), encoding="utf-8")
    (cand_root / "direction_split_section.md").write_text("\n".join(ds_md), encoding="utf-8")
    (cand_root / "path_geometry_section.md").write_text("\n".join(pg_md), encoding="utf-8")

    # --- compare --------------------------------------------------------------
    results: list[Result] = []
    for artifact in (
        "key_metrics_section.md",
        "direction_split_section.md",
        "path_geometry_section.md",
    ):
        got = tmp_dir / artifact
        golden = baseline_dir / "golden" / artifact
        passed, diff = compare_text(got, golden)
        results.append(Result(
            scenario="report_project",
            artifact=artifact,
            passed=passed,
            diff=diff,
        ))
    return results
