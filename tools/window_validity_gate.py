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


@dataclass(frozen=True)
class WindowValidityResult:
    """Structured, non-raising result of the window-validity evaluation.

    `status` is the raw methodology verdict: NOT_APPLICABLE (gate does not
    apply), PASS (window inside the latest continuous cointegrated span), or
    REJECT. The remaining fields are the regime provenance the cointegration
    ledger records. check_window_validity() turns a REJECT into a raise, or a
    WARN+admit when `override_reason` is set.
    """
    applies: bool
    status: str  # "NOT_APPLICABLE" | "PASS" | "REJECT"
    reject_reason: str | None = None
    suggestion: str = ""
    override_reason: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    span_start: str | None = None
    span_end: str | None = None
    continuous_span_obs: int | None = None
    fragment_count: int | None = None
    pct_cointegrated: float | None = None
    regime_state: str | None = None

    @property
    def ledger_window_status(self) -> str:
        """`window_validation_status` value for the cointegration ledger:
        PASS, OVERRIDE (admitted past a REJECT via methodology_override),
        or N/A (not applicable, or a REJECT that was not admitted)."""
        if self.status == "PASS":
            return "PASS"
        if self.status == "REJECT" and self.override_reason:
            return "OVERRIDE"
        return "N/A"


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


def evaluate_window_validity(directive_path: Path) -> WindowValidityResult:
    """Non-raising core of the window-validity gate.

    Computes whether the directive's test window sits inside the LATEST
    continuous cointegrated span, plus the regime provenance (span bounds,
    fragment count, aligned fraction, latest regime) that the cointegration
    ledger records. Methodology verdicts never raise; a missing screener DB is
    an ENVIRONMENT error and still raises (from _load_regime_series) -- but only
    for directives the gate applies to, after the no-op checks.
    check_window_validity() wraps this for admission.
    """
    data = _parse_directive(directive_path)
    basket = data.get("basket") or {}
    coint_join = basket.get("cointegration_join") or {}
    lookback = coint_join.get("lookback_days")
    if lookback is None:
        # not a cointegration-join directive — gate does not apply
        return WindowValidityResult(applies=False, status="NOT_APPLICABLE")

    legs = basket.get("legs") or []
    symbols = [leg.get("symbol") for leg in legs if leg.get("symbol")]
    if len(symbols) != 2:
        # cointegration_join is a pairwise construct; >2 or <2 legs are out of
        # this gate's single question. Leave to other validation.
        return WindowValidityResult(applies=False, status="NOT_APPLICABLE")

    test = data.get("test") or {}
    test_start = test.get("start_date")
    test_end = test.get("end_date")
    if not test_start or not test_end:
        # no window to validate; other gates own date presence
        return WindowValidityResult(applies=False, status="NOT_APPLICABLE")

    override = coint_join.get("methodology_override")
    override = override.strip() if isinstance(override, str) else None

    pair_a, pair_b = _canonical_pair(symbols)
    series = _load_regime_series(pair_a, pair_b, int(lookback))
    ts, te = str(test_start), str(test_end)

    # Regime provenance from the full series (independent of pass/fail).
    n_series = len(series)
    pct_cointegrated = (
        sum(1 for _, r in series if r == ALIGNED_REGIME) / n_series
        if n_series else None
    )
    regime_state = series[-1][1] if series else None
    spans = _continuous_cointegrated_spans(series) if series else []
    fragment_count = len(spans)
    latest = spans[-1] if spans else None
    span_start = latest.start if latest else None
    span_end = latest.end if latest else None
    continuous_span_obs = latest.n_rows if latest else None

    reject_reason: str | None = None
    suggestion: str = ""

    if not series:
        reject_reason = (
            f"no cointegration history for pair ({pair_a}, {pair_b}) at "
            f"lookback_days={lookback}. The screener has never evaluated this "
            f"pair/lookback."
        )
    elif not spans:
        reject_reason = (
            f"pair ({pair_a}, {pair_b}) lookback_days={lookback} has "
            f"{len(series)} screener rows but ZERO continuous "
            f"'{ALIGNED_REGIME}' spans — never aligned in recorded history."
        )
    else:
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

    status = "PASS" if reject_reason is None else "REJECT"
    return WindowValidityResult(
        applies=True,
        status=status,
        reject_reason=reject_reason,
        suggestion=suggestion,
        override_reason=override,
        test_start=ts,
        test_end=te,
        span_start=span_start,
        span_end=span_end,
        continuous_span_obs=continuous_span_obs,
        fragment_count=fragment_count,
        pct_cointegrated=pct_cointegrated,
        regime_state=regime_state,
    )


def check_window_validity(directive_path: Path) -> None:
    """Gate entry point. Raise WindowValidityGateError to reject admission.

    Thin wrapper over evaluate_window_validity(): NOT_APPLICABLE / PASS ->
    return; REJECT -> raise, unless basket.cointegration_join.methodology_override
    admits it with a noisy WARN. Behavior is byte-identical to the pre-refactor
    gate. No-op unless the directive declares
    `basket.cointegration_join.lookback_days` on a 2-symbol basket.
    """
    result = evaluate_window_validity(directive_path)
    if result.status in ("NOT_APPLICABLE", "PASS"):
        return

    msg = (
        f"[WINDOW_VALIDITY_GATE] directive '{directive_path.stem}' "
        f"test window [{result.test_start} → {result.test_end}] is not inside a continuous "
        f"cointegrated regime: {result.reject_reason}.{result.suggestion}"
    )

    if result.override_reason:
        print(
            f"[WINDOW_VALIDITY_GATE][WARN] METHODOLOGY_OVERRIDE for "
            f"'{directive_path.stem}': {result.override_reason} -- admitting despite window "
            f"check. Reject reason was: {result.reject_reason}"
        )
        return

    raise WindowValidityGateError(
        msg + " Set basket.cointegration_join.methodology_override with a "
        "documented reason to admit anyway."
    )
