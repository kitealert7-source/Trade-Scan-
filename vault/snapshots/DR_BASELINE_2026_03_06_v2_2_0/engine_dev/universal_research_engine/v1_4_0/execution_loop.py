"""
Universal Research Engine v1.2.0 — Execution Loop
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.
"""


import pandas as pd
from types import SimpleNamespace
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime

ENGINE_ATR_MULTIPLIER = 2.0

class ContextView:
    """Lightweight adapter wrapping context namespace to unify .get() and attribute access.
    
    Protocol: All engine-standard methods (FilterStack, check_entry, check_exit)
    must receive a ContextView instance. Raw dicts and SimpleNamespace are rejected.
    """
    _ENGINE_PROTOCOL = True  # Protocol marker for enforcement
    
    def __init__(self, ns):
        self._ns = ns
        
    def get(self, key, default=None):
        try:
            val = getattr(self, key)
            if val is None:
                return default
            if pd.isna(val):
                return default
            return val
        except AttributeError:
            return default
            
    def require(self, key):
        val = self.get(key)
        if val is None:
            raise RuntimeError(f"AUTHORITATIVE_INDICATOR_MISSING: '{key}'")
        return val
        
    def __getattr__(self, name):
        if hasattr(self._ns, name):
            return getattr(self._ns, name)
        if hasattr(self._ns, 'row'):
            row_obj = getattr(self._ns, 'row')
            if hasattr(row_obj, 'get'):
                val = row_obj.get(name)
                if val is not None and not pd.isna(val):
                    return val
        raise AttributeError(f"'ContextView' object has no attribute '{name}'")

def run_execution_loop(df, strategy):
    """
    Fixed execution loop. Strategy-agnostic.
    
    Returns list of trade dicts with entry/exit details.
    Tracks trade_high (MAX of bar highs) and trade_low (MIN of bar lows)
    from entry_bar to exit_bar inclusive.
    """
    df = strategy.prepare_indicators(df)

    # --- ENSURE DATETIME INDEX ---
    # Required for HTF indicators that use daily resampling
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.index = pd.DatetimeIndex(df['timestamp'])
        elif 'time' in df.columns:
            df.index = pd.DatetimeIndex(df['time'])
    # --- INTRINSIC MARKET STATE COMPUTATION ---
    # Per SOP_TESTING v2.1 Section 7
    
    # 1. Compute Trend Components (Mandatory Engine-Owned Calculation)
    # Ref: ENGINE INTEGRATION FIX (Step 1513)
    
    # Ensure 'close' is used
    close_series = df['close']
    
    # A) Linear Regression Regime (Default window=50)
    # Output: DataFrame with ['regime']
    try:
        lr_df = linreg_regime(close_series)
        df['linreg_regime'] = lr_df['regime']
    except Exception as e:
        raise RuntimeError(f"Engine Trend Calc Failed (linreg_regime): {e}")

    # B) Linear Regression Regime HTF (Fixed window=200)
    try:
        lr_htf_df = linreg_regime_htf(close_series, window=200)
        df['linreg_regime_htf'] = lr_htf_df['regime']
    except Exception as e:
        raise RuntimeError(f"Engine Trend Calc Failed (linreg_regime_htf): {e}")

    # C) Kalman Regime
    # Expects DataFrame and column name
    try:
        kr_df = kalman_regime(df, price_col="close")
        df['kalman_regime'] = kr_df['regime']
    except Exception as e:
         raise RuntimeError(f"Engine Trend Calc Failed (kalman_regime): {e}")

    # D) Trend Persistence
    try:
        tp_out = trend_persistence(close_series)
        if isinstance(tp_out, pd.DataFrame):
            df['trend_persistence'] = tp_out['regime']
        else:
            df['trend_persistence'] = tp_out
    except Exception as e:
         raise RuntimeError(f"Engine Trend Calc Failed (trend_persistence): {e}")

    # E) Efficiency Ratio Regime
    try:
        er_out = efficiency_ratio_regime(close_series)
        if isinstance(er_out, pd.DataFrame):
            df['efficiency_ratio_regime'] = er_out['regime']
        else:
            df['efficiency_ratio_regime'] = er_out
    except Exception as e:
         raise RuntimeError(f"Engine Trend Calc Failed (efficiency_ratio_regime): {e}")

    # ------------------------------------------------------------------
    # STAGE 2.1: INTRINSIC MARKET STATE COMPUTATION
    # ------------------------------------------------------------------
    
    required_trend_components = [
        'linreg_regime', 
        'linreg_regime_htf', 
        'kalman_regime', 
        'trend_persistence', 
        'efficiency_ratio_regime'
    ]
    
    # Strict Validation
    missing = [c for c in required_trend_components if c not in df.columns]
    if missing:
        raise ValueError(f"CRITICAL: Missing trend components after calculation: {missing}")

    # Compute Trend Score
    df['trend_score'] = 0
    for col in required_trend_components:
        df['trend_score'] += df[col].fillna(0).astype(int)
            
    # Compute Trend Regime
    def get_trend_regime(score):
        if score >= 3: return 2
        if score >= 1: return 1
        if score == 0: return 0
        if score >= -2: return -1
        return -2
        
    df['trend_regime'] = df['trend_score'].apply(get_trend_regime)
    
    # Compute Trend Label
    def get_trend_label(regime):
        if regime == 2: return "strong_up"
        if regime == 1: return "weak_up"
        if regime == 0: return "neutral"
        if regime == -1: return "weak_down"
        return "strong_down"
        
    df['trend_label'] = df['trend_regime'].apply(get_trend_label)

    # ------------------------------------------------------------------

    # === AUTHORITATIVE INDICATOR GOVERNANCE ===
    # Step 1: Canonicalization
    if 'ATR' in df.columns:
        if 'atr' not in df.columns: df['atr'] = df['ATR']
        del df['ATR']
    if 'atr_entry' in df.columns:
        if 'atr' not in df.columns: df['atr'] = df['atr_entry']
        del df['atr_entry']
    if 'regime' in df.columns:
        if 'volatility_regime' not in df.columns: df['volatility_regime'] = df['regime']
        del df['regime']

    # Step 2: Unconditional Column Assertion
    AUTHORITATIVE_INDICATORS = ['volatility_regime', 'trend_regime', 'trend_label', 'trend_score', 'atr']
    for field in AUTHORITATIVE_INDICATORS:
        if field not in df.columns:
            raise RuntimeError(f"ABORT_GOVERNANCE: Missing authoritative indicator '{field}'")
    # ==========================================

    trades = []
    
    in_pos = False
    direction = 0      # 1 = LONG, -1 = SHORT, 0 = flat
    entry_index = 0
    entry_price = 0.0
    trade_high = 0.0   # MAX(high) during trade
    trade_low = float('inf')  # MIN(low) during trade
    entry_market_state = {} # Initialize to store market state at entry

    for i in range(len(df)):
        row = df.iloc[i]
        
        # Build context
        ctx_ns = SimpleNamespace(
            row=row,
            index=i,
            direction=direction,
            trend_regime=row.get("trend_regime"),
            volatility_regime=row.get("volatility_regime"),
            entry_index=entry_index if in_pos else None,
            bars_held=(i - entry_index) if in_pos else 0
        )
        ctx = ContextView(ctx_ns)

        if not in_pos:
            # --- ENTRY CHECK ---
            entry_signal = strategy.check_entry(ctx)
            if entry_signal:
                direction = entry_signal.get("signal", 1)
                
                # Phase 2: Engine-Level Directional Gating
                if hasattr(strategy, "filter_stack"):
                    if not strategy.filter_stack.allow_direction(direction):
                        direction = 0  # Revert back to flat
                        continue       # Blocked by directional filter
                        
                in_pos = True
                entry_index = i
                entry_price = row['close']
                
                # --- CAPTURE MARKET STATE (AT ENTRY) ---
                # "Capture and attach to trade dict... No recomputation later."
                
                # Volatility: Must use authoritative name from context
                vol_regime = ctx.require('volatility_regime')
                
                # Mapper for strict schema (int/float/numpy -> string)
                try:
                    # Attempt safe conversion to decide category
                    # This handles int, float, np.int64, np.float64, and string numbers
                    v_val = float(vol_regime)
                    if v_val >= 0.5: 
                        vol_regime = "high"
                    elif v_val <= -0.5: 
                        vol_regime = "low"
                    else: 
                        vol_regime = "normal"
                except (ValueError, TypeError):
                    # Already a string label (e.g. 'high')
                    pass
                
                # --- INITIAL STOP CAPTURE (STRATEGY OVERRIDE → ATR FALLBACK) ---
                stop_price = entry_signal.get("stop_price")

                if stop_price is None:
                    # Require canonical ATR
                    atr_value = ctx.require('atr')

                    if atr_value <= 0:
                        raise ValueError(
                            "STOP CONTRACT VIOLATION: No strategy stop provided and ATR invalid (<=0)."
                        )

                    if direction == 1:
                        stop_price = entry_price - (atr_value * ENGINE_ATR_MULTIPLIER)
                    elif direction == -1:
                        stop_price = entry_price + (atr_value * ENGINE_ATR_MULTIPLIER)
                    else:
                        raise ValueError("Invalid direction during stop capture")

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
                entry_market_state = {
                    "volatility_regime": vol_regime,
                    "trend_score": int(ctx.require('trend_score')),
                    "trend_regime": int(ctx.require('trend_regime')),
                    "trend_label": ctx.require('trend_label'),
                    "atr_entry": ctx.require('atr'),
                    "initial_stop_price": stop_price,
                    "risk_distance": risk_distance,
                }
                
                # Initialize trade extrema with entry bar
                trade_high = row.get('high', row['close'])
                trade_low = row.get('low', row['close'])
                
        else:
            # --- UPDATE TRADE EXTREMA ---
            bar_high = row.get('high', row['close'])
            bar_low = row.get('low', row['close'])
            if bar_high > trade_high:
                trade_high = bar_high
            if bar_low < trade_low:
                trade_low = bar_low
            
            # --- EXIT CHECK ---
            if strategy.check_exit(ctx):
                exit_price = row['close']
                
                trade = {
                    "entry_index": entry_index,
                    "exit_index": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "direction": direction,
                    "bars_held": i - entry_index,
                    "entry_timestamp": df.iloc[entry_index].get('timestamp', df.iloc[entry_index].get('time', None)),
                    "exit_timestamp": row.get('timestamp', row.get('time', None)),
                    "trade_high": trade_high,
                    "trade_low": trade_low,
                    
                    # Intrinsic Market State (Passthrough)
                    "volatility_regime": entry_market_state['volatility_regime'],
                    "trend_score": entry_market_state['trend_score'],
                    "trend_regime": entry_market_state['trend_regime'],
                    "trend_label": entry_market_state['trend_label'],
                    "atr_entry": entry_market_state['atr_entry'],
                    "initial_stop_price": entry_market_state['initial_stop_price'],
                    "risk_distance": entry_market_state['risk_distance'],
                }
                trades.append(trade)
                
                # Reset to flat
                in_pos = False
                direction = 0
                entry_index = 0
                entry_price = 0.0
                trade_high = 0.0
                trade_low = float('inf')
                entry_market_state = {}

    return trades
