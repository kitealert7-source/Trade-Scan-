"""Phase 0a Step 6 — TS_Execution boot smoke via engine_abi.v1_5_9.

We can't start the live MT5 broker connection from CI, so the boot test
exercises the import surface only:
  - Repos sys.path setup as main.py does it.
  - phase0_validation.assert_abi() resolves the configured abi_version
    against the wired engine_abi sub-package.
  - The exact import lines executed by main.py / pipeline.py /
    execution_adapter.py / strategy_loader.py / replay.py succeed and
    bind objects `is`-identical to their source modules.

If any of these regresses, TS_Execution would refuse to boot at run time.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 0a Step 6 acceptance gate
          (post-v11: TS_Execution migrated to v1_5_9, v1_5_3 retired).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TRADE_SCAN_ROOT = Path(__file__).resolve().parent.parent
_TS_EXECUTION_ROOT = _TRADE_SCAN_ROOT.parent / "TS_Execution"


@pytest.fixture(scope="module")
def ts_execution_on_path():
    """Mirror main.py's sys.path setup — Trade_Scan first, then TS_Execution/src.

    Yields the configured abi_version (validated by phase0_validation)."""
    if not _TS_EXECUTION_ROOT.is_dir():
        pytest.skip(f"TS_Execution sibling repo not present at {_TS_EXECUTION_ROOT}")
    added: list[str] = []
    for p in (str(_TRADE_SCAN_ROOT), str(_TS_EXECUTION_ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    try:
        yield
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def test_phase0_validation_against_portfolio(ts_execution_on_path):
    """portfolio.yaml's abi_version must match a real engine_abi sub-package."""
    from phase0_validation import assert_abi
    portfolio_path = _TS_EXECUTION_ROOT / "portfolio.yaml"
    assert portfolio_path.is_file(), f"missing {portfolio_path}"
    v = assert_abi(portfolio_path)
    assert v == "v1_5_9", (
        f"TS_Execution portfolio.yaml abi_version expected v1_5_9, got {v!r}."
    )


def test_execution_adapter_imports_compile(ts_execution_on_path):
    """execution_adapter.py imports admit + validate_cap via engine_abi.v1_5_9."""
    from engine_abi.v1_5_9 import admit, validate_cap
    from engines.concurrency_gate import admit as src_admit
    from engines.concurrency_gate import validate_cap as src_validate_cap
    assert admit is src_admit
    assert validate_cap is src_validate_cap


def test_main_imports_compile(ts_execution_on_path):
    """main.py imports ContextView + apply_regime_model via engine_abi.v1_5_9."""
    from engine_abi.v1_5_9 import ContextView, apply_regime_model
    from engine_dev.universal_research_engine.v1_5_9.evaluate_bar import (
        ContextView as src_ContextView,
    )
    from engines.regime_state_machine import apply_regime_model as src_arm
    assert ContextView is src_ContextView
    assert apply_regime_model is src_arm


def test_pipeline_imports_compile(ts_execution_on_path):
    """pipeline.py imports REGIME_CACHE_DIR via engine_abi.v1_5_9."""
    from engine_abi.v1_5_9 import REGIME_CACHE_DIR
    from engines.regime_state_machine import REGIME_CACHE_DIR as src_dir
    assert REGIME_CACHE_DIR is src_dir


def test_strategy_loader_imports_compile(ts_execution_on_path):
    """strategy_loader.py imports StrategyProtocol via engine_abi.v1_5_9."""
    from engine_abi.v1_5_9 import StrategyProtocol
    from engines.protocols import StrategyProtocol as src_protocol
    assert StrategyProtocol is src_protocol


def test_normalized_context_view_subclass_still_constructs(ts_execution_on_path):
    """main.py subclasses ContextView to NormalizedContextView. ABI re-export
    must remain a real class (not a function/wrapper), so subclassing works."""
    from engine_abi.v1_5_9 import ContextView

    class NormalizedContextView(ContextView):
        def get(self, key, default=None):
            return super().get(key.lower().strip(), default)

    # Construction with a dummy namespace works.
    from types import SimpleNamespace
    ncv = NormalizedContextView(SimpleNamespace())
    assert isinstance(ncv, ContextView)


def test_replay_harness_imports_compile(ts_execution_on_path):
    """harness/replay.py uses the same engine_abi.v1_5_9 surface as main.py.

    Validates that no legacy v1_5_3 import fallback exists in active code: a
    fallback would silently rebind types if v1_5_9 ever became unavailable,
    which the plan explicitly prohibits. Post-v11 there is only one ABI.
    Stale comments mentioning v1_5_3 are tolerated (history references);
    we only ban executable import statements via AST inspection.
    """
    import ast
    replay_py = _TS_EXECUTION_ROOT / "harness" / "replay.py"
    assert replay_py.is_file()
    text = replay_py.read_text(encoding="utf-8")
    assert "from engine_abi.v1_5_9 import ContextView, apply_regime_model" in text

    tree = ast.parse(text)
    bad_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("engine_abi.v1_5_3"):
                bad_imports.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("engine_abi.v1_5_3"):
                    bad_imports.append(f"import {alias.name}")
    assert not bad_imports, (
        f"replay.py still has active v1_5_3 imports {bad_imports}; "
        "that ABI was retired in plan v11."
    )
