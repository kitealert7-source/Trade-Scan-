"""
Regression tests for the verify_engine_integrity.py + engine_registry.json
governance bugfix (2026-05-03).

The pre-fix integrity tool hardcoded `_engine_main_path = .../v1_5_6/main.py`,
so the integrity check verified v1.5.6 even when the orchestrator was
running v1.5.8 / v1.5.8a. After the fix, the integrity tool reads the
engine version from the same `tools.pipeline_utils.get_engine_version()`
resolver path the pipeline orchestrator uses, which in turn reads
`config/engine_registry.json` `active_engine`.

The two assertions:
  1. Integrity tool's ENGINE_VERSION == engine_registry.json active_engine
     (i.e. it follows the resolver, not the hardcoded v1_5_6).
  2. End-to-end integrity self-test passes on the current repository state
     (active_engine = v1_5_8a, which is the Phase-2 clean engine).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_integrity_tool_uses_resolver_not_hardcoded_v156():
    """ENGINE_VERSION resolved by verify_engine_integrity.py MUST match
    the engine_registry.json active_engine, NOT the legacy v1.5.6 hardcode."""
    # Force a fresh import to pick up resolved ENGINE_VERSION
    import importlib
    import tools.verify_engine_integrity as vei
    importlib.reload(vei)

    registry = json.loads(
        (PROJECT_ROOT / "config" / "engine_registry.json").read_text(encoding="utf-8")
    )
    expected_version_dir = registry["active_engine"]              # e.g. "v1_5_8a"
    expected_version_str = expected_version_dir.lstrip("v").replace("_", ".")

    assert vei.ENGINE_VERSION == expected_version_str, (
        f"verify_engine_integrity.py ENGINE_VERSION={vei.ENGINE_VERSION!r} "
        f"does not match engine_registry.json active_engine version "
        f"({expected_version_str!r}). The integrity tool is not using the "
        f"resolver path."
    )

    expected_engine_root = (
        PROJECT_ROOT / "engine_dev" / "universal_research_engine" / expected_version_dir
    )
    assert vei.ENGINE_ROOT == expected_engine_root, (
        f"verify_engine_integrity.py ENGINE_ROOT={vei.ENGINE_ROOT} "
        f"does not match the resolver-selected engine directory "
        f"{expected_engine_root}."
    )


def test_integrity_tool_does_not_target_v1_5_6_anymore():
    """Explicit anti-regression: ENGINE_VERSION MUST NOT be 1.5.6 (the
    legacy hardcode value), unless the registry deliberately rolls back."""
    import importlib
    import tools.verify_engine_integrity as vei
    importlib.reload(vei)

    registry = json.loads(
        (PROJECT_ROOT / "config" / "engine_registry.json").read_text(encoding="utf-8")
    )
    if registry["active_engine"] == "v1_5_6":
        # If registry explicitly points at v1.5.6, ENGINE_VERSION should
        # follow — that's the resolver doing its job, not the legacy hardcode.
        # Skip the anti-regression in that case.
        import pytest
        pytest.skip("Registry intentionally on v1.5.6; resolver is correct.")
    assert vei.ENGINE_VERSION != "1.5.6", (
        f"ENGINE_VERSION resolved to '1.5.6' but engine_registry.json "
        f"active_engine = {registry['active_engine']!r}. The hardcoded "
        f"v1.5.6 lookup has crept back in. See governance bugfix "
        f"2026-05-03."
    )


def test_end_to_end_integrity_passes_on_current_repo_state():
    """Running tools/verify_engine_integrity.py against the current
    repository state MUST exit 0. With Phase 2 active_engine = v1_5_8a
    (which has clean canonical-LF manifest), the integrity check should
    pass without error."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "verify_engine_integrity.py")],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        # Surface full output for diagnostic
        msg = (
            f"\nverify_engine_integrity.py exited with code "
            f"{result.returncode}.\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}\n"
        )
        raise AssertionError(msg)


def test_registry_lineage_consistency():
    """Cross-layer consistency: engine_registry.json active_engine MUST
    match governance/engine_lineage.yaml's latest non-superseded FROZEN
    entry. Catches future drift between the two governance records."""
    import yaml
    registry = json.loads(
        (PROJECT_ROOT / "config" / "engine_registry.json").read_text(encoding="utf-8")
    )
    lineage = yaml.safe_load(
        (PROJECT_ROOT / "governance" / "engine_lineage.yaml").read_text(encoding="utf-8")
    )

    active = registry["active_engine"]
    lineage_entry = (lineage.get("engines") or {}).get(active)
    assert lineage_entry is not None, (
        f"engine_registry.json active_engine = {active!r} but "
        f"governance/engine_lineage.yaml has no entry for it."
    )
    assert lineage_entry.get("status") == "frozen", (
        f"engine_lineage.yaml entry for {active!r} status = "
        f"{lineage_entry.get('status')!r}; expected 'frozen'."
    )
    assert lineage_entry.get("vaulted") is True, (
        f"engine_lineage.yaml entry for {active!r} vaulted = "
        f"{lineage_entry.get('vaulted')!r}; expected True."
    )
    assert lineage_entry.get("superseded_by") is None, (
        f"engine_lineage.yaml entry for {active!r} marked "
        f"superseded_by={lineage_entry.get('superseded_by')!r}, "
        f"but registry still points at it. Lineage and registry "
        f"are out of sync."
    )
