
import pandas as pd
import numpy as np
from indicators.structure.range_breakout_session import session_range_structure

class Strategy:
    """
    Range_Breakout Strategy (Final v3)
    
    Modeling Assumptions/Logic:
    - Bar-resolution breakout model.
    - Event-Based: Signals on transition from No-Break (0) to Break (1/-1).
    - Daily Cap: Maximum 2 trades per day (regardless of direction).
    - Exits: Precise 18:00 UTC time exit; Bar-based SL.
    """
    name = "Range_Breakout"
    instrument_class = "FOREX"
    timeframe = "5m"

    def __init__(self):
        # State tracking
        self.last_trade_date = None
        self.daily_trade_count = 0
        self.prev_break_direction = 0

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Ensure index is DatetimeIndex for the indicator
        if 'timestamp' in df.columns:
            df = df.set_index('timestamp', drop=False)
            
        # Compute Session Structure (03:00 - 06:00 UTC)
        structure = session_range_structure(df, session_start="03:00", session_end="06:00")
        
        # Join structure columns to main df
        df = df.join(structure)
        
        return df

    def check_entry(self, ctx) -> dict:
        row = ctx['row']
        
        # Robust Timestamp Retrieval
        timestamp = row.get('timestamp')
        if not timestamp:
            timestamp = ctx.get('index')  # Fallback
            
        if not timestamp:
            return None
            
        # Convert index to date object
        if hasattr(timestamp, 'date'):
            current_date = timestamp.date()
        else:
            current_date = pd.to_datetime(timestamp).date()
        
        # Reset state at start of new day
        if self.last_trade_date != current_date:
            self.last_trade_date = current_date
            self.daily_trade_count = 0
            self.prev_break_direction = 0
            
        current_break_direction = row.get('break_direction', 0)
        signal = None
        
        # Event Logic: Trigger on 0 -> +/-1 transition
        if self.prev_break_direction == 0 and current_break_direction != 0:
            
            # Check Daily Cap: Allow only if count < 2
            if self.daily_trade_count < 2:
                if current_break_direction == 1: # Long Event
                     self.daily_trade_count += 1
                     signal = {"signal": 1, "comment": "Breakout_Long"}
                     
                elif current_break_direction == -1: # Short Event
                     self.daily_trade_count += 1
                     signal = {"signal": -1, "comment": "Breakout_Short"}
        
        # Update State
        self.prev_break_direction = current_break_direction
            
        return signal

    def check_exit(self, ctx) -> dict:
        row = ctx['row']
        bars_held = ctx['bars_held']
        direction = ctx['direction'] # 1 or -1
        
        # Robust Timestamp Retrieval
        timestamp = row.get('timestamp')
        if not timestamp:
            timestamp = ctx.get('index')
            
        # 1. Precise Time-Based Exit (18:00 UTC)
        if timestamp:
            ts = pd.to_datetime(timestamp)
            if ts.hour == 18 and ts.minute == 0:
                return {"signal": 1, "comment": "Time_Exit_1800"}
            
        # 2. Stop Loss (Opposite side of range)
        session_high = row.get('session_high')
        session_low = row.get('session_low')
        
        # Sanity check
        if pd.isna(session_high) or pd.isna(session_low):
            return None
            
        current_high = row['high']
        current_low = row['low']
        
        if direction == 1: # Long
            # SL at Session Low
            if current_low < session_low:
                return {"signal": 1, "comment": "SL_Session_Low"}
                
        elif direction == -1: # Short
            # SL at Session High
            if current_high > session_high:
                return {"signal": 1, "comment": "SL_Session_High"}

        return None
