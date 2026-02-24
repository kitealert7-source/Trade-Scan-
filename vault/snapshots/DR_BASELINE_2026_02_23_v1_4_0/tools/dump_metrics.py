
import pandas as pd
from pathlib import Path

file_path = Path("backtests/Strategy_Master_Filter.xlsx")
if file_path.exists():
    df = pd.read_excel(file_path)
    # Filter for our strategy
    subset = df[df['strategy'].astype(str).str.contains("Range_Breakout")]
    
    if not subset.empty:
        cols = ['symbol', 'total_net_profit', 'total_trades', 'profit_factor', 'max_drawdown', 'sharpe_ratio']
        # Check if columns exist
        cols = [c for c in cols if c in df.columns]
        
        print(subset[cols].to_string(index=False))
        
        # Total PnL
        if 'total_net_profit' in subset.columns:
            total_pnl = subset['total_net_profit'].sum()
            print(f"\nTotal Portfolio PnL: {total_pnl:.2f}")
    else:
        print("No rows found for Range_Breakout")
else:
    print("Master Filter not found")
