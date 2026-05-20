"""test_cointegration_meanrev_leg_strategy.py — C3 leg-strategy tests.

Unit-tests CointMeanRevLegStrategy without engine / basket_runner
dependency. Uses a stub ctx that mimics ContextView's `.get(col, default)`
interface.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.recycle_strategies import CointMeanRevLegStrategy


# ---------------------------------------------------------------------------
# Lightweight ctx stub
# ---------------------------------------------------------------------------


class _StubCtx:
    """Mimics ContextView's per-bar API: ctx.get(col, default)."""
    def __init__(self, **fields):
        self._fields = fields

    def get(self, name, default=None):
        return self._fields.get(name, default)


def _strategy(**overrides) -> CointMeanRevLegStrategy:
    defaults = dict(
        symbol="EURUSD",
        position_direction=+1,
        watch_direction=0,        # bidirectional by default for tests
        entry_z=2.0,
    )
    defaults.update(overrides)
    return CointMeanRevLegStrategy(**defaults)


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------


class TestParamValidation:

    def test_valid_params_construct_ok(self):
        s = CointMeanRevLegStrategy(symbol="EURUSD", position_direction=+1)
        assert s.entry_z == 2.0
        assert s.watch_direction == 0

    def test_bad_position_direction_raises(self):
        with pytest.raises(ValueError, match="position_direction"):
            CointMeanRevLegStrategy("EURUSD", position_direction=0)
        with pytest.raises(ValueError, match="position_direction"):
            CointMeanRevLegStrategy("EURUSD", position_direction=2)

    def test_bad_watch_direction_raises(self):
        with pytest.raises(ValueError, match="watch_direction"):
            CointMeanRevLegStrategy("EURUSD", position_direction=+1, watch_direction=2)

    def test_zero_or_negative_entry_z_raises(self):
        with pytest.raises(ValueError, match="entry_z"):
            CointMeanRevLegStrategy("EURUSD", +1, entry_z=0)
        with pytest.raises(ValueError, match="entry_z"):
            CointMeanRevLegStrategy("EURUSD", +1, entry_z=-1)


# ---------------------------------------------------------------------------
# prepare_indicators column check
# ---------------------------------------------------------------------------


class TestPrepareIndicators:

    def test_passes_when_columns_present(self):
        s = _strategy()
        df = pd.DataFrame({"close": [1.0], "intra_z": [0.5], "qualified_daily": [True]})
        out = s.prepare_indicators(df)
        assert out is df

    def test_raises_when_columns_missing(self):
        s = _strategy()
        df = pd.DataFrame({"close": [1.0]})   # missing intra_z + qualified_daily
        with pytest.raises(RuntimeError, match="missing required columns"):
            s.prepare_indicators(df)


# ---------------------------------------------------------------------------
# Entry detection — bidirectional mode
# ---------------------------------------------------------------------------


class TestEntryBidirectional:

    def test_no_entry_on_first_bar(self):
        """First bar has no prev_z → cannot detect a crossing."""
        s = _strategy()
        ctx = _StubCtx(intra_z=2.5, qualified_daily=True)
        assert s.check_entry(ctx) is None

    def test_entry_on_fresh_crossing_above(self):
        s = _strategy()
        # Bar 1: below threshold (prep prev_z)
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True))
        # Bar 2: crosses up
        result = s.check_entry(_StubCtx(intra_z=2.3, qualified_daily=True))
        assert result == {"signal": +1}

    def test_entry_on_fresh_crossing_below(self):
        """Bidirectional: negative z crossing also fires."""
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=-1.5, qualified_daily=True))
        result = s.check_entry(_StubCtx(intra_z=-2.3, qualified_daily=True))
        assert result == {"signal": +1}

    def test_no_entry_on_continued_hold(self):
        """|z| already above threshold on prev → not a fresh crossing."""
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=True))   # warm prev
        s.check_entry(_StubCtx(intra_z=2.7, qualified_daily=True))   # crosses (none, no prev)
        # Wait — first call has prev=None, returns None. Second call sees
        # prev=2.5 ≥ 2.0 → NOT a fresh crossing (|prev|>=entry_z fails the test).
        # Third call extends — also not a fresh crossing.
        result = s.check_entry(_StubCtx(intra_z=2.8, qualified_daily=True))
        assert result is None

    def test_no_entry_when_below_threshold(self):
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=1.0, qualified_daily=True))
        assert s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True)) is None


# ---------------------------------------------------------------------------
# Qualification gate
# ---------------------------------------------------------------------------


class TestQualificationGate:

    def test_no_entry_when_not_qualified(self):
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=False))
        result = s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=False))
        assert result is None

    def test_no_entry_qualified_missing(self):
        """Missing qualified column defaults to False → no entry."""
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=1.5))
        result = s.check_entry(_StubCtx(intra_z=2.5))
        assert result is None


# ---------------------------------------------------------------------------
# Direction filter (watch_direction)
# ---------------------------------------------------------------------------


class TestDirectionFilter:

    def test_watch_positive_only_blocks_negative_crossing(self):
        s = _strategy(watch_direction=+1)
        s.check_entry(_StubCtx(intra_z=-1.5, qualified_daily=True))
        result = s.check_entry(_StubCtx(intra_z=-2.5, qualified_daily=True))
        assert result is None

    def test_watch_positive_only_allows_positive_crossing(self):
        s = _strategy(watch_direction=+1)
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True))
        result = s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=True))
        assert result == {"signal": +1}

    def test_watch_negative_only_allows_negative_crossing(self):
        s = _strategy(watch_direction=-1)
        s.check_entry(_StubCtx(intra_z=-1.5, qualified_daily=True))
        result = s.check_entry(_StubCtx(intra_z=-2.5, qualified_daily=True))
        assert result == {"signal": +1}


# ---------------------------------------------------------------------------
# Position direction returned in signal
# ---------------------------------------------------------------------------


class TestSignalDirection:

    def test_position_direction_passes_through_signal(self):
        s = _strategy(position_direction=-1)
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True))
        result = s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=True))
        assert result == {"signal": -1}


# ---------------------------------------------------------------------------
# NaN / data-gap handling
# ---------------------------------------------------------------------------


class TestNanHandling:

    def test_nan_resets_prev_z(self):
        """A NaN intra_z must clear prev_z so a stale crossing isn't
        synthesized when valid data resumes."""
        s = _strategy()
        # Bar 1: valid below
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True))
        # Bar 2: NaN (data gap)
        s.check_entry(_StubCtx(intra_z=float("nan"), qualified_daily=True))
        # Bar 3: valid above — but prev_z was reset, so first valid bar
        # after the gap cannot trigger entry (need TWO consecutive valid
        # bars to assess the crossing)
        result = s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=True))
        assert result is None

    def test_recovery_after_nan_takes_two_bars(self):
        s = _strategy()
        s.check_entry(_StubCtx(intra_z=float("nan"), qualified_daily=True))
        s.check_entry(_StubCtx(intra_z=1.5, qualified_daily=True))   # rebuild prev
        result = s.check_entry(_StubCtx(intra_z=2.5, qualified_daily=True))
        assert result == {"signal": +1}


# ---------------------------------------------------------------------------
# check_exit always False (rule owns exits)
# ---------------------------------------------------------------------------


class TestCheckExit:

    def test_check_exit_always_false(self):
        s = _strategy()
        ctx = _StubCtx(intra_z=2.5, qualified_daily=True)
        assert s.check_exit(ctx) is False
