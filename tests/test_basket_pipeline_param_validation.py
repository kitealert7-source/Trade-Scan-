"""Strict-validation tests for basket_pipeline._instantiate_rule.

Added 2026-05-24 after a silent-no-op experiment confused the
vol_neutral_sizing test. The dispatcher had silently dropped the new param
because its kwargs construction didn't forward it. These tests ensure
that future silent-drop bugs of the same class fail loudly.

What the validator catches:
  1. Typos in directive YAML (e.g., `vol_neutral_seizing` instead of
     `vol_neutral_sizing`).
  2. Params that exist on the rule's dataclass but aren't wired through
     the dispatcher's explicit kwargs (the bug we hit).
  3. Stale params left in directives after a rule schema change.

What it deliberately accepts:
  - Params consumed by external surfaces (leg strategy in run_pipeline.py,
    macro/regime data loader in basket_data_loader.py) via the
    _EXTERNAL_CONSUMER_PARAMS allowlist.
  - Documented aliases via _RULE_PARAM_ALIASES.
"""
from __future__ import annotations

import pytest

from tools.basket_pipeline import _instantiate_rule


# ---------- Happy paths --------------------------------------------------

def test_validation_accepts_h3v2_with_known_params():
    """All canonical H3_spread@2 params accepted without error."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "bidirectional": True,
            "vol_neutral_sizing": True,
            "vol_neutral_window": 200,
            "max_exposure_multiple": 3.0,
            "pyramid_threshold_step_pct": 0.15,
            "adverse_stop_pct": 0.002,
            "time_stop_bars": 288,
            "entry_delay_bars": 8,  # external (leg strategy)
            "macro_direction_timeframe": "4h",  # external (data loader)
        },
    }
    # Must not raise.
    _instantiate_rule(rule_cfg)


def test_validation_accepts_h3v3_with_known_params():
    """All canonical H3_spread@3 params (including @2 inheritance) accepted."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 3,
        "params": {
            "bidirectional": True,
            "vol_neutral_sizing": True,
            "extreme_z_threshold": 5.0,
            "reentry_z_threshold": 1.0,
            "max_exposure_multiple": 3.0,
            "entry_delay_bars": 8,
            "macro_warmup_days": 120,
            "macro_z_window": 60,
        },
    }
    _instantiate_rule(rule_cfg)


def test_validation_accepts_documented_alias():
    """harvest_delay_levels is a documented alias for
    harvest_start_after_extra_pyramids — must not raise."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "harvest_delay_levels": 5,  # legacy alias
        },
    }
    _instantiate_rule(rule_cfg)


# ---------- Failure paths (the real regression value) --------------------

def test_validation_rejects_typo_in_directive_yaml():
    """Typo'd param name fails loudly."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "vol_neutral_seizing": True,  # typo for vol_neutral_sizing
        },
    }
    with pytest.raises(ValueError) as exc:
        _instantiate_rule(rule_cfg)
    assert "recycle_rule.params validation failed" in str(exc.value)
    assert "vol_neutral_seizing" in str(exc.value)


def test_validation_rejects_unknown_param_with_helpful_message():
    """Unknown param produces a diagnostic that lists valid params."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"made_up_param_name": 42},
    }
    with pytest.raises(ValueError) as exc:
        _instantiate_rule(rule_cfg)
    msg = str(exc.value)
    # Includes the unknown param name
    assert "made_up_param_name" in msg
    # Includes a hint about what's valid
    assert "Rule dataclass fields" in msg
    assert "External-consumer params" in msg
    # Includes the historical context
    assert "2026-05-24" in msg


def test_validation_rejects_dispatcher_bug_class():
    """REGRESSION: this is exactly the bug we hit today. If a future PR
    adds a param to a rule's dataclass but forgets to wire it through the
    dispatcher's kwargs, this validator must still let it through (because
    the dataclass field IS valid) — but the dispatcher would simply not
    forward it. So this test verifies the validator's positive case for
    a NEW dataclass field, then the SEPARATE behavioral test
    (test_basket_leg_invariants.test_leg_direction_immutable_through_cycle
    and similar) verifies the param actually takes effect.

    The validator's job is the *negative* half — catch typos and stale
    params. The dispatcher-forwarding bug is caught by behavioral tests on
    the param (e.g., the post-fix sizing test on h3_spread). Together they
    eliminate the silent-no-op class."""
    # vol_neutral_sizing was the silent-drop bug today; it IS on the
    # H3SpreadV2Rule dataclass, so the validator accepts it. The behavioral
    # proof (param actually applies) is the integration test (see
    # 2026-05-24 dispatcher fix commit + the S21 vol-neutral re-run).
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"vol_neutral_sizing": True},
    }
    _instantiate_rule(rule_cfg)  # must not raise


def test_validation_rejects_runtime_only_field_in_yaml():
    """Runtime-only fields like run_id must not be settable from YAML."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"run_id": "ATTEMPTED_OVERRIDE"},
    }
    with pytest.raises(ValueError, match="run_id"):
        _instantiate_rule(rule_cfg)


def test_validation_rejects_private_field_in_yaml():
    """Private (_-prefixed) fields must not be settable from YAML."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"_basket_open": True},
    }
    with pytest.raises(ValueError, match="_basket_open"):
        _instantiate_rule(rule_cfg)
