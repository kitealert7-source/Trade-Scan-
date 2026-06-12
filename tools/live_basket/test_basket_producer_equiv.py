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


# ---- PRODUCER_START banner: resolved key params (z_entry auditability) --------- #
# Regression guard for 2026-06-11: a live z_entry 2.0->2.5 switch could not be
# confirmed from the producer log alone. The banner now echoes _resolved_key_params,
# so the running z_entry (et al.) is greppable straight out of producer.log.

def _parsed_with_params(params: dict) -> dict:
    """Minimal parsed-directive shape that _resolved_key_params reads."""
    return {"basket": {"recycle_rule": {
        "name": "pine_ratio_zrev_v1_zcross", "version": 1, "params": params,
    }}}


def test_banner_includes_resolved_z_entry():
    """The headline case: a directive's z_entry appears verbatim in the banner."""
    s = generic._resolved_key_params(_parsed_with_params({
        "z_entry": 2.5, "n_window": 60, "entry_mode": "absolute",
        "entry_fill_timing": "current_bar_open",
    }))
    assert "z_entry=2.5" in s
    assert "rule=pine_ratio_zrev_v1_zcross@1" in s
    assert "n_window=60" in s
    assert "entry_mode=absolute" in s
    assert "entry_fill_timing=current_bar_open" in s
    # coint_break_exit omitted -> rendered with the (default) marker, not (UNSET!).
    assert "coint_break_exit=False(default)" in s
    assert "(UNSET!)" not in s


def test_banner_flags_missing_z_entry_as_unset():
    """z_entry has no downstream default (basket_pipeline raises); an omitted key
    must be flagged loudly so the operator sees the misconfiguration at startup."""
    s = generic._resolved_key_params(_parsed_with_params({"n_window": 60}))
    assert "z_entry=(UNSET!)" in s


def test_banner_marks_explicit_value_over_default():
    """An explicitly-set coint_break_exit must NOT carry the (default) marker."""
    s = generic._resolved_key_params(_parsed_with_params({
        "z_entry": 3.0, "coint_break_exit": True,
    }))
    assert "z_entry=3.0" in s
    assert "coint_break_exit=True" in s
    assert "coint_break_exit=True(default)" not in s


def test_banner_reflects_real_promoted_directive_z_entry():
    """End-to-end: derive a real promoted ZCRS basket and assert the banner
    reflects the directive's resolved z_entry (catches drift between directive
    parsing and the banner). CADJPYUSDCHF carries the post-2026-06-11 z_entry=2.5
    + coint_break_exit=true."""
    cfg = generic.derive_basket_config("CADJPYUSDCHF")
    s = generic._resolved_key_params(cfg.parsed)
    params = cfg.parsed["basket"]["recycle_rule"]["params"]
    assert f"z_entry={params['z_entry']}" in s
    # Whatever the directive resolves to today, the value (not a stale default)
    # is what the banner shows.
    assert "(UNSET!)" not in s
