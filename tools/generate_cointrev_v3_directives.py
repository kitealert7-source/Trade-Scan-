"""generate_cointrev_v3_directives.py -- v2 cointegration corpus generator.

Enumerates qualifying continuous-cointegrated spans from the v2_log_eg
cointegration screener (cointegration_daily SQLite table) and stages one
COINTREV_V3 directive per qualifying span.

Methodology vs the legacy tmp/gen_all_episodes.py:
  - Filters on methodology_version='v2_log_eg' (EG/MacKinnon log-prices math),
    NOT the v1_raw_adf cohort the tmp/ script enumerated.
  - Replaces the retrospective `dur >= 45 days` filter with a **look-ahead-safe
    N=5 confirmation model**: a span is admitted only if it has at least
    N+1 consecutive cointegrated bars (one onset day + N confirmation days),
    AND there is at least one further cointegrated bar after the confirmation
    period (so the entry bar lies inside the span). The entry_date is the
    bar AFTER the N confirmation days, so a real-time trader would have
    observed the full confirmation window before opening the position.
  - Exit_date is set to the **last cointegrated bar of the span**
    (last_coint_idx), so [start_date, end_date] is fully inside a single
    continuous cointegrated regime. This matches the window_validity_gate
    "any-span containment" rule (operator-locked 2026-05-28). Treating exit
    as break+1 is a separate strategy-side experiment (live exit fires at
    open of break_idx + 1 via the engine's regime feed, but the BACKTEST
    WINDOW encodes the regime period, not the execution day).

INDEXING CONVENTION (operator-fixed, 2026-05-30 --- do not relitigate)
======================================================================
   onset day             = day 0  (the first bar labeled regime='cointegrated'
                                   that triggers a new span)
   confirmation period   = next N completed business days (default N=5,
                                   i.e. days 1, 2, 3, 4, 5 of the span)
   entry eligibility     = the following business day  (day N+1 of the span,
                                   i.e. onset_idx + N + 1 in the regime series)

This convention answers the recurring "+N vs +N+1" question by anchoring
on the trader's information set: the screener emits the regime label for
day D at the close of day D, so the earliest causal entry bar is day
D+1. Five days of confirmation observed end-of-day for days 1..5 means
the position can be opened at the open of day 6 --- *not* day 5.

Look-ahead-safe convention (see section A of the design contract):
  onset_idx       = first bar of the cointegrated span                (= day 0)
  last_coint_idx  = last bar still labeled 'cointegrated'
  break_idx       = first bar after the span where regime != 'cointegrated'
                    (None when the span is open at end-of-series)
  entry_idx       = onset_idx + N + 1  (bar AFTER the Nth confirmation day,
                                        i.e. day N+1 of the span)
  exit_idx        = last_coint_idx (the last bar still labeled 'cointegrated'
                                    in the span; same for closed and open
                                    spans because last_coint_idx == len-1
                                    when the span is open at series end)
  ncoint          = last_coint_idx - onset_idx + 1   (onset day + run-length)

A span QUALIFIES iff entry_idx <= last_coint_idx, i.e. ncoint >= N + 2.
(Mathematically: entry_idx = onset + N + 1 and last_coint_idx = onset +
ncoint - 1, so the constraint reduces to ncoint - 1 >= N + 1.) Spans whose
entry_idx falls off the end of available data, or that have only the
confirmation period inside the regime (ncoint == N + 1), are skipped ---
there is no causal entry bar inside the cointegrated span.

The default N=5 matches HYSTERESIS_LOOKBACK in tools/cointegration_db.py
(one trading week of confirmation), filters out single-day flickers, and
empirically removes ~50% of unfiltered spans.

Pre-write gate verification (CR-EXIT-FIX 2026-05-30, retro F1 high-ROI):
After span enumeration completes, the generator renders 3 sample directives
(first / median / last) and runs each through
tools.window_validity_gate.evaluate_window_validity(). Any REJECT aborts the
run with the gate's reject_reason -- BEFORE any directive reaches staging.
The historical motivator: the first v2 corpus emitted 527 directives that
ALL failed at window_validity_gate because exit=break+1 contradicted the
gate's containment rule (operator-locked 2026-05-28). A pre-write sample
check would have caught that conflict before any file was written. ~10 ms
overhead per corpus generation.

CLI:
    python tools/generate_cointrev_v3_directives.py --dry-run
    python tools/generate_cointrev_v3_directives.py
    python tools/generate_cointrev_v3_directives.py --confirmation 5 --lookback 252 --tf 1d

Module-level constants (operator-facing defaults):
    DEFAULT_CONFIRMATION_N  = 5    -- one trading week, == HYSTERESIS_LOOKBACK
    DEFAULT_LOOKBACK_DAYS   = 252  -- ~1y; the v2 corpus standard
    DEFAULT_TF              = '1d'
    DEFAULT_OUTPUT_DIR      = backtest_directives/cointrev_v3_staging
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cointegration_db import SQLITE_DB
from tools.cointegration_screen import SUPPORTED_TFS


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIRMATION_N = 5
DEFAULT_LOOKBACK_DAYS = 252
DEFAULT_TF = "1d"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "backtest_directives" / "cointrev_v3_staging"

# Methodology cohort we enumerate. v1_raw_adf was retired 2026-05-30 in
# favour of v2_log_eg (log-prices + Engle-Granger/MacKinnon critical
# values); we only want spans produced by the current math.
METHODOLOGY_VERSION = "v2_log_eg"

# Pair-class membership --- mirrors tmp/gen_all_episodes.py classifier so
# the per-class summary in --dry-run matches operator expectations from
# the legacy script.
_IDX_SYMBOLS = frozenset({
    "FRA40", "UK100", "US30", "AUS200", "EUSTX50", "JPN225", "GER40",
    "ESP35", "NAS100", "SPX500", "US500",
})
_CRY_SYMBOLS = frozenset({"BTCUSD", "ETHUSD"})
_MET_SYMBOLS = frozenset({"XAUUSD"})


def _kind(sym: str) -> str:
    if sym in _IDX_SYMBOLS:
        return "IDX"
    if sym in _CRY_SYMBOLS:
        return "CRY"
    if sym in _MET_SYMBOLS:
        return "MET"
    return "FX"


def _pair_class(a: str, b: str) -> str:
    """Classify a pair-pair for the dry-run summary."""
    kinds = tuple(sorted([_kind(a), _kind(b)]))
    if kinds == ("FX", "FX"):
        return "FX-FX"
    if kinds == ("IDX", "IDX"):
        return "IDX-IDX"
    if "CRY" in kinds or "MET" in kinds:
        return "CRYPTO/METAL"
    if kinds == ("FX", "IDX"):
        return "FX-IDX"
    return "other"


def _dur_days(start: str, end: str) -> int:
    """Calendar days between two YYYY-MM-DD strings (preserved from legacy)."""
    y1, m1, d1 = map(int, start.split("-"))
    y2, m2, d2 = map(int, end.split("-"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days


# ---------------------------------------------------------------------------
# Span enumeration --- LOOK-AHEAD-SAFE
# ---------------------------------------------------------------------------


def spans_confirmation_safe(
    series: list[tuple[str, str]],
    N: int = DEFAULT_CONFIRMATION_N,
) -> list[tuple[str, str, int]]:
    """Enumerate look-ahead-safe (entry_date, exit_date, ncoint) tuples.

    `series` is an ordered list of (as_of_date, regime_label) tuples, one
    per regime snapshot for a single (pair_a, pair_b, lookback_days,
    methodology) cohort.

    For each maximal run of consecutive 'cointegrated' rows:
        onset_idx       = first index of the run
        last_coint_idx  = last index where regime == 'cointegrated'
        break_idx       = first index after last_coint_idx where regime
                          != 'cointegrated' (or None if span is open at
                          end of series)
        ncoint          = last_coint_idx - onset_idx + 1

    A span QUALIFIES iff entry_idx <= last_coint_idx, i.e. there is at
    least one cointegrated bar AFTER the N-day confirmation period.
    Equivalently: ncoint >= N + 2 (onset day + N confirmation days + at
    least one bar to enter on, all still cointegrated).

    For a qualifying span:
        entry_idx  = onset_idx + N + 1
        if entry_idx >= len(series): skip (confirmation off end of data)
        entry_date = series[entry_idx][0]
        exit_date  = series[last_coint_idx][0]
                     (last cointegrated bar in the span; for open-at-end
                     spans, last_coint_idx == len(series) - 1 so this is
                     the latest available as_of)

    Indexing convention (operator-fixed; mirrors module docstring):
        onset day             = day 0
        confirmation period   = next N completed business days (default N=5)
        entry eligibility     = the following business day (day N+1)

    Look-ahead correctness:
        * The Nth confirmation day's regime label is known at the close of
          bar (onset_idx + N), so the trader can act on the open of bar
          (onset_idx + N + 1) --- that's the entry_idx.
        * The exit is the LAST bar still labeled 'cointegrated' in the span;
          the directive's [start_date, end_date] therefore lies entirely
          inside a single continuous cointegrated regime, which is the
          window_validity_gate's containment rule (operator-locked
          2026-05-28). The "live exit on break+1" execution rule is a
          separate strategy-side concern --- the BACKTEST WINDOW encodes
          the regime period, not the execution day.
        * Open spans (no observed break yet) terminate at series[-1] --
          which equals series[last_coint_idx] by construction, since
          last_coint_idx tracks the latest cointegrated bar.

    Edge case --- just-at-threshold (ncoint == N + 1):
        With the new exit rule, a span of exactly N+1 cointegrated days
        has entry_idx = N + 1 but last_coint_idx = N, so entry_idx >
        last_coint_idx and the span is SKIPPED. The minimum tradable span
        is ncoint == N + 2 (one cointegrated bar to enter on; tradable
        duration = 1 bar).

    Returns [] when the series produces no qualifying spans.
    """
    if N < 0:
        raise ValueError(f"N must be >= 0, got {N!r}")

    n_total = len(series)
    out: list[tuple[str, str, int]] = []

    onset_idx: int | None = None
    last_coint_idx: int | None = None

    def _emit_span(
        onset: int, last_coint: int, break_at: int | None
    ) -> None:
        # Two qualification checks:
        #   1. entry_idx must lie inside the cointegrated span
        #      (entry_idx <= last_coint, i.e. ncoint >= N + 2)
        #   2. entry_idx must lie inside the series
        #      (entry_idx <  n_total; covers the case where confirmation
        #       completes only at series-end with no entry bar emitted yet)
        entry_idx = onset + N + 1
        if entry_idx > last_coint:
            return
        if entry_idx >= n_total:
            return
        entry_date = series[entry_idx][0]
        exit_date = series[last_coint][0]
        ncoint = last_coint - onset + 1
        out.append((entry_date, exit_date, ncoint))

    for i, (_as_of, regime) in enumerate(series):
        if regime == "cointegrated":
            if onset_idx is None:
                onset_idx = i
            last_coint_idx = i
        else:
            if onset_idx is not None:
                _emit_span(onset_idx, last_coint_idx, i)
                onset_idx = None
                last_coint_idx = None

    # Open span at end of series --- no observed break.
    if onset_idx is not None:
        _emit_span(onset_idx, last_coint_idx, None)

    return out


# ---------------------------------------------------------------------------
# Directive template --- preserved verbatim from tmp/gen_all_episodes.py
# ---------------------------------------------------------------------------

TEMPLATE = """test:
  name: {name}
  family: PORT
  strategy: {name}
  version: 1
  signal_version: 1
  broker: OctaFx
  timeframe: 15m
  start_date: '{start}'
  end_date: '{end}'
  research_mode: true
  tuning_allowed: false
  parameter_mutation: false
  hypothesis_ref: COINTREV_V3_PINE_RATIOZ
  hypothesis_variant: {variant}
  description: 'Pine z_r reversal port (pine_ratio_zrev_v1), N=30 / 15M / absolute /
    always-in-market, {a}/{b}. Capital 1000 USD, target_notional_per_leg_usd=1000.
    Episode test: natural continuous 252d-cointegrated span {start} -> {end}.
    cointegration_join lookback_days=252 gates (any-span) + routes to the
    cointegration ledger.'
symbols:
- {a}
- {b}
indicators:
- indicators.volatility.atr
execution_rules:
  pyramiding: false
  entry_when_flat_only: true
  reset_on_exit: false
  entry_logic:
    type: pine_zrev_reversal_proposal
  exit_logic:
    type: basket_recycle_rule
  stop_loss:
    type: atr_multiple
    atr_multiplier: 100000.0
  trailing_stop:
    enabled: false
  take_profit:
    enabled: false
order_placement:
  type: market
  execution_timing: next_bar_open
trade_management:
  direction: basket_mixed
  reentry:
    allowed: true
  session_reset: none
position_management:
  lots: 0.01
basket:
  basket_id: {bid}
  legs:
  - symbol: {a}
    lot: 0.01
    direction: long
  - symbol: {b}
    lot: 0.01
    direction: short
  initial_stake_usd: 1000.0
  harvest_threshold_usd: 1000000.0
  cointegration_join:
    lookback_days: 252
  recycle_rule:
    name: pine_ratio_zrev_v1
    version: 1
    params:
      n_window: 30
      n_meta: 100
      z_entry: 2.0
      entry_mode: absolute
      hedge_lock_at_entry: true
      always_in_market: true
      initial_notional_usd: 1000.0
      target_notional_per_leg_usd: 1000.0
      default_initial_lot: 0.01
"""


# ---------------------------------------------------------------------------
# DB read + directive emission
# ---------------------------------------------------------------------------


def _yymmdd(iso_date: str) -> str:
    """'2024-01-15' -> '240115'."""
    return iso_date[2:4] + iso_date[5:7] + iso_date[8:10]


def _read_pairs(
    conn: sqlite3.Connection, tf: str, lookback_days: int, methodology: str
) -> list[tuple[str, str]]:
    cur = conn.execute(
        "SELECT DISTINCT pair_a, pair_b FROM cointegration_daily "
        "WHERE methodology_version = ? AND tf = ? AND lookback_days = ? "
        "ORDER BY pair_a, pair_b",
        (methodology, tf, int(lookback_days)),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _read_series(
    conn: sqlite3.Connection,
    pair_a: str,
    pair_b: str,
    tf: str,
    lookback_days: int,
    methodology: str,
    p_threshold: float | None = None,
) -> list[tuple[str, str]]:
    """Return [(as_of, regime_label)] for the (pair, tf, lookback, methodology) cohort.

    When ``p_threshold`` is None (default), uses the screener-precomputed
    ``regime`` column (which encodes the screener's own p<0.05 threshold).
    When set (e.g. 0.03 or 0.02), re-derives the regime label from the raw
    ``adf_pvalue`` column: ``cointegrated`` iff ``adf_pvalue < p_threshold``.
    The p-value is already stored at row creation time, so this is a pure
    label re-derivation -- no screener re-run.
    """
    if p_threshold is None:
        cur = conn.execute(
            "SELECT as_of, regime FROM cointegration_daily "
            "WHERE pair_a = ? AND pair_b = ? AND tf = ? AND lookback_days = ? "
            "AND methodology_version = ? "
            "ORDER BY as_of",
            (pair_a, pair_b, tf, int(lookback_days), methodology),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]
    cur = conn.execute(
        "SELECT as_of, adf_pvalue FROM cointegration_daily "
        "WHERE pair_a = ? AND pair_b = ? AND tf = ? AND lookback_days = ? "
        "AND methodology_version = ? "
        "ORDER BY as_of",
        (pair_a, pair_b, tf, int(lookback_days), methodology),
    )
    return [
        (r[0], "cointegrated" if (r[1] is not None and r[1] < p_threshold) else "not_cointegrated")
        for r in cur.fetchall()
    ]


def _render_directive(
    pair_a: str,
    pair_b: str,
    entry_date: str,
    exit_date: str,
    *,
    p_tag: str = "",
    n_tag: str = "",
) -> tuple[str, str]:
    """Return (filename_stem, yaml_body) for a single span.

    Filename + variant E-stamp are derived from entry_date (NOT onset),
    so the E-stamp encodes the look-ahead-safe entry boundary that the
    trader would actually act on.

    ``p_tag`` (e.g. ``"_P03"``, ``"_P02"``) and ``n_tag`` (e.g. ``"_N0"``) are
    spliced into the name and variant after ``_L30`` to mark cohorts generated
    under a tighter cointegration p-threshold and/or a non-default confirmation
    window N. Both empty for the baseline (screener-default p<0.05, N=5). They
    prevent directive-id collision across cohorts when the same (pair,
    entry_date) tuple is produced by multiple thresholds or N values (same slot
    as existing exit-variant tokens such as ``_ZBND`` / ``_ZCRS``). Order is
    ``{p_tag}{n_tag}`` -> e.g. ``_L30_P01_N0``.
    """
    bid = f"{pair_a}{pair_b}"
    yymmdd = _yymmdd(entry_date)
    name = f"90_PORT_{bid}_15M_COINTREV_V3_L30{p_tag}{n_tag}__E{yymmdd}"
    variant = f"COINTREV_V3_PINE_RATIOZ_{pair_a}_{pair_b}_N30_15M_ABS{p_tag}{n_tag}_E{yymmdd}"
    body = TEMPLATE.format(
        name=name,
        start=entry_date,
        end=exit_date,
        variant=variant,
        a=pair_a,
        b=pair_b,
        bid=bid,
    )
    return name, body


def _verify_gate_compatibility(
    spans_per_pair: list[tuple[str, str, str, str, int]],
    *,
    sample_indices: list[int] | None = None,
    db_path: Path | None = None,
    p_tag: str = "",
    n_tag: str = "",
) -> None:
    """Render sample directives and run them through evaluate_window_validity.

    Catches operator-locked-rule conflicts at corpus-generation time, BEFORE
    any directive is written to staging or promoted to INBOX. The historical
    motivator is CR-EXIT-FIX (2026-05-30): the first v2 corpus was generated
    with exit=break+1 and ALL 527 directives were rejected at
    window_validity_gate because the rule required end_date <= last_coint_date.
    A 3-sample pre-write check costs ~10 ms and would have caught that
    contradiction before any file was written.

    Picks 1-3 samples from `spans_per_pair` (first / median / last by
    enumeration order, which is alphabetical-by-pair then chronological-by-
    onset within a pair -- a reasonable spread). For each sample, renders the
    directive YAML to a tempfile, calls
    tools.window_validity_gate.evaluate_window_validity(), and asserts
    status == "PASS". Raises RuntimeError on the first REJECT with the gate's
    reject_reason + remediation pointer.

    `db_path` (optional): override the gate's module-level DB_PATH for the
    duration of the verification. When omitted, the gate reads from the
    production cointegration.db (its default). This is threaded through from
    generate_directives's own db_path arg so tests using a tmp DB don't see
    a mismatch between span enumeration (tmp DB) and gate verification
    (would otherwise hit production DB).

    No-op when `spans_per_pair` is empty. Tempfiles are cleaned up in
    `finally` regardless of outcome; the gate's original DB_PATH is restored
    in `finally` regardless of outcome.
    """
    if not spans_per_pair:
        return

    # Default: first / median / last sample. With <3 items, sample all.
    if sample_indices is None:
        n = len(spans_per_pair)
        if n >= 3:
            sample_indices = [0, n // 2, n - 1]
        else:
            sample_indices = list(range(n))

    # Local import — keeps the gate dependency at use-time, not import-time,
    # so tools that import this module for span enumeration alone don't pay
    # the cost of loading the gate's sqlite layer.
    import tempfile

    from tools import window_validity_gate

    # Optionally override the gate's module-level DB_PATH so verification
    # reads from the same DB the spans were enumerated from. Restored in
    # `finally`.
    _original_gate_db = window_validity_gate.DB_PATH
    if db_path is not None:
        window_validity_gate.DB_PATH = Path(db_path)

    try:
        for idx in sample_indices:
            pair_a, pair_b, entry_date, exit_date, ncoint = spans_per_pair[idx]
            name, body = _render_directive(pair_a, pair_b, entry_date, exit_date, p_tag=p_tag, n_tag=n_tag)
            tf_handle = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            )
            try:
                tf_handle.write(body)
                tf_handle.close()
                tf_path = Path(tf_handle.name)
                res = window_validity_gate.evaluate_window_validity(tf_path)
                if res.status != "PASS":
                    raise RuntimeError(
                        f"[GATE-VERIFY] Sample directive {name!r} would be REJECTED "
                        f"at admission by window_validity_gate.\n"
                        f"  pair         : {pair_a} / {pair_b}\n"
                        f"  test window  : [{res.test_start} -> {res.test_end}]\n"
                        f"  span         : {res.span_start} -> {res.span_end} "
                        f"({res.continuous_span_obs} aligned rows)\n"
                        f"  reject reason: {res.reject_reason}\n"
                        f"\n"
                        f"Generator rules contradict an operator-locked admission "
                        f"gate. Either adjust the generator (preferred: align "
                        f"entry/exit with the gate's containment rule) or update "
                        f"the gate's contract. Aborting before bulk write to avoid "
                        f"the wasted-corpus failure mode documented in "
                        f"CR-EXIT-FIX 2026-05-30 "
                        f"(outputs/system_reports/06_strategy_research/"
                        f"COINTEGRATION_V1_TO_V2_TRANSITION.md §4.5)."
                    )
            finally:
                try:
                    Path(tf_handle.name).unlink()
                except FileNotFoundError:
                    pass
    finally:
        window_validity_gate.DB_PATH = _original_gate_db


def generate_directives(
    tf: str = DEFAULT_TF,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    N: int = DEFAULT_CONFIRMATION_N,
    output_dir: Path | None = None,
    db_path: Path | None = None,
    dry_run: bool = False,
    p_threshold: float | None = None,
) -> list[Path]:
    """Read cointegration_daily, enumerate look-ahead-safe spans, and emit
    one directive YAML per qualifying span.

    Filters the SQL query to:
        methodology_version = 'v2_log_eg'
        tf = `tf`
        lookback_days = `lookback_days`

    For each distinct (pair_a, pair_b) cohort, runs spans_confirmation_safe
    over the as_of-ordered regime series and writes one .txt directive per
    qualifying span to `output_dir`.

    When `dry_run=True`, performs the full enumeration but writes nothing.
    Prints a per-class summary + total episode count and returns [].

    Returns the list of written Paths (empty in dry-run mode).
    """
    if tf not in SUPPORTED_TFS:
        raise ValueError(f"Unsupported tf: {tf!r}; allowed: {SUPPORTED_TFS}")
    if N < 0:
        raise ValueError(f"N must be >= 0, got {N!r}")
    if lookback_days < 1:
        raise ValueError(f"lookback_days must be >= 1, got {lookback_days!r}")
    if p_threshold is not None and not (0.0 < p_threshold < 1.0):
        raise ValueError(f"p_threshold must lie in (0,1), got {p_threshold!r}")
    # Encode p_threshold in directive name to prevent cohort collisions.
    # _P05 is implicit (screener default); _P03 = p<0.03; _P02 = p<0.02; etc.
    p_tag = "" if p_threshold is None else f"_P{int(round(p_threshold * 100)):02d}"
    # Encode non-default confirmation N the same way: N=5 (default) -> no tag,
    # so existing N=5 cohorts keep their stems; N=0 -> _N0. Same variant slot
    # and collision-prevention role as p_tag.
    n_tag = "" if N == DEFAULT_CONFIRMATION_N else f"_N{N}"

    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    db_path = Path(db_path) if db_path is not None else Path(SQLITE_DB)

    if not db_path.is_file():
        raise FileNotFoundError(f"cointegration DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        pairs = _read_pairs(conn, tf, lookback_days, METHODOLOGY_VERSION)

        # Aggregate qualifying spans across all pairs.
        spans_per_pair: list[tuple[str, str, str, str, int]] = []
        # (pair_a, pair_b, entry_date, exit_date, ncoint)
        for pair_a, pair_b in pairs:
            series = _read_series(
                conn, pair_a, pair_b, tf, lookback_days, METHODOLOGY_VERSION,
                p_threshold=p_threshold,
            )
            for entry_date, exit_date, ncoint in spans_confirmation_safe(series, N=N):
                spans_per_pair.append(
                    (pair_a, pair_b, entry_date, exit_date, ncoint)
                )
    finally:
        conn.close()

    # Per-class breakdown for the summary line.
    cls_count: Counter[str] = Counter()
    pairs_with_eps: set[tuple[str, str]] = set()
    for pair_a, pair_b, _ed, _xd, _nc in spans_per_pair:
        cls_count[_pair_class(pair_a, pair_b)] += 1
        pairs_with_eps.add((pair_a, pair_b))

    # Gate-compatibility verification (CR-EXIT-FIX 2026-05-30, F1 high-ROI).
    # Renders 3 sample directives + runs them through evaluate_window_validity
    # to catch operator-locked-rule conflicts at generation time, before any
    # bulk write reaches staging. ~10 ms overhead; aborts loudly on REJECT.
    # Threads db_path through so the gate reads from the same DB the spans
    # were enumerated from (matters for tests using a tmp DB; in production
    # both default to cointegration.db).
    _verify_gate_compatibility(spans_per_pair, db_path=db_path, p_tag=p_tag, n_tag=n_tag)

    p_tag_label = "screener-default p<0.05" if p_threshold is None else f"p<{p_threshold} ({p_tag} tag)"
    if dry_run:
        print(
            f"[summary] N={N}, lookback={lookback_days}, tf={tf}, "
            f"methodology={METHODOLOGY_VERSION}, p-threshold={p_tag_label}, "
            f"would write {len(spans_per_pair)} episodes across "
            f"{len(pairs_with_eps)} pairs"
        )
        print("by pair-class:")
        for k, v in sorted(cls_count.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        if spans_per_pair:
            n_batches = math.ceil(len(spans_per_pair) / 50)
            print(
                f"batches of 50: {n_batches} "
                f"({len(spans_per_pair) // 50}x50 + {len(spans_per_pair) % 50})"
            )
        return []

    # File-writing path: clean staging dir + write all qualifying directives.
    if output_dir.exists():
        for f in list(output_dir.glob("*.txt")):
            f.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for pair_a, pair_b, entry_date, exit_date, _ncoint in spans_per_pair:
        name, body = _render_directive(pair_a, pair_b, entry_date, exit_date, p_tag=p_tag, n_tag=n_tag)
        out_path = output_dir / f"{name}.txt"
        out_path.write_text(body, encoding="utf-8")
        written.append(out_path)

    print(
        f"staged {len(written)} episode directives -> {output_dir} "
        f"(N={N}, lookback={lookback_days}, tf={tf}, "
        f"methodology={METHODOLOGY_VERSION}, p-threshold={p_tag_label})"
    )
    print("by pair-class:")
    for k, v in sorted(cls_count.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    if written:
        n_batches = math.ceil(len(written) / 50)
        print(
            f"batches of 50: {n_batches} "
            f"({len(written) // 50}x50 + {len(written) % 50})"
        )
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Generate COINTREV_V3 directives from the v2_log_eg cointegration "
            "corpus with look-ahead-safe N-day confirmation."
        )
    )
    p.add_argument(
        "--confirmation",
        type=int,
        default=DEFAULT_CONFIRMATION_N,
        help=(
            "Number of confirmation days required after onset before the "
            f"entry bar is emitted (default: {DEFAULT_CONFIRMATION_N}, "
            "matches HYSTERESIS_LOOKBACK / one trading week)."
        ),
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"lookback_days filter on cointegration_daily (default: {DEFAULT_LOOKBACK_DAYS}).",
    )
    p.add_argument(
        "--tf",
        type=str,
        default=DEFAULT_TF,
        choices=list(SUPPORTED_TFS),
        help=f"Timeframe filter (default: {DEFAULT_TF}).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output staging dir (default: {DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "--db-path",
        type=Path,
        default=Path(SQLITE_DB),
        help=f"SQLite path (default: {SQLITE_DB}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print per-class summary + episode count, write NO files.",
    )
    p.add_argument(
        "--p-threshold",
        type=float,
        default=None,
        help=(
            "Custom p-value threshold for cointegration admission (e.g., 0.03 "
            "or 0.02). Default: use the screener-precomputed regime label "
            "(screener default p<0.05). When set, derives regime on-the-fly "
            "from the stored adf_pvalue column; no screener re-run needed. "
            "Encoded in directive name as _P03 / _P02 etc. to prevent cohort "
            "collisions on the same (pair, entry_date)."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generate_directives(
        tf=args.tf,
        lookback_days=args.lookback,
        N=args.confirmation,
        output_dir=args.output_dir,
        db_path=args.db_path,
        dry_run=args.dry_run,
        p_threshold=args.p_threshold,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
