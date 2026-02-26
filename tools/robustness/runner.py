"""
Robustness Engine Runner.
Orchestrates computation modules. Returns structured results dict.
No markdown formatting here.
"""
import pandas as pd
from tools.robustness import (
    tail, monte_carlo, rolling, drawdown, friction, directional, symbol, temporal, bootstrap
)

def run_robustness_suite(
    prefix: str,
    profile: str,
    tr_df: pd.DataFrame,
    eq_df: pd.DataFrame,
    metrics: dict,
    run_bootstrap: bool = True
) -> dict:
    """
    Run all core robustness modules securely and return a structured dict of results.
    Preserves original section numbering/ordering for downstream formatters.
    """
    start_cap = metrics.get("starting_capital", 10_000)
    results = {}

    # Section 1: Edge metrics (from summary_metrics)
    pnls = tr_df["pnl_usd"]
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    n = len(pnls)

    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else 999
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    gross_win = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_win / gross_loss if gross_loss > 0 else 999

    eq = eq_df.copy()
    eq = eq.sort_values("timestamp")
    eq = eq.set_index("timestamp")
    eq = eq[~eq.index.duplicated(keep="last")]
    daily = eq["equity"].resample("D").last().ffill()
    peak = daily.cummax()
    max_dd_usd = float((peak - daily).max())
    net = float(pnls.sum())
    recovery_factor = net / max_dd_usd if max_dd_usd > 0 else 999

    results["edge_metrics"] = {
        "final_equity": metrics.get("final_equity", 0),
        "starting_capital": start_cap,
        "realized_pnl": metrics.get("realized_pnl", 0),
        "total_accepted": metrics.get("total_accepted", len(tr_df)),
        "total_trades": n,
        "win_rate": float(win_rate),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "payoff_ratio": float(payoff),
        "expectancy_per_trade": float(expectancy),
        "profit_factor": float(pf),
        "net_profit": net,
        "max_dd_usd": max_dd_usd,
        "recovery_factor": float(recovery_factor),
    }

    # Section 2: Tail
    results["tail_contribution"] = tail.tail_contribution(tr_df)
    
    # Section 3: Tail removal (loop over 1% and 5%)
    tr_results = []
    for pct in [0.01, 0.05]:
        tr_res = tail.tail_removal(
            tr_df, pct_cutoff=pct,
            start_cap=start_cap,
            sim_years=metrics.get("simulation_years"),
        )
        tr_res["pct_cutoff"] = pct
        tr_results.append(tr_res)
    results["tail_removal"] = tr_results

    # Section 3: Sequence MC (seed=42, 500 iterations)
    baseline = monte_carlo.simulate_percent_path(tr_df, start_cap)
    results["baseline_simulation"] = baseline
    mc_df = monte_carlo.run_random_sequence_mc(tr_df, iterations=500, start_cap=start_cap, seed=42)
    results["sequence_mc"] = {
        "mean_cagr": float(mc_df["cagr"].mean()),
        "median_cagr": float(mc_df["cagr"].median()),
        "p5_cagr": float(mc_df["cagr"].quantile(0.05)),
        "p95_cagr": float(mc_df["cagr"].quantile(0.95)),
        "mean_dd": float(mc_df["max_dd_pct"].mean()),
        "median_dd": float(mc_df["max_dd_pct"].median()),
        "p95_dd": float(mc_df["max_dd_pct"].quantile(0.95)),
        "blowup_runs": int(len(mc_df[mc_df["max_dd_pct"] > 90])),
        "baseline_cagr": baseline.get("cagr", 0),
        "iterations": 500,
        "seed": 42,
    }

    # Reverse Path Test
    rev = monte_carlo.run_reverse_path_test(tr_df, start_cap=start_cap)
    results["reverse_path"] = {
        "final_equity": float(rev["final_equity"]),
        "cagr": float(rev["cagr"]),
        "max_dd_pct": float(rev["max_dd_pct"]),
        "max_loss_streak": int(rev["max_loss_streak"])
    }

    # Section 4: Rolling windows
    win_df = rolling.rolling_window(eq_df, tr_df, window_days=365, step_days=30)
    stab = rolling.classify_stability(win_df)
    results["rolling"] = {
        "stability": stab,
        "window_count": len(win_df),
    }
    
    # Year-wise PnL & Monthly Heatmap
    tr_tmp = tr_df.copy()
    tr_tmp["year"] = tr_tmp["exit_timestamp"].dt.year
    tr_tmp["month"] = tr_tmp["exit_timestamp"].dt.month
    
    yr_grp = tr_tmp.groupby("year")
    yw_dict = {}
    for yr, grp in yr_grp:
        n_yr = len(grp)
        net_yr = float(grp["pnl_usd"].sum())
        wr_yr = float((grp["pnl_usd"] > 0).mean() * 100)
        avg_yr = float(grp["pnl_usd"].mean())
        yw_dict[str(int(yr))] = {
            "trades": n_yr,
            "net_pnl": net_yr,
            "win_rate": wr_yr,
            "avg_pnl": avg_yr
        }
    results["year_wise_pnl"] = yw_dict

    pivot = tr_tmp.pivot_table(values="pnl_usd", index="year", columns="month", aggfunc="sum", fill_value=0)
    monthly_dict = {}
    for yr in pivot.index:
        monthly_dict[str(int(yr))] = {str(int(m)): float(pivot.loc[yr, m]) for m in pivot.columns}
    results["monthly_heatmap"] = monthly_dict

    # Section 5/6: Drawdown
    clusters = drawdown.identify_dd_clusters(eq_df, top_n=3)
    dd_results = []
    for c in clusters:
        exp = drawdown.analyze_dd_exposure(tr_df, c)
        beh = drawdown.analyze_dd_trade_behavior(tr_df, c)
        dd_results.append({
            "start_date": c.get("start_date"),
            "trough_date": c.get("trough_date"),
            "recovery_date": c.get("recovery_date"),
            "max_dd_pct": c.get("max_dd_pct", 0),
            "duration_days": c.get("duration_days", 0),
            "exposure": exp,
            "behavior": beh,
        })
    results["drawdown"] = dd_results

    # Section 8: Streaks
    pnls = tr_df["pnl_usd"].values
    wins = (pnls > 0).astype(int)
    losses = (pnls < 0).astype(int)
    
    def _max_streak(arr):
        mx, cur = 0, 0
        for v in arr:
            if v: 
                cur += 1 
                if cur > mx: mx = cur
            else: 
                cur = 0
        return mx

    def _avg_streak(arr):
        streaks = []
        cur = 0
        for v in arr:
            if v:
                cur += 1
            else:
                if cur > 0:
                    streaks.append(cur)
                cur = 0
        if cur > 0:
            streaks.append(cur)
        return sum(streaks) / len(streaks) if streaks else 0
    
    results["streaks"] = {
        "max_win_streak": _max_streak(wins),
        "max_loss_streak": _max_streak(losses),
        "avg_win_streak": float(_avg_streak(wins)),
        "avg_loss_streak": float(_avg_streak(losses)),
        "total_trades": len(pnls),
    }

    # Section 9: Friction
    results["friction"] = friction.run_friction_scenarios(tr_df)

    # Section 10: Directional
    results["directional"] = directional.directional_removal(tr_df)

    # Section 11: Early/Late
    results["early_late"] = temporal.early_late_split(tr_df, start_cap=start_cap)

    # Section 12: Symbol isolation
    symbols = sorted(tr_df["symbol"].unique())
    if len(symbols) > 1:
        results["symbol_isolation"] = symbol.symbol_isolation(tr_df, start_cap=start_cap)
    else:
        results["symbol_isolation"] = {"note": "single_asset_skip"}

    # Section 13: Symbol breakdown
    sb_dict = {}
    for sym, grp in tr_df.groupby("symbol"):
        n = len(grp)
        net = float(grp["pnl_usd"].sum())
        wr = float((grp["pnl_usd"] > 0).mean() * 100)
        sb_dict[str(sym)] = {"pnl": net, "trades": n, "win_rate": wr}
    results["symbol_breakdown"] = sb_dict

    # Section 14: Block bootstrap (conditional)
    if run_bootstrap:
        try:
            bb_df = bootstrap.run_block_bootstrap(prefix, profile, iterations=100, seed=42)
            under = len(bb_df[bb_df["final_equity"] < bb_df["final_equity"].iloc[0]])
            results["block_bootstrap"] = {
                "median_equity": float(bb_df["final_equity"].median()),
                "p5_equity": float(bb_df["final_equity"].quantile(0.05)),
                "p95_equity": float(bb_df["final_equity"].quantile(0.95)),
                "mean_cagr": float(bb_df["cagr"].mean()),
                "median_cagr": float(bb_df["cagr"].median()),
                "p5_cagr": float(bb_df["cagr"].quantile(0.05)),
                "p95_cagr": float(bb_df["cagr"].quantile(0.95)),
                "mean_dd": float(bb_df["max_dd_pct"].mean()),
                "median_dd": float(bb_df["max_dd_pct"].median()),
                "worst_dd": float(bb_df["max_dd_pct"].max()),
                "under_start": under,
                "iterations": 100,
                "seed": 42,
            }
        except Exception as e:
            results["block_bootstrap"] = {"error": str(e)}

    # Section 15 & 16: Seasonality
    # Parse timeframe from prefix, e.g. AK35_FX_PORTABILITY_4H -> 4H
    import re
    from tools.robustness import seasonality
    
    tf_match = re.search(r"_(\d+[A-Za-z]+)$", prefix)
    tf_str = tf_match.group(1) if tf_match else "1D"
    
    results["monthly_seasonality"] = seasonality.analyze_monthly(tr_df, tf_str)
    results["weekday_seasonality"] = seasonality.analyze_weekday(tr_df, tf_str)

    return results
