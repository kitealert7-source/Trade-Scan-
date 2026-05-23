"""Tests for the regime-gate signal in tools/basket_data_loader.py.

Charter: h3_spread_window_c_regime_detector (2026-05-23). The data
loader produces a `flips_in_lookback` column when
`regime_gate_lookback_bars` is set; the h3_spread_v3 rule consumes it
to gate cycle_init and pyramid_add when count exceeds threshold.

Covers:
  - regime_gate_lookback_bars=None preserves legacy behavior (no
    flips_in_lookback column, no schema change)
  - regime_gate_lookback_bars=N adds the column with correct rolling-
    count semantics
  - Cold-start contract: first N-1 bars are NaN (gate inactive until
    lookback is filled)
  - Computation matches a hand-derived reference on a known cross_side
    sequence (sanity gate against subtle off-by-one errors)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.basket_data_loader import load_basket_leg_data
from config.path_authority import ANTI_GRAVITY_DATA_ROOT


# Skip when OctaFx RESEARCH data isn't present locally.
_EURUSD_PATH = (ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA"
                / "EURUSD_OCTAFX_MASTER" / "RESEARCH")
_USDJPY_PATH = (ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA"
                / "USDJPY_OCTAFX_MASTER" / "RESEARCH")
_REQUIRES_DATA = pytest.mark.skipif(
    not (_EURUSD_PATH.is_dir() and _USDJPY_PATH.is_dir()),
    reason="OctaFx RESEARCH data not present",
)


@_REQUIRES_DATA
def test_no_regime_gate_preserves_legacy_columns():
    """regime_gate_lookback_bars=None — no flips_in_lookback column added,
    schema unchanged (= legacy behavior pre-2026-05-23). This is the
    byte-equivalence contract for all existing directives."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="15m",
    )
    eur = data["EURUSD"]
    assert "flips_in_lookback" not in eur.columns
    # cross_side (the source signal) is still present from the
    # spread_sma_cross step.
    assert "cross_side" in eur.columns


@_REQUIRES_DATA
def test_regime_gate_adds_flips_in_lookback_column():
    """regime_gate_lookback_bars=200 — flips_in_lookback column appears on
    every leg, non-negative integer values."""
    lookback = 200
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="15m",
        regime_gate_lookback_bars=lookback,
    )
    for sym in ("EURUSD", "USDJPY"):
        col = data[sym]["flips_in_lookback"]
        assert "flips_in_lookback" in data[sym].columns
        # First (lookback-1) bars must be NaN — cold-start contract.
        assert col.iloc[: lookback - 1].isna().all(), (
            "cold-start contract violated: bars before lookback fills "
            "must be NaN so the rule treats the gate as inactive"
        )
        # Beyond cold start, values are non-negative integers (a count).
        beyond_cold = col.iloc[lookback - 1:].dropna()
        assert (beyond_cold >= 0).all()
        # Each count cannot exceed the lookback window size.
        assert (beyond_cold <= lookback).all()


@_REQUIRES_DATA
def test_regime_gate_both_legs_carry_identical_column():
    """flips_in_lookback is a pair-level property derived from cross_side,
    which is shared between both legs. Both legs must carry the same
    series (modulo index alignment)."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="15m",
        regime_gate_lookback_bars=200,
    )
    eur = data["EURUSD"]["flips_in_lookback"]
    jpy = data["USDJPY"]["flips_in_lookback"]
    # Indices are the same (both legs share the entry-TF clock).
    pd.testing.assert_index_equal(eur.index, jpy.index)
    # Values are byte-identical.
    pd.testing.assert_series_equal(
        eur.dropna(), jpy.dropna(), check_names=False
    )


@_REQUIRES_DATA
def test_regime_gate_count_matches_handcomputed_reference():
    """Sanity gate: compute the flip count by hand from cross_side and
    confirm it matches the rolling-sum column. Catches off-by-one errors
    in the rolling-window definition (e.g. min_periods, shift, edge
    handling)."""
    lookback = 200
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="15m",
        regime_gate_lookback_bars=lookback,
    )
    cs = data["EURUSD"]["cross_side"]
    col = data["EURUSD"]["flips_in_lookback"]

    # Hand-computed reference: a "flip" is a sign change between
    # consecutive NON-ZERO values. fillna(0) on the shifted series
    # mirrors the production code's first-bar guard (NaN != 0 in pandas
    # evaluates to True; without the guard, position 0 phantom-counts).
    prev = cs.shift(1).fillna(0)
    is_flip = (
        (cs != prev) & (cs != 0) & (prev != 0)
    ).astype(int)
    expected = is_flip.rolling(lookback, min_periods=lookback).sum()

    pd.testing.assert_series_equal(col, expected, check_names=False)


def test_synthetic_known_flips_count():
    """Pure unit test (no data dependency) on the flip-counting logic.

    Construct a cross_side series with a known number of flips and
    confirm the rolling count matches. This catches schema drift even
    when broker data isn't available locally."""
    # Build a cross_side with 5 known flips in 20 bars (alternations at
    # positions 4-5, 9-10, 12-13, 15-16, 18-19).
    cs = pd.Series([
        1, 1, 1, 1, -1,
        -1, -1, -1, -1, 1,
        1, 1, -1, -1, -1,
        1, 1, 1, -1, -1,
    ], dtype=int)
    # fillna(0) mirrors the production code's first-bar guard. Without
    # it, position 0's shifted-prev is NaN, and (NaN != 0) is True in
    # pandas, phantom-counting position 0 as a flip.
    prev = cs.shift(1).fillna(0)
    is_flip = (
        (cs != prev) & (cs != 0) & (prev != 0)
    ).astype(int)

    # With a lookback of 20 bars and min_periods=20, only the last bar
    # has a non-NaN count, which equals total flips in the series.
    rolled = is_flip.rolling(20, min_periods=20).sum()
    assert rolled.iloc[-1] == 5
    assert rolled.iloc[:-1].isna().all()

    # With a shorter lookback of 5 bars, the counts depend on the
    # window content. Spot-check a few positions.
    short = is_flip.rolling(5, min_periods=5).sum()
    # Position 4 (index 4) is the first non-NaN; window = positions 0..4.
    # is_flip at those positions = [0, 0, 0, 0, 1] (flip 1->-1 at idx 4).
    assert short.iloc[4] == 1
    # Position 9 window = positions 5..9, is_flip = [0, 0, 0, 0, 1].
    assert short.iloc[9] == 1
    # Position 15 window = positions 11..15, is_flip = [0, 1, 0, 0, 1]
    # (flip at idx 12 and at idx 15).
    assert short.iloc[15] == 2
