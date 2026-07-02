"""Warmup-formula resolver: whitelisted n-ary function support (2026-07-02).

max/min are the canonical way to express "warmup = the longest of several
lookback windows" (e.g. kc_bands: max(ema_window, atr_period) + smooth). The
resolver evaluates them via a STRICT allowlist (CALL_FUNCTIONS) — positional
numeric args only, bare-name calls only — so it can resolve such formulas
without ever becoming a general code evaluator.

Regression for the kc_bands warmup that blocked session close on 2026-07-02
(RegistryFormulaError: Unsupported node type ast.Call).
"""

import pytest

from engines.indicator_warmup_resolver import (
    RegistryFormulaError,
    _safe_eval_formula,
)


class TestCallFunctions:
    def test_max_resolves(self):
        assert _safe_eval_formula(
            "max(ema_window, atr_period) + smooth",
            {"ema_window": 20, "atr_period": 14, "smooth": 3}, "kc_bands") == 23.0

    def test_min_resolves(self):
        assert _safe_eval_formula(
            "min(a, b)", {"a": 5, "b": 9}, "t") == 5.0

    def test_nested_calls_resolve(self):
        assert _safe_eval_formula(
            "max(a, min(b, c)) + 1", {"a": 10, "b": 30, "c": 7}, "t") == 11.0

    def test_multi_arg_max(self):
        assert _safe_eval_formula(
            "max(a, b, c)", {"a": 4, "b": 11, "c": 8}, "t") == 11.0

    def test_unknown_function_rejected(self):
        with pytest.raises(RegistryFormulaError, match="Unsupported function"):
            _safe_eval_formula("sqrt(a)", {"a": 9}, "t")

    def test_keyword_args_rejected(self):
        with pytest.raises(RegistryFormulaError, match="positional numeric args only"):
            _safe_eval_formula("max(a, key=b)", {"a": 1, "b": 2}, "t")

    def test_empty_args_rejected(self):
        with pytest.raises(RegistryFormulaError, match="at least one arg"):
            _safe_eval_formula("max()", {}, "t")

    def test_attribute_call_rejected(self):
        with pytest.raises(RegistryFormulaError):
            _safe_eval_formula("os.system(a)", {"a": 1}, "t")


def test_kc_bands_registry_formula_resolves_end_to_end():
    """The actual failing case: kc_bands resolves through the public API."""
    from engines.indicator_warmup_resolver import resolve_strategy_warmup
    result = resolve_strategy_warmup([{"name": "kc_bands", "params": {}}])
    assert isinstance(result, int) and result > 0
