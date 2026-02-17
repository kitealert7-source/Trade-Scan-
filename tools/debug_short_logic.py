import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from indicators.structure.range_breakout_session import session_range_structure
from strategies.Range_Breakout.strategy import Strategy

def run_test():
    print("TEST: Synthetic Short Logic")
    
    # 1. Create Synthetic Data (UTC)
    # Session: 03:00 - 06:00
    # 03:00 - 05:55: Range [1.1000, 1.2000]
    # 06:00: Break Down -> 1.0900
    
    dates = pd.date_range("2024-01-01 00:00", "2024-01-01 10:00", freq="5min", tz="UTC")
    df = pd.DataFrame(index=dates)
    df["open"] = 1.1500
    df["high"] = 1.1500
    df["low"] = 1.1500
    df["close"] = 1.1500
    
    # Set Session High/Low manually in data
    mask_session = (dates.time >= pd.to_datetime("03:00").time()) & (dates.time < pd.to_datetime("06:00").time())
    
    # Make session high 1.2000, low 1.1000
    # We'll toggle high/low on specific bars
    df.loc[dates[mask_session][0], "high"] = 1.2000
    df.loc[dates[mask_session][0], "low"] = 1.1000
    
    # BREAKDOWN EVENT at 06:05
    break_idx = pd.Timestamp("2024-01-01 06:05:00+00:00")
    df.loc[break_idx, "low"] = 1.0900 # Below 1.1000
    df.loc[break_idx, "close"] = 1.0900
    
    print("Running Indicator...")
    df_ind = session_range_structure(df)
    
    # Check Indicator Output
    row = df_ind.loc[break_idx]
    print(f"Time: {break_idx}")
    print(f"Session Low: {row['session_low']}")
    print(f"Low: {df.loc[break_idx, 'low']}")
    print(f"Break Direction: {row['break_direction']}")
    
    if row['break_direction'] == -1:
        print(">> INDICATOR PASS: Detected -1")
    else:
        print(f">> INDICATOR FAIL: Detected {row['break_direction']}")
        return

    # 2. Test Strategy Logic
    print("\nRunning Strategy Logic...")
    strat = Strategy()
    df_strat = strat.prepare_indicators(df.copy()) # Should be same
    
    # Simulate Context Loop
    triggered = False
    
    # We iterate from 05:50 to 06:15
    test_range = dates[(dates >= "2024-01-01 05:50:00+00:00") & (dates <= "2024-01-01 06:15:00+00:00")]
    
    for ts in test_range:
        row = df_strat.loc[ts]
        ctx = {
            'row': row,
            'index': ts 
        }
        
        sig = strat.check_entry(ctx)
        d = row['break_direction']
        p = strat.prev_break_direction
        
        print(f"Time: {ts.time()} | Dir: {d} | Prev: {p} | Signal: {sig}")
        
        if sig and sig['signal'] == -1:
            triggered = True
            print(">> STRATEGY PASS: Triggered Short (-1)")
            break
            
    if not triggered:
        print(">> STRATEGY FAIL: No Short Triggered")

if __name__ == "__main__":
    run_test()
