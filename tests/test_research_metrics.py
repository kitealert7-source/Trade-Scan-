"""Tests for the research-metrics registry validator (governs metrics_json).

Uses an in-memory fake registry for the contract cases; one test confirms the
real v1 registry parses and is intentionally empty.
"""
import pytest

from tools.portfolio.research_metrics import (
    MetricsRegistryError,
    load_registry,
    validate_metrics_json,
)

_REG = {
    "tail.worst_trade_pct": {"key": "tail.worst_trade_pct", "type": "float",
                             "namespace": "tail", "first_class": False},
    "cycle.count": {"key": "cycle.count", "type": "int",
                    "namespace": "cycle", "first_class": False},
    "regime.label": {"key": "regime.label", "type": "str",
                     "namespace": "regime", "first_class": False},
    "canonical_ret_dd": {"key": "canonical_ret_dd", "type": "float",
                         "namespace": "core", "first_class": True},
}


def test_none_and_empty_ok():
    validate_metrics_json(None, registry=_REG)
    validate_metrics_json("", registry=_REG)
    validate_metrics_json({}, registry=_REG)


def test_valid_scalars_pass():
    validate_metrics_json(
        {"tail.worst_trade_pct": -3.2, "cycle.count": 5, "regime.label": "cointegrated"},
        registry=_REG,
    )


def test_unknown_key_raises():
    with pytest.raises(MetricsRegistryError, match="unknown metric key"):
        validate_metrics_json({"bogus.metric": 1.0}, registry=_REG)


def test_nesting_rejected():
    with pytest.raises(MetricsRegistryError, match="scalar"):
        validate_metrics_json({"tail.worst_trade_pct": {"nested": 1}}, registry=_REG)


def test_list_value_rejected():
    with pytest.raises(MetricsRegistryError, match="scalar"):
        validate_metrics_json({"tail.worst_trade_pct": [1, 2]}, registry=_REG)


def test_type_mismatch_raises():
    with pytest.raises(MetricsRegistryError, match="expected int"):
        validate_metrics_json({"cycle.count": 1.5}, registry=_REG)


def test_bool_is_not_int():
    with pytest.raises(MetricsRegistryError, match="expected int"):
        validate_metrics_json({"cycle.count": True}, registry=_REG)


def test_first_class_key_rejected_in_json():
    with pytest.raises(MetricsRegistryError, match="first_class"):
        validate_metrics_json({"canonical_ret_dd": 1.5}, registry=_REG)


def test_json_string_is_parsed():
    validate_metrics_json('{"cycle.count": 3}', registry=_REG)


def test_real_v1_registry_loads_empty():
    # The shipped v1 registry is intentionally empty -> any extra key is unknown.
    assert load_registry() == {}
