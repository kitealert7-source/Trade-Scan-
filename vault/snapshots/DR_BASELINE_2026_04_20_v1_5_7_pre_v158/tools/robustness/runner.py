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
    all_profiles: dict = None,
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
    peak_equity = float(peak.max())
    peak_dd_ratio = round(peak_equity / max_dd_usd, 4) if max_dd_usd > 0 else 0.0

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
        "peak_dd_ratio": peak_dd_ratio,
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

    # Section 3: Regime-Aware Block Bootstrap MC (seed=42, 500 iterations)
    baseline = monte_carlo.simulate_percent_path(tr_df, start_cap)
    results["baseline_simulation"] = baseline
    mc_df, mc_meta = monte_carlo.run_regime_block_mc(tr_df, iterations=500, start_cap=start_cap, seed=42)
    results["regime_block_mc"] = {
        "mean_cagr": float(mc_df["cagr"].mean()),
        "median_cagr": float(mc_df["cagr"].median()),
        "p5_cagr": float(mc_df["cagr"].quantile(0.05)),
        "p95_cagr": float(mc_df["cagr"].quantile(0.95)),
        "mean_dd": float(mc_df["max_dd_pct"].mean()),
        "median_dd": float(mc_df["max_dd_pct"].median()),
        "p95_dd": float(mc_df["max_dd_pct"].quantile(0.95)),
        "blowup_runs": int(len(mc_df[mc_df["max_dd_pct"] > 90])),
        "baseline_cagr": baseline.get("cagr", 0),
        "iterations": mc_meta["iterations"],
        "seed": mc_meta["seed"],
        "mc_method": mc_meta["method"],
        "block_definition": mc_meta["block_definition"],
        "total_blocks": mc_meta["total_blocks"],
        "regime_distribution": mc_meta["regime_distribution"],
    }

    # Section 4.5: Position Sizing Guidance (Monte Carlo Derived)
    # Observational only — does NOT modify pipeline parameters.
    mc_dd_95 = results["regime_block_mc"]["p95_dd"]
    # Infer current risk from metrics or default to conservative 0.5%
    current_risk_pct = metrics.get("risk_per_trade", 0.005) * 100  # e.g. 0.5%

    target_dds = [10, 15, 20, 25, 30]
    sizing_table = []
    for target_dd in target_dds:
        if mc_dd_95 > 0:
            suggested = min(current_risk_pct * (target_dd / mc_dd_95), 2.0)
        else:
            suggested = current_risk_pct
        sizing_table.append({
            "target_max_dd": target_dd,
            "suggested_risk_pct": round(suggested, 2),
        })

    # Kelly fraction: f* = (b*p - q) / b  where b=payoff, p=win_prob, q=loss_prob
    w = win_rate / 100.0  # convert from percentage
    b = payoff             # payoff ratio from edge_metrics section
    kelly_full = max(((b * w) - (1 - w)) / b if b > 0 else 0, 0)
    kelly_safe = kelly_full * 0.5  # half-Kelly for safety

    results["position_sizing"] = {
        "current_risk_pct": round(current_risk_pct, 2),
        "mc_dd_95": round(mc_dd_95, 2),
        "sizing_table": sizing_table,
        "kelly_fraction": round(kelly_full, 4),
        "kelly_safe_fraction": round(kelly_safe, 4),
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

    # Section 9: Friction Stress Test (tiered: baseline / stress / extreme)
    results["friction"] = friction.run_friction_scenarios(tr_df)
    results["friction_tiered"] = friction.run_tiered_friction(tr_df)

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

    # ── Section 17: Capital Efficiency Summary + Baseline Comparison ──────────
    import math as _math

    if all_profiles is None:
        all_profiles = {}

    profile_data = all_profiles.get(profile, {})
    BASELINE_KEY = "RAW_MIN_LOT_V1"
    baseline_data = all_profiles.get(BASELINE_KEY, {})

    # ── Resolve utilized_capital for current profile ──
    utilized_capital = profile_data.get("utilized_capital")
    if utilized_capital is None:
        avg_heat = float(metrics.get("avg_heat_utilization_pct", 0.0))
        max_conc = int(metrics.get("max_concurrent_trades_during_test_period", 0))
        effective_capital = max_conc * 1000.0 if max_conc > 0 else 0.0
        utilized_capital = effective_capital * avg_heat
        cap_source = "recomputed"
    else:
        cap_source = "profile_comparison"

    # ── Portfolio-level efficiency metrics (current profile) ──
    n_total   = len(tr_df)
    net_pnl   = float(tr_df["pnl_usd"].sum())
    wins_s    = tr_df["pnl_usd"][tr_df["pnl_usd"] > 0]
    loss_s    = tr_df["pnl_usd"][tr_df["pnl_usd"] < 0]
    gross_win  = float(wins_s.sum())       if len(wins_s) > 0 else 0.0
    gross_loss = float(abs(loss_s.sum()))  if len(loss_s) > 0 else 0.0
    pf_total   = gross_win / gross_loss    if gross_loss > 1e-9 else 999.0

    rouc             = net_pnl / utilized_capital if utilized_capital > 1e-9 else 0.0
    util_pct         = float(profile_data.get("capital_efficiency_ratio", 0.0)) * 100
    stability_factor = min(1.0, pf_total / 2.0)
    sample_factor    = _math.log(1 + n_total)
    efficiency_score = rouc * stability_factor * sample_factor

    # ── Per-engine ranking (composite PF_ prefix only) ──
    engine_rows = []
    is_composite = prefix.startswith("PF_")
    if is_composite and "trade_id" in tr_df.columns:
        tr_tmp = tr_df.copy()
        tr_tmp["_prefix"] = tr_tmp["trade_id"].str.split("|").str[0]
        for eng_prefix, grp in tr_tmp.groupby("_prefix"):
            eng_n     = len(grp)
            eng_net   = float(grp["pnl_usd"].sum())
            eng_wins  = grp["pnl_usd"][grp["pnl_usd"] > 0]
            eng_loss  = grp["pnl_usd"][grp["pnl_usd"] < 0]
            eng_gw    = float(eng_wins.sum())      if len(eng_wins) > 0 else 0.0
            eng_gl    = float(abs(eng_loss.sum())) if len(eng_loss) > 0 else 0.0
            eng_pf    = eng_gw / eng_gl            if eng_gl > 1e-9 else 999.0
            eng_proxy = eng_net / 1000.0           # return_proxy_per_1000
            eng_stab  = min(1.0, eng_pf / 2.0)
            eng_samp  = _math.log(1 + eng_n)
            eng_score = eng_proxy * eng_stab * eng_samp
            parts = str(eng_prefix).rsplit("_", 1)
            engine_rows.append({
                "prefix":               eng_prefix,
                "strategy_id":          parts[0] if len(parts) == 2 else eng_prefix,
                "symbol":               parts[1] if len(parts) == 2 else "",
                "trades":               eng_n,
                "net_pnl":              eng_net,
                "pf":                   round(eng_pf, 4),
                "return_proxy_per_1000": round(eng_proxy, 4),
                "stability_factor":     round(eng_stab, 4),
                "sample_factor":        round(eng_samp, 4),
                "efficiency_score":     round(eng_score, 4),
            })
        engine_rows.sort(key=lambda r: r["efficiency_score"], reverse=True)

    # ── Baseline comparison (RAW_MIN_LOT_V1 vs current profile) ──
    baseline_comparison = None
    if baseline_data and profile != BASELINE_KEY:
        b_pnl   = float(baseline_data.get("realized_pnl", 0.0))
        b_rouc  = float(baseline_data.get("return_on_utilized_capital", 0.0))
        b_util  = float(baseline_data.get("capital_efficiency_ratio", 0.0)) * 100
        b_dd    = float(baseline_data.get("max_drawdown_pct", 0.0))

        c_pnl   = float(profile_data.get("realized_pnl", net_pnl))
        c_rouc  = float(profile_data.get("return_on_utilized_capital", rouc))
        c_util  = util_pct
        c_dd    = float(profile_data.get("max_drawdown_pct", 0.0))

        # Derived metrics
        pnl_multiplier         = c_pnl / b_pnl        if abs(b_pnl)  > 1e-9 else None
        utilization_multiplier = c_util / b_util       if abs(b_util) > 1e-9 else None
        edge_delta             = c_rouc - b_rouc

        # Interpretation: what is driving PnL improvement?
        high_util_lift  = utilization_multiplier is not None and utilization_multiplier >= 1.5
        large_edge      = abs(edge_delta) >= 0.1
        if high_util_lift and not large_edge:
            driver = "utilization"
        elif large_edge and not high_util_lift:
            driver = "edge improvement"
        else:
            driver = "both"

        baseline_comparison = {
            "baseline_key":            BASELINE_KEY,
            "current_key":             profile,
            "baseline_pnl":            round(b_pnl,  2),
            "current_pnl":             round(c_pnl,  2),
            "baseline_rouc":           round(b_rouc, 4),
            "current_rouc":            round(c_rouc, 4),
            "baseline_util_pct":       round(b_util, 2),
            "current_util_pct":        round(c_util, 2),
            "baseline_max_dd_pct":     round(b_dd,   2),
            "current_max_dd_pct":      round(c_dd,   2),
            "pnl_multiplier":          round(pnl_multiplier, 2)          if pnl_multiplier         is not None else None,
            "utilization_multiplier":  round(utilization_multiplier, 2)  if utilization_multiplier is not None else None,
            "edge_delta":              round(edge_delta, 4),
            "driver":                  driver,
        }

    results["capital_efficiency"] = {
        "utilized_capital":           round(utilized_capital, 2),
        "net_pnl":                    round(net_pnl, 2),
        "return_on_utilized_capital": round(rouc, 4),
        "utilization_pct":            round(util_pct, 2),
        "profit_factor":              round(pf_total, 4),
        "total_trades":               n_total,
        "stability_factor":           round(stability_factor, 4),
        "sample_factor":              round(sample_factor, 4),
        "efficiency_score":           round(efficiency_score, 4),
        "is_composite":               is_composite,
        "engine_ranking":             engine_rows,
        "capital_source":             cap_source,
        "baseline_comparison":        baseline_comparison,
    }

    # Section 18: Edge Quality Gate — industry-calibrated pre-promote metrics
    import numpy as np

    pnls_sorted = tr_df["pnl_usd"].sort_values(ascending=False)
    total_pnl = pnls_sorted.sum()
    n_trades = len(pnls_sorted)

    # t-statistic / SQN
    mean_pnl = pnls_sorted.mean()
    std_pnl = pnls_sorted.std()
    ir = float(mean_pnl / std_pnl) if std_pnl > 0 else 0
    t_stat = float(ir * np.sqrt(n_trades)) if std_pnl > 0 else 0
    n_for_t2 = (2.0 / ir) ** 2 if ir > 0 else 99999
    n_for_t3 = (3.0 / ir) ** 2 if ir > 0 else 99999

    # Gate 1: Remove top 5 trades -> PnL
    without_top5 = float(pnls_sorted.iloc[5:].sum()) if n_trades > 5 else 0
    without_top5_pct = (without_top5 / total_pnl * 100) if total_pnl > 0 else -999

    # Gate 2: Top-5 concentration
    top5_pnl = float(pnls_sorted.iloc[:5].sum()) if n_trades >= 5 else float(pnls_sorted.sum())
    top5_pct = (top5_pnl / total_pnl * 100) if total_pnl > 0 else 999

    # Gate 3: Flat period as % of backtest
    if "exit_timestamp" in tr_df.columns and "entry_timestamp" in tr_df.columns:
        exits = pd.to_datetime(tr_df["exit_timestamp"])
        entries_dt = pd.to_datetime(tr_df["entry_timestamp"])
        bt_days = (exits.max() - entries_dt.min()).days
        df_sorted = tr_df.sort_values("exit_timestamp")
        cum = df_sorted["pnl_usd"].cumsum()
        running_max = cum.cummax()
        high_dates = exits.loc[cum[cum == running_max].index].sort_values()
        longest_flat = int(high_dates.diff().dt.days.dropna().max()) if len(high_dates) > 1 else bt_days
        flat_pct = (longest_flat / bt_days * 100) if bt_days > 0 else 999
    else:
        bt_days = 0
        longest_flat = 0
        flat_pct = 999

    # Gate 4: Edge ratio (MFE/MAE)
    if "mfe_r" in tr_df.columns and "mae_r" in tr_df.columns:
        mae_mean = abs(tr_df["mae_r"].mean())
        edge_ratio = float(tr_df["mfe_r"].mean() / mae_mean) if mae_mean > 0 else 0
    else:
        edge_ratio = -1

    # Gate 6: PF after removing top 5% of trades
    top5pct_n = max(1, int(np.ceil(n_trades * 0.05)))
    remaining = pnls_sorted.iloc[top5pct_n:]
    w_rem = remaining[remaining > 0].sum()
    l_rem = abs(remaining[remaining <= 0].sum())
    pf_after_5pct = float(w_rem / l_rem) if l_rem > 0 else 999

    # Evaluate verdicts
    gates = []
    # Gate 1
    if without_top5 < 0:
        gates.append({"gate": "Top-5 Removal PnL", "value": f"${without_top5:.2f}", "verdict": "HARD FAIL"})
    elif without_top5_pct < 30:
        gates.append({"gate": "Top-5 Removal PnL", "value": f"{without_top5_pct:.1f}% survives", "verdict": "WARN"})
    else:
        gates.append({"gate": "Top-5 Removal PnL", "value": f"{without_top5_pct:.1f}% survives", "verdict": "OK"})
    # Gate 2
    if top5_pct > 70:
        gates.append({"gate": "Top-5 Concentration", "value": f"{top5_pct:.1f}%", "verdict": "HARD FAIL"})
    elif top5_pct > 50:
        gates.append({"gate": "Top-5 Concentration", "value": f"{top5_pct:.1f}%", "verdict": "WARN"})
    else:
        gates.append({"gate": "Top-5 Concentration", "value": f"{top5_pct:.1f}%", "verdict": "OK"})
    # Gate 3
    if flat_pct > 40:
        gates.append({"gate": "Flat Period %", "value": f"{flat_pct:.1f}%", "verdict": "HARD FAIL"})
    elif flat_pct > 30:
        gates.append({"gate": "Flat Period %", "value": f"{flat_pct:.1f}%", "verdict": "WARN"})
    else:
        gates.append({"gate": "Flat Period %", "value": f"{flat_pct:.1f}%", "verdict": "OK"})
    # Gate 4
    if edge_ratio >= 0 and edge_ratio < 1.0:
        gates.append({"gate": "Edge Ratio (MFE/MAE)", "value": f"{edge_ratio:.2f}", "verdict": "HARD FAIL"})
    elif edge_ratio >= 0 and edge_ratio < 1.2:
        gates.append({"gate": "Edge Ratio (MFE/MAE)", "value": f"{edge_ratio:.2f}", "verdict": "WARN"})
    elif edge_ratio >= 0:
        gates.append({"gate": "Edge Ratio (MFE/MAE)", "value": f"{edge_ratio:.2f}", "verdict": "OK"})
    else:
        gates.append({"gate": "Edge Ratio (MFE/MAE)", "value": "N/A", "verdict": "N/A"})
    # Gate 5
    if n_trades < 100:
        gates.append({"gate": "Trade Count", "value": str(n_trades), "verdict": "HARD FAIL"})
    elif n_trades < 200:
        gates.append({"gate": "Trade Count", "value": str(n_trades), "verdict": "WARN"})
    else:
        gates.append({"gate": "Trade Count", "value": str(n_trades), "verdict": "OK"})
    # Gate 6
    if pf_after_5pct < 1.0:
        gates.append({"gate": "PF After Top-5% Removal", "value": f"{pf_after_5pct:.2f}", "verdict": "HARD FAIL"})
    elif pf_after_5pct < 1.1:
        gates.append({"gate": "PF After Top-5% Removal", "value": f"{pf_after_5pct:.2f}", "verdict": "WARN"})
    else:
        gates.append({"gate": "PF After Top-5% Removal", "value": f"{pf_after_5pct:.2f}", "verdict": "OK"})

    hard_fails = sum(1 for g in gates if g["verdict"] == "HARD FAIL")
    warns = sum(1 for g in gates if g["verdict"] == "WARN")
    if hard_fails > 0:
        overall = "REJECT"
    elif warns > 0:
        overall = "CONDITIONAL"
    else:
        overall = "PASS"

    # t-stat verdict
    if t_stat >= 3.0:
        t_verdict = "Harvey-grade (t >= 3.0)"
    elif t_stat >= 2.0:
        t_verdict = "Standard significance (t >= 2.0)"
    elif t_stat >= 1.5:
        t_verdict = "Marginal (t >= 1.5)"
    else:
        t_verdict = "Insufficient evidence"

    results["edge_quality_gate"] = {
        "t_stat": round(t_stat, 2),
        "ir_per_trade": round(ir, 4),
        "trades_needed_t2": round(n_for_t2, 0),
        "trades_needed_t3": round(n_for_t3, 0),
        "t_verdict": t_verdict,
        "bt_days": bt_days,
        "longest_flat_days": longest_flat,
        "gates": gates,
        "overall_verdict": overall,
        "hard_fails": hard_fails,
        "warns": warns,
    }

    return results
