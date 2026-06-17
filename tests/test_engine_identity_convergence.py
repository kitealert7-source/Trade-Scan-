"""Regression: engine-identity convergence within an execution path.

Charter task_edc22e4d (2026-06-15) + bulletproofing pass (2026-06-16). Within
ANY execution path, every emitted ``engine_version`` must equal the ACTUAL
compute that ran, regardless of ``ENGINE_VERSION_OVERRIDE``. The two paths
consolidate INDEPENDENTLY:

  * BASKET -- compute is hardcoded to ``engine_abi.v1_5_9`` via
    ``tools.basket_runner`` (the ONE module that imports the ABI). It re-exports
    ENGINE_VERSION + ENGINE_ABI as the SINGLE SOURCE; every basket stamp
    (manifest/input_provenance, run_metadata.json, STRATEGY_CARD.md, the
    cointegration_sheet row, the live heartbeat) derives from those symbols and
    NEVER from ``get_engine_version()`` (override-honored -> would mislabel) nor
    a second independent ``from engine_abi.v1_5_X`` (would drift on a bump).

  * SINGLE-STRATEGY -- the engine is LEGITIMATELY selected by
    ``get_engine_version()``, which ALSO drives the dynamic compute import in
    ``run_engine_logic`` -- AND that import is verified against the loaded
    module's own ENGINE_VERSION, so a folder whose name lies about its version
    (v1_5_3 ships the 1.5.4 engine) fails loud instead of mislabelling. A
    requested engine with no module / no run_engine / no emitter fails loud too.

Doctrine: memory ``engine_identity_is_compute_not_stamp``.
"""
import ast
import inspect
import json
import types
from pathlib import Path

import pytest

import tools.basket_runner as basket_runner
from engine_abi.v1_5_10 import ENGINE_VERSION as ABI_ENGINE_VERSION
from tools.pipeline_utils import get_engine_version
from config.engine_authority import (
    CANONICAL_ENGINE_ABI,
    CANONICAL_ENGINE_VERSION_DOTTED,
    CANONICAL_SINGLE_ASSET_ENGINE,
    CANONICAL_SINGLE_ASSET_VERSION_DOTTED,
    DRYRUN_CONTEXTVIEW_ENGINE,
    DRYRUN_CONTEXTVIEW_WAIVER,
    normalize_engine_token,
)
from config.engine_loader import get_active_engine


# ===========================================================================
# BASKET PATH -- single-source, override-inert, every surface on the compute.
# ===========================================================================

def test_basket_single_source_chain():
    """basket_runner is THE single source: its ENGINE_VERSION IS the ABI's, and
    the run_pipeline helpers derive from basket_runner (not a 2nd ABI import)."""
    import tools.run_pipeline as rp
    # basket_runner re-exports the exact ABI compute identity.
    assert basket_runner.ENGINE_VERSION == ABI_ENGINE_VERSION
    assert basket_runner.ENGINE_ABI == "engine_abi.v1_5_10"
    # Positive lock (Phase B): literal v1.5.10 so an accidental revert to v1_5_9 fails loud.
    assert str(basket_runner.ENGINE_VERSION) == "1.5.10"
    # The stamp helpers read basket_runner, not engine_abi directly.
    assert rp._basket_compute_engine_version() == str(basket_runner.ENGINE_VERSION)
    assert rp._basket_engine_abi() == str(basket_runner.ENGINE_ABI)
    helper_src = inspect.getsource(rp._basket_compute_engine_version)
    assert "from tools.basket_runner import ENGINE_VERSION" in helper_src, (
        "the basket stamp must derive from basket_runner (single source), not a "
        "second independent `from engine_abi.v1_5_X import` that could drift")


def test_basket_compute_version_is_override_inert(monkeypatch):
    """The basket compute identity does not move with the override that
    ``get_engine_version()`` honors."""
    import tools.run_pipeline as rp
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "9.9.9")
    assert get_engine_version() == "9.9.9"          # selector honors override...
    assert rp._basket_compute_engine_version() == str(ABI_ENGINE_VERSION)  # ...stamp does not
    assert rp._basket_compute_engine_version() != "9.9.9"  # (1.5.10 is now REAL basket compute)


def test_basket_all_four_writers_echo_compute(monkeypatch, tmp_path):
    """Value-level (alias/literal-proof) coverage of ALL FOUR basket stamp
    surfaces: under an override, each persisted artifact reads the compute."""
    import tools.run_pipeline as rp
    from tools.basket_provenance import basket_input_provenance
    from tools.basket_report import _write_run_metadata, write_basket_strategy_card
    import tools.portfolio.cointegration_provenance as cp

    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "9.9.9")
    compute = rp._basket_compute_engine_version()
    abi = rp._basket_engine_abi()
    assert compute == str(ABI_ENGINE_VERSION) != "9.9.9"

    # (1) manifest / input_provenance
    ip = basket_input_provenance({}, compute)
    assert ip["engine_version"] == compute

    # (2) run_metadata.json
    p = tmp_path / "run_metadata.json"
    _write_run_metadata(
        p, run_id="r", directive_id="d", basket_id="b",
        parsed_directive={}, engine_version=compute, leg_symbols=[],
    )
    assert json.loads(p.read_text(encoding="utf-8"))["engine_version"] == compute

    # (3) STRATEGY_CARD.md
    card = write_basket_strategy_card(
        tmp_path / "card", directive_id="d", run_id="r",
        parsed_directive={}, engine_version=compute,
    )
    card_text = card.read_text(encoding="utf-8")
    assert f"**Engine:** {compute}" in card_text and "9.9.9" not in card_text

    # (4) cointegration_sheet row (window-validity gate stubbed out)
    fake_wv = types.SimpleNamespace(
        span_start="2024-01-01", span_end="2024-06-01", continuous_span_obs=100,
        fragment_count=1, pct_cointegrated=0.9, regime_state="OK",
        ledger_window_status="VALID",
    )
    monkeypatch.setattr(cp, "evaluate_window_validity", lambda _p: fake_wv)
    legs = [{"symbol": "EURUSD", "lot": 0.01, "direction": "long"},
            {"symbol": "USDJPY", "lot": 0.01, "direction": "short"}]
    row = cp.build_cointegration_row(
        parsed={"basket": {"legs": legs}, "test": {}},
        directive_path=tmp_path / "directive.txt", run_id="r", directive_id="d",
        directive_hash="h", backtests_path="bt", vault_path="v", canonical={},
        trades_total=0, completed_at_utc="2026-06-16T00:00:00Z", stake_usd=1000.0,
        engine_version=compute, engine_abi=abi,
    )
    assert row["engine_version"] == compute
    assert row["engine_abi"] == abi == str(basket_runner.ENGINE_ABI)


def _basket_dispatch_functions():
    """All module-level functions in tools.run_pipeline whose name starts with
    `_basket_` -- the basket dispatch surface the AST guard scans."""
    import tools.run_pipeline as rp
    tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
    return [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("_basket_")]


def test_basket_dispatch_ast_guard_fail_closed():
    """Fail-CLOSED structural guard (replaces the old fail-open 2-function
    substring scan). Across EVERY ``_basket_*`` function in tools.run_pipeline:
      - no reference to ``get_engine_version`` (the override-honored selector);
      - every ``engine_version=`` kwarg / dict-entry value is a call to
        ``_basket_compute_engine_version()`` -- never a literal, alias, or other;
      - every ``engine_abi=`` kwarg / dict-entry value is a call to
        ``_basket_engine_abi()``.
    A NEW stamp helper, an aliased import, or a hardcoded literal all fail here."""
    KW_HELPER = {"engine_version": "_basket_compute_engine_version",
                 "engine_abi": "_basket_engine_abi"}
    violations = []
    for fn in _basket_dispatch_functions():
        for node in ast.walk(fn):
            # (a) no override-honored selector anywhere in the basket surface
            if isinstance(node, ast.Name) and node.id == "get_engine_version":
                violations.append(f"{fn.name}: references get_engine_version")
            if isinstance(node, ast.Attribute) and node.attr == "get_engine_version":
                violations.append(f"{fn.name}: references .get_engine_version")
            # (b) call kwargs: engine_version=/engine_abi= must be the helper call
            if isinstance(node, ast.keyword) and node.arg in KW_HELPER:
                want = KW_HELPER[node.arg]
                v = node.value
                if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                        and v.func.id == want):
                    violations.append(
                        f"{fn.name}: {node.arg}= must be {want}(), got {ast.dump(v)[:60]}")
            # (c) dict entries: "engine_version"/"engine_abi" keys likewise
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in KW_HELPER:
                        want = KW_HELPER[k.value]
                        if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                                and v.func.id == want):
                            violations.append(
                                f"{fn.name}: dict '{k.value}' must be {want}(), "
                                f"got {ast.dump(v)[:60]}")
    assert not violations, "basket engine-stamp guard violations:\n" + "\n".join(violations)


# ===========================================================================
# SINGLE-STRATEGY PATH -- stamp == the loaded module's OWN version; mis-resolve
# (missing, version-skewed, or no run_engine) fails loud.
# ===========================================================================

def test_single_strategy_selected_engine_is_loadable_and_consistent(monkeypatch):
    """No override: get_engine_version() names an engine whose module loads AND
    declares the SAME version (selection == stamp == compute, verified)."""
    import importlib
    monkeypatch.delenv("ENGINE_VERSION_OVERRIDE", raising=False)
    ver = get_engine_version()
    mod = importlib.import_module(
        f"engine_dev.universal_research_engine.v{ver.replace('.', '_')}.main")
    assert hasattr(mod, "run_engine")
    declared = getattr(mod, "ENGINE_VERSION", None) or getattr(mod, "__version__", None)
    assert str(declared) == str(ver), (
        f"active engine v{ver} module declares {declared!r} -- folder/version skew")


def test_single_strategy_unresolvable_engine_fails_loud(monkeypatch):
    """A requested engine with no loadable main.py ABORTS (no silent v1_5_6)."""
    from tools.run_stage1 import run_engine_logic
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "9.9.9")   # v9_9_9 does not exist (1.5.10 is now a real, loadable engine)
    assert get_engine_version() == "9.9.9"
    with pytest.raises(RuntimeError, match="no loadable run-engine module"):
        run_engine_logic(None, None)


def test_single_strategy_folder_version_skew_fails_loud(monkeypatch):
    """A folder whose module declares a DIFFERENT version than its name must
    abort rather than stamp the folder name onto the other engine's compute.
    v1_5_3/main.py ships ENGINE_VERSION='1.5.4' -- the live skew case."""
    from tools.run_stage1 import run_engine_logic
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "1.5.3")
    assert get_engine_version() == "1.5.3"
    with pytest.raises(RuntimeError, match="disagrees with the engine's own identity"):
        run_engine_logic(None, None)


# ===========================================================================
# LIVE BASKET PRODUCER -- the heartbeat records the compute engine.
# ===========================================================================

def test_live_heartbeat_carries_compute_engine(tmp_path):
    """The bridge faithfully records engine_version, and the producer (driver)
    wires it from the basket single-source."""
    import tools.live_basket.bridge as bridge
    import tools.live_basket.driver as driver
    rec = bridge.write_heartbeat(
        tmp_path, "basketX", "2026-06-16T00:00:00Z",
        engine_version=str(basket_runner.ENGINE_VERSION),
    )
    assert rec["engine_version"] == str(basket_runner.ENGINE_VERSION)
    assert bridge.read_heartbeat(tmp_path)["engine_version"] == str(basket_runner.ENGINE_VERSION)
    # Producer wiring: the StreamingBasketRunner heartbeat call stamps the engine
    # from the basket single-source. Assert the wiring is present in the module
    # (both the single-source import and the engine_version= on a heartbeat call).
    drv_src = inspect.getsource(driver)
    assert "from tools.basket_runner import ENGINE_VERSION" in drv_src
    assert "write_heartbeat" in drv_src and "engine_version=" in drv_src
    drv_tree = ast.parse(drv_src)
    heartbeat_calls = [
        n for n in ast.walk(drv_tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "write_heartbeat"
    ]
    assert heartbeat_calls, "driver must write a heartbeat"
    assert all(any(k.arg == "engine_version" for k in c.keywords) for c in heartbeat_calls), (
        "every driver write_heartbeat call must stamp engine_version (the compute)")


# ===========================================================================
# WRITER CONTRACTS -- a basket engine stamp can never be omitted/NULL.
# ===========================================================================

def test_cointegration_writer_requires_engine_version():
    """engine_version is a REQUIRED corpus field (NULL -> fatal write reject) AND
    a required build_cointegration_row arg (omission -> loud TypeError, not a
    silent NULL). engine_abi keeps a fallback default but the production caller
    single-sources it (locked by the AST guard, not by being a required param)."""
    from tools.portfolio.cointegration_ledger_writer import REQUIRED_FIELDS
    from tools.portfolio.cointegration_provenance import build_cointegration_row
    assert "engine_version" in REQUIRED_FIELDS
    params = inspect.signature(build_cointegration_row).parameters
    assert params["engine_version"].default is inspect.Parameter.empty


# ===========================================================================
# UNIFIED ENGINE AUTHORITY (Phase A) -- every selection surface names the ONE
# config.engine_authority, and that name resolves to the REAL compute. Doctrine:
# compute-binding by VERIFICATION, not dispatch (UNIFIED_ENGINE_AUTHORITY_PLAN.md;
# config.engine_authority imports NO engine).
# ===========================================================================

def test_selection_surfaces_converge_on_authority(monkeypatch):
    """Assertions a-g: every engine-selection surface == the single authority,
    and the authority name resolves to the real imported module's own
    ENGINE_VERSION (compute-bound, not just a string)."""
    import importlib
    import re
    monkeypatch.delenv("ENGINE_VERSION_OVERRIDE", raising=False)
    repo_root = Path(basket_runner.__file__).resolve().parent.parent

    # (a) basket ENGINE_ABI is the authority constant (value-level).
    assert basket_runner.ENGINE_ABI == CANONICAL_ENGINE_ABI

    # (b) the basket_runner:38 STATIC import target == the authority (AST-level:
    #     the literal the doctrine fixes, proven without importing).
    tree = ast.parse(Path(basket_runner.__file__).read_text(encoding="utf-8"))
    abi_imports = [
        n.module for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("engine_abi.")
    ]
    assert abi_imports == [CANONICAL_ENGINE_ABI], (
        f"basket_runner static engine_abi import {abi_imports} must be exactly "
        f"[{CANONICAL_ENGINE_ABI!r}] (the authority)")

    # (c) single-asset selectors (no override) both resolve to the authority, in
    #     their respective conventions, via the one normalizer.
    assert get_active_engine() == CANONICAL_SINGLE_ASSET_ENGINE
    assert get_active_engine() == normalize_engine_token(CANONICAL_SINGLE_ASSET_ENGINE, "underscore")
    assert get_engine_version() == CANONICAL_SINGLE_ASSET_VERSION_DOTTED

    # (d) the registry's active_engine == the authority single-asset engine.
    reg = json.loads((repo_root / "config" / "engine_registry.json").read_text(encoding="utf-8"))
    assert normalize_engine_token(reg["active_engine"], "underscore") == CANONICAL_SINGLE_ASSET_ENGINE

    # (e) [graft] version cross-check -- the authority NAME resolves to the REAL
    #     imported module's ENGINE_VERSION. THIS makes the authority compute-bound.
    abi_mod = importlib.import_module(CANONICAL_ENGINE_ABI)
    assert abi_mod.ENGINE_VERSION == str(basket_runner.ENGINE_VERSION) == CANONICAL_ENGINE_VERSION_DOTTED
    sa_mod = importlib.import_module(
        f"engine_dev.universal_research_engine.{CANONICAL_SINGLE_ASSET_ENGINE}.main")
    sa_declared = getattr(sa_mod, "ENGINE_VERSION", None) or getattr(sa_mod, "__version__", None)
    assert str(sa_declared) == CANONICAL_SINGLE_ASSET_VERSION_DOTTED

    # (f) [graft] symbol superset -- the canonical ABI exports >= the 8 symbols the
    #     basket statically imports, so a future one-file flip can't break the
    #     import surface.
    BASKET_SYMBOLS = {
        "BarState", "ENGINE_VERSION", "EngineConfig", "StrategyProtocol",
        "apply_regime_model", "evaluate_bar", "finalize_force_close",
        "resolve_engine_config",
    }
    abi_all = set(getattr(abi_mod, "__all__", []) or dir(abi_mod))
    assert BASKET_SYMBOLS <= abi_all, (
        f"{CANONICAL_ENGINE_ABI} missing basket symbols: {BASKET_SYMBOLS - abi_all}")

    # (g) [graft] dryrun waiver -- the dryrun ContextView surface is pinned to the
    #     authority's declared dryrun engine AND an explicit waiver is present (it
    #     is intentionally outside canonical-engine selection).
    assert DRYRUN_CONTEXTVIEW_WAIVER is True
    dv_src = (repo_root / "tools" / "strategy_dryrun_validator.py").read_text(encoding="utf-8")
    ctxview_modules = [
        n.module for n in ast.walk(ast.parse(dv_src))
        if isinstance(n, ast.ImportFrom) and any(a.name == "ContextView" for a in n.names)
    ]
    assert len(ctxview_modules) == 1, f"expected one ContextView import, got {ctxview_modules}"
    m = re.search(r"v\d+_\d+_\d+", ctxview_modules[0] or "")
    assert m and m.group(0) == DRYRUN_CONTEXTVIEW_ENGINE, (
        f"dryrun ContextView import {ctxview_modules[0]!r} drifted from the waived "
        f"engine {DRYRUN_CONTEXTVIEW_ENGINE!r}; update config.engine_authority if intentional")


def test_canonical_engines_declare_their_label_versions():
    """Anchor (graft 3): each canonical-set engine module declares the version its
    FOLDER LABEL claims, so retiring/relabelling can never silently stamp the
    wrong compute. Full compute byte-equivalence (v1.5.8==v1.5.9 output;
    v1.5.10==v1.5.9 @spread=0) is covered by tests/test_engine_abi_v1_5_9.py,
    tests/test_engine_abi_v1_5_10.py, and tests/test_basket_runner_phase2.py."""
    import importlib
    EXPECT = {"v1_5_8": "1.5.8", "v1_5_9": "1.5.9", "v1_5_10": "1.5.10"}
    for label, dotted in EXPECT.items():
        mod = importlib.import_module(f"engine_dev.universal_research_engine.{label}.main")
        declared = getattr(mod, "ENGINE_VERSION", None) or getattr(mod, "__version__", None)
        assert str(declared) == dotted, (
            f"engine folder {label} declares {declared!r}, expected {dotted!r} -- "
            "folder/label/version skew")
