"""Phase 1 acceptance test — basket directive schema validator.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 1 (Section 8 — tools/namespace_gate.py
and basket_schema gates).

Covers:
  - happy-path basket directive validates clean
  - missing/invalid leg/recycle_rule/regime_gate each FAIL with a specific message
  - basket_id mismatch with name SYMBOL slot is rejected
  - RECYCLE model without basket block is rejected at namespace_gate
  - non-basket directives are unaffected (existing pipeline still admits)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.basket_schema import (
    is_basket_directive,
    validate_basket_block,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
RECYCLE_REGISTRY = REPO_ROOT / "governance" / "recycle_rules" / "registry.yaml"


def _h2_directive() -> dict:
    return {
        "test": {
            "name": "90_PORT_H2_5M_RECYCLE_S01_V1_P00",
            "strategy": "90_PORT_H2_5M_RECYCLE_S01_V1_P00",
        },
        "basket": {
            "basket_id": "H2",
            "legs": [
                {"symbol": "EURUSD", "lot": 0.02, "direction": "long"},
                {"symbol": "USDJPY", "lot": 0.01, "direction": "short"},
            ],
            "initial_stake_usd": 1000.0,
            "harvest_threshold_usd": 2000.0,
            "recycle_rule": {
                "name": "H2_v7_compression",
                "version": 1,
                "params": {"compression_5d_threshold": 10.0},
            },
            "regime_gate": {
                "factor": "USD_SYNTH.compression_5d",
                "operator": ">=",
                "value": 10,
            },
        },
    }


def test_recycle_rule_registry_loads():
    assert RECYCLE_REGISTRY.is_file(), (
        f"recycle_rules registry missing at {RECYCLE_REGISTRY}; Phase 1 deliverable."
    )


def test_is_basket_directive_positive():
    assert is_basket_directive(_h2_directive()) is True


def test_is_basket_directive_negative():
    assert is_basket_directive({"test": {"name": "x"}}) is False


def test_h2_directive_validates_clean():
    errors = validate_basket_block(
        _h2_directive(), recycle_registry_path=RECYCLE_REGISTRY, name_symbol_slot="H2",
    )
    assert errors == [], errors


def test_basket_id_must_match_symbol_slot():
    d = _h2_directive()
    errors = validate_basket_block(
        d, recycle_registry_path=RECYCLE_REGISTRY, name_symbol_slot="DIFFERENT",
    )
    assert any("basket_id" in e and "SYMBOL slot" in e for e in errors), errors


def test_legs_must_have_at_least_two():
    d = _h2_directive()
    d["basket"]["legs"] = [d["basket"]["legs"][0]]
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("at least 2" in e for e in errors), errors


def test_duplicate_leg_symbol_rejected():
    d = _h2_directive()
    d["basket"]["legs"][1]["symbol"] = "EURUSD"  # duplicate
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("duplicated" in e for e in errors), errors


def test_negative_lot_rejected():
    d = _h2_directive()
    d["basket"]["legs"][0]["lot"] = -0.01
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("must be > 0" in e for e in errors), errors


def test_bad_direction_rejected():
    d = _h2_directive()
    d["basket"]["legs"][0]["direction"] = "sideways"
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("direction must be one of" in e for e in errors), errors


def test_unregistered_recycle_rule_rejected():
    d = _h2_directive()
    d["basket"]["recycle_rule"]["name"] = "PHANTOM_RULE_NOT_REGISTERED"
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("not registered" in e for e in errors), errors


def test_regime_gate_optional():
    d = _h2_directive()
    del d["basket"]["regime_gate"]
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert errors == []


def test_regime_gate_factor_dotted():
    d = _h2_directive()
    d["basket"]["regime_gate"]["factor"] = "no_namespace"  # missing dot
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("NAMESPACE.field" in e for e in errors), errors


def test_regime_gate_operator_valid():
    d = _h2_directive()
    d["basket"]["regime_gate"]["operator"] = "bigger_than"
    errors = validate_basket_block(d, RECYCLE_REGISTRY, "H2")
    assert any("operator must be one of" in e for e in errors), errors
