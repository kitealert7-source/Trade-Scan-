"""
Unit tests for the Engine-Owned Fields Guard in tools.semantic_validator.

Covers the refined import policy (2026-04-23):
  1. Zero-tolerance reference rule -- imported engine-owned symbol must
     appear nowhere outside its ImportFrom node.
  2. Consumer-filter contract -- an engine-owned import MUST be paired
     with a behaviorally-effective FilterStack block that consumes the
     field.
  3. Legacy rules preserved -- df[<field>] = ... and bare callable
     invocation still hard-fail.

Tests construct strategy.py source on disk in a temp workspace and
drive `validate_semantic_signature` end-to-end. Each test case ensures
the correct behavior for a single permutation.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test fixtures: minimal strategy + directive pair, parameterized by the
# import/filter/reference permutation under test.
# ---------------------------------------------------------------------------


_STRATEGY_TEMPLATE = textwrap.dedent("""\
    from indicators.volatility.atr import atr
    from indicators.structure.hull_moving_average import hull_moving_average
    {extra_imports}
    from engines.filter_stack import FilterStack


    class Strategy:
        name = "{strategy_name}"
        timeframe = "15m"

        STRATEGY_SIGNATURE = {signature_literal}

        def __init__(self):
            self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)

        def prepare_indicators(self, df):
            df['atr'] = atr(df, window=14)
            df['hma'] = hull_moving_average(df['close'], period=50)
            {extra_prepare}
            return df

        def check_entry(self, ctx):
            if not self.filter_stack.allow_trade(ctx):
                return None
            {extra_check_entry}
            close = ctx.get('close')
            if close is None:
                return None
            return {{"signal": 1, "entry_reference_price": float(close), "entry_reason": "test"}}

        def check_exit(self, ctx):
            return False
""")


_DIRECTIVE_TEMPLATE = textwrap.dedent("""\
    test:
      name: {strategy_name}
      strategy: {strategy_name}
      timeframe: 15m
      start_date: 2024-01-01
      end_date: 2024-01-31
      broker: OCTAFX
      symbols: [XAUUSD]
    indicators:
    {indicator_lines}
    execution_rules:
      entry_logic:
        type: hma_trend_follow
      entry_when_flat_only: true
      exit_logic:
        type: time
        max_bars: 20
      pyramiding: false
      reset_on_exit: true
      stop_loss:
        type: atr_multiple
        atr_multiplier: 1.5
      take_profit:
        enabled: false
      trailing_stop:
        enabled: false
    order_placement:
      execution_timing: next_bar_open
      type: market
    position_management:
      lots: 0.01
    signal_version: 1
    signature_version: 2
    state_machine:
      entry:
        direction: long_and_short
        trigger: signal_bar
      no_reentry_after_stop: false
      session_reset: none
    trade_management:
      direction_restriction: long_and_short
      reentry:
        allowed: true
      session_reset: none
    version: 2
    {filter_block_yaml}
""")


_DEFAULT_INDICATORS = [
    "indicators.volatility.atr",
    "indicators.structure.hull_moving_average",
]


def _build_signature(extra_indicator: str | None, filter_block: dict | None) -> dict:
    sig = {
        "execution_rules": {
            "entry_logic": {"type": "hma_trend_follow"},
            "entry_when_flat_only": True,
            "exit_logic": {"type": "time", "max_bars": 20},
            "pyramiding": False,
            "reset_on_exit": True,
            "stop_loss": {"type": "atr_multiple", "atr_multiplier": 1.5},
            "take_profit": {"enabled": False},
            "trailing_stop": {"enabled": False},
        },
        "indicators": list(_DEFAULT_INDICATORS) + ([extra_indicator] if extra_indicator else []),
        "order_placement": {"execution_timing": "next_bar_open", "type": "market"},
        "position_management": {"lots": 0.01},
        "signal_version": 1,
        "signature_version": 2,
        "state_machine": {
            "entry": {"direction": "long_and_short", "trigger": "signal_bar"},
            "no_reentry_after_stop": False,
            "session_reset": "none",
        },
        "trade_management": {
            "direction_restriction": "long_and_short",
            "reentry": {"allowed": True},
            "session_reset": "none",
        },
        "version": 2,
    }
    if filter_block is not None:
        sig["volatility_filter"] = filter_block
    return sig


def _write_pair(
    tmp_path: Path,
    *,
    strategy_name: str,
    extra_imports: str,
    extra_prepare: str,
    extra_check_entry: str,
    signature: dict,
    filter_block: dict | None,
    extra_indicator: str | None,
) -> Path:
    """Create strategies/<name>/strategy.py and directive file on disk.

    Returns path to the directive.
    """
    import pprint

    # Write strategy.py under PROJECT_ROOT/strategies/<name>/
    import sys
    project_root = Path(__file__).resolve().parent.parent
    strat_dir = project_root / "strategies" / strategy_name
    strat_dir.mkdir(parents=True, exist_ok=True)
    strat_src = _STRATEGY_TEMPLATE.format(
        extra_imports=extra_imports,
        strategy_name=strategy_name,
        signature_literal=pprint.pformat(signature, sort_dicts=True),
        extra_prepare=extra_prepare,
        extra_check_entry=extra_check_entry,
    )
    (strat_dir / "strategy.py").write_text(strat_src, encoding="utf-8")

    # Write directive in tmp_path
    indicator_lines = "\n".join(
        f"  - {mod}" for mod in ([*_DEFAULT_INDICATORS] + ([extra_indicator] if extra_indicator else []))
    )
    if filter_block is None:
        filter_yaml = ""
    else:
        lines = ["volatility_filter:"]
        for k, v in filter_block.items():
            lines.append(f"  {k}: {_yaml_scalar(v)}")
        filter_yaml = "\n".join(lines)
    directive_src = _DIRECTIVE_TEMPLATE.format(
        strategy_name=strategy_name,
        indicator_lines=indicator_lines,
        filter_block_yaml=filter_yaml,
    )
    directive_path = tmp_path / f"{strategy_name}.txt"
    directive_path.write_text(directive_src, encoding="utf-8")

    return directive_path


def _yaml_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, str):
        return v
    return str(v)


def _cleanup(strategy_name: str):
    import shutil
    project_root = Path(__file__).resolve().parent.parent
    strat_dir = project_root / "strategies" / strategy_name
    if strat_dir.exists():
        shutil.rmtree(strat_dir)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------


def _validate(directive_path: Path):
    from tools.semantic_validator import validate_semantic_signature
    return validate_semantic_signature(str(directive_path))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


STRATEGY_PREFIX = "testguard_"


@pytest.fixture(autouse=True)
def _cleanup_stray(request):
    yield
    # Clean up any strategy directory created by the test.
    name = getattr(request.node, "_strategy_name", None)
    if name:
        _cleanup(name)


def _make(request, suffix):
    name = f"{STRATEGY_PREFIX}{suffix}"
    request.node._strategy_name = name
    return name


def test_pass_import_unreferenced_with_behavioral_filter(tmp_path, request):
    """Import allowed when symbol is unused AND behavioral filter declared."""
    name = _make(request, "pass_ok")
    filter_block = {"enabled": True, "operator": "gte", "required_regime": 0}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    assert _validate(directive) is True


def test_fail_import_referenced_in_check_entry(tmp_path, request):
    """Referencing the imported symbol anywhere fails (zero tolerance)."""
    name = _make(request, "ref_assign")
    filter_block = {"enabled": True, "operator": "gte", "required_regime": 0}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    # Indirect alias creation: `val = volatility_regime`
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="",
        extra_check_entry="val = volatility_regime",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="engine-owned symbol referenced after import"):
        _validate(directive)


def test_fail_import_passed_to_wrapper(tmp_path, request):
    """Pass-through into another function still fails."""
    name = _make(request, "ref_wrap")
    filter_block = {"enabled": True, "operator": "gte", "required_regime": 0}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="_ = dict(fn=volatility_regime)",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="engine-owned symbol referenced after import"):
        _validate(directive)


def test_fail_orphan_import_no_filter(tmp_path, request):
    """Import without any consumer filter is orphaned -> FAIL."""
    name = _make(request, "orphan_nofilter")
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=None,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="",
        extra_check_entry="",
        signature=sig,
        filter_block=None,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="behavioral consumer filter"):
        _validate(directive)


def test_fail_orphan_import_disabled_filter(tmp_path, request):
    """Import with enabled=False consumer filter -> FAIL."""
    name = _make(request, "orphan_disabled")
    filter_block = {"enabled": False, "required_regime": 0}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="behavioral consumer filter"):
        _validate(directive)


def test_fail_orphan_import_empty_filter(tmp_path, request):
    """Import with {enabled: True} only (no field-referencing key) -> FAIL."""
    name = _make(request, "orphan_empty")
    filter_block = {"enabled": True}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="behavioral consumer filter"):
        _validate(directive)


def test_fail_df_column_write(tmp_path, request):
    """df['volatility_regime'] = ... still hard-blocked."""
    name = _make(request, "dfwrite")
    filter_block = {"enabled": True, "required_regime": 0}
    sig = _build_signature(
        extra_indicator=None,
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="",
        extra_prepare="df['volatility_regime'] = 0",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator=None,
    )
    with pytest.raises(ValueError, match="forbidden df column writes"):
        _validate(directive)


def test_fail_bare_callable_via_referenced_import(tmp_path, request):
    """Calling the imported symbol is referenced AND a callable call.

    Should fail with either/both violation messages (zero-tolerance + call).
    """
    name = _make(request, "call_bare")
    filter_block = {"enabled": True, "required_regime": 0}
    sig = _build_signature(
        extra_indicator="indicators.volatility.volatility_regime",
        filter_block=filter_block,
    )
    directive = _write_pair(
        tmp_path,
        strategy_name=name,
        extra_imports="from indicators.volatility.volatility_regime import volatility_regime",
        extra_prepare="df['x'] = volatility_regime(df, window=14)",
        extra_check_entry="",
        signature=sig,
        filter_block=filter_block,
        extra_indicator="indicators.volatility.volatility_regime",
    )
    with pytest.raises(ValueError, match="engine-owned symbol referenced after import|forbidden function calls"):
        _validate(directive)


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
