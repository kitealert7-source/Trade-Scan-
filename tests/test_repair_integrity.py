"""Regression: repair_integrity.py must (1) tag, never delete; (2) preserve
every sheet in MPS on write; (3) be idempotent; (4) refuse the legacy
--action flag with a clear error.

Anti-bug: the pre-2026-05-26 version read MPS as a single sheet and wrote
back with to_excel() — silently deleting SAC + Baskets + Notes on every
run. After the H3 rehab batch (2026-05-25) that's ~514 rows of irreplaceable
audit history per run. This test guards the fix at the unit level.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.state_lifecycle import repair_integrity as ri


def _write_fsp(path: Path, rows: list[dict]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Sheet1", index=False)
        pd.DataFrame([{"note": "preserved Notes row"}]).to_excel(
            writer, sheet_name="Notes", index=False
        )


def _write_mps(path: Path, portfolios: list[dict], sac: list[dict],
               baskets: list[dict] | None = None,
               notes: list[dict] | None = None) -> None:
    baskets = baskets or [{"basket_id": "H2", "directive_id": "X1",
                           "verdict_status": "CORE", "quarantine_status": None}]
    notes = notes or [{"note": "preserved baskets-Notes row"}]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(portfolios).to_excel(writer, sheet_name="Portfolios", index=False)
        pd.DataFrame(sac).to_excel(writer, sheet_name="Single-Asset Composites", index=False)
        pd.DataFrame(baskets).to_excel(writer, sheet_name="Baskets", index=False)
        pd.DataFrame(notes).to_excel(writer, sheet_name="Notes", index=False)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Create FSP + MPS with a mix of valid and orphan run_ids.

    `RID_A` is "valid" (we plant its disk artifacts under tmp_path/runs and
    tmp_path/backtests). `RID_X` is "orphan" — never planted.

    `PF_LIVE` / `PF_DEAD` portfolio_ids: PF_LIVE has a folder under
    strategies_dir; PF_DEAD does not.
    """
    fsp = tmp_path / "fsp.xlsx"
    mps = tmp_path / "mps.xlsx"
    runs = tmp_path / "runs"
    backtests = tmp_path / "backtests"
    sandbox = tmp_path / "sandbox"
    strategies = tmp_path / "strategies"
    runs.mkdir()
    backtests.mkdir()
    sandbox.mkdir()
    strategies.mkdir()

    # Plant RID_A as valid: folder + JSON
    (runs / "RID_A").mkdir()
    (backtests / "RID_A.json").write_text("{}", encoding="utf-8")
    # Plant PF_LIVE as a deployed portfolio (folder exists)
    (strategies / "PF_LIVE").mkdir()

    monkeypatch.setattr(ri, "FILTERED_SHEET_PATH", fsp)
    monkeypatch.setattr(ri, "MASTER_SHEET_PATH", mps)
    monkeypatch.setattr(ri, "RUNS_DIR", runs)
    monkeypatch.setattr(ri, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(ri, "SANDBOX_DIR", sandbox)
    monkeypatch.setattr(ri, "STRATEGIES_DIR", strategies)
    # Neutralize the formatter subprocess — irrelevant for unit tests, and
    # the worktree's tools/format_excel_artifact.py would touch real paths.
    monkeypatch.setattr(ri, "_reformat", lambda path, profile: None)
    return fsp, mps


def test_dry_run_does_not_mutate(staged):
    fsp, mps = staged
    _write_fsp(fsp, [
        {"run_id": "RID_A"},
        {"run_id": "RID_X"},
    ])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD",
                     "constituent_run_ids": "RID_X"}],
        sac=[],
    )
    before_fsp = pd.read_excel(fsp)
    before_mps_p = pd.read_excel(mps, sheet_name="Portfolios")

    rc = ri.main_via_args([])  # dry-run is default; main() returns 0
    # see helper below — main is invoked via argparse, so we use a wrapper.

    after_fsp = pd.read_excel(fsp)
    after_mps_p = pd.read_excel(mps, sheet_name="Portfolios")
    # Frame equality — nothing changed
    pd.testing.assert_frame_equal(before_fsp, after_fsp)
    pd.testing.assert_frame_equal(before_mps_p, after_mps_p)


def test_execute_tags_fsp_and_mps(staged):
    fsp, mps = staged
    _write_fsp(fsp, [
        {"run_id": "RID_A"},
        {"run_id": "RID_X"},
    ])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},
        ],
        sac=[{"portfolio_id": "SAC_DEAD", "constituent_run_ids": "RID_X"}],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    fsp_after = pd.read_excel(fsp)
    # RID_X row gets quarantined=True; RID_A stays alive
    a_row = fsp_after[fsp_after.run_id == "RID_A"].iloc[0]
    x_row = fsp_after[fsp_after.run_id == "RID_X"].iloc[0]
    assert bool(x_row["quarantined"]) is True
    # RID_A may have a quarantined column added with default False — that's fine
    assert bool(a_row.get("quarantined", False)) is False

    mps_p = pd.read_excel(mps, sheet_name="Portfolios")
    live = mps_p[mps_p.portfolio_id == "PF_LIVE"].iloc[0]
    dead = mps_p[mps_p.portfolio_id == "PF_DEAD"].iloc[0]
    assert dead["quarantine_status"] == "ARCHIVED_DEPENDENCY_LOST"
    assert "RID_X" in str(dead["quarantine_reason"])
    qstat_live = live.get("quarantine_status")
    assert pd.isna(qstat_live) or qstat_live in (None, "")

    mps_sac = pd.read_excel(mps, sheet_name="Single-Asset Composites")
    sac_dead = mps_sac[mps_sac.portfolio_id == "SAC_DEAD"].iloc[0]
    assert sac_dead["quarantine_status"] == "ARCHIVED_DEPENDENCY_LOST"


def test_all_sheets_preserved_after_execute(staged):
    """The bug we set out to fix: pre-2026-05-26 to_excel() deleted SAC + Baskets + Notes."""
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
        baskets=[{"basket_id": "H2", "directive_id": "PRESERVED_DIR",
                  "verdict_status": "CORE", "quarantine_status": None}],
        notes=[{"note": "MUST_NOT_BE_LOST"}],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    post_sheets = pd.ExcelFile(mps).sheet_names
    assert "Portfolios" in post_sheets
    assert "Single-Asset Composites" in post_sheets
    assert "Baskets" in post_sheets
    assert "Notes" in post_sheets

    # Content preserved verbatim on untouched sheets
    baskets_after = pd.read_excel(mps, sheet_name="Baskets")
    assert "PRESERVED_DIR" in baskets_after["directive_id"].values
    notes_after = pd.read_excel(mps, sheet_name="Notes")
    assert "MUST_NOT_BE_LOST" in notes_after["note"].values

    # FSP Notes preserved
    fsp_sheets = pd.ExcelFile(fsp).sheet_names
    assert "Notes" in fsp_sheets


def test_idempotent_second_run_is_noop(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
    )

    rc1 = ri.main_via_args(["--execute"])
    fsp_1 = pd.read_excel(fsp)
    mps_1 = pd.read_excel(mps, sheet_name="Portfolios")

    rc2 = ri.main_via_args(["--execute"])
    fsp_2 = pd.read_excel(fsp)
    mps_2 = pd.read_excel(mps, sheet_name="Portfolios")

    assert rc1 == 0 and rc2 == 0
    # Already-tagged rows are skipped on the second pass — DataFrames must
    # be byte-equivalent.
    pd.testing.assert_frame_equal(fsp_1, fsp_2)
    pd.testing.assert_frame_equal(mps_1, mps_2)


def test_missing_portfolio_folder_is_tagged(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}])
    _write_mps(
        mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_NO_FOLDER", "constituent_run_ids": "RID_A"},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    mps_p = pd.read_excel(mps, sheet_name="Portfolios")
    live = mps_p[mps_p.portfolio_id == "PF_LIVE"].iloc[0]
    dead = mps_p[mps_p.portfolio_id == "PF_NO_FOLDER"].iloc[0]
    assert dead["quarantine_status"] == "ARCHIVED_DEPENDENCY_LOST"
    assert "deployed portfolio folder missing" in str(dead["quarantine_reason"])
    qstat_live = live.get("quarantine_status")
    assert pd.isna(qstat_live) or qstat_live in (None, "")


def test_legacy_action_flag_is_rejected(staged, capsys):
    fsp, mps = staged
    _write_fsp(fsp, [])
    _write_mps(mps, portfolios=[], sac=[])

    rc = ri.main_via_args(["--action", "drop"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--action removed" in captured.out
    assert "append-only invariant" in captured.out


# ---------------------------------------------------------------------------
# Helper — argparse uses sys.argv; route via a wrapper for testability.
# ---------------------------------------------------------------------------

def _install_main_via_args():
    import argparse as _argparse
    real_main = ri.main

    def main_via_args(argv):
        # Patch sys.argv around the real main; restore after.
        old = sys.argv
        sys.argv = ["repair_integrity.py", *argv]
        try:
            return real_main()
        finally:
            sys.argv = old

    ri.main_via_args = main_via_args


_install_main_via_args()
