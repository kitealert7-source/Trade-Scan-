"""
run_portfolio_analysis.py — Governance-Grade Portfolio Engine (v3.0)

Fully compliant with SOP_PORTFOLIO_ANALYSIS_v1_0.md

Capital Model:
- Per-run fixed allocation
- Trade-close compounding only
- No MTM
- No trade rejection
- No scaling

Concurrency Definition (Authoritative):
entry_A < exit_B AND entry_B < exit_A
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import subprocess


# ==========================================================
# ENGINE CONSTANTS
# ==========================================================

PORTFOLIO_ENGINE_VERSION = "3.0"
SCHEMA_VERSION = "1.0"
CAPITAL_MODEL_VERSION = "v1.0_trade_close_compounding"
ROLLING_WINDOW_LENGTH = 252
CAPITAL_PER_RUN_USD = 5000

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGY_MASTER_PATH = PROJECT_ROOT / "backtests" / "Strategy_Master_Filter.xlsx"
PORTFOLIO_MASTER_PATH = PROJECT_ROOT / "strategies" / "Master_Portfolio_Sheet.xlsx"
PORTFOLIO_ROOT = PROJECT_ROOT / "strategies"


# ==========================================================
# FAIL FAST
# ==========================================================

def fail(msg):
    print(f"[FATAL] {msg}")
    sys.exit(1)


# ==========================================================
# PORTFOLIO ID
# ==========================================================

def deterministic_portfolio_id(run_ids):
    sorted_ids = sorted(run_ids)
    joined = "|".join(sorted_ids)
    h = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return f"PF_{h.upper()}"


# ==========================================================
# CAPITAL ENGINE
# ==========================================================

def compute_equity_curve(trades, reference_capital):
    equity = reference_capital
    equity_before_list = []
    equity_after_list = []
    return_list = []

    for _, row in trades.iterrows():
        equity_before_list.append(equity)
        pnl = row["pnl"]
        r = pnl / equity if equity != 0 else 0.0
        equity += pnl
        equity_after_list.append(equity)
        return_list.append(r)

    trades["equity_before_trade"] = equity_before_list
    trades["equity_after_trade"] = equity_after_list
    trades["return_t"] = return_list

    return trades


# ==========================================================
# CONCURRENCY ENGINE
# ==========================================================

from collections import defaultdict

# ==========================================================
# CONCURRENCY ENGINE (Ported from portfolio_evaluator.py)
# ==========================================================

def compute_concurrency_series(portfolio_df):
    """
    Compute concurrency metrics using exact timestamp overlap.
    (Strict Port from portfolio_evaluator.py)
    Returns:
        - concurrency_series: list of concurrency counts at each trade entry
        - max_concurrent: global maximum peak
        - avg_concurrent: time-weighted average
        - pct_time_at_max: percentage of time at global max
        - pct_time_deployed: percentage of time with count > 0
    """
    if portfolio_df.empty:
        return [], 0, 0.0, 0.0, 0.0

    # Ensure chronological order by entry time
    df_sorted = portfolio_df.sort_values('entry_timestamp').copy()
    
    events = []
    for idx, row in df_sorted.iterrows():
        events.append((row['entry_timestamp'], 1))
        events.append((row['exit_timestamp'], -1))
        
    # Sort events: time asc, then exit(-1) before entry(1)
    events.sort(key=lambda x: (x[0], x[1]))
    
    current_concurrent = 0
    max_concurrent = 0
    weighted_sum = 0.0
    time_deployed = 0.0
    duration_by_count = defaultdict(float)
    
    last_time = events[0][0]
    total_duration = (events[-1][0] - events[0][0]).total_seconds()
    
    series = []
    
    for t, type_ in events:
        delta = (t - last_time).total_seconds()
        if delta > 0:
            weighted_sum += current_concurrent * delta
            duration_by_count[current_concurrent] += delta
            if current_concurrent > 0:
                time_deployed += delta
        
        if type_ == 1:
            current_concurrent += 1
            series.append(current_concurrent)
        else:
            current_concurrent -= 1
            
        if current_concurrent > max_concurrent:
            max_concurrent = current_concurrent
            
        last_time = t
        
    avg_concurrent = weighted_sum / total_duration if total_duration > 0 else 0.0
    pct_deployed = (time_deployed / total_duration) if total_duration > 0 else 0.0
    
    time_at_max = duration_by_count[max_concurrent]
    pct_at_max = (time_at_max / total_duration) if total_duration > 0 else 0.0
    
    return series, max_concurrent, avg_concurrent, pct_at_max, pct_deployed


def compute_concurrency_profile(trades, equity_series):
    """
    Analyze concurrency distribution and extreme loads.
    (Strict Port from portfolio_evaluator.py)
    """
    # 1. Base Series
    series, max_conc, avg_conc, pct_at_max, pct_deployed = compute_concurrency_series(trades)
    
    concurrent_values = np.array(series)
    
    # 2. P95
    if len(concurrent_values) > 0:
        p95_conc = np.percentile(concurrent_values, 95)
    else:
        p95_conc = 0
        
    # 3. Full Load Cluster
    # "Full load clustering detected": 95th percentile concurrency equals maximum concurrency.
    full_load_cluster = (p95_conc >= max_conc - 1e-9)
    
    # 4. During Largest DD
    # equity_series is expected to be a time-indexed Series (from compute_equity_curve or similar)
    # in run_portfolio_analysis, we have trades['equity_after_trade'] indexed by integer.
    # We need a proper time index for DD calculation overlap.
    
    # Construct time-indexed equity for DD overlap calculation
    eq_time = trades.set_index("exit_timestamp")["equity_after_trade"]
    running_max = eq_time.cummax()
    dd = eq_time - running_max
    
    trough_date = dd.idxmin()
    # Handle edge case where trough_date might be NaT or empty
    if pd.isna(trough_date):
         dd_max = 0
         dd_avg = 0
    else:
        peak_data = eq_time[:trough_date]
        peak_date = peak_data.idxmax() if not peak_data.empty else trough_date
        
        # Filter trades active during DD window
        active_in_dd = trades[
            (trades['exit_timestamp'] >= peak_date) & 
            (trades['entry_timestamp'] <= trough_date)
        ]
        
        if not active_in_dd.empty:
            dd_series, dd_max, dd_avg, _, _ = compute_concurrency_series(active_in_dd)
        else:
            dd_max = 0
            dd_avg = 0
            
    # Attach to trades for export (legacy support for simple series)
    # The 'series' variable aligns with 'entry_timestamp' sorted trades.
    # But 'trades' passed here is usually sorted by exit in main().
    # compute_concurrency_series sorts by entry internally.
    # To map back to 'trades', we need to be careful.
    # Strict Port: The evaluator doesn't attach this series to the DF permanent columns usually, 
    # but run_portfolio_analysis expects 'concurrency_at_entry' column.
    
    # We will re-generate the simple series aligned to the input 'trades' index for the CSV output
    # This is a slight deviation but necessary for the "trades" object persistence.
    # Or strict adherence: Re-implement the loop to map by Entry?
    # portfolio_tradelevel.csv requires 'concurrency_at_entry'.
    # Let's compute that simply for the DF:
    
    # Re-compute simple per-row concurrency for the DF columns (Capital Engine requirement)
    # Sort by entry to match logical sweep
    df_sorted = trades.sort_values('entry_timestamp').copy()
    temp_series, _, _, _, _ = compute_concurrency_series(df_sorted)
    
    # Create a mapping from original index to concurrency
    # Assuming df_sorted preserves original index
    conc_map = {idx: val for idx, val in zip(df_sorted.index, temp_series)}
    
    concurrency_at_entry_series = pd.Series(trades.index.map(conc_map), index=trades.index).fillna(0)
    
    capital_deployed_series = concurrency_at_entry_series * CAPITAL_PER_RUN_USD
    
    peak_capital_deployed = capital_deployed_series.max() if not capital_deployed_series.empty else 0.0

    metrics = {
        "avg_concurrent": avg_conc,
        "max_concurrent": int(max_conc),
        "p95_concurrent": p95_conc,
        "dd_max_concurrent": int(dd_max),
        "full_load_cluster": full_load_cluster,
        "peak_capital_deployed": peak_capital_deployed,
        "pct_time_deployed": pct_deployed  # Phase 16: Exposure Metric
    }
    
    return concurrency_at_entry_series, capital_deployed_series, metrics


# ==========================================================
# DRAWDOWN + STRESS WINDOW
# ==========================================================

def compute_drawdown(trades):

    equity = trades["equity_after_trade"]
    rolling_peak = equity.cummax()
    drawdown = equity - rolling_peak

    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()
    peak_idx = equity.loc[:trough_idx].idxmax()

    peak_time = trades.loc[peak_idx, "exit_timestamp"]
    trough_time = trades.loc[trough_idx, "exit_timestamp"]

    max_dd_pct = max_dd / equity.loc[peak_idx] if equity.loc[peak_idx] != 0 else 0.0

    return max_dd, max_dd_pct, peak_time, trough_time


# ==========================================================
# CORRELATION ENGINE
# ==========================================================

def compute_correlation(trades, peak_time, trough_time):

    # Build daily PnL matrix by strategy
    daily = (
        trades
        .set_index("exit_timestamp")
        .groupby("strategy_id")["pnl"]
        .resample("1D")
        .sum()
        .unstack(0)
        .fillna(0)
    )

    if daily.shape[1] < 2:
        return 0.0, 0.0

    corr_full = daily.corr().values
    avg_pairwise_corr = float(np.mean(corr_full[np.triu_indices_from(corr_full, k=1)]))

    # Stress window subset
    stress_mask = (daily.index >= peak_time) & (daily.index <= trough_time)
    daily_stress = daily.loc[stress_mask]

    if daily_stress.shape[0] < 2 or daily_stress.shape[1] < 2:
        max_corr_stress = 0.0
    else:
        corr_stress = daily_stress.corr().values
        max_corr_stress = float(np.max(corr_stress[np.triu_indices_from(corr_stress, k=1)]))

    return avg_pairwise_corr, max_corr_stress


# ==========================================================
# LEDGER APPEND
# ==========================================================




# ==========================================================
# MAIN
# ==========================================================

def main():

    if not STRATEGY_MASTER_PATH.exists():
        fail("Strategy_Master_Filter.xlsx missing.")

    df_master = pd.read_excel(STRATEGY_MASTER_PATH)

    # Normalize column names to uppercase for consistent access
    df_master.columns = [c.upper() for c in df_master.columns]

    required_cols = ["IN_PORTFOLIO", "RUN_ID", "STRATEGY"]
    for col in required_cols:
        if col not in df_master.columns:
            fail(f"Missing column in master sheet: {col}")

    # Relaxed filter: implied status from IN_PORTFOLIO
    selected = df_master[
        (df_master["IN_PORTFOLIO"] == True)
    ]

    if selected.empty:
        fail("No eligible RUN_COMPLETE strategies selected.")

    run_ids = selected["RUN_ID"].astype(str).tolist()
    portfolio_id = deterministic_portfolio_id(run_ids)

    reference_capital = CAPITAL_PER_RUN_USD * len(run_ids)

    print(f"[INFO] Portfolio ID: {portfolio_id}")
    print(f"[INFO] Reference Capital: {reference_capital}")

    # --------------------------------------------------
    # Load trades
    # --------------------------------------------------

    all_trades = []

    for _, row in selected.iterrows():

        run_id = str(row["RUN_ID"])
        strategy_id = row["STRATEGY"]

        trade_path = PROJECT_ROOT / "backtests" / strategy_id / "raw" / "results_tradelevel.csv"

        if not trade_path.exists():
            fail(f"Trade file missing for run {run_id}")

        df_trades = pd.read_csv(trade_path)
        
        # Rename pnl_usd to pnl for internal logic consistency if needed, or adjust checks
        if "pnl_usd" in df_trades.columns:
            df_trades.rename(columns={"pnl_usd": "pnl"}, inplace=True)

        for col in ["entry_timestamp", "exit_timestamp", "pnl"]:
            if col not in df_trades.columns:
                fail(f"Missing column '{col}' in run {run_id}")

        df_trades["entry_timestamp"] = pd.to_datetime(df_trades["entry_timestamp"])
        df_trades["exit_timestamp"] = pd.to_datetime(df_trades["exit_timestamp"])
        df_trades["strategy_id"] = strategy_id
        df_trades["run_id"] = run_id

        all_trades.append(df_trades)

    trades = pd.concat(all_trades, ignore_index=True)
    trades.sort_values("exit_timestamp", inplace=True)
    trades.reset_index(drop=True, inplace=True)

    # Regime PnL Calculation (Added for parity with portfolio_evaluator.py)
    if "volatility_regime" in trades.columns:
        regime_pnl = trades.groupby("volatility_regime")["pnl"].sum()
        low_pnl = float(regime_pnl.get("low", 0.0))
        normal_pnl = float(regime_pnl.get("normal", 0.0))
        high_pnl = float(regime_pnl.get("high", 0.0))
    else:
        low_pnl = normal_pnl = high_pnl = 0.0

    # --------------------------------------------------
    # Capital model
    # --------------------------------------------------

    trades = compute_equity_curve(trades, reference_capital)

    # Timeframe Metadata (SOP Requirement)
    tf_col = 'timeframe' if 'timeframe' in selected.columns else 'TIMEFRAME'
    if tf_col in selected.columns:
        # Case insensitive handling if needed, but usually standardized
        timeframes = sorted(selected[tf_col].astype(str).unique())
        signal_timeframes_str = "|".join(timeframes)
    else:
        signal_timeframes_str = "UNKNOWN"
    
    evaluation_timeframe = "1D"

    # --------------------------------------------------
    # Concurrency (Updated Port)
    # --------------------------------------------------
    
    # We need equity_series (time-indexed) for DD concurrency.
    # Re-construct it logic similar to Sharpe:
    ts = trades.set_index("exit_timestamp")[["equity_after_trade"]]
    start_ts = pd.DataFrame(
        {"equity_after_trade": [reference_capital]},
        index=[trades["entry_timestamp"].min()] 
    )
    full_ts = pd.concat([start_ts, ts]).sort_index()
    # Resample to daily close (using last known equity) for granularity
    daily_equity_series = full_ts.resample("1D").last().ffill()["equity_after_trade"]

    concurrency_at_entry, capital_deployed_at_entry, concurrency_data = compute_concurrency_profile(trades, daily_equity_series)

    # Pure Assignment
    trades["concurrency_at_entry"] = concurrency_at_entry
    trades["capital_deployed_at_entry"] = capital_deployed_at_entry

    capital_overextension_ratio = (
        concurrency_data['peak_capital_deployed'] / reference_capital
        if reference_capital != 0 else 0.0
    )

    # --------------------------------------------------
    # Drawdown
    # --------------------------------------------------

    max_dd, max_dd_pct, peak_time, trough_time = compute_drawdown(trades)

    return_dd_ratio = (
        trades["pnl"].sum() / abs(max_dd)
        if max_dd != 0 else 0.0
    )

    # --------------------------------------------------
    # Performance (Sharpe / CAGR)
    # --------------------------------------------------

    def compute_performance_metrics(trades, final_equity, reference_capital):
        # CAGR
        days = (trades["exit_timestamp"].max() - trades["exit_timestamp"].min()).days
        if days > 0:
            cagr = (final_equity / reference_capital) ** (365 / days) - 1
        else:
            cagr = 0.0

        # Sharpe (Daily Resampling)
        # Re-use daily_equity_series constructed above? Yes.
        
        daily_rets = daily_equity_series.pct_change().dropna()
        
        if not daily_rets.empty and daily_rets.std() > 0:
            sharpe = (daily_rets.mean() / daily_rets.std()) * (252 ** 0.5)
        else:
            sharpe = 0.0
            
        return cagr, sharpe

    cagr, sharpe = compute_performance_metrics(trades, trades["equity_after_trade"].iloc[-1], reference_capital)

    # --------------------------------------------------
    # Correlation
    # --------------------------------------------------

    avg_pairwise_corr, max_pairwise_corr_stress = compute_correlation(
        trades, peak_time, trough_time
    )

    # --------------------------------------------------
    # Phase 16: Mandatory Research Metrics
    # --------------------------------------------------

    # K-Ratio (Slope of log equity / SE)
    log_eq = np.log(daily_equity_series.values)
    x = np.arange(len(log_eq))
    if len(x) > 2:
        slope, intercept = np.polyfit(x, log_eq, 1)
        predicted = slope * x + intercept
        residuals = log_eq - predicted
        denom = np.sqrt(np.sum((x - x.mean())**2))
        if denom > 0:
             se_slope = np.sqrt(np.sum(residuals**2) / (len(x) - 2)) / denom
        else:
             se_slope = 0.0
        k_ratio = slope / se_slope if se_slope > 0 else 0.0
    else:
        k_ratio = 0.0

    # Win Rate
    total_trades = len(trades)
    if total_trades > 0:
        win_rate = (trades['pnl'] > 0).mean() * 100.0
    else:
        win_rate = 0.0

    # Profit Factor
    gross_profit = trades[trades['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades[trades['pnl'] < 0]['pnl'].sum())
    
    if gross_loss == 0:
        profit_factor = float('inf') if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    # Expectancy
    if total_trades > 0:
        expectancy = trades['pnl'].mean()
    else:
        expectancy = 0.0

    # Exposure % (Mapped)
    exposure_pct = concurrency_data.get('pct_time_deployed', 0.0) * 100.0

    # Equity Stability (Mapped)
    equity_stability_k_ratio = k_ratio

    # --------------------------------------------------
    # Outputs
    # --------------------------------------------------

    output_dir = PORTFOLIO_ROOT / portfolio_id
    output_dir.mkdir(parents=True, exist_ok=True)

    trades.to_csv(output_dir / "portfolio_tradelevel.csv", index=False)

    summary = {
        "portfolio_id": portfolio_id,
        "net_pnl_usd": float(trades["pnl"].sum()),
        "max_dd_usd": float(max_dd),
        "max_dd_pct": float(max_dd_pct),
        "return_dd_ratio": float(return_dd_ratio),
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "avg_concurrent": float(concurrency_data['avg_concurrent']),
        "max_concurrent": int(concurrency_data['max_concurrent']),
        "p95_concurrent": float(concurrency_data['p95_concurrent']),
        "dd_max_concurrent": int(concurrency_data['dd_max_concurrent']),
        "full_load_cluster": bool(concurrency_data['full_load_cluster']),
        "peak_capital_deployed": float(concurrency_data['peak_capital_deployed']),
        "capital_overextension_ratio": float(capital_overextension_ratio),
        "avg_pairwise_corr": float(avg_pairwise_corr),
        "max_pairwise_corr_stress": float(max_pairwise_corr_stress),
        "reference_capital_usd": reference_capital,
        "total_trades": len(trades),
        "portfolio_net_profit_low_vol": low_pnl,
        "portfolio_net_profit_normal_vol": normal_pnl,
        "portfolio_net_profit_high_vol": high_pnl,
        "signal_timeframes": signal_timeframes_str,
        "evaluation_timeframe": evaluation_timeframe,
        # Phase 16 Metrics
        "k_ratio": float(k_ratio),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "expectancy": float(expectancy),
        "exposure_pct": float(exposure_pct),
        "equity_stability_k_ratio": float(equity_stability_k_ratio)
    }

    with open(output_dir / "portfolio_summary.json", "w") as f:
        json.dump(summary, f, indent=4)

    metadata = {
        "portfolio_id": portfolio_id,
        "creation_timestamp_utc": datetime.utcnow().isoformat(),
        "constituent_run_ids": run_ids,
        "reference_capital_usd": reference_capital,
        "capital_per_run_usd": CAPITAL_PER_RUN_USD,
        "capital_model_version": CAPITAL_MODEL_VERSION,
        "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
        "rolling_window_length": ROLLING_WINDOW_LENGTH,
        "schema_version": SCHEMA_VERSION,
        "signal_timeframes": signal_timeframes_str,
        "evaluation_timeframe": evaluation_timeframe
    }

    with open(output_dir / "portfolio_metadata.json", "w") as f:
        json.dump(metadata, f, indent=4)

    # --------------------------------------------------
    # Ledger Append
    # --------------------------------------------------

    # Governance Columns (Authoritative Sequence from portfolio_evaluator.py)
    LEDGER_SCHEMA = [
        "portfolio_id",
        "creation_timestamp",
        "constituent_run_ids",
        "source_strategy",
        "reference_capital_usd",
        "net_pnl_usd",
        "sharpe",
        "max_dd_pct",
        "return_dd_ratio",
        "peak_capital_deployed",
        "capital_overextension_ratio",
        "avg_concurrent",
        "max_concurrent",
        "p95_concurrent",
        "dd_max_concurrent",
        "full_load_cluster",
        "avg_pairwise_corr",
        "max_pairwise_corr_stress",
        "total_trades",
        "portfolio_engine_version",
        "portfolio_net_profit_low_vol",
        "portfolio_net_profit_normal_vol",
        "portfolio_net_profit_high_vol",
        "signal_timeframes",
        "signal_timeframes",
        "evaluation_timeframe",
        # Phase 16 Metrics
        "k_ratio",
        "win_rate",
        "profit_factor",
        "expectancy",
        "exposure_pct",
        "equity_stability_k_ratio"
    ]

    def append_master_portfolio_sheet(record):

        if PORTFOLIO_MASTER_PATH.exists():
            try:
                df_master = pd.read_excel(PORTFOLIO_MASTER_PATH)
            except Exception as e:
                print(f"[WARN] Read failed: {e}. Creating new sheet.")
                df_master = pd.DataFrame(columns=LEDGER_SCHEMA)
        else:
            df_master = pd.DataFrame(columns=LEDGER_SCHEMA)

        # 1. Check Duplicate (Strict Append-Only)
        if "portfolio_id" in df_master.columns:
            pid = record["portfolio_id"]
            if pid in df_master["portfolio_id"].astype(str).values:
                raise ValueError(f"Portfolio ID '{pid}' already exists in ledger. Update rejected (Append-Only).")

        # 2. Append
        new_row = pd.DataFrame([record])
        df_combined = pd.concat([df_master, new_row], ignore_index=True)

        # 3. Ensure Schema Alignment
        # Create missing columns
        for col in LEDGER_SCHEMA:
            if col not in df_combined.columns:
                df_combined[col] = None

        # 4. Reindex to Strict Order
        df_final = df_combined.reindex(columns=LEDGER_SCHEMA)

        try:
            df_final.to_excel(PORTFOLIO_MASTER_PATH, index=False)
            
            # Call Unified Formatter
            cmd = [
                sys.executable, 
                str(PROJECT_ROOT / "tools" / "format_excel_artifact.py"),
                "--file", str(PORTFOLIO_MASTER_PATH),
                "--profile", "portfolio"
            ]
            subprocess.run(cmd, check=True)

            print("[SUCCESS] Master Portfolio Sheet updated and styled.")
            
        except PermissionError:
            fail(f"Permission denied: {PORTFOLIO_MASTER_PATH}. Please close the file.")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Formatting failed: {e}")

    record = {
        "portfolio_id": portfolio_id,
        "creation_timestamp": metadata["creation_timestamp_utc"],
        "constituent_run_ids": "|".join(run_ids),
        "source_strategy": "AGGREGATED",
        "reference_capital_usd": reference_capital,
        "net_pnl_usd": summary["net_pnl_usd"],
        "sharpe": summary["sharpe"],
        "max_dd_pct": summary["max_dd_pct"],
        "return_dd_ratio": summary["return_dd_ratio"],
        "peak_capital_deployed": summary["peak_capital_deployed"],
        "capital_overextension_ratio": summary["capital_overextension_ratio"],
        "avg_concurrent": summary["avg_concurrent"],
        "max_concurrent": summary["max_concurrent"],
        "p95_concurrent": summary["p95_concurrent"],
        "dd_max_concurrent": summary["dd_max_concurrent"],
        "full_load_cluster": summary["full_load_cluster"],
        "avg_pairwise_corr": summary["avg_pairwise_corr"],
        "max_pairwise_corr_stress": summary["max_pairwise_corr_stress"],
        "total_trades": summary["total_trades"],
        "portfolio_engine_version": PORTFOLIO_ENGINE_VERSION,
        "portfolio_net_profit_low_vol": summary["portfolio_net_profit_low_vol"],
        "portfolio_net_profit_normal_vol": summary["portfolio_net_profit_normal_vol"],
        "portfolio_net_profit_high_vol": summary["portfolio_net_profit_high_vol"],
        "signal_timeframes": summary["signal_timeframes"],
        "signal_timeframes": summary["signal_timeframes"],
        "evaluation_timeframe": summary["evaluation_timeframe"],
        # Phase 16 Metrics
        "k_ratio": summary["k_ratio"],
        "win_rate": summary["win_rate"],
        "profit_factor": summary["profit_factor"],
        "expectancy": summary["expectancy"],
        "exposure_pct": summary["exposure_pct"],
        "equity_stability_k_ratio": summary["equity_stability_k_ratio"]
    }

    append_master_portfolio_sheet(record)

    print("[SUCCESS] Portfolio v3.0 construction complete.")


if __name__ == "__main__":
    main()
