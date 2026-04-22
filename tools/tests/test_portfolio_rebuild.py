import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = PROJECT_ROOT / "strategies"

def main():
    print("--- Test D: Portfolio Rebuild Validation ---")
    
    portfolio_id = "PF_AEC3B3603D9C"
    run_ids = ["4c4750b00b01"]
    portfolio_dir = STRATEGIES_DIR / portfolio_id
    
    if not portfolio_dir.exists():
        print(f"[INFO] Portfolio {portfolio_id} does not exist, creating it first...")
        cmd = ["python", "tools/run_portfolio_analysis.py", "--run-ids"] + run_ids
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    metrics_path = portfolio_dir / "portfolio_summary.json"
    if not metrics_path.exists():
        print(f"[ERROR] Failed to find metrics at {metrics_path}")
        return
        
    # Read original metrics
    with open(metrics_path, "r", encoding="utf-8") as f:
        orig_metrics = json.load(f)
        
    # Capture a key metric to compare
    orig_total_return = orig_metrics.get("Total Return [%]")
    print(f"[INFO] Original Total Return: {orig_total_return}")
    
    print(f"[INFO] Deleting portfolio folder {portfolio_dir.name}...")
    shutil.rmtree(portfolio_dir)
    
    print("[INFO] Scrubbing portfolio from Master_Portfolio_Sheet.xlsx ledger...")
    import pandas as pd
    ledger_path = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
    if ledger_path.exists():
        df = pd.read_excel(ledger_path)
        if "portfolio_id" in df.columns:
            df = df[df["portfolio_id"] != portfolio_id]
            df.to_excel(ledger_path, index=False)
            
    print("[INFO] Rebuilding portfolio from explicit run-ids...")
    cmd = ["python", "tools/run_portfolio_analysis.py", "--run-ids"] + run_ids
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if res.returncode != 0:
        print(f"[ERROR] Portfolio rebuild failed!\n{res.stderr}")
        return
        
    if not portfolio_dir.exists():
        print(f"[FAIL] Portfolio {portfolio_id} was not recreated!")
        return
        
    # Read new metrics
    with open(metrics_path, "r", encoding="utf-8") as f:
        new_metrics = json.load(f)
        
    new_total_return = new_metrics.get("Total Return [%]")
    print(f"[INFO] Rebuilt Total Return: {new_total_return}")
    
    if str(orig_total_return) == str(new_total_return):
        print("[PASS] Portfolio metrics perfectly match after rebuild!")
        print("[PASS] Native Run Atomicity Confirmed.")
    else:
        print(f"[FAIL] Metric mismatch! Orig: {orig_total_return}, New: {new_total_return}")

if __name__ == "__main__":
    main()
