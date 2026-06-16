"""Regression: engine-identity convergence within an execution path.

Charter task_edc22e4d (2026-06-15). Within ANY execution path, every emitted
``engine_version`` must equal the ACTUAL compute that ran, regardless of
``ENGINE_VERSION_OVERRIDE``. The two paths consolidate INDEPENDENTLY:

  * BASKET -- compute is hardcoded to ``engine_abi.v1_5_9`` (basket_runner.py;
    ``engine_abi/`` exposes only v1_5_9). Every basket stamp (manifest /
    input_provenance, run_metadata.json, STRATEGY_CARD.md, the
    cointegration_sheet row) must equal ``engine_abi.v1_5_9.ENGINE_VERSION`` and
    must NEVER consult ``get_engine_version()`` -- that helper honors the
    override, which is INERT for basket compute, so it would mislabel the run.

  * SINGLE-STRATEGY -- the engine is LEGITIMATELY selected by
    ``get_engine_version()`` (registry active_engine / override), which ALSO
    drives the dynamic compute import in ``run_engine_logic``. Selection and
    stamp are one source, so stamp == loaded compute by construction. The one
    failure mode -- a requested engine with no ``main.py`` -- must FAIL LOUD,
    never silently fall back to v1_5_6 under the requested label.

Doctrine: memory ``engine_identity_is_compute_not_stamp``.
"""
import importlib
import inspect
import json

import pytest

from engine_abi.v1_5_9 import ENGINE_VERSION as BASKET_COMPUTE_VERSION
from tools.pipeline_utils import get_engine_version


# ---------------------------------------------------------------------------
# BASKET PATH -- stamp MUST be the hardcoded compute, override-inert.
# ---------------------------------------------------------------------------

def test_basket_compute_version_is_override_inert(monkeypatch):
    """The basket compute identity is the hardcoded ABI version and does not move
    with the override that ``get_engine_version()`` honors."""
    import tools.run_pipeline as rp
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "1.5.10")
    # The override IS honored by the shared selector (the would-be liar)...
    assert get_engine_version() == "1.5.10"
    # ...but the basket compute identity is inert to it.
    assert rp._basket_compute_engine_version() == str(BASKET_COMPUTE_VERSION)
    assert rp._basket_compute_engine_version() != "1.5.10"


def test_basket_manifest_and_run_metadata_converge_on_compute(monkeypatch, tmp_path):
    """Acceptance criterion: run_metadata.engine_version == manifest
    engine_version == imported ABI ENGINE_VERSION, even under an override."""
    import tools.run_pipeline as rp
    from tools.basket_provenance import basket_input_provenance
    from tools.basket_report import _write_run_metadata
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "1.5.10")

    compute = rp._basket_compute_engine_version()

    # manifest source (input_provenance block folded into manifest.json)
    ip = basket_input_provenance({}, compute)
    assert ip["engine_version"] == compute == str(BASKET_COMPUTE_VERSION)

    # run_metadata.json source
    p = tmp_path / "run_metadata.json"
    _write_run_metadata(
        p, run_id="r", directive_id="d", basket_id="b",
        parsed_directive={}, engine_version=compute, leg_symbols=[],
    )
    rm = json.loads(p.read_text(encoding="utf-8"))
    assert rm["engine_version"] == compute == str(BASKET_COMPUTE_VERSION)


def test_basket_dispatch_sites_never_consult_get_engine_version():
    """Static guard against re-introducing the leak. The basket dispatch helpers
    must stamp via ``_basket_compute_engine_version()`` and never via
    ``get_engine_version()``. A future 'DRY-up' onto the override-honored
    selector (the original 2026-06-15 defect) fails here first."""
    import tools.run_pipeline as rp

    stamping_helpers = [
        rp._basket_write_tradelevel_and_report,  # input_provenance + run_metadata + card
        rp._basket_persist_run_record,           # cointegration_sheet row
    ]
    for fn in stamping_helpers:
        src = inspect.getsource(fn)
        assert "_basket_compute_engine_version(" in src, (
            f"{fn.__name__} must stamp engine_version via "
            "_basket_compute_engine_version()")
        assert "get_engine_version" not in src, (
            f"{fn.__name__} must NOT consult get_engine_version() for a basket "
            "stamp (override-honored -> mislabels the hardcoded v1_5_9 compute)")

    # The manifest writer reads engine_version off input_provenance (already the
    # compute); it must not independently consult the override-honored selector.
    assert "get_engine_version" not in inspect.getsource(
        rp._basket_finalize_state_machine)


# ---------------------------------------------------------------------------
# SINGLE-STRATEGY PATH -- stamp follows the ACTUAL loaded engine; mis-resolve
# must fail loud rather than silently mislabel.
# ---------------------------------------------------------------------------

def test_single_strategy_selected_engine_is_loadable_and_stamped(monkeypatch):
    """With no override, ``get_engine_version()`` names the engine that BOTH
    stamps the run (``_emit_build_metadata``) AND is dynamically imported by
    ``run_engine_logic`` -- so the stamp equals the loaded compute. Guard that
    the selected engine actually loads (selection == compute, no silent
    substitution)."""
    monkeypatch.delenv("ENGINE_VERSION_OVERRIDE", raising=False)
    ver = get_engine_version()
    mod = importlib.import_module(
        f"engine_dev.universal_research_engine.v{ver.replace('.', '_')}.main")
    assert hasattr(mod, "run_engine"), (
        f"engine v{ver} selected by get_engine_version() must expose run_engine")


def test_single_strategy_unresolvable_engine_fails_loud(monkeypatch):
    """A requested engine with no loadable main.py must ABORT, never silently run
    v1_5_6 while keeping the requested label. v1_5_10 ships no main.py today, so
    an override onto it is the canonical mis-resolve case."""
    from tools.run_stage1 import run_engine_logic
    monkeypatch.setenv("ENGINE_VERSION_OVERRIDE", "1.5.10")
    assert get_engine_version() == "1.5.10"
    with pytest.raises(RuntimeError, match="no loadable run-engine module"):
        run_engine_logic(None, None)
