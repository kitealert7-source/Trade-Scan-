"""test_cointegration_db.py — Phase 2 unit tests.

Validates tools/cointegration_db.py against in-memory SQLite + synthetic
parquet inputs. No MASTER_DATA dependency.

Per COINTEGRATION_SCREENER_V1_SPEC.md §12 Phase 2 gate:
    "unit test: parquet→DB→DataFrame roundtrip preserves all columns"
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cointegration_db import (
    DB_COLUMNS,
    HYSTERESIS_LOOKBACK,
    P_BREAKING,
    P_COINTEGRATED,
    TABLE_NAME,
    classify_regime,
    compute_rolling_median,
    connect,
    create_tables,
    query_for_classifier,
    query_history,
    query_today,
    upsert_from_parquet,
)
from tools.cointegration_screen import PARQUET_COLUMNS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    """Fresh on-disk SQLite per test (so WAL mode works)."""
    db = tmp_path / "test_coint.db"
    c = connect(db)
    create_tables(c)
    yield c
    c.close()


def _make_parquet_row(as_of_date: str, pair_a: str, pair_b: str,
                       lookback_days: int, adf_pvalue: float,
                       regime: str = "broken",
                       methodology_version: str = "v1_raw_adf") -> dict:
    """Construct a minimal valid parquet row in PARQUET_COLUMNS order."""
    window_end = pd.Timestamp(as_of_date, tz="UTC")
    window_start = window_end - pd.Timedelta(days=lookback_days - 1)
    return {
        "pair_a": pair_a, "pair_b": pair_b,
        "tf": "1d", "lookback_days": lookback_days,
        "window_start": window_start, "window_end": window_end,
        "sample_size": lookback_days,
        "adf_pvalue": adf_pvalue,
        "pvalue_rolling_median_5d": float("nan"),
        "adf_statistic": -3.5,
        "half_life_days": 10.0,
        "hedge_ratio": 1.5,
        "beta_method": "ols_static",
        "test_method": "adf",
        "current_zscore": 0.5,
        "regime": regime,
        "data_version": "abc123def456",
        "generated_at": pd.Timestamp(as_of_date + "T22:00:00", tz="UTC"),
        "methodology_version": methodology_version,
    }


@pytest.fixture
def parquet_one_day(tmp_path):
    """Write a parquet for one day (2 rows, 1 pair × 2 windows)."""
    rows = [
        _make_parquet_row("2026-05-15", "EURUSD", "USDJPY", 252, 0.03),
        _make_parquet_row("2026-05-15", "EURUSD", "USDJPY", 504, 0.07),
    ]
    df = pd.DataFrame(rows, columns=PARQUET_COLUMNS)
    p = tmp_path / "coint_one_day.parquet"
    df.to_parquet(p, index=False)
    return p


# ---------------------------------------------------------------------------
# Schema + connection
# ---------------------------------------------------------------------------


class TestSchema:

    def test_table_created(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_NAME,),
        ).fetchall()
        assert len(rows) == 1

    def test_indexes_created(self, conn):
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        for required in ("idx_coint_pair", "idx_coint_regime", "idx_coint_history"):
            assert required in names

    def test_wal_mode_active(self, conn):
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_db_columns_canonical_order(self):
        # Schema is FROZEN — accidental reorder must fail this test.
        # Additive-only: methodology_version appended at end 2026-05-30 (C2).
        expected = [
            "as_of", "pair_a", "pair_b", "tf", "lookback_days",
            "window_start", "window_end", "sample_size",
            "adf_pvalue", "pvalue_rolling_median_5d", "history_depth", "adf_statistic",
            "half_life_days", "hedge_ratio", "beta_method", "test_method",
            "current_zscore", "regime",
            "data_version", "inserted_at",
            "methodology_version",
        ]
        assert DB_COLUMNS == expected

    def test_methodology_version_column_present(self, conn):
        """Column is on the live DB after create_tables."""
        cols = {r[1] for r in conn.execute(
            f"PRAGMA table_info({TABLE_NAME})").fetchall()}
        assert "methodology_version" in cols
        s_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(singles_daily)").fetchall()}
        assert "methodology_version" in s_cols

    def test_placeholder_rows_skipped_at_upsert(self, conn, tmp_path):
        """When run() emits a placeholder row for a pair that lacked the
        requested lookback bars at as_of (sample_size=0, NaT window dates),
        upsert_from_parquet must skip the row entirely. The schema declares
        window_start/end as NOT NULL — a snapshot with no compute is not
        a series claim. Regression for 2026-05-30 BC3 attempt 2 failure.

        Production daily runs never produce placeholders (today's as_of
        has full history for every symbol); historical backfills do, for
        pair-pairs involving symbols that were not yet in the universe.

        Note: production-produced parquets have TZ-NAIVE window_start/end
        (compute_pair_stats reads them from the data index which is tz-naive).
        This fixture mirrors that so the upsert's NaT-fillna doesn't trip
        the .dt accessor on a mixed tz-aware + tz-naive column."""
        def _row(pair_a, pair_b, sample_size, pvalue):
            window_end = pd.Timestamp("2026-05-15")  # tz-naive, matches prod
            return {
                "pair_a": pair_a, "pair_b": pair_b,
                "tf": "1d", "lookback_days": 252,
                "window_start": window_end - pd.Timedelta(days=251)
                                  if sample_size > 0 else pd.NaT,
                "window_end": window_end if sample_size > 0 else pd.NaT,
                "sample_size": sample_size,
                "adf_pvalue": pvalue,
                "pvalue_rolling_median_5d": float("nan"),
                "adf_statistic": -3.5 if sample_size > 0 else float("nan"),
                "half_life_days": 10.0 if sample_size > 0 else float("nan"),
                "hedge_ratio": 1.5 if sample_size > 0 else float("nan"),
                "beta_method": "ols_static",
                "test_method": "eg_mackinnon",
                "current_zscore": 0.5 if sample_size > 0 else float("nan"),
                "regime": "cointegrated" if sample_size > 0 else "broken",
                "data_version": "abc",
                "generated_at": pd.Timestamp("2026-05-15T22:00:00", tz="UTC"),
                "methodology_version": "v1_raw_adf",
            }

        df = pd.DataFrame(
            [_row("EURUSD", "USDJPY", 252, 0.03),
             _row("GBPUSD", "USDCHF", 252, 0.04),
             _row("ETHUSD", "BTCUSD", 0, 1.0)],          # placeholder
            columns=PARQUET_COLUMNS,
        )
        p = tmp_path / "mixed.parquet"
        df.to_parquet(p, index=False)

        n = upsert_from_parquet(conn, p)
        assert n == 2, f"expected 2 real rows upserted, got {n}"

        rows = conn.execute(
            f"SELECT pair_a, pair_b, sample_size FROM {TABLE_NAME} "
            f"ORDER BY pair_a, pair_b"
        ).fetchall()
        pairs = {(r["pair_a"], r["pair_b"]) for r in rows}
        assert ("EURUSD", "USDJPY") in pairs
        assert ("GBPUSD", "USDCHF") in pairs
        assert ("ETHUSD", "BTCUSD") not in pairs, (
            "Placeholder row (sample_size=0) should have been skipped, "
            "but it landed in the DB."
        )
        for r in rows:
            assert r["sample_size"] > 0

    def test_methodology_version_required_not_null(self, conn):
        """No write path may emit NULL methodology_version (operator C2 invariant)."""
        import sqlite3
        # Build a row tuple with NULL in the methodology slot — must raise.
        inserted_at = datetime.now(timezone.utc).isoformat()
        cols = ", ".join(DB_COLUMNS)
        placeholders = ", ".join(["?"] * len(DB_COLUMNS))
        bad_row = (
            "2026-05-30", "EURUSD", "USDJPY", "1d", 252,
            "2025-08-25", "2026-05-30", 252, 0.5, None, 0, -3.0,
            10.0, 1.5, "ols_static", "adf",
            0.0, "broken", "v0", inserted_at,
            None,  # methodology_version = NULL → NOT NULL constraint should fire
        )
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL|methodology_version"):
            conn.execute(
                f"INSERT INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})",
                bad_row,
            )

    def test_create_tables_is_idempotent(self, tmp_path):
        """create_tables can be called repeatedly without error or drift.
        Guards the backfill UPDATE which runs on every call — must not overwrite
        existing populated values."""
        db = tmp_path / "idem.db"
        c1 = connect(db)
        create_tables(c1)
        # Seed a v2 row that the migration MUST NOT clobber back to v1.
        inserted_at = datetime.now(timezone.utc).isoformat()
        c1.execute(
            f"INSERT INTO {TABLE_NAME} ({', '.join(DB_COLUMNS)}) VALUES ({', '.join(['?']*len(DB_COLUMNS))})",
            (
                "2026-06-01", "EURUSD", "USDJPY", "1d", 252,
                "2025-09-01", "2026-06-01", 252, 0.03, None, 0, -4.0,
                12.0, 1.0, "ols_static", "eg_mackinnon",
                0.2, "cointegrated", "v0", inserted_at,
                "v2_log_eg",  # NEW methodology; migration must leave alone
            ),
        )
        c1.commit()
        c1.close()
        # Re-open and re-run create_tables — should be a no-op for schema +
        # idempotent for the UPDATE WHERE IS NULL.
        c2 = connect(db)
        create_tables(c2)  # second call — must not raise, must not corrupt
        row = c2.execute(
            f"SELECT methodology_version FROM {TABLE_NAME} "
            f"WHERE as_of='2026-06-01'"
        ).fetchone()
        c2.close()
        assert row["methodology_version"] == "v2_log_eg", (
            "second create_tables call clobbered a non-NULL methodology_version"
        )


# ---------------------------------------------------------------------------
# Roundtrip — the PHASE 2 GATE TEST
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """Spec §12 Phase 2 gate: parquet→DB→DataFrame preserves all columns."""

    def test_two_row_roundtrip(self, conn, parquet_one_day):
        n = upsert_from_parquet(conn, parquet_one_day)
        assert n == 2

        df = query_today(conn)
        assert len(df) == 2

        # All DB_COLUMNS present
        for col in DB_COLUMNS:
            assert col in df.columns, f"missing column {col}"

        # Spot-check numeric round-trip (within float tolerance).
        row_252 = df[df.lookback_days == 252].iloc[0]
        assert row_252["pair_a"] == "EURUSD"
        assert row_252["pair_b"] == "USDJPY"
        assert abs(row_252["adf_pvalue"] - 0.03) < 1e-6
        assert row_252["beta_method"] == "ols_static"
        assert row_252["test_method"] == "adf"
        assert row_252["data_version"] == "abc123def456"
        assert row_252["sample_size"] == 252

    def test_as_of_derived_from_window_end(self, conn, parquet_one_day):
        upsert_from_parquet(conn, parquet_one_day)
        df = query_today(conn)
        assert df["as_of"].unique().tolist() == ["2026-05-15"]


# ---------------------------------------------------------------------------
# Hysteresis classifier (spec §7)
# ---------------------------------------------------------------------------


class TestHysteresisClassifier:

    def test_bootstrap_path_no_priors(self):
        # < HYSTERESIS_LOOKBACK priors -> bootstrap (current-pvalue only)
        assert classify_regime(0.01, []) == "cointegrated"
        assert classify_regime(0.07, []) == "breaking"
        assert classify_regime(0.20, []) == "broken"
        assert classify_regime(0.01, [0.5, 0.5]) == "cointegrated"

    def test_full_history_cointegrated_persistent(self):
        # current low + ≥4 of 5 priors low → cointegrated
        priors = [0.01, 0.02, 0.03, 0.04, 0.20]   # 4 of 5 < 0.05
        assert classify_regime(0.01, priors) == "cointegrated"

    def test_full_history_cointegrated_insufficient_priors(self):
        # current low BUT only 3 of 5 priors low → breaking (not cointegrated)
        priors = [0.01, 0.02, 0.03, 0.20, 0.20]   # 3 of 5 < 0.05
        assert classify_regime(0.01, priors) == "breaking"

    def test_breaking_zone(self):
        # current in [0.05, 0.10) always → breaking
        assert classify_regime(0.07, [0.01]*5) == "breaking"
        assert classify_regime(0.07, [0.5]*5) == "breaking"

    def test_broken_zone(self):
        # current ≥ 0.10 always → broken
        assert classify_regime(0.10, [0.01]*5) == "broken"
        assert classify_regime(0.50, []) == "broken"


# ---------------------------------------------------------------------------
# Rolling median enrichment
# ---------------------------------------------------------------------------


class TestRollingMedian:

    def test_no_priors_returns_none(self):
        assert compute_rolling_median([]) is None

    def test_uses_up_to_5_priors(self):
        assert compute_rolling_median([0.1, 0.2, 0.3]) == pytest.approx(0.2)
        # If more than 5 provided, only first 5 used
        assert compute_rolling_median([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Upsert semantics (idempotency, history queries)
# ---------------------------------------------------------------------------


class TestUpsertSemantics:

    def _seed_history(self, conn, pvalues_oldest_first: list[float],
                       methodology: str = "v1_raw_adf"):
        """Insert N rows for EURUSD/USDJPY/252, one per day. methodology
        tags the cohort; default 'v1_raw_adf' mirrors the legacy era."""
        base = pd.Timestamp("2026-05-01", tz="UTC")
        inserted_at = datetime.now(timezone.utc).isoformat()
        for i, p in enumerate(pvalues_oldest_first):
            as_of = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                f"INSERT INTO {TABLE_NAME} ({', '.join(DB_COLUMNS)}) VALUES ({', '.join(['?']*len(DB_COLUMNS))})",
                (
                    as_of, "EURUSD", "USDJPY", "1d", 252,
                    "2025-08-25", as_of, 252, p, None, 0, -3.0,
                    10.0, 1.5, "ols_static", "adf",
                    0.0, "broken", "v0", inserted_at,
                    methodology,
                ),
            )
        conn.commit()

    def test_query_for_classifier_returns_most_recent_first(self, conn):
        self._seed_history(conn, [0.50, 0.40, 0.30, 0.20, 0.10])
        priors = query_for_classifier(conn, "EURUSD", "USDJPY", 252,
                                       before_as_of="2026-05-06")
        # 5 priors, most recent (2026-05-05=0.10) first
        assert priors == [0.10, 0.20, 0.30, 0.40, 0.50]

    def test_query_for_classifier_respects_before_filter(self, conn):
        self._seed_history(conn, [0.50, 0.40, 0.30, 0.20, 0.10])
        # before 2026-05-03 -> only 0.50 (5-01) and 0.40 (5-02)
        priors = query_for_classifier(conn, "EURUSD", "USDJPY", 252,
                                       before_as_of="2026-05-03")
        assert priors == [0.40, 0.50]

    def test_upsert_uses_history_for_enrichment(self, conn, parquet_one_day):
        # Seed 5 prior days all cointegrated
        self._seed_history(conn, [0.01, 0.02, 0.03, 0.04, 0.045])
        # The parquet has 2026-05-15 EURUSD/USDJPY adf_pvalue=0.03 (252-bar)
        upsert_from_parquet(conn, parquet_one_day)
        df = query_today(conn)
        row_252 = df[df.lookback_days == 252].iloc[0]
        # Hysteresis: 5 of 5 priors < 0.05 + current 0.03 → cointegrated
        assert row_252["regime"] == "cointegrated"
        # Rolling median of the 5 priors = median([0.045,0.04,0.03,0.02,0.01]) = 0.03
        assert row_252["pvalue_rolling_median_5d"] == pytest.approx(0.03)
        # history_depth = number of priors used = 5 (hysteresis active)
        assert row_252["history_depth"] == 5

    def test_history_depth_zero_when_no_priors(self, conn, parquet_one_day):
        # No history seeded — both rows should report history_depth=0
        upsert_from_parquet(conn, parquet_one_day)
        df = query_today(conn)
        # Day-1 bootstrap path: history_depth must be 0 for every row
        assert (df["history_depth"] == 0).all()

    def test_upsert_idempotent_on_same_as_of(self, conn, parquet_one_day):
        # Two upserts of the same parquet → still 2 rows (REPLACE on PK)
        upsert_from_parquet(conn, parquet_one_day)
        upsert_from_parquet(conn, parquet_one_day)
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {TABLE_NAME}").fetchone()["n"]
        assert n == 2

    # --- C3 regime-reset transition tests (2026-05-30) ---

    def test_query_for_classifier_filters_by_methodology(self, conn):
        """When methodology_version is passed, query returns only same-cohort
        priors. Prevents v1+v2 p-value mixing on the math cutover."""
        # Seed 3 v1 rows (oldest p-values) then 2 v2 rows (most recent).
        self._seed_history(conn, [0.50, 0.40, 0.30], methodology="v1_raw_adf")
        # _seed_history starts at 2026-05-01; second call starts again — collide
        # on the as_of PK. Use direct inserts at later dates instead.
        base = pd.Timestamp("2026-05-04", tz="UTC")
        inserted_at = datetime.now(timezone.utc).isoformat()
        for i, p in enumerate([0.20, 0.10]):
            as_of = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                f"INSERT INTO {TABLE_NAME} ({', '.join(DB_COLUMNS)}) VALUES ({', '.join(['?']*len(DB_COLUMNS))})",
                (as_of, "EURUSD", "USDJPY", "1d", 252, "2025-09-01", as_of,
                 252, p, None, 0, -4.0, 10.0, 1.0, "ols_static", "eg_mackinnon",
                 0.0, "broken", "v0", inserted_at, "v2_log_eg"),
            )
        conn.commit()
        # Unfiltered: returns all 5
        all_priors = query_for_classifier(
            conn, "EURUSD", "USDJPY", 252, before_as_of="2026-05-10")
        assert all_priors == [0.10, 0.20, 0.30, 0.40, 0.50]
        # v2 filter: returns only 2 v2 priors
        v2_priors = query_for_classifier(
            conn, "EURUSD", "USDJPY", 252,
            methodology_version="v2_log_eg",
            before_as_of="2026-05-10")
        assert v2_priors == [0.10, 0.20]
        # v1 filter: returns only 3 v1 priors
        v1_priors = query_for_classifier(
            conn, "EURUSD", "USDJPY", 252,
            methodology_version="v1_raw_adf",
            before_as_of="2026-05-10")
        assert v1_priors == [0.30, 0.40, 0.50]

    def test_hysteresis_resets_at_methodology_cutover(self, conn, tmp_path):
        """End-to-end: 5 v1 priors + 1 v2 row → v2 row's regime is classified
        from current p-value alone (bootstrap path), NOT from the v1 priors.

        Locked decision (2026-05-30): regime reset until ≥5 v2 rows exist per
        pair-window. The query filter + classify_regime's existing
        bootstrap-when-priors<5 path compose to deliver this naturally."""
        # Seed 5 v1 priors all cointegrated (p<0.05). Under v1 history, the
        # hysteresis would lock the regime to "cointegrated" if mixing were
        # allowed. With methodology filter, v2 sees 0 priors → bootstrap.
        self._seed_history(conn, [0.01, 0.02, 0.03, 0.04, 0.045],
                            methodology="v1_raw_adf")

        # Write a v2 parquet row whose adf_pvalue is in the BREAKING zone
        # (0.05 ≤ p < 0.10). If hysteresis incorrectly mixed v1 priors in,
        # the regime would lock to "cointegrated" (4+ of 5 priors < 0.05).
        # With reset, current-pvalue alone → "breaking".
        v2_pq_path = tmp_path / "v2.parquet"
        v2_row = _make_parquet_row(
            "2026-05-20", "EURUSD", "USDJPY", 252, 0.07,  # in breaking zone
            regime="breaking", methodology_version="v2_log_eg")
        pd.DataFrame([v2_row], columns=PARQUET_COLUMNS).to_parquet(
            v2_pq_path, index=False)
        upsert_from_parquet(conn, v2_pq_path)

        # The v2 row should be classified by the bootstrap path (no same-
        # methodology priors), so regime = "breaking" purely from p=0.07.
        df = query_today(conn)
        assert len(df) == 1
        v2 = df.iloc[0]
        assert v2["methodology_version"] == "v2_log_eg"
        assert v2["regime"] == "breaking", (
            "v2 row classified using v1 priors — methodology filter not "
            "applied; expected bootstrap-from-current-pvalue (regime=breaking)"
        )
        # history_depth = 0 confirms zero same-methodology priors used.
        assert v2["history_depth"] == 0
        # And the rolling median is None for the same reason.
        assert v2["pvalue_rolling_median_5d"] is None or pd.isna(v2["pvalue_rolling_median_5d"])

    def test_history_query_returns_oldest_first(self, conn):
        self._seed_history(conn, [0.50, 0.40, 0.30, 0.20, 0.10])
        hist = query_history(conn, "EURUSD", "USDJPY", 252, days=10)
        # oldest first
        assert hist["as_of"].iloc[0] == "2026-05-01"
        assert hist["as_of"].iloc[-1] == "2026-05-05"
