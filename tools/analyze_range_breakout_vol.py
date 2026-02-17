import pandas as pd
from pathlib import Path

# Path to master filter
master_path = Path("backtests/Strategy_Master_Filter.xlsx")

if not master_path.exists():
    print("Master Filter not found.")
    exit(1)

try:
    df = pd.read_excel(master_path)
    
    # Filter for Range_Breakout01
    df_rb = df[df['strategy'].astype(str).str.contains("Range_Breakout02", na=False)]
    
    if df_rb.empty:
        print("No Range_Breakout02 runs found.")
        exit(0)
        
    print(f"Found {len(df_rb)} runs for Range_Breakout01")
    print("-" * 60)
    print(f"{'Symbol':<10} | {'Low Vol':>12} | {'Normal Vol':>12} | {'High Vol':>12} | {'Total Net':>12}")
    print("-" * 60)
    
    total_low = 0
    total_normal = 0
    total_high = 0
    total_net = 0
    
    for _, row in df_rb.iterrows():
        sym = str(row['symbol'])
        low = float(row.get('net_profit_low_vol', 0))
        norm = float(row.get('net_profit_normal_vol', 0))
        high = float(row.get('net_profit_high_vol', 0))
        net = float(row.get('total_net_profit', 0))
        
        total_low += low
        total_normal += norm
        total_high += high
        total_net += net
        
        print(f"{sym:<10} | {low:>12.2f} | {norm:>12.2f} | {high:>12.2f} | {net:>12.2f}")
        
    print("-" * 60)
    print(f"{'TOTAL':<10} | {total_low:>12.2f} | {total_normal:>12.2f} | {total_high:>12.2f} | {total_net:>12.2f}")
    print("-" * 60)
    
except Exception as e:
    print(f"Error analyzing Master Filter: {e}")
