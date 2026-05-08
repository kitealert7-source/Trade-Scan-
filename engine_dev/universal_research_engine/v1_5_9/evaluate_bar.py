# =============================================================================
# Engine v1.5.9 — EXPERIMENTAL — extraction of v1.5.8 per-bar block.
#
# Purpose:
#   Lift the per-bar logic of v1.5.8's run_execution_loop() into a standalone
#   callable evaluate_bar(df, i, state, strategy, config), so the same per-bar
#   logic is reusable from a streaming live runtime without re-implementation.
#
#   This is a MECHANICAL EXTRACTION ONLY. No logic changes, no cleanup, no
#   refactor beyond threading outer-scope locals through a BarState dataclass
#   and resolved-config locals through an EngineConfig dataclass.
#
#   v1.5.8's run_execution_loop body, lines 263-644 of v1.5.8/execution_loop.py,
#   becomes the body of evaluate_bar() here. v1.5.8's force-close epilogue,
#   lines 646-694, becomes finalize_force_close() here. Helpers (ContextView,
#   resolve_exit, _compute_unrealized_r*) are lifted verbatim.
#
#   v1.5.9/execution_loop.py is reduced to setup + per-bar dispatch + finalize.
#
# Acceptance criterion:
#   Backtest output (signals, trades, ledger) byte-identical to v1.5.8 for
#   every strategy.  Tested on:
#     33_TREND_BTCUSD_1H_IMPULSE_S03_V1_P02 (sanity)
#     62_TREND_IDX_5M_KALFLIP_S01_V2_P15    (hardest)
#     27_MR_XAUUSD_1H_PINBAR_S01_V1_P05     (cross-archetype)
# =============================================================================
"""
Universal Research Engine v1.5.9 — Per-bar Evaluator (EXPERIMENTAL).
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.

Hook contract (inherited from v1.5.8, unchanged):

  check_partial_exit(ctx) -> dict | None
  check_stop_mutation(ctx) -> float | None

ctx fields and per-bar ordering identical to v1.5.8.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from engines.protocols import ContextViewProtocol, StrategyProtocol

__all__ = [
    "ContextView",
    "BarState",
    "EngineConfig",
    "resolve_exit",
    "resolve_engine_config",
    "evaluate_bar",
    "finalize_force_close",
    "ENGINE_ATR_MULTIPLIER",
]

# Engine constants (lifted verbatim from v1.5.8)
ENGINE_ATR_MULTIPLIER = 2.0

# Guards for check_partial_exit (locked by design review 2026-04-19)
_PARTIAL_MIN_UNREALIZED_R = 1.0001   # epsilon tolerance vs float equality jitter
_PARTIAL_MIN_BARS_HELD    = 1        # never trigger on the entry bar
_PARTIAL_FRACTION_MIN     = 0.01
_PARTIAL_FRACTION_MAX     = 0.99


# =============================================================================
# ContextView — lifted verbatim from v1.5.8
# =============================================================================

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


# =============================================================================
# resolve_exit + r-multiple helpers — lifted verbatim from v1.5.8
# =============================================================================

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


def _compute_unrealized_r_intrabar(direction: int, bar_high: float, bar_low: float,
                                   entry_price: float,
                                   stop_price_initial: float) -> float | None:
    """Intrabar R-multiple using bar_high (longs) or bar_low (shorts).
    Denominator is the initial risk distance — same as _compute_unrealized_r.
    Use this in check_stop_mutation for BE so the trigger aligns with
    resolve_exit() which also checks bar_low/bar_high for SL/TP."""
    if direction == 1:
        denom = entry_price - stop_price_initial
        if denom <= 0:
            return None
        return (bar_high - entry_price) / denom
    if direction == -1:
        denom = stop_price_initial - entry_price
        if denom <= 0:
            return None
        return (entry_price - bar_low) / denom
    return None


# =============================================================================
# BarState — cross-bar mutable state (NEW for v1.5.9)
#
# Captures every outer-scope local variable that v1.5.8's for-loop body reads
# from or writes to. Threading these through a dataclass is the only structural
# change v1.5.9 makes vs v1.5.8.
# =============================================================================

@dataclass
class BarState:
    # Position state
    in_pos:      bool                  = False
    direction:   int                   = 0
    entry_index: int                   = 0
    entry_price: float                 = 0.0
    trade_high:  float                 = 0.0
    trade_low:   float                 = float('inf')
    entry_market_state: dict[str, Any] = field(default_factory=dict)

    # v1.5.7+ partial / stop-mutation state (per-trade, reset on entry/exit)
    partial_taken:                bool                = False
    partial_leg:                  dict[str, Any] | None = None
    stop_price_active:            float | None        = None
    stop_mutation_rejected_count: int                 = 0

    # Session state
    session_trade_count:  int          = 0
    current_session_date: Any          = None

    # Pending next-bar-open entry
    pending_entry: dict[str, Any] | None = None


# =============================================================================
# EngineConfig — resolved STRATEGY_SIGNATURE config (NEW for v1.5.9)
#
# Lifts the once-per-run setup block (v1.5.8 lines 215-256) into a function
# that returns this dataclass. Per-bar code reads from this; never mutates.
# =============================================================================

@dataclass
class EngineConfig:
    sl_atr_mult:            float
    tp_atr_mult:            float | None
    max_trades_per_session: int | None
    session_reset_mode:     str
    has_partial_hook:       bool
    has_stop_mut_hook:      bool


def resolve_engine_config(strategy: StrategyProtocol) -> EngineConfig:
    """Resolve STRATEGY_SIGNATURE config + hook detection into EngineConfig.

    Lifted verbatim (only restructured into return value) from v1.5.8 lines 215-256.
    """
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

    has_partial_hook  = hasattr(strategy, 'check_partial_exit') and callable(getattr(strategy, 'check_partial_exit'))
    has_stop_mut_hook = hasattr(strategy, 'check_stop_mutation') and callable(getattr(strategy, 'check_stop_mutation'))

    return EngineConfig(
        sl_atr_mult            = sl_atr_mult,
        tp_atr_mult            = tp_atr_mult,
        max_trades_per_session = max_trades_per_session,
        session_reset_mode     = session_reset_mode,
        has_partial_hook       = has_partial_hook,
        has_stop_mut_hook      = has_stop_mut_hook,
    )


# =============================================================================
# evaluate_bar — body of v1.5.8 for-loop, lifted verbatim (state-threaded).
#
# Returns:
#   trade_dict on bar where exit is triggered (caller appends to trades list)
#   None       on every other bar
# Side effects:
#   Mutates `state` in place (entry, exit, partial, stop mutation, session
#   counters). Caller passes the same BarState across consecutive bars.
# =============================================================================

def evaluate_bar(
    df:       pd.DataFrame,
    i:        int,
    state:    BarState,
    strategy: StrategyProtocol,
    config:   EngineConfig,
) -> dict[str, Any] | None:
    """Per-bar evaluator. Body of v1.5.8 run_execution_loop's for-loop, verbatim
    apart from state.X / config.X substitutions for outer-scope variables.

    Mechanical lift: every line below corresponds to a line in v1.5.8/execution_loop.py
    lines 263-644.  Logic, ordering, and arithmetic are unchanged.
    """
    row      = df.iloc[i]
    bar_date = df.index[i].date()

    if bar_date != state.current_session_date:
        state.current_session_date = bar_date
        if config.session_reset_mode == 'utc_day':
            state.session_trade_count = 0
        if config.session_reset_mode == 'utc_day':
            state.pending_entry = None

    # Build context (v1.5.8 adds unrealized_r_intrabar alongside close-based unrealized_r)
    _unrealized_r:          float | None = None
    _unrealized_r_intrabar: float | None = None
    if state.in_pos:
        _initial_stop = state.entry_market_state.get('initial_stop_price', state.entry_price)
        _unrealized_r = _compute_unrealized_r(
            state.direction,
            row['close'],
            state.entry_price,
            _initial_stop,
        )
        _unrealized_r_intrabar = _compute_unrealized_r_intrabar(
            state.direction,
            row.get('high', row['close']),
            row.get('low',  row['close']),
            state.entry_price,
            _initial_stop,
        )

    ctx_ns = SimpleNamespace(
        row=row,
        index=i,
        direction=state.direction,
        trend_regime=row.get("trend_regime"),
        volatility_regime=row.get("volatility_regime"),
        entry_index=state.entry_index if state.in_pos else None,
        entry_price=state.entry_price if state.in_pos else None,
        bars_held=(i - state.entry_index) if state.in_pos else 0,
        unrealized_r=_unrealized_r,
        unrealized_r_intrabar=_unrealized_r_intrabar,
    )
    ctx = ContextView(ctx_ns)

    if not state.in_pos:
        # EXECUTE PENDING ENTRY at bar N+1 open
        if state.pending_entry is not None:
            pe            = state.pending_entry
            state.pending_entry = None
            pe_signal     = pe['signal']
            if 'signal' not in pe_signal:
                raise RuntimeError(
                    "check_entry() return dict missing required field 'signal'. "
                    "Contract v1.2 requires pe_signal['signal'] in {-1, +1}."
                )
            pe_direction = pe_signal['signal']

            direction_allowed = True
            if hasattr(strategy, 'filter_stack'):
                if not strategy.filter_stack.allow_direction(pe_direction):
                    direction_allowed = False

            if direction_allowed:
                state.direction   = pe_direction
                state.in_pos      = True
                state.entry_index = i
                state.entry_price = row.get('open', row['close'])

                reference_entry_price = pe.get('reference_entry_price')
                entry_reason          = pe.get('entry_reason')
                trade_entry_slippage  = (
                    state.entry_price - reference_entry_price
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
                    if state.direction == 1:
                        stop_price = state.entry_price - (atr_at_signal * config.sl_atr_mult)
                    else:
                        stop_price = state.entry_price + (atr_at_signal * config.sl_atr_mult)
                    stop_source = 'ENGINE_FALLBACK'

                if state.direction == 1 and stop_price >= state.entry_price:
                    raise ValueError("STOP CONTRACT VIOLATION: Long stop >= entry")
                if state.direction == -1 and stop_price <= state.entry_price:
                    raise ValueError("STOP CONTRACT VIOLATION: Short stop <= entry")

                risk_distance = abs(state.entry_price - stop_price)
                if risk_distance <= 0:
                    raise ValueError(
                        f"STOP CONTRACT VIOLATION: risk_distance <= 0 "
                        f"(entry={state.entry_price}, stop={stop_price})"
                    )

                tp_price = pe_signal.get('tp_price')
                if tp_price is None and config.tp_atr_mult is not None:
                    atr_at_signal = pe['atr']
                    if atr_at_signal > 0:
                        if state.direction == 1:
                            tp_price = state.entry_price + (atr_at_signal * config.tp_atr_mult)
                        else:
                            tp_price = state.entry_price - (atr_at_signal * config.tp_atr_mult)

                state.entry_market_state = {
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

                state.trade_high = row.get('high', row['close'])
                state.trade_low  = row.get('low',  row['close'])

                # v1.5.7: reset per-trade partial / mutation state
                state.partial_taken = False
                state.partial_leg = None
                state.stop_price_active = stop_price
                state.stop_mutation_rejected_count = 0

                # v1.5.8 'continue' — no further per-bar work this bar
                return None

        # CHECK FOR NEW ENTRY SIGNAL
        allow_entry = (
            config.max_trades_per_session is None or
            state.session_trade_count < config.max_trades_per_session
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

                state.pending_entry = {
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

        # No trade completed on this bar
        return None

    else:
        # --- UPDATE TRADE EXTREMA ---
        bar_high = row.get('high', row['close'])
        bar_low  = row.get('low',  row['close'])
        if bar_high > state.trade_high:
            state.trade_high = bar_high
        if bar_low < state.trade_low:
            state.trade_low = bar_low

        # ====================================================================
        # v1.5.7 CANONICAL PER-BAR ORDERING:
        #   1) SL/TP resolution
        #   2) Partial exit
        #   3) Stop mutation
        #   4) check_exit
        # ====================================================================

        # --- (1) SL / TP RESOLUTION ---
        position_state = {
            'direction':  state.direction,
            'stop_price': state.stop_price_active if state.stop_price_active is not None
                          else state.entry_market_state.get('initial_stop_price'),
            'tp_price':   state.entry_market_state.get('tp_price'),
        }
        exit_triggered, exit_price, exit_source = resolve_exit(row, position_state)

        # --- (2) PARTIAL EXIT (only if SL/TP did NOT fire this bar) ---
        if (not exit_triggered) and config.has_partial_hook and (not state.partial_taken):
            bars_held_now = i - state.entry_index
            ur = _unrealized_r  # already computed for ctx
            guards_pass = (
                bars_held_now >= _PARTIAL_MIN_BARS_HELD
                and ur is not None
                and ur >= _PARTIAL_MIN_UNREALIZED_R
            )
            if guards_pass:
                partial_sig = strategy.check_partial_exit(ctx)
                if partial_sig is not None:
                    _frac_raw = partial_sig.get('fraction')
                    try:
                        frac = float(_frac_raw)
                    except (TypeError, ValueError):
                        raise RuntimeError(
                            f"check_partial_exit() returned non-numeric fraction={_frac_raw!r}. "
                            "Contract requires fraction in [0.01, 0.99]."
                        )
                    if not (_PARTIAL_FRACTION_MIN <= frac <= _PARTIAL_FRACTION_MAX):
                        raise RuntimeError(
                            f"check_partial_exit() returned fraction={frac} outside "
                            f"[{_PARTIAL_FRACTION_MIN}, {_PARTIAL_FRACTION_MAX}]. "
                            "Return None to skip."
                        )
                    state.partial_leg = {
                        'exit_index':     i,
                        'exit_price':     row['close'],
                        'exit_timestamp': row.get('timestamp', row.get('time', df.index[i])),
                        'fraction':       frac,
                        'reason':         str(partial_sig.get('reason', 'partial')),
                        'bars_held':      bars_held_now,
                        'trade_high':     state.trade_high,
                        'trade_low':      state.trade_low,
                        'unrealized_r':   ur,
                    }
                    state.partial_taken = True

        # --- (3) STOP MUTATION (monotone; applies from next bar) ---
        if (not exit_triggered) and config.has_stop_mut_hook:
            new_sl = strategy.check_stop_mutation(ctx)
            if new_sl is not None:
                try:
                    new_sl_f = float(new_sl)
                except (TypeError, ValueError):
                    new_sl_f = None
                if new_sl_f is not None:
                    current_sl = state.stop_price_active if state.stop_price_active is not None \
                        else state.entry_market_state.get('initial_stop_price')
                    monotone_ok = (
                        (state.direction == 1  and new_sl_f > current_sl) or
                        (state.direction == -1 and new_sl_f < current_sl)
                    )
                    if monotone_ok:
                        state.stop_price_active = new_sl_f
                    else:
                        state.stop_mutation_rejected_count += 1

        # --- (4) check_exit (time / signal) ---
        # Contract v1.3 (additive, backward-compatible):
        #   False         → keep position
        #   True          → exit; strategy_exit_label = None (legacy)
        #   "<LABEL>"     → exit; strategy_exit_label = normalized label
        # Engine internal `exit_source` vocabulary unchanged
        # (STOP/TP/TIME_EXIT/SIGNAL_EXIT/DATA_END) for backward compat with
        # tests + verify_engine_integrity. The namespaced CSV column
        # `exit_source` is derived in the Stage-1 emitter from the pair
        # (engine exit_source, strategy_exit_label).
        strategy_exit_label = None
        if not exit_triggered:
            exit_result = strategy.check_exit(ctx)
            if not isinstance(exit_result, (bool, str)):
                raise RuntimeError(
                    f"check_exit() must return bool or str, got {type(exit_result).__name__}. "
                    "Contract v1.3 accepts: False | True | '<LABEL>'."
                )
            if exit_result:
                exit_triggered = True
                exit_price = row['close']
                is_time_exit = (
                    bool(row.get('is_exit_time', False)) or
                    bool(row.get('is_penultimate_bar', False))
                )
                exit_source = 'TIME_EXIT' if is_time_exit else 'SIGNAL_EXIT'
                if isinstance(exit_result, str):
                    # Deterministic normalization (strip + uppercase). Prefix
                    # is enforced downstream in the emitter so the engine
                    # stays vocabulary-neutral.
                    strategy_exit_label = exit_result.strip().upper() or None

        if exit_triggered:
            trade = {
                "entry_index":        state.entry_index,
                "exit_index":         i,
                "entry_price":        state.entry_price,
                "exit_price":         exit_price,
                "direction":          state.direction,
                "bars_held":          i - state.entry_index,
                "entry_timestamp":    df.iloc[state.entry_index].get(
                                         'timestamp',
                                         df.iloc[state.entry_index].get('time', None)
                                     ),
                "exit_timestamp":     row.get('timestamp', row.get('time', None)),
                "trade_high":         state.trade_high,
                "trade_low":          state.trade_low,
                "volatility_regime":  state.entry_market_state['volatility_regime'],
                "trend_score":        state.entry_market_state['trend_score'],
                "trend_regime":       state.entry_market_state['trend_regime'],
                "trend_label":        state.entry_market_state['trend_label'],
                "atr_entry":          state.entry_market_state['atr_entry'],
                "initial_stop_price": state.entry_market_state['initial_stop_price'],
                "risk_distance":      state.entry_market_state['risk_distance'],
                "exit_source":        exit_source,
                "strategy_exit_label": strategy_exit_label,
                "stop_source":        state.entry_market_state['stop_source'],
                "entry_reference_price": state.entry_market_state.get('entry_reference_price'),
                "entry_slippage":        state.entry_market_state.get('entry_slippage'),
                "entry_reason":          state.entry_market_state.get('entry_reason'),
                "signal_bar_idx":        state.entry_market_state.get('signal_bar_idx'),
                "fill_bar_idx":          state.entry_market_state.get('fill_bar_idx'),
                "regime_age_signal":     state.entry_market_state.get('regime_age_signal'),
                "regime_age_fill":       state.entry_market_state.get('regime_age_fill'),
                "market_regime_signal":  state.entry_market_state.get('market_regime_signal'),
                "market_regime_fill":    state.entry_market_state.get('market_regime_fill'),
                "regime_id_signal":      state.entry_market_state.get('regime_id_signal'),
                "regime_id_fill":        state.entry_market_state.get('regime_id_fill'),
                "regime_age_exec_signal": state.entry_market_state.get('regime_age_exec_signal'),
                "regime_age_exec_fill":   state.entry_market_state.get('regime_age_exec_fill'),
            }
            # v1.5.7 additions — only populated when a partial fired on this
            # trade. When absent the dict shape matches v1.5.6 exactly, so
            # no-hook strategies emit byte-identical output downstream.
            if state.partial_leg is not None:
                trade["partial_leg"] = state.partial_leg
                trade["partial_of_parent"] = True
            if state.stop_mutation_rejected_count > 0:
                trade["stop_mutation_rejected"] = state.stop_mutation_rejected_count

            state.session_trade_count += 1

            # Reset position + v1.5.7 state
            state.in_pos      = False
            state.direction   = 0
            state.entry_index = 0
            state.entry_price = 0.0
            state.trade_high  = 0.0
            state.trade_low   = float('inf')
            state.entry_market_state = {}
            state.partial_taken = False
            state.partial_leg = None
            state.stop_price_active = None
            state.stop_mutation_rejected_count = 0

            return trade

        # In position, no exit this bar
        return None


# =============================================================================
# finalize_force_close — lifted verbatim from v1.5.8 lines 646-694.
# Handles open position at end of data (research-only; live never hits this).
# =============================================================================

def finalize_force_close(df: pd.DataFrame, state: BarState, trades: list[dict[str, Any]]) -> None:
    """Force-close an open position at end of data.

    Appends a final trade with exit_source='DATA_END' to `trades` if state.in_pos.
    Lifted verbatim (state-threaded) from v1.5.8 execution_loop.py lines 646-694.
    """
    if state.in_pos and len(df) > 0:
        last_row = df.iloc[-1]
        last_i = len(df) - 1
        trade = {
            "entry_index":        state.entry_index,
            "exit_index":         last_i,
            "entry_price":        state.entry_price,
            "exit_price":         last_row['close'],
            "direction":          state.direction,
            "bars_held":          last_i - state.entry_index,
            "entry_timestamp":    df.iloc[state.entry_index].get(
                                      'timestamp',
                                      df.iloc[state.entry_index].get('time', None)
                                  ),
            "exit_timestamp":     last_row.get('timestamp', last_row.get('time', None)),
            "trade_high":         state.trade_high,
            "trade_low":          state.trade_low,
            "volatility_regime":  state.entry_market_state.get('volatility_regime'),
            "trend_score":        state.entry_market_state.get('trend_score'),
            "trend_regime":       state.entry_market_state.get('trend_regime'),
            "trend_label":        state.entry_market_state.get('trend_label'),
            "atr_entry":          state.entry_market_state.get('atr_entry'),
            "initial_stop_price": state.entry_market_state.get('initial_stop_price'),
            "risk_distance":      state.entry_market_state.get('risk_distance'),
            "exit_source":        'DATA_END',
            "strategy_exit_label": None,
            "stop_source":        state.entry_market_state.get('stop_source'),
            "entry_reference_price": state.entry_market_state.get('entry_reference_price'),
            "entry_slippage":        state.entry_market_state.get('entry_slippage'),
            "entry_reason":          state.entry_market_state.get('entry_reason'),
            "signal_bar_idx":        state.entry_market_state.get('signal_bar_idx'),
            "fill_bar_idx":          state.entry_market_state.get('fill_bar_idx'),
            "regime_age_signal":     state.entry_market_state.get('regime_age_signal'),
            "regime_age_fill":       state.entry_market_state.get('regime_age_fill'),
            "market_regime_signal":  state.entry_market_state.get('market_regime_signal'),
            "market_regime_fill":    state.entry_market_state.get('market_regime_fill'),
            "regime_id_signal":      state.entry_market_state.get('regime_id_signal'),
            "regime_id_fill":        state.entry_market_state.get('regime_id_fill'),
            "regime_age_exec_signal": state.entry_market_state.get('regime_age_exec_signal'),
            "regime_age_exec_fill":   state.entry_market_state.get('regime_age_exec_fill'),
        }
        if state.partial_leg is not None:
            trade["partial_leg"] = state.partial_leg
            trade["partial_of_parent"] = True
        if state.stop_mutation_rejected_count > 0:
            trade["stop_mutation_rejected"] = state.stop_mutation_rejected_count
        trades.append(trade)
