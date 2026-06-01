"""Recycle-rule code-hash admission gate.

Pins each rule_name@version to the canonical sha256 of its module file
(governance/recycle_rules/rule_code_hashes.yaml) and makes namespace_gate
reject a basket directive whose rule code drifted from its registered version
— turning the registry's append-only "version is part of the basket strategy
hash" guarantee from convention into a mechanical check.

The match test is also the regression guard: if a rule's code is edited
without re-running generate_recycle_rule_hashes.py (and without a version
bump), test_pinned_hashes_match_current_code fails in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import basket_provenance  # noqa: E402
from tools.basket_provenance import (  # noqa: E402
    load_recycle_rule_hashes,
    recycle_rule_code_sha256,
)
from tools.namespace_gate import _validate_recycle_rule_code_hash  # noqa: E402
from tools.recycle_rules import RULE_CLASSES  # noqa: E402

REGISTRY = REPO_ROOT / "governance" / "recycle_rules" / "registry.yaml"


def _parsed(name: str, version: int = 1) -> dict:
    return {"basket": {"recycle_rule": {"name": name, "version": version}}}


# ── Sidecar coverage + integrity ───────────────────────────────────────────


def test_sidecar_covers_all_registry_rules():
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    reg_keys = {f"{r['name']}@{r['version']}" for r in reg["rules"]}
    pinned = set(load_recycle_rule_hashes())
    assert pinned == reg_keys, (
        "rule_code_hashes.yaml must pin exactly the registry rules. "
        f"registry-only={reg_keys - pinned} sidecar-only={pinned - reg_keys}. "
        "Run `python tools/generate_recycle_rule_hashes.py`."
    )


def test_pinned_hashes_match_current_code():
    """Regression guard: a rule edited without a rehash (+ version bump) fails
    here. If this fails, either bump the rule version or rehash intentionally."""
    pinned = load_recycle_rule_hashes()
    for name, version in RULE_CLASSES:
        key = f"{name}@{version}"
        assert pinned.get(key) == recycle_rule_code_sha256(name, version), (
            f"{key} code drifted from its pinned hash. Bump the version "
            f"(append-only) or rehash via generate_recycle_rule_hashes.py."
        )


# ── Gate behaviour ─────────────────────────────────────────────────────────


def test_gate_passes_on_clean_directive():
    assert _validate_recycle_rule_code_hash(_parsed("H2_recycle", 1)) == []


def test_gate_rejects_drift(monkeypatch):
    monkeypatch.setattr(
        basket_provenance, "load_recycle_rule_hashes",
        lambda *a, **k: {"H2_recycle@1": "0" * 64},
    )
    errors = _validate_recycle_rule_code_hash(_parsed("H2_recycle", 1))
    assert errors and "code hash" in errors[0]


def test_gate_soft_skips_when_sidecar_absent(monkeypatch):
    monkeypatch.setattr(
        basket_provenance, "load_recycle_rule_hashes", lambda *a, **k: {}
    )
    assert _validate_recycle_rule_code_hash(_parsed("H2_recycle", 1)) == []


def test_gate_rejects_unregistered_rule(monkeypatch):
    monkeypatch.setattr(
        basket_provenance, "load_recycle_rule_hashes",
        lambda *a, **k: {"SomeOtherRule@1": "a" * 64},
    )
    errors = _validate_recycle_rule_code_hash(_parsed("H2_recycle", 1))
    assert errors and "no pinned code hash" in errors[0]


def test_gate_ignores_non_basket_directive():
    # No basket block -> nothing to check.
    assert _validate_recycle_rule_code_hash({"some": "directive"}) == []
