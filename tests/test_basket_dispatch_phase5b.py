"""Phase 5b — basket dispatch negative-path guards in run_pipeline.py.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.

For RECYCLE basket directives, _try_basket_dispatch() short-circuits BEFORE
BootstrapController + StageRunner fire and runs the basket pipeline.

Scope of THIS file (trimmed 2026-06-05): the cheap negative-path guards only —
  - _try_basket_dispatch returns False for a regular per-symbol directive
  - _try_basket_dispatch returns False under provision_only

The expensive positive-path dispatch assertions (returns True, emits the
basket_sheet row, writes the vault) were consolidated into
test_basket_dispatch_e2e.py, which dispatches ONCE and asserts each
post-condition separately instead of re-dispatching per assertion (audit
2026-06-05: removed duplicated setup, not coverage).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---- helpers --------------------------------------------------------------


def _stage_directive_in_active_backup(monkeypatch, directive_id: str) -> Path:
    """Copy the canonical (tracked) directive from completed/ into a temp
    active_backup/ that the dispatch can find."""
    src = REPO_ROOT / "backtest_directives" / "completed" / f"{directive_id}.txt"
    assert src.is_file(), f"canonical directive missing at {src}"
    # Patch ACTIVE_BACKUP_DIR + COMPLETED_DIR module constants to point at
    # tmp dirs so we don't touch real state.
    import tools.run_pipeline as rp
    tmp_active = REPO_ROOT / "tmp" / "phase5b_active_backup"
    tmp_completed = REPO_ROOT / "tmp" / "phase5b_completed"
    if tmp_active.exists():
        shutil.rmtree(tmp_active)
    if tmp_completed.exists():
        shutil.rmtree(tmp_completed)
    tmp_active.mkdir(parents=True, exist_ok=True)
    tmp_completed.mkdir(parents=True, exist_ok=True)
    staged = tmp_active / src.name
    shutil.copy2(src, staged)
    monkeypatch.setattr(rp, "ACTIVE_BACKUP_DIR", tmp_active)
    monkeypatch.setattr(rp, "COMPLETED_DIR", tmp_completed)
    return staged


# ---- tests ----------------------------------------------------------------


def test_basket_dispatch_returns_false_for_per_symbol_directive(monkeypatch):
    """A regular non-basket directive must NOT be dispatched via the
    basket path (returns False -> caller proceeds with per-symbol flow)."""
    from tools.run_pipeline import _try_basket_dispatch
    # Use an existing per-symbol directive from completed/
    candidates = list((REPO_ROOT / "backtest_directives" / "completed").glob(
        "22_CONT_FX_15M_RSIAVG_*.txt"
    ))
    if not candidates:
        pytest.skip("no per-symbol completed directive available for negative test")
    per_symbol = candidates[0]
    directive_id = per_symbol.stem

    # Stage it as if admitted
    import tools.run_pipeline as rp
    tmp_active = REPO_ROOT / "tmp" / "phase5b_active_backup_persym"
    if tmp_active.exists():
        shutil.rmtree(tmp_active)
    tmp_active.mkdir(parents=True, exist_ok=True)
    shutil.copy2(per_symbol, tmp_active / per_symbol.name)
    monkeypatch.setattr(rp, "ACTIVE_BACKUP_DIR", tmp_active)

    dispatched = _try_basket_dispatch(directive_id, provision_only=False)
    assert dispatched is False


def test_basket_dispatch_returns_false_for_provision_only(monkeypatch):
    """provision_only flow must skip basket dispatch entirely."""
    from tools.run_pipeline import _try_basket_dispatch
    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    _stage_directive_in_active_backup(monkeypatch, directive_id)

    dispatched = _try_basket_dispatch(directive_id, provision_only=True)
    assert dispatched is False
