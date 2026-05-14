"""basket_ledger.py — convert BasketRunResult into per-symbol-shaped artifacts.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5b.2 (Path B).

Phase 5b shipped basket dispatch but kept basket artifacts in a parallel
location (DRY_RUN_VAULT/baskets/, TradeScan_State/research/basket_runs.csv).
That made basket runs invisible to the per-symbol artifact tooling
(MPS, run_registry, backtests/ folder discovery).

This module is the converter. It maps a BasketRunResult into:
  - results_tradelevel.csv (per-symbol-shape DataFrame; one row per leg trade
    with `symbol` column distinguishing legs)
  - The trade dicts come from two sources:
      * engine `evaluate_bar()` emissions (rich schema: regime, trend, ATR)
      * recycle rule emissions (BASKET_RECYCLE_WINNER, BASKET_HARVEST_*) —
        sparser schema; we fill computable fields, leave engine-only fields
        as NaN.
  - Per-symbol schema is 31 columns (see PER_SYMBOL_TRADE_COLUMNS); the
    converter writes all of them so the per-symbol loader works untouched.

The per-symbol schema is the contract. If a future engine version changes
the per-symbol shape, this converter must stay in lockstep.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


__all__ = [
    "PER_SYMBOL_TRADE_COLUMNS",
    "basket_result_to_tradelevel_df",
    "leg_specs_string",
]


# Locked schema mirror — keep aligned with the per-symbol stage1 emitter.
# (Verified 2026-05-14 against
#  TradeScan_State/backtests/01_MR_FX_1H_ULTC_REGFILT_S07_V1_P01_EURUSD/raw/
#  results_tradelevel.csv header.)
PER_SYMBOL_TRADE_COLUMNS = [
    "run_id", "strategy_name", "parent_trade_id", "sequence_index",
    "entry_timestamp", "exit_timestamp",
    "direction", "entry_price", "exit_price", "pnl_usd", "r_multiple",
    "trade_high", "trade_low", "bars_held",
    "atr_entry", "position_units", "notional_usd",
    "mfe_price", "mae_price", "mfe_r", "mae_r",
    "volatility_regime", "trend_score", "trend_regime", "trend_label",
    "symbol",
    "initial_stop_price", "risk_distance",
    "market_regime", "regime_id", "regime_age",
]


_LOT_UNITS = 100_000


def leg_specs_string(legs: list[dict[str, Any]]) -> str:
    """Render legs as a human-readable string for the MPS leg_specs column.

    Format: "EURUSD:0.02:long;USDJPY:0.01:short"
    Semicolon-delimited per leg; colon-delimited triplets within a leg.
    Greppable, parseable, no JSON escaping needed.
    """
    parts: list[str] = []
    for leg in legs:
        parts.append(f"{leg['symbol']}:{leg['lot']}:{leg['direction']}")
    return ";".join(parts)


def _safe_get(d: dict, key: str, default=None):
    """dict.get with explicit default (avoids relying on key truthiness)."""
    v = d.get(key, default)
    return default if v is None else v


def _ts_at(df: pd.DataFrame, idx: int) -> Optional[pd.Timestamp]:
    """Return the DatetimeIndex value at positional index `idx`, or None."""
    if idx is None or idx < 0 or idx >= len(df):
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    return df.index[idx]


def _trade_to_row(
    trade: dict[str, Any],
    *,
    leg_symbol: str,
    leg_lot: float,
    leg_df: pd.DataFrame,
    run_id: str,
    strategy_name: str,
    sequence_index: int,
) -> dict[str, Any]:
    """Project a single basket trade dict into the per-symbol schema."""
    entry_idx = _safe_get(trade, "entry_index", -1)
    exit_idx = _safe_get(trade, "exit_index", -1)

    entry_ts = trade.get("entry_timestamp") or _ts_at(leg_df, entry_idx)
    exit_ts = trade.get("exit_timestamp") or _ts_at(leg_df, exit_idx)

    direction = _safe_get(trade, "direction", 0)
    entry_price = float(trade.get("entry_price", 0.0) or 0.0)
    exit_price = float(trade.get("exit_price", 0.0) or 0.0)

    # PnL: prefer engine-emitted; else compute from prices + lot via H2's
    # USD-quote / USD-base convention.
    pnl_usd = trade.get("pnl_usd")
    if pnl_usd is None:
        if leg_symbol.endswith("USD") and not leg_symbol.startswith("USD"):
            # USD_QUOTE: PnL = lot * units * (price - entry) * direction
            pnl_usd = direction * leg_lot * _LOT_UNITS * (exit_price - entry_price)
        elif leg_symbol.startswith("USD"):
            # USD_BASE: PnL = lot * units * (price - entry) / price * direction
            denom = exit_price if exit_price else 1.0
            pnl_usd = direction * leg_lot * _LOT_UNITS * (exit_price - entry_price) / denom
        else:
            pnl_usd = float("nan")
    pnl_usd = float(pnl_usd) if pnl_usd is not None else float("nan")

    bars_held = trade.get("bars_held")
    if bars_held is None and entry_idx >= 0 and exit_idx >= 0:
        bars_held = exit_idx - entry_idx

    position_units = leg_lot * _LOT_UNITS
    notional_usd = (
        position_units * entry_price
        if leg_symbol.endswith("USD") and not leg_symbol.startswith("USD")
        else position_units
    )

    return {
        "run_id":            run_id,
        "strategy_name":     strategy_name,
        "parent_trade_id":   sequence_index + 1,  # 1-based, matches per-symbol
        "sequence_index":    sequence_index,
        "entry_timestamp":   entry_ts,
        "exit_timestamp":    exit_ts,
        "direction":         direction,
        "entry_price":       entry_price,
        "exit_price":        exit_price,
        "pnl_usd":           pnl_usd,
        "r_multiple":        trade.get("r_multiple", float("nan")),
        "trade_high":        trade.get("trade_high", float("nan")),
        "trade_low":         trade.get("trade_low", float("nan")),
        "bars_held":         bars_held if bars_held is not None else float("nan"),
        "atr_entry":         trade.get("atr_entry", float("nan")),
        "position_units":    position_units,
        "notional_usd":      notional_usd,
        "mfe_price":         trade.get("mfe_price", float("nan")),
        "mae_price":         trade.get("mae_price", float("nan")),
        "mfe_r":             trade.get("mfe_r", float("nan")),
        "mae_r":             trade.get("mae_r", float("nan")),
        "volatility_regime": trade.get("volatility_regime", ""),
        "trend_score":       trade.get("trend_score", float("nan")),
        "trend_regime":      trade.get("trend_regime", float("nan")),
        "trend_label":       trade.get("trend_label", ""),
        "symbol":             leg_symbol,
        "initial_stop_price":trade.get("initial_stop_price", float("nan")),
        "risk_distance":     trade.get("risk_distance", float("nan")),
        "market_regime":     trade.get("market_regime", ""),
        "regime_id":         trade.get("regime_id", float("nan")),
        "regime_age":        trade.get("regime_age", float("nan")),
    }


def basket_result_to_tradelevel_df(
    basket_result: Any,
    *,
    run_id: str,
    directive_id: str,
    leg_data: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Convert a BasketRunResult into a per-symbol-shape tradelevel DataFrame.

    Args:
        basket_result: tools.basket_pipeline.BasketRunResult
        run_id:        12-char hex generated by tools.pipeline_utils.generate_run_id
        directive_id:  used as strategy_name (matches per-symbol convention
                       where strategy_name = the directive id)
        leg_data:      dict[symbol -> DataFrame] used for timestamp lookups
                       on trades whose entry/exit timestamps are missing

    Returns:
        DataFrame with PER_SYMBOL_TRADE_COLUMNS columns; one row per
        per-leg trade dict in basket_result.per_leg_trades.
    """
    # Build leg-spec lookup from result.legs (list of {symbol, lot, direction})
    leg_lot_lookup = {leg["symbol"]: float(leg["lot"]) for leg in basket_result.legs}

    rows: list[dict[str, Any]] = []
    seq = 0
    # Iterate per-leg trades in directive order so output is deterministic
    for leg_meta in basket_result.legs:
        sym = leg_meta["symbol"]
        leg_trades = basket_result.per_leg_trades.get(sym, [])
        leg_lot = leg_lot_lookup[sym]
        leg_df = leg_data.get(sym)
        if leg_df is None:
            # Caller didn't pass leg_data for this symbol; timestamps will be None
            leg_df = pd.DataFrame(index=pd.DatetimeIndex([]))
        for trade in leg_trades:
            rows.append(_trade_to_row(
                trade,
                leg_symbol=sym, leg_lot=leg_lot, leg_df=leg_df,
                run_id=run_id, strategy_name=directive_id,
                sequence_index=seq,
            ))
            seq += 1

    if not rows:
        # Empty DataFrame with the right schema (loader expects all columns)
        return pd.DataFrame(columns=PER_SYMBOL_TRADE_COLUMNS)

    df = pd.DataFrame(rows, columns=PER_SYMBOL_TRADE_COLUMNS)
    return df
