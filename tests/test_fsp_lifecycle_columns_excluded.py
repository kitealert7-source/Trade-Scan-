"""FSP candidate-view column contract (2026-07-02).

FSP (Filtered_Strategies_Passed.xlsx) is a FILTERED view: the promotion mask in
filter_strategies.py already guarantees every row is is_current==1 &
quarantined==0, so the supersession/quarantine lifecycle columns are constant
there and carry no information. They are relics of the hoard-era mark-and-keep
flow, superseded by the delete-not-hoard `repair_integrity --action drop`
default. The DURABLE copies live in master_filter (DB) → SMF.

This test locks two halves of the contract:
  1. The producer excludes the 5 lifecycle columns from the FSP xlsx.
  2. SMF / master_filter STILL carries them (durable source of truth preserved).
"""

import openpyxl
import pytest

from config.path_authority import TRADE_SCAN_STATE
from tools.filter_strategies import _FSP_EXCLUDED_LIFECYCLE_COLS

FSP_PATH = TRADE_SCAN_STATE / "candidates" / "Filtered_Strategies_Passed.xlsx"
SMF_PATH = TRADE_SCAN_STATE / "sandbox" / "Strategy_Master_Filter.xlsx"

EXPECTED_EXCLUDED = {
    "is_current",
    "superseded_by",
    "superseded_at",
    "supersede_reason",
    "quarantined",
}


def _headers(path, sheet=None):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet] if sheet else wb.active
    return [c.value for c in ws[1]]


def test_excluded_constant_matches_contract():
    """The producer constant is exactly the 5 lifecycle columns."""
    assert set(_FSP_EXCLUDED_LIFECYCLE_COLS) == EXPECTED_EXCLUDED


@pytest.mark.skipif(not FSP_PATH.exists(), reason="FSP not generated yet")
def test_fsp_excludes_lifecycle_columns():
    """FSP xlsx must NOT carry any of the 5 lifecycle columns."""
    headers = set(_headers(FSP_PATH))
    leaked = EXPECTED_EXCLUDED & headers
    assert not leaked, (
        f"FSP leaks lifecycle columns {sorted(leaked)} — the candidate view "
        f"must drop them (durable copy is in SMF). Regenerate via "
        f"filter_strategies.py."
    )


@pytest.mark.skipif(not SMF_PATH.exists(), reason="SMF not generated yet")
def test_smf_retains_lifecycle_columns():
    """SMF (the full ledger export) MUST still carry the durable copies."""
    headers = set(_headers(SMF_PATH))
    missing = EXPECTED_EXCLUDED - headers
    assert not missing, (
        f"SMF is missing lifecycle columns {sorted(missing)} — the durable "
        f"source of truth for supersession/quarantine must be preserved in the "
        f"full ledger view even though FSP drops them."
    )
