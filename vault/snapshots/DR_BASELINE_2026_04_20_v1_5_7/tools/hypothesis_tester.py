"""
hypothesis_tester.py — Structured Insight Extraction & Hypothesis Report

Recomputes dimensional breakdowns directly from trade-level data.
Returns structured InsightRecords — never parses report text.

Usage:
    # Report mode (this file's scope):
    python tools/hypothesis_tester.py <backtest_folder>
    python tools/hypothesis_tester.py --scan 32_TREND_XAUUSD_1H_EMAXO_S01_V1_P00

    # Programmatic:
    from tools.hypothesis_tester import extract_structured_insights
    insights = extract_structured_insights(trades, starting_capital)

No pipeline execution. No strategy modification. No side effects.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.metrics_core import (
    _safe_float,
    _safe_int,
    compute_pnl_basics,
    compute_regime_age_breakdown,
    REGIME_AGE_BUCKETS,
)
from config.state_paths import BACKTESTS_DIR

# Session boundaries (UTC hours) — mirrored from report_generator.py
_ASIA_START, _ASIA_END = 0, 8
_LONDON_START, _LONDON_END = 8, 16
_NY_START, _NY_END = 16, 24
_LATE_NY_START, _LATE_NY_END = 21, 24


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InsightRecord:
    hypothesis_class: str       # weak_cell, direction_bias, session_divergence, regime_age_gradient, late_ny_asymmetry
    rank_score: float
    target_field: str           # trade-level column to filter on
    target_value: Any           # value(s) to exclude
    target_op: str              # shadow_filter operator
    secondary_field: str | None = None
    secondary_value: Any | None = None
    secondary_op: str | None = None
    bucket_trades: int = 0
    bucket_pct: float = 0.0     # % of total trades
    bucket_net_pnl: float = 0.0
    bucket_pf: float = 0.0
    bucket_wr: float = 0.0
    confidence: str = "Low"     # High / Medium / Low
    eligible: bool = False      # passes eligibility filter
    rejection_reasons: list[str] = field(default_factory=list)
    hypothesis_rank: int = 0    # 1-based rank among eligible insights (set after sorting)
    _matched_trade_indices: frozenset = field(default_factory=frozenset, repr=False)  # trade indices matched by this filter

    def to_filter_spec(self) -> dict[str, Any]:
        """Convert to shadow_filter-compatible filter_spec dict."""
        conditions = [{"field": self.target_field, "op": self.target_op, "value": self.target_value}]
        if self.secondary_field is not None:
            conditions.append({"field": self.secondary_field, "op": self.secondary_op or "eq", "value": self.secondary_value})
        return {
            "label": f"Excl. {self.hypothesis_class}: {self._describe()}",
            "logic": "AND",
            "conditions": conditions,
        }

    def _describe(self) -> str:
        parts = [f"{self.target_field}={self.target_value}"]
        if self.secondary_field:
            parts.append(f"{self.secondary_field}={self.secondary_value}")
        return " & ".join(parts)


# ---------------------------------------------------------------------------
# Confidence tagging
# ---------------------------------------------------------------------------

def _conf_tag(trades: int) -> str:
    if trades >= 50:
        return "High"
    if trades >= 20:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Session classification (pure, no pandas)
# ---------------------------------------------------------------------------

def _get_entry_hour(trade: dict) -> int | None:
    ts = trade.get("entry_timestamp", "")
    if not ts or ts in ("None", "nan"):
        return None
    try:
        from tools.metrics_core import _parse_timestamp
        dt = _parse_timestamp(str(ts))
        return dt.hour if dt else None
    except Exception:
        return None


def _classify_session_hour(hour: int) -> str:
    if _ASIA_START <= hour < _ASIA_END:
        return "asia"
    if _LONDON_START <= hour < _LONDON_END:
        return "london"
    return "ny"


# ---------------------------------------------------------------------------
# Eligibility filter
# ---------------------------------------------------------------------------

_MIN_TRADES = 10
_MIN_PCT = 5.0


def _apply_eligibility(insight: InsightRecord, total_trades: int) -> InsightRecord:
    """Apply eligibility rules. Mutates insight.eligible and rejection_reasons."""
    reasons = []

    if insight.bucket_trades < _MIN_TRADES:
        reasons.append(f"trades={insight.bucket_trades} < {_MIN_TRADES}")

    if insight.bucket_pct < _MIN_PCT:
        reasons.append(f"pct={insight.bucket_pct:.1f}% < {_MIN_PCT}%")

    if insight.bucket_net_pnl >= 0:
        reasons.append(f"net_pnl=${insight.bucket_net_pnl:.2f} >= 0 (not a drag)")

    if insight.confidence == "Low":
        reasons.append("confidence=Low")

    insight.eligible = len(reasons) == 0
    insight.rejection_reasons = reasons
    return insight


# ---------------------------------------------------------------------------
# Dimensional checks — each returns a list of InsightRecord candidates
# ---------------------------------------------------------------------------

def _pf_from_pnls(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl > 0:
        return gp / gl
    return gp if gp > 0 else 0.0


def _check_direction_x_categorical(
    trades: list[dict], total: int,
    cat_field: str, cat_map: dict[str, str],
    hypothesis_class: str,
) -> list[InsightRecord]:
    """Direction x categorical field cross-tab (e.g. Direction x Volatility)."""
    results = []
    dir_map = {1: "Long", -1: "Short"}

    for dir_val, dir_label in dir_map.items():
        dir_trades = [t for t in trades if _safe_int(t.get("direction", 0)) == dir_val]
        for nice_name, raw_val in cat_map.items():
            cell = [t for t in dir_trades if str(t.get(cat_field, "")).strip().lower() == raw_val]
            n = len(cell)
            if n < 5:
                continue
            pnls = [_safe_float(t.get("pnl_usd", 0)) for t in cell]
            b = compute_pnl_basics(pnls)
            pf = b["profit_factor"]
            pct = (n / total * 100) if total > 0 else 0.0

            # Only surface weak cells (PF < 1.0, or PF gap logic handled by scoring)
            if pf >= 1.5:
                continue

            score = (1.0 / max(pf, 0.01)) * min(1.0, n / 30)

            results.append(InsightRecord(
                hypothesis_class=hypothesis_class,
                rank_score=round(score, 4),
                target_field=cat_field,
                target_value=raw_val,
                target_op="eq",
                secondary_field="direction",
                secondary_value=dir_val,
                secondary_op="eq",
                bucket_trades=n,
                bucket_pct=round(pct, 1),
                bucket_net_pnl=round(b["net_profit"], 2),
                bucket_pf=round(pf, 3),
                bucket_wr=round(b["win_rate"] * 100, 1),
                confidence=_conf_tag(n),
            ))

    return results


def _check_direction_bias(trades: list[dict], total: int) -> list[InsightRecord]:
    """Standalone direction asymmetry check."""
    results = []
    for dir_val, dir_label in [(1, "Long"), (-1, "Short")]:
        dir_trades = [t for t in trades if _safe_int(t.get("direction", 0)) == dir_val]
        n = len(dir_trades)
        if n < 10:
            continue
        pnls = [_safe_float(t.get("pnl_usd", 0)) for t in dir_trades]
        b = compute_pnl_basics(pnls)

        other_trades = [t for t in trades if _safe_int(t.get("direction", 0)) == -dir_val]
        if len(other_trades) < 10:
            continue
        other_pnls = [_safe_float(t.get("pnl_usd", 0)) for t in other_trades]
        other_b = compute_pnl_basics(other_pnls)

        # Only surface if this direction is a drag AND the other is clearly better
        if b["profit_factor"] >= other_b["profit_factor"]:
            continue
        ratio = other_b["profit_factor"] / max(b["profit_factor"], 0.01)
        if ratio < 1.5:
            continue

        pct = (n / total * 100) if total > 0 else 0.0
        score = ratio * min(1.0, min(n, len(other_trades)) / 30)

        results.append(InsightRecord(
            hypothesis_class="direction_bias",
            rank_score=round(score, 4),
            target_field="direction",
            target_value=dir_val,
            target_op="eq",
            bucket_trades=n,
            bucket_pct=round(pct, 1),
            bucket_net_pnl=round(b["net_profit"], 2),
            bucket_pf=round(b["profit_factor"], 3),
            bucket_wr=round(b["win_rate"] * 100, 1),
            confidence=_conf_tag(n),
        ))

    return results


def _check_session_divergence(trades: list[dict], total: int) -> list[InsightRecord]:
    """Session-level PF divergence."""
    session_buckets: dict[str, list[float]] = {"asia": [], "london": [], "ny": []}
    session_nice = {"asia": "Asia", "london": "London", "ny": "NY"}
    session_hours = {"asia": (0, 8), "london": (8, 16), "ny": (16, 24)}

    for t in trades:
        hour = _get_entry_hour(t)
        if hour is None:
            continue
        sess = _classify_session_hour(hour)
        session_buckets[sess].append(_safe_float(t.get("pnl_usd", 0)))

    results = []
    sess_pfs = {}
    for sess, pnls in session_buckets.items():
        if len(pnls) < 10:
            continue
        sess_pfs[sess] = (pnls, _pf_from_pnls(pnls))

    if len(sess_pfs) < 2:
        return results

    best_s = max(sess_pfs, key=lambda s: sess_pfs[s][1])
    worst_s = min(sess_pfs, key=lambda s: sess_pfs[s][1])
    gap = sess_pfs[best_s][1] - sess_pfs[worst_s][1]

    if gap < 0.5:
        return results

    worst_pnls = sess_pfs[worst_s][0]
    n = len(worst_pnls)
    b = compute_pnl_basics(worst_pnls)
    pct = (n / total * 100) if total > 0 else 0.0
    score = gap * min(1.0, n / 30)
    lo, hi = session_hours[worst_s]

    results.append(InsightRecord(
        hypothesis_class="session_divergence",
        rank_score=round(score, 4),
        target_field="entry_hour",
        target_value=lo,
        target_op="gte",
        secondary_field="entry_hour",
        secondary_value=hi,
        secondary_op="lt",
        bucket_trades=n,
        bucket_pct=round(pct, 1),
        bucket_net_pnl=round(b["net_profit"], 2),
        bucket_pf=round(b["profit_factor"], 3),
        bucket_wr=round(b["win_rate"] * 100, 1),
        confidence=_conf_tag(n),
    ))

    return results


def _check_regime_age_gradient(trades: list[dict], total: int) -> list[InsightRecord]:
    """Regime age bucket gradient."""
    age_rows = compute_regime_age_breakdown(trades)
    qualified = [r for r in age_rows if r["trades"] >= 10]
    if len(qualified) < 2:
        return []

    best = max(qualified, key=lambda r: r["profit_factor"])
    worst = min(qualified, key=lambda r: r["profit_factor"])
    gap = best["profit_factor"] - worst["profit_factor"]
    if gap < 0.5:
        return []

    n = worst["trades"]
    pct = (n / total * 100) if total > 0 else 0.0
    score = gap * min(1.0, n / 30)

    # Find the bucket range for the worst bucket
    worst_label = worst["label"]
    lo = hi = None
    for label, age_lo, age_hi in REGIME_AGE_BUCKETS:
        if label == worst_label:
            lo, hi = age_lo, age_hi
            break

    if lo is None:
        return []

    # Build conditions for the range
    if hi is None:
        # Open-ended (e.g. Age 11+)
        record = InsightRecord(
            hypothesis_class="regime_age_gradient",
            rank_score=round(score, 4),
            target_field="regime_age",
            target_value=lo,
            target_op="gte",
            bucket_trades=n,
            bucket_pct=round(pct, 1),
            bucket_net_pnl=round(worst["net_pnl"], 2),
            bucket_pf=round(worst["profit_factor"], 3),
            bucket_wr=round(worst["win_rate"], 1),
            confidence=_conf_tag(n),
        )
    elif lo == hi:
        # Single value (e.g. Age 0)
        record = InsightRecord(
            hypothesis_class="regime_age_gradient",
            rank_score=round(score, 4),
            target_field="regime_age",
            target_value=lo,
            target_op="eq",
            bucket_trades=n,
            bucket_pct=round(pct, 1),
            bucket_net_pnl=round(worst["net_pnl"], 2),
            bucket_pf=round(worst["profit_factor"], 3),
            bucket_wr=round(worst["win_rate"], 1),
            confidence=_conf_tag(n),
        )
    else:
        # Range (e.g. Age 3-5)
        record = InsightRecord(
            hypothesis_class="regime_age_gradient",
            rank_score=round(score, 4),
            target_field="regime_age",
            target_value=lo,
            target_op="gte",
            secondary_field="regime_age",
            secondary_value=hi,
            secondary_op="lte",
            bucket_trades=n,
            bucket_pct=round(pct, 1),
            bucket_net_pnl=round(worst["net_pnl"], 2),
            bucket_pf=round(worst["profit_factor"], 3),
            bucket_wr=round(worst["win_rate"], 1),
            confidence=_conf_tag(n),
        )

    return [record]


def _check_late_ny_asymmetry(trades: list[dict], total: int) -> list[InsightRecord]:
    """Late NY (21-24 UTC) directional asymmetry."""
    late_trades = []
    core_trades = []
    for t in trades:
        hour = _get_entry_hour(t)
        if hour is None:
            continue
        sess = _classify_session_hour(hour)
        if sess != "ny":
            continue
        if _LATE_NY_START <= hour < _LATE_NY_END:
            late_trades.append(t)
        else:
            core_trades.append(t)

    if len(late_trades) < 10:
        return []

    results = []
    for dir_val, dir_label in [(1, "Long"), (-1, "Short")]:
        late_d = [t for t in late_trades if _safe_int(t.get("direction", 0)) == dir_val]
        opp_val = -dir_val
        late_opp = [t for t in late_trades if _safe_int(t.get("direction", 0)) == opp_val]
        core_d = [t for t in core_trades if _safe_int(t.get("direction", 0)) == dir_val]

        if len(late_d) < 10 or len(late_opp) < 10 or len(core_d) < 10:
            continue

        late_pnls = [_safe_float(t.get("pnl_usd", 0)) for t in late_d]
        core_pnls = [_safe_float(t.get("pnl_usd", 0)) for t in core_d]
        opp_pnls = [_safe_float(t.get("pnl_usd", 0)) for t in late_opp]

        late_pf = _pf_from_pnls(late_pnls)
        core_pf = _pf_from_pnls(core_pnls)
        opp_pf = _pf_from_pnls(opp_pnls)

        if core_pf < 1.0:
            continue

        # Look for the WEAK direction in late NY
        if opp_pf < 1.0 and late_pf >= core_pf * 1.5:
            # The opposite direction is weak in late NY — that's the exclusion candidate
            n = len(late_opp)
            b = compute_pnl_basics(opp_pnls)
            pct = (n / total * 100) if total > 0 else 0.0
            late_pf_c = min(late_pf, 5.0)
            score = (late_pf_c / core_pf) * (1.0 - opp_pf) * min(1.0, n / 30)
            opp_label = "Short" if dir_val == 1 else "Long"

            results.append(InsightRecord(
                hypothesis_class="late_ny_asymmetry",
                rank_score=round(score, 4),
                target_field="entry_hour",
                target_value=_LATE_NY_START,
                target_op="gte",
                secondary_field="direction",
                secondary_value=opp_val,
                secondary_op="eq",
                bucket_trades=n,
                bucket_pct=round(pct, 1),
                bucket_net_pnl=round(b["net_profit"], 2),
                bucket_pf=round(b["profit_factor"], 3),
                bucket_wr=round(b["win_rate"] * 100, 1),
                confidence=_conf_tag(n),
            ))
            break

    return results


# ---------------------------------------------------------------------------
# Trade matching (for cross-dimension overlap detection)
# ---------------------------------------------------------------------------

def _trade_matches_insight(trade: dict, insight: InsightRecord) -> bool:
    """Return True if a trade would be excluded by this insight's filter."""
    # Primary condition
    raw = trade.get(insight.target_field)

    # Special handling for entry_hour (derived from entry_timestamp)
    if insight.target_field == "entry_hour":
        hour = _get_entry_hour(trade)
        if hour is None:
            return False
        raw = hour

    if raw is None:
        return False

    try:
        if insight.target_op == "eq":
            if not (_coerce_match(raw, insight.target_value)):
                return False
        elif insight.target_op == "gte":
            if not (float(raw) >= float(insight.target_value)):
                return False
        elif insight.target_op == "lte":
            if not (float(raw) <= float(insight.target_value)):
                return False
        elif insight.target_op == "lt":
            if not (float(raw) < float(insight.target_value)):
                return False
        else:
            return False
    except (ValueError, TypeError):
        return False

    # Secondary condition (AND logic)
    if insight.secondary_field is not None:
        raw2 = trade.get(insight.secondary_field)
        if insight.secondary_field == "entry_hour":
            hour = _get_entry_hour(trade)
            if hour is None:
                return False
            raw2 = hour
        if raw2 is None:
            return False
        op2 = insight.secondary_op or "eq"
        try:
            if op2 == "eq":
                if not _coerce_match(raw2, insight.secondary_value):
                    return False
            elif op2 == "gte":
                if not (float(raw2) >= float(insight.secondary_value)):
                    return False
            elif op2 == "lte":
                if not (float(raw2) <= float(insight.secondary_value)):
                    return False
            elif op2 == "lt":
                if not (float(raw2) < float(insight.secondary_value)):
                    return False
            else:
                return False
        except (ValueError, TypeError):
            return False

    return True


def _coerce_match(raw: Any, target: Any) -> bool:
    """Flexible equality: try numeric first, then string."""
    try:
        if float(raw) == float(target):
            return True
    except (ValueError, TypeError):
        pass
    return str(raw).strip().lower() == str(target).strip().lower()


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_structured_insights(
    trades: list[dict[str, Any]],
    starting_capital: float,
) -> list[InsightRecord]:
    """Recompute all dimensional checks from raw trade data.

    Returns InsightRecords sorted by rank_score descending,
    with eligibility applied. No text parsing. No side effects.
    """
    total = len(trades)
    if total == 0:
        return []

    all_insights: list[InsightRecord] = []

    # 1. Direction x Volatility
    vol_map = {"high": "high", "normal": "normal", "low": "low"}
    if any(t.get("volatility_regime") not in (None, "", "None") for t in trades):
        all_insights.extend(_check_direction_x_categorical(
            trades, total, "volatility_regime", vol_map, "weak_cell"))

    # 2. Direction x Trend
    trend_map = {"strong_up": "strong_up", "weak_up": "weak_up", "neutral": "neutral",
                 "weak_down": "weak_down", "strong_down": "strong_down"}
    if any(t.get("trend_label") not in (None, "", "None") for t in trades):
        all_insights.extend(_check_direction_x_categorical(
            trades, total, "trend_label", trend_map, "weak_cell"))

    # 3. Direction bias
    all_insights.extend(_check_direction_bias(trades, total))

    # 4. Session divergence
    all_insights.extend(_check_session_divergence(trades, total))

    # 5. Regime age gradient
    if any(t.get("regime_age") not in (None, "", "None", "nan") for t in trades):
        all_insights.extend(_check_regime_age_gradient(trades, total))

    # 6. Late NY asymmetry
    all_insights.extend(_check_late_ny_asymmetry(trades, total))

    # Apply eligibility
    for ins in all_insights:
        _apply_eligibility(ins, total)

    # Sort by rank_score descending
    all_insights.sort(key=lambda x: -x.rank_score)

    # Assign hypothesis_rank (1-based among eligible only)
    rank = 0
    for ins in all_insights:
        if ins.eligible:
            rank += 1
            ins.hypothesis_rank = rank

    # Compute matched trade indices for cross-dimension overlap detection
    for ins in all_insights:
        if not ins.eligible:
            continue
        matched = set()
        for idx, t in enumerate(trades):
            if _trade_matches_insight(t, ins):
                matched.add(idx)
        ins._matched_trade_indices = frozenset(matched)

    return all_insights


# ---------------------------------------------------------------------------
# Overlap & diversity guards (used by hypothesis-testing workflow)
# ---------------------------------------------------------------------------

def _get_value_range(insight: InsightRecord) -> tuple[str, Any, Any]:
    """Extract (field, lo, hi) for overlap checking. Returns canonical range."""
    field = insight.target_field
    lo = insight.target_value
    if insight.secondary_field == field:
        hi = insight.secondary_value
    elif insight.target_op == "eq":
        hi = lo
    else:
        hi = None  # open-ended
    return field, lo, hi


def _ranges_overlap(a_lo: Any, a_hi: Any, b_lo: Any, b_hi: Any) -> bool:
    """Check if two numeric ranges overlap. None means unbounded."""
    try:
        a_lo_f = float(a_lo) if a_lo is not None else float("-inf")
        a_hi_f = float(a_hi) if a_hi is not None else float("inf")
        b_lo_f = float(b_lo) if b_lo is not None else float("-inf")
        b_hi_f = float(b_hi) if b_hi is not None else float("inf")
        return a_lo_f <= b_hi_f and b_lo_f <= a_hi_f
    except (TypeError, ValueError):
        # Non-numeric fields: overlap only if values are identical
        return a_lo == b_lo


def check_overlap(candidate: InsightRecord, tested: list[InsightRecord]) -> bool:
    """Return True if candidate overlaps with any previously tested insight.

    Two overlap modes:
    1. Same-field overlap: same target_field AND overlapping value range.
    2. Cross-dimension overlap: different fields but >50% trade subset overlap.
       Catches cases like weak_cell(direction x trend) vs direction_bias(direction)
       where the excluded trades are largely the same set.
    """
    c_field, c_lo, c_hi = _get_value_range(candidate)

    for prev in tested:
        p_field, p_lo, p_hi = _get_value_range(prev)

        # Mode 1: Same-field range overlap
        if c_field == p_field:
            # If both have secondary fields, those must also match
            if candidate.secondary_field and candidate.secondary_field != candidate.target_field:
                if prev.secondary_field != candidate.secondary_field:
                    pass  # fall through to cross-dimension check
                elif prev.secondary_value != candidate.secondary_value:
                    pass  # fall through to cross-dimension check
                elif _ranges_overlap(c_lo, c_hi, p_lo, p_hi):
                    return True
            elif _ranges_overlap(c_lo, c_hi, p_lo, p_hi):
                return True

        # Mode 2: Cross-dimension trade subset overlap (>50%)
        if candidate._matched_trade_indices and prev._matched_trade_indices:
            intersection = len(candidate._matched_trade_indices & prev._matched_trade_indices)
            smaller = min(len(candidate._matched_trade_indices), len(prev._matched_trade_indices))
            if smaller > 0 and (intersection / smaller) > 0.5:
                return True

    return False


def check_diversity(candidate: InsightRecord, last_tested_class: str | None) -> bool:
    """Return True if candidate violates diversity (same class as last tested).

    None means no previous test — always passes.
    """
    if last_tested_class is None:
        return False
    return candidate.hypothesis_class == last_tested_class


def filter_next_candidates(
    eligible: list[InsightRecord],
    tested: list[InsightRecord],
    last_tested_class: str | None,
) -> list[InsightRecord]:
    """Filter eligible insights, removing overlapping and diversity-violating ones.

    Returns remaining candidates in rank order, annotated with skip reasons.
    """
    candidates = []
    for ins in eligible:
        if check_overlap(ins, tested):
            continue
        if check_diversity(ins, last_tested_class):
            continue
        candidates.append(ins)
    return candidates


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_hypothesis_report(
    strategy_name: str,
    insights: list[InsightRecord],
    total_trades: int,
) -> str:
    """Format insights into a readable text report."""
    lines = []
    lines.append(f"=== Hypothesis Report: {strategy_name} ({total_trades} trades) ===")
    lines.append("")

    eligible = [i for i in insights if i.eligible]
    ineligible = [i for i in insights if not i.eligible]

    lines.append(f"Eligible insights: {len(eligible)}  |  Filtered out: {len(ineligible)}")
    lines.append("")

    if eligible:
        lines.append("--- ELIGIBLE (ranked by score) ---")
        lines.append(f"{'Rank':<5} {'Class':<24} {'Score':>6} {'Conf':<6} {'Trades':>6} {'Pct':>5} {'Net PnL':>10} {'PF':>6} {'WR%':>5}  Filter")
        lines.append("-" * 112)
        for ins in eligible:
            filt = ins._describe()
            lines.append(
                f"H{ins.hypothesis_rank:<4} {ins.hypothesis_class:<24} {ins.rank_score:>6.2f} {ins.confidence:<6} "
                f"{ins.bucket_trades:>6} {ins.bucket_pct:>4.1f}% {ins.bucket_net_pnl:>10.2f} "
                f"{ins.bucket_pf:>6.3f} {ins.bucket_wr:>5.1f}  {filt}"
            )
        lines.append("")

    if ineligible:
        lines.append("--- FILTERED OUT ---")
        for ins in ineligible:
            reasons = ", ".join(ins.rejection_reasons)
            lines.append(f"  {ins.hypothesis_class}: {ins._describe()} — {reasons}")
        lines.append("")

    if not eligible:
        lines.append("No actionable hypotheses found for this strategy.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_trades(folder: Path) -> tuple[list[dict], float, str]:
    """Load trade data and metadata from a backtest folder."""
    csv_path = folder / "raw" / "results_tradelevel.csv"
    meta_path = folder / "metadata" / "run_metadata.json"

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing: {csv_path}")
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing: {meta_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        trades = list(csv.DictReader(f))

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    capital = meta.get("reference_capital_usd", 10000)
    strat = meta.get("strategy_name", folder.name)

    return trades, float(capital), strat


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Hypothesis Tester — Structured Insight Report")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("folder", nargs="?", help="Path to backtest folder")
    group.add_argument("--scan", help="Directive name to scan in backtests/")
    args = parser.parse_args()

    if args.scan:
        folders = sorted(BACKTESTS_DIR.glob(f"{args.scan}_*"))
        folders = [f for f in folders if f.is_dir() and (f / "raw" / "results_tradelevel.csv").exists()]
        if not folders:
            print(f"No valid folders found for: {args.scan}")
            sys.exit(1)

        # Aggregate trades across symbols
        all_trades = []
        capital = 10000.0
        strat = args.scan
        for folder in folders:
            trades, cap, s = _load_trades(folder)
            all_trades.extend(trades)
            capital = cap
            strat = s.rsplit("_", 1)[0] if "_" in s else s  # strip symbol suffix

        insights = extract_structured_insights(all_trades, capital)
        print(format_hypothesis_report(strat, insights, len(all_trades)))

    else:
        folder = Path(args.folder).resolve()
        trades, capital, strat = _load_trades(folder)
        insights = extract_structured_insights(trades, capital)
        print(format_hypothesis_report(strat, insights, len(trades)))


if __name__ == "__main__":
    main()
