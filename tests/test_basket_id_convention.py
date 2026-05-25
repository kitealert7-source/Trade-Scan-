"""Regression test for the H3_spread basket_id direction-suffix convention.

Convention formalized 2026-05-25 (after the leg_direction_flip_bug
rehabilitation batch). For H3_spread rules:

  - params.bidirectional=True  -> basket_id MUST end with 'BIDIR'
  - params.bidirectional=False -> basket_id MUST end with 'BEAR' or 'BULL'

Other rule families (H2_recycle, cointegration_*, pine_ratio_zrev_v1) do
NOT use this convention and must not be affected by these checks.

Enforced inside tools/basket_pipeline._validate_basket_id_convention,
called from the H3_spread@1/@2/@3 branches of _instantiate_rule.
"""
from __future__ import annotations

import pytest

from tools.basket_pipeline import _instantiate_rule


# ════════════════════════════════════════════════════════════════════
# Happy paths
# ════════════════════════════════════════════════════════════════════

def test_h3v2_bidirectional_true_with_BIDIR_suffix_accepted():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"bidirectional": True},
    }
    _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBIDIR")


def test_h3v2_bidirectional_false_with_BEAR_suffix_accepted():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"bidirectional": False},
    }
    _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBEAR")


def test_h3v2_bidirectional_absent_with_BULL_suffix_accepted():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {},  # bidirectional defaults to False
    }
    _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBULL")


def test_h3v3_bidirectional_true_with_BIDIR_suffix_accepted():
    cfg = {
        "name": "H3_spread",
        "version": 3,
        "params": {"bidirectional": True},
    }
    _instantiate_rule(cfg, basket_id="GBPUSDUSDJPYBIDIR")


def test_h3v1_with_BEAR_suffix_accepted():
    """H3_spread@1 has no bidirectional param -> defaults False -> BEAR/BULL required."""
    cfg = {
        "name": "H3_spread",
        "version": 1,
        "params": {},
    }
    _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBEAR")


# ════════════════════════════════════════════════════════════════════
# Violations — must raise ValueError with informative message
# ════════════════════════════════════════════════════════════════════

def test_h3v2_bidirectional_true_with_BEAR_suffix_rejected():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"bidirectional": True},
    }
    with pytest.raises(ValueError, match="does not end with 'BIDIR'"):
        _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBEAR")


def test_h3v2_bidirectional_false_with_BIDIR_suffix_rejected():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"bidirectional": False},
    }
    with pytest.raises(ValueError, match="does not end with 'BEAR' or 'BULL'"):
        _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBIDIR")


def test_h3v2_bidirectional_absent_with_unknown_suffix_rejected():
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {},
    }
    with pytest.raises(ValueError, match="does not end with 'BEAR' or 'BULL'"):
        _instantiate_rule(cfg, basket_id="EURUSDUSDJPY")  # no suffix at all


def test_h3v3_bidirectional_true_with_no_suffix_rejected():
    cfg = {
        "name": "H3_spread",
        "version": 3,
        "params": {"bidirectional": True},
    }
    with pytest.raises(ValueError, match="does not end with 'BIDIR'"):
        _instantiate_rule(cfg, basket_id="EURUSDUSDJPY")


def test_h3v1_with_BIDIR_suffix_rejected():
    """H3_spread@1 has no bidirectional support -> must not declare BIDIR."""
    cfg = {
        "name": "H3_spread",
        "version": 1,
        "params": {},
    }
    with pytest.raises(ValueError, match="does not end with 'BEAR' or 'BULL'"):
        _instantiate_rule(cfg, basket_id="EURUSDUSDJPYBIDIR")


# ════════════════════════════════════════════════════════════════════
# Other rule families MUST NOT be affected
# ════════════════════════════════════════════════════════════════════

def test_h2_recycle_basket_id_unchecked():
    """H2_recycle baskets use basket_id='H2' or similar — must not trigger the H3 check."""
    cfg = {
        "name": "H2_recycle",
        "version": 1,
        "params": {},
    }
    # H2 rule needs additional context (factor_column) but the convention check
    # must not be the failure surface. Passing basket_id without a direction suffix
    # should be fine for H2.
    try:
        _instantiate_rule(cfg, factor_column="compression_5d", basket_id="H2")
    except ValueError as e:
        if "basket_id convention violation" in str(e):
            pytest.fail(f"H2_recycle basket_id should not be checked by H3 convention: {e}")


def test_cointegration_meanrev_v1_2_basket_id_unchecked():
    """COINTREV v1.2 basket_ids are alphabetical pair concats (e.g. AUS200NAS100).
    The H3 convention must not apply to them."""
    cfg = {
        "name": "cointegration_meanrev_v1_2",
        "version": 1,
        "params": {},
    }
    try:
        _instantiate_rule(cfg, basket_id="AUS200NAS100")
    except ValueError as e:
        if "basket_id convention violation" in str(e):
            pytest.fail(f"cointegration_meanrev_v1_2 must not be checked by H3 convention: {e}")


# ════════════════════════════════════════════════════════════════════
# Test-mode invocation (empty basket_id) skips the check
# ════════════════════════════════════════════════════════════════════

def test_empty_basket_id_skips_check():
    """Existing tests call _instantiate_rule without basket_id; the convention
    check must skip rather than fail in that mode (test convenience)."""
    cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"bidirectional": True},
    }
    # basket_id defaults to "" — must not raise.
    _instantiate_rule(cfg)
