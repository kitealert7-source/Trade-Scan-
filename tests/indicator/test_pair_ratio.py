"""Unit tests — indicators/stats/pair_ratio.py (synthetic RV ratio)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.stats.pair_ratio import pair_ratio


def _legs(n: int = 100, seed: int = 5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    gold = pd.Series(2000 + np.cumsum(rng.normal(0, 5, n)), index=idx)
    silver = pd.Series(25 + np.cumsum(rng.normal(0, 0.2, n)), index=idx)
    return gold, silver


def test_basic_ratio_values():
    gold, silver = _legs()
    out = pair_ratio(gold, silver)
    assert out.index.equals(gold.index)
    pd.testing.assert_series_equal(out, gold / silver)
    assert (out.dropna() > 0).all()


def test_strict_raises_on_mismatch():
    gold, silver = _legs()
    with pytest.raises(ValueError, match="strict"):
        pair_ratio(gold, silver.iloc[:-5])


def test_inner_alignment_explicit():
    gold, silver = _legs()
    out = pair_ratio(gold, silver.iloc[:-5], align="inner")
    assert len(out) == len(gold) - 5
    assert out.index.equals(silver.iloc[:-5].index)


def test_inner_no_overlap_raises():
    gold, _ = _legs()
    other = pd.Series(
        [1.0, 2.0], index=pd.date_range("2030-01-01", periods=2, freq="D")
    )
    with pytest.raises(ValueError, match="no overlapping"):
        pair_ratio(gold, other, align="inner")


def test_zero_denominator_guard():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    num = pd.Series([10.0, 10.0, 10.0], index=idx)
    den = pd.Series([2.0, 0.0, 5.0], index=idx)
    out = pair_ratio(num, den)
    assert out.iloc[0] == 5.0
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0


def test_bad_align_raises_and_inputs_not_mutated():
    gold, silver = _legs()
    g_snap, s_snap = gold.copy(deep=True), silver.copy(deep=True)
    with pytest.raises(ValueError, match="align"):
        pair_ratio(gold, silver, align="outer")
    pair_ratio(gold, silver)
    pd.testing.assert_series_equal(gold, g_snap)
    pd.testing.assert_series_equal(silver, s_snap)
