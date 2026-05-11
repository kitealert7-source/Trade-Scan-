"""Verdict + Risk + Parent Δ block — top-of-report decision-guidance section.

Surfaces the CORE/WATCH/FAIL classification (currently buried in Excel `Notes`
sheet ~row 270), tail concentration / direction bias / longest flat-period
flags, and a one-row Δ vs the parent pass when one can be inferred.

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4:
- reuses `tools.filter_strategies._compute_candidate_status` directly
- reuses `tools.utils.research.robustness.tail_contribution` directly
- does not modify either source module
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


# Same thresholds as filter_strategies and feedback_promote_quality_gate.
_FLAG_TAIL_TOP5_THRESHOLD = 0.70           # top-5 trades > 70% of net PnL
_FLAG_DIR_IMBALANCE_THRESHOLD = 0.85       # one direction > 85% of positive PnL
_FLAG_FLAT_DAYS_THRESHOLD = 250            # longest no-new-equity-high in days
_FLAG_BODY_DEFICIT_THRESHOLD = -500.0      # body PnL after removing top-20 < -$500
_FLAG_LOSS_STREAK_THRESHOLD = 15           # >15 consecutive losses
_FLAG_WASTED_EDGE_THRESHOLD = 0.25         # >25% of trades hit ≥+2R MFE then closed <0R
_FLAG_STALL_DECAY_THRESHOLD = 0.50         # second half delivers <50% of first half (positive H1)


def _build_verdict_risk_section(directive_name: str, pl, totals: dict) -> list[str]:
    """Verdict + Risk + Parent Δ markdown block.

    Each subsection is fail-soft — a missing/malformed input degrades to a
    stub line rather than crashing the whole report.
    """
    md: list[str] = ["## Verdict & Risk\n"]

    verdict = _compute_verdict(directive_name, pl, totals)
    md.append(f"**Verdict:** {verdict['status']}")
    if verdict.get("rationale"):
        md.append(f"  ")
        md.append(f"*{verdict['rationale']}*")
    md.append("")

    flags = _compute_risk_flags(pl, totals)
    if flags:
        md.append("**Risk flags:**")
        for f in flags:
            md.append(f"- {f}")
        md.append("")
    else:
        md.append("**Risk flags:** none surfaced")
        md.append("")

    parent = _compute_parent_delta(directive_name, pl, totals)
    if parent is None:
        md.append("**Δ vs parent:** (no parent found in Master Filter — first pass or out-of-family)")
    elif parent.get("window_mismatch"):
        md.append(
            f"**Δ vs parent ({parent['parent']}):** unavailable (window mismatch)  "
        )
        md.append(f"*{parent['reason']}*")
    else:
        md.append(
            f"**Δ vs parent ({parent['parent']}):** "
            f"PnL {parent['pnl_delta']:+.2f}  | "
            f"SQN {parent['sqn_delta']:+.2f}  | "
            f"DD% {parent['dd_pct_delta']:+.2f}pp  | "
            f"Trades {parent['trades_delta']:+d}"
        )
    md.append("")

    md.append("---\n")
    return md


# ---------------------------------------------------------------------------
# Verdict (reuses tools.filter_strategies._compute_candidate_status)
# ---------------------------------------------------------------------------

def _compute_verdict(directive_name: str, pl, totals: dict) -> dict[str, Any]:
    """Build a 1-row DataFrame matching _compute_candidate_status's expected
    schema and run it. Returns {status, rationale}.
    """
    try:
        from tools.filter_strategies import _compute_candidate_status
    except Exception as e:
        return {"status": "UNKNOWN", "rationale": f"verdict logic unavailable ({type(e).__name__})"}

    try:
        trades = int(pl.portfolio_trades)
        # Derive trade_density (trades / year) from the pl date range.
        density = _derive_trade_density(pl, trades)
        expectancy = (pl.portfolio_pnl / trades) if trades > 0 else 0.0

        # Symbol used for asset-class detection — take first if multi-asset.
        symbol = _first_symbol(pl)

        row = {
            "strategy": directive_name,
            "symbol": symbol,
            "total_trades": trades,
            "max_dd_pct": float(totals.get("max_dd_pct", float("inf"))),
            "return_dd_ratio": float(totals.get("ret_dd", 0.0)),
            "sharpe_ratio": float(totals.get("sharpe", 0.0)),
            "sqn": float(totals.get("sqn", 0.0)),
            "profit_factor": float(totals.get("port_pf", 0.0)),
            "trade_density": density,
            "expectancy": expectancy,
        }
        df = pd.DataFrame([row])
        status = str(_compute_candidate_status(df).iloc[0])
        rationale = _verdict_rationale(row, status)
        return {"status": status, "rationale": rationale}
    except Exception as e:
        return {"status": "UNKNOWN", "rationale": f"verdict computation failed ({type(e).__name__}: {e})"}


def _verdict_rationale(row: dict, status: str) -> str:
    """One-sentence rationale that explicitly names the binding gate(s).

    Source of truth for thresholds: tools/filter_strategies.py:67-160. Any
    change to that authority must be mirrored here.
    """
    if status == "LIVE":
        return "Active in TS_Execution portfolio.yaml."
    if status == "FAIL":
        return "FAIL: " + "; ".join(_fail_gates_violated(row))
    if status == "CORE":
        return (
            f"CORE: SQN {row['sqn']:.2f} ≥ 2.5, Sharpe {row['sharpe_ratio']:.2f} ≥ 1.5, "
            f"R/DD {row['return_dd_ratio']:.2f} ≥ 2.0, DD {row['max_dd_pct']:.2f}% ≤ 30, "
            f"PF {row['profit_factor']:.2f} ≥ 1.25, density {row['trade_density']:.0f} ≥ 50."
        )
    if status == "RESERVE":
        return (
            "RESERVE: passes CORE gates but outranked by sibling variant on "
            "sqn × return_dd within family/symbol group."
        )
    # WATCH or UNKNOWN
    binding = _core_gates_missing(row)
    if binding:
        return (
            "WATCH — binding gate" + ("s" if len(binding) > 1 else "") + ": "
            + "; ".join(binding) + ". Other CORE gates passed."
        )
    return (
        f"WATCH: SQN {row['sqn']:.2f}, Sharpe {row['sharpe_ratio']:.2f}, "
        f"R/DD {row['return_dd_ratio']:.2f}, DD {row['max_dd_pct']:.2f}%, "
        f"PF {row['profit_factor']:.2f}, density {row['trade_density']:.0f} — "
        f"passes FAIL but no CORE gate identified as binding "
        f"(may indicate asset-class expectancy gate)."
    )


def _fail_gates_violated(row: dict) -> list[str]:
    """Which FAIL gate(s) from filter_strategies fired."""
    out: list[str] = []
    if row["total_trades"] < 50:
        out.append(f"trades {row['total_trades']} < 50")
    if row["max_dd_pct"] > 40:
        out.append(f"DD {row['max_dd_pct']:.1f}% > 40%")
    if row["sqn"] < 1.5:
        out.append(f"SQN {row['sqn']:.2f} < 1.5")
    # Expectancy is asset-class-dependent; named generically if no other gate fired.
    if not out:
        out.append("expectancy below asset-class FAIL gate")
    return out


def _core_gates_missing(row: dict) -> list[str]:
    """Which CORE gate(s) is the variant failing, in canonical order."""
    out: list[str] = []
    if row["sqn"] < 2.5:
        out.append(f"SQN {row['sqn']:.2f} < 2.5")
    if row["sharpe_ratio"] < 1.5:
        out.append(f"Sharpe {row['sharpe_ratio']:.2f} < 1.5")
    if row["return_dd_ratio"] < 2.0:
        out.append(f"R/DD {row['return_dd_ratio']:.2f} < 2.0")
    if row["max_dd_pct"] > 30.0:
        out.append(f"DD {row['max_dd_pct']:.2f}% > 30%")
    if row["trade_density"] < 50.0:
        out.append(f"density {row['trade_density']:.0f} < 50")
    if row["profit_factor"] < 1.25:
        out.append(f"PF {row['profit_factor']:.2f} < 1.25")
    return out


def _derive_trade_density(pl, trade_count: int) -> float:
    """Trades per year. Mirrors tools/metrics_core.py:855."""
    try:
        from datetime import datetime
        start = datetime.fromisoformat(str(pl.start_date)[:10])
        end = datetime.fromisoformat(str(pl.end_date)[:10])
        days = max((end - start).days, 1)
        return round(trade_count / (days / 365.25), 1)
    except Exception:
        return 0.0


def _first_symbol(pl) -> str:
    """First symbol from symbols_data, defaulting to empty string."""
    try:
        if pl.symbols_data:
            return str(pl.symbols_data[0].get("Symbol", ""))
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Risk flags (reuses tail_contribution; computes direction bias + flat period
# directly from trades — both are O(N) over the trade log, no new analytics)
# ---------------------------------------------------------------------------

def _compute_risk_flags(pl, totals: dict) -> list[str]:
    """Surface the highest-cost concentration / bias / dormancy risks."""
    flags: list[str] = []
    if not pl.all_trades_dfs:
        return flags
    try:
        df = pd.concat(pl.all_trades_dfs, ignore_index=True)
    except Exception:
        return flags
    if "pnl_usd" not in df.columns or len(df) == 0:
        return flags

    flags.extend(_tail_flag(df))
    flags.extend(_body_deficit_flag(df))
    flags.extend(_direction_imbalance_flag(df))
    flags.extend(_flat_period_flag(df))
    flags.extend(_loss_streak_flag(df))
    flags.extend(_wasted_edge_flag(df))
    flags.extend(_stall_decay_flag(df))
    return flags


def _tail_flag(df: pd.DataFrame) -> list[str]:
    """Top-5 trades' share of net PnL > 70% → flag."""
    try:
        from tools.utils.research.robustness import tail_contribution
        tail = tail_contribution(df)
        share = float(tail.get("top_5", 0.0))
        if share > _FLAG_TAIL_TOP5_THRESHOLD:
            return [
                f"⚠ **Tail concentration:** top-5 trades carry "
                f"{share * 100:.1f}% of net PnL (> {_FLAG_TAIL_TOP5_THRESHOLD * 100:.0f}% threshold). "
                f"Edge depends on a handful of outliers — fragile to a regime shift."
            ]
    except Exception:
        return []
    return []


def _body_deficit_flag(df: pd.DataFrame) -> list[str]:
    """Body PnL after removing top-20 trades < -$500 → flag."""
    try:
        sorted_pnl = df["pnl_usd"].astype(float).sort_values(ascending=False)
        if len(sorted_pnl) < 20:
            return []
        body = float(sorted_pnl.iloc[20:].sum())
        if body < _FLAG_BODY_DEFICIT_THRESHOLD:
            return [
                f"⚠ **Body deficit:** PnL after removing top-20 trades = "
                f"${body:,.2f} (< ${_FLAG_BODY_DEFICIT_THRESHOLD:.0f} threshold). "
                f"Net positive only because of tail; non-outlier body is loss-making."
            ]
    except Exception:
        return []
    return []


def _direction_imbalance_flag(df: pd.DataFrame) -> list[str]:
    """One direction carries >85% of POSITIVE PnL → flag."""
    if "direction" not in df.columns:
        return []
    try:
        pos = df[df["pnl_usd"].astype(float) > 0]
        total_pos = float(pos["pnl_usd"].sum())
        if total_pos <= 0:
            return []
        long_share = float(pos.loc[pos["direction"] == 1, "pnl_usd"].sum()) / total_pos
        short_share = float(pos.loc[pos["direction"] == -1, "pnl_usd"].sum()) / total_pos
        if long_share > _FLAG_DIR_IMBALANCE_THRESHOLD:
            return [
                f"⚠ **Direction bias:** longs carry "
                f"{long_share * 100:.1f}% of positive PnL "
                f"(> {_FLAG_DIR_IMBALANCE_THRESHOLD * 100:.0f}% threshold). "
                f"Single-sided edge — examine whether short branch is filter-only or dead weight."
            ]
        if short_share > _FLAG_DIR_IMBALANCE_THRESHOLD:
            return [
                f"⚠ **Direction bias:** shorts carry "
                f"{short_share * 100:.1f}% of positive PnL "
                f"(> {_FLAG_DIR_IMBALANCE_THRESHOLD * 100:.0f}% threshold). "
                f"Single-sided edge — examine whether long branch is filter-only or dead weight."
            ]
    except Exception:
        return []
    return []


def _loss_streak_flag(df: pd.DataFrame) -> list[str]:
    """Longest run of consecutive losing trades > threshold → flag."""
    if "entry_timestamp" not in df.columns:
        return []
    try:
        d = df.copy()
        d["entry_timestamp"] = pd.to_datetime(d["entry_timestamp"], errors="coerce")
        d = d.dropna(subset=["entry_timestamp"]).sort_values("entry_timestamp")
        if len(d) == 0:
            return []
        is_loss = (d["pnl_usd"].astype(float) < 0).values
        longest = 0
        cur = 0
        for v in is_loss:
            cur = cur + 1 if v else 0
            if cur > longest:
                longest = cur
        if longest > _FLAG_LOSS_STREAK_THRESHOLD:
            return [
                f"⚠ **Loss streak:** longest run of consecutive losing trades = "
                f"{longest} (> {_FLAG_LOSS_STREAK_THRESHOLD} threshold). "
                f"Capacity to ride extended losing stretches before any recovery — "
                f"psychological + capital strain risk."
            ]
    except Exception:
        return []
    return []


def _wasted_edge_flag(df: pd.DataFrame) -> list[str]:
    """Share of trades that reached MFE ≥ +2R but closed at < 0R > threshold → flag.

    Operationalises the idea that a strategy is leaving edge on the table
    when its exits don't capture observed favorable excursion.
    """
    if "mfe_r" not in df.columns or "r_multiple" not in df.columns:
        return []
    try:
        mfe = pd.to_numeric(df["mfe_r"], errors="coerce")
        r = pd.to_numeric(df["r_multiple"], errors="coerce")
        # Trades with valid MFE and valid R that reached at least +2R favorable then turned negative
        valid = mfe.notna() & r.notna()
        wasted_mask = valid & (mfe >= 2.0) & (r < 0.0)
        n_valid = int(valid.sum())
        if n_valid == 0:
            return []
        share = float(wasted_mask.sum()) / n_valid
        if share > _FLAG_WASTED_EDGE_THRESHOLD:
            return [
                f"⚠ **Wasted edge:** {share * 100:.1f}% of trades reached "
                f"≥+2R MFE then closed at < 0R "
                f"(> {_FLAG_WASTED_EDGE_THRESHOLD * 100:.0f}% threshold). "
                f"Exits are not capturing observed favorable excursion — likely too-tight trail "
                f"or premature stop-out."
            ]
    except Exception:
        return []
    return []


def _stall_decay_flag(df: pd.DataFrame) -> list[str]:
    """Second-half PnL delivers <50% of first-half PnL when first half is positive.

    Operationalises edge decay over time. Only fires when H1 > 0 (otherwise
    'decay' is ill-defined). Trades are split at the midpoint by entry order.
    """
    if "entry_timestamp" not in df.columns:
        return []
    try:
        d = df.copy()
        d["entry_timestamp"] = pd.to_datetime(d["entry_timestamp"], errors="coerce")
        d = d.dropna(subset=["entry_timestamp"]).sort_values("entry_timestamp").reset_index(drop=True)
        n = len(d)
        if n < 20:
            return []
        mid = n // 2
        h1 = float(d.iloc[:mid]["pnl_usd"].astype(float).sum())
        h2 = float(d.iloc[mid:]["pnl_usd"].astype(float).sum())
        if h1 <= 0:
            return []
        ratio = h2 / h1
        if ratio < _FLAG_STALL_DECAY_THRESHOLD:
            return [
                f"⚠ **Stall / decay:** second-half PnL = ${h2:,.2f} "
                f"is {ratio * 100:.0f}% of first-half ${h1:,.2f} "
                f"(< {_FLAG_STALL_DECAY_THRESHOLD * 100:.0f}% threshold). "
                f"Edge appears to be eroding over time — most-recent half is materially weaker."
            ]
    except Exception:
        return []
    return []


def _flat_period_flag(df: pd.DataFrame) -> list[str]:
    """Longest stretch with no new equity high > 250 days → flag."""
    if "exit_timestamp" not in df.columns:
        return []
    try:
        d = df.copy()
        d["exit_timestamp"] = pd.to_datetime(d["exit_timestamp"], errors="coerce")
        d = d.dropna(subset=["exit_timestamp"]).sort_values("exit_timestamp").reset_index(drop=True)
        if len(d) == 0:
            return []
        d["cum_pnl"] = d["pnl_usd"].astype(float).cumsum()
        d["peak"] = d["cum_pnl"].cummax()
        d["at_new_high"] = d["cum_pnl"] >= d["peak"]
        # Longest run of bars without a new high — measured in calendar days
        last_high_ts = d.loc[d["at_new_high"], "exit_timestamp"]
        if len(last_high_ts) == 0:
            return []
        # Map each row to the timestamp of its most-recent new-high
        d["ref_high_ts"] = last_high_ts.reindex(d.index).ffill()
        d["days_since_high"] = (d["exit_timestamp"] - d["ref_high_ts"]).dt.days
        longest = int(d["days_since_high"].max() or 0)
        if longest > _FLAG_FLAT_DAYS_THRESHOLD:
            return [
                f"⚠ **Flat period:** longest stretch with no new equity high = "
                f"{longest} days (> {_FLAG_FLAT_DAYS_THRESHOLD} threshold). "
                f"Strategy spent extended periods without progress — capital tied up unproductively."
            ]
    except Exception:
        return []
    return []


# ---------------------------------------------------------------------------
# Parent Δ (read-only Master Filter lookup; infer parent by pass-number heuristic)
# ---------------------------------------------------------------------------

def _compute_parent_delta(directive_name: str, pl, totals: dict) -> dict | None:
    """Find parent pass and compute metric deltas.

    Parent inference is naive: P(N) → P(N-1), then P(N-2), down to P00.
    First Master Filter row found wins. Returns None if no parent located.
    """
    import re
    m = re.search(r"_P(\d{2})(?:_|$)", directive_name)
    if not m:
        return None
    n = int(m.group(1))
    if n == 0:
        return None
    prefix = directive_name[: m.start()]
    symbol = _first_symbol(pl)

    try:
        from tools.ledger_db import read_master_filter
        mf = read_master_filter()
    except Exception:
        return None
    if mf is None or len(mf) == 0:
        return None

    # Master Filter `strategy` column appends `_<SYMBOL>` to the directive
    # name (e.g. `..._P13` → `..._P13_XAUUSD`). Match on the prefix to handle
    # both legacy bare-directive rows and the standard symbol-suffixed form.
    parent_name = None
    parent_row = None
    strat_col = mf.get("strategy", pd.Series(dtype=str)).astype(str)
    sym_col = mf.get("symbol", pd.Series(dtype=str)).astype(str)
    for pn in range(n - 1, -1, -1):
        candidate = f"{prefix}_P{pn:02d}"
        # Match either bare candidate or candidate_<SYMBOL>
        name_match = (strat_col == candidate) | strat_col.str.startswith(candidate + "_")
        rows = mf[name_match]
        if symbol and len(rows) > 0:
            rows = rows[rows["symbol"].astype(str) == symbol]
        if len(rows) > 0:
            parent_name = candidate
            parent_row = rows.iloc[0]
            break

    if parent_row is None:
        return None

    # Fix 2: window mismatch guard. If parent's test window differs from
    # current beyond tolerance, suppress the metric deltas — comparing across
    # windows is what produced false conclusions in the pre-recovery era
    # (REPORT_AUDIT §2.7, family report §11).
    window_ok, window_reason = _windows_compatible(
        pl.start_date, pl.end_date,
        parent_row.get("test_start"), parent_row.get("test_end"),
    )
    if not window_ok:
        return {
            "parent": parent_name,
            "window_mismatch": True,
            "reason": window_reason,
        }

    # Master Filter column names: total_net_profit (not realized_pnl),
    # max_dd_pct, sqn, total_trades.
    try:
        cur_pnl = float(pl.portfolio_pnl)
        cur_sqn = float(totals.get("sqn", 0.0))
        cur_dd = float(totals.get("max_dd_pct", 0.0))
        cur_trades = int(pl.portfolio_trades)
        p_pnl = float(parent_row.get("total_net_profit", 0.0))
        p_sqn = float(parent_row.get("sqn", 0.0))
        p_dd = float(parent_row.get("max_dd_pct", 0.0))
        p_trades = int(parent_row.get("total_trades", 0))
    except Exception:
        return None

    return {
        "parent": parent_name,
        "window_mismatch": False,
        "pnl_delta": cur_pnl - p_pnl,
        "sqn_delta": cur_sqn - p_sqn,
        "dd_pct_delta": cur_dd - p_dd,
        "trades_delta": cur_trades - p_trades,
    }


_PARENT_WINDOW_TOLERANCE_DAYS = 5


def _windows_compatible(cur_start, cur_end, p_start, p_end) -> tuple[bool, str]:
    """True iff parent and current backtest windows are within ±N days at
    each boundary. Returns (compatible, reason_if_not).
    """
    try:
        cs = pd.to_datetime(str(cur_start)[:10])
        ce = pd.to_datetime(str(cur_end)[:10])
        ps = pd.to_datetime(str(p_start)[:10])
        pe = pd.to_datetime(str(p_end)[:10])
    except Exception:
        return True, ""  # missing date — permissive on parse errors
    start_diff = abs((cs - ps).days)
    end_diff = abs((ce - pe).days)
    if start_diff > _PARENT_WINDOW_TOLERANCE_DAYS or end_diff > _PARENT_WINDOW_TOLERANCE_DAYS:
        return False, (
            f"current {cs.date()}..{ce.date()} vs parent {ps.date()}..{pe.date()} "
            f"(start Δ {start_diff}d, end Δ {end_diff}d > {_PARENT_WINDOW_TOLERANCE_DAYS}d tolerance)"
        )
    return True, ""
