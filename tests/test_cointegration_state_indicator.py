"""test_cointegration_state_indicator.py — C1 indicator tests.

Validates the runtime feature-lookup module against synthetic matrix
fixtures. No production-matrix dependency — monkeypatches MATRIX_DIR
to use tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from indicators.stats import cointegration_state as cs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_matrix():
    """Two pair-pairs × 10 daily bars × all 7 feature columns."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
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
                "qualified": bool(rng.random() < 0.4),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch, synthetic_matrix):
    """Write synthetic matrix to tmp_path with proper naming + LATEST pointer."""
    monkeypatch.setattr(cs, "MATRIX_DIR", tmp_path)
    monkeypatch.setattr(cs, "LATEST_POINTER", tmp_path / "coint_1d_history_matrix_LATEST.json")
    # Critical: clear cache between tests so monkeypatched paths are honored
    cs.clear_cache()

    matrix_hash = "testhash12ab"
    parquet = tmp_path / f"coint_1d_history_matrix_{matrix_hash}.parquet"
    synthetic_matrix.to_parquet(parquet, index=False)

    pointer = tmp_path / "coint_1d_history_matrix_LATEST.json"
    pointer.write_text(json.dumps({
        "matrix_hash": matrix_hash,
        "parquet_file": parquet.name,
        "manifest_file": f"coint_1d_history_matrix_{matrix_hash}.manifest.json",
        "updated_at": "2026-05-20T00:00:00+00:00",
    }))

    return tmp_path, matrix_hash


# ---------------------------------------------------------------------------
# Hash resolution
# ---------------------------------------------------------------------------


class TestHashResolution:

    def test_resolve_latest_returns_pointer_hash(self, fixture_dir):
        _, expected_hash = fixture_dir
        assert cs.resolve_latest_hash() == expected_hash

    def test_resolve_latest_raises_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "MATRIX_DIR", tmp_path)
        monkeypatch.setattr(cs, "LATEST_POINTER", tmp_path / "no_such_pointer.json")
        with pytest.raises(FileNotFoundError, match="LATEST pointer not found"):
            cs.resolve_latest_hash()

    def test_list_available_hashes(self, fixture_dir):
        tmp_path, h = fixture_dir
        # Add a second hash to the dir
        (tmp_path / f"coint_1d_history_matrix_otherhash02.parquet").touch()
        hashes = cs.list_available_hashes()
        assert h in hashes
        assert "otherhash02" in hashes
        assert "LATEST" not in hashes


# ---------------------------------------------------------------------------
# Matrix load
# ---------------------------------------------------------------------------


class TestLoadMatrix:

    def test_load_by_explicit_hash(self, fixture_dir):
        _, h = fixture_dir
        df = cs.load_history_matrix(h)
        assert len(df) == 20  # 2 pairs × 10 dates
        assert "date" in df.columns
        assert df.groupby(["pair_a", "pair_b"]).ngroups == 2

    def test_load_with_none_uses_latest(self, fixture_dir):
        df = cs.load_history_matrix()
        assert len(df) == 20

    def test_load_caches(self, fixture_dir):
        _, h = fixture_dir
        df1 = cs.load_history_matrix(h)
        df2 = cs.load_history_matrix(h)
        assert df1 is df2   # same object — cache hit

    def test_load_raises_for_missing_hash(self, fixture_dir):
        with pytest.raises(FileNotFoundError, match="matrix not found"):
            cs.load_history_matrix("nonexistent99")


# ---------------------------------------------------------------------------
# Per-pair feature extraction
# ---------------------------------------------------------------------------


class TestGetPairFeatures:

    def test_returns_expected_columns(self, fixture_dir):
        df = cs.load_history_matrix()
        target = pd.date_range("2025-01-01", periods=10, freq="D")
        feats = cs.get_pair_features(df, "EURUSD", "USDJPY", target)
        expected = ["beta", "spread_mean", "spread_std", "daily_z",
                    "adf_p_252", "adf_p_504", "qualified"]
        assert list(feats.columns) == expected
        assert len(feats) == 10

    def test_pair_lookup_is_alphabetically_canonicalized(self, fixture_dir):
        """(A, B) and (B, A) must look up the same row set."""
        df = cs.load_history_matrix()
        target = pd.date_range("2025-01-01", periods=10, freq="D")
        ab = cs.get_pair_features(df, "EURUSD", "USDJPY", target)
        ba = cs.get_pair_features(df, "USDJPY", "EURUSD", target)
        pd.testing.assert_frame_equal(ab, ba)

    def test_missing_pair_raises(self, fixture_dir):
        df = cs.load_history_matrix()
        target = pd.date_range("2025-01-01", periods=10, freq="D")
        with pytest.raises(KeyError, match="GBPUSD/USDCAD not in matrix"):
            cs.get_pair_features(df, "GBPUSD", "USDCAD", target)

    def test_ffill_projects_daily_to_intraday(self, fixture_dir):
        """A 15m-spaced target index between two daily bars must inherit
        the most recent <= target daily value (forward-fill)."""
        df = cs.load_history_matrix()
        # 15m bars across the 10-day window
        intraday = pd.date_range("2025-01-01", "2025-01-10", freq="15min")
        feats = cs.get_pair_features(df, "EURUSD", "USDJPY", intraday, ffill=True)
        assert len(feats) == len(intraday)
        # Pick the first daily-bar timestamp and verify its qualified flag
        # is propagated to the next 95 15m bars (1 day's worth)
        first_day_qualified = feats.loc[pd.Timestamp("2025-01-01"), "qualified"]
        # The next 95 15m bars (full Jan 1) should all share this value
        same_day = feats.loc["2025-01-01 00:00":"2025-01-01 23:45"]
        assert (same_day["qualified"] == first_day_qualified).all()

    def test_qualified_is_bool_even_after_ffill(self, fixture_dir):
        """qualified column must stay bool dtype after ffill of NaN
        (NaN gets filled to False, then cast)."""
        df = cs.load_history_matrix()
        # Target extends BEFORE the matrix dates — first rows will have NaN
        target = pd.date_range("2024-12-25", "2025-01-10", freq="D")
        feats = cs.get_pair_features(df, "EURUSD", "USDJPY", target, ffill=True)
        assert str(feats["qualified"].dtype) == "bool"
        # Pre-matrix dates should be False (not NaN)
        pre_matrix = feats.loc[:"2024-12-31"]
        assert not pre_matrix["qualified"].any()

    def test_no_ffill_preserves_nan(self, fixture_dir):
        df = cs.load_history_matrix()
        # Target extends BEFORE the matrix dates with daily-aligned timestamps;
        # without ffill, pre-matrix dates → NaN feature values.
        target = pd.date_range("2024-12-25", "2025-01-10", freq="D")
        feats = cs.get_pair_features(df, "EURUSD", "USDJPY", target, ffill=False)
        pre = feats.loc[:"2024-12-31"]
        # beta should be NaN for pre-matrix dates
        assert pre["beta"].isna().all()
