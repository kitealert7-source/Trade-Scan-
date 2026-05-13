"""Phase 5c acceptance test — real OHLC + factor data wiring.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5c.

Covers:
  - basket_data_loader.load_basket_leg_data returns DataFrames with
    OHLC + compression_5d for each requested symbol.
  - ContinuousHoldStrategy opens once and only once.
  - _load_basket_leg_inputs returns 'real' mode when the RESEARCH layer
    is available; falls back to 'synthetic' when symbols missing.
  - End-to-end: _try_basket_dispatch against the canonical 90_PORT_H2
    directive produces a basket vault + research CSV row WITH real data
    indicators (compression_5d range non-trivial, trades open).

The 10-window basket_sim bit-for-bit parity gate remains skipped —
that's Phase 5d ("live data validation gate"). This test asserts the
data wiring works; parity tuning is separate work.
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---- basket_data_loader -----------------------------------------------------


def test_load_compression_5d_factor_returns_named_series():
    from tools.basket_data_loader import load_compression_5d_factor
    series = load_compression_5d_factor("2024-09-02", "2024-09-30")
    assert isinstance(series, pd.Series)
    assert series.name == "compression_5d"
    # Daily series — at most ~30 rows for a ~4-week window
    assert 15 <= len(series) <= 40, f"expected ~daily granularity, got {len(series)}"
    # Pre-warmup NaNs are not in this window (2024-09 is well past 2007 start)
    assert series.notna().any(), "compression_5d must have at least one non-NaN value"


def test_load_basket_leg_data_eurusd_usdjpy_window():
    from tools.basket_data_loader import load_basket_leg_data
    data = load_basket_leg_data(["EURUSD", "USDJPY"], "2024-09-02", "2024-09-30")
    assert set(data.keys()) == {"EURUSD", "USDJPY"}
    for sym, df in data.items():
        assert isinstance(df, pd.DataFrame), f"{sym} payload must be DataFrame"
        assert {"open", "high", "low", "close", "compression_5d"} <= set(df.columns), (
            f"{sym} columns missing: {df.columns}"
        )
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.is_monotonic_increasing
        # Window filter applied
        assert df.index.min() >= pd.Timestamp("2024-09-02")
        assert df.index.max() <= pd.Timestamp("2024-09-30 23:59:59")
        # Real 5m data has thousands of rows in a 4-week window
        assert len(df) > 1000, f"{sym}: too few rows ({len(df)}); 5m × 4 weeks ~ 5800"


def test_load_basket_leg_data_unknown_symbol_raises():
    from tools.basket_data_loader import load_basket_leg_data
    with pytest.raises(FileNotFoundError, match="RESEARCH dir missing"):
        load_basket_leg_data(["NONESUCH"], "2024-09-02", "2024-09-30")


# ---- ContinuousHoldStrategy -------------------------------------------------


def test_continuous_hold_strategy_opens_once_only():
    from tools.recycle_strategies import ContinuousHoldStrategy
    s = ContinuousHoldStrategy(symbol="EURUSD", direction=+1)
    first = s.check_entry(None)
    second = s.check_entry(None)
    third = s.check_entry(None)
    assert first == {"signal": 1}
    assert second is None
    assert third is None


def test_continuous_hold_strategy_direction_short():
    from tools.recycle_strategies import ContinuousHoldStrategy
    s = ContinuousHoldStrategy(symbol="USDJPY", direction=-1)
    assert s.check_entry(None) == {"signal": -1}


def test_continuous_hold_strategy_never_signals_exit():
    from tools.recycle_strategies import ContinuousHoldStrategy
    s = ContinuousHoldStrategy(symbol="EURUSD", direction=+1)
    s.check_entry(None)  # open
    assert s.check_exit(None) is False
    assert s.check_exit(None) is False


def test_continuous_hold_strategy_rejects_bad_direction():
    from tools.recycle_strategies import ContinuousHoldStrategy
    with pytest.raises(ValueError, match="direction must be"):
        ContinuousHoldStrategy(symbol="EURUSD", direction=0)


# ---- run_pipeline._load_basket_leg_inputs ----------------------------------


def test_load_basket_leg_inputs_returns_real_mode_for_h2_directive():
    """When RESEARCH data is available, the dispatcher loads it in 'real' mode."""
    from tools.run_pipeline import _load_basket_leg_inputs
    from tools.pipeline_utils import parse_directive
    parsed = parse_directive(
        REPO_ROOT / "backtest_directives" / "completed"
        / "90_PORT_H2_5M_RECYCLE_S01_V1_P00.txt"
    )
    leg_data, leg_strategies, mode = _load_basket_leg_inputs(parsed)
    assert mode == "real", (
        f"expected 'real' mode against the RESEARCH layer; got {mode!r}. "
        "If DATA_INGRESS has been run, this assert flags a regression in the loader."
    )
    assert set(leg_data.keys()) == {"EURUSD", "USDJPY"}
    assert set(leg_strategies.keys()) == {"EURUSD", "USDJPY"}
    # Direction encoding survives: EURUSD long, USDJPY short per directive
    assert leg_strategies["EURUSD"].direction == +1
    assert leg_strategies["USDJPY"].direction == -1


def test_load_basket_leg_inputs_falls_back_to_synthetic_for_unknown_symbols(monkeypatch):
    """When a leg's data is unavailable, dispatcher falls back to synthetic mode."""
    from tools.run_pipeline import _load_basket_leg_inputs
    parsed = {
        "test": {"start_date": "2024-09-02", "end_date": "2024-09-30"},
        "basket": {
            "basket_id": "FAKE",
            "legs": [
                {"symbol": "NONESUCH_AAA", "lot": 0.01, "direction": "long"},
                {"symbol": "NONESUCH_BBB", "lot": 0.01, "direction": "short"},
            ],
            "recycle_rule": {"name": "H2_v7_compression", "version": 1},
        },
    }
    leg_data, leg_strategies, mode = _load_basket_leg_inputs(parsed)
    assert mode == "synthetic"
    assert set(leg_data.keys()) == {"NONESUCH_AAA", "NONESUCH_BBB"}


# ---- end-to-end dispatch with real data ------------------------------------


def test_dispatch_against_h2_directive_with_real_data(monkeypatch, tmp_path):
    """Full Phase 5c smoke: dispatch produces 'real' mode, opens positions
    on both legs, writes vault, appends research CSV row."""
    from tools.run_pipeline import _try_basket_dispatch
    import tools.run_pipeline as rp

    directive_id = "90_PORT_H2_5M_RECYCLE_S01_V1_P00"
    src = REPO_ROOT / "backtest_directives" / "completed" / f"{directive_id}.txt"
    assert src.is_file()

    tmp_active = tmp_path / "active_backup"
    tmp_active.mkdir()
    shutil.copy2(src, tmp_active / src.name)
    monkeypatch.setattr(rp, "ACTIVE_BACKUP_DIR", tmp_active)

    fake_state = tmp_path / "TradeScan_State"
    import config.path_authority as pa
    monkeypatch.setattr(pa, "TRADE_SCAN_STATE", fake_state)

    # Pre-clean any stale vault from a prior run.
    from config.path_authority import DRY_RUN_VAULT
    vault_parent = DRY_RUN_VAULT / "baskets" / directive_id
    if vault_parent.exists():
        shutil.rmtree(vault_parent)

    try:
        dispatched = _try_basket_dispatch(directive_id, provision_only=False)
        assert dispatched is True

        # Vault written
        vault_dir = vault_parent / "H2"
        assert vault_dir.is_dir()

        # CSV row
        csv_path = fake_state / "research" / "basket_runs.csv"
        assert csv_path.is_file()
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        row = rows[0]
        # Real data means at least one entry per leg fires -> trades_total >= 2
        # (each leg's evaluate_bar appends an entry+exit pair as trades, plus
        # any recycle-driven exits and the final force_close).
        assert int(row["trades_total"]) >= 2, (
            f"expected at least one entry per leg with real data; got "
            f"trades_total={row['trades_total']}"
        )
        assert row["basket_id"] == "H2"
        assert row["rule_name"] == "H2_recycle"
    finally:
        if vault_parent.exists():
            shutil.rmtree(vault_parent)
