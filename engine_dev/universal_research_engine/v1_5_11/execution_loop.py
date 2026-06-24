# =============================================================================
# Engine v1.5.11 — EXPERIMENTAL (Patch A: structural core, byte-identical to v1.5.10; successor to v1.5.10)
#
# v1.5.10 over v1.5.8 — RESTORATION of the OctaFx addendum line-17 intent
#   (ASK-for-BUY / BID-for-SELL), NOT a new cost model. SELL fills execute at the
#   bid (= ask - per-bar embedded spread from the RESEARCH `spread` column); BUY
#   fills at the ask. The P&L formula (exit-entry)*dir*units is UNCHANGED — only
#   the fill price fed into it becomes side-correct. SELL-side fills = {short
#   entry} + {long exit: SL/TP/partial/signal/forced}. With spread=0 (all
#   RESEARCH until the embed regen) this is BYTE-IDENTICAL to v1.5.8.
#
# Engine v1.5.8 — EXPERIMENTAL
# Successor to FROZEN v1.5.7. Do not promote to FROZEN without burn-in evidence
# and explicit go-live review.
#
# Changes over v1.5.7:
#   (F) ctx.unrealized_r_intrabar — intrabar-aware R multiple for BE/stop logic.
#       long:  (bar_high - entry_price) / risk_distance_initial
#       short: (entry_price - bar_low)  / risk_distance_initial
#       Exposed alongside existing close-based ctx.unrealized_r (unchanged).
#       Strategies using check_stop_mutation for BE should compare this field
#       against the threshold instead of ctx.unrealized_r so the BE trigger
#       aligns with the SL/TP resolver which also uses intrabar high/low.
#
# All v1.5.7 invariants preserved. No-hook strategies produce byte-equivalent
# output to v1.5.7 (and therefore v1.5.6).
# =============================================================================
"""
Universal Research Engine v1.5.11 — Execution Loop (EXPERIMENTAL)
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.

Hook contract (inherited from v1.5.7, unchanged):

  check_partial_exit(ctx) -> dict | None
  check_stop_mutation(ctx) -> float | None

New ctx field (v1.5.8):

  ctx.unrealized_r_intrabar : float | None
      Intrabar R-multiple using bar_high (longs) or bar_low (shorts).
      Denominator: initial risk distance (frozen at entry, same as unrealized_r).
      long:  (bar_high - entry_price) / (entry_price - stop_price_initial)
      short: (entry_price - bar_low)  / (stop_price_initial - entry_price)
      None when flat (not in position). This field aligns with the SL/TP
      resolver which also uses OHLC; use it in check_stop_mutation for BE
      logic so the trigger fires whenever the bar actually reached 1R+
      intrabar, not just at the close.

Canonical per-bar ordering (in-position branch, unchanged):
  1) SL/TP resolution via resolve_exit()      — intrabar, highest priority
  2) Partial exit (if hook + guards pass)     — bar close, realized event
  3) Stop mutation (if hook returns value)    — applies from NEXT bar
  4) check_exit (time / signal)               — bar close, lowest priority

unrealized_r (ctx field, close-based, UNCHANGED from v1.5.7):
  long:  (close - entry_price) / (entry_price - stop_price_initial)
  short: (entry_price - close) / (stop_price_initial - entry_price)
"""

from __future__ import annotations

import pandas as pd
from types import SimpleNamespace
from typing import Any

from engines.protocols import ContextViewProtocol, StrategyProtocol
from engines.regime_state_machine import apply_regime_model
# C2: the single shared pending-fill builder (one body for single-asset + basket;
# the seam Patch B's invalid_fill_policy=SKIP hooks). Absolute import — main.py loads
# this module standalone via spec_from_file_location, so a relative import would fail;
# engine_dev is on sys.path (main.py inserts PROJECT_ROOT).
from engine_dev.universal_research_engine.v1_5_11.evaluate_bar import build_position_from_pending

__all__ = [
    "ContextView",
    "resolve_exit",
    "run_execution_loop",
    "ENGINE_VERSION",
    "ENGINE_STATUS",
]

ENGINE_ATR_MULTIPLIER = 2.0
ENGINE_VERSION    = "1.5.11"
ENGINE_STATUS     = "EXPERIMENTAL"
ENGINE_FREEZE_DATE = None  # EXPERIMENTAL engines do not have a freeze date (set at promotion, Patch A step 7).

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


def _bar_spread(row: pd.Series) -> float:
    """Per-bar embedded spread (PRICE units) carried in the RESEARCH `spread`
    column. Returns 0.0 when absent / NaN / <=0 — so on spread=0 data the
    direction-aware fills are a no-op and output is byte-identical to v1.5.8."""
    s = row.get('spread', 0.0)
    if s is None or pd.isna(s):
        return 0.0
    s = float(s)
    return s if s > 0.0 else 0.0


def _exec_fill(raw_ask_price: float, is_sell: bool, bar_spread: float) -> float:
    """Direction-aware execution price (v1.5.10). RESEARCH OHLC are ASK-based:
    a BUY fills at the ask (raw price, unchanged); a SELL fills at the bid
    (= ask - embedded spread). Restores the OctaFx addendum's ASK-for-BUY /
    BID-for-SELL intent. The P&L formula is unchanged — only the price fed in
    becomes side-correct."""
    return (raw_ask_price - bar_spread) if is_sell else raw_ask_price


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


def run_execution_loop(df: pd.DataFrame, strategy: StrategyProtocol,
                       health: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """
    v1.5.7 execution loop. Strategy-agnostic.

    Entry model:   signal on bar N -> fill at bar N+1 open  (next_bar_open)
    Exit model:    SL/TP intrabar; partial/stop-mutation/check_exit at bar close.
    Session guard: max 1 trade per UTC calendar day (unchanged from v1.5.6).

    Returns list of trade dicts. When a partial exit fired during a trade, the
    trade dict contains a `partial_leg` sub-dict with the partial close details
    AND `partial_of_parent = True`. Otherwise both fields are absent / False.

    v1.5.11 Patch A: `health` is an optional mutable dict of run-level engine
    counters. When None (the default — every byte-identical caller) nothing is
    counted and behaviour is unchanged; when supplied, run-level events are
    tallied into it in place. Observational ONLY — it never alters a trade.
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

    # v1.5.11 Patch A: initialise the run-level health counters when opted in.
    # Guarded so the default (health is None) path is byte-identical.
    if health is not None:
        for _hk in ('rejected_entries', 'stop_mutation_rejected',
                    'pending_entries_expired', 'force_close_count',
                    'negative_spread_bars', 'nan_bar_count'):
            health.setdefault(_hk, 0)

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
                if health is not None and pending_entry is not None:
                    health['pending_entries_expired'] += 1
                pending_entry = None

        # Build context (v1.5.8 adds unrealized_r_intrabar alongside close-based unrealized_r)
        _unrealized_r: float | None = None
        _unrealized_r_intrabar: float | None = None
        if in_pos:
            _initial_stop = entry_market_state.get('initial_stop_price', entry_price)
            _unrealized_r = _compute_unrealized_r(
                direction,
                row['close'],
                entry_price,
                _initial_stop,
            )
            _unrealized_r_intrabar = _compute_unrealized_r_intrabar(
                direction,
                row.get('high', row['close']),
                row.get('low',  row['close']),
                entry_price,
                _initial_stop,
            )

        ctx_ns = SimpleNamespace(
            row=row,
            index=i,
            direction=direction,
            trend_regime=row.get("trend_regime"),
            volatility_regime=row.get("volatility_regime"),
            entry_index=entry_index if in_pos else None,
            entry_price=entry_price if in_pos else None,
            bars_held=(i - entry_index) if in_pos else 0,
            unrealized_r=_unrealized_r,
            unrealized_r_intrabar=_unrealized_r_intrabar,
        )
        ctx = ContextView(ctx_ns)

        if not in_pos:
            # EXECUTE PENDING ENTRY at bar N+1 open
            if pending_entry is not None:
                pe = pending_entry
                pending_entry = None
                # C2: shared pending-fill builder (byte-identical to the inline
                # v1.5.10 computation; the seam Patch B's invalid_fill_policy=SKIP
                # hooks). None => direction filtered out: fall through to a new signal.
                pos = build_position_from_pending(pe, sl_atr_mult, tp_atr_mult,
                                                  strategy, row, i)
                if pos is not None:
                    direction                    = pos.direction
                    in_pos                       = True
                    entry_index                  = i
                    entry_price                  = pos.entry_price
                    reference_entry_price        = pos.reference_entry_price
                    entry_reason                 = pos.entry_reason
                    trade_entry_slippage         = pos.entry_slippage
                    stop_price                   = pos.stop_price
                    stop_source                  = pos.stop_source
                    risk_distance                = pos.risk_distance
                    tp_price                     = pos.tp_price
                    entry_market_state           = pos.entry_market_state
                    trade_high                   = pos.trade_high
                    trade_low                    = pos.trade_low
                    # v1.5.7: reset per-trade partial / mutation state
                    partial_taken                = False
                    partial_leg                  = None
                    stop_price_active            = stop_price
                    stop_mutation_rejected_count = 0
                    continue
                # pos is None => direction filtered out by allow_direction; the
                # pending entry is discarded and we fall through to a fresh
                # signal. Count the engine-level rejection (observational only).
                if health is not None:
                    health['rejected_entries'] += 1

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
            if exit_triggered:
                # v1.5.10: SL/TP fill is side-correct. Long exit=SELL (bid);
                # short exit=BUY (ask). resolve_exit() stays pure (level logic).
                exit_price = _exec_fill(
                    exit_price, is_sell=(direction == 1), bar_spread=_bar_spread(row)
                )

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
                        partial_leg = {
                            'exit_index':     i,
                            # v1.5.10: long partial exit=SELL (bid); short=BUY (ask).
                            'exit_price':     _exec_fill(
                                row['close'], is_sell=(direction == 1),
                                bar_spread=_bar_spread(row)),
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
                            if health is not None:
                                health['stop_mutation_rejected'] += 1

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
                    # v1.5.10: long signal/time exit=SELL (bid); short=BUY (ask).
                    exit_price = _exec_fill(
                        row['close'], is_sell=(direction == 1),
                        bar_spread=_bar_spread(row))
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
                    "strategy_exit_label": strategy_exit_label,
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
        if health is not None:
            health['force_close_count'] += 1
        last_row = df.iloc[-1]
        last_i = len(df) - 1
        trade = {
            "entry_index":        entry_index,
            "exit_index":         last_i,
            "entry_price":        entry_price,
            # v1.5.10: long forced-close=SELL (bid); short=BUY (ask).
            "exit_price":         _exec_fill(
                                      last_row['close'], is_sell=(direction == 1),
                                      bar_spread=_bar_spread(last_row)),
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
            "strategy_exit_label": None,
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

    # v1.5.11 Patch A: cheap vectorized data-quality probes (count-only; does
    # NOT open the H2/ContextView NaN audit). Computed once at run end so the
    # per-bar hot path stays byte-identical. nan_bar_count = bars whose consumed
    # price (`close`) is NaN (a genuine data gap, distinct from benign indicator
    # warm-up NaN); negative_spread_bars = bars whose raw `spread` is finite and
    # < 0 (the values _bar_spread clamps to 0).
    if health is not None:
        try:
            if 'close' in df.columns:
                health['nan_bar_count'] = int(df['close'].isna().sum())
            if 'spread' in df.columns:
                _sp = pd.to_numeric(df['spread'], errors='coerce')
                health['negative_spread_bars'] = int((_sp < 0).sum())
        except Exception:
            pass  # observational only — a probe hiccup must never abort a run

    return trades
