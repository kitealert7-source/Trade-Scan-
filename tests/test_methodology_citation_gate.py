"""Tests for tools/methodology_citation_gate.check_methodology_citations (Task D).

Trigger: presence of a non-empty methodology_citations list.
Validation: governance/methodology/methodology_registry.yaml ONLY (repo-local,
no auto-memory coupling).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import tools.methodology_citation_gate as gate
from tools.methodology_citation_gate import (
    MethodologyCitationGateError,
    check_methodology_citations,
)


@pytest.fixture
def patched_registry(tmp_path, monkeypatch):
    def _set(slugs: list[str]) -> Path:
        reg = tmp_path / "methodology_registry.yaml"
        reg.write_text(
            yaml.safe_dump({"citations": [{"slug": s} for s in slugs]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "REGISTRY_PATH", reg)
        return reg
    return _set


def _directive(path: Path, citations) -> Path:
    doc: dict = {"test": {"start_date": "2025-01-01"}}
    if citations is not None:
        doc["methodology_citations"] = citations
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


# --- trigger / no-op -------------------------------------------------------

def test_absent_field_is_noop(tmp_path, patched_registry):
    patched_registry(["feedback_a"])
    d = _directive(tmp_path / "d.txt", None)
    check_methodology_citations(d)  # no raise


def test_empty_list_is_noop(tmp_path, patched_registry):
    patched_registry(["feedback_a"])
    d = _directive(tmp_path / "d.txt", [])
    check_methodology_citations(d)  # no raise


# --- validation ------------------------------------------------------------

def test_all_valid_slugs_pass(tmp_path, patched_registry):
    patched_registry(["feedback_a", "feedback_b", "feedback_c"])
    d = _directive(tmp_path / "d.txt", ["feedback_a", "feedback_c"])
    check_methodology_citations(d)  # no raise


def test_unknown_slug_rejects_and_names_it(tmp_path, patched_registry):
    patched_registry(["feedback_a", "feedback_b"])
    d = _directive(tmp_path / "d.txt", ["feedback_a", "feedback_TYPO"])
    with pytest.raises(MethodologyCitationGateError) as exc:
        check_methodology_citations(d)
    assert "feedback_TYPO" in str(exc.value)
    assert "feedback_a" not in str(exc.value).split("unknown")[1].split("Admissible")[0]


def test_bare_string_citation_treated_as_single(tmp_path, patched_registry):
    patched_registry(["feedback_a"])
    d = _directive(tmp_path / "d.txt", "feedback_a")
    check_methodology_citations(d)  # no raise


def test_bare_string_unknown_rejects(tmp_path, patched_registry):
    patched_registry(["feedback_a"])
    d = _directive(tmp_path / "d.txt", "feedback_nope")
    with pytest.raises(MethodologyCitationGateError, match="feedback_nope"):
        check_methodology_citations(d)


def test_malformed_field_rejects(tmp_path, patched_registry):
    patched_registry(["feedback_a"])
    d = _directive(tmp_path / "d.txt", {"slug": "feedback_a"})  # dict, not list
    with pytest.raises(MethodologyCitationGateError, match="malformed"):
        check_methodology_citations(d)


def test_no_filesystem_coupling_to_auto_memory(tmp_path, patched_registry, monkeypatch):
    """The gate must validate against the registry only — never touch a
    home-dir / auto-memory path. Sabotage HOME and confirm it still works."""
    patched_registry(["feedback_a"])
    monkeypatch.setenv("HOME", str(tmp_path / "nonexistent_home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "nonexistent_home"))
    d = _directive(tmp_path / "d.txt", ["feedback_a"])
    check_methodology_citations(d)  # no raise — proves no ~/.claude dependency


# --- live registry structure ----------------------------------------------

def test_live_registry_parses_and_is_well_formed():
    slugs = gate._load_admissible_slugs()
    assert slugs, "live methodology registry is empty"
    # every slug is a non-empty string, unique (set guarantees uniqueness)
    for s in slugs:
        assert isinstance(s, str) and s.strip()


def test_live_registry_contains_seed_doctrines():
    slugs = gate._load_admissible_slugs()
    for expected in (
        "feedback_test_window_must_match_signal_class",
        "feedback_screening_rules_for_research",
        "feedback_prove_then_falsify",
    ):
        assert expected in slugs, f"seed doctrine {expected!r} missing from registry"
