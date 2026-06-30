"""Engine resolver = canonical VALIDATOR, not a selector.

Consolidation 2026-06-30 (ENGINE_CONSOLIDATION_PLAN_2026-06-29.md, Phase 3)
inverted tools/engine_resolver.resolve_engine from capability-driven SELECTION
(enumerate engine dirs, filter, min-semver tie-break) to single-engine
VALIDATION (is the ONE canonical engine valid for this run?). These tests lock
that contract so runtime engine selection cannot silently creep back:

  * resolves to the canonical engine WITHOUT enumerating any directory;
  * a stale contract_id whitelist is ADVISORY (non-blocking) — the operator
    decision "Advisory whitelist" — surfaced via contract_whitelist_ok=False;
  * a capability miss is a hard F9 (canonical is the superset, so this only
    fires on a genuine fault);
  * the return shape preflight depends on (engine_version/engine_path/
    contract_id) is preserved.
"""
import logging
import pathlib

import pytest

from config.engine_authority import CANONICAL_SINGLE_ASSET_ENGINE
from tools.engine_resolver import (
    EngineResolverError,
    _load_canonical_manifest,
    resolve_engine,
)


@pytest.fixture
def canonical():
    m = _load_canonical_manifest()
    return {
        "version": m["engine_version"],
        "caps": list(m.get("capabilities") or []),
        "contract_id": m["contract_id"],
    }


def test_resolves_to_canonical(canonical):
    r = resolve_engine(canonical["caps"], [canonical["contract_id"]])
    assert r["engine_version"] == canonical["version"] == CANONICAL_SINGLE_ASSET_ENGINE
    assert r["contract_id"] == canonical["contract_id"]
    assert r["contract_whitelist_ok"] is True
    # Return shape preflight CHECK 6.8 / F11 depends on:
    assert set(r) >= {"engine_version", "engine_path", "contract_id"}
    assert CANONICAL_SINGLE_ASSET_ENGINE in r["engine_path"]


def test_no_runtime_enumeration(canonical, monkeypatch):
    """resolve_engine must NOT iterate engine_dev/ or vault/engines/. Make any
    directory enumeration explode; resolution must still succeed (it loads only
    the canonical manifest by name)."""
    def _boom(self):
        raise AssertionError("resolver enumerated a directory (selection leak)")

    monkeypatch.setattr(pathlib.Path, "iterdir", _boom)
    r = resolve_engine(canonical["caps"], [canonical["contract_id"]])
    assert r["engine_version"] == CANONICAL_SINGLE_ASSET_ENGINE


def test_stale_contract_whitelist_is_advisory(canonical, caplog):
    """A strategy declaring an OLD engine's contract_id (the live case for the
    pre-consolidation strategies) resolves to canonical, flags the staleness,
    logs a structured WARNING, and does NOT raise."""
    stale = "sha256:" + "0" * 64
    assert stale != canonical["contract_id"]
    with caplog.at_level(logging.WARNING, logger="tools.engine_resolver"):
        r = resolve_engine(canonical["caps"], [stale])
    assert r["engine_version"] == CANONICAL_SINGLE_ASSET_ENGINE  # not blocked
    assert r["contract_whitelist_ok"] is False
    assert any("STALE_CONTRACT_WHITELIST" in rec.message for rec in caplog.records)


def test_capability_miss_raises_f9(canonical):
    with pytest.raises(EngineResolverError) as ei:
        resolve_engine(["execution.NONEXISTENT_CAP.v1"], [canonical["contract_id"]])
    assert ei.value.code == "F9"


def test_empty_capabilities_resolve(canonical):
    """No required capabilities is trivially satisfied by the canonical engine."""
    r = resolve_engine([], [canonical["contract_id"]])
    assert r["engine_version"] == CANONICAL_SINGLE_ASSET_ENGINE
