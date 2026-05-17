"""Tests for basket_pipeline._instantiate_rule H2_recycle@5 dispatch (Phase C).

Locks in the wiring: when a directive specifies H2_recycle@5, the pipeline:
  - instantiates H2RecycleRuleV5 (not @1/@2/@3/@4)
  - threads all v1 params with correct defaults
  - threads new v5 params (pyramid_increment_usd, exit_recovery_usd,
    hard_floor_loss_usd) with sensible defaults
  - defaults factor_operator='<=' (inverted vs @1) and factor_min=5.0
  - threads identity kwargs (run_id / directive_id / basket_id)
  - leaves basket_runner unset (filled by BasketRunner.__init__'s back-ref)
"""
from __future__ import annotations

import pytest

from tools.basket_pipeline import _instantiate_rule
from tools.recycle_rules import (
    H2RecycleRule, H2RecycleRuleV2, H2RecycleRuleV3, H2RecycleRuleV4, H2RecycleRuleV5,
)


# ---------------------------------------------------------------------------
# Dispatch: name + version → correct class
# ---------------------------------------------------------------------------


def test_dispatch_h2_recycle_v5_returns_v5_instance():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    assert isinstance(rule, H2RecycleRuleV5)
    assert type(rule) is H2RecycleRuleV5


def test_dispatch_does_not_collide_with_v4():
    rule_v4 = _instantiate_rule(
        {"name": "H2_recycle", "version": 4, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    rule_v5 = _instantiate_rule(
        {"name": "H2_recycle", "version": 5, "params": {}},
        run_id="r1", directive_id="d1", basket_id="H2",
    )
    assert type(rule_v4) is H2RecycleRuleV4
    assert type(rule_v5) is H2RecycleRuleV5


# ---------------------------------------------------------------------------
# Default param threading for v5 (matches registry defaults)
# ---------------------------------------------------------------------------


def test_v5_defaults_match_registry():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5, "params": {}},
    )
    # V5-specific
    assert rule.pyramid_increment_usd == 10.0
    assert rule.exit_recovery_usd == 10.0
    assert rule.hard_floor_loss_usd == -10.0
    # Inverted gate defaults vs @1
    assert rule.factor_operator == "<="
    assert rule.factor_min == 5.0
    # Inherited
    assert rule.trigger_usd == 10.0
    assert rule.add_lot == 0.01
    assert rule.starting_equity == 1000.0
    assert rule.harvest_target_usd == 2000.0
    assert rule.dd_freeze_frac == 0.10
    assert rule.margin_freeze_frac == 0.15
    assert rule.leverage == 1000.0
    assert rule.factor_column == "compression_5d"


def test_v5_override_pyramid_increment():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5,
         "params": {"pyramid_increment_usd": 20.0}},
    )
    assert rule.pyramid_increment_usd == 20.0


def test_v5_override_exit_recovery():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5,
         "params": {"exit_recovery_usd": 15.0}},
    )
    assert rule.exit_recovery_usd == 15.0


def test_v5_override_hard_floor():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5,
         "params": {"hard_floor_loss_usd": -25.0}},
    )
    assert rule.hard_floor_loss_usd == -25.0


def test_v5_override_inherited_params():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5,
         "params": {"factor_min": 8.0, "factor_operator": ">=",
                    "harvest_target_usd": 3000.0}},
    )
    assert rule.factor_min == 8.0
    assert rule.factor_operator == ">="
    assert rule.harvest_target_usd == 3000.0


# ---------------------------------------------------------------------------
# Identity threading + back-ref contract
# ---------------------------------------------------------------------------


def test_v5_threads_identity_kwargs():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5, "params": {}},
        run_id="run_xyz789",
        directive_id="90_PORT_H2_5M_RECYCLE_S16_V1_P00",
        basket_id="H2",
    )
    assert rule.run_id == "run_xyz789"
    assert rule.directive_id == "90_PORT_H2_5M_RECYCLE_S16_V1_P00"
    assert rule.basket_id == "H2"


def test_v5_basket_runner_unset_at_instantiation():
    rule = _instantiate_rule(
        {"name": "H2_recycle", "version": 5, "params": {}},
    )
    assert rule.basket_runner is None


# ---------------------------------------------------------------------------
# Invalid params surface validation errors at dispatch time
# ---------------------------------------------------------------------------


def test_v5_invalid_pyramid_increment_raises():
    with pytest.raises(ValueError, match="pyramid_increment_usd"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 5,
             "params": {"pyramid_increment_usd": 0}},
        )


def test_v5_invalid_hard_floor_positive_raises():
    with pytest.raises(ValueError, match="hard_floor_loss_usd"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 5,
             "params": {"hard_floor_loss_usd": 10}},
        )


def test_v5_invalid_factor_operator_raises():
    with pytest.raises(ValueError, match="factor_operator"):
        _instantiate_rule(
            {"name": "H2_recycle", "version": 5,
             "params": {"factor_operator": "=="}},
        )
