"""
test_warmup_resolver_signature.py

Regression test for the 2026-04-19 → 2026-05-06 silent-fallback incident.

Background
----------
Commit 31f0b38 (2026-04-19) updated `tools/run_stage1.py` to call:

    resolve_strategy_warmup(_indicator_list, base_tf_minutes=_base_tf_min)

…but the resolver in `engines/indicator_warmup_resolver.py` was never
updated to accept `base_tf_minutes`. Every Stage1 run for 17 days hit a
TypeError that the bare `except Exception` at run_stage1.py:982-984
silently swallowed, falling back to a 250-bar default.

This test locks two invariants so a future refactor cannot resurrect
the regression:

1. The resolver signature MUST accept `base_tf_minutes` as a keyword
   argument without raising TypeError.
2. The 2026-04-19 call shape — i.e. the literal kwarg call from
   `run_stage1.py` — MUST return an integer, not raise.

If a future refactor changes the resolver signature, both checks fail
loudly here at gate-suite time rather than in production.

Run:
    python -m pytest tools/tests/test_warmup_resolver_signature.py -v
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engines.indicator_warmup_resolver import resolve_strategy_warmup


# ─── Signature invariants ───────────────────────────────────────────────


def test_resolver_accepts_base_tf_minutes_kwarg():
    """Locks Option 1 fix: signature must accept `base_tf_minutes`.

    This is the exact call shape used by tools/run_stage1.py:974.
    Pre-fix this raised TypeError; post-fix it must succeed.
    """
    sig = inspect.signature(resolve_strategy_warmup)
    assert "base_tf_minutes" in sig.parameters, (
        "resolve_strategy_warmup must accept `base_tf_minutes` kwarg. "
        "If you removed it, the bare `except Exception` in run_stage1.py "
        "will silently swallow the TypeError and fall back to 250 bars — "
        "see incident 2026-04-19 → 2026-05-06."
    )


def test_resolver_kwarg_is_optional():
    """Backwards compat: resolver must still work without the kwarg."""
    sig = inspect.signature(resolve_strategy_warmup)
    param = sig.parameters["base_tf_minutes"]
    assert param.default is not inspect.Parameter.empty, (
        "`base_tf_minutes` must have a default value (currently None) so "
        "callers that haven't been migrated continue to work."
    )


# ─── Behavioral invariants — exact incident shape ───────────────────────


@pytest.fixture
def common_indicators():
    """Indicators present in most active strategies (atr, rsi)."""
    return [
        {"name": "atr", "params": {"period": 14}},
        {"name": "rsi", "params": {"period": 14}},
    ]


def test_kwarg_call_does_not_raise_typerror(common_indicators):
    """Locks the exact regression: the 2026-04-19 call shape must work.

    Pre-fix this raised:
      TypeError: resolve_strategy_warmup() got an unexpected keyword
                 argument 'base_tf_minutes'

    Post-fix this returns an integer.
    """
    # Should not raise
    result = resolve_strategy_warmup(common_indicators, base_tf_minutes=15)
    assert isinstance(result, int), f"expected int, got {type(result).__name__}"
    assert result >= 0, "warmup count cannot be negative"


def test_kwarg_call_returns_same_as_no_kwarg(common_indicators):
    """While Option 2 (time-aware conversion) is deferred, the resolver
    must return the same value with or without the kwarg.

    When Option 2 lands, this test should be REPLACED with a test that
    verifies the time-aware conversion (currently passing kwarg should
    still produce identical output to no-kwarg).
    """
    result_with_kwarg = resolve_strategy_warmup(common_indicators, base_tf_minutes=15)
    result_no_kwarg = resolve_strategy_warmup(common_indicators)
    assert result_with_kwarg == result_no_kwarg, (
        "While time-aware conversion is deferred, kwarg path must be "
        "identical to no-kwarg path. If you implemented Option 2, "
        "update this test rather than removing it."
    )


def test_kwarg_call_with_various_base_tfs(common_indicators):
    """Resolver must accept any positive int for base_tf_minutes
    (5M, 15M, 30M, 1H, 4H, 1D)."""
    for tf in (5, 15, 30, 60, 240, 1440):
        result = resolve_strategy_warmup(common_indicators, base_tf_minutes=tf)
        assert isinstance(result, int), (
            f"resolver must return int for base_tf_minutes={tf}"
        )


def test_kwarg_call_with_none_base_tf(common_indicators):
    """Default None must work (resolver currently ignores the kwarg)."""
    result = resolve_strategy_warmup(common_indicators, base_tf_minutes=None)
    assert isinstance(result, int)


# ─── Call-site simulation ───────────────────────────────────────────────


def test_run_stage1_call_shape():
    """Simulate the exact call from tools/run_stage1.py:974.

    If this test fails, the call site or resolver has drifted and
    Stage1 backtests are silently using the 250-bar fallback again.
    """
    from engines.utils.timeframe import parse_freq_to_minutes

    # Same shape as run_stage1.py:963-974
    timeframe_str = "15m"
    base_tf_min = parse_freq_to_minutes(timeframe_str)
    indicator_list = [
        {"name": "atr", "params": {"period": 14}},
        {"name": "rsi", "params": {"period": 14}},
    ]

    # Pre-fix: TypeError. Post-fix: returns int.
    try:
        resolved = resolve_strategy_warmup(indicator_list, base_tf_minutes=base_tf_min)
    except TypeError as e:
        pytest.fail(
            f"REGRESSION: resolve_strategy_warmup() raised TypeError on the "
            f"run_stage1.py call shape ({e}). This is the exact incident "
            f"from 2026-04-19. The bare `except Exception` at "
            f"run_stage1.py:982 will swallow it and fall back to 250 bars."
        )

    assert isinstance(resolved, int)
    assert resolved >= 0


def test_resolver_does_not_silently_fall_through_to_default(common_indicators):
    """When indicators have a real warmup formula, the resolver MUST
    return that value, not a hardcoded default. This catches the case
    where a refactor accidentally introduces a bare except inside the
    resolver itself."""
    # ATR period=14 → warmup = period*2 = 28 (per registry)
    # RSI period=14 → warmup = period = 14
    # Max should be 28, NOT a default like 250.
    result = resolve_strategy_warmup(common_indicators, base_tf_minutes=15)
    # The resolver should produce a meaningful value, not the 250 fallback.
    # Allow some headroom for registry changes, but reject the suspicious
    # exact-250 result that would indicate fallthrough.
    assert result < 250 or result > 250, (
        f"Suspicious result: resolver returned exactly 250 — this is the "
        f"signature of the silent fallback path in run_stage1.py:984. "
        f"Verify the resolver actually consulted the registry."
    )


# ─── Structural invariant: no catch-all in the warmup block ─────────────


def test_run_stage1_warmup_block_has_no_catchall_exception():
    """Architectural lock: the warmup-resolution block in run_stage1.py
    must NOT contain `except Exception` or a bare `except:`.

    Reasoning: every exception that can come out of that block —
    ImportError on a broken strategy, AttributeError on a bad
    STRATEGY_SIGNATURE, KeyError on a malformed registry,
    RegistryFormulaError, yaml.YAMLError, etc. — is an infra defect,
    not a recoverable runtime condition. A catch-all would silently
    fall back to 250 bars and ship subtly-wrong backtests, which is
    exactly the failure mode that produced the 2026-04-19 →
    2026-05-06 incident.

    Specific named excepts (TypeError, ValueError, etc.) are allowed
    and expected — they exist to give clearer operator-facing messages.
    """
    import ast

    src_path = PROJECT_ROOT / "tools" / "run_stage1.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    # Find the warmup block by sentinel marker comment in source — we
    # can't easily locate it via AST since it's nested inside main(),
    # so use line-anchored scanning. Pull every except handler that
    # falls within the warmup region.
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    # `(invariant #8)` distinguishes the active warmup block from earlier
    # legacy comment occurrences of "WARM-UP EXTENSION PROVISION".
    start_marker = "WARM-UP EXTENSION PROVISION (invariant #8)"
    end_marker = "INVARIANT: WARMUP RESOLUTION MUST NOT SILENTLY FAIL"
    start_lineno = None
    end_lineno = None
    for i, line in enumerate(src_lines, start=1):
        if start_marker in line and start_lineno is None:
            start_lineno = i
        elif end_marker in line and start_lineno is not None:
            end_lineno = i
            break

    assert start_lineno is not None, "could not find warmup block start marker"
    assert end_lineno is not None, "could not find warmup block end marker"

    offending: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not (start_lineno <= node.lineno <= end_lineno):
            continue
        if node.type is None:
            offending.append(f"line {node.lineno}: bare `except:`")
            continue
        # Reject `except Exception` (and `except BaseException`)
        if isinstance(node.type, ast.Name) and node.type.id in {
            "Exception", "BaseException"
        }:
            offending.append(f"line {node.lineno}: `except {node.type.id}`")
        # Reject tuple containing Exception/BaseException
        elif isinstance(node.type, ast.Tuple):
            for elt in node.type.elts:
                if isinstance(elt, ast.Name) and elt.id in {
                    "Exception", "BaseException"
                }:
                    offending.append(
                        f"line {node.lineno}: tuple includes `{elt.id}`"
                    )

    assert not offending, (
        "Warmup block contains catch-all exception handler(s):\n  "
        + "\n  ".join(offending)
        + "\n\nA catch-all silently swallows infra defects (ImportError, "
        "AttributeError, KeyError, RegistryFormulaError, yaml.YAMLError) "
        "and falls back to 250 bars — the exact failure mode of the "
        "2026-04-19 → 2026-05-06 incident. Use specific exception "
        "classes or let the exception propagate as a run failure."
    )


def test_run_stage1_warmup_block_has_named_typeerror_handler():
    """Locks the Option 3 fix: the warmup block MUST handle TypeError
    explicitly with a FATAL message, so a future signature drift can
    never re-enter the silent-fallback regime.
    """
    import ast

    src_path = PROJECT_ROOT / "tools" / "run_stage1.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    src_lines = src_path.read_text(encoding="utf-8").splitlines()

    # `(invariant #8)` distinguishes the active warmup block from earlier
    # legacy comment occurrences of "WARM-UP EXTENSION PROVISION".
    start_marker = "WARM-UP EXTENSION PROVISION (invariant #8)"
    end_marker = "INVARIANT: WARMUP RESOLUTION MUST NOT SILENTLY FAIL"
    start_lineno = None
    end_lineno = None
    for i, line in enumerate(src_lines, start=1):
        if start_marker in line and start_lineno is None:
            start_lineno = i
        elif end_marker in line and start_lineno is not None:
            end_lineno = i
            break

    found_typeerror_handler = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not (start_lineno <= node.lineno <= end_lineno):
            continue
        # Single class: except TypeError
        if isinstance(node.type, ast.Name) and node.type.id == "TypeError":
            found_typeerror_handler = True
            break
        # Tuple including TypeError: except (TypeError, ...)
        if isinstance(node.type, ast.Tuple):
            for elt in node.type.elts:
                if isinstance(elt, ast.Name) and elt.id == "TypeError":
                    found_typeerror_handler = True
                    break

    assert found_typeerror_handler, (
        "Warmup block must explicitly handle TypeError (resolver "
        "signature drift). Without it, signature drift falls through "
        "to runtime and is hard to diagnose. See incident "
        "2026-04-19 → 2026-05-06."
    )
