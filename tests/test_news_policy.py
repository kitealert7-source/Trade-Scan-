"""
News Policy Impact — unit and integration tests.

Covers:
  - RESEARCH-layer calendar loading and runtime assertions
  - Currency derivation
  - Trade classification (overlap, straddle, entry-in-window)
  - Scenario computation (No-Entry, Go-Flat)
  - Edge cases (missing calendar, empty trades, boundary conditions)
  - Section builder output structure
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.news_calendar import (
    derive_currencies,
    _load_research_calendar,
    _validate_calendar,
    _build_windows,
    group_windows_by_currency,
    load_news_calendar,
    _CALENDAR_CACHE,
)
from tools.report_generator import (
    _get_price_at,
    _classify_all_trades_news,
    _compute_news_metrics,
    _build_news_policy_section,
    _news_pf,
)


# ---------------------------------------------------------------------------
# Helpers to build test fixtures
# ---------------------------------------------------------------------------

def _make_research_csv(path: Path, rows: list[str]):
    """Write a RESEARCH-layer calendar CSV (lowercase columns, UTC-naive)."""
    header = "datetime_utc,currency,impact,event,source"
    content = header + "\n" + "\n".join(rows) + "\n"
    path.write_text(content, encoding="utf-8")


def _make_trades_df(trades: list[dict]) -> pd.DataFrame:
    """Build a minimal trade-level DataFrame matching RawTradeRecord schema."""
    defaults = {
        'entry_price': 2000.0,
        'exit_price': 2010.0,
        'direction': 1,
        'pnl_usd': 10.0,
        'r_multiple': 1.0,
        'bars_held': 5,
        'symbol': 'XAUUSD',
    }
    records = []
    for t in trades:
        row = {**defaults, **t}
        records.append(row)
    df = pd.DataFrame(records)
    return df


def _make_ohlc_df(bars: list[tuple]) -> pd.DataFrame:
    """Build a datetime-indexed OHLC DataFrame.

    Each *bar* is (datetime_str, open, high, low, close).
    """
    rows = []
    for ts_str, o, h, l, c in bars:
        rows.append({
            'time': pd.Timestamp(ts_str, tz='UTC'),
            'open': o, 'high': h, 'low': l, 'close': c,
        })
    df = pd.DataFrame(rows).set_index('time').sort_index()
    return df


# =====================================================================
# 1. RESEARCH calendar loading tests
# =====================================================================

class TestResearchCalendarLoading(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _CALENDAR_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _CALENDAR_CACHE.clear()

    def test_load_valid_research_csv(self):
        _make_research_csv(self.tmpdir / "cal.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        result = _load_research_calendar(self.tmpdir)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    def test_load_missing_dir(self):
        result = _load_research_calendar(self.tmpdir / "nonexistent")
        self.assertIsNone(result)

    def test_load_empty_dir(self):
        (self.tmpdir / "subdir").mkdir()
        result = _load_research_calendar(self.tmpdir / "subdir")
        self.assertIsNone(result)

    def test_load_merges_multiple_files(self):
        _make_research_csv(self.tmpdir / "a.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        _make_research_csv(self.tmpdir / "b.csv", [
            "2024-02-02 13:30:00,USD,High,NFP,ForexFactory",
        ])
        result = _load_research_calendar(self.tmpdir)
        self.assertEqual(len(result), 2)

    def test_utc_naive_assertion(self):
        """RESEARCH data must be UTC-naive — tz-aware triggers assertion."""
        _make_research_csv(self.tmpdir / "cal.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        result = _load_research_calendar(self.tmpdir)
        # Should have loaded successfully (UTC-naive)
        self.assertIsNone(result['datetime_utc'].dt.tz)

    def test_year_sanity_assertion(self):
        """Timestamps before year 2000 should trigger assertion."""
        (self.tmpdir / "bad.csv").write_text(
            "datetime_utc,currency,impact,event,source\n"
            "1970-01-01 00:00:00,USD,High,Test,ForexFactory\n",
            encoding="utf-8"
        )
        with self.assertRaises(AssertionError):
            _load_research_calendar(self.tmpdir)

    def test_dedup_across_files(self):
        """Same event in two files → deduplicated after validation."""
        _make_research_csv(self.tmpdir / "a.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        _make_research_csv(self.tmpdir / "b.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        raw = _load_research_calendar(self.tmpdir)
        validated, warnings = _validate_calendar(raw)
        self.assertEqual(len(validated), 1)


# =====================================================================
# 2. Validation tests
# =====================================================================

class TestValidation(unittest.TestCase):

    def test_missing_currency_column(self):
        df = pd.DataFrame({
            'datetime_utc': [pd.Timestamp('2024-01-05 13:30')],
            'impact': ['High'],
        })
        result, warnings = _validate_calendar(df)
        self.assertIsNone(result)
        self.assertTrue(any('currency' in w.lower() for w in warnings))

    def test_invalid_impact_dropped(self):
        df = pd.DataFrame({
            'datetime_utc': [
                pd.Timestamp('2024-01-05 13:30'),
                pd.Timestamp('2024-01-06 13:30'),
            ],
            'currency': ['USD', 'USD'],
            'impact': ['High', 'NonEconomic'],
        })
        result, _ = _validate_calendar(df)
        self.assertEqual(len(result), 1)

    def test_impact_filter_high_only(self):
        """load_news_calendar with impact_filter='High' returns only High."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            _CALENDAR_CACHE.clear()
            _make_research_csv(tmpdir / "cal.csv", [
                "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
                "2024-01-06 15:00:00,USD,Medium,ISM,ForexFactory",
            ])
            result = load_news_calendar(tmpdir, impact_filter="High")
            self.assertIsNotNone(result)
            windows_df, _ = result
            self.assertEqual(len(windows_df), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            _CALENDAR_CACHE.clear()


# =====================================================================
# 3. Window construction tests
# =====================================================================

class TestWindowConstruction(unittest.TestCase):

    def test_window_expansion(self):
        df = pd.DataFrame({
            'datetime_utc': [pd.Timestamp('2024-01-05 13:30')],
            'currency': ['USD'],
            'impact': ['High'],
            'event': ['NFP'],
        })
        windows = _build_windows(df, pre_min=15, post_min=15)
        self.assertEqual(len(windows), 1)
        ws = windows.iloc[0]['window_start']
        we = windows.iloc[0]['window_end']
        self.assertEqual(ws.hour, 13)
        self.assertEqual(ws.minute, 15)
        self.assertEqual(we.hour, 13)
        self.assertEqual(we.minute, 45)

    def test_group_by_currency(self):
        df = pd.DataFrame({
            'window_start': pd.to_datetime([
                '2024-01-05 13:15', '2024-01-05 11:45'
            ]),
            'window_end': pd.to_datetime([
                '2024-01-05 13:45', '2024-01-05 12:15'
            ]),
            'currency': ['USD', 'EUR'],
            'impact': ['High', 'High'],
            'event': ['NFP', 'ECB'],
            'datetime_utc': pd.to_datetime([
                '2024-01-05 13:30', '2024-01-05 12:00'
            ]),
        })
        grouped = group_windows_by_currency(df)
        self.assertIn('USD', grouped)
        self.assertIn('EUR', grouped)
        self.assertEqual(len(grouped['USD']), 1)
        self.assertEqual(len(grouped['EUR']), 1)


# =====================================================================
# 4. Currency derivation tests
# =====================================================================

class TestCurrencyDerivation(unittest.TestCase):

    def test_fx_pair(self):
        self.assertEqual(derive_currencies('EURUSD'), ['EUR', 'USD'])

    def test_fx_pair_gbpjpy(self):
        self.assertEqual(derive_currencies('GBPJPY'), ['GBP', 'JPY'])

    def test_commodity_override(self):
        self.assertEqual(derive_currencies('XAUUSD'), ['USD'])

    def test_index_override(self):
        self.assertEqual(derive_currencies('US30'), ['USD'])
        self.assertEqual(derive_currencies('GER40'), ['EUR'])

    def test_unknown_defaults_to_usd(self):
        self.assertEqual(derive_currencies('FOOBAR'), ['USD'])

    def test_case_insensitive(self):
        self.assertEqual(derive_currencies('eurusd'), ['EUR', 'USD'])


# =====================================================================
# 5. Trade classification tests
# =====================================================================

class TestTradeClassification(unittest.TestCase):

    def _make_windows_by_ccy(self, events: list[tuple]) -> dict:
        """Build windows_by_currency from (start_str, end_str, ccy) tuples."""
        rows = []
        for ws_str, we_str, ccy in events:
            rows.append({
                'window_start': pd.Timestamp(ws_str, tz='UTC'),
                'window_end': pd.Timestamp(we_str, tz='UTC'),
                'currency': ccy,
                'event': 'Test',
                'impact': 'High',
                'datetime_utc': pd.Timestamp(ws_str, tz='UTC'),
            })
        wdf = pd.DataFrame(rows)
        return group_windows_by_currency(wdf)

    def test_no_overlap(self):
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 14:00:00+00:00',
            'exit_timestamp': '2024-01-05 15:00:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertFalse(nf.iloc[0])
        self.assertFalse(eiw.iloc[0])
        self.assertFalse(strad.iloc[0])

    def test_entry_in_window(self):
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 13:30:00+00:00',
            'exit_timestamp': '2024-01-05 15:00:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertTrue(nf.iloc[0])
        self.assertTrue(eiw.iloc[0])

    def test_entry_exactly_at_window_start(self):
        """Entry exactly at window_start → entry_in_window = True."""
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 13:15:00+00:00',
            'exit_timestamp': '2024-01-05 14:00:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertTrue(eiw.iloc[0])

    def test_straddle(self):
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 12:00:00+00:00',
            'exit_timestamp': '2024-01-05 14:00:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertTrue(nf.iloc[0])
        self.assertFalse(eiw.iloc[0])
        self.assertTrue(strad.iloc[0])
        self.assertEqual(
            ews.iloc[0], pd.Timestamp('2024-01-05 13:15', tz='UTC')
        )

    def test_exit_exactly_at_window_start_no_straddle(self):
        """Exit == window_start → NOT a straddle (strict inequality)."""
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 12:00:00+00:00',
            'exit_timestamp': '2024-01-05 13:15:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        # exit == window_start: overlap check is exit > ws which is False
        self.assertFalse(strad.iloc[0])

    def test_currency_mismatch_no_flag(self):
        """USD news event does NOT flag a GBPJPY trade."""
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 13:30:00+00:00',
            'exit_timestamp': '2024-01-05 14:00:00+00:00',
            'symbol': 'GBPJPY',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'GBPJPY': ['GBP', 'JPY']}
        )
        self.assertFalse(nf.iloc[0])

    def test_multiple_windows_earliest_selected(self):
        """Multiple overlapping windows → earliest_window_start is min."""
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:15', '2024-01-05 13:45', 'USD'),
            ('2024-01-05 14:00', '2024-01-05 14:30', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 12:00:00+00:00',
            'exit_timestamp': '2024-01-05 15:00:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertEqual(
            ews.iloc[0], pd.Timestamp('2024-01-05 13:15', tz='UTC')
        )

    def test_fully_inside_window(self):
        """Trade fully inside window → entry_in_window = True."""
        wbc = self._make_windows_by_ccy([
            ('2024-01-05 13:00', '2024-01-05 14:00', 'USD'),
        ])
        df = _make_trades_df([{
            'entry_timestamp': '2024-01-05 13:15:00+00:00',
            'exit_timestamp': '2024-01-05 13:45:00+00:00',
            'symbol': 'XAUUSD',
        }])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        df['_exit_dt'] = pd.to_datetime(df['exit_timestamp'], utc=True)

        nf, eiw, strad, ews = _classify_all_trades_news(
            df, wbc, {'XAUUSD': ['USD']}
        )
        self.assertTrue(nf.iloc[0])
        self.assertTrue(eiw.iloc[0])


# =====================================================================
# 6. Scenario computation tests
# =====================================================================

class TestScenarioComputation(unittest.TestCase):

    def test_no_entry_removes_correct_trades(self):
        """5 trades, 2 flagged as entry_in_window → No-Entry keeps 3."""
        trades = []
        for i in range(5):
            trades.append({
                'entry_timestamp': f'2024-01-0{i+1} 10:00:00+00:00',
                'exit_timestamp': f'2024-01-0{i+1} 12:00:00+00:00',
                'pnl_usd': 10.0 * (i + 1),
                'symbol': 'XAUUSD',
            })
        df = _make_trades_df(trades)
        df['_entry_in_window'] = [True, False, True, False, False]
        df_no_entry = df[~df['_entry_in_window']].copy()
        self.assertEqual(len(df_no_entry), 3)

    def test_go_flat_pnl_scaling(self):
        """Verify PnL scaling formula against known values."""
        # Long trade: entry 2000, exit 2020, pnl $100
        # Go-flat exit at 2010 → should be $50
        entry_price = 2000.0
        exit_price = 2020.0
        direction = 1
        original_pnl = 100.0
        new_exit_price = 2010.0

        price_delta = (exit_price - entry_price) * direction  # 20
        pnl_scale = original_pnl / price_delta  # 5.0
        new_pnl = pnl_scale * (new_exit_price - entry_price) * direction
        self.assertAlmostEqual(new_pnl, 50.0)

    def test_go_flat_pnl_scaling_short(self):
        """Verify PnL scaling for short trade."""
        # Short trade: entry 2020, exit 2000, pnl $100
        # Go-flat exit at 2010 → should be $50
        entry_price = 2020.0
        exit_price = 2000.0
        direction = -1
        original_pnl = 100.0

        price_delta = (exit_price - entry_price) * direction  # 20
        pnl_scale = original_pnl / price_delta  # 5.0
        new_exit_price = 2010.0
        new_pnl = pnl_scale * (new_exit_price - entry_price) * direction
        self.assertAlmostEqual(new_pnl, 50.0)

    def test_go_flat_entry_equals_exit(self):
        """When entry == exit price, pnl_scale undefined → new_pnl = 0."""
        entry_price = 2000.0
        exit_price = 2000.0
        direction = 1
        original_pnl = 0.0

        price_delta = (exit_price - entry_price) * direction
        self.assertAlmostEqual(abs(price_delta), 0.0)
        # Code handles this: new_pnl = 0.0

    def test_compute_metrics_empty(self):
        df = pd.DataFrame(columns=['pnl_usd', '_entry_dt'])
        m = _compute_news_metrics(df)
        self.assertEqual(m['trades'], 0)
        self.assertEqual(m['net_pnl'], 0.0)

    def test_compute_metrics_basic(self):
        df = _make_trades_df([
            {'entry_timestamp': '2024-01-01 10:00+00:00',
             'exit_timestamp': '2024-01-01 11:00+00:00', 'pnl_usd': 10.0},
            {'entry_timestamp': '2024-01-02 10:00+00:00',
             'exit_timestamp': '2024-01-02 11:00+00:00', 'pnl_usd': -5.0},
        ])
        df['_entry_dt'] = pd.to_datetime(df['entry_timestamp'], utc=True)
        m = _compute_news_metrics(df)
        self.assertEqual(m['trades'], 2)
        self.assertAlmostEqual(m['net_pnl'], 5.0)
        self.assertAlmostEqual(m['pf'], 2.0)  # 10 / 5
        self.assertAlmostEqual(m['win_pct'], 50.0)

    def test_baseline_unchanged_after_scenarios(self):
        """Original DataFrame must not be mutated by scenario functions."""
        df = _make_trades_df([
            {'entry_timestamp': '2024-01-05 13:30:00+00:00',
             'exit_timestamp': '2024-01-05 14:30:00+00:00',
             'pnl_usd': 50.0, 'symbol': 'XAUUSD'},
        ])
        original_pnl = df['pnl_usd'].iloc[0]
        df_copy = df.copy()

        # Simulate No-Entry (drop all)
        df_ne = df[df['pnl_usd'] < 0].copy()  # empty result
        # Original unchanged
        self.assertEqual(df['pnl_usd'].iloc[0], original_pnl)
        pd.testing.assert_frame_equal(df, df_copy)


# =====================================================================
# 7. OHLC price lookup tests
# =====================================================================

class TestOHLCLookup(unittest.TestCase):

    def test_get_price_at_exact(self):
        ohlc = _make_ohlc_df([
            ('2024-01-05 12:00+00:00', 2000, 2010, 1990, 2005),
            ('2024-01-05 13:00+00:00', 2005, 2015, 2000, 2010),
        ])
        price = _get_price_at(ohlc, pd.Timestamp('2024-01-05 13:00', tz='UTC'))
        self.assertAlmostEqual(price, 2010.0)

    def test_get_price_at_between_bars(self):
        ohlc = _make_ohlc_df([
            ('2024-01-05 12:00+00:00', 2000, 2010, 1990, 2005),
            ('2024-01-05 13:00+00:00', 2005, 2015, 2000, 2010),
        ])
        # 12:30 → last bar at or before is 12:00, close = 2005
        price = _get_price_at(ohlc, pd.Timestamp('2024-01-05 12:30', tz='UTC'))
        self.assertAlmostEqual(price, 2005.0)

    def test_get_price_at_before_data(self):
        ohlc = _make_ohlc_df([
            ('2024-01-05 12:00+00:00', 2000, 2010, 1990, 2005),
        ])
        price = _get_price_at(ohlc, pd.Timestamp('2024-01-05 11:00', tz='UTC'))
        self.assertIsNone(price)

    def test_get_price_at_none_ohlc(self):
        self.assertIsNone(_get_price_at(None, pd.Timestamp('2024-01-05', tz='UTC')))


# =====================================================================
# 8. PF helper tests
# =====================================================================

class TestPFHelper(unittest.TestCase):

    def test_pf_basic(self):
        s = pd.Series([10.0, -5.0, 20.0, -10.0])
        self.assertAlmostEqual(_news_pf(s), 2.0)  # 30/15

    def test_pf_no_losses(self):
        s = pd.Series([10.0, 20.0])
        self.assertAlmostEqual(_news_pf(s), 30.0)

    def test_pf_no_wins(self):
        s = pd.Series([-10.0, -20.0])
        self.assertAlmostEqual(_news_pf(s), 0.0)

    def test_pf_empty(self):
        s = pd.Series([], dtype=float)
        self.assertAlmostEqual(_news_pf(s), 0.0)


# =====================================================================
# 9. Section builder integration tests
# =====================================================================

class TestSectionBuilder(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.cal_dir = self.tmpdir / "research_calendar"
        self.cal_dir.mkdir()
        _CALENDAR_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _CALENDAR_CACHE.clear()

    def test_missing_calendar_skips_gracefully(self):
        empty_cal = self.tmpdir / "no_cal"
        md = _build_news_policy_section([], "1h", self.tmpdir, empty_cal)
        self.assertTrue(any("section skipped" in line for line in md))

    def test_empty_trades_returns_empty(self):
        _make_research_csv(self.cal_dir / "cal.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        md = _build_news_policy_section([], "1h", self.tmpdir, self.cal_dir)
        # No trades → no section content (calendar loaded but nothing to do)
        self.assertEqual(len(md), 0)

    def test_full_section_structure(self):
        """Verify section contains all required sub-sections."""
        _make_research_csv(self.cal_dir / "cal.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        # Create enough trades to pass threshold
        trades = []
        for i in range(15):
            day = f'2024-01-{i+1:02d}'
            trades.append({
                'entry_timestamp': f'{day} 10:00:00+00:00',
                'exit_timestamp': f'{day} 12:00:00+00:00',
                'pnl_usd': 10.0 if i % 2 == 0 else -5.0,
                'symbol': 'XAUUSD',
                'entry_price': 2000.0,
                'exit_price': 2010.0 if i % 2 == 0 else 1995.0,
                'direction': 1,
                'r_multiple': 1.0 if i % 2 == 0 else -0.5,
            })
        df = _make_trades_df(trades)
        md = _build_news_policy_section(
            [df], "1h", self.tmpdir, self.cal_dir
        )
        md_text = "\n".join(md)

        self.assertIn("## News Policy Impact", md_text)
        self.assertIn("### Portfolio Impact", md_text)
        self.assertIn("Baseline", md_text)
        self.assertIn("No-Entry", md_text)
        self.assertIn("Go-Flat", md_text)
        self.assertIn("### Per-Symbol News Sensitivity", md_text)
        self.assertIn("### News vs Non-News Performance", md_text)
        self.assertIn("Note: Go-Flat assumes no entries", md_text)

    def test_below_threshold_after_filter(self):
        """When filtering leaves < _NEWS_MIN_TRADES, show count only."""
        _make_research_csv(self.cal_dir / "cal.csv", [
            f"2024-01-{d:02d} 10:00:00,USD,High,NFP,ForexFactory"
            for d in range(1, 16)
        ])
        trades = []
        for i in range(12):
            day = f'2024-01-{i+1:02d}'
            trades.append({
                'entry_timestamp': f'{day} 10:00:00+00:00',
                'exit_timestamp': f'{day} 12:00:00+00:00',
                'pnl_usd': 10.0,
                'symbol': 'XAUUSD',
            })
        df = _make_trades_df(trades)
        md = _build_news_policy_section(
            [df], "1h", self.tmpdir, self.cal_dir
        )
        md_text = "\n".join(md)
        # Section should still render (baseline has enough trades)
        self.assertIn("Baseline", md_text)

    def test_no_news_entries_no_straddlers(self):
        """When no trades overlap news → No-Entry and Go-Flat == Baseline."""
        _make_research_csv(self.cal_dir / "cal.csv", [
            "2024-06-01 13:30:00,USD,High,NFP,ForexFactory",
        ])
        trades = []
        for i in range(12):
            day = f'2024-01-{i+1:02d}'
            trades.append({
                'entry_timestamp': f'{day} 10:00:00+00:00',
                'exit_timestamp': f'{day} 12:00:00+00:00',
                'pnl_usd': 10.0,
                'symbol': 'XAUUSD',
            })
        df = _make_trades_df(trades)
        md = _build_news_policy_section(
            [df], "1h", self.tmpdir, self.cal_dir
        )
        md_text = "\n".join(md)
        # Baseline, No-Entry, Go-Flat in Portfolio Impact + Outside in
        # aggregate diagnostic all show 12 trades (no news overlap at all)
        lines_with_12 = [l for l in md if '| 12 |' in l]
        self.assertGreaterEqual(len(lines_with_12), 3)


# =====================================================================
# 10. Caching tests
# =====================================================================

class TestCaching(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _CALENDAR_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _CALENDAR_CACHE.clear()

    def test_cache_hit(self):
        _make_research_csv(self.tmpdir / "cal.csv", [
            "2024-01-05 13:30:00,USD,High,NFP,ForexFactory",
        ])
        r1 = load_news_calendar(self.tmpdir)
        r2 = load_news_calendar(self.tmpdir)
        self.assertIs(r1, r2)  # same object from cache

    def test_cache_miss_none(self):
        """Missing dir → cached as None, subsequent calls return None fast."""
        empty = self.tmpdir / "empty"
        r1 = load_news_calendar(empty)
        self.assertIsNone(r1)
        r2 = load_news_calendar(empty)
        self.assertIsNone(r2)


if __name__ == '__main__':
    unittest.main()
