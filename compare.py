import json
import pandas as pd
from pathlib import Path

targets = [
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
        data.append({
            "Patch": strat[-3:],
            "Total Trades": metrics["total_accepted"],
            "Win Rate (%)": f"{metrics['win_rate']*100:.2f}%",
            "Realized PnL": f"${metrics['realized_pnl']:,.2f}",
            "Max Drawdown": f"${metrics['max_drawdown']:,.2f}",
            "Profit Factor": f"{metrics['profit_factor']:.2f}",
            "Return/DD Ratio": f"{metrics['return_dd_ratio']:.2f}",
            "Expectancy": f"${metrics['expectancy_per_trade']:,.2f}"
        })
    except Exception as e:
        data.append({
            "Patch": strat[-3:],
            "Error": str(e)
        })

df = pd.DataFrame(data)
print(df.to_markdown(index=False))
