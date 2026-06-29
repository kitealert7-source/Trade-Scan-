"""Lock: the report's per-symbol capsule resolver excludes rerun variants.

A base-stem report (test.strategy) must NOT aggregate "__E###" rerun capsules as
phantom "symbols" — that double-counts the overlapping windows of one strategy's
reruns. Regression: the SPKFADE S04 base report blended contaminated + Arm A +
Arm B (3 runs sharing the S04_V1_P00 stem) into a meaningless PF 1.21, while the
genuine per-run report (__E002) was PF 1.06.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.report_generator import _resolve_symbol_dirs  # noqa: E402

BASE = "11_REV_XAUUSD_1H_SPKFADE_VOLFILT_S04_V1_P00"


def _make(root, *names):
    for n in names:
        (root / n).mkdir(parents=True)


def test_base_stem_excludes_rerun_variants(tmp_path):
    # The exact regression: base + two reruns share the stem.
    _make(tmp_path, f"{BASE}_XAUUSD", f"{BASE}__E001_XAUUSD", f"{BASE}__E002_XAUUSD")
    got = sorted(d.name for d in _resolve_symbol_dirs(tmp_path, BASE))
    assert got == [f"{BASE}_XAUUSD"]  # ONLY the base capsule; reruns excluded


def test_variant_name_resolves_only_its_own_capsule(tmp_path):
    _make(tmp_path, f"{BASE}_XAUUSD", f"{BASE}__E001_XAUUSD", f"{BASE}__E002_XAUUSD")
    got = sorted(d.name for d in _resolve_symbol_dirs(tmp_path, f"{BASE}__E002"))
    assert got == [f"{BASE}__E002_XAUUSD"]


def test_multi_symbol_siblings_all_included(tmp_path):
    # The legitimate case the fix must NOT break: one directive, many symbols.
    d = "40_CONT_FX_15M_RSIPULL_SESSFILT_S01_V1_P00"
    _make(tmp_path, f"{d}_XAUUSD", f"{d}_EURUSD", f"{d}_GBPJPY", f"{d}__E001_XAUUSD")
    got = sorted(x.name for x in _resolve_symbol_dirs(tmp_path, d))
    assert got == [f"{d}_EURUSD", f"{d}_GBPJPY", f"{d}_XAUUSD"]  # 3 symbols, rerun excluded


def test_basket_concatenated_symbol_included(tmp_path):
    # Basket "symbols" are concatenated tokens with no underscore — must be kept.
    d = "90_PORT_AUDJPYXAUUSD_15M_COINTREV_V3_L30"
    _make(tmp_path, f"{d}_AUDJPYXAUUSD", f"{d}__E001_AUDJPYXAUUSD")
    got = sorted(x.name for x in _resolve_symbol_dirs(tmp_path, d))
    assert got == [f"{d}_AUDJPYXAUUSD"]  # concatenated symbol kept, rerun excluded


def test_no_capsules_returns_empty(tmp_path):
    assert _resolve_symbol_dirs(tmp_path, BASE) == []
