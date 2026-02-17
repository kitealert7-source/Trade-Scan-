print("BOOT")
import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

# Reuse load_market_data from run_stage1 or re-implement simply
# I'll implement a simple loader for speed
def load_eurusd_sample():
    # Attempt to locate the file
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / "EURUSD_OCTAFX_MASTER" / "RESEARCH"
    print(f"DEBUG: Project Root: {PROJECT_ROOT}")
    print(f"DEBUG: Data Root: {data_root}")
    pattern = "EURUSD_OCTAFX_15m_2024_RESEARCH.csv"
    files = list(data_root.glob(pattern))
    
    if not files:
        files = sorted(data_root.glob("EURUSD_OCTAFX_15m_*_RESEARCH.csv"))
        
    if not files:
        print("Data file not found.")
        return None
        
    f = files[0]
    print(f"Loading {f}...")
    df = pd.read_csv(f, comment='#')
    df = pd.read_csv(f, comment='#')
    if 'time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['time'])
    else:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df

from indicators.structure.range_breakout_session import session_range_structure

def main():
    df = load_eurusd_sample()
    if df is None: return
    
    print(f"Data Loaded: {len(df)} rows (15m Native)")
    print(f"Columns: {df.columns}")
    
    # Run Indicator
    print("Running Indicator...")
    df_ind = session_range_structure(df)
    
    shorts = df_ind[df_ind['break_direction'] == -1]
    if not shorts.empty:
        print("\nFirst 5 Shorts:")
        print(shorts[['session_high', 'session_low', 'break_direction']].head())
    else:
        print("\nNO SHORTS DETECTED IN INDICATOR OUTPUT.")
        
    # --- STRATEGY TRACE ---
    print("\nRunning Strategy Trace for 2024-08-28...")
    from strategies.Range_Breakout.strategy import Strategy
    
    # Filter for that day
    day_mask = df.index.date == pd.to_datetime("2024-08-28").date()
    df_day = df[day_mask].copy()
    
    # Run Indicator again on subset (or splice from full)
    # Better to splice to ensure context
    df_day = df_ind.loc[df_day.index].copy() 
    # Need original columns too for check_exit/check_entry context if they used them
    # But check_entry only uses break_direction and timestamp
    # check_exit uses high/low/close
    
    # Merge indicator cols to original df slice
    df_strat_input = df.loc[df_day.index].join(df_day[['break_direction', 'session_high', 'session_low']])
    
    strat = Strategy()
    # Strategy expects 'timestamp' in column or index.
    # We have it in index.
    
    print("Iterating...")
    triggered = False
    for ts, row in df_strat_input.iterrows():
        # Artificial context
        ctx = {
            'row': row,
            'index': ts 
        }
        
        # Update row with timestamp for helper
        # Logic in strategy: timestamp = row.get('timestamp') ...
        # Our row is a Series from iterrows, it doesn't have 'timestamp' unless we add it
        row['timestamp'] = ts
        
        # Capture state before
        prev_dir = strat.prev_break_direction
        count = strat.daily_trade_count
        
        sig = strat.check_entry(ctx)
        
        curr_dir = row['break_direction']
        
        if ts.hour == 6 and ts.minute <= 30:
             print(f"{ts.time()} | Dir: {curr_dir} | Prev: {prev_dir} | Count: {count} | Signal: {sig}")
        
        if sig and sig['signal'] == -1:
            print(f"!!! TRIGGERED SHORT AT {ts} !!!")
            triggered = True
            
    if not triggered:
        print("FAIL: Strategy did not trigger short on known breakdown day.")

main()
