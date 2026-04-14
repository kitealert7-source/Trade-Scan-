
"""
apply_portfolio_constraints.py — Post-Stage-1 Concurrency Enforcement
Usage: python tools/apply_portfolio_constraints.py <STRATEGY_ID> [MAX_CONCURRENT]

Purpose:
  Consumes raw Stage-1 trade lists (symbol-isolated), aggregates them,
  applies a portfolio-level concurrency limit (default=4), and rewrites
  the trade lists to contain only VALID accepted trades.
  
  Rejected trades are saved to 'results_tradelevel_rejected.csv' for audit.
  Original full lists are backed up to 'results_tradelevel_unconstrained.csv'.

Authority:
  IDX27 Directive ("Selection rule: Entries processed chronologically... Take first 4... Reject remaining")

Logic:
  1. Load all trades for strategy.
  2. Sort by Entry Time (ASC) -> Symbol (ASC).
  3. Iterate through time. Track active trades.
  4. If new trade entry time < valid exit time of 4th active trade, REJECT.
     Else ACCEPT.
  5. Save results back to symbol folders.
"""

import sys
import pandas as pd
import shutil
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).parent.parent
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/apply_portfolio_constraints.py <STRATEGY_ID> [MAX_CONCURRENT]")
        sys.exit(1)

    strategy_id = sys.argv[1]
    max_concurrent = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    
    print(f"\n{'='*60}")
    print(f"PORTFOLIO CONSTRAINT ENFORCEMENT — {strategy_id}")
    print(f"Max Concurrent Positions: {max_concurrent}")
    print(f"{'='*60}")

    # 1. Discovery
    trade_files = []
    symbol_folders = {} # sym -> folder path
    
    for folder in sorted(BACKTESTS_ROOT.iterdir()):
        if folder.is_dir() and folder.name.startswith(f"{strategy_id}_"):
            sym = folder.name.replace(f"{strategy_id}_", "")
            raw_dir = folder / "raw"
            csv_path = raw_dir / "results_tradelevel.csv"
            
            if csv_path.exists():
                trade_files.append((sym, csv_path))
                symbol_folders[sym] = raw_dir
    
    if not trade_files:
        print(f"No trade files found for {strategy_id}")
        sys.exit(1)
        
    print(f"[1/4] Loaded {len(trade_files)} symbol trade lists.")

    # 2. Aggregation
    all_trades = []
    for sym, path in trade_files:
        df = pd.read_csv(path)
        # Backup original
        backup_path = path.parent / "results_tradelevel_unconstrained.csv"
        if not backup_path.exists():
            shutil.copy(path, backup_path)
        
        df['symbol'] = sym
        df['_origin_path'] = str(path)
        df['entry_dt'] = pd.to_datetime(df['entry_timestamp'])
        df['exit_dt'] = pd.to_datetime(df['exit_timestamp'])
        all_trades.append(df)
        
    full_df = pd.concat(all_trades, ignore_index=True)
    full_df.sort_values(by=['entry_dt', 'symbol'], inplace=True)
    
    total_trades = len(full_df)
    print(f"[2/4] Processing {total_trades} total signal candidates...")

    # 3. Simulation (Throttle)
    accepted_indices = []
    rejected_indices = []
    
    active_trades = [] # List of {'exit_dt': datetime, 'symbol': str}
    
    for idx, row in full_df.iterrows():
        entry_time = row['entry_dt']
        
        # Clean up expired trades (strictly before entry?)
        # A trade exits AT exit_time. If new trade enters AT exit_time, is slot free?
        # Usually yes. Exit is execution. Position is closed.
        active_trades = [t for t in active_trades if t['exit_dt'] > entry_time]
        
        if len(active_trades) < max_concurrent:
            # Accept
            accepted_indices.append(idx)
            active_trades.append({
                'exit_dt': row['exit_dt'],
                'symbol': row['symbol']
            })
        else:
            # Reject
            rejected_indices.append(idx)
            
    accepted_count = len(accepted_indices)
    rejected_count = len(rejected_indices)
    
    print(f"[3/4] Filter Complete.")
    print(f"  Accepted: {accepted_count} ({accepted_count/total_trades*100:.1f}%)")
    print(f"  Rejected: {rejected_count} ({rejected_count/total_trades*100:.1f}%)")
    
    # 4. Distribution (Write Back)
    print("\n[4/4] Writing filtered results...")
    
    # Accepted DF
    accepted_df = full_df.loc[accepted_indices].copy()
    
    # Rejected DF (for audit)
    rejected_df = full_df.loc[rejected_indices].copy()
    
    # Group by symbol and save
    # Note: We must save empty CSVs if all trades were rejected for a symbol, 
    # to maintain file structure for Stage-2.
    
    for sym, folder in symbol_folders.items():
        sym_accepted = accepted_df[accepted_df['symbol'] == sym]
        sym_rejected = rejected_df[rejected_df['symbol'] == sym]
        
        # Restore original columns (exclude helper cols)
        # Helper cols: symbol, _origin_path, entry_dt, exit_dt
        # 'symbol' might be useful to keep? No, run_stage1 output doesn't have it standardly (metadata has it).
        # Actually `results_tradelevel.csv` usually doesn't have symbol col.
        
        orig_cols = pd.read_csv(folder / "results_tradelevel_unconstrained.csv", nrows=0).columns.tolist()
        
        # Save Accepted (Overwrite original)
        target_path = folder / "results_tradelevel.csv"
        if not sym_accepted.empty:
            sym_accepted[orig_cols].to_csv(target_path, index=False)
        else:
            # Write empty with headers
            pd.DataFrame(columns=orig_cols).to_csv(target_path, index=False)
            
        # Save Rejected
        reject_path = folder / "results_tradelevel_rejected.csv"
        if not sym_rejected.empty:
            sym_rejected[orig_cols].to_csv(reject_path, index=False)
            
        print(f"  {sym}: {len(sym_accepted)} accepted, {len(sym_rejected)} rejected")

    print(f"\nSUCCESS: Portfolio constraints enforced. Original files backed up to *_unconstrained.csv.")

if __name__ == "__main__":
    main()
