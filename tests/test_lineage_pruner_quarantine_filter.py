"""Regression: lineage_pruner.build_keep_runs() must skip rows tagged
`quarantined=True` (FSP) or `quarantine_status` set (MPS Portfolios + SAC).

Why this matters: the H3 rehab batch (2026-05-25) and any future
dependency-loss tagging via repair_integrity.py write quarantine_status to
declare "this row's lineage is intentionally not on disk." The pruner's
referential integrity check would otherwise FAIL on these rows and refuse
to operate, blocking every downstream cleanup pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.state_lifecycle import lineage_pruner as lp


def _write_fsp(path: Path, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df.to_excel(path, sheet_name="Sheet1", index=False)


def _write_mps(path: Path, portfolios: list[dict], sac: list[dict]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(portfolios).to_excel(writer, sheet_name="Portfolios", index=False)
        pd.DataFrame(sac).to_excel(writer, sheet_name="Single-Asset Composites", index=False)
        pd.DataFrame([{"basket_id": "H2", "directive_id": "x"}]).to_excel(
            writer, sheet_name="Baskets", index=False
        )


@pytest.fixture
def patched_sheets(tmp_path, monkeypatch):
    fsp = tmp_path / "fsp.xlsx"
    mps = tmp_path / "mps.xlsx"
    monkeypatch.setattr(lp, "FILTERED_SHEET_PATH", fsp)
    monkeypatch.setattr(lp, "MASTER_SHEET_PATH", mps)
    # PORTFOLIO_COMPLETE scan operates on real backtest_directives — neutralize
    # so the test doesn't pick up real-repo state.
    monkeypatch.setattr(lp, "_collect_portfolio_complete_runs", lambda: (set(), set()))
    return fsp, mps


def test_quarantined_fsp_rows_are_skipped(patched_sheets):
    fsp, mps = patched_sheets
    _write_fsp(fsp, [
        {"run_id": "ALIVE_RUN", "quarantined": False},
        {"run_id": "DEAD_RUN", "quarantined": True},
    ])
    _write_mps(mps, [], [])

    keep_runs, _, _ = lp.build_keep_runs()

    assert "ALIVE_RUN" in keep_runs
    assert "DEAD_RUN" not in keep_runs


def test_quarantined_portfolios_constituents_are_skipped(patched_sheets):
    fsp, mps = patched_sheets
    _write_fsp(fsp, [])
    _write_mps(
        mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A,RID_B",
             "quarantine_status": None},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_C,RID_D",
             "quarantine_status": "ARCHIVED_DEPENDENCY_LOST"},
        ],
        sac=[],
    )

    keep_runs, active_portfolios, _ = lp.build_keep_runs()

    assert "RID_A" in keep_runs
    assert "RID_B" in keep_runs
    assert "RID_C" not in keep_runs
    assert "RID_D" not in keep_runs
    assert "PF_LIVE" in active_portfolios
    assert "PF_DEAD" not in active_portfolios


def test_sac_sheet_is_scanned_and_filtered(patched_sheets):
    fsp, mps = patched_sheets
    _write_fsp(fsp, [])
    _write_mps(
        mps,
        portfolios=[],
        sac=[
            {"portfolio_id": "SAC_LIVE", "constituent_run_ids": "SAC_RID_A",
             "quarantine_status": None},
            {"portfolio_id": "SAC_DEAD", "constituent_run_ids": "SAC_RID_B",
             "quarantine_status": "ARCHIVED_DEPENDENCY_LOST"},
        ],
    )

    keep_runs, active_portfolios, _ = lp.build_keep_runs()

    assert "SAC_RID_A" in keep_runs
    assert "SAC_RID_B" not in keep_runs
    assert "SAC_LIVE" in active_portfolios
    assert "SAC_DEAD" not in active_portfolios


def test_missing_quarantine_columns_default_to_active(patched_sheets):
    """Back-compat: sheets without the filter columns behave as today."""
    fsp, mps = patched_sheets
    _write_fsp(fsp, [{"run_id": "LEGACY_RID"}])
    _write_mps(
        mps,
        portfolios=[{"portfolio_id": "PF_LEGACY", "constituent_run_ids": "LEGACY_C"}],
        sac=[],
    )

    keep_runs, active_portfolios, _ = lp.build_keep_runs()

    assert "LEGACY_RID" in keep_runs
    assert "LEGACY_C" in keep_runs
    assert "PF_LEGACY" in active_portfolios
