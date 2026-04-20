
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
        _cols = [c for c in ['run_id', 'strategy', 'symbol', 'Analysis_selection']
                 if c in subset.columns]
        print(subset[_cols])
    else:
        print("No rows found starting with Range_Breakout01")

    if 'Analysis_selection' in df.columns:
        print("\nTotal rows with Analysis_selection = 1:",
              int((df['Analysis_selection'] == 1).sum()))
else:
    print("Strategy_Master_Filter.xlsx not found")
