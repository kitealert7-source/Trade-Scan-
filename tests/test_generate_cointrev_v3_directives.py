"""test_generate_cointrev_v3_directives.py — v2 cointegration corpus generator tests.

Validates tools/generate_cointrev_v3_directives.py against the look-ahead-safe
N=5 confirmation model. All series-level tests use hand-crafted lists; only the
end-to-end directive emission test touches SQLite (via a tmp_path DB, never the
production cointegration.db).

Look-ahead-safe convention under test (revised 2026-05-30 — exit = last_coint_idx
per operator decision; see CR-EXIT-FIX in COINTEGRATION_V1_TO_V2_TRANSITION.md):
  - For a span of consecutive 'cointegrated' rows starting at onset_idx and
    last cointegrated at last_coint_idx with break_idx = last_coint_idx + 1
    (or None if open):
      * ncoint = last_coint_idx - onset_idx + 1  (= onset day + confirmation days)
      * entry_idx = onset_idx + N + 1  (bar AFTER the Nth confirmation day)
      * span qualifies iff entry_idx <= last_coint_idx (i.e. ncoint >= N + 2)
        AND entry_idx < len(series)
      * exit_idx  = last_coint_idx (last cointegrated bar of the span;
                    for open spans this equals len(series) - 1)

The directive's [start_date, end_date] therefore lies inside a single
continuous cointegrated regime, satisfying the window_validity_gate's
containment rule (operator-locked 2026-05-28).

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
    _verify_gate_compatibility,
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
    """Contract E.(1): 10 rows, days 1-8 cointegrated, days 9-10 broken. N=5.

    ncoint = 8 (onset_idx=0, last_coint_idx=7)
    entry_idx = onset_idx + N + 1 = 0 + 5 + 1 = 6 → series[6] (cointegrated)
    entry_idx (6) <= last_coint_idx (7) → qualifies
    exit_idx = last_coint_idx = 7 → series[7] (last cointegrated bar)
    """
    series = _series("2024-01-01", ["cointegrated"] * 8 + ["broken"] * 2)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 1, f"expected exactly 1 span, got {len(out)}: {out}"
    entry_date, exit_date, ncoint = out[0]
    assert entry_date == series[6][0], (
        f"entry_date should be series[6][0]={series[6][0]}, got {entry_date}"
    )
    assert exit_date == series[7][0], (
        f"exit_date should be series[7][0]={series[7][0]} (= last_coint_idx), "
        f"got {exit_date}"
    )
    assert ncoint == 8, f"ncoint should be 8, got {ncoint}"


def test_spans_confirmation_safe_just_at_threshold():
    """Contract E.(2): 6 rows all cointegrated. N=5.

    ncoint = 6, satisfies the old >= N+1 = 6 check, BUT entry_idx = 6 ==
    len(series), so confirmation completes off the end of data → skip.
    Under the revised exit rule the qualification is ncoint >= N+2 = 7,
    which this span also fails — empty list either way.
    """
    series = _series("2024-01-01", ["cointegrated"] * 6)
    out = spans_confirmation_safe(series, N=5)
    assert out == [], (
        f"span with entry_idx==len(series) must be skipped, got {out}"
    )


def test_spans_confirmation_safe_below_threshold():
    """Contract E.(3): 6 coint + 2 broken. N=5.

    ncoint = 6 (onset_idx=0, last_coint_idx=5), entry_idx = 6.
    entry_idx (6) > last_coint_idx (5) — entry would be AFTER the
    cointegrated span ends, so SKIP. Minimum tradable span requires
    ncoint >= N + 2 = 7.
    """
    series = _series("2024-01-01", ["cointegrated"] * 6 + ["broken"] * 2)
    out = spans_confirmation_safe(series, N=5)
    assert out == [], (
        f"ncoint=6 should not qualify with N=5 under exit=last_coint rule "
        f"(needs ncoint >= 7), got {out}"
    )


def test_spans_confirmation_safe_open_at_end():
    """Contract E.(4): 10 rows all cointegrated, no break. N=5.

    ncoint = 10 >= 7. onset_idx=0, last_coint_idx=9, entry_idx = 6.
    Open span (no observed break). exit = series[last_coint_idx][0] =
    series[9][0] = series[-1][0] (last_coint_idx == len-1 by construction
    for open spans).
    """
    series = _series("2024-01-01", ["cointegrated"] * 10)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 1, f"expected 1 open-ended span, got {len(out)}: {out}"
    entry_date, exit_date, ncoint = out[0]
    assert entry_date == series[6][0], (
        f"entry_date should be series[6][0]={series[6][0]}, got {entry_date}"
    )
    assert exit_date == series[-1][0] == series[9][0], (
        f"exit_date should be series[-1][0]={series[-1][0]} (= last_coint_idx for open spans), "
        f"got {exit_date}"
    )
    assert ncoint == 10, f"ncoint should be 10, got {ncoint}"


def test_spans_confirmation_safe_multiple_spans():
    """Contract E.(5): 8 coint + 3 broken + 9 coint + 2 broken. N=5.

    Span 1: onset_idx=0, last_coint_idx=7, ncoint=8 >= 7, entry_idx=6,
            exit = series[last_coint_idx] = series[7].
    Span 2: onset_idx=11, last_coint_idx=19, ncoint=9 >= 7,
            entry_idx = 11 + 5 + 1 = 17,
            exit = series[last_coint_idx] = series[19].
    """
    regimes = (
        ["cointegrated"] * 8 + ["broken"] * 3
        + ["cointegrated"] * 9 + ["broken"] * 2
    )
    series = _series("2024-01-01", regimes)
    out = spans_confirmation_safe(series, N=5)
    assert len(out) == 2, f"expected 2 qualifying spans, got {len(out)}: {out}"

    e1_date, x1_date, n1 = out[0]
    assert e1_date == series[6][0], (
        f"span 1 entry should be series[6][0]={series[6][0]}, got {e1_date}"
    )
    assert x1_date == series[7][0], (
        f"span 1 exit should be series[7][0]={series[7][0]} (= last_coint_idx), got {x1_date}"
    )
    assert n1 == 8, f"span 1 ncoint should be 8, got {n1}"

    e2_date, x2_date, n2 = out[1]
    assert e2_date == series[17][0], (
        f"span 2 entry should be series[17][0]={series[17][0]} (onset 11 + N + 1), got {e2_date}"
    )
    assert x2_date == series[19][0], (
        f"span 2 exit should be series[19][0]={series[19][0]} (= last_coint_idx), got {x2_date}"
    )
    assert n2 == 9, f"span 2 ncoint should be 9, got {n2}"


def test_directive_yaml_well_formed(tmp_coint_db, tmp_path):
    """Contract E.(6): End-to-end emit + YAML parse.

    Seeds one pair guaranteed to produce 1 span (15 coint rows + 3 broken),
    runs generate_directives in non-dry-run mode against the tmp DB + tmp
    output dir, and validates the resulting YAML structure.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    # 15 coint + 3 broken: ncoint=15 >= 7, entry_idx=6, last_coint_idx=14,
    # exit = series[last_coint_idx] = series[14].
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
    expected_exit  = series[14][0]  # 2024-01-15 (= last_coint_idx)
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


# ---------------------------------------------------------------------------
# Section F — gate-compatibility verification (CR-EXIT-FIX 2026-05-30, F1)
# ---------------------------------------------------------------------------
#
# F.1 happy path: samples that align with window_validity_gate's containment
#     rule pass without raising.
# F.2 fail path:  a hand-constructed bad sample (exit_date past last_coint_idx)
#     triggers RuntimeError with the gate's reject_reason in the message.
# F.3 empty case: no spans = no-op, no exception.


def test_verify_gate_compatibility_passes_on_valid_samples(
    tmp_coint_db, monkeypatch
):
    """F.1 — samples produced by spans_confirmation_safe (with the post-CR-EXIT-FIX
    rule exit=last_coint_date) all pass window_validity_gate containment."""
    pair_a, pair_b = "EURUSD", "USDJPY"
    # 15 coint + 3 broken: spans_confirmation_safe emits entry=series[6],
    # exit=series[14] (= last_coint_idx). The window fully sits inside the
    # cointegrated span [series[0], series[14]] -> gate PASS.
    series = _series("2024-01-01", ["cointegrated"] * 15 + ["broken"] * 3)
    _seed_pair(tmp_coint_db, pair_a, pair_b, series)

    # Patch the gate's DB_PATH so evaluate_window_validity reads our tmp DB
    # instead of the production cointegration.db.
    monkeypatch.setattr("tools.window_validity_gate.DB_PATH", tmp_coint_db)

    # Build spans list as spans_confirmation_safe would emit:
    # (pair_a, pair_b, entry_date, exit_date, ncoint)
    spans = [(pair_a, pair_b, series[6][0], series[14][0], 15)]

    # Should return None without raising.
    result = _verify_gate_compatibility(spans)
    assert result is None, "happy-path helper should return None"


def test_verify_gate_compatibility_blocks_on_reject(
    tmp_coint_db, monkeypatch
):
    """F.2 — a hand-constructed bad sample (exit_date PAST last_coint_idx,
    simulating the pre-CR-EXIT-FIX exit=break+1 rule) triggers RuntimeError
    BEFORE any bulk write. This is exactly the failure mode the helper exists
    to catch.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    # 15 coint + 3 broken; last_coint_idx = 14 (series[14] = '2024-01-15').
    # Cointegrated span ends 2024-01-15; series[16] = '2024-01-17' is BREAKING.
    series = _series("2024-01-01", ["cointegrated"] * 15 + ["broken"] * 3)
    _seed_pair(tmp_coint_db, pair_a, pair_b, series)
    monkeypatch.setattr("tools.window_validity_gate.DB_PATH", tmp_coint_db)

    # Manually inject exit_date=series[16] — 2 bars past last_coint_idx, in
    # the breaking regime. This is the pre-CR-EXIT-FIX exit=break+1 shape.
    bad_spans = [(pair_a, pair_b, series[6][0], series[16][0], 15)]

    with pytest.raises(RuntimeError) as exc_info:
        _verify_gate_compatibility(bad_spans)

    msg = str(exc_info.value)
    assert "GATE-VERIFY" in msg, f"error must be tagged [GATE-VERIFY], got {msg!r}"
    assert "REJECTED" in msg, f"error must surface REJECTED, got {msg!r}"
    assert pair_a in msg and pair_b in msg, (
        f"error must name the pair, got {msg!r}"
    )
    assert "CR-EXIT-FIX" in msg, (
        f"error must point at the historical motivator for remediation context"
    )


def test_verify_gate_compatibility_empty_spans_is_noop():
    """F.3 — empty span list = no-op, no exception, no DB read."""
    result = _verify_gate_compatibility([])
    assert result is None


# ---------------------------------------------------------------------------
# Section G — custom p-threshold (2026-06-02: confirmation-window experiments)
# ---------------------------------------------------------------------------
#
# The generator default reads the `regime` column directly (screener-default
# threshold, p<0.05). With --p-threshold set, it re-derives `regime` on the fly
# from the stored `adf_pvalue` column. Tests lock the contract:
#   G.1 default (p_threshold=None) keeps reading the regime column unchanged
#   G.2 a tighter threshold filters out borderline-cointegrated rows
#   G.3 a non-tightening threshold (>= screener's) reproduces the default spans
#   G.4 directive names carry the _P03 / _P02 tag to prevent cohort collisions
#   G.5 invalid threshold values raise ValueError before any DB read


def _seed_pair_with_pvalues(
    db_path: Path,
    pair_a: str,
    pair_b: str,
    rows: list[tuple[str, str, float]],  # (as_of, regime, adf_pvalue)
    *,
    tf: str = "1d",
    lookback_days: int = 252,
    methodology_version: str = "v2_log_eg",
) -> None:
    """Variant of ``_seed_pair`` that takes explicit per-row p-values.

    Lets G-tests stage rows where the screener's recorded ``regime`` and
    the raw ``adf_pvalue`` independently encode admissibility, so the
    ``p_threshold`` filter path can be exercised against a known mix.
    """
    from tools.cointegration_db import DB_COLUMNS, TABLE_NAME
    inserted_at = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(DB_COLUMNS)
    placeholders = ", ".join(["?"] * len(DB_COLUMNS))
    conn = sqlite3.connect(str(db_path))
    try:
        for as_of, regime, pvalue in rows:
            row = (
                as_of, pair_a, pair_b, tf, int(lookback_days),
                as_of, as_of, int(lookback_days),
                float(pvalue),
                None, 0,
                -3.5, 10.0, 1.5,
                "ols_static", "eg_mackinnon",
                0.5, regime, "synthetic-data-v1",
                inserted_at, methodology_version,
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {TABLE_NAME} ({cols}) VALUES ({placeholders})",
                row,
            )
        conn.commit()
    finally:
        conn.close()


def test_p_threshold_default_uses_regime_column(tmp_coint_db, tmp_path):
    """G.1: ``p_threshold=None`` (default) reads the ``regime`` column directly,
    NOT the p-value. A row labelled 'cointegrated' with p=0.99 still qualifies.

    This locks the default-path contract: existing behavior is byte-equivalent
    for callers that don't pass ``--p-threshold``.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    # 15 'cointegrated' rows with absurdly HIGH p-values (would fail any real
    # threshold) + 3 'broken' rows. With p_threshold=None, the regime column
    # alone determines admission -> one span as in test E.6.
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.99) for i in range(1, 16)]
        + [(f"2024-01-{i:02d}", "broken", 0.99) for i in range(16, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_default",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=None,  # default
    )
    assert len(written) == 1, (
        f"default p_threshold=None must use regime column "
        f"(ignoring p-values), expected 1 span, got {len(written)}"
    )


def test_p_threshold_filters_borderline_pvalues(tmp_coint_db, tmp_path):
    """G.2: a TIGHTER threshold (e.g. 0.03) excludes rows the screener admitted
    at p<0.05. The 'cointegrated'-labelled rows with p=0.04 are filtered out;
    only the p<0.03 sub-series remains cointegrated -> fewer/no spans.

    This locks the on-the-fly re-derivation contract: ``regime = cointegrated
    iff adf_pvalue < p_threshold`` is what gets fed into ``spans_confirmation_safe``.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    # All 18 rows are 'cointegrated' per the screener's column, but their
    # p-values straddle 0.03. Under p_threshold=0.03 only rows with p<0.03
    # count -- which in this layout is days 1-8 (p=0.01), then day 9 onward
    # have p=0.04 -> filtered out -> only the first run of cointegrated days
    # survives. With days 1-8 'cointegrated' at p<0.03 and day 9+ effectively
    # 'not_cointegrated', spans_confirmation_safe at N=5 finds one span
    # (entry=day 7, exit=day 8) per E.1.
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.01) for i in range(1, 9)]
        + [(f"2024-01-{i:02d}", "cointegrated", 0.04) for i in range(9, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_filtered",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=0.03,
    )
    assert len(written) == 1, (
        f"with p_threshold=0.03 only the p<0.03 prefix should remain "
        f"cointegrated; expected 1 span, got {len(written)}"
    )


def test_p_threshold_loose_reproduces_regime_column(tmp_coint_db, tmp_path):
    """G.3: a threshold that admits ALL the cointegrated-labelled rows but
    NONE of the broken ones reproduces the screener-default span set.

    Critical: the regime column and the on-the-fly re-derivation must AGREE
    on every row, otherwise the window_validity_gate (which reads the
    stored regime column directly to validate end_date containment) will
    reject the directive. So 'loose' here means "above all cointegrated
    rows' p-values, below all broken rows' p-values". With p_threshold
    inside the [coint_max, broken_min) interval, results match the
    regime-column path.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.01) for i in range(1, 16)]
        + [(f"2024-01-{i:02d}", "broken", 0.50) for i in range(16, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_loose",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=0.10,  # admits coint rows (0.01) but excludes broken (0.50)
    )
    assert len(written) == 1, (
        f"with p_threshold=0.10 the 15-row coint prefix qualifies; broken "
        f"rows at p=0.50 are excluded; one span should emerge as in E.6; "
        f"got {len(written)}"
    )


def test_p_threshold_encodes_in_directive_name(tmp_coint_db, tmp_path):
    """G.4: directive filename + test.name carry the _P03 / _P02 tag.

    Critical for cohort isolation: without this, p<0.05 and p<0.03
    directives that happen to land on the same (pair, entry_date) would
    collide in INBOX and the directive-id-set aggregation would conflate
    cohorts.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.01) for i in range(1, 16)]
        + [(f"2024-01-{i:02d}", "broken", 0.50) for i in range(16, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_tag03",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=0.03,
    )
    assert len(written) == 1
    name = Path(written[0]).stem
    assert "_L30_P03__E" in name, (
        f"name must splice _P03 between _L30 and __E (cohort-isolation tag), "
        f"got {name!r}"
    )
    parsed = yaml.safe_load(Path(written[0]).read_text(encoding="utf-8"))
    assert "_L30_P03__E" in parsed["test"]["name"], (
        f"test.name inside the YAML body must also carry the tag, "
        f"got {parsed['test']['name']!r}"
    )

    # And independently with 0.02 -> _P02
    written2 = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_tag02",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=0.02,
    )
    assert len(written2) == 1
    assert "_L30_P02__E" in Path(written2[0]).stem


def test_confirmation_n_encodes_in_directive_name(tmp_coint_db, tmp_path):
    """G.6: a non-default confirmation N carries the _N tag for cohort isolation
    (mirrors the _P p-threshold tag); default N=5 carries NO _N tag so existing
    N=5 cohort stems are preserved. Combined with a p-threshold the order is
    _P01_N0 -> ..._L30_P01_N0__E...
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.005) for i in range(1, 16)]
        + [(f"2024-01-{i:02d}", "broken", 0.50) for i in range(16, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    # N=0 + p<0.01 -> stem + test.name + variant carry _P01_N0 (p_tag then n_tag).
    written = generate_directives(
        tf="1d", lookback_days=252, N=0,
        output_dir=tmp_path / "out_p01_n0",
        db_path=tmp_coint_db, dry_run=False, p_threshold=0.01,
    )
    assert len(written) >= 1
    name = Path(written[0]).stem
    assert "_L30_P01_N0__E" in name, (
        f"non-default N must splice _N0 after the p-tag (cohort isolation), "
        f"got {name!r}"
    )
    parsed = yaml.safe_load(Path(written[0]).read_text(encoding="utf-8"))
    assert "_L30_P01_N0__E" in parsed["test"]["name"]
    assert "_P01_N0" in parsed["test"]["hypothesis_variant"]

    # N=0 alone (no p-threshold) -> _N0 only: ..._L30_N0__E...
    written_n0 = generate_directives(
        tf="1d", lookback_days=252, N=0,
        output_dir=tmp_path / "out_n0",
        db_path=tmp_coint_db, dry_run=False, p_threshold=None,
    )
    assert "_L30_N0__E" in Path(written_n0[0]).stem

    # Default N=5 -> NO _N tag: existing cohort stem ..._L30_P01__E... unchanged.
    written_n5 = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_n5",
        db_path=tmp_coint_db, dry_run=False, p_threshold=0.01,
    )
    assert "_L30_P01__E" in Path(written_n5[0]).stem


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.01, 1.5, 2.0])
def test_p_threshold_invalid_raises(tmp_coint_db, tmp_path, bad):
    """G.5: a p_threshold outside (0, 1) raises ValueError before any DB
    read, naming the bad value. Locks the boundary check.
    """
    with pytest.raises(ValueError, match="p_threshold"):
        generate_directives(
            tf="1d", lookback_days=252, N=5,
            output_dir=tmp_path / "out_bad",
            db_path=tmp_coint_db, dry_run=True,
            p_threshold=bad,
        )


# ---------------------------------------------------------------------------
# Section H — leg-sizing cohort (2026-06-04: current-vs-granular-parity test)
# ---------------------------------------------------------------------------
#
# The generator default emits the equal-notional baseline (sizing_mode absent
# from recycle_rule.params -> the rule defaults to "notional"). With
# --sizing-mode granular_parity it injects sizing_mode + granular_parity_max_k
# and appends a _GP cohort tag. Tests lock the contract:
#   H.1 default ("notional") is byte-clean: NO _GP tag, NO injected params
#       (baseline-arm fidelity is load-bearing for the comparison)
#   H.2 "granular_parity" tags _GP and injects the params additively
#   H.3 the _GP tag composes after the _P / _N tags (order p, n, s)
#   H.4 an unknown sizing_mode raises ValueError before any DB read


def test_sizing_mode_default_notional_is_byte_clean(tmp_coint_db, tmp_path):
    """H.1: the default ("notional") cohort carries NO _GP tag and injects NO
    sizing params -- the baseline arm must be identical to the historical
    production directive, since it stands in for "current sizing" in the
    comparison. Any drift here silently biases the experiment.
    """
    pair_a, pair_b = "EURUSD", "USDJPY"
    series = _series("2024-01-01", ["cointegrated"] * 15 + ["broken"] * 3)
    _seed_pair(tmp_coint_db, pair_a, pair_b, series)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_notional",
        db_path=tmp_coint_db, dry_run=False,
        sizing_mode="notional",
    )
    assert len(written) == 1
    name = Path(written[0]).stem
    assert "_GP" not in name, f"notional baseline must carry no _GP tag, got {name!r}"
    body = Path(written[0]).read_text(encoding="utf-8")
    assert "sizing_mode" not in body, (
        "notional baseline body must not inject a sizing_mode param"
    )
    assert "granular_parity_max_k" not in body
    params = yaml.safe_load(body)["basket"]["recycle_rule"]["params"]
    assert "sizing_mode" not in params and "granular_parity_max_k" not in params


def test_sizing_mode_granular_parity_tags_and_injects(tmp_coint_db, tmp_path):
    """H.2: --sizing-mode granular_parity appends _GP and injects
    sizing_mode + granular_parity_max_k WITHOUT dropping any baseline param
    (additive injection)."""
    pair_a, pair_b = "EURUSD", "USDJPY"
    series = _series("2024-01-01", ["cointegrated"] * 15 + ["broken"] * 3)
    _seed_pair(tmp_coint_db, pair_a, pair_b, series)

    written = generate_directives(
        tf="1d", lookback_days=252, N=5,
        output_dir=tmp_path / "out_gp",
        db_path=tmp_coint_db, dry_run=False,
        sizing_mode="granular_parity",
    )
    assert len(written) == 1
    name = Path(written[0]).stem
    assert "_L30_GP__E" in name, (
        f"granular_parity must splice _GP between _L30 and __E, got {name!r}"
    )
    parsed = yaml.safe_load(Path(written[0]).read_text(encoding="utf-8"))
    assert "_L30_GP__E" in parsed["test"]["name"]
    assert "_GP" in parsed["test"]["hypothesis_variant"]
    params = parsed["basket"]["recycle_rule"]["params"]
    assert params["sizing_mode"] == "granular_parity"
    assert params["granular_parity_max_k"] == 8
    # additive: baseline params survive the injection
    assert params["target_notional_per_leg_usd"] == 1000.0
    assert params["n_window"] == 30
    assert params["z_entry"] == 2.0


def test_sizing_mode_tag_composes_after_p_and_n(tmp_coint_db, tmp_path):
    """H.3: with a p-threshold + non-default N + granular_parity, the name
    carries _P01_N0_GP in that order (p_tag, n_tag, s_tag). Locks the cohort
    tag ordering so multi-axis cohorts never collide."""
    pair_a, pair_b = "EURUSD", "USDJPY"
    rows = (
        [(f"2024-01-{i:02d}", "cointegrated", 0.005) for i in range(1, 16)]
        + [(f"2024-01-{i:02d}", "broken", 0.50) for i in range(16, 19)]
    )
    _seed_pair_with_pvalues(tmp_coint_db, pair_a, pair_b, rows)

    written = generate_directives(
        tf="1d", lookback_days=252, N=0,
        output_dir=tmp_path / "out_p01_n0_gp",
        db_path=tmp_coint_db, dry_run=False,
        p_threshold=0.01, sizing_mode="granular_parity",
    )
    assert len(written) >= 1
    name = Path(written[0]).stem
    assert "_L30_P01_N0_GP__E" in name, (
        f"tag order must be p_tag, n_tag, s_tag -> _P01_N0_GP, got {name!r}"
    )


@pytest.mark.parametrize("bad", ["", "beta", "vol_parity", "NOTIONAL", "granular"])
def test_sizing_mode_invalid_raises(tmp_coint_db, tmp_path, bad):
    """H.4: an unknown sizing_mode raises ValueError before any DB read, naming
    the field. Modes valid on the RULE but not exposed by the generator (beta,
    vol_parity) are intentionally rejected here -- the generator only stands up
    the two arms of the current-vs-granular-parity experiment."""
    with pytest.raises(ValueError, match="sizing_mode"):
        generate_directives(
            tf="1d", lookback_days=252, N=5,
            output_dir=tmp_path / "out_bad_sizing",
            db_path=tmp_coint_db, dry_run=True,
            sizing_mode=bad,
        )
