"""Regression: repair_integrity.py contract.

Two actions:
  * --action drop (default): rows whose disk artifacts are gone are dropped.
    Operator-driven cleanup is the documented exception to the append-only
    ledger invariant (CLAUDE.md #2). LINEAGE_PROTECTED_TAGS rows (SUPERSEDED
    / ARCHIVED_UNRESOLVED from H3 rehab batches) are preserved on drop.
  * --action mark: rows are tagged ARCHIVED_DEPENDENCY_LOST instead. Mark
    mode is idempotent and never overwrites an existing tag.

Both actions share the multi-sheet-safe writer (Portfolios + SAC + Baskets +
Notes all survive) and the dry-run default. The pre-2026-05-26 implementation
had a critical data-loss bug here (single-sheet write would delete SAC +
Baskets + Notes on every run); this test file guards that fix.
"""
from __future__ import annotations

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
    """Stage a tmp workspace with planted valid artifacts:
       - RID_A: valid (folder + JSON planted)
       - RID_X: orphan
       - PF_LIVE: deployed folder planted
       - PF_DEAD / SAC_DEAD: no folder
    """
    fsp = tmp_path / "fsp.xlsx"
    mps = tmp_path / "mps.xlsx"
    runs = tmp_path / "runs"
    backtests = tmp_path / "backtests"
    sandbox = tmp_path / "sandbox"
    strategies = tmp_path / "strategies"
    runs.mkdir(); backtests.mkdir(); sandbox.mkdir(); strategies.mkdir()

    (runs / "RID_A").mkdir()
    (backtests / "RID_A.json").write_text("{}", encoding="utf-8")
    (strategies / "PF_LIVE").mkdir()

    monkeypatch.setattr(ri, "FILTERED_SHEET_PATH", fsp)
    monkeypatch.setattr(ri, "MASTER_SHEET_PATH", mps)
    monkeypatch.setattr(ri, "RUNS_DIR", runs)
    monkeypatch.setattr(ri, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(ri, "SANDBOX_DIR", sandbox)
    monkeypatch.setattr(ri, "STRATEGIES_DIR", strategies)
    monkeypatch.setattr(ri, "_reformat", lambda path, profile: None)
    return fsp, mps


# ---------------------------------------------------------------------------
# Shared invariants (both actions)
# ---------------------------------------------------------------------------


def test_dry_run_does_not_mutate(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
    )
    before_fsp = pd.read_excel(fsp)
    before_mps = pd.read_excel(mps, sheet_name="Portfolios")

    rc_drop = ri.main_via_args([])  # default drop, dry-run
    rc_mark = ri.main_via_args(["--action", "mark"])  # mark, dry-run

    assert rc_drop == 0 and rc_mark == 0
    pd.testing.assert_frame_equal(before_fsp, pd.read_excel(fsp))
    pd.testing.assert_frame_equal(before_mps, pd.read_excel(mps, sheet_name="Portfolios"))


def test_all_sheets_preserved_after_execute(staged):
    """The headline data-loss guard. Pre-rewrite to_excel() deleted SAC + Baskets + Notes."""
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
        baskets=[{"basket_id": "H2", "directive_id": "PRESERVED_DIR",
                  "verdict_status": "CORE", "quarantine_status": None}],
        notes=[{"note": "MUST_NOT_BE_LOST"}],
    )

    rc = ri.main_via_args(["--execute"])  # drop, execute
    assert rc == 0

    post_sheets = pd.ExcelFile(mps).sheet_names
    assert {"Portfolios", "Single-Asset Composites", "Baskets", "Notes"} <= set(post_sheets)
    assert "PRESERVED_DIR" in pd.read_excel(mps, sheet_name="Baskets")["directive_id"].values
    assert "MUST_NOT_BE_LOST" in pd.read_excel(mps, sheet_name="Notes")["note"].values
    assert "Notes" in pd.ExcelFile(fsp).sheet_names


# ---------------------------------------------------------------------------
# Drop mode (default)
# ---------------------------------------------------------------------------


def test_drop_removes_orphan_rows(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},
        ],
        sac=[{"portfolio_id": "SAC_DEAD", "constituent_run_ids": "RID_X"}],
    )

    rc = ri.main_via_args(["--execute"])  # default drop
    assert rc == 0

    fsp_after = pd.read_excel(fsp)
    assert list(fsp_after["run_id"]) == ["RID_A"]
    assert list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"]) == ["PF_LIVE"]
    assert pd.read_excel(mps, sheet_name="Single-Asset Composites").empty


def test_drop_preserves_lineage_protected_tags(staged):
    """SUPERSEDED / ARCHIVED_UNRESOLVED rows survive drop — those are explicit
    audit decisions from the H3 rehab pattern."""
    fsp, mps = staged
    _write_fsp(fsp, [])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_SUPERSEDED", "constituent_run_ids": "RID_X",
             "quarantine_status": "SUPERSEDED"},
            {"portfolio_id": "PF_UNRESOLVED", "constituent_run_ids": "RID_X",
             "quarantine_status": "ARCHIVED_UNRESOLVED"},
            {"portfolio_id": "PF_TOMBSTONE", "constituent_run_ids": "RID_X",
             "quarantine_status": "ARCHIVED_DEPENDENCY_LOST"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X",
             "quarantine_status": None},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    survivors = list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"])
    assert "PF_SUPERSEDED" in survivors
    assert "PF_UNRESOLVED" in survivors
    assert "PF_TOMBSTONE" not in survivors  # soft tombstone — drop removes
    assert "PF_DEAD" not in survivors


def test_drop_handles_missing_folder_orphans(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_NO_FOLDER", "constituent_run_ids": "RID_A"},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--execute"])
    assert rc == 0

    survivors = list(pd.read_excel(mps, sheet_name="Portfolios")["portfolio_id"])
    assert survivors == ["PF_LIVE"]


# ---------------------------------------------------------------------------
# Mark mode
# ---------------------------------------------------------------------------


def test_mark_tags_orphan_rows_without_dropping(staged):
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_A"}, {"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_LIVE", "constituent_run_ids": "RID_A"},
            {"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"},
        ],
        sac=[{"portfolio_id": "SAC_DEAD", "constituent_run_ids": "RID_X"}],
    )

    rc = ri.main_via_args(["--action", "mark", "--execute"])
    assert rc == 0

    fsp_after = pd.read_excel(fsp)
    assert set(fsp_after["run_id"]) == {"RID_A", "RID_X"}
    x_row = fsp_after[fsp_after.run_id == "RID_X"].iloc[0]
    assert bool(x_row["quarantined"]) is True

    mps_p = pd.read_excel(mps, sheet_name="Portfolios")
    dead = mps_p[mps_p.portfolio_id == "PF_DEAD"].iloc[0]
    assert dead["quarantine_status"] == "ARCHIVED_DEPENDENCY_LOST"
    assert "RID_X" in str(dead["quarantine_reason"])
    live = mps_p[mps_p.portfolio_id == "PF_LIVE"].iloc[0]
    qstat_live = live.get("quarantine_status")
    assert pd.isna(qstat_live) or qstat_live in (None, "")


def test_mark_does_not_overwrite_existing_tag(staged):
    fsp, mps = staged
    _write_fsp(fsp, [])
    _write_mps(mps,
        portfolios=[
            {"portfolio_id": "PF_SUPER", "constituent_run_ids": "RID_X",
             "quarantine_status": "SUPERSEDED", "quarantine_reason": "from H3 rehab"},
        ],
        sac=[],
    )

    rc = ri.main_via_args(["--action", "mark", "--execute"])
    assert rc == 0
    row = pd.read_excel(mps, sheet_name="Portfolios").iloc[0]
    assert row["quarantine_status"] == "SUPERSEDED"
    assert row["quarantine_reason"] == "from H3 rehab"


def test_idempotent_second_run_is_noop(staged):
    """Both modes should produce identical state on a second --execute pass."""
    fsp, mps = staged
    _write_fsp(fsp, [{"run_id": "RID_X"}])
    _write_mps(mps,
        portfolios=[{"portfolio_id": "PF_DEAD", "constituent_run_ids": "RID_X"}],
        sac=[],
    )

    rc1 = ri.main_via_args(["--action", "mark", "--execute"])
    state_1 = pd.read_excel(mps, sheet_name="Portfolios")

    rc2 = ri.main_via_args(["--action", "mark", "--execute"])
    state_2 = pd.read_excel(mps, sheet_name="Portfolios")

    assert rc1 == 0 and rc2 == 0
    pd.testing.assert_frame_equal(state_1, state_2)


# ---------------------------------------------------------------------------
# argparse wrapper for tests
# ---------------------------------------------------------------------------


def _install_main_via_args():
    real_main = ri.main

    def main_via_args(argv):
        old = sys.argv
        sys.argv = ["repair_integrity.py", *argv]
        try:
            return real_main()
        finally:
            sys.argv = old

    ri.main_via_args = main_via_args


_install_main_via_args()
