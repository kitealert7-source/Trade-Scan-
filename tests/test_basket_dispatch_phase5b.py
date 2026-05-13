"""Phase 5b acceptance test — basket dispatch wiring in run_pipeline.py.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.

Phase 5b deliberately threads basket dispatch INTO run_pipeline.py — for
RECYCLE basket directives, _try_basket_dispatch() short-circuits BEFORE
BootstrapController + StageRunner fire, calls run_basket_pipeline() with
PASSTHROUGH strategies + SYNTHETIC OHLC data, writes the basket vault,
and appends a basket row to TradeScan_State/research/basket_runs.csv.

Real EUR+JPY 5m data + USD_SYNTH feature wiring is Phase 5c — until
then this test validates the wiring shape only (no real PnL).

Scope of this test:
  - _try_basket_dispatch returns True for a RECYCLE basket directive
  - _try_basket_dispatch returns False for a regular per-symbol directive
  - It writes a research CSV row with the expected columns
  - It writes a basket vault directory with the expected layout
"""
from __future__ import annotations

import csv
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


def test_basket_dispatch_returns_true_for_recycle_directive(monkeypatch, tmp_path):
    """The H2 directive must be detected and dispatched via the basket path."""
    from tools.run_pipeline import _try_basket_dispatch
    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    _stage_directive_in_active_backup(monkeypatch, directive_id)

    # Redirect vault + CSV writes into tmp_path to avoid touching real state.
    monkeypatch.chdir(tmp_path)
    # Patch path_authority TRADE_SCAN_STATE so the CSV lands in tmp.
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path / "TradeScan_State")
    # Vault writes go to the real DRY_RUN_VAULT (resolved via path_authority
    # inside run_pipeline._try_basket_dispatch); the test cleans up after.

    dispatched = _try_basket_dispatch(directive_id, provision_only=False)
    assert dispatched is True

    # Cleanup: remove the real-vault write we just made (synthetic test data)
    from config.path_authority import DRY_RUN_VAULT
    vault_parent = DRY_RUN_VAULT / "baskets" / directive_id
    if vault_parent.exists():
        shutil.rmtree(vault_parent)


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


def test_basket_dispatch_emits_research_csv_row(monkeypatch, tmp_path):
    """After dispatch, basket_runs.csv must contain one row with the
    Phase 5b schema columns."""
    from tools.run_pipeline import _try_basket_dispatch
    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    _stage_directive_in_active_backup(monkeypatch, directive_id)

    fake_state = tmp_path / "TradeScan_State"
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", fake_state)

    _try_basket_dispatch(directive_id, provision_only=False)

    csv_path = fake_state / "research" / "basket_runs.csv"
    assert csv_path.is_file(), f"expected CSV at {csv_path}"
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    row = rows[0]
    assert row["directive_id"] == directive_id
    assert row["basket_id"] == "H2"
    assert row["execution_mode"] == "basket"
    assert row["rule_name"] == "H2_v7_compression"
    assert row["rule_version"] == "1"
    assert row["leg_count"] == "2"
    # Trade counts depend on data mode (synthetic vs real). The wiring
    # assertion is "the dispatcher produces a numeric trades_total" — the
    # exact value is covered by Phase 5c (test_basket_phase5c_real_data).
    assert int(row["trades_total"]) >= 0
    assert int(row["recycle_event_count"]) >= 0

    # Cleanup the real vault write (the function targets the sibling repo)
    from config.path_authority import DRY_RUN_VAULT
    vault_parent = DRY_RUN_VAULT / "baskets" / directive_id
    if vault_parent.exists():
        shutil.rmtree(vault_parent)


def test_basket_dispatch_writes_vault(monkeypatch, tmp_path):
    """The basket vault directory must exist after dispatch with the
    expected Phase 6 layout (basket.yaml + legs/ subdir)."""
    from tools.run_pipeline import _try_basket_dispatch
    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    _stage_directive_in_active_backup(monkeypatch, directive_id)

    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", tmp_path / "TradeScan_State")

    _try_basket_dispatch(directive_id, provision_only=False)

    # Vault layout: DRY_RUN_VAULT/baskets/<directive_id>/<basket_id>/
    from config.path_authority import DRY_RUN_VAULT
    vault_parent = DRY_RUN_VAULT / "baskets" / directive_id
    vault_dir = vault_parent / "H2"
    try:
        assert vault_dir.is_dir(), f"expected vault at {vault_dir}"
        from tools.basket_vault import is_basket_vault
        assert is_basket_vault(vault_dir), "vault must be detected as basket"
        assert (vault_dir / "legs" / "EURUSD").is_dir()
        assert (vault_dir / "legs" / "USDJPY").is_dir()
    finally:
        if vault_parent.exists():
            shutil.rmtree(vault_parent)
