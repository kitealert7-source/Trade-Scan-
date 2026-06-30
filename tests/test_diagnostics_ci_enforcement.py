"""Diagnostic Contract — CI enforcement (the anti-decay mechanism).

Per feedback_enforceable_mechanisms_only: a contract that gates *may* speak
decays to today's heterogeneity. This test makes it structural. It fails when:

  (a) any `Diagnostic(code="...")` constructed anywhere under tools/ references a
      code NOT registered in governance/diagnostics/catalog.yaml (drift);
  (b) any catalog entry is missing a required field, has an empty field, or an
      invalid category / next_action / severity;
  (c) a converted gate reverts to a bare-string failure for a wired code.

Mirrors the abi_audit triple-gate pattern: detection is mechanical, not advisory.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.diagnostics import load_catalog, validate_catalog

TOOLS_DIR = REPO_ROOT / "tools"

# Matches a literal-code construction: Diagnostic(code="x.Y" ...) / single quotes.
_DIAGNOSTIC_CODE_RE = re.compile(r"""Diagnostic\(\s*code\s*=\s*["']([^"']+)["']""")

# Gates converted in Phase 1: file -> the code(s) that file must construct via
# the contract. Used both to assert registration and to guard against reverts.
_CONVERTED = {
    "tools/canonicalizer.py": ["canonicalizer.UNKNOWN_NESTED_KEY"],
    "tools/orchestration/admission_controller.py": ["classifier.IDENTITY_CHANGE"],
}


def _iter_tool_sources():
    for path in TOOLS_DIR.rglob("*.py"):
        yield path, path.read_text(encoding="utf-8")


def _all_constructed_codes() -> dict[str, list[Path]]:
    """code -> [files that construct it as a Diagnostic literal under tools/]."""
    found: dict[str, list[Path]] = {}
    for path, text in _iter_tool_sources():
        for code in _DIAGNOSTIC_CODE_RE.findall(text):
            found.setdefault(code, []).append(path)
    return found


# ---------------------------------------------------------------------------
# (b) Catalog integrity
# ---------------------------------------------------------------------------
def test_catalog_is_valid():
    errors = validate_catalog(load_catalog())
    assert errors == [], "Catalog validation failures:\n" + "\n".join(errors)


def test_validate_catalog_detects_missing_field():
    bad = {"x.MISSING": {"category": "SCHEMA"}}  # missing nearly everything
    errors = validate_catalog(bad)
    assert any("missing required field" in e for e in errors)


def test_validate_catalog_detects_invalid_enum():
    bad = {
        "x.BAD": {
            "category": "BOGUS", "error": "e", "cause": "c", "why_now": "w",
            "source": "s", "remedy": "r", "next_action": "noop",
            "auto_fixable": False, "severity": "loud", "doc_ref": "d",
        }
    }
    errors = validate_catalog(bad)
    assert any("invalid category" in e for e in errors)
    assert any("invalid next_action" in e for e in errors)
    assert any("invalid severity" in e for e in errors)


def test_validate_catalog_detects_empty_field():
    bad = {
        "x.EMPTY": {
            "category": "SCHEMA", "error": "  ", "cause": "c", "why_now": "w",
            "source": "s", "remedy": "r", "next_action": "continue",
            "auto_fixable": False, "severity": "error", "doc_ref": "d",
        }
    }
    errors = validate_catalog(bad)
    assert any("field 'error' is empty" in e for e in errors)


def test_validate_catalog_requires_namespaced_code():
    bad = {
        "UNNAMESPACED": {
            "category": "SCHEMA", "error": "e", "cause": "c", "why_now": "w",
            "source": "s", "remedy": "r", "next_action": "continue",
            "auto_fixable": False, "severity": "error", "doc_ref": "d",
        }
    }
    errors = validate_catalog(bad)
    assert any("must be namespaced" in e for e in errors)


def test_validate_catalog_requires_bool_auto_fixable():
    bad = {
        "x.NOTBOOL": {
            "category": "SCHEMA", "error": "e", "cause": "c", "why_now": "w",
            "source": "s", "remedy": "r", "next_action": "continue",
            "auto_fixable": "false", "severity": "error", "doc_ref": "d",
        }
    }
    errors = validate_catalog(bad)
    assert any("auto_fixable must be a bool" in e for e in errors)


# ---------------------------------------------------------------------------
# (a) Every code constructed under tools/ is registered
# ---------------------------------------------------------------------------
def test_all_constructed_codes_are_registered():
    catalog = load_catalog()
    constructed = _all_constructed_codes()
    unregistered = {
        code: [str(p.relative_to(REPO_ROOT)) for p in paths]
        for code, paths in constructed.items()
        if code not in catalog
    }
    assert not unregistered, (
        "Diagnostic codes constructed under tools/ but not in the catalog: "
        f"{unregistered}"
    )


# ---------------------------------------------------------------------------
# (c) Converted gates actually use the contract (anti-revert)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rel_path,codes", list(_CONVERTED.items()))
def test_converted_gate_constructs_contract(rel_path, codes):
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    constructed = set(_DIAGNOSTIC_CODE_RE.findall(text))
    for code in codes:
        assert code in constructed, (
            f"{rel_path} must construct Diagnostic(code={code!r}) "
            f"(found: {sorted(constructed)})"
        )


def test_canonicalizer_unknown_nested_key_is_not_bare_string():
    # Guard against a revert to the old bare-string raise.
    text = (REPO_ROOT / "tools" / "canonicalizer.py").read_text(encoding="utf-8")
    assert "UNKNOWN_NESTED_KEY: Unknown keys" not in text, (
        "canonicalizer.py reverted to a bare-string UNKNOWN_NESTED_KEY failure; "
        "it must raise via Diagnostic(code='canonicalizer.UNKNOWN_NESTED_KEY')."
    )
