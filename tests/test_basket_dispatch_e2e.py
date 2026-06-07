"""Consolidated basket-dispatch end-to-end acceptance test.

Merges four formerly-separate ~18s dispatches of the SAME directive that each
re-paid the expensive `_try_basket_dispatch` setup just to assert one
post-condition:
  - test_basket_dispatch_phase5b.py : returns_true / basket_sheet_row / vault
  - test_basket_path_b_phase5b2.py  : produces_all_four_artifact_paths

This module dispatches ONCE via a module-scoped fixture and asserts each
post-condition in its own small test function, so failure localization is
preserved while the expensive dispatch runs a single time.

Untouched: the fast unit tests in those files (converter, leg_specs, writer
schema, ContinuousHoldStrategy, negative dispatch guards) and the real-data
PnL dispatch in test_basket_phase5c_real_data.py.

Audit 2026-06-05: this is CURRENT production behavior
(run_pipeline._try_basket_dispatch); the "phaseN" names were dev milestones,
not obsolescence. Cluster reduction = removing duplicated setup, not coverage.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DIRECTIVE_ID = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"


@pytest.fixture(scope="module")
def dispatched(tmp_path_factory):
    """Dispatch the canonical H2 basket directive ONCE into a fully isolated
    fake TradeScan_State; yield the artifact context for the assert functions.

    Isolation mirrors the (most thorough) former phase5b2 setup: rebind
    path_authority + state_paths + pipeline_utils RUNS_DIR + system_registry so
    every artifact lands in tmp and the state-machine layer agrees with the
    artifact-write layer (the post-2026-05-18 terminal-state guard would
    otherwise reject re-init in the broader suite). pytest.MonkeyPatch is used
    because the stdlib `monkeypatch` fixture is function-scoped.
    """
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("basket_e2e")
    fake_state = base / "TradeScan_State"
    fake_state.mkdir()

    import config.path_authority as pa
    import config.state_paths as sp
    import tools.pipeline_utils as pu
    import tools.system_registry as sr
    import tools.run_pipeline as rp

    mp.setattr(pa, "TRADE_SCAN_STATE", fake_state)
    mp.setattr(sp, "STATE_ROOT", fake_state)
    mp.setattr(sp, "RUNS_DIR", fake_state / "runs")
    mp.setattr(pu, "RUNS_DIR", fake_state / "runs")
    mp.setattr(sr, "REGISTRY_PATH", fake_state / "registry" / "run_registry.json")

    src = REPO_ROOT / "backtest_directives" / "completed" / f"{DIRECTIVE_ID}.txt"
    assert src.is_file(), f"canonical directive missing at {src}"
    tmp_active = base / "active_backup"
    tmp_active.mkdir()
    shutil.copy2(src, tmp_active / src.name)
    mp.setattr(rp, "ACTIVE_BACKUP_DIR", tmp_active)

    from config.path_authority import DRY_RUN_VAULT
    vault_parent = DRY_RUN_VAULT / "baskets" / DIRECTIVE_ID
    if vault_parent.exists():
        shutil.rmtree(vault_parent)

    from tools.run_pipeline import _try_basket_dispatch
    ok = _try_basket_dispatch(DIRECTIVE_ID, provision_only=False)

    # Resolve the basket-flavored run_id from the registry for the MPS assertion.
    run_id = None
    reg_path = fake_state / "registry" / "run_registry.json"
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        basket = {rid: e for rid, e in reg.items() if e.get("execution_mode") == "basket"}
        if basket:
            run_id = next(iter(basket))

    ctx = {
        "ok": ok,
        "fake_state": fake_state,
        "vault_parent": vault_parent,
        "vault_dir": vault_parent / "H2",
        "run_id": run_id,
    }
    yield ctx

    mp.undo()
    if vault_parent.exists():
        shutil.rmtree(vault_parent)


# ---- post-condition assertions (one dispatch, asserted many ways) -----------


def test_dispatch_returns_true(dispatched):
    assert dispatched["ok"] is True


def test_basket_vault_not_auto_written(dispatched):
    """db87f977 (2026-06-07) removed the DRY_RUN_VAULT/baskets/ auto-write;
    basket artifacts now live only in TradeScan_State/runs/. The fixture
    pre-cleans vault_parent, so this asserts the dispatch did NOT recreate
    the per-run vault dump — guarding the removal from a silent regression."""
    vault_parent = dispatched["vault_parent"]
    vault_dir = dispatched["vault_dir"]
    assert not vault_parent.exists(), (
        f"basket vault parent must NOT be auto-written; found {vault_parent}"
    )
    assert not vault_dir.is_dir(), (
        f"basket vault dir must NOT be auto-written; found {vault_dir}"
    )


def test_basket_sheet_row(dispatched):
    from tools.ledger_db import _connect, create_tables
    conn = _connect()
    create_tables(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM basket_sheet WHERE directive_id = ?", (DIRECTIVE_ID,))]
    conn.close()
    assert len(rows) == 1, f"expected 1 basket_sheet row, got {len(rows)}"
    row = rows[0]
    assert row["basket_id"] == "H2"
    assert row["execution_mode"] == "basket"
    assert row["rule_name"] == "H2_recycle"
    assert int(row["rule_version"]) == 1
    assert int(row["leg_count"]) == 2
    assert int(row["trades_total"]) >= 0
    assert int(row["recycle_event_count"]) >= 0


def test_registry_entry(dispatched):
    fake_state = dispatched["fake_state"]
    reg = json.loads((fake_state / "registry" / "run_registry.json").read_text(encoding="utf-8"))
    basket = {rid: e for rid, e in reg.items() if e.get("execution_mode") == "basket"}
    assert len(basket) == 1, f"expected 1 basket registry entry, got {len(basket)}"
    _, entry = next(iter(basket.items()))
    assert entry["directive_id"] == DIRECTIVE_ID
    assert entry["basket_id"] == "H2"
    assert entry["status"] == "BASKET_COMPLETE"
    assert entry["tier"] == "basket"


def test_backtests_tradelevel_csv(dispatched):
    fake_state = dispatched["fake_state"]
    bt_csv = fake_state / "backtests" / f"{DIRECTIVE_ID}_H2" / "raw" / "results_tradelevel.csv"
    assert bt_csv.is_file()
    df = pd.read_csv(bt_csv)
    assert df.shape[1] == 31
    assert df.shape[0] >= 2  # at least one trade per leg
    assert set(df["symbol"].unique()) == {"EURUSD", "USDJPY"}


def test_mps_baskets_row(dispatched):
    fake_state = dispatched["fake_state"]
    mps = fake_state / "strategies" / "Master_Portfolio_Sheet.xlsx"
    assert mps.is_file()
    df_b = pd.read_excel(mps, sheet_name="Baskets")
    assert (df_b["run_id"] == dispatched["run_id"]).any()


def test_legacy_csv_absent_and_report_suppressed(dispatched):
    fake_state = dispatched["fake_state"]
    assert not (fake_state / "research" / "basket_runs.csv").exists()
    directive_dir = fake_state / "backtests" / f"{DIRECTIVE_ID}_H2"
    assert not (directive_dir / f"REPORT_{DIRECTIVE_ID}.md").is_file(), (
        "legacy REPORT.md should be suppressed for basket runs"
    )


def test_raw_artifacts_present(dispatched):
    directive_dir = dispatched["fake_state"] / "backtests" / f"{DIRECTIVE_ID}_H2"
    for fname in ("results_standard.csv", "results_risk.csv", "results_yearwise.csv",
                  "results_basket.csv", "metrics_glossary.csv", "bar_geometry.json"):
        assert (directive_dir / "raw" / fname).is_file(), f"missing raw/{fname}"
    assert (directive_dir / "metadata" / "run_metadata.json").is_file()
    assert (directive_dir / "STRATEGY_CARD.md").is_file()
