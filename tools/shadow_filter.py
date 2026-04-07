"""
shadow_filter.py — Trade Filter Impact Analysis

Given a list of trades and a filter specification, evaluates the metric
impact of excluding matching trades. Pure analysis tool — no pipeline
integration, no file I/O, no side effects.

Usage:
    from tools.shadow_filter import evaluate_shadow_filter, compare_shadow_filters

    result = evaluate_shadow_filter(trades, starting_capital, filter_spec)
    print(result.deltas)

Filter spec example:
    {
        "label": "Excl. range_high_vol x fresh",
        "logic": "AND",
        "conditions": [
            {"field": "market_regime", "op": "eq",  "value": "range_high_vol"},
            {"field": "regime_age",    "op": "lte", "value": 2}
        ]
    }

Supported operators: eq, neq, lt, lte, gt, gte, in, not_in
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.metrics_core import compute_metrics_from_trades

# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

@dataclass
class ShadowResult:
    filter_label: str
    baseline: dict
    filtered: dict
    excluded_count: int
    excluded_pct: float
    deltas: dict


# ---------------------------------------------------------------------------
# Filter evaluation
# ---------------------------------------------------------------------------

def _match_condition(trade: dict[str, Any], condition: dict[str, Any]) -> bool:
    """Return True if the trade matches a single condition.

    Missing fields are treated as non-matching — the trade is kept.
    """
    field_name = condition.get("field", "")
    op = condition.get("op", "eq")
    target = condition.get("value")

    raw = trade.get(field_name)
    if raw is None:
        return False

    # Coerce to numeric when target is numeric and raw is a string
    value: Any = raw
    if isinstance(target, (int, float)) and not isinstance(raw, (int, float)):
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return False

    try:
        if op == "eq":
            return value == target
        if op == "neq":
            return value != target
        if op == "lt":
            return float(value) < float(target)
        if op == "lte":
            return float(value) <= float(target)
        if op == "gt":
            return float(value) > float(target)
        if op == "gte":
            return float(value) >= float(target)
        if op == "in":
            return value in target
        if op == "not_in":
            return value not in target
    except (TypeError, ValueError):
        return False

    return False


def _apply_filter(
    trades: list[dict[str, Any]],
    filter_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return a new list with trades matching filter_spec removed.

    Does not mutate the input list.
    Logic defaults to AND if not specified.
    Empty conditions → all trades kept.
    """
    conditions = filter_spec.get("conditions", [])
    if not conditions:
        return list(trades)

    logic = str(filter_spec.get("logic", "AND")).upper()

    result = []
    for trade in trades:
        matches = [_match_condition(trade, c) for c in conditions]
        if logic == "OR":
            excluded = any(matches)
        else:  # AND (default)
            excluded = all(matches)
        if not excluded:
            result.append(trade)

    return result


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

_DELTA_KEYS = (
    "total_trades",
    "net_profit",
    "profit_factor",
    "pct_profitable",   # win rate (0..100 in metrics_core output)
    "avg_trade",
    "max_dd_usd",
    "sharpe_ratio",
)

# Keys where percentage change is meaningful (non-zero baseline expected)
_PCT_CHANGE_KEYS = frozenset({
    "net_profit", "profit_factor", "pct_profitable", "avg_trade", "sharpe_ratio",
})


def _compute_deltas(
    baseline: dict[str, Any],
    filtered: dict[str, Any],
) -> dict[str, Any]:
    """Return absolute and percentage deltas for key metrics."""
    deltas: dict[str, Any] = {}

    for key in _DELTA_KEYS:
        b_val = baseline.get(key, 0.0)
        f_val = filtered.get(key, 0.0)

        try:
            b = float(b_val) if b_val is not None else 0.0
            f = float(f_val) if f_val is not None else 0.0
        except (TypeError, ValueError):
            b, f = 0.0, 0.0

        abs_delta = f - b
        entry: dict[str, Any] = {"absolute": round(abs_delta, 4)}

        if key in _PCT_CHANGE_KEYS and b != 0.0:
            entry["pct_change"] = round((abs_delta / abs(b)) * 100, 2)

        deltas[key] = entry

    return deltas


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_shadow_filter(
    trades: list[dict[str, Any]],
    starting_capital: float,
    filter_spec: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> ShadowResult:
    """Evaluate the metric impact of excluding trades matching filter_spec.

    Args:
        trades:           Full trade list (not mutated).
        starting_capital: Reference capital for drawdown/return metrics.
        filter_spec:      Filter definition dict (see module docstring).
        metadata:         Optional run metadata forwarded to metrics_core.

    Returns:
        ShadowResult with baseline, filtered metrics, counts, and deltas.
    """
    label = filter_spec.get("label", "unnamed_filter")

    baseline_metrics = compute_metrics_from_trades(trades, starting_capital, metadata=metadata)

    filtered_trades = _apply_filter(trades, filter_spec)
    filtered_metrics = compute_metrics_from_trades(filtered_trades, starting_capital, metadata=metadata)

    n_total = len(trades)
    n_excluded = n_total - len(filtered_trades)
    excluded_pct = round((n_excluded / n_total) * 100, 2) if n_total > 0 else 0.0

    deltas = _compute_deltas(baseline_metrics, filtered_metrics)

    return ShadowResult(
        filter_label=label,
        baseline=baseline_metrics,
        filtered=filtered_metrics,
        excluded_count=n_excluded,
        excluded_pct=excluded_pct,
        deltas=deltas,
    )


def compare_shadow_filters(
    trades: list[dict[str, Any]],
    starting_capital: float,
    filter_specs: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> list[ShadowResult]:
    """Evaluate multiple filter specs against the same trade list.

    Returns one ShadowResult per spec, in input order.
    """
    return [
        evaluate_shadow_filter(trades, starting_capital, spec, metadata=metadata)
        for spec in filter_specs
    ]
