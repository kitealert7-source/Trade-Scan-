"""Diagnostic Contract — core object, catalog loader, and renderer tests.

Covers tools/diagnostics: enums, Diagnostic resolution/templating from the
catalog, safe-format behaviour, GateError transport, and render() output shape
(the boxed §2 block, ASCII/console-safe).

No production directives or pipeline state are touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.diagnostics import (
    Category,
    Diagnostic,
    GateError,
    NextAction,
    Severity,
    UnknownDiagnosticCode,
    _safe_format,
    load_catalog,
    render,
)


# ---------------------------------------------------------------------------
# Enums (closed vocabularies)
# ---------------------------------------------------------------------------
def test_category_enum_values():
    assert {c.value for c in Category} == {
        "IDENTITY", "NAMESPACE", "SCHEMA", "ENGINE",
        "EXECUTION", "DATA", "GOVERNANCE", "FSM",
    }


def test_next_action_enum_values():
    assert {n.value for n in NextAction} == {
        "stop_and_request_approval", "retry_after_autofix",
        "continue", "abort_directive",
    }


def test_severity_enum_values():
    assert {s.value for s in Severity} == {"error", "warn"}


# ---------------------------------------------------------------------------
# Safe templating
# ---------------------------------------------------------------------------
def test_safe_format_substitutes_known_keys():
    assert _safe_format("{a}-{b}", {"a": "X", "b": "Y"}) == "X-Y"


def test_safe_format_leaves_missing_key_visible():
    # A missing context key must not crash a gate's failure path.
    assert _safe_format("{a}-{b}", {"a": "X"}) == "X-{b}"


def test_safe_format_non_string_passthrough():
    assert _safe_format(None, {}) is None
    assert _safe_format(123, {}) == 123


# ---------------------------------------------------------------------------
# Diagnostic resolution from the catalog
# ---------------------------------------------------------------------------
def test_diagnostic_resolves_and_templates_from_catalog():
    d = Diagnostic(
        code="canonicalizer.UNKNOWN_NESTED_KEY",
        context={"block_name": "volatility_filter", "unknown": ["cooldown_bars"]},
    )
    assert d.category == "SCHEMA"
    assert d.next_action == "stop_and_request_approval"
    assert d.severity == "error"
    assert d.auto_fixable is False
    # context templated into the prose:
    assert "volatility_filter" in d.error
    assert "cooldown_bars" in d.error
    assert d.why_now  # WHY NOW field present and non-empty
    assert d.doc_ref


def test_diagnostic_unknown_code_raises():
    with pytest.raises(UnknownDiagnosticCode):
        Diagnostic(code="nonexistent.NOPE", context={})


def test_diagnostic_explicit_fields_bypass_catalog():
    # Passing category explicitly = renderer-isolation mode (no catalog lookup).
    d = Diagnostic(
        code="test.EXPLICIT",
        category="SCHEMA",
        error="boom",
        cause="c",
        why_now="w",
        source="s",
        remedy="r",
        next_action="continue",
        auto_fixable=False,
        severity="error",
        doc_ref="doc",
    )
    assert d.category == "SCHEMA"


def test_diagnostic_invalid_enum_rejected():
    with pytest.raises(ValueError):
        Diagnostic(
            code="test.BAD",
            category="NOT_A_CATEGORY",
            error="e", cause="c", why_now="w", source="s", remedy="r",
            next_action="continue", auto_fixable=False, severity="error",
            doc_ref="d",
        )


# ---------------------------------------------------------------------------
# Renderer — boxed §2 block, ASCII/console-safe
# ---------------------------------------------------------------------------
def _explicit(**over):
    base = dict(
        code="test.SAMPLE", category="IDENTITY", error="E", cause="C",
        why_now="WN", source="S", remedy="R", next_action="stop_and_request_approval",
        auto_fixable=False, severity="error", doc_ref="D",
    )
    base.update(over)
    return Diagnostic(**base)


def test_render_contains_all_contract_fields():
    out = render(_explicit())
    for label in ("ERROR", "CAUSE", "WHY NOW", "SOURCE", "REMEDY",
                  "NEXT ACTION", "AUTO-FIX", "DOC_REF"):
        assert f"{label.ljust(11)} : " in out or f"{label} :" in out, label
    # header carries code + category + severity
    assert "test.SAMPLE" in out
    assert "[category: IDENTITY]" in out
    assert "[severity: error]" in out


def test_render_error_severity_uses_ascii_marker():
    out = render(_explicit(severity="error"))
    assert out.startswith("[X] ")


def test_render_warn_severity_uses_ascii_marker():
    out = render(_explicit(severity="warn"))
    assert out.startswith("[!] ")


def test_render_is_pure_ascii():
    # Output is print()ed to the Windows cp1252 console; must encode cleanly.
    out = render(_explicit())
    out.encode("cp1252")  # raises UnicodeEncodeError on any stray glyph


def test_render_humanizes_next_action_and_note():
    out = render(_explicit(next_action="stop_and_request_approval",
                           next_action_note="a research decision"))
    assert "Stop-and-request-approval" in out
    assert "(a research decision)" in out


def test_render_autofix_yes_no():
    assert "AUTO-FIX    : Yes" in render(_explicit(auto_fixable=True))
    assert "AUTO-FIX    : No" in render(_explicit(auto_fixable=False))


def test_render_multiline_source_indents_continuation():
    out = render(_explicit(source="line1\nline2\nline3"))
    lines = out.split("\n")
    # First SOURCE line carries the label + colon:
    src_idx = next(i for i, ln in enumerate(lines) if ln.startswith("SOURCE"))
    assert lines[src_idx] == "SOURCE      : line1"
    # Continuation lines align under the value column (14 spaces), no colon:
    assert lines[src_idx + 1] == " " * 14 + "line2"
    assert lines[src_idx + 2] == " " * 14 + "line3"


# ---------------------------------------------------------------------------
# GateError transport
# ---------------------------------------------------------------------------
def test_gateerror_carries_diagnostic_and_renders():
    d = _explicit()
    err = GateError(d)
    assert err.diagnostic is d
    assert str(err) == render(d)


# ---------------------------------------------------------------------------
# Catalog loader against the real catalog
# ---------------------------------------------------------------------------
def test_load_catalog_has_wired_codes():
    cat = load_catalog()
    assert "classifier.IDENTITY_CHANGE" in cat
    assert "canonicalizer.UNKNOWN_NESTED_KEY" in cat
