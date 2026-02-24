import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"

def check_symbol(symbol):
    print(f"\nScanning {symbol}...")
    # Find the folder
    # Pattern: Range_Breakout02_<SYMBOL>
    # or just search recursively
    found = False
    for folder in BACKTESTS_ROOT.glob(f"Range_Breakout02_{symbol}*"):
        csv_path = folder / "raw" / "results_tradelevel.csv"
        if csv_path.exists():
            found = True
            df = pd.read_csv(csv_path)
            
            print(f"Total Trades: {len(df)}")
            
            # Overall
            if 'direction' in df.columns:
                n_long = len(df[df['direction'] == 1])
                n_short = len(df[df['direction'] == -1])
            else:
                n_long = len(df[df['position_units'] > 0])
                n_short = len(df[df['position_units'] < 0])
                
            print(f"  Longs: {n_long}")
            print(f"  Shorts: {n_short}")
            
            # By Regime
            if 'volatility_regime' in df.columns:
                print("  By Regime:")
                for reg in df['volatility_regime'].unique():
                    subset = df[df['volatility_regime'] == reg]
                    if 'direction' in subset.columns:
                        l = len(subset[subset['direction'] == 1])
                        s = len(subset[subset['direction'] == -1])
                    else:
                        l = len(subset[subset['position_units'] > 0])
                        s = len(subset[subset['position_units'] < 0])
                    print(f"    {reg}: Longs={l}, Shorts={s}")
            else:
                 print("  [WARN] 'volatility_regime' column missing")
                 
    if not found:
        print(f"  [WARN] No backtest folder found for {symbol}")

def main():
    check_symbol("EURUSD")
    check_symbol("USDJPY")
    check_symbol("AUDUSD")

if __name__ == "__main__":
    main()
