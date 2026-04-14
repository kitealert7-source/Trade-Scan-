# =============================================================================
# WARNING: Execution engine frozen.
# Do not modify execution behavior.
# Any change requires a new engine version and full strategy re-run.
# Freeze date: 2026-03-31  |  ENGINE_STATUS = FROZEN
# =============================================================================
"""
Universal Research Engine v1.5.2 — Execution Loop
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.

v1.5.0 changes (hardening pass, 2026-03-10):
  - resolve_exit(): centralized OHLC exit resolver (SL → TP → strategy signal)
  - Gap-through stop/TP: fills at bar_open, not stop/tp_price
  - next_bar_open entry: signal on bar N → fill at bar N+1 open
  - Session guard: max 1 trade per UTC calendar day; resets on date boundary
  - exit_source (STOP|TP|TIME_EXIT|SIGNAL_EXIT) and stop_source
    (STRATEGY|ENGINE_FALLBACK) added to every trade record

v1.5.1 changes (trade-management generalization, 2026-03-10):
  - max_trades_per_session read from STRATEGY_SIGNATURE.trade_management
  - None = unlimited; N = per-session cap; session_reset modes: utc_day | none

v1.5.2 changes (entry diagnostics, 2026-03-10):
  - check_entry() may optionally return entry_reference_price and entry_reason
  - entry_slippage = entry_price - entry_reference_price stored per trade
  - All three optional fields propagated through pending_entry → trade record
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

ENGINE_ATR_MULTIPLIER = 2.0  # Last-resort default; overridden per-run by
                             # STRATEGY_SIGNATURE.execution_rules.stop_loss.atr_multiplier
                             # when present (see _resolve_atr_multipliers below).
ENGINE_VERSION    = "1.5.6"
ENGINE_STATUS     = "PROBE"  # Experimental — dual regime-age clock + cross-flip
                             # probe. NOT vaulted. Last stable vaulted engine is
                             # v1.5.5 (DR_BASELINE_2026_04_14_v0_0_0). Do not
                             # treat v1.5.6 output as production; promote only
                             # after cross-flip edge validates or is discarded.
ENGINE_FREEZE_DATE = None  # Intentionally unfrozen — probe branch


class ContextView:
    """Lightweight adapter wrapping context namespace to unify .get() and attribute access.

    Satisfies ContextViewProtocol (engines.protocols) — type-system enforced.
    Also retains _ENGINE_PROTOCOL marker for backward-compatible runtime checks
    in FilterStack.allow_trade().
    """
    _ENGINE_PROTOCOL = True  # Legacy marker — kept for FilterStack backward compat

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
    Centralized OHLC exit resolver.

    Priority: SL → TP → (strategy signal handled by caller)

    Gap handling:
      LONG stop gapped-down (stop_price > bar_high) → fill at bar_open
      SHORT stop gapped-up  (stop_price < bar_low)  → fill at bar_open
      LONG TP gapped-up     (tp_price < bar_low)    → fill at bar_open
      SHORT TP gapped-down  (tp_price > bar_high)   → fill at bar_open

    In all gap cases bar_open represents the first realistic traded price,
    which is worse than stop_price for stops (correct) and better than
    tp_price for TPs (correct — gap in your favour).

    Args:
        bar_row:        current bar as pandas Series (open, high, low, close)
        position_state: dict with keys:
                          direction   (int: 1=long, -1=short)
                          stop_price  (float)
                          tp_price    (float | None)

    Returns:
        (exit_triggered: bool, exit_price: float | None, exit_source: str | None)
        exit_source in {'STOP', 'TP'}; None when no OHLC exit triggered.
    """
    bar_open = bar_row.get('open', bar_row['close'])
    bar_high = bar_row.get('high', bar_row['close'])
    bar_low  = bar_row.get('low',  bar_row['close'])

    direction  = position_state['direction']
    stop_price = position_state.get('stop_price')
    tp_price   = position_state.get('tp_price')

    # --- 1. SL check (highest priority) ---
    if stop_price is not None:
        if direction == 1 and bar_low <= stop_price:
            # Normal: stop inside bar → fill at stop.
            # Gap-down: entire bar below stop → fill at bar_open (realistic worst-case).
            fill = stop_price if stop_price <= bar_high else bar_open
            return True, fill, 'STOP'
        if direction == -1 and bar_high >= stop_price:
            # Normal: stop inside bar → fill at stop.
            # Gap-up: entire bar above stop → fill at bar_open (realistic worst-case).
            fill = stop_price if stop_price >= bar_low else bar_open
            return True, fill, 'STOP'

    # --- 2. TP check (second priority; only reached if SL did not trigger) ---
    if tp_price is not None:
        if direction == 1 and bar_high >= tp_price:
            # Normal: TP inside bar → fill at tp.
            # Gap-up: entire bar above TP → fill at bar_open (realistic best-case).
            fill = tp_price if tp_price >= bar_low else bar_open
            return True, fill, 'TP'
        if direction == -1 and bar_low <= tp_price:
            # Normal: TP inside bar → fill at tp.
            # Gap-down: entire bar below TP → fill at bar_open (realistic best-case).
            fill = tp_price if tp_price <= bar_high else bar_open
            return True, fill, 'TP'

    return False, None, None


def run_execution_loop(df: pd.DataFrame, strategy: StrategyProtocol) -> list[dict[str, Any]]:
    """
    Hardened execution loop. Strategy-agnostic.

    Entry model:   signal on bar N → fill at bar N+1 open  (next_bar_open)
    Exit model:    SL/TP resolved intrabar via resolve_exit(); strategy
                   time/signal exits fill at bar close.
    Session guard: max 1 trade per UTC calendar day.

    Returns list of trade dicts with entry/exit details.
    Tracks trade_high (MAX of bar highs) and trade_low (MIN of bar lows)
    from entry_bar to exit_bar inclusive.
    """
    df = strategy.prepare_indicators(df)

    # --- ENSURE DATETIME INDEX ---
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.index = pd.DatetimeIndex(df['timestamp'])
        elif 'time' in df.columns:
            df.index = pd.DatetimeIndex(df['time'])

    # --- INTRINSIC MARKET REGIME DETECTION (STATE MACHINE v2) ---
    # Replaces legacy hardcoded indicators from Stage 1/2.
    # Applied once per dataset for performance and determinism.
    try:
        df = apply_regime_model(df)
    except Exception as e:
        raise RuntimeError(f"Engine Regime Implementation Failed: {e}") from e

    # ==========================================

    trades = []

    # --- TRADE MANAGEMENT POLICY (read from STRATEGY_SIGNATURE) ---
    # max_trades_per_session = None  → unlimited (no guard applied)
    # max_trades_per_session = N     → at most N trades per session
    # session_reset_mode = 'utc_day' → counter resets at UTC midnight (default)
    # session_reset_mode = 'none'    → counter never resets
    _sig      = getattr(strategy, 'STRATEGY_SIGNATURE', {})
    _tmgmt    = _sig.get('trade_management', {})
    max_trades_per_session = _tmgmt.get('max_trades_per_session', None)
    session_reset_mode     = _tmgmt.get('session_reset', 'utc_day')

    # --- ATR FALLBACK MULTIPLIERS (engine fallback when strategy omits
    # stop_price / tp_price; see STOP CONTRACT guard in governance/).
    # Authority: STRATEGY_SIGNATURE.execution_rules.stop_loss.atr_multiplier
    #            STRATEGY_SIGNATURE.execution_rules.take_profit.atr_multiplier
    # Missing/invalid → SL falls back to ENGINE_ATR_MULTIPLIER, TP falls back to None.
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
    entry_market_state = {}

    # --- SESSION STATE ---
    session_trade_count  = 0    # increments on every trade close
    current_session_date = None

    # --- PENDING ENTRY (next_bar_open execution) ---
    # Stores signal + signal-bar market state; executed at next bar's open.
    # Discarded if a new session starts before execution.
    pending_entry = None

    for i in range(len(df)):
        row      = df.iloc[i]
        bar_date = df.index[i].date()

        # --- SESSION RESET ---
        if bar_date != current_session_date:
            current_session_date = bar_date
            if session_reset_mode == 'utc_day':
                session_trade_count = 0
            # Signal from the previous session is stale; discard it.
            if session_reset_mode == 'utc_day':
                pending_entry = None

        # Build context
        ctx_ns = SimpleNamespace(
            row=row,
            index=i,
            direction=direction,
            trend_regime=row.get("trend_regime"),
            volatility_regime=row.get("volatility_regime"),
            entry_index=entry_index if in_pos else None,
            bars_held=(i - entry_index) if in_pos else 0,
        )
        ctx = ContextView(ctx_ns)

        if not in_pos:
            # -------------------------------------------------------
            # EXECUTE PENDING ENTRY at bar N+1 open
            # -------------------------------------------------------
            if pending_entry is not None:
                pe           = pending_entry
                pending_entry = None
                pe_signal    = pe['signal']
                pe_direction = pe_signal.get('signal', 1)

                # Phase 2: Engine-Level Directional Gating
                direction_allowed = True
                if hasattr(strategy, 'filter_stack'):
                    if not strategy.filter_stack.allow_direction(pe_direction):
                        direction_allowed = False

                if direction_allowed:
                    direction   = pe_direction
                    in_pos      = True
                    entry_index = i
                    entry_price = row.get('open', row['close'])  # next_bar_open fill

                    # Entry diagnostics (v1.5.2)
                    reference_entry_price = pe.get('reference_entry_price')
                    entry_reason          = pe.get('entry_reason')
                    trade_entry_slippage  = (
                        entry_price - reference_entry_price
                        if reference_entry_price is not None else None
                    )

                    # Stop: strategy-provided takes priority; otherwise ATR fallback
                    # using ATR captured at the signal bar (bar N).
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

                    # Hard invariants
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
                    # TP engine fallback (symmetric to SL fallback above):
                    # if strategy omits tp_price and signature declares a TP
                    # ATR multiplier, compute TP from actual fill price.
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
                        # Entry diagnostics (v1.5.2)
                        "entry_reference_price": reference_entry_price,
                        "entry_slippage":        trade_entry_slippage,
                        "entry_reason":          entry_reason,
                        # v1.5.5 signal/fill alignment — explicit dual-time state.
                        # signal_bar_idx: df row where strategy decided (bar N).
                        # fill_bar_idx:   df row where fill executed (bar N+1 = i).
                        # regime_age_signal: regime age at decision time.
                        # regime_age_fill:  regime age at fill time (read at bar i).
                        "signal_bar_idx":        pe['signal_bar_idx'],
                        "fill_bar_idx":          i,
                        "regime_age_signal":     pe.get('regime_age_signal'),
                        "regime_age_fill":       row.get('regime_age'),
                        "market_regime_signal":  pe.get('market_regime_signal'),
                        "market_regime_fill":    row.get('market_regime'),
                        "regime_id_signal":      pe.get('regime_id_signal'),
                        "regime_id_fill":        row.get('regime_id'),
                        # v1.5.6 exec-TF clock probe (bars-since-regime-change at exec granularity)
                        "regime_age_exec_signal": pe.get('regime_age_exec_signal'),
                        "regime_age_exec_fill":   row.get('regime_age_exec'),
                    }

                    # Initialize trade extrema from entry bar
                    trade_high = row.get('high', row['close'])
                    trade_low  = row.get('low',  row['close'])

                    # Entry executed on this bar — begin exit checks from next bar.
                    continue

            # -------------------------------------------------------
            # CHECK FOR NEW ENTRY SIGNAL (session guard enforced here)
            # -------------------------------------------------------
            allow_entry = (
                max_trades_per_session is None or
                session_trade_count < max_trades_per_session
            )
            if allow_entry:
                entry_signal = strategy.check_entry(ctx)
                if entry_signal:
                    # Capture signal-bar market state for stop computation on next bar.
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
                        pass  # Already a string label

                    # Capture signal-bar regime state for downstream alignment.
                    # regime_age is optional (strategies without regime model omit it);
                    # fall back to None rather than raising so non-regime strategies
                    # continue to work unchanged.
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
                    # v1.5.6 exec-TF clock probe
                    try:
                        _signal_regime_age_exec = ctx.require('regime_age_exec')
                    except RuntimeError:
                        _signal_regime_age_exec = None

                    pending_entry = {
                        'signal':                entry_signal,
                        'bar_idx':               i,  # legacy alias of signal_bar_idx
                        'signal_bar_idx':        i,  # v1.5.5: explicit signal index
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
            # -------------------------------------------------------
            # UPDATE TRADE EXTREMA
            # -------------------------------------------------------
            bar_high = row.get('high', row['close'])
            bar_low  = row.get('low',  row['close'])
            if bar_high > trade_high:
                trade_high = bar_high
            if bar_low < trade_low:
                trade_low = bar_low

            # -------------------------------------------------------
            # OHLC EXIT RESOLUTION (SL → TP → strategy signal)
            # -------------------------------------------------------
            position_state = {
                'direction':  direction,
                'stop_price': entry_market_state.get('initial_stop_price'),
                'tp_price':   entry_market_state.get('tp_price'),
            }
            exit_triggered, exit_price, exit_source = resolve_exit(row, position_state)

            # Strategy time/signal exit — lowest priority, fills at bar close.
            if not exit_triggered and strategy.check_exit(ctx):
                exit_triggered = True
                exit_price = row['close']
                # Best-effort source classification based on common strategy columns.
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
                    # Intrinsic market state (captured at signal bar)
                    "volatility_regime":  entry_market_state['volatility_regime'],
                    "trend_score":        entry_market_state['trend_score'],
                    "trend_regime":       entry_market_state['trend_regime'],
                    "trend_label":        entry_market_state['trend_label'],
                    "atr_entry":          entry_market_state['atr_entry'],
                    "initial_stop_price": entry_market_state['initial_stop_price'],
                    "risk_distance":      entry_market_state['risk_distance'],
                    # Exit and stop diagnostics
                    "exit_source":        exit_source,
                    "stop_source":        entry_market_state['stop_source'],
                    # Entry diagnostics (v1.5.2) — None when strategy does not provide them
                    "entry_reference_price": entry_market_state.get('entry_reference_price'),
                    "entry_slippage":        entry_market_state.get('entry_slippage'),
                    "entry_reason":          entry_market_state.get('entry_reason'),
                    # v1.5.5 signal/fill alignment — explicit decision vs execution indices.
                    "signal_bar_idx":        entry_market_state.get('signal_bar_idx'),
                    "fill_bar_idx":          entry_market_state.get('fill_bar_idx'),
                    "regime_age_signal":     entry_market_state.get('regime_age_signal'),
                    "regime_age_fill":       entry_market_state.get('regime_age_fill'),
                    "market_regime_signal":  entry_market_state.get('market_regime_signal'),
                    "market_regime_fill":    entry_market_state.get('market_regime_fill'),
                    "regime_id_signal":      entry_market_state.get('regime_id_signal'),
                    "regime_id_fill":        entry_market_state.get('regime_id_fill'),
                    # v1.5.6 exec-TF clock probe
                    "regime_age_exec_signal": entry_market_state.get('regime_age_exec_signal'),
                    "regime_age_exec_fill":   entry_market_state.get('regime_age_exec_fill'),
                }
                trades.append(trade)

                # Increment session trade counter (applies regardless of exit source).
                session_trade_count += 1

                # Reset position state
                in_pos      = False
                direction   = 0
                entry_index = 0
                entry_price = 0.0
                trade_high  = 0.0
                trade_low   = float('inf')
                entry_market_state = {}

    # --- FORCE-CLOSE: open position at end of data ---
    # If a trade is still open when data ends, close it at the last bar's close.
    # Without this, unrealized losers (trades that never hit SL/TP) are silently
    # dropped, systematically biasing backtest results.
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
            # v1.5.5 signal/fill alignment
            "signal_bar_idx":        entry_market_state.get('signal_bar_idx'),
            "fill_bar_idx":          entry_market_state.get('fill_bar_idx'),
            "regime_age_signal":     entry_market_state.get('regime_age_signal'),
            "regime_age_fill":       entry_market_state.get('regime_age_fill'),
            "market_regime_signal":  entry_market_state.get('market_regime_signal'),
            "market_regime_fill":    entry_market_state.get('market_regime_fill'),
            "regime_id_signal":      entry_market_state.get('regime_id_signal'),
            "regime_id_fill":        entry_market_state.get('regime_id_fill'),
            # v1.5.6 exec-TF clock probe
            "regime_age_exec_signal": entry_market_state.get('regime_age_exec_signal'),
            "regime_age_exec_fill":   entry_market_state.get('regime_age_exec_fill'),
        }
        trades.append(trade)

    return trades
