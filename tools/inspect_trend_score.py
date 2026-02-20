
import pandas as pd
from pathlib import Path

def inspect_trend_score():
    csv_path = Path("backtests/Range_Breakout_02_AllVol_USDJPY/raw/results_tradelevel.csv")
    if not csv_path.exists():
        print("CSV not found.")
        return

    try:
        df = pd.read_csv(csv_path)
        if "trend_score" not in df.columns:
            print("trend_score column missing!")
            return
            
        print("--- Trend Score Distribution ---")
        print(df["trend_score"].value_counts().sort_index())
        
        print("\n--- First 5 Rows ---")
        print(df[["entry_timestamp", "trend_score", "trend_label"]].head().to_string())

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_trend_score()
