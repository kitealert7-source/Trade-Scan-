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
    COINT_UNIVERSE,
    PARQUET_COLUMNS,
    SINGLES_PARQUET_COLUMNS,
    SUPPORTED_TFS,
    compute_pair_stats,
    compute_single_series_adf,
    compute_synthetic_log_ratio,
    lookback_for,
    metadata_path_for,
    parquet_path_for,
    singles_metadata_path_for,
    singles_parquet_path_for,
    universe_for,
    BETA_METHOD,
    TEST_METHOD,
    PAIR_METHODOLOGY_VERSION,
    SINGLES_METHODOLOGY_VERSION,
)
from tools.factors.fx_correlation_matrix import FX_UNIVERSE


# ---------------------------------------------------------------------------
# Synthetic data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cointegrated_pair() -> tuple[pd.Series, pd.Series]:
    """Log-cointegrated by construction: B = A * exp(stationary_noise).

    Equivalently: log(B) = log(A) + ε where ε is stationary. So (la, lb)
    are cointegrated with β=1.0 exactly; the residual log-spread is just ε.
    Under v2 (log + Engle-Granger via coint()), this fits the math directly:
    coint(lb, la) returns a small p-value, OLS recovers β≈1.0, log-spread
    is stationary so half-life is finite + small.

    Construction migrated 2026-05-30 (C3) from the v1 linear form
    `B = 2.0 * A + noise` — that form was *also* log-cointegrated when
    a >> noise, but β coerced to ≈1.0 not 2.0 under log-space OLS, so the
    test's hedge_ratio assertion needed re-grounding in the new construction.
    """
    rng = np.random.default_rng(seed=42)
    n = 504
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    a_returns = rng.normal(0, 0.01, n)
    a = pd.Series(100 * np.exp(np.cumsum(a_returns)), index=idx, name="A")
    log_noise = rng.normal(0, 0.005, n)  # stationary in log-space
    b = pd.Series(a.values * np.exp(log_noise), index=idx, name="B")
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
        # adf_pvalue field name preserved for schema stability; under v2 the
        # value is the Engle-Granger p-value from coint(), not raw adfuller.
        assert stats["adf_pvalue"] < 0.01, (
            f"expected p<0.01 for known log-cointegrated pair, got {stats['adf_pvalue']}"
        )
        # Regime should be "cointegrated".
        assert stats["regime"] == "cointegrated"
        # Hedge ratio recovers ≈1.0 by construction (B = A * exp(noise) → β=1
        # in log space). Under v1 raw this synthetic gave β≈2.0; under v2 log
        # it gives β≈1.0 — the assertion was re-grounded with the synthetic.
        assert abs(stats["hedge_ratio"] - 1.0) < 0.05, (
            f"expected hedge_ratio ≈1.0 in log space, got {stats['hedge_ratio']}"
        )
        # Half-life should be finite and small (fast mean reversion).
        assert not np.isnan(stats["half_life_days"])
        assert 0 < stats["half_life_days"] < 30
        # Sample size matches the lookback.
        assert stats["sample_size"] == 252
        # Methodology cohort tag: pair path is v2_log_eg post-C3.
        assert stats["methodology_version"] == "v2_log_eg"

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
        # v2 (C3, 2026-05-30): cointegration test is Engle-Granger with
        # MacKinnon critical values via statsmodels.tsa.stattools.coint.
        # Field names adf_statistic / adf_pvalue retained; semantics flip
        # via this constant.
        assert TEST_METHOD == "eg_mackinnon"

    def test_methodology_constants_post_c3(self):
        """Cohort tags after the math fix lands."""
        assert PAIR_METHODOLOGY_VERSION == "v2_log_eg"
        assert SINGLES_METHODOLOGY_VERSION == "v2_log_adf"

    def test_parquet_columns_canonical_order(self):
        """Schema is FROZEN — accidental reorder must fail this test.
        Additive-only: methodology_version appended at end 2026-05-30 (C2)."""
        expected = [
            "pair_a", "pair_b", "tf", "lookback_days",
            "window_start", "window_end", "sample_size",
            "adf_pvalue", "pvalue_rolling_median_5d", "adf_statistic",
            "half_life_days", "hedge_ratio", "beta_method", "test_method",
            "current_zscore", "regime",
            "data_version", "generated_at",
            "methodology_version",
        ]
        assert PARQUET_COLUMNS == expected

    def test_singles_parquet_columns_canonical_order(self):
        expected = [
            "symbol", "tf", "lookback_days",
            "window_start", "window_end", "sample_size",
            "adf_pvalue", "pvalue_rolling_median_5d", "adf_statistic",
            "half_life_days", "current_zscore", "regime",
            "data_version", "generated_at",
            "methodology_version",
        ]
        assert SINGLES_PARQUET_COLUMNS == expected

    def test_universe_includes_cross_asset(self):
        for sym in ("XAUUSD", "BTCUSD", "ETHUSD"):
            assert sym in COINT_UNIVERSE


# ---------------------------------------------------------------------------
# Single-series ADF tests (2026-05-21 addition — single-leg mean-reversion)
# ---------------------------------------------------------------------------


class TestComputeSingleSeriesAdf:

    def test_stationary_series_passes_adf(self):
        """A mean-reverting AR(1) process should produce p<0.05 + finite hl."""
        rng = np.random.default_rng(seed=42)
        n = 504
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        # Generate AR(1) with strong mean reversion: x_t = 0.5 * x_{t-1} + ε
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = 0.5 * x[i - 1] + rng.normal(0, 1.0)
        # Exponentiate to make it a price-like series (positive values).
        series = pd.Series(100 * np.exp(0.01 * x), index=idx)
        stats = compute_single_series_adf(series, lookback=252)
        assert stats is not None
        assert stats["adf_pvalue"] < 0.05, (
            f"expected p<0.05 for AR(1) stationary, got {stats['adf_pvalue']}"
        )
        assert stats["regime"] == "cointegrated"
        assert not np.isnan(stats["half_life_days"])
        assert 0 < stats["half_life_days"] < 10

    def test_random_walk_fails_adf(self):
        """A random walk should NOT pass ADF — high p-value, no regime."""
        rng = np.random.default_rng(seed=99)
        n = 504
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        rw = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
        stats = compute_single_series_adf(rw, lookback=252)
        assert stats is not None
        assert stats["adf_pvalue"] > 0.05
        assert stats["regime"] in ("breaking", "broken")

    def test_too_few_bars_returns_none(self):
        rng = np.random.default_rng(seed=7)
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        s = pd.Series(rng.normal(0, 1, 10).cumsum() + 100, index=idx)
        assert compute_single_series_adf(s, lookback=252) is None

    def test_synthetic_log_ratio_picks_up_stationary_spread(self):
        """log(A/B) stationary when A and B share a stochastic trend with a
        bounded residual. Verifies the synthetic-ratio path works end-to-end."""
        rng = np.random.default_rng(seed=11)
        n = 504
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        common = np.cumsum(rng.normal(0, 0.01, n))
        a = pd.Series(100 * np.exp(common + rng.normal(0, 0.005, n)), index=idx)
        b = pd.Series(100 * np.exp(common + rng.normal(0, 0.005, n)), index=idx)
        stats = compute_synthetic_log_ratio(a, b, lookback=252)
        assert stats is not None
        # A/B is two independent jitter terms around the same trend → ratio is
        # approximately stationary. Should produce a small (but not vanishing)
        # p-value.
        assert stats["adf_pvalue"] < 0.10


# ---------------------------------------------------------------------------
# Candidates registry tests (2026-05-21 addition)
# ---------------------------------------------------------------------------


class TestCandidatesRegistry:

    def test_candidates_yaml_parses(self):
        from tools.cointegration_excel import load_candidates
        data = load_candidates()
        assert "forex" in data
        assert "crypto" in data
        assert "indices_stocks" in data
        # Forex has known candidates
        forex_keys = {c["key"] for c in data["forex"]["candidates"]}
        assert "AUDNZD" in forex_keys
        assert "GBPJPY_vs_XAUUSD" in forex_keys
        # Crypto has known candidates
        crypto_keys = {c["key"] for c in data["crypto"]["candidates"]}
        assert "BTC_ETH_RATIO" in crypto_keys
        # Indices/stocks deferred
        assert data["indices_stocks"].get("deferred") is True

    def test_candidate_types_are_valid(self):
        from tools.cointegration_excel import load_candidates
        data = load_candidates()
        valid_types = {"single", "pair", "synthetic_ratio"}
        valid_routes = {"direct", "synthesize", "redundant_with"}
        for class_key, cls in data.items():
            for c in cls.get("candidates") or []:
                assert c["type"] in valid_types, (
                    f"{class_key}/{c['key']} has invalid type {c['type']!r}"
                )
                assert c["route"] in valid_routes, (
                    f"{class_key}/{c['key']} has invalid route {c['route']!r}"
                )
                if c["route"] == "redundant_with":
                    assert c.get("canonical"), (
                        f"{class_key}/{c['key']} is redundant_with but no "
                        f"canonical key set"
                    )

    def test_candidate_pair_tokens_match_route(self):
        """Pair candidates with route=synthesize should be DISJOINT (no
        shared currency); route=redundant_with should be TRIANGULAR
        (share a currency)."""
        from tools.cointegration_excel import load_candidates
        data = load_candidates()

        def tokens(sym: str) -> set[str]:
            return {sym[:3], sym[3:]}

        for class_key, cls in data.items():
            for c in cls.get("candidates") or []:
                if c["type"] != "pair":
                    continue
                a, b = c["pair_a"], c["pair_b"]
                shared = tokens(a) & tokens(b)
                if c["route"] == "synthesize":
                    assert not shared, (
                        f"{c['key']}: marked synthesize but shares {shared}"
                    )
                elif c["route"] == "redundant_with":
                    assert shared, (
                        f"{c['key']}: marked redundant_with but has disjoint "
                        f"tokens"
                    )


# ---------------------------------------------------------------------------
# Multi-TF parameterization (Phase 1, locked decision 2026-05-26)
# ---------------------------------------------------------------------------


class TestMultiTFParameterization:
    """Phase-1 parameterization for the screener: 1d is the default and
    preserves all legacy paths; 4h is the opt-in research tier with
    calendar-matched windows + FX-only universe."""

    def test_supported_tfs_locked(self):
        """Scope-discipline guard: only 1d and 4h are supported in Phase 1.
        Adding 1h or 15m requires the operator decision gate
        (see feedback_infra_build_to_falsify)."""
        assert set(SUPPORTED_TFS) == {"1d", "4h"}

    def test_universe_1d_is_full_cross_asset(self):
        u = universe_for("1d")
        assert len(u) == len(COINT_UNIVERSE)
        # Spot-check: indices + crypto present at 1d
        assert "SPX500" in u
        assert "BTCUSD" in u
        assert "EURUSD" in u

    def test_universe_4h_matches_full_cross_asset(self):
        """Decision 2026-05-26 (revised): 4h universe matches 1d
        cross-asset (31 symbols). OctaFX synthesizes index 4h bars to
        24-hour cadence (verified: SPX500 has ~1545 4h bars in 2025
        vs EURUSD's 1567), so inner-join with FX works. Cross-asset
        pair-pairs are the most research-productive surface per
        RESEARCH_MEMORY 2026-05-21."""
        u = universe_for("4h")
        assert set(u) == set(COINT_UNIVERSE)
        assert len(u) == 31
        # FX, commodity, crypto, and indices must all appear at 4h
        for required in ["EURUSD", "XAUUSD", "BTCUSD", "SPX500", "JPN225"]:
            assert required in u, f"{required} should be in 4h universe"

    def test_universe_unsupported_tf_raises(self):
        with pytest.raises(ValueError, match="Unsupported tf"):
            universe_for("1h")
        with pytest.raises(ValueError, match="Unsupported tf"):
            universe_for("15m")

    def test_lookback_1d_is_legacy_windows(self):
        assert lookback_for("1d") == (252, 504)

    def test_lookback_4h_is_calendar_matched(self):
        """4h windows preserve calendar time (~1y / ~2y) so the ADF test
        retains its cointegration interpretation — not microstructure MR."""
        assert lookback_for("4h") == (1500, 3000)

    def test_parquet_path_namespaced_per_tf(self):
        p_1d = parquet_path_for("1d")
        p_4h = parquet_path_for("4h")
        assert p_1d.name == "coint_1d_latest.parquet"
        assert p_4h.name == "coint_4h_latest.parquet"
        assert p_1d != p_4h

    def test_metadata_path_1d_keeps_legacy_filename(self):
        """1d metadata stays at the un-namespaced `metadata.json` filename
        for backward compat. 4h gets the namespaced sibling."""
        assert metadata_path_for("1d").name == "metadata.json"
        assert metadata_path_for("4h").name == "metadata_4h.json"

    def test_singles_paths_namespaced_per_tf(self):
        assert singles_parquet_path_for("1d").name == "singles_1d_latest.parquet"
        assert singles_parquet_path_for("4h").name == "singles_4h_latest.parquet"
        # singles_metadata: 1d keeps legacy, 4h namespaced
        assert singles_metadata_path_for("1d").name == "singles_metadata.json"
        assert singles_metadata_path_for("4h").name == "singles_metadata_4h.json"

    def test_cli_accepts_tf_4h_choice(self):
        """The argparse spec must accept --tf 4h (and reject 1h to
        prevent scope creep before Phase-4 validation gate)."""
        from tools.cointegration_screen import _parser
        parser = _parser()
        args = parser.parse_args(["--tf", "4h"])
        assert args.tf == "4h"
        # Default is 1d
        args = parser.parse_args([])
        assert args.tf == "1d"
        # 1h must be rejected (out of scope per locked decision)
        with pytest.raises(SystemExit):
            parser.parse_args(["--tf", "1h"])
