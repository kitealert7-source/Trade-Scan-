import pandas as pd
from pathlib import Path
import sys

def verify_batch_fix():
    print("=== BATCH VERIFICATION: TREND INTEGIRTY ===")
    root = Path("backtests")
    # Find all results_tradelevel.csv for Range_Breakout_02_AllVol_*
    files = list(root.glob("Range_Breakout_02_AllVol_*/raw/results_tradelevel.csv"))
    
    if not files:
        print("[FATAL] No result files found.")
        return

    summary_stats = []
    
    for f in files:
        symbol = f.parent.parent.name.split("_")[-1]
        try:
            df = pd.read_csv(f)
            ts = df['trend_score']
            
            non_zero = (ts != 0).sum()
            total = len(ts)
            unique_regimes = df['trend_regime'].nunique()
            min_score = ts.min()
            max_score = ts.max()
            
            summary_stats.append({
                "Symbol": symbol,
                "Trades": total,
                "NonZero%": round((non_zero/total)*100, 1) if total > 0 else 0,
                "Regimes": unique_regimes,
                "Min": min_score,
                "Max": max_score,
                "Status": "PASS" if (unique_regimes >= 3 and min_score < 0 < max_score) else "WARN"
            })
        except Exception as e:
             summary_stats.append({
                "Symbol": symbol,
                "Status": f"ERROR: {e}"
            })

    # Print Table
    df_res = pd.DataFrame(summary_stats)
    print(df_res.to_string())
    
    # Validation Logic
    if any(df_res['Status'] != "PASS"):
        print("\n[FAIL] Some symbols failed trend integrity check.")
    else:
        print("\n[SUCCESS] All symbols passed trend integrity.")

if __name__ == "__main__":
    verify_batch_fix()
