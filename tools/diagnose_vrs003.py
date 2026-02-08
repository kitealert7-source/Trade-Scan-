
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def load_data():
    data_root = PROJECT_ROOT.parent / "Anti_Gravity_DATA_ROOT" / "MASTER_DATA" / "XAUUSD_OCTAFX_MASTER" / "CLEAN"
    files = sorted(data_root.glob("XAUUSD_OCTAFX_4h_*_CLEAN.csv"))
    if not files:
        print(f"No files found in {data_root}")
        return None
    
    dfs = [pd.read_csv(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    if 'time' in df.columns:
        df['timestamp'] = df['time']
    # Deduplicate
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
    # Filter 2020-2025
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[(df['timestamp'] >= '2020-01-01') & (df['timestamp'] <= '2025-12-31')].reset_index(drop=True)
    return df

def apply_indicators(df):
    # RSI(2)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=2).mean()
    rs = gain / loss
    df['rsi_2'] = 100 - (100 / (1 + rs))
    
    # RSI(2) Avg
    df['rsi_2_avg'] = df['rsi_2'].shift(1).rolling(window=2).mean()
    
    # EMA 200
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # Slope
    df['ema_slope_proxy'] = df['ema_200'].diff(20)
    
    return df

def diagnose(df):
    print(f"Total Bars: {len(df)}")
    
    # Short Conditions
    # 1. Price < EMA 200
    cond_price = df['close'] < df['ema_200']
    print(f"Price < EMA 200: {cond_price.sum()} bars")
    
    # 2. Slope < 0
    cond_slope = df['ema_slope_proxy'] < 0
    print(f"Slope < 0: {cond_slope.sum()} bars")
    
    # 3. RSI Avg >= 75
    cond_rsi = df['rsi_2_avg'] >= 75
    print(f"RSI Avg >= 75: {cond_rsi.sum()} bars")
    
    # Combined
    combined = cond_price & cond_slope & cond_rsi
    print(f"Combined SHORT Signal: {combined.sum()} bars")
    
    if combined.sum() > 0:
        print("\nExample Short setup bars:")
        print(df[combined][['timestamp', 'close', 'ema_200', 'ema_slope_proxy', 'rsi_2_avg']].head())
        
    print("-" * 30)
    
    # Long Conditions check (for comparison)
    # Price > EMA, Slope > 0, RSI <= 25
    comb_long = (df['close'] > df['ema_200']) & (df['ema_slope_proxy'] > 0) & (df['rsi_2_avg'] <= 25)
    print(f"Combined LONG Signal: {comb_long.sum()} bars")

if __name__ == "__main__":
    df = load_data()
    if df is not None:
        df = apply_indicators(df)
        diagnose(df)
