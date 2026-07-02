"""Unit tests — indicators/momentum/cci.py (Commodity Channel Index)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.momentum.cci import cci


def _make_df(n: int = 250, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    spread = np.abs(rng.normal(0.4, 0.1, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"high": close + spread, "low": close - spread, "close": close}, index=idx
    )


def test_output_alignment_and_warmup():
    df = _make_df()
    out = cci(df, period=20)
    assert isinstance(out, pd.Series)
    assert out.index.equals(df.index)
    assert out.iloc[:19].isna().all()          # warmup NaN
    assert out.iloc[20:].notna().all()


def test_centered_and_scaled():
    """On a stationary random walk the distribution straddles zero and
    lives mostly inside the conventional +/-300 envelope."""
    out = cci(_make_df(600)).dropna()
    assert out.min() < 0 < out.max()
    assert (out.abs() < 500).mean() > 0.99


def test_known_value_single_window():
    """Hand-check one window: constant series inside the window except a
    final step — verify against the direct formula."""
    n = 25
    close = np.full(n, 100.0)
    close[-1] = 110.0
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame({"high": close, "low": close, "close": close}, index=idx)
    out = cci(df, period=20)
    window = close[-20:]
    expected = (window[-1] - window.mean()) / (
        0.015 * np.abs(window - window.mean()).mean()
    )
    assert out.iloc[-1] == pytest.approx(expected)


def test_no_lookahead():
    df = _make_df(270)
    full = cci(df)
    trunc = cci(df.iloc[:250])
    pd.testing.assert_series_equal(full.iloc[:250], trunc)


def test_input_not_mutated():
    df = _make_df()
    snapshot = df.copy(deep=True)
    cci(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_zero_mad_guard():
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {"high": [100.0] * n, "low": [100.0] * n, "close": [100.0] * n}, index=idx
    )
    out = cci(df)
    assert out.isna().all()                    # MAD == 0 -> NaN, no raise


def test_source_variants_and_bad_source():
    df = _make_df()
    typ = cci(df, source="typical").dropna()
    hl2 = cci(df, source="hl2").dropna()
    assert not typ.equals(hl2)                 # variants genuinely differ
    with pytest.raises(ValueError, match="source"):
        cci(df, source="median")


def test_missing_column_raises():
    df = _make_df().drop(columns=["close"])
    with pytest.raises(ValueError, match="close"):
        cci(df)
