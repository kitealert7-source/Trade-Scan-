"""6-metric quality gate (edge quality check).

Thresholds from promote.md — industry literature calibration.
Computes top-5 concentration, PnL w/o top 5, flat period, edge ratio,
trade count, and PF after removing top 5% of trades.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import BACKTESTS_DIR


# Thresholds from promote.md (industry literature calibration)
_QG_THRESHOLDS = {
    "top5_conc":   {"hard": 70.0, "warn": 50.0, "label": "Top-5 concentration (%)"},
    "wo5_pnl":     {"hard": 0.0,  "warn": 30.0, "label": "PnL w/o top 5 trades (%)"},
    "flat_pct":    {"hard": 40.0, "warn": 30.0, "label": "Flat period (%)"},
    "edge_ratio":  {"hard": 1.0,  "warn": 1.2,  "label": "Edge ratio (MFE/MAE)"},
    "trade_count": {"hard": 100,  "warn": 200,  "label": "Trade count"},
    "pf_minus5":   {"hard": 1.0,  "warn": 1.1,  "label": "PF after removing top 5%"},
}


def _compute_quality_gate(strategy_id: str) -> dict:
    """Compute 6-metric quality gate from trade-level CSVs.

    Returns dict with keys: metrics (dict of values), hard_fails (list),
    warns (list), passed (bool).
    """
    csvs = sorted(BACKTESTS_DIR.glob(f"{strategy_id}_*/raw/results_tradelevel.csv"))
    if not csvs:
        return {"metrics": {}, "hard_fails": ["No trade-level CSVs found"], "warns": [], "passed": False}

    frames = []
    for f in csvs:
        try:
            frames.append(pd.read_csv(f, encoding="utf-8"))
        except Exception:
            continue
    if not frames:
        return {"metrics": {}, "hard_fails": ["All CSVs unreadable"], "warns": [], "passed": False}

    df = pd.concat(frames, ignore_index=True)
    if "parent_trade_id" in df.columns and "symbol" in df.columns:
        df = df.drop_duplicates(subset=["parent_trade_id", "symbol"])

    n = len(df)
    pnls = df["pnl_usd"].sort_values(ascending=False)
    total = pnls.sum()

    # Gate 1: PnL without top 5 trades
    wo5 = pnls.iloc[5:].sum() if n > 5 else 0
    wo5_pct = (wo5 / total * 100) if total > 0 else -999

    # Gate 2: Top-5 concentration
    t5 = (pnls.iloc[:5].sum() / total * 100) if total > 0 else 999

    # Gate 3: Flat period
    flat_pct = 0.0
    try:
        exits = pd.to_datetime(df["exit_timestamp"])
        entries = pd.to_datetime(df["entry_timestamp"])
        bt_days = (exits.max() - entries.min()).days
        if bt_days > 0:
            cum = df.sort_values("exit_timestamp")["pnl_usd"].cumsum()
            rm = cum.cummax()
            hd = exits.loc[cum[cum == rm].index].sort_values()
            flat_d = int(hd.diff().dt.days.dropna().max()) if len(hd) > 1 else bt_days
            flat_pct = flat_d / bt_days * 100
    except Exception:
        flat_pct = 999

    # Gate 4: Edge ratio
    er = 0.0
    if "mfe_r" in df.columns and "mae_r" in df.columns:
        mae_mean = abs(df["mae_r"].mean())
        er = (df["mfe_r"].mean() / mae_mean) if mae_mean > 0 else 0.0

    # Gate 5: Trade count (n already computed)

    # Gate 6: PF after removing top 5% of trades
    top5pct_n = max(1, int(np.ceil(n * 0.05)))
    rem = pnls.iloc[top5pct_n:]
    w = rem[rem > 0].sum()
    l_val = abs(rem[rem <= 0].sum())
    pf_rem = (w / l_val) if l_val > 0 else 999

    metrics = {
        "top5_conc": round(t5, 1),
        "wo5_pnl": round(wo5_pct, 1),
        "flat_pct": round(flat_pct, 1),
        "edge_ratio": round(er, 2),
        "trade_count": n,
        "pf_minus5": round(pf_rem, 2),
    }

    hard_fails = []
    warns = []
    for key, thresh in _QG_THRESHOLDS.items():
        val = metrics[key]
        label = thresh["label"]
        if key in ("edge_ratio", "trade_count", "pf_minus5", "wo5_pnl"):
            # Lower is worse
            if val < thresh["hard"]:
                hard_fails.append(f"{label}: {val} < {thresh['hard']}")
            elif val < thresh["warn"]:
                warns.append(f"{label}: {val} < {thresh['warn']}")
        else:
            # Higher is worse (top5_conc, flat_pct)
            if val > thresh["hard"]:
                hard_fails.append(f"{label}: {val} > {thresh['hard']}")
            elif val > thresh["warn"]:
                warns.append(f"{label}: {val} > {thresh['warn']}")

    return {
        "metrics": metrics,
        "hard_fails": hard_fails,
        "warns": warns,
        "passed": len(hard_fails) == 0,
    }


def _print_quality_gate(qg: dict) -> None:
    """Print quality gate results in a formatted table."""
    print(f"\n  --- Quality Gate (6-metric edge check) ---")
    m = qg["metrics"]
    if not m:
        print(f"  [SKIP] No trade-level data available")
        return
    for key, thresh in _QG_THRESHOLDS.items():
        val = m.get(key, "?")
        label = thresh["label"]
        if key in ("edge_ratio", "trade_count", "pf_minus5", "wo5_pnl"):
            if val < thresh["hard"]:
                tag = "HARD FAIL"
            elif val < thresh["warn"]:
                tag = "WARN"
            else:
                tag = "OK"
        else:
            if val > thresh["hard"]:
                tag = "HARD FAIL"
            elif val > thresh["warn"]:
                tag = "WARN"
            else:
                tag = "OK"
        print(f"  {label:30s} {str(val):>8s}  {tag}")
    if qg["hard_fails"]:
        print(f"  RESULT: HARD FAIL ({len(qg['hard_fails'])} metric(s))")
    elif qg["warns"]:
        print(f"  RESULT: WARN ({len(qg['warns'])} metric(s))")
    else:
        print(f"  RESULT: PASS")
