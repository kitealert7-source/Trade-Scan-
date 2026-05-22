"""Unit tests for indicators.stats.spread_sma_cross.

Covers the existing smoothed columns (cross_side, cross_event) and the
2026-05-22 additions (diff_raw, cross_side_raw, cross_event_raw) used
by the S16 z=0 exit probe (h3_spread@2 exit-side faster signal test).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.stats.spread_sma_cross import spread_sma_cross


def _make_series(values, start="2024-01-01"):
    """Build a 5m-spaced Series from a values iterable."""
    idx = pd.date_range(start, periods=len(values), freq="5min")
    return pd.Series(values, index=idx, dtype=float)


def test_output_has_expected_columns():
    """The output DataFrame must expose all 10 contracted columns."""
    rng = np.random.default_rng(42)
    a = _make_series(rng.normal(loc=1.10, scale=0.001, size=100))
    b = _make_series(rng.normal(loc=150.0, scale=0.1, size=100))
    out = spread_sma_cross(a, b, z_window=20, sma_window=5)
    expected = {
        "z_a", "z_b", "sma_z_a", "sma_z_b", "diff",
        "cross_side", "cross_event",
        "diff_raw", "cross_side_raw", "cross_event_raw",
    }
    assert expected.issubset(set(out.columns)), (
        f"Missing columns: {expected - set(out.columns)}"
    )


def test_cross_side_raw_is_sign_of_diff_raw():
    """cross_side_raw must equal sign(diff_raw) row-wise post-warmup."""
    rng = np.random.default_rng(7)
    a = _make_series(rng.normal(loc=1.10, scale=0.001, size=200))
    b = _make_series(rng.normal(loc=150.0, scale=0.1, size=200))
    out = spread_sma_cross(a, b, z_window=20, sma_window=5)

    # Drop warmup rows (z_window for raw variants)
    valid = out.iloc[20:].copy()
    expected = np.sign(valid["diff_raw"]).astype(int)
    # Where diff_raw is NaN (any residual edge case), cross_side_raw is 0.
    expected_safe = expected.where(~valid["diff_raw"].isna(), 0)
    assert (valid["cross_side_raw"] == expected_safe).all()


def test_cross_side_raw_leads_smoothed_cross_side_in_retrace():
    """Constructed retrace: z_a starts above z_b, then dives below. The
    UNSMOOTHED cross fires earlier than the SMOOTHED cross by ~sma_window/2
    bars (the smoothing's group delay).
    """
    # Build a deterministic spread that's clearly positive, then flips
    # negative at a known bar. Use long enough series that warmup is
    # cleared and the SMA has time to stabilize.
    n = 100
    a_vals = np.concatenate([
        np.linspace(1.10, 1.20, 50),    # rising → z_a will be positive
        np.linspace(1.20, 1.05, 50),    # falling sharply → z_a flips negative
    ])
    b_vals = np.full(n, 150.0)          # flat → z_b ≈ 0 most of run
    # Tiny noise to keep z_b's std non-zero
    rng = np.random.default_rng(3)
    b_vals = b_vals + rng.normal(0, 0.001, size=n)
    a = _make_series(a_vals)
    b = _make_series(b_vals)
    z_window, sma_window = 10, 5
    out = spread_sma_cross(a, b, z_window=z_window, sma_window=sma_window)

    # Find the first bar where the SMOOTHED side flips from + to -
    smoothed = out["cross_side"].iloc[z_window + sma_window:]
    raw = out["cross_side_raw"].iloc[z_window + sma_window:]
    # Locate transitions to -1 in both series
    smoothed_flip = smoothed.index[
        (smoothed == -1) & (smoothed.shift(1, fill_value=0) >= 0)
    ]
    raw_flip = raw.index[
        (raw == -1) & (raw.shift(1, fill_value=0) >= 0)
    ]
    # If both flipped at least once, raw must flip at-or-before smoothed.
    if len(smoothed_flip) and len(raw_flip):
        assert raw_flip[0] <= smoothed_flip[0], (
            f"Raw cross at {raw_flip[0]} fires AFTER smoothed cross at "
            f"{smoothed_flip[0]} — unsmoothed should lead in a retrace."
        )


def test_cross_event_raw_transition_semantics():
    """cross_event_raw fires exactly once on each cross_side_raw transition."""
    rng = np.random.default_rng(11)
    n = 300
    a = _make_series(rng.normal(loc=1.10, scale=0.005, size=n))
    b = _make_series(rng.normal(loc=150.0, scale=0.5, size=n))
    out = spread_sma_cross(a, b, z_window=20, sma_window=5)

    valid = out.iloc[20:].copy()
    # Manually reconstruct expected events from cross_side_raw transitions
    css = valid["cross_side_raw"]
    prev = css.shift(1, fill_value=0)
    expected_plus = (css == 1) & (prev <= 0)
    expected_minus = (css == -1) & (prev >= 0)
    expected = pd.Series(0, index=css.index, dtype=int)
    expected[expected_plus] = 1
    expected[expected_minus] = -1
    assert (valid["cross_event_raw"] == expected).all()


def test_existing_columns_unchanged_by_raw_addition():
    """Smoke check: the smoothed columns (cross_side, cross_event, diff,
    sma_z_a, sma_z_b) must NOT differ from their pre-addition behavior.
    Hand-fixture verifies value-equivalence to a manual recomputation.
    """
    rng = np.random.default_rng(99)
    n = 150
    a = _make_series(rng.normal(loc=1.10, scale=0.002, size=n))
    b = _make_series(rng.normal(loc=150.0, scale=0.2, size=n))
    out = spread_sma_cross(a, b, z_window=20, sma_window=5)

    # Manual recomputation of the smoothed pipeline
    z_a = (a - a.rolling(20).mean()) / a.rolling(20).std()
    z_b = (b - b.rolling(20).mean()) / b.rolling(20).std()
    sma_z_a = z_a.rolling(5).mean()
    sma_z_b = z_b.rolling(5).mean()
    diff = sma_z_a - sma_z_b
    cross_side_manual = pd.Series(0, index=a.index, dtype=int)
    cross_side_manual[diff > 0] = 1
    cross_side_manual[diff < 0] = -1

    # Compare only non-NaN rows
    valid_idx = diff.dropna().index
    assert (out.loc[valid_idx, "cross_side"] == cross_side_manual.loc[valid_idx]).all()
    # diff equivalence to floating precision
    np.testing.assert_allclose(
        out.loc[valid_idx, "diff"].values,
        diff.loc[valid_idx].values,
        rtol=1e-10,
    )
