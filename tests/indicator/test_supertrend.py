"""Unit tests — indicators/trend/supertrend.py.

Pins the contract properties that matter for admission: causality
(forward-only recursion), the ratchet invariant (uptrend stop never
falls, downtrend stop never rises, within a direction run), flip
semantics on a synthetic reversal, and hygiene (alignment, mutation,
missing columns).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.trend.supertrend import supertrend


def _make_df(n: int = 300, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.6, n))
    spread = np.abs(rng.normal(0.5, 0.15, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"high": close + spread, "low": close - spread, "close": close}, index=idx
    )


def _make_vee(n_leg: int = 120) -> pd.DataFrame:
    """Deterministic down-then-up 'V' — guarantees at least one flip."""
    down = 200 - np.arange(n_leg) * 1.0
    up = down[-1] + np.arange(1, n_leg + 1) * 1.0
    close = np.concatenate([down, up])
    idx = pd.date_range("2024-01-01", periods=len(close), freq="h")
    return pd.DataFrame(
        {"high": close + 0.5, "low": close - 0.5, "close": close}, index=idx
    )


def test_output_shape_and_direction_domain():
    df = _make_df()
    out = supertrend(df)
    assert list(out.columns) == ["supertrend", "st_dir", "st_upper", "st_lower"]
    assert out.index.equals(df.index)
    settled = out["st_dir"].iloc[15:]
    assert set(settled.unique()).issubset({-1, 1})


def test_line_sides_price_by_direction():
    df = _make_df()
    out = supertrend(df).iloc[15:]
    up = out[out["st_dir"] == 1]
    down = out[out["st_dir"] == -1]
    assert (up["supertrend"] == up["st_lower"]).all()
    assert (down["supertrend"] == down["st_upper"]).all()


def test_no_lookahead():
    df = _make_df(320)
    full = supertrend(df)
    trunc = supertrend(df.iloc[:300])
    pd.testing.assert_frame_equal(full.iloc[:300], trunc)


def test_input_not_mutated():
    df = _make_df()
    snapshot = df.copy(deep=True)
    supertrend(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_flip_on_reversal():
    """Down-leg must register -1; up-leg must eventually flip to +1."""
    out = supertrend(_make_vee())
    n_leg = 120
    assert out["st_dir"].iloc[60] == -1
    assert out["st_dir"].iloc[-1] == 1
    flips = (out["st_dir"].iloc[15:] != out["st_dir"].shift(1).iloc[15:]).sum()
    assert flips >= 1


def test_ratchet_invariant():
    """Within one direction run, the active line only moves toward price:
    non-decreasing while long (+1), non-increasing while short (-1)."""
    out = supertrend(_make_df()).iloc[15:]
    d = out["st_dir"].to_numpy()
    line = out["supertrend"].to_numpy()
    same_run = d[1:] == d[:-1]
    diffs = line[1:] - line[:-1]
    assert (diffs[same_run & (d[1:] == 1)] >= -1e-9).all()
    assert (diffs[same_run & (d[1:] == -1)] <= 1e-9).all()


def test_missing_column_raises():
    df = _make_df().drop(columns=["high"])
    with pytest.raises(ValueError, match="high"):
        supertrend(df)
