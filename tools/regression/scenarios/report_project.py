"""report_project — DB/metrics -> markdown section projection.

Choke-point: report section builders are pure functions of their inputs.
Any drift in wording, column order, number formatting, or metric math
silently corrupts every published report downstream.

Scenario: feed deterministic inputs to two representative section builders
(`_build_key_metrics_section`, `_build_direction_split_section`) and
compare the rendered markdown to frozen goldens.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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

    # Candidates for --update-baseline
    cand_root = tmp_dir / "golden_candidate"
    cand_root.mkdir(parents=True, exist_ok=True)
    (cand_root / "key_metrics_section.md").write_text("\n".join(km_md), encoding="utf-8")
    (cand_root / "direction_split_section.md").write_text("\n".join(ds_md), encoding="utf-8")

    # --- compare --------------------------------------------------------------
    results: list[Result] = []
    for artifact in ("key_metrics_section.md", "direction_split_section.md"):
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
