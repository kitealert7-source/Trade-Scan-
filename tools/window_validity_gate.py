"""Window-validity admission gate (Task B).

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task B.
Methodology: [[feedback_test_window_must_match_signal_class]].

THE GATE ANSWERS EXACTLY ONE QUESTION:
    "Is this directive's test window entirely inside a single continuous
     cointegrated regime span for (pair, lookback_days)?"

Continuous-span definition (operator-locked 2026-05-28, NOT the 70%-fraction
heuristic from the plan sketch):
  - "aligned" means regime == 'cointegrated' ONLY. 'breaking' and 'broken'
    are NOT aligned ('breaking' is the onset of instability — including it
    would make the gate permissive exactly where caution is intended).
  - A "continuous span" is a maximal run of consecutive cointegrated rows in
    the screener's daily series (ordered by as_of). A non-cointegrated row
    ends the run. Missing as_of rows (weekends/holidays/screener downtime)
    are NOT treated as breaks and are NOT interpolated — the gate operates on
    observed regime rows only.
  - Pass iff [test.start_date, test.end_date] is fully contained within the
    LATEST (most-recent) continuous cointegrated span.

DELIBERATELY OUT OF SCOPE (do not add): regime-quality scoring, gap
smoothing, day interpolation, percentage/fraction thresholds, tolerance
windows, statistical reinterpretation. One question, one answer.

Scope: fires only when `basket.cointegration_join.lookback_days` is set on a
2-symbol basket. All other directives are gate no-ops. `lookback_days`
uniquely determines the screener tf (252/504 → 1d, 1500/3000 → 4h), so the
query keys on (pair, lookback_days); see the live-DB invariant guard in
tests/test_window_validity_gate.py.

Override: `basket.cointegration_join.methodology_override: "<reason>"` allows
admission past a methodology reject with a noisy WARN. Does NOT bypass a
missing-DB environment error.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from tools.cointegration_db import SQLITE_DB, TABLE_NAME

# Patchable in tests.
DB_PATH = SQLITE_DB

ALIGNED_REGIME = "cointegrated"


class WindowValidityGateError(Exception):
    """Raised when admission must be rejected by the window-validity gate."""


@dataclass(frozen=True)
class _Span:
    start: str  # ISO date (first cointegrated as_of in the run)
    end: str    # ISO date (last cointegrated as_of in the run)
    n_rows: int  # number of cointegrated rows in the run


def _canonical_pair(symbols: list[str]) -> tuple[str, str]:
    """Match the DB's canonical ordering (mirrors basket_data_loader)."""
    a, b = sorted([symbols[0].upper(), symbols[1].upper()])
    return a, b


def _load_regime_series(pair_a: str, pair_b: str, lookback_days: int) -> list[tuple[str, str]]:
    """Return [(as_of, regime), ...] ordered by as_of for the canonical pair.

    Raises WindowValidityGateError if the DB file is absent (environment
    error — not a methodology reject, so not override-able).
    """
    if not DB_PATH.exists():
        raise WindowValidityGateError(
            f"[WINDOW_VALIDITY_GATE] cointegration.db not found at {DB_PATH}. "
            f"Cannot validate cointegration_join window. Run the screener "
            f"(tools/cointegration_db.py) before admitting cointegration-join "
            f"directives."
        )
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            f"SELECT as_of, regime FROM {TABLE_NAME} "
            f"WHERE pair_a = ? AND pair_b = ? AND lookback_days = ? "
            f"ORDER BY as_of",
            (pair_a, pair_b, int(lookback_days)),
        ).fetchall()
    finally:
        conn.close()
    return [(str(d), str(r)) for d, r in rows]


def _continuous_cointegrated_spans(series: list[tuple[str, str]]) -> list[_Span]:
    """Maximal runs of consecutive ALIGNED_REGIME rows. Order preserved
    (chronological), so the last element is the latest span."""
    spans: list[_Span] = []
    cur_start: str | None = None
    cur_end: str | None = None
    cur_n = 0
    for as_of, regime in series:
        if regime == ALIGNED_REGIME:
            if cur_start is None:
                cur_start = as_of
            cur_end = as_of
            cur_n += 1
        else:
            if cur_start is not None:
                spans.append(_Span(cur_start, cur_end, cur_n))
                cur_start, cur_end, cur_n = None, None, 0
    if cur_start is not None:
        spans.append(_Span(cur_start, cur_end, cur_n))
    return spans


def _parse_directive(directive_path: Path) -> dict:
    return yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}


def check_window_validity(directive_path: Path) -> None:
    """Gate entry point. Raise WindowValidityGateError to reject admission.

    No-op unless the directive declares `basket.cointegration_join.lookback_days`
    on a 2-symbol basket.
    """
    data = _parse_directive(directive_path)
    basket = data.get("basket") or {}
    coint_join = basket.get("cointegration_join") or {}
    lookback = coint_join.get("lookback_days")
    if lookback is None:
        return  # not a cointegration-join directive — gate does not apply

    legs = basket.get("legs") or []
    symbols = [leg.get("symbol") for leg in legs if leg.get("symbol")]
    if len(symbols) != 2:
        # cointegration_join is a pairwise construct; >2 or <2 legs are out of
        # this gate's single question. Leave to other validation.
        return

    test = data.get("test") or {}
    test_start = test.get("start_date")
    test_end = test.get("end_date")
    if not test_start or not test_end:
        return  # no window to validate; other gates own date presence

    override = coint_join.get("methodology_override")
    override = override.strip() if isinstance(override, str) else None

    pair_a, pair_b = _canonical_pair(symbols)
    series = _load_regime_series(pair_a, pair_b, int(lookback))

    reject_reason: str | None = None
    suggestion: str = ""

    if not series:
        reject_reason = (
            f"no cointegration history for pair ({pair_a}, {pair_b}) at "
            f"lookback_days={lookback}. The screener has never evaluated this "
            f"pair/lookback."
        )
    else:
        spans = _continuous_cointegrated_spans(series)
        if not spans:
            reject_reason = (
                f"pair ({pair_a}, {pair_b}) lookback_days={lookback} has "
                f"{len(series)} screener rows but ZERO continuous "
                f"'{ALIGNED_REGIME}' spans — never aligned in recorded history."
            )
        else:
            latest = spans[-1]
            ts, te = str(test_start), str(test_end)
            before = ts < latest.start
            after = te > latest.end
            if before or after:
                parts = []
                if before:
                    parts.append(
                        f"window starts {ts} — before the aligned span opens "
                        f"({latest.start})"
                    )
                if after:
                    parts.append(
                        f"window ends {te} — after the aligned span closes "
                        f"({latest.end}); regime left '{ALIGNED_REGIME}' after that"
                    )
                reject_reason = "; ".join(parts)
                suggestion = (
                    f" Latest continuous '{ALIGNED_REGIME}' span: "
                    f"{latest.start} → {latest.end} ({latest.n_rows} aligned "
                    f"rows). Suggested directive window: start_date={latest.start}, "
                    f"end_date={latest.end}."
                )

    if reject_reason is None:
        return  # PASS — window fully inside the latest cointegrated span

    msg = (
        f"[WINDOW_VALIDITY_GATE] directive '{directive_path.stem}' "
        f"test window [{test_start} → {test_end}] is not inside a continuous "
        f"cointegrated regime: {reject_reason}.{suggestion}"
    )

    if override:
        print(
            f"[WINDOW_VALIDITY_GATE][WARN] METHODOLOGY_OVERRIDE for "
            f"'{directive_path.stem}': {override} -- admitting despite window "
            f"check. Reject reason was: {reject_reason}"
        )
        return

    raise WindowValidityGateError(
        msg + " Set basket.cointegration_join.methodology_override with a "
        "documented reason to admit anyway."
    )
