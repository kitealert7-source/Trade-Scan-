"""Tests for tools/basket_reset.py — basket directive reset tool.

Uses tmp_path fixtures and monkeypatch to isolate the tool from the real
TradeScan_State / DRY_RUN_VAULT / governance/ paths. Each test exercises
one purge concern in isolation, then a couple integration tests run
the full reset on a synthesized basket layout.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import basket_reset as br


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _basket_directive_yaml(directive_id: str, basket_id: str = "H2") -> str:
    """Minimal basket directive YAML."""
    return yaml.safe_dump({
        "test": {
            "name": directive_id,
            "family": "PORT",
            "strategy": directive_id,
        },
        "basket": {
            "basket_id": basket_id,
            "legs": [
                {"symbol": "EURUSD", "lot": 0.01, "direction": "long"},
                {"symbol": "USDJPY", "lot": 0.01, "direction": "long"},
            ],
        },
    })


def _normal_strategy_yaml(directive_id: str) -> str:
    """Non-basket directive (no basket: section)."""
    return yaml.safe_dump({
        "test": {
            "name": directive_id,
            "family": "MR",
            "strategy": directive_id,
        },
        "symbols": ["EURUSD"],
    })


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect all paths used by basket_reset to tmp_path."""
    project_root = tmp_path / "Trade_Scan"
    state_root = tmp_path / "TradeScan_State"
    vault_root = tmp_path / "DRY_RUN_VAULT"

    # Build the directory tree
    (project_root / "backtest_directives" / "INBOX").mkdir(parents=True)
    (project_root / "backtest_directives" / "active").mkdir(parents=True)
    (project_root / "backtest_directives" / "active_backup").mkdir(parents=True)
    (project_root / "backtest_directives" / "completed").mkdir(parents=True)
    (project_root / "governance").mkdir(parents=True)
    (state_root / "registry").mkdir(parents=True)
    (state_root / "backtests").mkdir(parents=True)
    (state_root / "runs").mkdir(parents=True)
    (state_root / "strategies").mkdir(parents=True)
    (state_root / "research").mkdir(parents=True)
    (vault_root / "baskets").mkdir(parents=True)

    # Patch path constants in the module
    monkeypatch.setattr(br, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(br, "TRADE_SCAN_STATE", state_root)
    monkeypatch.setattr(br, "DRY_RUN_VAULT", vault_root)
    monkeypatch.setattr(br, "REGISTRY_PATH", state_root / "registry" / "run_registry.json")
    monkeypatch.setattr(br, "BACKTESTS_DIR", state_root / "backtests")
    monkeypatch.setattr(br, "VAULT_BASKETS_DIR", vault_root / "baskets")
    monkeypatch.setattr(br, "RUNS_DIR", state_root / "runs")
    monkeypatch.setattr(br, "MPS_PATH", state_root / "strategies" / "Master_Portfolio_Sheet.xlsx")
    monkeypatch.setattr(br, "BASKET_RUNS_CSV", state_root / "research" / "basket_runs.csv")
    monkeypatch.setattr(br, "AUDIT_LOG", project_root / "governance" / "reset_audit_log.csv")
    monkeypatch.setattr(br, "DIRECTIVE_SEARCH_DIRS", [
        project_root / "backtest_directives" / "INBOX",
        project_root / "backtest_directives" / "active",
        project_root / "backtest_directives" / "active_backup",
        project_root / "backtest_directives" / "completed",
    ])
    monkeypatch.setattr(br, "INBOX_DIR", project_root / "backtest_directives" / "INBOX")

    return {
        "project_root": project_root,
        "state_root": state_root,
        "vault_root": vault_root,
    }


def _seed_basket(paths, directive_id="TEST_BASKET_S01_V1_P00", basket_id="H2",
                 run_id="abc12345deadbeef00000001"):
    """Create a fully-populated basket layout for `directive_id`."""
    pr = paths["project_root"]
    sr = paths["state_root"]
    vr = paths["vault_root"]

    # Directive file in completed/
    (pr / "backtest_directives" / "completed" / f"{directive_id}.txt").write_text(
        _basket_directive_yaml(directive_id, basket_id), encoding="utf-8"
    )

    # Registry entry
    reg_path = sr / "registry" / "run_registry.json"
    reg_path.write_text(json.dumps({
        run_id: {
            "run_id": run_id,
            "directive_id": directive_id,
            "basket_id": basket_id,
            "execution_mode": "basket",
            "status": "BASKET_COMPLETE",
            "created_at": "2026-05-15T14:42:08+00:00",
        },
        # Unrelated entry that must NOT be purged
        "other_run_id_zzz": {
            "run_id": "other_run_id_zzz",
            "directive_id": "OTHER_DIRECTIVE_S01_V1_P00",
            "status": "complete",
        },
    }, indent=2), encoding="utf-8")

    # Backtest artifacts
    backtest_dir = sr / "backtests" / f"{directive_id}_{basket_id}"
    (backtest_dir / "raw").mkdir(parents=True)
    (backtest_dir / "raw" / "results_basket.csv").write_text("data,row\n1,2\n", encoding="utf-8")
    (backtest_dir / "metadata").mkdir()
    (backtest_dir / "metadata" / "run_metadata.json").write_text("{}", encoding="utf-8")

    # Vault artifacts
    vault_dir = vr / "baskets" / directive_id
    (vault_dir / basket_id).mkdir(parents=True)
    (vault_dir / basket_id / "recycle_events.jsonl").write_text(
        '{"event": "test"}\n', encoding="utf-8"
    )

    # Run dir
    (sr / "runs" / run_id).mkdir()
    (sr / "runs" / run_id / "manifest.json").write_text("{}", encoding="utf-8")

    # basket_runs.csv with two rows: target + other
    csv_path = sr / "research" / "basket_runs.csv"
    csv_path.write_text(
        f"directive_id,basket_id,result\n{directive_id},{basket_id},complete\n"
        f"OTHER_DIRECTIVE_S01_V1_P00,H3,complete\n",
        encoding="utf-8"
    )

    return {
        "directive_id": directive_id,
        "basket_id": basket_id,
        "run_id": run_id,
        "directive_path": pr / "backtest_directives" / "completed" / f"{directive_id}.txt",
        "backtest_dir": backtest_dir,
        "vault_dir": vault_dir,
        "run_dir": sr / "runs" / run_id,
    }


def _seed_mps(paths, directive_id="TEST_BASKET_S01_V1_P00"):
    """Create an MPS Baskets sheet with target + other row, plus another sheet."""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not available")
    mps_path = paths["state_root"] / "strategies" / "Master_Portfolio_Sheet.xlsx"
    df_baskets = pd.DataFrame([
        {"directive_id": directive_id, "basket_id": "H2", "metric": "target"},
        {"directive_id": "OTHER_DIRECTIVE_S01_V1_P00", "basket_id": "H3", "metric": "preserve"},
    ])
    df_portfolios = pd.DataFrame([
        {"portfolio_id": "P01", "asset": "EURUSD"},
    ])
    with pd.ExcelWriter(mps_path, engine="openpyxl") as writer:
        df_baskets.to_excel(writer, sheet_name="Baskets", index=False)
        df_portfolios.to_excel(writer, sheet_name="Portfolios", index=False)
    return mps_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basket_directive_validation_rejects_normal_strategy(isolated_paths):
    """Non-basket directive should error with explicit message."""
    pr = isolated_paths["project_root"]
    directive_id = "01_MR_FX_1H_TEST_S01_V1_P00"
    (pr / "backtest_directives" / "completed" / f"{directive_id}.txt").write_text(
        _normal_strategy_yaml(directive_id), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not a basket directive"):
        br.basket_reset(directive_id, "test reason")


def test_directive_file_missing_raises(isolated_paths):
    with pytest.raises(FileNotFoundError, match="not found in any lifecycle folder"):
        br.basket_reset("NONEXISTENT_S01_V1_P00", "test reason")


def test_purges_registry_entries(isolated_paths):
    """Registry entries for the target directive are purged; others preserved."""
    seed = _seed_basket(isolated_paths)
    result = br.basket_reset(seed["directive_id"], "test")
    assert seed["run_id"] in result["purged_run_ids"]
    # Verify the registry no longer has the target entry but still has the unrelated one
    reg = json.loads(br.REGISTRY_PATH.read_text(encoding="utf-8"))
    assert seed["run_id"] not in reg
    assert "other_run_id_zzz" in reg


def test_purges_backtest_dir(isolated_paths):
    seed = _seed_basket(isolated_paths)
    assert seed["backtest_dir"].exists()
    br.basket_reset(seed["directive_id"], "test")
    assert not seed["backtest_dir"].exists()


def test_purges_vault_dir(isolated_paths):
    seed = _seed_basket(isolated_paths)
    assert seed["vault_dir"].exists()
    br.basket_reset(seed["directive_id"], "test")
    assert not seed["vault_dir"].exists()


def test_purges_run_dirs(isolated_paths):
    seed = _seed_basket(isolated_paths)
    assert seed["run_dir"].exists()
    br.basket_reset(seed["directive_id"], "test")
    assert not seed["run_dir"].exists()


def test_purges_basket_runs_csv_row(isolated_paths):
    """Target row removed; unrelated row preserved."""
    seed = _seed_basket(isolated_paths)
    br.basket_reset(seed["directive_id"], "test")
    csv_path = isolated_paths["state_root"] / "research" / "basket_runs.csv"
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    directive_ids = [r["directive_id"] for r in rows]
    assert seed["directive_id"] not in directive_ids
    assert "OTHER_DIRECTIVE_S01_V1_P00" in directive_ids


def test_purges_mps_baskets_row(isolated_paths):
    """MPS Baskets row removed; other sheet preserved."""
    seed = _seed_basket(isolated_paths)
    _seed_mps(isolated_paths, directive_id=seed["directive_id"])
    br.basket_reset(seed["directive_id"], "test")
    import pandas as pd
    mps_path = br.MPS_PATH
    df_baskets = pd.read_excel(mps_path, sheet_name="Baskets")
    df_portfolios = pd.read_excel(mps_path, sheet_name="Portfolios")
    assert seed["directive_id"] not in df_baskets["directive_id"].tolist()
    assert "OTHER_DIRECTIVE_S01_V1_P00" in df_baskets["directive_id"].tolist()
    # Other sheet should be untouched
    assert "P01" in df_portfolios["portfolio_id"].tolist()


def test_restores_directive_to_inbox(isolated_paths):
    """Directive .txt moved from completed/ to INBOX/."""
    seed = _seed_basket(isolated_paths)
    pr = isolated_paths["project_root"]
    assert seed["directive_path"].exists()
    br.basket_reset(seed["directive_id"], "test")
    assert not seed["directive_path"].exists()
    assert (pr / "backtest_directives" / "INBOX" / f"{seed['directive_id']}.txt").exists()


def test_removes_stale_admitted_marker(isolated_paths):
    """Any .admitted marker for the directive is removed across all lifecycle dirs."""
    seed = _seed_basket(isolated_paths)
    pr = isolated_paths["project_root"]
    marker = pr / "backtest_directives" / "completed" / f"{seed['directive_id']}.txt.admitted"
    marker.write_text("", encoding="utf-8")
    assert marker.exists()
    br.basket_reset(seed["directive_id"], "test")
    assert not marker.exists()


def test_audit_log_entry(isolated_paths):
    """An audit log entry is written with required columns."""
    seed = _seed_basket(isolated_paths)
    br.basket_reset(seed["directive_id"], "phase-A recalibration test")
    audit_path = br.AUDIT_LOG
    assert audit_path.exists()
    rows = list(csv.DictReader(audit_path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    row = rows[0]
    assert row["directive_id"] == seed["directive_id"]
    assert "phase-A recalibration test" in row["reason"]
    assert "BASKET_RESET" in row["new_state"]
    assert row["previous_state"] in {"BASKET_COMPLETE", "UNKNOWN"}


def test_idempotent_on_clean_directive(isolated_paths):
    """Second reset on already-clean directive doesn't error."""
    seed = _seed_basket(isolated_paths)
    br.basket_reset(seed["directive_id"], "first reset")
    # Now directive is in INBOX (no artifacts to purge); second call should succeed
    br.basket_reset(seed["directive_id"], "idempotent check")
    audit_path = br.AUDIT_LOG
    rows = list(csv.DictReader(audit_path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 2  # Both calls logged


def test_registry_backup_created(isolated_paths):
    """Registry mutation creates a .bak.basket_reset backup."""
    seed = _seed_basket(isolated_paths)
    br.basket_reset(seed["directive_id"], "test")
    backup = br.REGISTRY_PATH.with_suffix(".json.bak.basket_reset")
    assert backup.exists()


def test_preserves_unrelated_registry_entries(isolated_paths):
    """Resetting one directive must not affect entries for other directives."""
    seed = _seed_basket(isolated_paths)
    br.basket_reset(seed["directive_id"], "test")
    reg = json.loads(br.REGISTRY_PATH.read_text(encoding="utf-8"))
    # Other entry should still exist
    assert any(
        v.get("directive_id") == "OTHER_DIRECTIVE_S01_V1_P00"
        for v in reg.values()
    )


def test_locates_directive_in_active_backup(isolated_paths):
    """Directive file in active_backup/ is found and moved to INBOX."""
    pr = isolated_paths["project_root"]
    directive_id = "TEST_BASKET_S02_V1_P00"
    (pr / "backtest_directives" / "active_backup" / f"{directive_id}.txt").write_text(
        _basket_directive_yaml(directive_id), encoding="utf-8"
    )
    br.basket_reset(directive_id, "test")
    assert (pr / "backtest_directives" / "INBOX" / f"{directive_id}.txt").exists()
    assert not (pr / "backtest_directives" / "active_backup" / f"{directive_id}.txt").exists()
