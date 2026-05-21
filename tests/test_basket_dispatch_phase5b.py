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


def _purge_real_state_for_directive(staged_directive: Path, directive_id: str) -> dict:
    """Wipe state pollution from prior runs of the same fixture.

    `generate_run_id` is deterministic from the directive content, and
    PipelineStateManager uses the module-level RUNS_DIR (not the monkey-patched
    path_authority). A prior test run leaves runs/<id>/run_state.json in the
    real TradeScan_State; the terminal-state guard (added 2026-05-18) then
    blocks re-init on the next dispatch. Clean that up before dispatch so
    Path B can write its basket_sheet row.

    Returns a snapshot dict that _post_purge_with_snapshot() can use to
    repeat the same cleanup without re-reading the (possibly tmp-deleted)
    staged file.
    """
    from tools.pipeline_utils import generate_run_id
    from config.state_paths import RUNS_DIR
    from config.path_authority import TRADE_SCAN_STATE

    # Parse the fixture to learn its basket_id (same way the dispatcher does).
    import yaml
    parsed = yaml.safe_load(staged_directive.read_text(encoding="utf-8"))
    basket_id = parsed["basket"]["basket_id"]
    run_id, _ = generate_run_id(staged_directive, symbol=basket_id)

    snapshot = {
        "directive_id": directive_id,
        "run_id": run_id,
        "basket_id": basket_id,
        "run_dir": str(RUNS_DIR / run_id),
        "backtests_dir": str(TRADE_SCAN_STATE / "backtests" / f"{directive_id}_{basket_id}"),
    }
    _purge_paths(snapshot)
    return snapshot


def _purge_paths(snapshot: dict) -> None:
    """Idempotent cleanup using paths captured eagerly in _purge_real_state_for_directive."""
    run_dir = Path(snapshot["run_dir"])
    if run_dir.exists():
        shutil.rmtree(run_dir)
    backtests_dir = Path(snapshot["backtests_dir"])
    if backtests_dir.exists():
        shutil.rmtree(backtests_dir)
    from tools.system_registry import _load_registry, _save_registry_atomic
    reg = _load_registry()
    if snapshot["run_id"] in reg:
        reg.pop(snapshot["run_id"])
        _save_registry_atomic(reg)
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    create_tables(conn)
    conn.execute("DELETE FROM basket_sheet WHERE directive_id = ?", (snapshot["directive_id"],))
    conn.commit()
    conn.close()


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


def test_basket_dispatch_emits_basket_sheet_row(monkeypatch, tmp_path, request):
    """After dispatch, ledger.db.basket_sheet must contain one row with the
    Phase 5b.3 schema columns. (Phase 5b.3 retired the legacy
    research/basket_runs.csv writer; the sink is now ledger.db.)"""
    from tools.run_pipeline import _try_basket_dispatch
    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    staged = _stage_directive_in_active_backup(monkeypatch, directive_id)
    purge_snapshot = _purge_real_state_for_directive(staged, directive_id)
    # Also purge post-test — PipelineStateManager uses module-level RUNS_DIR
    # and writes a run_state.json to the real path during dispatch, even
    # under monkeypatch. Without this finalizer, every test run leaves a
    # RUN_INCOMPLETE entry in real RUNS_DIR. Use the snapshot so the
    # finalizer does not depend on `staged` (under pytest tmp_path, which
    # may already be cleaned by the time finalizers fire).
    request.addfinalizer(lambda: _purge_paths(purge_snapshot))

    fake_state = tmp_path / "TradeScan_State"
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", fake_state)

    _try_basket_dispatch(directive_id, provision_only=False)

    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    create_tables(conn)
    cur = conn.execute(
        "SELECT * FROM basket_sheet WHERE directive_id = ?", (directive_id,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    assert len(rows) == 1, f"expected 1 basket_sheet row for {directive_id}, got {len(rows)}"
    row = rows[0]
    assert row["directive_id"] == directive_id
    assert row["basket_id"] == "H2"
    assert row["execution_mode"] == "basket"
    assert row["rule_name"] == "H2_recycle"
    assert int(row["rule_version"]) == 1
    assert int(row["leg_count"]) == 2
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
