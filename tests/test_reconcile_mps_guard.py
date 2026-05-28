"""Regression: reconcile_portfolio_master_sheet._guard_multi_sheet tolerance.

The reconciler patches only the Portfolios + Single-Asset Composites sheets, but
the live MPS workbook also carries DB-canonical sibling sheets (Baskets,
Cointegration) that export_mps regenerates. The pre-2026-05-28 guard required the
data-sheet set to be EXACTLY {Portfolios, Single-Asset Composites} and so FATAL-ed
against every post-Baskets workbook. This test locks in the corrected contract:

  * core sheets {Portfolios, Single-Asset Composites} must both be present;
  * known siblings {Baskets, Cointegration} are tolerated alongside;
  * anything else (a collapsed lone 'Sheet1', a stray/unknown sheet, or a
    missing core sheet) still FATALs — the structural-corruption guard stays.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.reconcile_portfolio_master_sheet import _guard_multi_sheet


def _write(path: Path, sheet_names: list[str]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name in sheet_names:
            pd.DataFrame([{"portfolio_id": "X"}]).to_excel(
                writer, sheet_name=name, index=False
            )


def test_missing_file_is_noop(tmp_path):
    # Fresh install — DB is authoritative; nothing to guard.
    _guard_multi_sheet(tmp_path / "nonexistent.xlsx")  # no raise


def test_core_only_passes(tmp_path):
    p = tmp_path / "mps.xlsx"
    _write(p, ["Portfolios", "Single-Asset Composites", "Notes"])
    _guard_multi_sheet(p)  # no raise


def test_baskets_sibling_passes(tmp_path):
    p = tmp_path / "mps.xlsx"
    _write(p, ["Portfolios", "Single-Asset Composites", "Baskets", "Notes"])
    _guard_multi_sheet(p)  # no raise


def test_baskets_and_cointegration_siblings_pass(tmp_path):
    """The live-workbook shape that used to FATAL."""
    p = tmp_path / "mps.xlsx"
    _write(p, ["Portfolios", "Single-Asset Composites", "Baskets",
               "Cointegration", "Notes"])
    _guard_multi_sheet(p)  # no raise


def test_collapsed_single_sheet_fatals(tmp_path):
    p = tmp_path / "mps.xlsx"
    _write(p, ["Sheet1"])
    with pytest.raises(SystemExit):
        _guard_multi_sheet(p)


def test_missing_core_sheet_fatals(tmp_path):
    # Single-Asset Composites absent — core requirement violated even though a
    # known sibling is present.
    p = tmp_path / "mps.xlsx"
    _write(p, ["Portfolios", "Baskets", "Notes"])
    with pytest.raises(SystemExit):
        _guard_multi_sheet(p)


def test_unknown_sibling_fatals(tmp_path):
    # An unrecognized data sheet must still trip the guard — catches the next
    # silent sheet addition before reconcile fans rows into the wrong tag.
    p = tmp_path / "mps.xlsx"
    _write(p, ["Portfolios", "Single-Asset Composites", "MysterySheet", "Notes"])
    with pytest.raises(SystemExit):
        _guard_multi_sheet(p)
