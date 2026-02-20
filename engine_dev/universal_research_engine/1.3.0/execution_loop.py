"""
Universal Research Engine v1.2.0 — Execution Loop
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.
"""


import pandas as pd
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime

def run_execution_loop(df, strategy):
    """
    Fixed execution loop. Strategy-agnostic.
    
    Returns list of trade dicts with entry/exit details.
    Tracks trade_high (MAX of bar highs) and trade_low (MIN of bar lows)
    from entry_bar to exit_bar inclusive.
    """
    df = strategy.prepare_indicators(df)
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
        ctx = {
            "row": row,
            "index": i,
            "direction": direction,
            # Pass market state to strategy context just in case, though they are in row
            "trend_regime": row['trend_regime'],
            "volatility_regime": row.get('volatility_regime'), # Default to normal if missing? No fallback allowed?
            # "No fallback-to-normal behavior references" -> I should handle missing strictly at CAPTURE.
            "entry_index": entry_index if in_pos else None,
            "bars_held": (i - entry_index) if in_pos else 0
        }

        if not in_pos:
            # --- ENTRY CHECK ---
            entry_signal = strategy.check_entry(ctx)
            if entry_signal:
                in_pos = True
                entry_index = i
                entry_price = row['close']
                direction = entry_signal.get("signal", 1)
                
                # --- CAPTURE MARKET STATE (AT ENTRY) ---
                # "Capture and attach to trade dict... No recomputation later."
                
                # Volatility: "volatility_regime MUST use existing volatility_regime indicator output."
                # "No fallback to 'normal'."
                # Support 'regime' alias as standard indicator output
                vol_regime = row.get('volatility_regime', row.get('regime'))
                
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
                    # Already a string label (e.g. 'high') or None
                    pass
                
                if vol_regime is None:
                    # Strict Fail? 
                    # "Raise ValueError on missing." is for the EMITTER. 
                    # Here we capture what we have. If missing, it will be None.
                    pass
                
                # --- INITIAL STOP CAPTURE (SESSION OPPOSITE RANGE) ---
                if direction == 1:
                    stop_price = strategy.session_low
                elif direction == -1:
                    stop_price = strategy.session_high
                else:
                    raise ValueError("Invalid direction during stop capture")

                risk_distance = abs(entry_price - stop_price)

                if risk_distance <= 0:
                    raise ValueError("Invalid risk distance (zero or negative)")

                entry_market_state = {
                    "volatility_regime": vol_regime,
                    "trend_score": int(row.get('trend_score', 0)),
                    "trend_regime": int(row.get('trend_regime', 0)),
                    "trend_label": row.get('trend_label', 'neutral'),
                    "atr_entry": row.get('atr', row.get('ATR', 0.0)), # Best effort
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
