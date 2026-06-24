"""Tests for the Engine Patch A (v1.5.11) engine_features.invalid_fill_policy
plumbing: the pure resolver/validator (tools/engine_features.py) and its
integration with Stage -0.25 canonicalization (tools/canonical_schema.py).

Design: outputs/system_reports/02_engine_core/ENGINE_PATCH_A_DESIGN_v1_5_11_2026-06-23.md §6
Contract: default FAIL (byte-identical to today); unknown key/value raises;
the block is admissible (canonicalizes clean) once schema-registered.
"""

from __future__ import annotations

import pytest

from tools.engine_features import (
    DEFAULT_INVALID_FILL_POLICY,
    resolve_invalid_fill_policy,
)


# ---------------------------------------------------------------------------
# resolve_invalid_fill_policy — pure resolver/validator
# ---------------------------------------------------------------------------

def test_default_is_fail_when_block_absent():
    assert resolve_invalid_fill_policy({"symbols": ["XAUUSD"]}) == "FAIL"
    assert DEFAULT_INVALID_FILL_POLICY == "FAIL"


def test_explicit_fail_resolves_fail():
    d = {"engine_features": {"invalid_fill_policy": "FAIL"}}
    assert resolve_invalid_fill_policy(d) == "FAIL"


def test_explicit_skip_resolves_skip():
    d = {"engine_features": {"invalid_fill_policy": "SKIP"}}
    assert resolve_invalid_fill_policy(d) == "SKIP"


def test_empty_block_defaults_fail():
    # Block present but key omitted -> default FAIL.
    assert resolve_invalid_fill_policy({"engine_features": {}}) == "FAIL"


def test_unknown_value_raises():
    d = {"engine_features": {"invalid_fill_policy": "SKIPP"}}
    with pytest.raises(ValueError, match="invalid_fill_policy"):
        resolve_invalid_fill_policy(d)


def test_unknown_subkey_raises():
    d = {"engine_features": {"invalid_fill_policy": "FAIL", "foo": 1}}
    with pytest.raises(ValueError, match="unknown key"):
        resolve_invalid_fill_policy(d)


def test_non_mapping_block_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        resolve_invalid_fill_policy({"engine_features": "SKIP"})


def test_lowercase_value_rejected():
    # Value domain is exact-case {FAIL, SKIP}; no silent normalization.
    with pytest.raises(ValueError):
        resolve_invalid_fill_policy({"engine_features": {"invalid_fill_policy": "skip"}})


# ---------------------------------------------------------------------------
# Stage -0.25 canonicalization integration
# ---------------------------------------------------------------------------

def _minimal_directive(engine_features=None) -> dict:
    d = {
        "test": {
            "name": "X",
            "family": "BRK",
            "strategy": "65_BRK_XAUUSD_5M_PSBRK_S01_V4_P17",
            "broker": "OctaFx",
            "timeframe": "5m",
            "start_date": "2024-01-02",
            "end_date": "2026-03-20",
        },
        "symbols": ["XAUUSD"],
        "indicators": ["indicators.volatility.atr"],
        "execution_rules": {"stop_loss": {"atr_multiplier": 1.0}},
    }
    if engine_features is not None:
        d["engine_features"] = engine_features
    return d


def test_canonicalize_accepts_engine_features_block():
    from tools.canonicalizer import canonicalize

    parsed = _minimal_directive({"invalid_fill_policy": "SKIP"})
    canonical, canonical_yaml, diff_lines, violations, has_drift = canonicalize(parsed)

    assert has_drift is False
    assert canonical["engine_features"] == {"invalid_fill_policy": "SKIP"}
    assert "engine_features" in canonical_yaml


def test_canonicalize_default_directive_has_no_engine_features():
    # A directive without the block is unchanged — byte-identical contract:
    # registering the schema must not perturb existing directives.
    from tools.canonicalizer import canonicalize

    parsed = _minimal_directive()
    canonical, _yaml, _diff, _viol, has_drift = canonicalize(parsed)
    assert has_drift is False
    assert "engine_features" not in canonical


def test_canonicalize_rejects_unknown_engine_features_subkey():
    from tools.canonicalizer import canonicalize, CanonicalizationError

    parsed = _minimal_directive({"invalid_fill_policy": "FAIL", "bogus": True})
    with pytest.raises(CanonicalizationError, match="UNKNOWN_NESTED_KEY"):
        canonicalize(parsed)
