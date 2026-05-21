"""Test that directive_reconciler honors the fixture registry.

Regression guard against the 2026-05-20 incident where `directive_reconciler
--execute` purged 270 orphan .txt files including a test fixture, breaking
12 broader-pytest tests in the basket suite.

The fix added a 4th living-signal (tests/_fixtures/directives.yaml) — this
test exercises that signal and would fail if the load path silently
returned an empty set (the fail-soft branch).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_fixture_directive_is_protected_from_purge():
    """The H2 fixture must be recognized as living even when absent from
    master_filter, registry, and FSM state."""
    from tools.directive_reconciler import _load_fixture_directives

    fixtures = _load_fixture_directives()
    assert "90_PORT_H2_5M_RECYCLE_S01_V1_P00" in fixtures, (
        "Fixture registry must list the basket dispatch test fixture. "
        "If you remove it from tests/_fixtures/directives.yaml, the "
        "next directive_reconciler --execute will purge the .txt and "
        "break test_basket_directive_phase5 + test_basket_dispatch_phase5b."
    )


def test_fixture_registry_load_is_failsoft(tmp_path, monkeypatch):
    """A malformed YAML must yield an empty set (warn, don't crash)."""
    import tools.directive_reconciler as dr
    bogus = tmp_path / "bogus.yaml"
    bogus.write_text("{[ not yaml ]:", encoding="utf-8")
    monkeypatch.setattr(dr, "FIXTURE_REGISTRY_PATH", bogus)
    result = dr._load_fixture_directives()
    assert result == frozenset()


def test_fixture_registry_missing_file_is_failsoft(tmp_path, monkeypatch):
    """An absent YAML must yield an empty set (the default)."""
    import tools.directive_reconciler as dr
    monkeypatch.setattr(dr, "FIXTURE_REGISTRY_PATH", tmp_path / "missing.yaml")
    result = dr._load_fixture_directives()
    assert result == frozenset()
