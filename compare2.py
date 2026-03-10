import json
import pandas as pd
from pathlib import Path

targets = [
    "06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P61",
    "08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P03",
    "08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P06",
    "08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1_P31"
]

data = []
for strat in targets:
    try:
        path = Path("strategies") / strat / "deployable" / "FIXED_USD_V1" / "summary_metrics.json"
        with open(path, 'r') as f:
            metrics = json.load(f)
        
        # Make the patch prefix more explicit since they are from different families
        patch_name = f"{strat[:5]}...{strat[-3:]}"
        
        data.append({
            "Patch": patch_name,
            "Trades": metrics.get("total_accepted"),
            "Win Rate": f"{metrics.get('win_rate', 0)*100:.2f}%" if "win_rate" in metrics else "N/A",
            "Realized PnL": f"${metrics.get('realized_pnl', 0):,.2f}",
            "Max DD": f"${metrics.get('max_drawdown_usd', 0):,.2f}",
            "MAR": f"{metrics.get('mar', 0):.2f}",
            "CAGR": f"{metrics.get('cagr_pct', 0):.2f}%"
        })
    except Exception as e:
        data.append({
            "Patch": strat[-3:],
            "Error": str(e)
        })

df = pd.DataFrame(data)
print(df.to_markdown(index=False))
