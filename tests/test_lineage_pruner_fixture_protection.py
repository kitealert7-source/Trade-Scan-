"""Test that lineage_pruner (the pipeline-state-cleanup engine) honors the
fixture registry.

Regression guard against the 2026-05-22 incident: the basket-dispatch test
fixture `90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt` was protected for
`directive_reconciler` by cad47a0 (2026-05-21) but that protection was NOT
ported to `lineage_pruner._collect_directive_targets`, so the very next
pipeline-state-cleanup sweep re-quarantined the fixture and re-broke 12
broader-pytest tests across test_basket_directive_phase5,
test_basket_dispatch_phase5b, test_basket_path_b_phase5b2, and
test_basket_phase5c_real_data.

These tests exercise the ported mechanism: the fail-soft loader AND the real
integration point (`_collect_directive_targets` must exclude the fixture so it
is never moved to quarantine).
"""
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_fixture_loader_returns_protected_id():
    """The H2 fixture must be recognized as protected by lineage_pruner's
    own loader (parallel to directive_reconciler's)."""
    from tools.state_lifecycle.lineage_pruner import _load_fixture_directives

    fixtures = _load_fixture_directives()
    assert "90_PORT_H2_5M_RECYCLE_S01_V1_P00" in fixtures, (
        "lineage_pruner must consult tests/_fixtures/directives.yaml. If this "
        "fixture is not protected here, the next pipeline-state-cleanup sweep "
        "will quarantine the .txt and re-break the basket-dispatch suite."
    )


def test_collect_directive_targets_skips_protected_fixture(tmp_path):
    """Integration point: a protected fixture .txt with no keep_runs linkage
    must NOT appear in the quarantine targets, while an unprotected orphan
    with the same (absent) linkage must."""
    from tools.state_lifecycle.lineage_pruner import _collect_directive_targets

    protected = tmp_path / "90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt"
    protected.write_text("# fixture\n", encoding="utf-8")
    orphan = tmp_path / "99_PORT_UNPROTECTED_ORPHAN_V1_P00.txt"
    orphan.write_text("# orphan\n", encoding="utf-8")

    # keep_runs empty: neither file is backed by pipeline state. Only the
    # fixture-registry signal should spare the protected one.
    targets = _collect_directive_targets(tmp_path, keep_runs=set())
    stems = {p.stem for p in targets}

    assert "99_PORT_UNPROTECTED_ORPHAN_V1_P00" in stems, (
        "unprotected orphan should be a quarantine target"
    )
    assert "90_PORT_H2_5M_RECYCLE_S01_V1_P00" not in stems, (
        "protected fixture must be spared from quarantine"
    )


def test_fixture_registry_load_is_failsoft(tmp_path, monkeypatch):
    """A malformed YAML must yield an empty set (warn, don't crash) — a
    cleanup run must never be blocked by test-infra drift."""
    import tools.state_lifecycle.lineage_pruner as lp
    bogus = tmp_path / "bogus.yaml"
    bogus.write_text("{[ not yaml ]:", encoding="utf-8")
    monkeypatch.setattr(lp, "FIXTURE_REGISTRY_PATH", bogus)
    assert lp._load_fixture_directives() == frozenset()


def test_fixture_registry_missing_file_is_failsoft(tmp_path, monkeypatch):
    """An absent YAML must yield an empty set (the default)."""
    import tools.state_lifecycle.lineage_pruner as lp
    monkeypatch.setattr(lp, "FIXTURE_REGISTRY_PATH", tmp_path / "missing.yaml")
    assert lp._load_fixture_directives() == frozenset()
