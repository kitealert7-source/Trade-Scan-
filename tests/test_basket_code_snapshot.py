"""Per-run basket code snapshot — provenance parity with single-strategy runs.

A single-strategy run snapshots strategy.py into runs/<run_id>/strategy.py so
the run pins the exact code that executed. Basket runs import their leg
strategies + recycle rule live from tools/, so without a snapshot a past run is
not reproducible once that shared code changes. tools/basket_provenance.py
copies the executed source files into runs/<run_id>/basket_code/ write-once.

These tests also guard the (name,version)->class resolver: it must match
governance/recycle_rules/registry.yaml exactly so a new rule cannot be
registered without a resolver entry (which both the snapshot and the
admission-time hash gate depend on).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.basket_provenance import (  # noqa: E402
    BasketProvenanceError,
    snapshot_basket_code,
)
from tools.recycle_rules import RULE_CLASSES, rule_class_for  # noqa: E402
from tools.recycle_strategies import ContinuousHoldStrategy  # noqa: E402

REGISTRY = REPO_ROOT / "governance" / "recycle_rules" / "registry.yaml"


def _leg_strategies():
    # type(strat) is all the snapshot needs; bypass __init__ to avoid coupling
    # the test to ContinuousHoldStrategy's constructor signature.
    return {
        "EURUSD": object.__new__(ContinuousHoldStrategy),
        "USDJPY": object.__new__(ContinuousHoldStrategy),
    }


# ── Resolver sync ──────────────────────────────────────────────────────────


def test_resolver_matches_registry_exactly():
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    reg_keys = {(r["name"], int(r["version"])) for r in reg["rules"]}
    assert set(RULE_CLASSES.keys()) == reg_keys, (
        "RULE_CLASSES must match registry.yaml exactly. "
        f"registry-only={reg_keys - set(RULE_CLASSES)} "
        f"resolver-only={set(RULE_CLASSES) - reg_keys}"
    )


def test_rule_class_for_resolves_known_rule():
    cls = rule_class_for("H2_recycle", 1)
    assert cls.__name__ == "H2RecycleRule"


# ── Snapshot ───────────────────────────────────────────────────────────────


def test_snapshot_writes_rule_and_leg_source_plus_manifest(tmp_path):
    m = snapshot_basket_code(
        tmp_path, rule_name="H2_recycle", rule_version=1,
        leg_strategies=_leg_strategies(), project_root=REPO_ROOT,
    )
    snap = tmp_path / "basket_code"
    assert (snap / "recycle_rules" / "h2_recycle.py").is_file()
    assert (snap / "recycle_strategies.py").is_file()
    assert (snap / "code_manifest.json").is_file()

    assert m["rule"] == "H2_recycle@1"
    assert "recycle_rules/h2_recycle.py" in m["files"]
    assert "recycle_strategies.py" in m["files"]
    assert all(len(h) == 64 for h in m["files"].values())  # sha256 hex
    assert "ContinuousHoldStrategy" in m["leg_strategy_classes"]


def test_snapshot_is_write_once_noop_on_identical_code(tmp_path):
    first = snapshot_basket_code(
        tmp_path, rule_name="H2_recycle", rule_version=1,
        leg_strategies=_leg_strategies(), project_root=REPO_ROOT,
    )
    # Second call against the same code must NOT raise and must return the
    # prior manifest unchanged.
    second = snapshot_basket_code(
        tmp_path, rule_name="H2_recycle", rule_version=1,
        leg_strategies=_leg_strategies(), project_root=REPO_ROOT,
    )
    assert first["files"] == second["files"]


def test_snapshot_raises_on_drift(tmp_path):
    snapshot_basket_code(
        tmp_path, rule_name="H2_recycle", rule_version=1,
        leg_strategies=_leg_strategies(), project_root=REPO_ROOT,
    )
    # Simulate drift: the recorded snapshot no longer matches current code.
    manifest_path = tmp_path / "basket_code" / "code_manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["files"] = {k: "0" * 64 for k in data["files"]}
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BasketProvenanceError):
        snapshot_basket_code(
            tmp_path, rule_name="H2_recycle", rule_version=1,
            leg_strategies=_leg_strategies(), project_root=REPO_ROOT,
        )
