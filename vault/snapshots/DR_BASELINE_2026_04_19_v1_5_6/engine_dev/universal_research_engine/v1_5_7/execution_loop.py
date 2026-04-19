# =============================================================================
# Engine v1.5.7 — EXPERIMENTAL
# Successor to FROZEN v1.5.6. Do not promote to FROZEN without burn-in evidence
# and explicit go-live review.
#
# Changes over v1.5.6:
#   (A) check_partial_exit hook — single partial exit per trade
#   (B) check_stop_mutation  hook — monotone stop-loss adjustment (BE use-case)
#   (C) Canonical per-bar ordering: SL/TP -> partial -> stop_mutation -> check_exit
#   (D) ctx.unrealized_r  — close-based, deterministic: no MFE, no intrabar
#   (E) Trade dict optionally carries `partial_leg` + `partial_of_parent` fields
#
# v1.5.6 strategies (no partial/stop-mutation hooks) must produce byte-equivalent
# tradelevel output under v1.5.7. This invariant is enforced by the regression
# test in tests/engine/test_v157_engine_level.py.
# =============================================================================
"""
Universal Research Engine v1.5.7 — Execution Loop (EXPERIMENTAL)
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.

Hook contract additions (v1.5.7):

  check_partial_exit(ctx) -> dict | None
      Return {"fraction": float_in_(0.01, 0.99), "reason": str} to close a
      fraction of the open position at bar close. Fires AT MOST ONCE per
      trade. Engine guards: unrealized_r >= 1.0001, bars_held >= 1,
      partial_taken is False. Sub-dict ignored if any guard fails.

  check_stop_mutation(ctx) -> float | None
      Return absolute new SL price or None. Engine enforces monotone
      tightening: longs may only raise SL, shorts may only lower SL.
      Non-monotone updates are silently rejected (logged via the
      `stop_mutation_rejected` counter in the returned trade dict of the
      affected parent trade). SL used for risk-distance calculation
      (initial_stop_price) is FROZEN at entry and never mutated.

Canonical per-bar ordering (in-position branch):
  1) SL/TP resolution via resolve_exit()      — intrabar, highest priority
  2) Partial exit (if hook + guards pass)     — bar close, realized event
  3) Stop mutation (if hook returns value)    — applies from NEXT bar
  4) check_exit (time / signal)               — bar close, lowest priority

unrealized_r (ctx field, close-based):
  long:  (close - entry_price) / (entry_price - stop_price_initial)
  short: (entry_price - close) / (stop_price_initial - entry_price)
"""

from __future__ import annotations

import pandas as pd
from types import SimpleNamespace
from typing import Any

from engines.protocols import ContextViewProtocol, StrategyProtocol
from engines.regime_state_machine import apply_regime_model

__all__ = [
    "ContextView",
    "resolve_exit",
    "run_execution_loop",
    "ENGINE_VERSION",
    "ENGINE_STATUS",
]

ENGINE_ATR_MULTIPLIER = 2.0
ENGINE_VERSION    = "1.5.7"
ENGINE_STATUS     = "EXPERIMENTAL"
ENGINE_FREEZE_DATE = None  # EXPERIMENTAL engines do not have a freeze date.

# Guards for check_partial_exit (locked by design review 2026-04-19):
_PARTIAL_MIN_UNREALIZED_R = 1.0001   # epsilon tolerance vs float equality jitter
_PARTIAL_MIN_BARS_HELD    = 1        # never trigger on the entry bar
_PARTIAL_FRACTION_MIN     = 0.01
_PARTIAL_FRACTION_MAX     = 0.99


class ContextView:
    """Lightweight adapter wrapping context namespace to unify .get() and attribute access.

    Satisfies ContextViewProtocol (engines.protocols) — type-system enforced.
    """
    _ENGINE_PROTOCOL = True

    def __init__(self, ns: SimpleNamespace) -> None:
        self._ns = ns

    def get(self, key: str, default: Any = None) -> Any:
        try:
            val = getattr(self, key)
            if val is None:
                return default
            if pd.isna(val):
                return default
            return val
        except AttributeError:
            return default

    def require(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise RuntimeError(f"AUTHORITATIVE_INDICATOR_MISSING: '{key}'")
        return val

    def __getattr__(self, name: str) -> Any:
        if hasattr(self._ns, name):
            return getattr(self._ns, name)
        if hasattr(self._ns, 'row'):
            row_obj = getattr(self._ns, 'row')
            if hasattr(row_obj, 'get'):
                val = row_obj.get(name)
                if val is not None and not pd.isna(val):
                    return val
        raise AttributeError(f"'ContextView' object has no attribute '{name}'")


def resolve_exit(bar_row: pd.Series, position_state: dict[str, Any]) -> tuple[bool, float | None, str | None]:
    """
    Centralized OHLC exit resolver. Identical to v1.5.6.

    Priority: SL -> TP -> (strategy signal handled by caller)
    """
    bar_open = bar_row.get('open', bar_row['close'])
    bar_high = bar_row.get('high', bar_row['close'])
    bar_low  = bar_row.get('low',  bar_row['close'])

    direction  = position_state['direction']
    stop_price = position_state.get('stop_price')
    tp_price   = position_state.get('tp_price')

    if stop_price is not None:
        if direction == 1 and bar_low <= stop_price:
            fill = stop_price if stop_price <= bar_high else bar_open
            return True, fill, 'STOP'
        if direction == -1 and bar_high >= stop_price:
            fill = stop_price if stop_price >= bar_low else bar_open
            return True, fill, 'STOP'

    if tp_price is not None:
        if direction == 1 and bar_high >= tp_price:
            fill = tp_price if tp_price >= bar_low else bar_open
            return True, fill, 'TP'
        if direction == -1 and bar_low <= tp_price:
            fill = tp_price if tp_price <= bar_high else bar_open
            return True, fill, 'TP'

    return False, None, None


def _compute_unrealized_r(direction: int, close: float, entry_price: float,
                          stop_price_initial: float) -> float | None:
    """Close-based, deterministic r-multiple. Returns None if risk distance is
    zero or direction is invalid (defensive — both should be caught earlier)."""
    if direction == 1:
        denom = entry_price - stop_price_initial
        if denom <= 0:
            return None
        return (close - entry_price) / denom
    if direction == -1:
        denom = stop_price_initial - entry_price
        if denom <= 0:
            return None
        return (entry_price - close) / denom
    return None


def run_execution_loop(df: pd.DataFrame, strategy: StrategyProtocol) -> list[dict[str, Any]]:
    """
    v1.5.7 execution loop. Strategy-agnostic.

    Entry model:   signal on bar N -> fill at bar N+1 open  (next_bar_open)
    Exit model:    SL/TP intrabar; partial/stop-mutation/check_exit at bar close.
    Session guard: max 1 trade per UTC calendar day (unchanged from v1.5.6).

    Returns list of trade dicts. When a partial exit fired during a trade, the
    trade dict contains a `partial_leg` sub-dict with the partial close details
    AND `partial_of_parent = True`. Otherwise both fields are absent / False.
    """
    df = strategy.prepare_indicators(df)

    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.index = pd.DatetimeIndex(df['timestamp'])
        elif 'time' in df.columns:
            df.index = pd.DatetimeIndex(df['time'])

    try:
        df = apply_regime_model(df)
    except Exception as e:
        raise RuntimeError(f"Engine Regime Implementation Failed: {e}") from e

    trades = []

    _sig      = getattr(strategy, 'STRATEGY_SIGNATURE', {})
    _tmgmt    = _sig.get('trade_management', {})
    max_trades_per_session = _tmgmt.get('max_trades_per_session', None)
    session_reset_mode     = _tmgmt.get('session_reset', 'utc_day')

    _exec_rules = _sig.get('execution_rules', {}) or {}
    _sl_cfg     = _exec_rules.get('stop_loss', {}) or {}
    _tp_cfg     = _exec_rules.get('take_profit', {}) or {}
    try:
        _sl_mult_raw = _sl_cfg.get('atr_multiplier')
        sl_atr_mult  = float(_sl_mult_raw) if _sl_mult_raw is not None else ENGINE_ATR_MULTIPLIER
        if sl_atr_mult <= 0:
            sl_atr_mult = ENGINE_ATR_MULTIPLIER
    except (TypeError, ValueError):
        sl_atr_mult = ENGINE_ATR_MULTIPLIER
    try:
        _tp_mult_raw = _tp_cfg.get('atr_multiplier') if _tp_cfg.get('enabled', True) else None
        tp_atr_mult  = float(_tp_mult_raw) if _tp_mult_raw is not None else None
        if tp_atr_mult is not None and tp_atr_mult <= 0:
            tp_atr_mult = None
    except (TypeError, ValueError):
        tp_atr_mult = None

    # --- POSITION STATE ---
    in_pos      = False
    direction   = 0
    entry_index = 0
    entry_price = 0.0
    trade_high  = 0.0
    trade_low   = float('inf')
    entry_market_state: dict[str, Any] = {}

    # --- v1.5.7 PARTIAL/STOP-MUTATION STATE (per-trade, reset on entry/exit) ---
    partial_taken = False
    partial_leg: dict[str, Any] | None = None
    stop_price_active: float | None = None         # live SL (mutated); initial frozen in entry_market_state
    stop_mutation_rejected_count = 0

    # v1.5.7 feature detection
    _has_partial_hook  = hasattr(strategy, 'check_partial_exit') and callable(getattr(strategy, 'check_partial_exit'))
    _has_stop_mut_hook = hasattr(strategy, 'check_stop_mutation') and callable(getattr(strategy, 'check_stop_mutation'))

    # --- SESSION STATE ---
    session_trade_count  = 0
    current_session_date = None

    pending_entry = None

    for i in range(len(df)):
        row      = df.iloc[i]
        bar_date = df.index[i].date()

        if bar_date != current_session_date:
            current_session_date = bar_date
            if session_reset_mode == 'utc_day':
                session_trade_count = 0
            if session_reset_mode == 'utc_day':
                pending_entry = None

        # Build context (v1.5.7 adds unrealized_r when in position)
        _unrealized_r: float | None = None
        if in_pos:
            _unrealized_r = _compute_unrealized_r(
                direction,
                row['close'],
                entry_price,
                entry_market_state.get('initial_stop_price', entry_price),
            )

        ctx_ns = SimpleNamespace(
            row=row,
            index=i,
            direction=direction,
            trend_regime=row.get("trend_regime"),
            volatility_regime=row.get("volatility_regime"),
            entry_index=entry_index if in_pos else None,
            bars_held=(i - entry_index) if in_pos else 0,
            unrealized_r=_unrealized_r,
        )
        ctx = ContextView(ctx_ns)

        if not in_pos:
            # EXECUTE PENDING ENTRY at bar N+1 open
            if pending_entry is not None:
                pe           = pending_entry
                pending_entry = None
                pe_signal    = pe['signal']
                pe_direction = pe_signal.get('signal', 1)

                direction_allowed = True
                if hasattr(strategy, 'filter_stack'):
                    if not strategy.filter_stack.allow_direction(pe_direction):
                        direction_allowed = False

                if direction_allowed:
                    direction   = pe_direction
                    in_pos      = True
                    entry_index = i
                    entry_price = row.get('open', row['close'])

                    reference_entry_price = pe.get('reference_entry_price')
                    entry_reason          = pe.get('entry_reason')
                    trade_entry_slippage  = (
                        entry_price - reference_entry_price
                        if reference_entry_price is not None else None
                    )

                    strat_stop = pe_signal.get('stop_price')
                    if strat_stop is not None:
                        stop_price  = strat_stop
                        stop_source = 'STRATEGY'
                    else:
                        atr_at_signal = pe['atr']
                        if atr_at_signal <= 0:
                            raise ValueError(
                                "STOP CONTRACT VIOLATION: ATR invalid (<=0) at signal bar."
                            )
                        if direction == 1:
                            stop_price = entry_price - (atr_at_signal * sl_atr_mult)
                        else:
                            stop_price = entry_price + (atr_at_signal * sl_atr_mult)
                        stop_source = 'ENGINE_FALLBACK'

                    if direction == 1 and stop_price >= entry_price:
                        raise ValueError("STOP CONTRACT VIOLATION: Long stop >= entry")
                    if direction == -1 and stop_price <= entry_price:
                        raise ValueError("STOP CONTRACT VIOLATION: Short stop <= entry")

                    risk_distance = abs(entry_price - stop_price)
                    if risk_distance <= 0:
                        raise ValueError(
                            f"STOP CONTRACT VIOLATION: risk_distance <= 0 "
                            f"(entry={entry_price}, stop={stop_price})"
                        )

                    tp_price = pe_signal.get('tp_price')
                    if tp_price is None and tp_atr_mult is not None:
                        atr_at_signal = pe['atr']
                        if atr_at_signal > 0:
                            if direction == 1:
                                tp_price = entry_price + (atr_at_signal * tp_atr_mult)
                            else:
                                tp_price = entry_price - (atr_at_signal * tp_atr_mult)

                    entry_market_state = {
                        "volatility_regime":    pe['vol_regime'],
                        "trend_score":          pe['trend_score'],
                        "trend_regime":         pe['trend_regime'],
                        "trend_label":          pe['trend_label'],
                        "atr_entry":            pe['atr'],
                        "initial_stop_price":   stop_price,
                        "risk_distance":        risk_distance,
                        "tp_price":             tp_price,
                        "stop_source":          stop_source,
                        "entry_reference_price": reference_entry_price,
                        "entry_slippage":        trade_entry_slippage,
                        "entry_reason":          entry_reason,
                        "signal_bar_idx":        pe['signal_bar_idx'],
                        "fill_bar_idx":          i,
                        "regime_age_signal":     pe.get('regime_age_signal'),
                        "regime_age_fill":       row.get('regime_age'),
                        "market_regime_signal":  pe.get('market_regime_signal'),
                        "market_regime_fill":    row.get('market_regime'),
                        "regime_id_signal":      pe.get('regime_id_signal'),
                        "regime_id_fill":        row.get('regime_id'),
                        "regime_age_exec_signal": pe.get('regime_age_exec_signal'),
                        "regime_age_exec_fill":   row.get('regime_age_exec'),
                    }

                    trade_high = row.get('high', row['close'])
                    trade_low  = row.get('low',  row['close'])

                    # v1.5.7: reset per-trade partial / mutation state
                    partial_taken = False
                    partial_leg = None
                    stop_price_active = stop_price
                    stop_mutation_rejected_count = 0

                    continue

            # CHECK FOR NEW ENTRY SIGNAL
            allow_entry = (
                max_trades_per_session is None or
                session_trade_count < max_trades_per_session
            )
            if allow_entry:
                entry_signal = strategy.check_entry(ctx)
                if entry_signal:
                    vol_regime = ctx.require('volatility_regime')
                    try:
                        v_val = float(vol_regime)
                        if v_val >= 0.5:
                            vol_regime = "high"
                        elif v_val <= -0.5:
                            vol_regime = "low"
                        else:
                            vol_regime = "normal"
                    except (ValueError, TypeError):
                        pass

                    try:
                        _signal_regime_age = ctx.require('regime_age')
                    except RuntimeError:
                        _signal_regime_age = None
                    try:
                        _signal_market_regime = ctx.require('market_regime')
                    except RuntimeError:
                        _signal_market_regime = None
                    try:
                        _signal_regime_id = ctx.require('regime_id')
                    except RuntimeError:
                        _signal_regime_id = None
                    try:
                        _signal_regime_age_exec = ctx.require('regime_age_exec')
                    except RuntimeError:
                        _signal_regime_age_exec = None

                    pending_entry = {
                        'signal':                entry_signal,
                        'bar_idx':               i,
                        'signal_bar_idx':        i,
                        'vol_regime':            vol_regime,
                        'trend_score':           int(ctx.require('trend_score')),
                        'trend_regime':          int(ctx.require('trend_regime')),
                        'trend_label':           ctx.require('trend_label'),
                        'atr':                   ctx.require('atr'),
                        'regime_age_signal':     _signal_regime_age,
                        'market_regime_signal':  _signal_market_regime,
                        'regime_id_signal':      _signal_regime_id,
                        'regime_age_exec_signal': _signal_regime_age_exec,
                        'reference_entry_price': entry_signal.get('entry_reference_price'),
                        'entry_reason':          entry_signal.get('entry_reason'),
                    }

        else:
            # --- UPDATE TRADE EXTREMA ---
            bar_high = row.get('high', row['close'])
            bar_low  = row.get('low',  row['close'])
            if bar_high > trade_high:
                trade_high = bar_high
            if bar_low < trade_low:
                trade_low = bar_low

            # ====================================================================
            # v1.5.7 CANONICAL PER-BAR ORDERING:
            #   1) SL/TP resolution
            #   2) Partial exit
            #   3) Stop mutation
            #   4) check_exit
            # ====================================================================

            # --- (1) SL / TP RESOLUTION ---
            position_state = {
                'direction':  direction,
                'stop_price': stop_price_active if stop_price_active is not None
                              else entry_market_state.get('initial_stop_price'),
                'tp_price':   entry_market_state.get('tp_price'),
            }
            exit_triggered, exit_price, exit_source = resolve_exit(row, position_state)

            # --- (2) PARTIAL EXIT (only if SL/TP did NOT fire this bar) ---
            if (not exit_triggered) and _has_partial_hook and (not partial_taken):
                bars_held_now = i - entry_index
                ur = _unrealized_r  # already computed for ctx
                guards_pass = (
                    bars_held_now >= _PARTIAL_MIN_BARS_HELD
                    and ur is not None
                    and ur >= _PARTIAL_MIN_UNREALIZED_R
                )
                if guards_pass:
                    partial_sig = strategy.check_partial_exit(ctx)
                    if partial_sig is not None:
                        frac = float(partial_sig.get('fraction', 0.0))
                        if _PARTIAL_FRACTION_MIN <= frac <= _PARTIAL_FRACTION_MAX:
                            partial_leg = {
                                'exit_index':     i,
                                'exit_price':     row['close'],
                                'exit_timestamp': row.get('timestamp', row.get('time', df.index[i])),
                                'fraction':       frac,
                                'reason':         str(partial_sig.get('reason', 'partial')),
                                'bars_held':      bars_held_now,
                                'trade_high':     trade_high,
                                'trade_low':      trade_low,
                                'unrealized_r':   ur,
                            }
                            partial_taken = True

            # --- (3) STOP MUTATION (monotone; applies from next bar) ---
            if (not exit_triggered) and _has_stop_mut_hook:
                new_sl = strategy.check_stop_mutation(ctx)
                if new_sl is not None:
                    try:
                        new_sl_f = float(new_sl)
                    except (TypeError, ValueError):
                        new_sl_f = None
                    if new_sl_f is not None:
                        current_sl = stop_price_active if stop_price_active is not None \
                            else entry_market_state.get('initial_stop_price')
                        monotone_ok = (
                            (direction == 1  and new_sl_f > current_sl) or
                            (direction == -1 and new_sl_f < current_sl)
                        )
                        if monotone_ok:
                            stop_price_active = new_sl_f
                        else:
                            stop_mutation_rejected_count += 1

            # --- (4) check_exit (time / signal) ---
            if not exit_triggered and strategy.check_exit(ctx):
                exit_triggered = True
                exit_price = row['close']
                is_time_exit = (
                    bool(row.get('is_exit_time', False)) or
                    bool(row.get('is_penultimate_bar', False))
                )
                exit_source = 'TIME_EXIT' if is_time_exit else 'SIGNAL_EXIT'

            if exit_triggered:
                trade = {
                    "entry_index":        entry_index,
                    "exit_index":         i,
                    "entry_price":        entry_price,
                    "exit_price":         exit_price,
                    "direction":          direction,
                    "bars_held":          i - entry_index,
                    "entry_timestamp":    df.iloc[entry_index].get(
                                             'timestamp',
                                             df.iloc[entry_index].get('time', None)
                                         ),
                    "exit_timestamp":     row.get('timestamp', row.get('time', None)),
                    "trade_high":         trade_high,
                    "trade_low":          trade_low,
                    "volatility_regime":  entry_market_state['volatility_regime'],
                    "trend_score":        entry_market_state['trend_score'],
                    "trend_regime":       entry_market_state['trend_regime'],
                    "trend_label":        entry_market_state['trend_label'],
                    "atr_entry":          entry_market_state['atr_entry'],
                    "initial_stop_price": entry_market_state['initial_stop_price'],
                    "risk_distance":      entry_market_state['risk_distance'],
                    "exit_source":        exit_source,
                    "stop_source":        entry_market_state['stop_source'],
                    "entry_reference_price": entry_market_state.get('entry_reference_price'),
                    "entry_slippage":        entry_market_state.get('entry_slippage'),
                    "entry_reason":          entry_market_state.get('entry_reason'),
                    "signal_bar_idx":        entry_market_state.get('signal_bar_idx'),
                    "fill_bar_idx":          entry_market_state.get('fill_bar_idx'),
                    "regime_age_signal":     entry_market_state.get('regime_age_signal'),
                    "regime_age_fill":       entry_market_state.get('regime_age_fill'),
                    "market_regime_signal":  entry_market_state.get('market_regime_signal'),
                    "market_regime_fill":    entry_market_state.get('market_regime_fill'),
                    "regime_id_signal":      entry_market_state.get('regime_id_signal'),
                    "regime_id_fill":        entry_market_state.get('regime_id_fill'),
                    "regime_age_exec_signal": entry_market_state.get('regime_age_exec_signal'),
                    "regime_age_exec_fill":   entry_market_state.get('regime_age_exec_fill'),
                }
                # v1.5.7 additions — only populated when a partial fired on this
                # trade. When absent the dict shape matches v1.5.6 exactly, so
                # no-hook strategies emit byte-identical output downstream.
                if partial_leg is not None:
                    trade["partial_leg"] = partial_leg
                    trade["partial_of_parent"] = True
                if stop_mutation_rejected_count > 0:
                    trade["stop_mutation_rejected"] = stop_mutation_rejected_count

                trades.append(trade)
                session_trade_count += 1

                # Reset position + v1.5.7 state
                in_pos      = False
                direction   = 0
                entry_index = 0
                entry_price = 0.0
                trade_high  = 0.0
                trade_low   = float('inf')
                entry_market_state = {}
                partial_taken = False
                partial_leg = None
                stop_price_active = None
                stop_mutation_rejected_count = 0

    # --- FORCE-CLOSE: open position at end of data ---
    if in_pos and len(df) > 0:
        last_row = df.iloc[-1]
        last_i = len(df) - 1
        trade = {
            "entry_index":        entry_index,
            "exit_index":         last_i,
            "entry_price":        entry_price,
            "exit_price":         last_row['close'],
            "direction":          direction,
            "bars_held":          last_i - entry_index,
            "entry_timestamp":    df.iloc[entry_index].get(
                                      'timestamp',
                                      df.iloc[entry_index].get('time', None)
                                  ),
            "exit_timestamp":     last_row.get('timestamp', last_row.get('time', None)),
            "trade_high":         trade_high,
            "trade_low":          trade_low,
            "volatility_regime":  entry_market_state.get('volatility_regime'),
            "trend_score":        entry_market_state.get('trend_score'),
            "trend_regime":       entry_market_state.get('trend_regime'),
            "trend_label":        entry_market_state.get('trend_label'),
            "atr_entry":          entry_market_state.get('atr_entry'),
            "initial_stop_price": entry_market_state.get('initial_stop_price'),
            "risk_distance":      entry_market_state.get('risk_distance'),
            "exit_source":        'DATA_END',
            "stop_source":        entry_market_state.get('stop_source'),
            "entry_reference_price": entry_market_state.get('entry_reference_price'),
            "entry_slippage":        entry_market_state.get('entry_slippage'),
            "entry_reason":          entry_market_state.get('entry_reason'),
            "signal_bar_idx":        entry_market_state.get('signal_bar_idx'),
            "fill_bar_idx":          entry_market_state.get('fill_bar_idx'),
            "regime_age_signal":     entry_market_state.get('regime_age_signal'),
            "regime_age_fill":       entry_market_state.get('regime_age_fill'),
            "market_regime_signal":  entry_market_state.get('market_regime_signal'),
            "market_regime_fill":    entry_market_state.get('market_regime_fill'),
            "regime_id_signal":      entry_market_state.get('regime_id_signal'),
            "regime_id_fill":        entry_market_state.get('regime_id_fill'),
            "regime_age_exec_signal": entry_market_state.get('regime_age_exec_signal'),
            "regime_age_exec_fill":   entry_market_state.get('regime_age_exec_fill'),
        }
        if partial_leg is not None:
            trade["partial_leg"] = partial_leg
            trade["partial_of_parent"] = True
        if stop_mutation_rejected_count > 0:
            trade["stop_mutation_rejected"] = stop_mutation_rejected_count
        trades.append(trade)

    return trades
