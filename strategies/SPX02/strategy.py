"""
SPX02 Strategy Plugin
Ported from spx01_logic.py per STRATEGY_PLUGIN_CONTRACT.md
"""
import pandas as pd
from indicators.price import rsi, stochastic_k, roc


class Strategy:
    """SPX02 Mean-Reversion Strategy for SPX500."""
    
    # --- Static Declarations ---
    name = "SPX02"
    instrument_class = "INDEX"
    timeframe = "D1"
    
    def __init__(self):
        self._df = None
    
    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute and attach all indicators."""
        df = df.copy()
        
        # Stochastic %K (14, 3)
        df['stoch_k'] = stochastic_k(
            df['high'], df['low'], df['close'],
            k_period=14, smooth_period=3
        )
        
        # ROC(5)
        df['roc_5'] = roc(df['close'], period=5)
        
        # RSI(2)
        df['rsi_2'] = rsi(df['close'], period=2)
        
        self._df = df
        return df
    
    def check_entry(self, ctx) -> bool:
        """
        Check Entry Conditions (UNION).
        Returns True if ANY condition is met.
        """
        i = ctx['index']
        
        # Need at least 3 prior bars for entry logic
        if i < 3:
            return False
        
        row = ctx['row']
        prev_row = self._df.iloc[i - 1]
        prev2_row = self._df.iloc[i - 2]
        prev3_row = self._df.iloc[i - 3]
        
        # 1. Three Consecutive Lower Closes
        cond1 = (row['close'] < prev_row['close']) and \
                (prev_row['close'] < prev2_row['close']) and \
                (prev2_row['close'] < prev3_row['close'])
        
        # 2. Stochastic Oversold Cross
        # %K < 20 AND %K(T-1) >= 20
        cond2 = (row['stoch_k'] < 20) and (prev_row['stoch_k'] >= 20)
        
        # 3. ROC Oversold Cross
        # ROC(5) < -1.0% AND ROC(5)(T-1) >= -1.0%
        cond3 = (row['roc_5'] < -1.0) and (prev_row['roc_5'] >= -1.0)
        
        # 4. RSI Deep Oversold
        # Average of RSI(T-1) and RSI(T-2) <= 25
        rsi_avg = (prev_row['rsi_2'] + prev2_row['rsi_2']) / 2
        cond4 = rsi_avg <= 25
        
        return cond1 or cond2 or cond3 or cond4
    
    def check_exit(self, ctx) -> bool:
        """
        Check Exit Conditions (STRICT PRECEDENCE).
        Returns True to exit the active position.
        """
        row = ctx['row']
        i = ctx['index']
        entry_index = ctx.get('entry_index', i)
        bars_held = i - entry_index
        
        # 1. PRIMARY: RSI(2) > 75
        if row['rsi_2'] > 75:
            return True
        
        # 2. FALLBACK: Bars held >= 4
        if bars_held >= 4:
            return True
        
        return False
