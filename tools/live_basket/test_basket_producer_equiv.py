"""Equivalence + USD-ref-derivation tests for the generic basket_producer.

Proves the parameterized producer reproduces the legacy hardcoded CADJPYUSDCHF
config exactly (so migrating to it is behavior-preserving), and that the inlined
USD-reference derivation matches the canonical basket_data_loader for several
currency shapes (drift guard).

Run from the Trade_Scan root:  pytest tools/live_basket/test_basket_producer_equiv.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_TS_ROOT = Path(__file__).resolve().parents[2]   # .../Trade_Scan
if str(_TS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TS_ROOT))

from tools.live_basket import cadjpyusdchf_producer as legacy   # noqa: E402
from tools.live_basket import basket_producer as generic        # noqa: E402


def test_generic_config_matches_legacy_cadjpyusdchf():
    """derive_basket_config('CADJPYUSDCHF') == the legacy module's hardcoded constants."""
    cfg = generic.derive_basket_config("CADJPYUSDCHF")
    assert cfg.basket_id == legacy.BASKET_ID
    assert cfg.directive_id == legacy.DIRECTIVE_ID
    assert cfg.mt5_tf_attr == legacy.MT5_TF_ATTR
    assert set(cfg.usd_ref_symbols) == set(legacy.USD_REF_SYMBOLS)
    assert str(cfg.signal_dir) == str(legacy.SIGNAL_DIR)
    assert (cfg.sym_a, cfg.sym_b) == ("CADJPY", "USDCHF")
    assert [(l["symbol"], l["direction"], l["lot"]) for l in cfg.legs] == \
        [("CADJPY", "long", 0.01), ("USDCHF", "short", 0.01)]


def test_usd_ref_derivation_matches_canonical_loader():
    """The inlined _required_ref_pairs must not drift from basket_data_loader's."""
    from tools.basket_data_loader import _required_ref_pairs as canonical
    shapes = [
        ["CADJPY", "USDCHF"],   # the live basket -> USDCAD, USDJPY
        ["EURGBP", "GBPUSD"],   # GBPUSD is a leg -> self-ref dropped; EUR -> EURUSD
        ["AUDNZD", "NZDUSD"],   # NZDUSD is a leg -> dropped; AUD -> AUDUSD
        ["EURUSD", "USDJPY"],   # USD-anchored legs -> EURUSD/USDJPY self-ref dropped
    ]
    for legs in shapes:
        assert set(generic._required_ref_pairs(legs)) == set(canonical(legs)), legs


def test_unknown_basket_raises():
    import pytest
    with pytest.raises(SystemExit):
        generic.derive_basket_config("NOSUCHBASKET_XYZ")
