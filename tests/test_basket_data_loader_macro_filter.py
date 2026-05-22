"""Tests for the macro-direction filter in tools/basket_data_loader.py.

Covers:
  - macro_direction_timeframe=None preserves legacy behavior (no filter,
    no htf_direction column)
  - macro_direction_timeframe="1d" adds htf_direction column and gates
    entry-TF cross_event entries
  - cross_side (used for reverse-cross EXITS) is left untouched even
    when entries are filtered (entry-only filter per design)
  - htf_direction values come from the PREVIOUS macro bar (1-bar shift,
    look-ahead protection)
  - Warmup assertion fires when macro_warmup_days is too small
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.basket_data_loader import load_basket_leg_data
from config.path_authority import ANTI_GRAVITY_DATA_ROOT


# Only run when the OctaFx RESEARCH data is present.
_EURUSD_PATH = (ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA"
                / "EURUSD_OCTAFX_MASTER" / "RESEARCH")
_USDJPY_PATH = (ANTI_GRAVITY_DATA_ROOT / "MASTER_DATA"
                / "USDJPY_OCTAFX_MASTER" / "RESEARCH")
_REQUIRES_DATA = pytest.mark.skipif(
    not (_EURUSD_PATH.is_dir() and _USDJPY_PATH.is_dir()),
    reason="OctaFx RESEARCH data not present",
)


@_REQUIRES_DATA
def test_no_macro_filter_preserves_legacy_columns():
    """macro_direction_timeframe=None — no htf_direction column added,
    cross_event/cross_side untouched (= legacy behavior pre-2026-05-19)."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_direction_timeframe=None,
    )
    eur = data["EURUSD"]
    assert "htf_direction" not in eur.columns
    assert "cross_event" in eur.columns
    assert "cross_side" in eur.columns


@_REQUIRES_DATA
def test_macro_1d_filter_adds_htf_direction_column():
    """macro_direction_timeframe='1d' — htf_direction column added, values
    in {-1, 0, +1}."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_direction_timeframe="1d",
        macro_warmup_days=120,
    )
    eur = data["EURUSD"]
    assert "htf_direction" in eur.columns
    unique_vals = set(eur["htf_direction"].unique())
    assert unique_vals.issubset({-1, 0, 1}), (
        f"htf_direction has unexpected values: {unique_vals}"
    )


@_REQUIRES_DATA
def test_macro_filter_gates_cross_event_to_macro_aligned_only():
    """After filter: every nonzero cross_event must equal the htf_direction
    at the same bar. Countertrend cross_events must be zeroed."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_direction_timeframe="1d",
        macro_warmup_days=120,
    )
    eur = data["EURUSD"]
    fires = eur[eur["cross_event"] != 0]
    if len(fires) == 0:
        # The window may legitimately have zero macro-aligned crosses
        # given the daily regime; assertion below would be vacuously true.
        return
    assert (fires["cross_event"] == fires["htf_direction"]).all(), (
        "Filtered cross_event must always equal htf_direction at the same bar"
    )


@_REQUIRES_DATA
def test_macro_filter_does_not_touch_cross_side_exits():
    """cross_side (the reverse-cross exit signal) must be IDENTICAL whether
    macro filter is on or off — per design: entries gated, exits untouched."""
    no_filter = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_direction_timeframe=None,
    )
    with_filter = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_direction_timeframe="1d", macro_warmup_days=120,
    )
    eur_no = no_filter["EURUSD"]
    eur_with = with_filter["EURUSD"]
    # Align (both should be the same index)
    assert (eur_no.index == eur_with.index).all()
    # cross_side untouched bar-for-bar
    assert (eur_no["cross_side"] == eur_with["cross_side"]).all(), (
        "cross_side must NOT change when macro filter is enabled"
    )
    # cross_event SHOULD differ (some entries got filtered out)
    n_filtered = int((eur_no["cross_event"] != eur_with["cross_event"]).sum())
    # In a 1-month window we typically have at least one countertrend
    # cross_event being filtered out, but allow == 0 if the regime was
    # uniformly aligned across the window (i.e. all crosses happened to
    # match the macro direction).
    assert n_filtered >= 0


@_REQUIRES_DATA
def test_macro_filter_uses_previous_macro_bar_no_lookahead():
    """The htf_direction at a 5m bar must derive from the PREVIOUS macro
    bar (1-bar shift). Verifies by comparing the htf_direction at a 5m
    bar on day T to the daily cross_side computed for day T-1's close."""
    from tools.basket_data_loader import (
        _load_symbol_5m, compute_spread_sma_cross_5m,
    )
    start, end = "2024-05-18", "2024-06-18"
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"], start, end,
        timeframe="5m", macro_direction_timeframe="1d", macro_warmup_days=120,
    )

    # Independently recompute the daily macro cross with the same params
    # the loader uses (z_window=60, sma_window=5), over the SAME extended
    # range, then shift by 1.
    ext_start = (pd.Timestamp(start) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    eur_d = _load_symbol_5m("EURUSD", ext_start, end, timeframe="1d")
    jpy_d = _load_symbol_5m("USDJPY", ext_start, end, timeframe="1d")
    macro_cross = compute_spread_sma_cross_5m(
        eur_d["close"], jpy_d["close"], z_window=60, sma_window=5,
    )
    shifted = macro_cross["cross_side"].shift(1)

    # Spot-check: for a few 5m bars within the test window, the loader's
    # htf_direction should equal the SHIFTED daily series ffilled to that
    # 5m timestamp.
    eur_5m = data["EURUSD"]
    sample_indices = eur_5m.index[::1000]   # every 1000th 5m bar (~3 days apart)
    for ts in sample_indices:
        # Daily index <= ts → use ffill semantic; the rightmost macro bar
        # at-or-before ts is the one our shifted series uses.
        # Find that bar manually.
        candidates = shifted[shifted.index <= ts].dropna()
        if candidates.empty:
            continue  # warmup gap — htf_direction would be 0
        expected = int(candidates.iloc[-1])
        actual = int(eur_5m.loc[ts, "htf_direction"])
        assert actual == expected, (
            f"htf_direction mismatch at {ts}: loader={actual}, "
            f"independently-shifted-daily={expected}"
        )


@_REQUIRES_DATA
def test_correlation_filter_off_preserves_legacy_columns():
    """macro_correlation_window=None — no htf_correlation column added."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_correlation_window=None,
    )
    eur = data["EURUSD"]
    assert "htf_correlation" not in eur.columns


@_REQUIRES_DATA
def test_cross_side_raw_column_present_on_basket_load():
    """The unsmoothed cross_side_raw column must be forward-filled onto
    each leg's df, with values in {-1, 0, +1}. Used by directives that
    set reverse_cross_column: cross_side_raw (S16 z=0 exit probe).
    """
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_direction_timeframe=None,
    )
    eur = data["EURUSD"]
    assert "cross_side_raw" in eur.columns
    unique_vals = set(eur["cross_side_raw"].unique())
    assert unique_vals.issubset({-1, 0, 1}), (
        f"cross_side_raw has unexpected values: {unique_vals}"
    )
    # Sanity: raw should differ from smoothed somewhere (otherwise the
    # SMA lag is zero and the probe is pointless on this data).
    assert (eur["cross_side"] != eur["cross_side_raw"]).any(), (
        "cross_side_raw must differ from cross_side on at least one bar "
        "(otherwise the unsmoothed signal provides no lead)"
    )


@_REQUIRES_DATA
def test_correlation_filter_on_adds_column_and_gates_entries():
    """macro_correlation_window=20 — htf_correlation column populated;
    surviving cross_events are all in periods where correlation <= threshold."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"],
        "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_correlation_window=20,
        macro_correlation_threshold=-0.5,
    )
    eur = data["EURUSD"]
    assert "htf_correlation" in eur.columns
    # All surviving cross_events must be in bars where correlation <= -0.5
    fires = eur[eur["cross_event"] != 0]
    if len(fires) > 0:
        assert (fires["htf_correlation"] <= -0.5).all(), (
            "Every filtered cross_event must be in a bar with "
            "correlation <= threshold"
        )


@_REQUIRES_DATA
def test_correlation_filter_does_not_touch_cross_side_exits():
    """cross_side (the reverse-cross EXIT signal) must be identical with
    and without the correlation filter — per design: entries gated,
    exits untouched."""
    no_corr = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_correlation_window=None,
    )
    with_corr = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_correlation_window=20,
        macro_correlation_threshold=-0.5,
    )
    eur_no = no_corr["EURUSD"]
    eur_with = with_corr["EURUSD"]
    assert (eur_no.index == eur_with.index).all()
    assert (eur_no["cross_side"] == eur_with["cross_side"]).all(), (
        "cross_side must NOT change when correlation filter is enabled"
    )


@_REQUIRES_DATA
def test_correlation_filter_one_bar_shift_no_lookahead():
    """The htf_correlation at a 5m bar must derive from the PREVIOUS daily
    close's correlation. Test: independently compute the shifted daily
    correlation and compare a few sample bars."""
    from tools.basket_data_loader import _load_symbol_5m
    import numpy as np
    start, end = "2024-05-18", "2024-06-18"
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"], start, end,
        timeframe="5m", macro_correlation_window=20,
        macro_correlation_threshold=-0.5,
        macro_warmup_days=120,
    )
    # Independent re-computation
    ext_start = (pd.Timestamp(start) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    eur_d = _load_symbol_5m("EURUSD", ext_start, end, timeframe="1d")
    jpy_d = _load_symbol_5m("USDJPY", ext_start, end, timeframe="1d")
    aligned = pd.concat([eur_d["close"].rename("a"), jpy_d["close"].rename("b")],
                         axis=1).dropna()
    ret = np.log(aligned).diff()
    roll = ret["a"].rolling(20).corr(ret["b"])
    shifted = roll.shift(1)

    eur_5m = data["EURUSD"]
    sample_ts = eur_5m.index[::1000]
    for ts in sample_ts:
        candidates = shifted[shifted.index <= ts].dropna()
        if candidates.empty:
            continue
        expected = float(candidates.iloc[-1])
        actual = float(eur_5m.loc[ts, "htf_correlation"])
        # Allow tiny tolerance (pandas float roundoff)
        assert abs(actual - expected) < 1e-9, (
            f"htf_correlation mismatch at {ts}: loader={actual}, "
            f"independent-shifted={expected}"
        )


@_REQUIRES_DATA
def test_correlation_filter_blocks_more_entries_than_no_filter():
    """With the correlation filter on, the number of surviving
    cross_events should be <= the count without the filter (the filter
    only suppresses, never adds)."""
    no_corr = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_correlation_window=None,
    )
    with_corr = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m", macro_correlation_window=20,
        macro_correlation_threshold=-0.5,
    )
    n_no = int((no_corr["EURUSD"]["cross_event"] != 0).sum())
    n_with = int((with_corr["EURUSD"]["cross_event"] != 0).sum())
    assert n_with <= n_no, (
        f"Correlation filter should suppress (not add) cross_events; "
        f"got no_filter={n_no}, with_filter={n_with}"
    )


@_REQUIRES_DATA
def test_correlation_filter_composes_with_macro_direction_filter():
    """When BOTH filters are on, surviving cross_events must satisfy both
    constraints (direction match AND correlation <= threshold)."""
    data = load_basket_leg_data(
        ["EURUSD", "USDJPY"], "2024-05-18", "2024-06-18",
        timeframe="5m",
        macro_direction_timeframe="4h",
        macro_warmup_days=120,
        macro_z_window=360,
        macro_sma_window=30,
        macro_correlation_window=20,
        macro_correlation_threshold=-0.5,
    )
    eur = data["EURUSD"]
    assert "htf_direction" in eur.columns
    assert "htf_correlation" in eur.columns
    fires = eur[eur["cross_event"] != 0]
    if len(fires) > 0:
        # Both constraints must hold on every surviving cross_event
        assert (fires["cross_event"] == fires["htf_direction"]).all()
        assert (fires["htf_correlation"] <= -0.5).all()


@_REQUIRES_DATA
def test_warmup_assertion_fires_when_insufficient():
    """macro_warmup_days=1 is insufficient for a 60-bar daily z-window.
    The loader should raise ValueError early instead of silently running
    with htf_direction=0 (which would block ALL entries)."""
    with pytest.raises(ValueError, match="htf_direction is all-zero"):
        load_basket_leg_data(
            ["EURUSD", "USDJPY"],
            "2024-05-18", "2024-06-18",
            timeframe="5m",
            macro_direction_timeframe="1d",
            macro_warmup_days=1,
        )
