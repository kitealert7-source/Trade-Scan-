"""
FF001 Strategy Plugin
Linear Regression Mean-Reversion per STRATEGY_PLUGIN_CONTRACT.md
"""
import pandas as pd
import numpy as np


class Strategy:
    """FF001 LinReg Mean-Reversion Strategy for Forex."""
    
    # --- Static Declarations ---
    name = "FF001"
    instrument_class = "FOREX"
    timeframe = "15m"
    
    def __init__(self):
        self._df = None
    
    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute and attach all indicators."""
        df = df.copy()
        
        period = 20
        multiplier = 2.5
        
        # Linear Regression (20)
        def linreg(series, length):
            result = np.full(len(series), np.nan)
            for i in range(length - 1, len(series)):
                y = series.iloc[i - length + 1:i + 1].values
                x = np.arange(length)
                if len(y) == length and not np.isnan(y).any():
                    slope, intercept = np.polyfit(x, y, 1)
                    result[i] = intercept + slope * (length - 1)
            return pd.Series(result, index=series.index)
        
        df['linreg_20'] = linreg(df['close'], period)
        
        # Standard Deviation (20)
        df['stddev_20'] = df['close'].rolling(window=period).std()
        
        # Bands
        df['upper_band'] = df['linreg_20'] + multiplier * df['stddev_20']
        df['lower_band'] = df['linreg_20'] - multiplier * df['stddev_20']
        
        # ATR(14) - for stop reference only (not used in entry/exit logic)
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr_14'] = df['tr'].rolling(window=14).mean()
        
        self._df = df
        return df
    
    def check_entry(self, ctx) -> bool:
        """
        Check Entry Conditions.
        LONG: Close touches or crosses below lower band.
        SHORT: Close touches or crosses above upper band.
        """
        i = ctx['index']
        
        # Need indicator warmup
        if i < 20:
            return False
        
        row = ctx['row']
        
        # Skip if indicators are NaN
        if pd.isna(row['linreg_20']) or pd.isna(row['lower_band']) or pd.isna(row['upper_band']):
            return False
        
        close = row['close']
        lower = row['lower_band']
        upper = row['upper_band']
        
        # LONG: Close touches or crosses below lower band
        if close <= lower:
            return True
        
        # SHORT: Close touches or crosses above upper band
        if close >= upper:
            return True
        
        return False
    
    def check_exit(self, ctx) -> bool:
        """
        Check Exit Conditions.
        Exit when price touches/crosses LinReg midline.
        """
        row = ctx['row']
        
        if pd.isna(row['linreg_20']):
            return False
        
        close = row['close']
        midline = row['linreg_20']
        direction = ctx.get('direction', 0)
        
        # LONG exit: price touches/crosses midline from below
        if direction == 1 and close >= midline:
            return True
        
        # SHORT exit: price touches/crosses midline from above
        if direction == -1 and close <= midline:
            return True
        
        return False
