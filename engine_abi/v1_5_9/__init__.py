"""engine_abi.v1_5_9 — new-consumer ABI surface for basket_runner + TS_SignalValidator.

Re-exports only. Each symbol below is `is`-identical to its source module's
binding. Modifying this package (adding/removing/aliasing exports) requires
editing `governance/engine_abi_v1_5_9_manifest.yaml` first and re-hashing via
`python tools/abi_audit.py --rehash --abi-version v1_5_9`.

Runtime guarantee (third CI gate):
  On import, `__all__` is compared against the manifest's `exports[*].name`.
  Mismatch -> RuntimeError at import time (FAIL-CLOSED).

Plan reference: H2_ENGINE_PROMOTION_PLAN.md Section 1l, Phase 0a Step 3-4.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from engine_dev.universal_research_engine.v1_5_9.evaluate_bar import (
    BarState,
    ContextView,
    ENGINE_ATR_MULTIPLIER,
    EngineConfig,
    evaluate_bar,
    finalize_force_close,
    resolve_engine_config,
    resolve_exit,
)
from engine_dev.universal_research_engine.v1_5_9.execution_loop import (
    ENGINE_STATUS,
    ENGINE_VERSION,
    run_execution_loop,
)
from engines.concurrency_gate import admit, validate_cap
from engines.regime_state_machine import apply_regime_model, REGIME_CACHE_DIR
from engines.protocols import StrategyProtocol

__all__ = [
    "evaluate_bar",
    "ContextView",
    "BarState",
    "EngineConfig",
    "resolve_engine_config",
    "resolve_exit",
    "finalize_force_close",
    "ENGINE_ATR_MULTIPLIER",
    "run_execution_loop",
    "ENGINE_VERSION",
    "ENGINE_STATUS",
    "apply_regime_model",
    "StrategyProtocol",
    "admit",
    "validate_cap",
    "REGIME_CACHE_DIR",
]

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "governance"
    / "engine_abi_v1_5_9_manifest.yaml"
)


def _verify_against_manifest() -> None:
    if not _MANIFEST_PATH.is_file():
        raise RuntimeError(
            f"engine_abi.v1_5_9: manifest not found at {_MANIFEST_PATH}. "
            "Run `python tools/abi_audit.py --rehash --abi-version v1_5_9`."
        )
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    declared = [e["name"] for e in manifest.get("exports", [])]
    if declared != list(__all__):
        raise RuntimeError(
            "engine_abi.v1_5_9 ABI manifest drift detected (FAIL-CLOSED).\n"
            f"  manifest exports: {declared}\n"
            f"  package __all__:  {list(__all__)}\n"
            "Fix: edit governance/engine_abi_v1_5_9_manifest.yaml and "
            "`python tools/abi_audit.py --rehash --abi-version v1_5_9`."
        )


_verify_against_manifest()
