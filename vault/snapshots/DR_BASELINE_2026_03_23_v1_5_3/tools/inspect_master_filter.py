
import pandas as pd
from pathlib import Path

file_path = Path("backtests/Strategy_Master_Filter.xlsx")
if file_path.exists():
    df = pd.read_excel(file_path)
    print("Columns:", df.columns.tolist())
    # Filter for Range_Breakout01
    subset = df[df['strategy'].astype(str).str.startswith("Range_Breakout01")]
    print(f"\nFound {len(subset)} rows for Range_Breakout01:")
    if not subset.empty:
        print(subset[['run_id', 'strategy', 'symbol', 'IN_PORTFOLIO']])
    else:
        print("No rows found starting with Range_Breakout01")
        
    print("\nTotal rows where IN_PORTFOLIO is True:", len(df[df['IN_PORTFOLIO'] == True]))
else:
    print("Strategy_Master_Filter.xlsx not found")
