"""Validator-specific tests for the SIGNAL_PRIMITIVE / PIVOT_SOURCE contract,
now enforced at admission by tools.semantic_validator (declared indicators only).

These replace the directive-bulk scan in test_indicator_semantic_contracts.py:
the contract is a property of each DECLARED signal indicator and is checked at
admission / pre-backtest (where the decision is made), not by re-scanning every
completed directive at commit time. Engine-internal regime inputs (ema_regime,
realized_vol, ...) are never declared by strategies, so they are out of scope
by construction. See project_semantic_contract_gate_migration.

Targeted + fast: each test exercises _enforce_signal_primitive_contract directly
on a small set of real indicator modules. No directive scan, no pipeline.
"""
from __future__ import annotations

import pytest

from tools.semantic_validator import _enforce_signal_primitive_contract


def test_compliant_declared_indicator_admits():
    """A declared indicator with a valid, allowlisted primitive passes.
    indicators.volatility.atr declares SIGNAL_PRIMITIVE='wilder_rma_tr'."""
    _enforce_signal_primitive_contract({"indicators.volatility.atr"})  # no raise


def test_empty_declared_set_admits():
    """No declared indicators -> nothing to validate -> no raise."""
    _enforce_signal_primitive_contract(set())


def test_declared_non_signal_indicator_is_rejected():
    """Architectural rule: directives may declare only SIGNAL indicators.
    Declaring an engine-owned/feature indicator (no SIGNAL_PRIMITIVE) is rejected
    at admission. realized_vol is such a feature — a regime input read via ctx,
    not a declarable signal — so declaring it must fail."""
    with pytest.raises(ValueError, match="(?i)SIGNAL_PRIMITIVE"):
        _enforce_signal_primitive_contract({"indicators.volatility.realized_vol"})


def test_not_allowlisted_primitive_blocks_admission():
    """A declared indicator whose primitive is not in the allowlist fails.
    indicators.stats.ratio_hedged_spread_zscore declares an unlisted primitive."""
    with pytest.raises(ValueError, match="(?i)not in allowlist"):
        _enforce_signal_primitive_contract({"indicators.stats.ratio_hedged_spread_zscore"})


def test_pivot_source_inconsistency_blocks_admission(monkeypatch):
    """A pivot-class primitive (pivot_k3) that declares PIVOT_SOURCE='none' and
    does not import swing_pivots violates rules 3 + 5. Driven via a controlled
    fake module (real indicators are consistent, so there's no live offender)."""
    import importlib
    import types
    fake = types.SimpleNamespace(SIGNAL_PRIMITIVE="pivot_k3", PIVOT_SOURCE="none")
    monkeypatch.setattr(importlib, "import_module", lambda name: fake)
    with pytest.raises(ValueError, match="(?i)swing_pivots|PIVOT_SOURCE"):
        _enforce_signal_primitive_contract({"indicators.structure.fake_pivot_only"})


def test_mixed_set_reports_only_the_offender():
    """A set with one compliant + one missing-primitive indicator fails, and the
    message names the offender (realized_vol), not the compliant one (atr)."""
    with pytest.raises(ValueError) as exc:
        _enforce_signal_primitive_contract(
            {"indicators.volatility.atr", "indicators.volatility.realized_vol"}
        )
    assert "realized_vol" in str(exc.value)
    assert "volatility.atr:" not in str(exc.value)
