"""
Seasonality Diagnostics (v2)
Implements timeframe-agnostic, horizon-aware calendar analysis using 
non-parametric Kruskal-Wallis testing and stability splits.
"""

import math
import numpy as np
import pandas as pd

from scipy.stats import kruskal


def _get_horizon_mode(tr_df: pd.DataFrame) -> str:
    if len(tr_df) == 0:
        return "SHORT"
    min_entry = tr_df["entry_timestamp"].min()
    max_exit = tr_df["exit_timestamp"].max()
    dur_days = (max_exit - min_entry).days
    years = dur_days / 365.25
    if years < 2:
        return "SHORT"
    elif years <= 5:
        return "MEDIUM"
    else:
        return "FULL"


def _check_stability(tr_df: pd.DataFrame, time_col: str, flag_buckets: list) -> dict:
    """
    Splits df into chronologically equal halves by trade count.
    Tests if flagged buckets have same sign and weaker half >= 25% of stronger half.
    """
    n = len(tr_df)
    mid = n // 2
    h1 = tr_df.iloc[:mid]
    h2 = tr_df.iloc[mid:]
    
    stability = {}
    for b in flag_buckets:
        h1_b = h1[h1[time_col] == b]["pnl_usd"].copy()
        h2_b = h2[h2[time_col] == b]["pnl_usd"].copy()
        
        h1_net = float(h1_b.sum()) if len(h1_b) > 0 else 0.0
        h2_net = float(h2_b.sum()) if len(h2_b) > 0 else 0.0
        
        if h1_net * h2_net <= 0:  # Different signs or one is zero
            stability[b] = False
        else:
            mag1, mag2 = abs(h1_net), abs(h2_net)
            weaker, stronger = min(mag1, mag2), max(mag1, mag2)
            stability[b] = (weaker >= 0.25 * stronger)
            
    return stability


def _analyze_seasonality(tr_df: pd.DataFrame, time_col: str, k_buckets: int) -> dict:
    """Core logic for both monthly and weekday."""
    tr_tmp = tr_df.copy()
    tr_tmp = tr_tmp.sort_values("exit_timestamp").reset_index(drop=True)
    
    if time_col == "month":
        tr_tmp[time_col] = tr_tmp["exit_timestamp"].dt.month
        buckets = range(1, 13)
        expected_k = 12
    elif time_col == "weekday":
        tr_tmp[time_col] = tr_tmp["exit_timestamp"].dt.weekday + 1 # 1=Mon, 5=Fri
        buckets = range(1, 6)
        expected_k = 5
    else:
        raise ValueError("time_col must be month or weekday")

    mode = _get_horizon_mode(tr_tmp)
    global_mean = tr_tmp["pnl_usd"].mean()
    global_std = tr_tmp["pnl_usd"].std()
    if pd.isna(global_std) or global_std == 0:
        global_std = 1.0

    groups = []
    bucket_stats = []
    
    # Prepare groups for KW
    for b in buckets:
        b_df = tr_tmp[tr_tmp[time_col] == b]
        pnls = b_df["pnl_usd"].values
        groups.append(pnls)
        
        n_trades = len(pnls)
        net_pnl = float(pnls.sum())
        wins = pnls[pnls > 0].sum()
        losses = abs(pnls[pnls < 0].sum())
        pf = float(wins / losses) if losses > 0 else (999.0 if wins > 0 else 0.0)
        
        mean_pnl = float(pnls.mean()) if n_trades > 0 else 0.0
        deviation = (mean_pnl - global_mean) / global_std
        
        # Bucket flagging: > 1.5 sigma AND >= 20 trades
        is_flagged = bool(abs(deviation) > 1.5 and n_trades >= 20)
        
        bucket_stats.append({
            time_col: b,
            "trades": n_trades,
            "pnl": net_pnl,
            "pf": pf,
            "mean_pnl": mean_pnl,
            "flag": is_flagged,
            "stable": None
        })

    # Run K-W using SciPy
    n_total = sum(len(g) for g in groups)
    k = len(groups)
    
    if n_total == 0 or k < 2:
        h, p_val = 0.0, 1.0
    else:
        try:
            h, p_val = kruskal(*groups)
            if math.isnan(h) or math.isnan(p_val):
                h, p_val = 0.0, 1.0
        except ValueError:
            h, p_val = 0.0, 1.0
            
    p_le_10 = bool(p_val <= 0.10)
    
    # Effect size (eta squared)
    eta_sq = (h - k + 1) / (n_total - k) if n_total > k else 0.0
    eta_sq = max(0.0, eta_sq)
    
    verdict = ""
    if not p_le_10:
        verdict = "No significant calendar pattern"
    else:
        if eta_sq < 0.02:
            verdict = "Weak pattern detected (low effect size)"
        else:
            verdict = "Significant calendar pattern"

    flagged_buckets = [b[time_col] for b in bucket_stats if b["flag"]]
    
    # Stability testing (FULL mode only)
    if mode == "FULL" and p_le_10 and eta_sq >= 0.02 and flagged_buckets:
        stab_dict = _check_stability(tr_tmp, time_col, flagged_buckets)
        for b in bucket_stats:
            if b["flag"]:
                b["stable"] = stab_dict.get(b[time_col], False)
        
        # Downgrade check
        if not all(stab_dict.values()):
            verdict += " [DOWNGRADED: Unstable subperiods]"

    # Exposure Decision Matrix
    decisions = []
    if p_le_10 and eta_sq >= 0.02 and mode in ["MEDIUM", "FULL"]:
        all_stable = True
        if mode == "FULL":
            all_stable = all(b["stable"] for b in bucket_stats if b["flag"])
            
        if mode == "MEDIUM" or all_stable:
            for b in bucket_stats:
                if b["flag"] and b["trades"] >= 20 and b["mean_pnl"] < 0:
                    action = "None"
                    if b["pf"] < 0.85:
                        action = "Avoid (0x)" if mode == "FULL" else "Throttle (0.5x)"
                    elif b["pf"] < 1.0:
                        action = "Throttle (0.5x)"
                        
                    if action != "None":
                        decisions.append({
                            time_col: b[time_col],
                            "action": action,
                            "pf": b["pf"]
                        })

    return {
        "mode": mode,
        "suppressed": False,
        "suppression_reason": None,
        "test_statistic": float(h),
        "p_value": float(p_val),
        "p_le_10": bool(p_le_10),
        "effect_size": float(eta_sq),
        "verdict": verdict,
        "buckets": bucket_stats,
        "exposure_decisions": decisions if decisions else None,
        "dispersion": {
            "max_deviation": float(max(abs(b["mean_pnl"] - global_mean) for b in bucket_stats)),
            "global_mean": float(global_mean)
        }
    }


def _suppressed_output(tr_df: pd.DataFrame, reason: str, time_col: str) -> dict:
    mode = _get_horizon_mode(tr_df)
    global_mean = tr_df["pnl_usd"].mean() if len(tr_df) > 0 else 0.0
    
    if time_col == "month":
        vals = tr_df["exit_timestamp"].dt.month if len(tr_df) > 0 else []
        buckets = range(1, 13)
    else:
        vals = tr_df["exit_timestamp"].dt.weekday + 1 if len(tr_df) > 0 else []
        buckets = range(1, 6)
        
    means = []
    if len(tr_df) > 0:
        tr_tmp = tr_df.copy()
        tr_tmp[time_col] = vals
        for b in buckets:
            b_pnls = tr_tmp[tr_tmp[time_col] == b]["pnl_usd"]
            if len(b_pnls) > 0:
                means.append(b_pnls.mean())
                
    max_dev = max([abs(m - global_mean) for m in means]) if means else 0.0

    return {
        "mode": mode,
        "suppressed": True,
        "suppression_reason": reason,
        "dispersion": {
            "max_deviation": float(max_dev),
            "global_mean": float(global_mean)
        }
    }


def analyze_monthly(tr_df: pd.DataFrame, timeframe: str) -> dict:
    """Analyze monthly seasonality."""
    if len(tr_df) < 300:
        return _suppressed_output(tr_df, f"{len(tr_df)} trades < 300 threshold", "month")
    return _analyze_seasonality(tr_df, "month", 12)


def analyze_weekday(tr_df: pd.DataFrame, timeframe: str) -> dict:
    """Analyze weekday seasonality."""
    if timeframe.upper() in ["1D", "DAILY", "W", "WEEKLY"]:
        return _suppressed_output(tr_df, f"Not applicable for {timeframe} timeframe", "weekday")
        
    if len(tr_df) < 200:
        return _suppressed_output(tr_df, f"{len(tr_df)} trades < 200 threshold", "weekday")
        
    if "4H" in timeframe.upper():
        if len(tr_df) / 5 < 40:
            return _suppressed_output(tr_df, f"Insufficient 4H density ({len(tr_df)} trades)", "weekday")
            
    return _analyze_seasonality(tr_df, "weekday", 5)
