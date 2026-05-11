"""Family-report verdict orchestration.

Calls the canonical `tools.filter_strategies._compute_candidate_status` for
each variant in the family, then layers on advisory "spirit of the gate"
overrides surfaced as soft FAIL gates per `memory/feedback_promote_quality_gate.md`:

  - Top-5 concentration > 70% of net PnL          → effective FAIL
  - Body-after-Top-20 PnL < -$500                 → effective FAIL
  - Longest flat period > 250 days                → effective FAIL

The family report's verdict is **advisory** — it never modifies
`Filtered_Strategies_Passed.xlsx`. Canonical promotion still goes through
`tools/filter_strategies.py`.

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4: this module
calls the canonical authority directly; it does not duplicate verdict logic.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Soft-gate thresholds (advisory)
_SOFT_TAIL_TOP5_THRESHOLD = 0.70
_SOFT_BODY_DEFICIT_THRESHOLD = -500.0
_SOFT_FLAT_DAYS_THRESHOLD = 250


def compute_family_verdicts(
    rows_df: pd.DataFrame,
    trades_by_variant: dict[str, pd.DataFrame] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute the {CORE/WATCH/FAIL/RESERVE/LIVE} verdict for every variant
    in `rows_df`, then apply soft-gate overrides where trade data is provided.

    Args:
        rows_df: one row per variant. Must carry the columns
            `_compute_candidate_status` expects: strategy, symbol, total_trades,
            max_dd_pct, return_dd_ratio, sharpe_ratio, sqn, profit_factor,
            trade_density, expectancy.
        trades_by_variant: optional mapping {variant_strategy_name -> trade_df}.
            When supplied, soft-gate overrides are evaluated per variant.

    Returns:
        {variant_strategy_name: {
            "status": "CORE" | "WATCH" | "FAIL" | "RESERVE" | "LIVE",
            "effective_status": same set + "FAIL (effective)" when a soft gate trips,
            "rationale": short string,
            "soft_gate_trips": list[str],
        }}
    """
    from tools.filter_strategies import _compute_candidate_status

    if rows_df is None or len(rows_df) == 0:
        return {}

    # Canonical verdict per row.
    status_series = _compute_candidate_status(rows_df)

    out: dict[str, dict[str, Any]] = {}
    for idx, row in rows_df.iterrows():
        name = str(row.get("strategy", f"row_{idx}"))
        status = str(status_series.iloc[idx]) if idx < len(status_series) else "UNKNOWN"

        # Soft-gate evaluation from trade-level data
        trips: list[str] = []
        if trades_by_variant:
            tdf = trades_by_variant.get(name)
            if tdf is not None and len(tdf) > 0:
                trips = _evaluate_soft_gates(tdf)

        effective = status
        if status in ("CORE", "WATCH") and trips:
            effective = "FAIL (effective)"

        rationale = _build_rationale(status, effective, row, trips)
        out[name] = {
            "status": status,
            "effective_status": effective,
            "rationale": rationale,
            "soft_gate_trips": trips,
        }
    return out


# ---------------------------------------------------------------------------
# Soft gates
# ---------------------------------------------------------------------------

def _evaluate_soft_gates(trades_df: pd.DataFrame) -> list[str]:
    """Return list of human-readable trip messages for any tripped soft gate."""
    trips: list[str] = []

    # Top-5 concentration
    try:
        from tools.utils.research.robustness import tail_contribution
        tail = tail_contribution(trades_df)
        share = float(tail.get("top_5", 0.0))
        if share > _SOFT_TAIL_TOP5_THRESHOLD:
            trips.append(
                f"Top-5 concentration {share * 100:.1f}% > "
                f"{_SOFT_TAIL_TOP5_THRESHOLD * 100:.0f}% (soft FAIL)"
            )
    except Exception:
        pass

    # Body deficit after Top-20
    try:
        sorted_pnl = trades_df["pnl_usd"].astype(float).sort_values(ascending=False)
        if len(sorted_pnl) >= 20:
            body = float(sorted_pnl.iloc[20:].sum())
            if body < _SOFT_BODY_DEFICIT_THRESHOLD:
                trips.append(
                    f"Body-after-Top-20 = ${body:,.2f} < ${_SOFT_BODY_DEFICIT_THRESHOLD:,.0f} "
                    f"(soft FAIL — tail-dependent)"
                )
    except Exception:
        pass

    # Longest flat period
    try:
        d = trades_df.copy()
        if "exit_timestamp" in d.columns:
            d["exit_timestamp"] = pd.to_datetime(d["exit_timestamp"], errors="coerce")
            d = d.dropna(subset=["exit_timestamp"]).sort_values("exit_timestamp").reset_index(drop=True)
            if len(d) > 0:
                d["cum_pnl"] = d["pnl_usd"].astype(float).cumsum()
                d["peak"] = d["cum_pnl"].cummax()
                d["at_new_high"] = d["cum_pnl"] >= d["peak"]
                last_high_ts = d.loc[d["at_new_high"], "exit_timestamp"]
                if len(last_high_ts) > 0:
                    d["ref_high_ts"] = last_high_ts.reindex(d.index).ffill()
                    d["days_since_high"] = (d["exit_timestamp"] - d["ref_high_ts"]).dt.days
                    longest = int(d["days_since_high"].max() or 0)
                    if longest > _SOFT_FLAT_DAYS_THRESHOLD:
                        trips.append(
                            f"Longest flat period {longest}d > "
                            f"{_SOFT_FLAT_DAYS_THRESHOLD}d (soft FAIL)"
                        )
    except Exception:
        pass

    return trips


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def _build_rationale(
    canonical_status: str,
    effective_status: str,
    row: pd.Series,
    soft_trips: list[str],
) -> str:
    """One-line rationale citing canonical gates and soft-gate trips."""
    parts: list[str] = []

    sqn = _f(row.get("sqn"))
    sharpe = _f(row.get("sharpe_ratio"))
    rdd = _f(row.get("return_dd_ratio"))
    dd_pct = _f(row.get("max_dd_pct"))
    pf = _f(row.get("profit_factor"))
    trades = int(row.get("total_trades") or 0)

    if canonical_status == "CORE":
        parts.append(
            f"CORE: SQN {sqn:.2f}, Sharpe {sharpe:.2f}, R/DD {rdd:.2f}, "
            f"DD {dd_pct:.2f}%, PF {pf:.2f}, trades {trades}."
        )
    elif canonical_status == "WATCH":
        binding = _binding_core_gates(row)
        if binding:
            parts.append(f"WATCH — binding gate(s): {'; '.join(binding)}.")
        else:
            parts.append(
                f"WATCH: SQN {sqn:.2f}, Sharpe {sharpe:.2f}, R/DD {rdd:.2f}, "
                f"DD {dd_pct:.2f}%, PF {pf:.2f} — passes FAIL but no single CORE gate identified."
            )
    elif canonical_status == "FAIL":
        parts.append(f"FAIL canonical (SQN {sqn:.2f}, DD {dd_pct:.2f}%, trades {trades}).")
    elif canonical_status == "RESERVE":
        parts.append("RESERVE: passes CORE but outranked by sibling.")
    elif canonical_status == "LIVE":
        parts.append("LIVE: active in TS_Execution portfolio.yaml.")

    if soft_trips:
        if effective_status == "FAIL (effective)":
            parts.append("Soft gate(s) tripped → effective FAIL:")
        else:
            parts.append("Soft gate(s):")
        for t in soft_trips:
            parts.append(f"  • {t}")

    return " ".join(parts) if len(parts) == 1 else "\n".join(parts)


def _binding_core_gates(row: pd.Series) -> list[str]:
    """Which CORE gate(s) is the variant failing — in canonical order."""
    out: list[str] = []
    if _f(row.get("sqn")) < 2.5:
        out.append(f"SQN {_f(row.get('sqn')):.2f} < 2.5")
    if _f(row.get("sharpe_ratio")) < 1.5:
        out.append(f"Sharpe {_f(row.get('sharpe_ratio')):.2f} < 1.5")
    if _f(row.get("return_dd_ratio")) < 2.0:
        out.append(f"R/DD {_f(row.get('return_dd_ratio')):.2f} < 2.0")
    if _f(row.get("max_dd_pct")) > 30.0:
        out.append(f"DD {_f(row.get('max_dd_pct')):.2f}% > 30%")
    if _f(row.get("trade_density")) < 50.0:
        out.append(f"density {_f(row.get('trade_density')):.0f} < 50")
    if _f(row.get("profit_factor")) < 1.25:
        out.append(f"PF {_f(row.get('profit_factor')):.2f} < 1.25")
    return out


def _f(v) -> float:
    """Safe float coercion."""
    try:
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0
    except Exception:
        return 0.0
