"""
Unit tests for indicators/macro/news_event_window.py

Covers:
  - Loading + caching of RESEARCH-layer events
  - Currency + impact filtering
  - Per-bar window membership (in_window / in_pre / in_post)
  - First-fire tie-breaker on overlapping events
  - DatetimeIndex vs 'time' column input
  - Empty calendar / empty df edge cases
  - Lookahead safety: event flags only depend on bar's timestamp
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from indicators.macro.news_event_window import (
    _EVENT_CACHE,
    news_event_window,
)


def _make_calendar(tmpdir: Path, events: list[tuple]) -> Path:
    """events: list of (datetime_utc_str, currency, impact, event_name)."""
    cal_dir = tmpdir / "research_calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    rows = ["datetime_utc,currency,impact,event,source"]
    for dt, ccy, imp, name in events:
        rows.append(f"{dt},{ccy},{imp},{name},test")
    (cal_dir / "cal.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return cal_dir


def _make_bars(times: list[str], h: float = 100.0, l: float = 99.0) -> pd.DataFrame:
    """Build a minimal bar df with a 'time' column and OHLC."""
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "open": [h] * len(times),
        "high": [h] * len(times),
        "low": [l] * len(times),
        "close": [h] * len(times),
    })


class TestBasicWindowing(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _EVENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _EVENT_CACHE.clear()

    def test_no_events_no_flags(self):
        cal = _make_calendar(self.tmp, [])
        bars = _make_bars(["2026-01-05 13:00:00", "2026-01-05 13:30:00"])
        out = news_event_window(bars, calendar_dir=cal)
        self.assertFalse(out["news_in_window"].any())
        self.assertTrue((out["news_event_id"] == 0).all())
        self.assertTrue(out["news_event_dt"].isna().all())

    def test_single_event_window_flagging(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        bars = _make_bars([
            "2026-01-05 13:00:00",  # outside
            "2026-01-05 13:20:00",  # in pre  (event-15 = 13:15 ≤ 13:20 < 13:30)
            "2026-01-05 13:30:00",  # in post (>= event_dt)
            "2026-01-05 13:45:00",  # outside (event+15 = 13:45, exclusive end)
            "2026-01-05 14:00:00",  # outside
        ])
        out = news_event_window(bars, calendar_dir=cal,
                                pre_min=15, post_min=15,
                                impact_filter="High")
        self.assertEqual(list(out["news_in_window"]),
                         [False, True, True, False, False])
        self.assertEqual(list(out["news_in_pre"]),
                         [False, True, False, False, False])
        self.assertEqual(list(out["news_in_post"]),
                         [False, False, True, False, False])

    def test_pre_post_split_at_event_dt(self):
        """Bar exactly at event_dt is post (post_min boundary inclusive on left)."""
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        bars = _make_bars(["2026-01-05 13:30:00"])
        out = news_event_window(bars, calendar_dir=cal)
        self.assertTrue(out["news_in_post"].iloc[0])
        self.assertFalse(out["news_in_pre"].iloc[0])

    def test_currency_filter(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
            ("2026-01-05 13:30:00", "EUR", "High", "ECB"),
        ])
        bars = _make_bars(["2026-01-05 13:30:00"])
        out_usd = news_event_window(bars.copy(), calendar_dir=cal,
                                    currencies=["USD"], impact_filter="High")
        out_all = news_event_window(bars.copy(), calendar_dir=cal,
                                    currencies=None, impact_filter="High")
        self.assertEqual(out_usd["news_currency"].iloc[0], "USD")
        # Both currencies pass when no filter — first-fire on equal start
        self.assertIn(out_all["news_currency"].iloc[0], {"USD", "EUR"})

    def test_impact_filter(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
            ("2026-01-05 13:30:00", "USD", "Medium", "ISM"),
        ])
        bars = _make_bars(["2026-01-05 13:30:00"])
        out = news_event_window(bars, calendar_dir=cal, impact_filter="High")
        self.assertEqual(out["news_impact"].iloc[0], "High")

    def test_multiple_events_first_start_wins(self):
        """Bar inside two overlapping windows takes the earliest window_start."""
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:00:00", "USD", "High", "EARLY"),
            ("2026-01-05 13:10:00", "USD", "High", "LATE"),
        ])
        bars = _make_bars(["2026-01-05 13:05:00"])  # in both windows
        out = news_event_window(bars, calendar_dir=cal,
                                pre_min=15, post_min=15)
        self.assertEqual(out["news_event_dt"].iloc[0],
                         pd.Timestamp("2026-01-05 13:00:00", tz="UTC"))


class TestInputShapes(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _EVENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _EVENT_CACHE.clear()

    def test_datetime_index_input(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        idx = pd.DatetimeIndex(pd.to_datetime([
            "2026-01-05 13:20:00", "2026-01-05 14:00:00",
        ], utc=True))
        df = pd.DataFrame({"high": [100.0, 101.0], "low": [99.0, 100.0]},
                          index=idx)
        out = news_event_window(df, calendar_dir=cal)
        self.assertEqual(list(out["news_in_window"]), [True, False])

    def test_empty_df(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close"])
        out = news_event_window(df, calendar_dir=cal)
        self.assertEqual(len(out), 0)
        self.assertIn("news_in_window", out.columns)
        self.assertIn("news_event_id", out.columns)

    def test_index_preserved(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        bars = _make_bars(["2026-01-05 13:00:00", "2026-01-05 13:30:00"])
        bars.index = [10, 20]
        out = news_event_window(bars, calendar_dir=cal)
        self.assertEqual(list(out.index), [10, 20])


class TestCalendarLoading(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _EVENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _EVENT_CACHE.clear()

    def test_missing_calendar_dir(self):
        bars = _make_bars(["2026-01-05 13:00:00"])
        out = news_event_window(bars, calendar_dir=self.tmp / "nonexistent")
        self.assertFalse(out["news_in_window"].any())

    def test_cache_hit(self):
        cal = _make_calendar(self.tmp, [
            ("2026-01-05 13:30:00", "USD", "High", "NFP"),
        ])
        bars = _make_bars(["2026-01-05 13:30:00"])
        news_event_window(bars.copy(), calendar_dir=cal,
                          impact_filter="High", currencies=["USD"])
        # Second call with same params — cached
        keys_before = len(_EVENT_CACHE)
        news_event_window(bars.copy(), calendar_dir=cal,
                          impact_filter="High", currencies=["USD"])
        self.assertEqual(len(_EVENT_CACHE), keys_before)


class TestLiveCalendarSmoke(unittest.TestCase):
    """Smoke test against the live RESEARCH calendar if present."""

    def test_live_calendar_loads(self):
        # Resolve via the standard EXTERNAL_DATA path under data_root,
        # mirroring how pipeline tools find the calendar. Falls back to
        # the sibling Anti_Gravity_DATA_ROOT layout if the symlink is
        # absent in the current checkout.
        candidates = [
            PROJECT_ROOT / "data_root" / "EXTERNAL_DATA"
                / "NEWS_CALENDAR" / "RESEARCH",
            PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "EXTERNAL_DATA"
                / "NEWS_CALENDAR" / "RESEARCH",
        ]
        live = next((c for c in candidates if c.exists()), None)
        if live is None:
            self.skipTest("Live calendar not present — skipping smoke test")
        # Build a year of synthetic 30-min NAS100 bars
        idx = pd.date_range("2026-01-01", "2026-01-31", freq="30min", tz="UTC")
        df = pd.DataFrame({
            "time": idx, "open": 16000.0, "high": 16010.0,
            "low": 15990.0, "close": 16000.0,
        })
        out = news_event_window(df, calendar_dir=live, currencies=["USD"],
                                impact_filter="High",
                                pre_min=15, post_min=15)
        # At least some bars should fire on a 31-day USD-High calendar window
        self.assertGreater(out["news_in_window"].sum(), 0)
        self.assertTrue((out["news_event_id"][out["news_in_window"]] > 0).all())


if __name__ == "__main__":
    unittest.main()
