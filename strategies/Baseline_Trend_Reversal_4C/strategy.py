"""
Baseline_Trend_Reversal_4C Strategy
Based on Forex.txt directive.
"""
import pandas as pd

class Strategy:
    """
    Forex Baseline Trend Reversal (GBPUSD).
    4 Consecutive Candles Reversal logic.
    """
    
    name = "Baseline_Trend_Reversal_4C"
    instrument_class = "FOREX"
    timeframe = "D1"
    
    def __init__(self):
        self._df = None
    
    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Attach candle color indicators."""
        df = df.copy()
        
        # Determine candle color
        # 1 = Green (Close > Open)
        # -1 = Red (Close < Open)
        # 0 = Doji (Close == Open)
        
        # Vectorized calculation
        close = df['close']
        open_ = df['open']
        
        df['color'] = 0
        df.loc[close > open_, 'color'] = 1
        df.loc[close < open_, 'color'] = -1
        
        self._df = df
        return df
    
    def check_entry(self, ctx) -> bool:
        """
        Entry Logic:
        Long: 4 consecutive RED candles -> Enter LONG.
        Short: 4 consecutive GREEN candles -> Enter SHORT.
        """
        i = ctx['index']
        if i < 4:
            return False
            
        df = self._df
        # Lookback 4 bars: i, i-1, i-2, i-3
        # Note: ctx['row'] is df.iloc[i]
        
        colors = df['color'].iloc[i-3 : i+1].values
        
        # Check Long Entry (4 Reds)
        if all(c == -1 for c in colors):
            ctx['direction'] = 1  # Long
            return True
            
        # Check Short Entry (4 Greens)
        if all(c == 1 for c in colors):
            ctx['direction'] = -1 # Short
            return True
            
        return False
    
    def check_exit(self, ctx) -> bool:
        """
        Exit Logic:
        1. Stop Loss (500 pips)
        2. Reversal Signal (4 Greens/Reds)
        """
        i = ctx['index']
        row = ctx['row']
        direction = ctx['direction']
        
        # Get entry price from history
        entry_index = ctx['entry_index']
        entry_price = self._df['close'].iloc[entry_index]
        
        # 1. Hard Stop (500 pips = 0.0500 for GBPUSD)
        STOP_DIST = 0.0500
        
        if direction == 1: # Long
            # Stop if Low <= Entry - 0.0500
            if row['low'] <= (entry_price - STOP_DIST):
                return True
                
            # Reversal: 4 Greens
            # Need to check history
            if i >= 4:
                colors = self._df['color'].iloc[i-3 : i+1].values
                if all(c == 1 for c in colors):
                    return True
                    
        elif direction == -1: # Short
            # Stop if High >= Entry + 0.0500
            if row['high'] >= (entry_price + STOP_DIST):
                return True
                
            # Reversal: 4 Reds
            if i >= 4:
                colors = self._df['color'].iloc[i-3 : i+1].values
                if all(c == -1 for c in colors):
                    return True
                    
        return False
