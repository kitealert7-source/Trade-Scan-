"""test_cointegration_freshness_check.py -- per-(tf,lookback) staleness alarm.

Covers the three required cases:
  1. fresh key passes (no alarm),
  2. a stale key alarms (the 4h-style silent gap),
  3. weekend FX-only staleness does NOT false-alarm,
plus threshold-configurability, the singles table, the global cross-table
reference, empty-DB safety, and the reference-date (absolute) override.

Uses an on-disk tmp SQLite via the same connect()+create_tables() path the
production code uses -- never the production cointegration.db.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cointegration_db import (
    DB_COLUMNS,
    SINGLES_DB_COLUMNS,
    SINGLES_TABLE_NAME,
    TABLE_NAME,
    connect,
    create_tables,
)
from tools.cointegration_freshness_check import (
    DEFAULT_MAX_LAG_DAYS,
    check_db,
    compute_freshness,
    format_report_lines,
)

# The four real (tf, lookback_days) keys present in production (verified
# 2026-06-07): 1d at 252/504 days, 4h at 1500/3000 bars.
ALL_KEYS = [("1d", 252), ("1d", 504), ("4h", 1500), ("4h", 3000)]


# ---------------------------------------------------------------------------
# Fixtures + insert helpers (mirror tests/test_cointegration_db.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    """Fresh on-disk SQLite per test (so WAL mode works)."""
    db = tmp_path / "test_freshness.db"
    c = connect(db)
    create_tables(c)
    yield c
    c.close()


def _insert_pair(conn, as_of, pair_a, pair_b, *, tf="1d", lookback_days=252,
                 regime="cointegrated"):
    inserted_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"INSERT INTO {TABLE_NAME} ({', '.join(DB_COLUMNS)}) "
        f"VALUES ({', '.join(['?']*len(DB_COLUMNS))})",
        (
            as_of, pair_a, pair_b, tf, lookback_days,
            "2025-01-01", as_of, lookback_days, 0.03, None, 0, -3.0,
            10.0, 1.5, "ols_static", "eg_mackinnon",
            0.5, regime, "v0", inserted_at, "v2_log_eg",
        ),
    )
    conn.commit()


def _insert_single(conn, as_of, symbol, *, tf="1d", lookback_days=252,
                   regime="cointegrated"):
    inserted_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"INSERT INTO {SINGLES_TABLE_NAME} ({', '.join(SINGLES_DB_COLUMNS)}) "
        f"VALUES ({', '.join(['?']*len(SINGLES_DB_COLUMNS))})",
        (
            as_of, symbol, tf, lookback_days,
            "2025-01-01", as_of, lookback_days, 0.03, None, 0, -3.0,
            10.0, "adf",
            0.5, regime, "v0", inserted_at, "v2_log_eg",
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 1. Fresh key passes
# ---------------------------------------------------------------------------


class TestFreshKeysPass:

    def test_all_keys_same_as_of_pass(self, conn):
        today = "2026-06-07"
        for tf, lb in ALL_KEYS:
            _insert_pair(conn, today, "EURUSD", "USDJPY", tf=tf, lookback_days=lb)
            _insert_single(conn, today, "EURUSD", tf=tf, lookback_days=lb)
        report = check_db(conn)
        assert report.ok
        assert report.stale_keys == []
        assert report.reference_as_of == today
        # 4 pair keys + 4 singles keys
        assert len(report.keys) == 8
        assert all(k.lag_days == 0 for k in report.keys)
        # single OK summary line
        lines = format_report_lines(report)
        assert len(lines) == 1 and lines[0].startswith("OK")


# ---------------------------------------------------------------------------
# 2. A stale key alarms (the 4h-style silent gap)
# ---------------------------------------------------------------------------


class TestStaleKeyAlarms:

    def test_4h_keys_stale_when_1d_advances(self, conn):
        # 1d advanced to today; 4h frozen 9 days back -- the exact shape of the
        # 2026-05-29 -> 2026-06-06 silent 4h gap this check exists to catch.
        for lb in (252, 504):
            _insert_pair(conn, "2026-06-07", "EURUSD", "USDJPY",
                         tf="1d", lookback_days=lb)
        for lb in (1500, 3000):
            _insert_pair(conn, "2026-05-29", "EURUSD", "USDJPY",
                         tf="4h", lookback_days=lb)

        report = check_db(conn)  # default N=3
        assert not report.ok
        assert {(k.tf, k.lookback_days) for k in report.stale_keys} == {
            ("4h", 1500), ("4h", 3000)}
        for k in report.keys:
            if k.tf == "1d":
                assert not k.stale and k.lag_days == 0   # freshest -> reference
            else:
                assert k.stale and k.lag_days == 9

        # the output is CONCISE: a header + exactly one compact line per stale
        # key (no wide table dump), each line greppable on "WARN".
        lines = format_report_lines(report)
        assert len(lines) == 3                        # header + 2 stale keys only
        assert lines[0].startswith("WARN  freshness:")
        assert "reference as_of 2026-06-07" in lines[0]
        assert "threshold 3d" in lines[0]
        assert any("cointegration_daily (4h,1500) lag=9d" in ln for ln in lines)
        assert any("cointegration_daily (4h,3000) lag=9d" in ln for ln in lines)
        # every detail line stays WARN-tagged so a log filter catches each key
        assert all(ln.startswith("WARN") for ln in lines)


# ---------------------------------------------------------------------------
# 3. Weekend FX-only staleness does NOT false-alarm
# ---------------------------------------------------------------------------


class TestWeekendDoesNotFalseAlarm:

    def test_fx_friday_crypto_sunday_same_key_not_stale(self, conn):
        # Real weekend shape: within EACH (tf,lookback) key, FX/index pairs
        # carry Friday's as_of (no weekend bars) while the crypto pair carries
        # Sunday's. The key's MAX(as_of) is crypto's Sunday, so every key is
        # fully fresh -- no alarm. This is precisely why the check is per-key
        # relative (driven by the freshest member) and not per-pair absolute.
        friday, sunday = "2026-06-05", "2026-06-07"
        for tf, lb in ALL_KEYS:
            _insert_pair(conn, friday, "EURUSD", "USDJPY", tf=tf, lookback_days=lb)
            _insert_pair(conn, friday, "GBPUSD", "USDCHF", tf=tf, lookback_days=lb)
            _insert_pair(conn, sunday, "BTCUSD", "ETHUSD", tf=tf, lookback_days=lb)
            _insert_single(conn, friday, "EURUSD", tf=tf, lookback_days=lb)
            _insert_single(conn, sunday, "BTCUSD", tf=tf, lookback_days=lb)

        report = check_db(conn)
        assert report.ok, [
            (k.table, k.tf, k.lookback_days, k.max_as_of, k.lag_days)
            for k in report.stale_keys
        ]
        assert report.reference_as_of == sunday

    def test_two_day_weekend_lag_not_flagged_at_default_threshold(self, conn):
        # Even a key that genuinely lags by a weekend (a hypothetical key with
        # no crypto member -> Fri while the freshest key is Sun) stays UNDER the
        # conservative N=3 default and must not alarm...
        _insert_pair(conn, "2026-06-07", "BTCUSD", "ETHUSD",
                     tf="1d", lookback_days=252)
        _insert_pair(conn, "2026-06-05", "EURUSD", "USDJPY",
                     tf="1d", lookback_days=504)
        report = check_db(conn)             # N=3, 2-day lag
        assert report.ok

        # ...but it IS surfaced under a stricter threshold (config works).
        strict = check_db(conn, max_lag_days=1)
        assert not strict.ok
        assert {(k.tf, k.lookback_days) for k in strict.stale_keys} == {
            ("1d", 504)}


# ---------------------------------------------------------------------------
# Edges: threshold boundary, singles table, global reference, empty DB, override
# ---------------------------------------------------------------------------


class TestThresholdBoundary:

    def test_exactly_threshold_days_not_stale(self, conn):
        # lag == N is NOT stale (strict >); lag == N+1 is.
        _insert_pair(conn, "2026-06-07", "BTCUSD", "ETHUSD",
                     tf="1d", lookback_days=252)
        _insert_pair(conn, "2026-06-04", "EURUSD", "USDJPY",   # 3 days behind
                     tf="1d", lookback_days=504)
        assert check_db(conn, max_lag_days=3).ok                # 3 > 3 is False
        assert not check_db(conn, max_lag_days=2).ok            # 3 > 2 is True


class TestSinglesTableChecked:

    def test_stale_singles_key_flagged_against_global_reference(self, conn):
        # pair-pair fresh today; a singles key frozen 10 days back must be
        # flagged -- and judged against the GLOBAL freshest key (which here
        # lives in the pair table), proving the cross-table reference.
        _insert_pair(conn, "2026-06-07", "EURUSD", "USDJPY",
                     tf="1d", lookback_days=252)
        _insert_single(conn, "2026-06-07", "EURUSD", tf="1d", lookback_days=252)
        _insert_single(conn, "2026-05-28", "EURUSD", tf="4h", lookback_days=1500)

        report = check_db(conn)
        assert report.reference_as_of == "2026-06-07"
        stale = {(k.table, k.tf, k.lookback_days) for k in report.stale_keys}
        assert stale == {(SINGLES_TABLE_NAME, "4h", 1500)}


class TestEmptyDb:

    def test_empty_db_no_alarm(self, conn):
        report = check_db(conn)
        assert report.ok
        assert report.keys == []
        assert report.reference_as_of is None
        lines = format_report_lines(report)
        assert len(lines) == 1 and "nothing to check" in lines[0]


class TestReferenceOverride:

    def test_reference_date_enables_absolute_check(self, conn):
        # Everything in the DB is at Friday. The relative check is clean (the
        # only key is its own reference, lag 0), but an absolute check vs a
        # later 'today' surfaces the lag -- the documented opt-in.
        _insert_pair(conn, "2026-06-05", "EURUSD", "USDJPY",
                     tf="1d", lookback_days=252)
        assert check_db(conn).ok                                  # relative
        absolute = check_db(conn, reference_as_of="2026-06-10")
        assert not absolute.ok
        assert absolute.keys[0].lag_days == 5


class TestComputeFreshnessPure:
    """Pure date-math on minimal synthetic DataFrames -- no DB."""

    def test_minimal_dataframe_contract(self):
        pairs = pd.DataFrame({
            "tf": ["1d", "1d", "4h"],
            "lookback_days": [252, 504, 1500],
            "as_of": ["2026-06-07", "2026-06-07", "2026-05-29"],
        })
        singles = pd.DataFrame(columns=["tf", "lookback_days", "as_of"])
        report = compute_freshness(pairs, singles, max_lag_days=3)
        assert report.reference_as_of == "2026-06-07"
        assert {(k.tf, k.lookback_days) for k in report.stale_keys} == {
            ("4h", 1500)}
        # lag is 9 days for the stale key; 0 for the two fresh ones
        lags = {(k.tf, k.lookback_days): k.lag_days for k in report.keys}
        assert lags == {("1d", 252): 0, ("1d", 504): 0, ("4h", 1500): 9}
