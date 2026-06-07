"""cointegration_freshness_check.py -- per-(tf, lookback_days) staleness alarm.

SCOPE (read first)
------------------
This detects DIVERGENCE between screener surfaces -- one (tf, lookback_days)
key falling behind the others -- NOT complete screener inactivity. If the whole
daily cycle stalls, every key freezes together, the relative lag stays 0, and
this check correctly reports healthy. Catching a total stall is a different
signal (see LIMITATION below) and is deliberately out of scope: this exists for
the PARTIAL-staleness failure mode (the 4h surface going stale while 1d kept
running). Do not rely on it as a "did the screener run at all today?" check.

WHY THIS EXISTS
---------------
"The daily cointegration runner exited 0" does NOT mean every
(tf, lookback_days) surface advanced. On 2026-05-26 a "parameterize TF"
refactor (commit 45e6a7a) added an opt-in `--tf {1d|4h}` to
cointegration_screen but never wired the daily runner to opt into 4h, so the
4h surface went SILENTLY stale for 10 days (last as_of 2026-05-29 ->
2026-06-06) and was caught only by manual operator inspection. The runner-level
fix (Phase 1a/1b, commit ba3b82cf) restored the 4h cadence -- but nothing
ALARMED on the staleness.

This module promotes "the runner ran" to "every (tf, lookback_days) key is as
fresh as the freshest key." It is a per-key RELATIVE freshness assertion:

    for each (table, tf, lookback_days) key:  key_max = MAX(as_of)
    reference = newest as_of across ALL keys, both tables (the freshest key)
    a key is STALE when (reference_date - key_max_date).days > max_lag_days

MIXED TRADING CALENDAR (why relative, not absolute)
---------------------------------------------------
Symbols trade on different calendars: FX + most indices stop Friday, but
BTC/ETH trade weekends. An ABSOLUTE check ("how far is as_of behind today?")
false-alarms every weekend on the FX-dominant universe (a Saturday run's newest
FX bar is the prior Friday). The relative check sidesteps calendar reasoning: it
asks only whether some keys lag OTHER keys. Because every (tf, lookback_days)
key spans the full universe -- including the weekend-trading crypto symbols that
set each key's MAX(as_of) -- all keys reach the same newest as_of in normal
operation, so the relative lag is ~0 even on weekends. A key that genuinely
stops advancing (the 4h gap above) accumulates lag and trips the threshold.

The per-key MAX(as_of) is sourced from cointegration_db.query_latest_per_pair /
query_latest_per_symbol -- the same per-pair-latest loaders that already back
the Excel screener tabs and the MPS candidates column -- so this check sees
exactly the calendar-aware "latest available per pair/symbol" view the operator
reviews, rather than reinventing the calendar handling.

LIMITATION (documented, by design)
----------------------------------
Detects divergence between screener surfaces, not complete screener inactivity.
Relative staleness cannot catch a WHOLE-runner stall: if the entire daily cycle
stops, every key freezes together and the relative lag stays 0. That failure
mode is a different signal (no daily-pipeline SUCCESS; the Excel Summary's
`data as-of` vs `run` line diverging) and is out of scope here by design. Pass
--reference-date <today> to the CLI for an opt-in absolute calendar check.

INTEGRATION
-----------
tools/cointegration_daily_runner.py calls emit_to_log() as a NON-FATAL step
right after Phase 2 (SQLite upsert), so a stale surface shows up in
tmp/cointegration_daily.log and -- because invoke_daily_pipeline.ps1 echoes the
runner's stdout into the DATA_INGRESS daily pipeline log -- there too. Default
posture is WARN only: a stale 4h surface must NOT hard-fail the daily run. The
standalone CLI offers --strict (exit 1 on stale) for callers that want a hard
gate, mirroring the DATA_INGRESS assert_raw_coverage.py /
validate_research_layer.py health-check shape.

CLI:
    python tools/cointegration_freshness_check.py
    python tools/cointegration_freshness_check.py --max-lag-days 5
    python tools/cointegration_freshness_check.py --strict            # exit 1 if stale
    python tools/cointegration_freshness_check.py --reference-date 2026-06-07
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from tools.cointegration_db import (
    SINGLES_TABLE_NAME,
    SQLITE_DB,
    TABLE_NAME,
    connect,
    query_latest_per_pair,
    query_latest_per_symbol,
)

# Conservative default: alarm only when a key lags the freshest key by MORE
# than this many calendar days. 3 absorbs a normal Fri->Mon weekend gap for any
# hypothetical key that lacks a weekend-trading (crypto) member, while still
# catching the multi-day silent staleness this check exists to surface.
DEFAULT_MAX_LAG_DAYS = 3


@dataclass(frozen=True)
class KeyFreshness:
    """Freshness of one (table, tf, lookback_days) key."""
    table: str
    tf: str
    lookback_days: int
    max_as_of: str
    lag_days: int
    stale: bool


@dataclass
class FreshnessReport:
    """Result of a freshness assertion across all (table, tf, lookback) keys."""
    reference_as_of: str | None
    max_lag_days: int
    keys: list[KeyFreshness] = field(default_factory=list)

    @property
    def stale_keys(self) -> list[KeyFreshness]:
        return [k for k in self.keys if k.stale]

    @property
    def ok(self) -> bool:
        """True when no key is stale (an empty DB is OK -- nothing to check)."""
        return not self.stale_keys


def _collect_key_maxes(df: pd.DataFrame, table: str) -> dict[tuple[str, str, int], str]:
    """{(table, tf, lookback_days): MAX(as_of)} from a per-pair-/per-symbol-latest
    DataFrame. as_of is an ISO 'YYYY-MM-DD' string, so a string max is a
    chronological max. An empty / column-less frame yields {} (empty table)."""
    if df is None or df.empty or "as_of" not in df.columns:
        return {}
    grouped = df.groupby(["tf", "lookback_days"])["as_of"].max()
    return {
        (table, str(tf), int(lookback_days)): str(max_as_of)
        for (tf, lookback_days), max_as_of in grouped.items()
    }


def compute_freshness(
    pairs_latest: pd.DataFrame,
    singles_latest: pd.DataFrame,
    *,
    max_lag_days: int = DEFAULT_MAX_LAG_DAYS,
    reference_as_of: str | None = None,
) -> FreshnessReport:
    """Per-(table, tf, lookback_days) relative freshness report.

    `pairs_latest` / `singles_latest` are per-pair-/per-symbol-latest views
    (one row per pair/symbol at its OWN most-recent as_of) -- pass the output of
    query_latest_per_pair / query_latest_per_symbol. Only the `tf`,
    `lookback_days`, and `as_of` columns are used.

    `reference_as_of` overrides the baseline. Default (None) uses the newest
    as_of across all keys in BOTH inputs -> relative staleness (the freshest key
    sets the bar). Pass a calendar date for an absolute check.
    """
    key_max: dict[tuple[str, str, int], str] = {}
    key_max.update(_collect_key_maxes(pairs_latest, TABLE_NAME))
    key_max.update(_collect_key_maxes(singles_latest, SINGLES_TABLE_NAME))

    if not key_max:
        return FreshnessReport(reference_as_of=reference_as_of,
                               max_lag_days=max_lag_days, keys=[])

    reference = reference_as_of or max(key_max.values())
    ref_date = date.fromisoformat(reference)

    keys: list[KeyFreshness] = []
    for (table, tf, lookback_days), max_as_of in sorted(key_max.items()):
        lag = (ref_date - date.fromisoformat(max_as_of)).days
        keys.append(KeyFreshness(
            table=table, tf=tf, lookback_days=lookback_days,
            max_as_of=max_as_of, lag_days=lag, stale=lag > max_lag_days,
        ))
    return FreshnessReport(reference_as_of=reference,
                           max_lag_days=max_lag_days, keys=keys)


def check_db(
    conn,
    *,
    max_lag_days: int = DEFAULT_MAX_LAG_DAYS,
    reference_as_of: str | None = None,
) -> FreshnessReport:
    """Run the freshness assertion against an open SQLite connection, reusing
    the calendar-aware per-pair-/per-symbol-latest loaders from cointegration_db."""
    return compute_freshness(
        query_latest_per_pair(conn),
        query_latest_per_symbol(conn),
        max_lag_days=max_lag_days,
        reference_as_of=reference_as_of,
    )


def format_report_lines(report: FreshnessReport) -> list[str]:
    """Compact, greppable lines for the daily runner's _log() / the CLI.

    Operational alerts get ignored when verbose, so the output is terse: a
    one-line summary carrying the reference + threshold, then ONE compact line
    per stale key -- `<table> (<tf>,<lookback>) lag=<N>d` -- never a wide table.
    Every line keeps a WARN/OK/INFO tag so a log filter on "WARN" surfaces the
    individual stale keys, not just the header. A single OK line when all fresh;
    an INFO line for an empty DB. Stale lines are bounded by the key count
    (<= 8 today), so this stays short even in the worst case.

        WARN  freshness: 2 of 8 keys stale -- reference as_of 2026-06-07, threshold 3d:
        WARN    cointegration_daily (4h,1500) lag=9d
        WARN    cointegration_daily (4h,3000) lag=9d
    """
    if not report.keys:
        return ["INFO  freshness: no cointegration rows in DB -- nothing to check"]

    stale = report.stale_keys
    if not stale:
        return [
            f"OK    freshness: {len(report.keys)} keys fresh -- all within "
            f"{report.max_lag_days}d of reference as_of {report.reference_as_of}"
        ]

    lines = [
        f"WARN  freshness: {len(stale)} of {len(report.keys)} keys stale -- "
        f"reference as_of {report.reference_as_of}, threshold {report.max_lag_days}d:"
    ]
    lines += [
        f"WARN    {k.table} ({k.tf},{k.lookback_days}) lag={k.lag_days}d"
        for k in stale
    ]
    return lines


def emit_to_log(
    log_fn,
    *,
    db_path: Path | str = SQLITE_DB,
    max_lag_days: int = DEFAULT_MAX_LAG_DAYS,
) -> FreshnessReport | None:
    """Run the check against db_path and emit each report line via log_fn.

    BEST-EFFORT: never raises. A freshness-check failure (missing DB, query
    error) must never abort the caller (the daily runner) -- it logs a WARN and
    returns None. Returns the FreshnessReport on success (for callers / tests).
    """
    try:
        conn = connect(db_path)
    except Exception as exc:  # pragma: no cover - connect rarely fails
        log_fn(f"WARN  freshness check could not open DB "
               f"({type(exc).__name__}: {exc}) -- skipped (non-fatal)")
        return None
    try:
        report = check_db(conn, max_lag_days=max_lag_days)
    except Exception as exc:
        log_fn(f"WARN  freshness check errored "
               f"({type(exc).__name__}: {exc}) -- skipped (non-fatal)")
        return None
    finally:
        conn.close()

    for line in format_report_lines(report):
        log_fn(line)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Cointegration screener -- per-(tf,lookback) freshness assertion.")
    p.add_argument("--db", type=str, default=str(SQLITE_DB),
                   help=f"SQLite path (default: {SQLITE_DB})")
    p.add_argument("--max-lag-days", type=int, default=DEFAULT_MAX_LAG_DAYS,
                   help="Stale when a key lags the freshest key by > N calendar "
                        f"days (default: {DEFAULT_MAX_LAG_DAYS}).")
    p.add_argument("--reference-date", type=str, default=None,
                   help="Override the freshness baseline (YYYY-MM-DD). Default: "
                        "newest as_of in the DB (relative staleness). Pass today's "
                        "date for an absolute calendar check.")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if any key is stale (default: exit 0 -- WARN only).")
    args = p.parse_args(argv)

    conn = connect(args.db)
    try:
        report = check_db(conn, max_lag_days=args.max_lag_days,
                          reference_as_of=args.reference_date)
    finally:
        conn.close()

    for line in format_report_lines(report):
        print(line)

    if args.strict and not report.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
