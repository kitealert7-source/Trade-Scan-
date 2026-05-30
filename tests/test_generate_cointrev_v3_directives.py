"""test_generate_cointrev_v3_directives.py — v2 cointegration corpus generator tests.

Validates tools/generate_cointrev_v3_directives.py against the look-ahead-safe
N=5 confirmation model. All series-level tests use hand-crafted lists; only the
end-to-end directive emission test touches SQLite (via a tmp_path DB, never the
production cointegration.db).

Look-ahead-safe convention under test (see section A of the design contract):
  - For a span of consecutive 'cointegrated' rows starting at onset_idx and
    last cointegrated at last_coint_idx with break_idx = last_coint_idx + 1
    (or None if open):
      * ncoint = last_coint_idx - onset_idx + 1  (= onset day + confirmation days)
      * span qualifies iff ncoint >= N + 1
      * entry_idx = onset_idx + N + 1 (the bar AFTER the Nth confirmation day)
      * if entry_idx >= len(series): skip (confirmation completes off the end)
      * exit_idx  = break_idx + 1 (the bar AFTER the break is observable)
                    or last index for open-at-end spans

Per design contract section E (7 required tests).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Module under test is being authored in parallel; we import lazily inside the
# tests / fixtures that need it so collection still works if a partial commit
# lands first. The CI gate is `pytest`, which will surface ImportError loudly
# at test-time rather than at collection-time.
from tools.generate_cointrev_v3_directives import (  # noqa: E402
    DEFAULT_CONFIRMATION_N,
    generate_directives,
    spans_confirmation_safe,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic regime series
# ---------------------------------------------------------------------------


def _series(start_date: str, regimes: list[str]) -> list[tuple[str, str]]:
    """Build a list[(as_of_iso, regime_str)] starting at start_date, +1 day per row.

    Uses naive date arithmetic over the proleptic Gregorian calendar — every
    row advances by one calendar day regardless of weekends, mirroring the
    way cointegration_daily emits one row per as_of in production (the
    spans_confirmation_safe contract operates on index positions, not on
    calendar deltas, so weekend gaps in the real series don't matter to the
    return values — only the index math matters).
    """
    from datetime import date, timedelta
    d0 = date.fromisoformat(start_date)
    return [
        ((d0 + timedelta(days=i)).isoformat(), r)
        for i, r in enumerate(regimes)
    ]


# ---------------------------------------------------------------------------
# Tmp-DB fixture pattern
# ---------------------------------------------------------------------------
#
# Tests that exercise generate_directives() end-to-end need a SQLite DB shaped
# like the real cointegration_daily table but isolated from production. The
# fixture below:
#   1. Builds a tmp_path / "cointegration.db" using the production schema via
#      tools.cointegration_db.connect + create_tables (so any schema drift is
#      caught at test-time — the test will fail if the production schema
#      changes in a way that breaks INSERT statements).
#   2. Seeds rows directly with INSERT statements (bypasses parquet → upsert
#      enrichment). The generator only reads as_of / pair_a / pair_b / tf /
#      lookback_days / regime / methodology_version, so we only have to fill
#      those plus the NOT NULL columns the schema requires.
#   3. Passes the tmp DB path to generate_directives via db_path= argument,
#      AND points output_dir at tmp_path so no production directives are
#      written.
# Production cointegration.db is never touched.


@pytest.fixture
def tmp_coint_db(tmp_path):
    """Construct a tmp SQLite DB with the production cointegration_daily schema.

    Returns the path to the DB; caller is responsible for seeding rows.
    """
    from tools.cointegration_db import connect, create_tables
    db = tmp_path / "cointegration.db"
    conn = connect(db)
    create_tables(conn)
    conn.close()
    return db


def _seed_pair(
    db_path: Path,
    pair_a: str,
    pair_b: str,
    series: list[tuple[str, str]],
    *,
    tf: str = "1d",
    lookback_days: int = 252,
    methodology_version: str = "v2_log_eg",
) -> None:
    """INSERT a regime series for one pair-window into a tmp DB.

    Fills all NOT NULL columns with stable placeholders; only regime + as_of
    vary across rows (those are the columns the generator reads).
    """
    from tools.cointegration_db import DB_COLUMNS, TABLE_NAME
    inserted_at = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(DB_COLUMNS)
    placeholders = ", ".join(["?"] * len(DB_COLUMNS))
    conn = sqlite3.connect(str(db_path))
    try:
        for as_of, regime in series:
            row = (
                as_of, pair_a, pair_b, tf, int(lookback_days),
                as_of, as_of, int(lookback_days),
                0.03 if regime == "cointegrated" else 0.20,
                None,  # pvalue_rolling_median_5d
                0,     # history_depth
                -3.5,  # adf_statistic
                10.0,  # half_life_days
                1.5,   # hedge_ratio
                "ols_static",   # beta_method
                "eg_mackinnon", # test_method
                0.5,   # current_zscore
                regime,
                "synthetic-data-v1",  # data_version
                inserted_at,
                methodology_version,
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})",
                row,
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Section E tests
# ---------------------------------------------------------------------------


def test_spans_confirmation_safe_basic():
    """Contract E.(1): 8 rows, days 1-6 cointegrated, days 7-8 broken. N=5.

    ncoint = 6 (onset_idx=0, last_coint_idx=5)
    entry_idx = onset_idx + N + 1 = 0 + 5 + 1 = 6 → series[6] (day 7 / first break)
    break_idx = 6 → exit_idx = break_idx + 1 = 7 → series[7] (day 8)
    """
    series = _series("2024-01-01", ["cointegrated"] * 6 + ["broken"] * 2)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 1, f"expected exactly 1 span, got {len(out)}: {out}"
    entry_date, exit_date, ncoint = out[0]
    assert entry_date == series[6][0], (
        f"entry_date should be series[6][0]={series[6][0]}, got {entry_date}"
    )
    assert exit_date == series[7][0], (
        f"exit_date should be series[7][0]={series[7][0]}, got {exit_date}"
    )
    assert ncoint == 6, f"ncoint should be 6, got {ncoint}"


def test_spans_confirmation_safe_just_at_threshold():
    """Contract E.(2): 6 rows all cointegrated. N=5.

    ncoint = 6, satisfies >= N+1 = 6. entry_idx = 0 + 5 + 1 = 6 = len(series).
    Confirmation completes off the end of data → skip → empty list.
    """
    series = _series("2024-01-01", ["cointegrated"] * 6)
    out = spans_confirmation_safe(series, N=5)
    assert out == [], (
        f"span with entry_idx==len(series) must be skipped, got {out}"
    )


def test_spans_confirmation_safe_below_threshold():
    """Contract E.(3): 5 coint + 2 broken. N=5. ncoint=5 < N+1=6 → no qualifying span."""
    series = _series("2024-01-01", ["cointegrated"] * 5 + ["broken"] * 2)
    out = spans_confirmation_safe(series, N=5)
    assert out == [], f"ncoint=5 should not qualify with N=5 (needs >= 6), got {out}"


def test_spans_confirmation_safe_open_at_end():
    """Contract E.(4): 10 rows all cointegrated, no break. N=5.

    ncoint = 10 >= 6. entry_idx = 6. break_idx = None → exit = series[-1][0].
    """
    series = _series("2024-01-01", ["cointegrated"] * 10)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 1, f"expected 1 open-ended span, got {len(out)}: {out}"
    entry_date, exit_date, ncoint = out[0]
    assert entry_date == series[6][0], (
        f"entry_date should be series[6][0]={series[6][0]}, got {entry_date}"
    )
    assert exit_date == series[-1][0] == series[9][0], (
        f"exit_date should be series[-1][0]={series[-1][0]}, got {exit_date}"
    )
    assert ncoint == 10, f"ncoint should be 10, got {ncoint}"


def test_spans_confirmation_safe_multiple_spans():
    """Contract E.(5): 8 coint + 3 broken + 7 coint + 2 broken. N=5.

    Span 1: onset_idx=0, ncoint=8 >= 6, entry_idx=6, break_idx=8, exit=series[9].
    Span 2: onset_idx=11, ncoint=7 >= 6, entry_idx=11+5+1=17, break_idx=18,
            exit=series[19].
    """
    regimes = (
        ["cointegrated"] * 8 + ["broken"] * 3
        + ["cointegrated"] * 7 + ["broken"] * 2
    )
    series = _series("2024-01-01", regimes)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 2, f"expected 2 qualifying spans, got {len(out)}: {out}"

    e1_date, x1_date, n1 = out[0]
    assert e1_date == series[6][0], (
        f"span 1 entry should be series[6][0]={series[6][0]}, got {e1_date}"
    )
    assert x1_date == series[9][0], (
        f"span 1 exit should be series[9][0]={series[9][0]} (break_idx=8 +1), got {x1_date}"
    )
    assert n1 == 8, f"span 1 ncoint should be 8, got {n1}"

    e2_date, x2_date, n2 = out[1]
    assert e2_date == series[17][0], (
        f"span 2 entry should be series[17][0]={series[17][0]} (onset 11 + N + 1), got {e2_date}"
    )
    assert x2_date == series[19][0], (
        f"span 2 exit should be series[19][0]={series[19][0]} (break_idx=18 +1), got {x2_date}"
    )
    assert n2 == 7, f"span 2 ncoint should be 7, got {n2}"


def test_directive_yaml_well_formed(tmp_coint_db, tmp_path):
    """Contract E.(6): End-to-end emit + YAML parse.

    Seeds one pair guaranteed to produce 1 span (15 coint rows + 3 broken),
    runs generate_directives in non-dry-run mode against the tmp DB + tmp
    output dir, and validates the resulting YAML structure.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    # 15 coint + 3 broken: ncoint=15 >= 6, entry_idx=6, break_idx=15, exit=series[16].
    series = _series("2024-01-01", ["cointegrated"] * 15 + ["broken"] * 3)
    _seed_pair(tmp_coint_db, pair_a, pair_b, series)

    out_dir = tmp_path / "out_directives"
    written = generate_directives(
        tf="1d",
        lookback_days=252,
        N=5,
        output_dir=out_dir,
        db_path=tmp_coint_db,
        dry_run=False,
    )
    assert len(written) == 1, (
        f"expected 1 directive written for 1 qualifying span, got {len(written)}: {written}"
    )

    directive_path = Path(written[0])
    assert directive_path.exists(), f"emitted path does not exist: {directive_path}"
    assert directive_path.suffix == ".txt", (
        f"directive should be a .txt file, got {directive_path.name}"
    )

    parsed = yaml.safe_load(directive_path.read_text(encoding="utf-8"))

    expected_entry = series[6][0]   # 2024-01-07
    expected_exit  = series[16][0]  # 2024-01-17 (break_idx=15 +1)
    yymmdd = expected_entry[2:4] + expected_entry[5:7] + expected_entry[8:10]

    # E.6 assertions
    assert parsed["test"]["start_date"] == expected_entry, (
        f"start_date must match entry_date {expected_entry}, "
        f"got {parsed['test']['start_date']}"
    )
    assert parsed["test"]["end_date"] == expected_exit, (
        f"end_date must match exit_date {expected_exit}, "
        f"got {parsed['test']['end_date']}"
    )
    assert f"__E{yymmdd}" in parsed["test"]["name"], (
        f"test.name must embed entry-date-derived stamp __E{yymmdd}, "
        f"got name={parsed['test']['name']!r}"
    )
    assert parsed["test"]["family"] == "PORT", (
        f"family must be PORT, got {parsed['test']['family']!r}"
    )

    leg_symbols = {leg["symbol"] for leg in parsed["basket"]["legs"]}
    assert leg_symbols == {pair_a, pair_b}, (
        f"basket.legs must carry both pair symbols, got {leg_symbols}"
    )


def test_default_confirmation_is_5():
    """Contract E.(7): frozen default — accidental drift must fail this test."""
    assert DEFAULT_CONFIRMATION_N == 5, (
        f"DEFAULT_CONFIRMATION_N must equal 5 "
        f"(matches HYSTERESIS_LOOKBACK in tools/cointegration_db.py), "
        f"got {DEFAULT_CONFIRMATION_N!r}"
    )
