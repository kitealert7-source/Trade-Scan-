"""Unit tests — indicators/volatility/kc_bands.py (KC Bands).

Pins the four contract properties that matter for admission:
causality (no lookahead), band asymmetry (a one-sided spike moves only
its own band), the zero-range guard, and output alignment/shape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.volatility.kc_bands import kc_bands


def _make_df(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    spread = np.abs(rng.normal(0.4, 0.1, n))
    high = close + spread
    low = close - spread
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"high": high, "low": low, "close": close}, index=idx)


def test_output_shape_and_alignment():
    df = _make_df()
    out = kc_bands(df)
    assert list(out.columns) == ["kc_upper", "kc_lower", "kc_pct_c", "kc_width_c"]
    assert out.index.equals(df.index)
    # after warmup, bands are ordered and width is positive
    tail = out.dropna()
    assert (tail["kc_upper"] > tail["kc_lower"]).all()
    assert (tail["kc_width_c"] > 0).all()


def test_no_lookahead():
    """Appending future bars must not change already-computed values."""
    df = _make_df(220)
    full = kc_bands(df)
    trunc = kc_bands(df.iloc[:200])
    pd.testing.assert_frame_equal(full.iloc[:200], trunc)


def test_input_not_mutated():
    df = _make_df()
    snapshot = df.copy(deep=True)
    kc_bands(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_asymmetry_one_sided_spike():
    """A single high-side spike must move the upper band more than the
    lower band (the design's core claim vs symmetric close-based bands).
    ATR feeds both sides, so the lower band moves a little — asymmetry
    means the upper response dominates."""
    df = _make_df()
    spiked = df.copy()
    i = 150
    spiked.iloc[i, spiked.columns.get_loc("high")] += 20.0  # high-only spike
    base = kc_bands(df)
    out = kc_bands(spiked)
    j = i + 2  # within the 3-bar band smoothing window
    d_upper = abs(out["kc_upper"].iloc[j] - base["kc_upper"].iloc[j])
    d_lower = abs(out["kc_lower"].iloc[j] - base["kc_lower"].iloc[j])
    assert d_upper > d_lower * 2


def test_pct_c_graded_beyond_bounds():
    """kc_pct_c must be measurable past the bands (e.g. deep stretch < 0)."""
    df = _make_df()
    crashed = df.copy()
    # force a close far below the channel on the last bar
    crashed.iloc[-1, crashed.columns.get_loc("close")] -= 30.0
    crashed.iloc[-1, crashed.columns.get_loc("low")] -= 30.0
    out = kc_bands(crashed)
    assert out["kc_pct_c"].iloc[-1] < 0


def test_zero_range_guard():
    """Degenerate constant series (upper == lower) -> NaN pct_c, no raise."""
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {"high": [100.0] * n, "low": [100.0] * n, "close": [100.0] * n}, index=idx
    )
    out = kc_bands(df)
    assert out["kc_pct_c"].isna().all()


def test_missing_column_raises():
    df = _make_df().drop(columns=["low"])
    with pytest.raises(ValueError, match="low"):
        kc_bands(df)
