import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import tools.system_registry as sr
from tools.system_registry import _load_registry, _save_registry_atomic, reconcile_registry


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Point system_registry's module-level path globals at a disposable temp
    tree. reconcile_registry()/_load_registry()/_save_registry_atomic() read
    these names from their own module namespace at call time, so patching them
    here fully isolates the test from the real TradeScan_State registry + runs
    (the previous version of these tests created folders in, and mutated, the
    live registry)."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry_path = registry_dir / "run_registry.json"

    monkeypatch.setattr(sr, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(sr, "RUN_DIRS_IN_LOOKUP_ORDER", [runs_dir])
    monkeypatch.setattr(sr, "QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(sr, "STRATEGIES_DIR", tmp_path / "strategies")
    monkeypatch.setattr(sr, "SELECTED_DIR", tmp_path / "selected")
    monkeypatch.setattr(sr, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(sr, "LOCK_PATH", registry_path.with_suffix(".lock"))
    # No active portfolio in the isolated world, so reconcile's
    # portfolio-dependency consistency check (which would otherwise read the
    # real portfolio and hard-crash on runs absent from the temp tree, and the
    # auto-clean pass that rewrites real portfolio_metadata.json) is a no-op.
    monkeypatch.setattr(sr, "get_active_portfolio_runs", lambda: [])
    return runs_dir


def test_orphan_run(isolated_registry):
    """A physical run folder (with data/) absent from the registry is
    auto-recovered by reconcile as a sandbox-tier entry."""
    runs_dir = isolated_registry
    orphan_id = "orphan123456"
    (runs_dir / orphan_id / "data").mkdir(parents=True)

    reconcile_registry()

    registry = _load_registry()
    assert orphan_id in registry, "orphaned physical run was not injected into registry"
    assert registry[orphan_id]["tier"] == "sandbox", (
        f"orphan should be tiered sandbox, got {registry[orphan_id].get('tier')!r}"
    )


def test_ghost_registry(isolated_registry):
    """A registry entry whose physical folder is absent is marked invalid
    (a terminal tombstone), not silently dropped."""
    ghost_id = "ghost654321"
    _save_registry_atomic({
        ghost_id: {
            "run_id": ghost_id,
            "tier": "sandbox",
            "status": "complete",
            "created_at": "2026-01-01T00:00:00Z",
            "directive_hash": "ghost_test",
            "artifact_hash": "deadbeef",
        }
    })

    reconcile_registry()

    registry = _load_registry()
    assert ghost_id in registry, "ghost entry should be preserved as a tombstone"
    assert registry[ghost_id]["status"] == "invalid", (
        f"ghost entry should be marked invalid, got {registry[ghost_id].get('status')!r}"
    )
