"""test_cointegration_screen.py — Phase 1 unit tests.

Validates the compute engine in tools/cointegration_screen.py against
synthetic inputs with known statistical properties. Does NOT touch
MASTER_DATA — purely deterministic from numpy seeds, so the test runs
under any identity (no SeBackupPrivilege required).

Per COINTEGRATION_SCREENER_V1_SPEC.md §12 Phase 1 gate:
    "unit test: compute against fixed inputs produces byte-identical
     parquet (modulo `generated_at`)"
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cointegration_screen import (
    PARQUET_COLUMNS,
    compute_pair_stats,
    BETA_METHOD,
    TEST_METHOD,
)


# ---------------------------------------------------------------------------
# Synthetic data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cointegrated_pair() -> tuple[pd.Series, pd.Series]:
    """A: random walk. B: 2.0 * A + stationary noise.

    Spread b - 2*a == stationary noise -> ADF should reject the
    unit-root null at well below 1%, half-life finite and small.
    """
    rng = np.random.default_rng(seed=42)
    n = 504
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    a_returns = rng.normal(0, 0.01, n)
    a = pd.Series(100 * np.exp(np.cumsum(a_returns)), index=idx, name="A")
    noise = rng.normal(0, 0.5, n)  # stationary
    b = pd.Series(2.0 * a.values + noise, index=idx, name="B")
    return a, b


@pytest.fixture
def random_walk_pair() -> tuple[pd.Series, pd.Series]:
    """Two independent random walks — should NOT be cointegrated.

    ADF p-value should be high (typically > 0.10); half-life NaN or
    very large.
    """
    rng = np.random.default_rng(seed=123)
    n = 504
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    a_returns = rng.normal(0, 0.01, n)
    b_returns = rng.normal(0, 0.01, n)
    a = pd.Series(100 * np.exp(np.cumsum(a_returns)), index=idx, name="A")
    b = pd.Series(100 * np.exp(np.cumsum(b_returns)), index=idx, name="B")
    return a, b


# ---------------------------------------------------------------------------
# Core compute tests
# ---------------------------------------------------------------------------


class TestComputePairStats:

    def test_cointegrated_pair_passes_adf(self, cointegrated_pair):
        a, b = cointegrated_pair
        stats = compute_pair_stats(a, b, lookback=252)
        assert stats is not None
        # Strong cointegration => p-value should be well below 0.05.
        assert stats["adf_pvalue"] < 0.01, (
            f"expected p<0.01 for known cointegrated pair, got {stats['adf_pvalue']}"
        )
        # Regime should be "cointegrated".
        assert stats["regime"] == "cointegrated"
        # Hedge ratio should recover the true 2.0 (within numerical tolerance).
        assert abs(stats["hedge_ratio"] - 2.0) < 0.05
        # Half-life should be finite and small (fast mean reversion).
        assert not np.isnan(stats["half_life_days"])
        assert 0 < stats["half_life_days"] < 30
        # Sample size matches the lookback.
        assert stats["sample_size"] == 252

    def test_random_walk_pair_fails_adf(self, random_walk_pair):
        a, b = random_walk_pair
        stats = compute_pair_stats(a, b, lookback=252)
        assert stats is not None
        # Random walks should NOT be cointegrated => high p-value.
        assert stats["adf_pvalue"] > 0.05, (
            f"expected p>0.05 for random walk pair, got {stats['adf_pvalue']}"
        )
        # Regime is "breaking" or "broken", never "cointegrated".
        assert stats["regime"] in ("breaking", "broken")

    def test_too_few_aligned_bars_returns_none(self):
        """If alignment leaves < lookback/2 bars, return None."""
        rng = np.random.default_rng(seed=7)
        n = 10
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        a = pd.Series(rng.normal(0, 1, n).cumsum(), index=idx)
        b = pd.Series(rng.normal(0, 1, n).cumsum(), index=idx)
        # Request lookback=252 but only 10 bars available.
        assert compute_pair_stats(a, b, lookback=252) is None

    def test_zscore_within_expected_bounds(self, cointegrated_pair):
        a, b = cointegrated_pair
        stats = compute_pair_stats(a, b, lookback=252)
        # Z-score should be a finite number, typically in [-4, 4].
        assert not np.isnan(stats["current_zscore"])
        assert -10 < stats["current_zscore"] < 10


# ---------------------------------------------------------------------------
# Schema + determinism tests
# ---------------------------------------------------------------------------


class TestDeterminism:

    def test_repeated_compute_on_same_input_is_identical(self, cointegrated_pair):
        """Byte-identity guarantee modulo non-deterministic fields."""
        a, b = cointegrated_pair
        s1 = compute_pair_stats(a, b, lookback=252)
        s2 = compute_pair_stats(a, b, lookback=252)
        # All numeric fields should be exactly equal across runs.
        for key in ("adf_pvalue", "adf_statistic", "half_life_days",
                    "hedge_ratio", "current_zscore", "sample_size"):
            assert s1[key] == s2[key], f"non-determinism in {key}"
        assert s1["regime"] == s2["regime"]


class TestSchema:

    def test_required_constants(self):
        assert BETA_METHOD == "ols_static"
        assert TEST_METHOD == "adf"

    def test_parquet_columns_canonical_order(self):
        """Schema is FROZEN — accidental reorder must fail this test."""
        expected = [
            "pair_a", "pair_b", "tf", "lookback_days",
            "window_start", "window_end", "sample_size",
            "adf_pvalue", "pvalue_rolling_median_5d", "adf_statistic",
            "half_life_days", "hedge_ratio", "beta_method", "test_method",
            "current_zscore", "regime",
            "data_version", "generated_at",
        ]
        assert PARQUET_COLUMNS == expected
