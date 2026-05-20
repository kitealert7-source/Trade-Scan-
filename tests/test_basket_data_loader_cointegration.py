"""test_basket_data_loader_cointegration.py — C3b basket_data_loader
extension tests.

Tests the two new helpers added to basket_data_loader for the COINTREV
strategy family:
  * load_cointegration_factor — reads from history matrix, returns per-pair
                                  daily features. Tested against a
                                  monkeypatched synthetic matrix.
  * compute_intra_z          — 100-bar rolling z-score on chart TF using
                                  a daily-pinned β.

The full auto-join inside load_basket_leg_data is integration-tested in
C3d when a real directive runs through the pipeline — that path requires
MASTER_DATA + the basket_runner stack, which is not unit-testable here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.basket_data_loader import (
    compute_intra_z,
    load_cointegration_factor,
)
from indicators.stats import cointegration_state as cs


# ---------------------------------------------------------------------------
# Synthetic matrix fixture (mirrors C1 test setup)
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_matrix_on_disk(tmp_path, monkeypatch):
    """Write a synthetic cointegration matrix + LATEST pointer to tmp_path
    and monkeypatch cointegration_state to look there."""
    monkeypatch.setattr(cs, "MATRIX_DIR", tmp_path)
    monkeypatch.setattr(cs, "LATEST_POINTER", tmp_path / "coint_1d_history_matrix_LATEST.json")
    cs.clear_cache()

    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    rows = []
    for (a, b) in [("EURUSD", "USDJPY"), ("AUDUSD", "NZDUSD")]:
        for d in dates:
            rows.append({
                "date": d,
                "pair_a": a, "pair_b": b,
                "beta": float(rng.uniform(0.5, 2.0)),
                "spread_mean": float(rng.normal(0, 1)),
                "spread_std": float(rng.uniform(0.5, 1.5)),
                "daily_z": float(rng.normal(0, 1)),
                "adf_p_252": float(rng.uniform(0.001, 0.5)),
                "adf_p_504": float(rng.uniform(0.001, 0.5)),
                "qualified": bool(rng.random() < 0.5),
            })
    matrix_df = pd.DataFrame(rows)

    matrix_hash = "synth0123abcd"
    parquet = tmp_path / f"coint_1d_history_matrix_{matrix_hash}.parquet"
    matrix_df.to_parquet(parquet, index=False)
    pointer = tmp_path / "coint_1d_history_matrix_LATEST.json"
    pointer.write_text(json.dumps({
        "matrix_hash": matrix_hash,
        "parquet_file": parquet.name,
        "manifest_file": f"coint_1d_history_matrix_{matrix_hash}.manifest.json",
        "updated_at": "2026-05-20T00:00:00+00:00",
    }))
    return tmp_path, matrix_hash, matrix_df


# ---------------------------------------------------------------------------
# load_cointegration_factor
# ---------------------------------------------------------------------------


class TestLoadCointegrationFactor:

    def test_returns_per_pair_dataframe(self, synthetic_matrix_on_disk):
        df = load_cointegration_factor("EURUSD", "USDJPY")
        # Should have 30 rows (one per date in the fixture) for this pair
        assert len(df) == 30
        # Indexed by date
        assert df.index.name == "date"
        # All expected columns present
        for c in ("beta", "spread_mean", "spread_std", "daily_z",
                   "adf_p_252", "adf_p_504", "qualified"):
            assert c in df.columns

    def test_pair_canonicalization(self, synthetic_matrix_on_disk):
        """(A, B) and (B, A) caller order must return identical features."""
        ab = load_cointegration_factor("EURUSD", "USDJPY")
        ba = load_cointegration_factor("USDJPY", "EURUSD")
        pd.testing.assert_frame_equal(ab, ba)

    def test_missing_pair_raises_keyerror(self, synthetic_matrix_on_disk):
        with pytest.raises(KeyError, match="cointegration matrix has no pair"):
            load_cointegration_factor("GBPUSD", "USDCAD")

    def test_date_range_filter(self, synthetic_matrix_on_disk):
        df = load_cointegration_factor(
            "EURUSD", "USDJPY",
            start_date=datetime(2024, 1, 10),
            end_date=datetime(2024, 1, 20),
        )
        assert len(df) == 11   # inclusive both ends
        assert df.index.min() >= pd.Timestamp("2024-01-10")
        assert df.index.max() <= pd.Timestamp("2024-01-20")

    def test_missing_matrix_raises_filenotfound(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "MATRIX_DIR", tmp_path)
        monkeypatch.setattr(cs, "LATEST_POINTER", tmp_path / "no_pointer.json")
        cs.clear_cache()
        with pytest.raises(FileNotFoundError, match="LATEST pointer not found"):
            load_cointegration_factor("EURUSD", "USDJPY")


# ---------------------------------------------------------------------------
# compute_intra_z
# ---------------------------------------------------------------------------


class TestComputeIntraZ:

    def test_returns_series_aligned_to_input(self):
        idx = pd.date_range("2024-06-01", periods=200, freq="15min")
        close_a = pd.Series(np.linspace(1.0, 1.01, 200), index=idx)
        close_b = pd.Series(np.linspace(100.0, 101.0, 200), index=idx)
        beta = pd.Series([1.5] * 200, index=idx)
        z = compute_intra_z(close_a, close_b, beta, window=50)
        assert isinstance(z, pd.Series)
        assert len(z) == 200
        assert (z.index == idx).all()

    def test_z_has_warmup_nans(self):
        idx = pd.date_range("2024-06-01", periods=200, freq="15min")
        close_a = pd.Series(np.random.normal(1, 0.01, 200).cumsum() + 100, index=idx)
        close_b = pd.Series(np.random.normal(1, 0.01, 200).cumsum() + 200, index=idx)
        beta = pd.Series([1.5] * 200, index=idx)
        z = compute_intra_z(close_a, close_b, beta, window=100)
        # min_periods = max(2, 50) → first ~50 bars NaN
        assert z.iloc[:40].isna().all()
        assert z.iloc[-10:].notna().all()

    def test_stationary_spread_z_in_reasonable_range(self):
        """A perfectly stationary spread should give |z| usually < 3."""
        rng = np.random.default_rng(42)
        n = 500
        idx = pd.date_range("2024-06-01", periods=n, freq="15min")
        # Spread = noise around 0 (stationary)
        a = pd.Series(np.ones(n), index=idx)
        b = pd.Series(rng.normal(0, 1, n), index=idx)  # spread = b directly
        beta = pd.Series([0.0] * n, index=idx)
        z = compute_intra_z(a, b, beta, window=100).dropna()
        # 99% of values within ±3σ for a stationary series
        assert (z.abs() < 3.5).mean() > 0.98

    def test_dislocated_spread_produces_high_z(self):
        """Stepping the spread mid-series should produce a |z| spike."""
        n = 300
        idx = pd.date_range("2024-06-01", periods=n, freq="15min")
        # Spread = 0 for first 200 bars, then jumps to 10 σ above mean
        a = pd.Series(np.ones(n), index=idx)
        spread = np.zeros(n)
        spread[200:] = 5.0
        # Add tiny noise so std isn't zero
        rng = np.random.default_rng(11)
        spread = spread + rng.normal(0, 0.1, n)
        b = pd.Series(spread, index=idx)
        beta = pd.Series([0.0] * n, index=idx)
        z = compute_intra_z(a, b, beta, window=100)
        # Bars 200-210 should show |z| > 2 (the dislocation)
        assert z.iloc[201:210].abs().max() > 2.0
