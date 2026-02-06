"""
SPX01 Logic Module
Pure predicate logic for Universal Engine.
"""
import pandas as pd
from indicators.price import rsi, stochastic_k, roc

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Apply SPX01 indicators to the DataFrame."""
    df = df.copy()
    
    # 2. Stochastic %K (14, 3)
    df['stoch_k'] = stochastic_k(df['high'], df['low'], df['close'], k_period=14, smooth_period=3)
    
    # 3. ROC(5)
    df['roc_5'] = roc(df['close'], period=5)
    
    # 4. RSI(2)
    df['rsi_2'] = rsi(df['close'], period=2)
    
    return df

def check_entry(row, prev_row, prev2_row, prev3_row) -> bool:
    """
    Check Entry Conditions (UNION).
    Returns True if ANY condition is met.
    """
    # 1. Three Consecutive Lower Closes
    cond1 = (row['close'] < prev_row['close']) and \
            (prev_row['close'] < prev2_row['close']) and \
            (prev2_row['close'] < prev3_row['close'])
    
    # 2. Stochastic Oversold Cross
    # %K < 20 AND %K(T-1) >= 20
    cond2 = (row['stoch_k'] < 20) and (prev_row['stoch_k'] >= 20)
    
    # 3. ROC Oversold Cross
    # ROC(5) < -1.0% (-0.01) AND ROC(5)(T-1) >= -1.0% (Note: ROC fn returns pct eg -1.5, not decimal)
    # Our ROC implementation returns percentage (e.g., -1.5 for -1.5%).
    # Directive: "ROC(5) < -1.0%" -> implies value comparison.
    cond3 = (row['roc_5'] < -1.0) and (prev_row['roc_5'] >= -1.0)
    
    # 4. RSI Deep Oversold
    # Average of RSI(T-1) and RSI(T-2) <= 25
    rsi_avg = (prev_row['rsi_2'] + prev2_row['rsi_2']) / 2
    cond4 = rsi_avg <= 25
    
    return cond1 or cond2 or cond3 or cond4

def check_exit(row, bars_held) -> tuple[bool, str]:
    """
    Check Exit Conditions (STRICT PRECEDENCE).
    Returns (ShouldExit, Reason)
    """
    # 1. PRIMARY: RSI(2) > 75
    if row['rsi_2'] > 75:
        return True, "RSI_Exhaustion"
    
    # 2. FALLBACK: Bars held >= 4
    if bars_held >= 4:
        return True, "Timeout"
        
    return False, ""
