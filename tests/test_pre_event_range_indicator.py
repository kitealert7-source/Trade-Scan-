"""
Unit tests for indicators/structure/pre_event_range.py

Covers:
  - Box correctly computed from N bars strictly before event_dt
  - Bars outside any event window receive NaN box / id 0
  - Bars inside an armed window receive broadcasted high/low
  - Insufficient pre-event bars → event skipped (NaN, id 0)
  - Lookahead safety: no bar at or after event_dt contributes to its box
  - Earliest-event-wins on overlap
  - Required columns enforced
"""
from __future__ import annotations

import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from indicators.macro.news_event_window import _EVENT_CACHE
from indicators.structure.pre_event_range import pre_event_range


def _make_calendar(tmpdir: Path, events: list[tuple]) -> Path:
    cal_dir = tmpdir / "research_calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    rows = ["datetime_utc,currency,impact,event,source"]
    for dt, ccy, imp, name in events:
        rows.append(f"{dt},{ccy},{imp},{name},test")
    (cal_dir / "cal.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return cal_dir


def _make_bars(times: list[str], highs: list[float], lows: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "high": highs,
        "low": lows,
    })


class TestBoxComputation(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _EVENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _EVENT_CACHE.clear()

    def test_box_uses_only_pre_event_bars(self):
        """Lookahead safety: bars at/after event_dt MUST NOT influence the box."""
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        # Pre-event bars (strictly before 13:30): highs 100..105, lows 99..104
        # Post-event bars (>= 13:30): highs 999, lows -999 — must be excluded
        bars = _make_bars(
            times=[
                "2026-01-05 13:00:00", "2026-01-05 13:05:00",
                "2026-01-05 13:10:00", "2026-01-05 13:15:00",
                "2026-01-05 13:20:00", "2026-01-05 13:25:00",
                "2026-01-05 13:30:00", "2026-01-05 13:35:00",
                "2026-01-05 13:40:00",
            ],
            highs=[100, 101, 102, 103, 104, 105, 999, 999, 999],
            lows=[99, 98, 97, 96, 95, 94, -999, -999, -999],
        )
        out = pre_event_range(bars, calendar_dir=cal, box_bars=6,
                              pre_min=15, post_min=15)
        # Bars in window (13:15 .. 13:45 exclusive end):
        #   13:15, 13:20, 13:25, 13:30, 13:35, 13:40
        in_win = out[out["armed_event_id"] != 0]
        self.assertEqual(len(in_win), 6)
        # Box: max(100..105) = 105, min(94..99) = 94
        # Critically NOT 999 / -999.
        for h, lo in zip(in_win["pre_event_high"], in_win["pre_event_low"]):
            self.assertEqual(h, 105.0)
            self.assertEqual(lo, 94.0)

    def test_outside_window_is_nan(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        bars = _make_bars(
            times=[
                "2026-01-05 12:00:00", "2026-01-05 12:30:00",
                "2026-01-05 13:00:00", "2026-01-05 13:05:00",
                "2026-01-05 13:10:00", "2026-01-05 13:15:00",
                "2026-01-05 13:20:00", "2026-01-05 13:25:00",
                "2026-01-05 14:00:00",  # post-window (event+30 = 14:00 boundary)
            ],
            highs=[100] * 9, lows=[99] * 9,
        )
        out = pre_event_range(bars, calendar_dir=cal, box_bars=6,
                              pre_min=15, post_min=15)
        # Bars at 12:00, 12:30, 13:00, 13:05, 13:10 are outside window
        # 13:15, 13:20, 13:25 are in window
        # 14:00 is outside (post end is 13:45, exclusive)
        outside_idx = [0, 1, 2, 3, 4, 8]
        for i in outside_idx:
            self.assertEqual(out["armed_event_id"].iloc[i], 0)
            self.assertTrue(math.isnan(out["pre_event_high"].iloc[i]))
            self.assertTrue(math.isnan(out["pre_event_low"].iloc[i]))

    def test_insufficient_pre_event_bars_skips_event(self):
        """Event with fewer than box_bars preceding bars → no box, id 0."""
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        # Only 3 bars before event_dt; box_bars=6 → can't form
        bars = _make_bars(
            times=[
                "2026-01-05 13:15:00", "2026-01-05 13:20:00",
                "2026-01-05 13:25:00", "2026-01-05 13:30:00",
                "2026-01-05 13:40:00",
            ],
            highs=[100] * 5, lows=[99] * 5,
        )
        out = pre_event_range(bars, calendar_dir=cal, box_bars=6,
                              pre_min=15, post_min=15)
        self.assertTrue((out["armed_event_id"] == 0).all())
        self.assertTrue(out["pre_event_high"].isna().all())

    def test_armed_event_id_matches_event_count(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
            ("2026-01-05 17:00:00", "USD", "High", "FOMC"),
        ])
        # Build enough bars that both events have a valid box.
        idx = pd.date_range("2026-01-05 12:00:00", "2026-01-05 18:00:00",
                             freq="5min", tz="UTC")
        bars = pd.DataFrame({
            "time": idx,
            "high": [100.0] * len(idx),
            "low": [99.0] * len(idx),
        })
        out = pre_event_range(bars, calendar_dir=cal, box_bars=6,
                              pre_min=15, post_min=15)
        ids = set(int(x) for x in out["armed_event_id"].unique() if x != 0)
        # Two armed events → two distinct non-zero ids
        self.assertEqual(len(ids), 2)

    def test_earliest_event_wins_on_overlap(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:00:00", "USD", "High", "EARLY"),
            ("2026-01-05 13:10:00", "USD", "High", "LATE"),
        ])
        # Plenty of bars before each event so both can form boxes.
        idx = pd.date_range("2026-01-05 11:00:00", "2026-01-05 14:00:00",
                             freq="5min", tz="UTC")
        bars = pd.DataFrame({
            "time": idx,
            "high": [100.0] * len(idx),
            "low": [99.0] * len(idx),
        })
        out = pre_event_range(bars, calendar_dir=cal, box_bars=6,
                              pre_min=15, post_min=15)
        # The bar at 13:05 is inside both events' windows — should bind to EARLY
        # (EARLY's window: 12:45-13:15; LATE's: 12:55-13:25 — so 13:05 is in both)
        bar_at_1305 = out[out["time"] == pd.Timestamp("2026-01-05 13:05:00", tz="UTC")]
        self.assertEqual(len(bar_at_1305), 1)
        self.assertEqual(bar_at_1305["pre_event_event_dt"].iloc[0],
                         pd.Timestamp("2026-01-05 13:00:00", tz="UTC"))


class TestBoundaryCrossIndicator(unittest.TestCase):
    """Regression: news_event_window and pre_event_range MUST agree on
    boundary semantics — both use [start, end) (left-inclusive, right-exclusive).

    A bar at exactly window_start is IN the window for both indicators.
    A bar at exactly window_end (event_dt + post_min) is OUT of the
    window for both indicators.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _EVENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _EVENT_CACHE.clear()

    def test_boundary_attribution_matches(self):
        from indicators.macro.news_event_window import news_event_window

        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        # Build a 5-min bar grid that includes BOTH boundaries explicitly:
        #   12:50, 12:55, 13:00, 13:05, 13:10, 13:15, ..., 13:45, 13:50
        # Window with pre=15, post=15 is [13:15, 13:45).
        idx = pd.date_range("2026-01-05 12:50:00",
                             "2026-01-05 13:55:00",
                             freq="5min", tz="UTC")
        bars = pd.DataFrame({
            "time": idx,
            "high": [100.0] * len(idx),
            "low": [99.0] * len(idx),
        })

        # Run both indicators with identical parameters.
        new_w = news_event_window(bars.copy(), calendar_dir=cal,
                                  pre_min=15, post_min=15,
                                  impact_filter="High")
        per = pre_event_range(bars.copy(), calendar_dir=cal,
                              box_bars=4,
                              pre_min=15, post_min=15,
                              impact_filter="High")

        # Compare on aligned timestamps.
        for ts, in_win, armed in zip(idx,
                                      new_w["news_in_window"],
                                      per["armed_event_id"] != 0):
            with self.subTest(ts=str(ts)):
                self.assertEqual(
                    bool(in_win), bool(armed),
                    f"Indicator disagreement at {ts}: "
                    f"news_in_window={in_win}, armed={armed}",
                )

        # Targeted boundary checks.
        ts_start = pd.Timestamp("2026-01-05 13:15:00", tz="UTC")  # ev_start
        ts_event = pd.Timestamp("2026-01-05 13:30:00", tz="UTC")  # ev_dt
        ts_end = pd.Timestamp("2026-01-05 13:45:00", tz="UTC")    # ev_end (exclusive)

        s_idx = bars.index[bars["time"] == ts_start][0]
        e_idx = bars.index[bars["time"] == ts_end][0]
        d_idx = bars.index[bars["time"] == ts_event][0]

        # Bar at window_start: IN for both (left-inclusive)
        self.assertTrue(new_w["news_in_window"].iloc[s_idx],
                        "news_event_window must INCLUDE bar at exact window_start")
        self.assertNotEqual(per["armed_event_id"].iloc[s_idx], 0,
                            "pre_event_range must INCLUDE bar at exact window_start")

        # Bar at exactly event_dt: IN for both, marked as in_post
        self.assertTrue(new_w["news_in_window"].iloc[d_idx])
        self.assertTrue(new_w["news_in_post"].iloc[d_idx])
        self.assertFalse(new_w["news_in_pre"].iloc[d_idx])
        self.assertNotEqual(per["armed_event_id"].iloc[d_idx], 0)

        # Bar at window_end: OUT for both (right-exclusive)
        self.assertFalse(new_w["news_in_window"].iloc[e_idx],
                         "news_event_window must EXCLUDE bar at exact window_end")
        self.assertEqual(per["armed_event_id"].iloc[e_idx], 0,
                         "pre_event_range must EXCLUDE bar at exact window_end")


class TestInputContract(unittest.TestCase):

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"time": pd.to_datetime(["2026-01-05 13:00:00"], utc=True),
                           "close": [100.0]})
        with self.assertRaises(ValueError):
            pre_event_range(df, calendar_dir=Path("nonexistent"))

    def test_empty_df(self):
        df = pd.DataFrame(columns=["time", "high", "low"])
        out = pre_event_range(df, calendar_dir=Path("nonexistent"))
        self.assertEqual(len(out), 0)
        self.assertIn("pre_event_high", out.columns)
        self.assertIn("armed_event_id", out.columns)


if __name__ == "__main__":
    unittest.main()
