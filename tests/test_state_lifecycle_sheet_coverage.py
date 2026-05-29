"""Coverage CI test for state-lifecycle tools vs MPS schema.

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task E.

Failure mode this locks in: someone adds a new data sheet to
Master_Portfolio_Sheet.xlsx (e.g., "Baskets" was added 2026-05) without
extending the lifecycle tools that mutate it. Symptom is silent — the
tools touch only the sheets they know about, so the new sheet is
effectively orphaned from cleanup/repair flows. Commit 544c361 (2026-05-27)
retroactively wired Baskets into both tools; this test prevents the next
sheet addition from repeating the gap.

Mechanism: read live MPS sheet names, then literal-string-search the
source of repair_integrity.py and lineage_pruner.py. Every data sheet
(everything except "Notes", which is preserved-but-not-scanned by design)
must appear in both sources.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config.path_authority import REAL_REPO_ROOT, TRADE_SCAN_STATE

MPS_PATH = TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx"

# Sheets explicitly preserved without scanning. Adding to this set is a
# governance decision — narrow scope deliberately. The "Notes" sheet was
# intentionally retired 2026-05-29 (MPS is SQL source-of-truth; the non-data
# operator Notes sheet was dropped), leaving no exempt sheets currently.
EXEMPT_SHEETS: set[str] = set()

LIFECYCLE_TOOLS = (
    REAL_REPO_ROOT / "tools" / "state_lifecycle" / "repair_integrity.py",
    REAL_REPO_ROOT / "tools" / "state_lifecycle" / "lineage_pruner.py",
)


def _live_mps_data_sheets() -> set[str]:
    if not MPS_PATH.exists():
        pytest.skip(f"MPS not present at {MPS_PATH} — cannot verify coverage")
    sheets = set(pd.ExcelFile(MPS_PATH).sheet_names)
    return sheets - EXEMPT_SHEETS


@pytest.mark.parametrize("tool_path", LIFECYCLE_TOOLS, ids=lambda p: p.name)
def test_lifecycle_tool_references_every_mps_data_sheet(tool_path: Path) -> None:
    """Every MPS data sheet name must appear literally in the tool's source.

    Literal-string match catches both direct references ('Portfolios')
    and constant declarations (MPS_TAGGED_SHEETS = ('Portfolios', ...)).
    Fails if a sheet name in MPS is absent from the source — signal that
    the tool was never extended to handle that sheet.
    """
    src = tool_path.read_text(encoding="utf-8")
    data_sheets = _live_mps_data_sheets()
    missing = sorted(s for s in data_sheets if s not in src)
    assert not missing, (
        f"{tool_path.name} does not reference MPS data sheet(s) {missing}. "
        f"Either extend the tool to handle the sheet or add it to "
        f"EXEMPT_SHEETS in tests/test_state_lifecycle_sheet_coverage.py "
        f"with documented reason."
    )


def test_exempt_set_is_subset_of_live_sheets() -> None:
    """EXEMPT_SHEETS entries must actually exist in MPS.

    Catches stale exemptions left over after a sheet rename or removal —
    keeps the exempt set honest.
    """
    if not MPS_PATH.exists():
        pytest.skip(f"MPS not present at {MPS_PATH} — cannot verify exemptions")
    live = set(pd.ExcelFile(MPS_PATH).sheet_names)
    stale = sorted(s for s in EXEMPT_SHEETS if s not in live)
    assert not stale, (
        f"EXEMPT_SHEETS contains sheet(s) {stale} that no longer exist in MPS. "
        f"Remove from EXEMPT_SHEETS."
    )
