"""Phase 0a Step 6 — engine_abi.v1_5_9 acceptance + bootstrap-consumer test.

This module is cited as the sole `consumed_by` for every entry in
`governance/engine_abi_v1_5_9_manifest.yaml` until Phase 2 (basket_runner)
and Phase 7a (TS_SignalValidator) land. Replacing entries here with real
production consumers happens via deliberate manifest-update commits, not
by deleting this file (the test stays as an identity guard).

Identity guarantee: every symbol exposed by engine_abi.v1_5_9 must be the
exact object exported by its source module. Since the ABI is a re-export
package, `is` (object identity) must hold. Any deviation is either a
silent shadowing bug or a real surface change that requires a manifest
update.

Adversarial tests for the triple-gate CI live separately in
test_engine_abi_adversarial.py.

Plan: H2_ENGINE_PROMOTION_PLAN.md Section 1l, Phase 0a Steps 4 + 6.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
import yaml

from engine_abi import v1_5_9 as abi

# Direct source-module imports — what the ABI re-exports must be `is`-identical to.
from engine_dev.universal_research_engine.v1_5_9 import evaluate_bar as _eb
from engine_dev.universal_research_engine.v1_5_9 import execution_loop as _el
from engines import concurrency_gate as _cg
from engines import regime_state_machine as _rsm
from engines import protocols as _proto


_REPO_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST_PATH = _REPO_ROOT / "governance" / "engine_abi_v1_5_9_manifest.yaml"


def _load_manifest():
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_manifest_loads():
    manifest = _load_manifest()
    assert manifest["abi_version"] == "v1_5_9"
    assert manifest["exports"], "manifest exports list is empty"


def test_package_all_matches_manifest():
    manifest = _load_manifest()
    declared = [e["name"] for e in manifest["exports"]]
    assert list(abi.__all__) == declared, (
        f"engine_abi.v1_5_9 __all__ does not match manifest.\n"
        f"  __all__:  {list(abi.__all__)}\n"
        f"  manifest: {declared}"
    )


def test_evaluate_bar_identity():
    assert abi.evaluate_bar is _eb.evaluate_bar


def test_context_view_identity():
    assert abi.ContextView is _eb.ContextView


def test_bar_state_identity():
    assert abi.BarState is _eb.BarState


def test_engine_config_identity():
    assert abi.EngineConfig is _eb.EngineConfig


def test_resolve_engine_config_identity():
    assert abi.resolve_engine_config is _eb.resolve_engine_config


def test_resolve_exit_identity():
    assert abi.resolve_exit is _eb.resolve_exit


def test_finalize_force_close_identity():
    assert abi.finalize_force_close is _eb.finalize_force_close


def test_engine_atr_multiplier_identity():
    assert abi.ENGINE_ATR_MULTIPLIER is _eb.ENGINE_ATR_MULTIPLIER


def test_run_execution_loop_identity():
    assert abi.run_execution_loop is _el.run_execution_loop


def test_engine_version_identity():
    assert abi.ENGINE_VERSION is _el.ENGINE_VERSION


def test_engine_status_identity():
    assert abi.ENGINE_STATUS is _el.ENGINE_STATUS


def test_apply_regime_model_identity():
    assert abi.apply_regime_model is _rsm.apply_regime_model


def test_strategy_protocol_identity():
    assert abi.StrategyProtocol is _proto.StrategyProtocol


def test_admit_identity():
    assert abi.admit is _cg.admit


def test_validate_cap_identity():
    assert abi.validate_cap is _cg.validate_cap


def test_regime_cache_dir_identity():
    assert abi.REGIME_CACHE_DIR is _rsm.REGIME_CACHE_DIR


def test_manifest_hash_is_stamped():
    manifest = _load_manifest()
    h = manifest.get("manifest_sha256", "")
    assert re.fullmatch(r"[0-9a-f]{64}", h), (
        f"manifest_sha256 not a hex64 — run "
        f"`python tools/abi_audit.py --rehash --abi-version v1_5_9` "
        f"(currently {h!r})"
    )


def test_import_is_idempotent():
    """The runtime assertion inside engine_abi.v1_5_9.__init__ must be a
    no-op on re-import. If it raises on the second load, something is
    leaking module-level state."""
    importlib.reload(abi)
