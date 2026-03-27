import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone
import json
from tools.pipeline_utils import get_engine_version

def generate_backtest_report(directive_name: str, backtest_root: Path):
    """
    Generates a deterministic markdown report from raw CSV artifacts without altering state.
    Provides run-level metrics (Stage-5A).
    The generated report is saved inside each matching symbol directory within the backtest namespace.
    """
    # The report will be saved inside each symbol directory later in the function.
    pass
    
    symbol_dirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith(f"{directive_name}_")]
    
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_gross_profit = 0.0
    portfolio_gross_loss = 0.0
    
    symbols_data = []
    vol_data = []
    trend_data = []
    all_trades_dfs = []
    
    engine_ver = get_engine_version()
    start_date = "YYYY-MM-DD"
    end_date = "YYYY-MM-DD"
    timeframe = "Unknown"
    
    global_has_stage3 = False
    
    for s_dir in symbol_dirs:
        symbol = s_dir.name.replace(f"{directive_name}_", "")
        raw_dir = s_dir / "raw"
        if not raw_dir.exists():
            continue
            
        std_csv = raw_dir / "results_standard.csv"
        risk_csv = raw_dir / "results_risk.csv"
        trade_csv = raw_dir / "results_tradelevel.csv"
        
        has_stage3 = std_csv.exists() and risk_csv.exists()
        has_stage1 = trade_csv.exists()

        if not has_stage1:
            continue
            
        meta_path = s_dir / "metadata" / "run_metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    if meta.get("timeframe"):
                        timeframe = meta.get("timeframe")
            except:
                pass
            
        # Compute avg_r, vol edges, and trend edges from results_tradelevel.csv
        avg_r = 0.0
        h_vol = 0.0; n_vol = 0.0; l_vol = 0.0
        s_up = 0.0; w_up = 0.0; neu = 0.0; w_dn = 0.0; s_dn = 0.0
        
        tdf = None
        if has_stage1:
            tdf = pd.read_csv(trade_csv)
            if len(tdf) > 0:
                # Defensively map legacy integer regimes to strings for backward compatibility
                if 'volatility_regime' in tdf.columns:
                    tdf['volatility_regime'] = tdf['volatility_regime'].replace({
                        -1: 'low', 0: 'normal', 1: 'high',
                        '-1': 'low', '0': 'normal', '1': 'high',
                        '-1.0': 'low', '0.0': 'normal', '1.0': 'high'
                    })
                
                all_trades_dfs.append(tdf)
                
                if 'r_multiple' in tdf.columns:
                    avg_r = float(tdf['r_multiple'].mean())
                
                if 'volatility_regime' in tdf.columns and 'pnl_usd' in tdf.columns:
                    tdf['volatility_regime_clean'] = tdf['volatility_regime'].astype(str).str.lower().str.strip()
                    vol_groups = tdf.groupby('volatility_regime_clean')['pnl_usd'].sum()
                    h_vol = float(vol_groups.get('high', 0.0))
                    n_vol = float(vol_groups.get('normal', 0.0))
                    l_vol = float(vol_groups.get('low', 0.0))
                
                if 'trend_label' in tdf.columns and 'pnl_usd' in tdf.columns:
                    tdf['trend_label_clean'] = tdf['trend_label'].astype(str).str.lower().str.strip()
                    trend_groups = tdf.groupby('trend_label_clean')['pnl_usd'].sum()
                    s_up = float(trend_groups.get('strong_up', 0.0))
                    w_up = float(trend_groups.get('weak_up', 0.0))
                    neu = float(trend_groups.get('neutral', 0.0))
                    w_dn = float(trend_groups.get('weak_down', 0.0))
                    s_dn = float(trend_groups.get('strong_down', 0.0))
                    
        if has_stage3:
            std_df = pd.read_csv(std_csv)
            risk_df = pd.read_csv(risk_csv)
            if len(std_df) == 0 or len(risk_df) == 0:
                has_stage3 = False
            else:
                global_has_stage3 = True
                std_row = std_df.iloc[-1]
                risk_row = risk_df.iloc[-1]
                
                # Explicit Mapping from results_standard.csv
                trades = int(std_row.get("total_trades", std_row.get("trade_count", 0)))
                net_pnl = float(std_row.get("net_profit", std_row.get("net_pnl_usd", 0.0)))
                win_rate = float(std_row.get("win_rate", 0.0))
                pf = float(std_row.get("profit_factor", 0.0))
                
                # We need these to compute a naive aggregate portfolio PF
                gross_profit = float(std_row.get("gross_profit", 0.0))
                gross_loss = float(std_row.get("gross_loss", 0.0))
                portfolio_gross_profit += gross_profit
                portfolio_gross_loss += abs(gross_loss)
                
                # Explicit Mapping from results_risk.csv
                max_dd = float(risk_row.get("max_drawdown_pct", 0.0))
                ret_dd = float(risk_row.get("return_dd_ratio", 0.0))
                
                symbols_data.append({
                    "Symbol": symbol,
                    "Trades": trades,
                    "Net PnL": net_pnl,
                    "PF": pf,
                    "Max DD": max_dd,
                    "Return/DD": ret_dd,
                    "Win %": win_rate * 100, # Converting fractional to percentage
                    "Avg R": avg_r
                })
                
                portfolio_trades += trades
                portfolio_pnl += net_pnl
                
        if not has_stage3:
            trades = len(tdf) if tdf is not None else 0
            net_pnl = float(tdf['pnl_usd'].sum()) if tdf is not None and 'pnl_usd' in tdf.columns else 0.0
            
            symbols_data.append({
                "Symbol": symbol,
                "Trades": trades,
                "Net PnL": net_pnl,
                "PF": None,
                "Max DD": None,
                "Return/DD": None,
                "Win %": None,
                "Avg R": avg_r
            })
            
            portfolio_trades += trades
            portfolio_pnl += net_pnl
            
        vol_data.append({"Symbol": symbol, "High": h_vol, "Normal": n_vol, "Low": l_vol})
        trend_data.append({"Symbol": symbol, "StrongUp": s_up, "WeakUp": w_up, "Neutral": neu, "WeakDn": w_dn, "StrongDn": s_dn})
        
        if has_stage1 and start_date == "YYYY-MM-DD":
            if tdf is not None and len(tdf) > 0 and 'entry_timestamp' in tdf.columns:
                start_date = str(tdf['entry_timestamp'].min())[:10]
                end_date = str(tdf['exit_timestamp'].max())[:10]

    port_pf = (portfolio_gross_profit / portfolio_gross_loss) if portfolio_gross_loss != 0 else portfolio_gross_profit
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    valid_symbol_dirs = [
        s_dir for s_dir in symbol_dirs
        if (s_dir / "raw" / "results_tradelevel.csv").exists()
    ]
    
    stage3_counts = sum(
        (s_dir / "raw" / "results_standard.csv").exists() and
        (s_dir / "raw" / "results_risk.csv").exists()
        for s_dir in valid_symbol_dirs
    )
    total_symbols = len(valid_symbol_dirs)
    
    md = [
        f"# Report Summary — {directive_name}\n",
        f"Engine Version: {engine_ver}",
        f"Timeframe: {timeframe}",
        f"Date Range: {start_date} → {end_date}",
        f"Symbols Evaluated: {total_symbols} / {len(symbol_dirs)}",
        f"Generated: {now_utc}\n",
        "---\n"
    ]
    
    if stage3_counts == 0:
        md.insert(0, "## ⚠️ Stage-1 Only Report\n")
        md.insert(1, "Metrics limited to trade-level data. No risk metrics computed.\n\n")
        port_pf_str = "N/A"
    elif stage3_counts < total_symbols:
        md.insert(0, "## ⚠️ Partial Report (Mixed Stage-1 / Stage-3)\n")
        md.insert(1, "Some symbols lack full risk metrics. Portfolio metrics limited.\n\n")
        port_pf_str = "N/A"
    else:
        port_pf_str = f"{port_pf:.2f}"

    md.extend([
        "## Portfolio Summary\n",
        "| Total Trades | Net PnL | Profit Factor | Max DD | Return/DD |",
        "|--------------|---------|---------------|--------|------------|",
        f"| {portfolio_trades} | ${portfolio_pnl:.2f} | {port_pf_str} | N/A | N/A |\n",
        "---\n",
        "## Symbol Summary\n",
        "| Symbol | Trades | Net PnL | PF | Max DD | Return/DD | Win % | Avg R |",
        "|--------|--------|---------|----|--------|-----------|-------|-------|"
    ])
    for row in symbols_data:
        if row['PF'] is not None:
            pf_str = f"{row['PF']:.2f} ✔ (S3)"
            max_dd_str = f"{row['Max DD']:.2f}%"
            ret_dd_str = f"{row['Return/DD']:.2f}"
            win_str = f"{row['Win %']:.1f}%"
        else:
            pf_str = "N/A (S1)"
            max_dd_str = "N/A (S1)"
            ret_dd_str = "N/A (S1)"
            win_str = "N/A (S1)"
            
        md.append(f"| {row['Symbol']} | {row['Trades']} | ${row['Net PnL']:.2f} | {pf_str} | {max_dd_str} | {ret_dd_str} | {win_str} | {row['Avg R']:.2f} |")
    md.append("\n---\n")
    
    md.append("## Volatility Edge\n")
    md.append("| Symbol | High | Normal | Low |")
    md.append("|--------|------|--------|-----|")
    for row in vol_data:
        md.append(f"| {row['Symbol']} | ${row['High']:.2f} | ${row['Normal']:.2f} | ${row['Low']:.2f} |")
    md.append("\n---\n")
    
    md.append("## Trend Edge\n")
    md.append("| Symbol | StrongUp | WeakUp | Neutral | WeakDn | StrongDn |")
    md.append("|--------|----------|--------|---------|--------|----------|")
    for row in trend_data:
        md.append(f"| {row['Symbol']} | ${row['StrongUp']:.2f} | ${row['WeakUp']:.2f} | ${row['Neutral']:.2f} | ${row['WeakDn']:.2f} | ${row['StrongDn']:.2f} |")
    
    md.append("\n---\n")
    md.append("## Edge Decomposition (Core)\n")
    
    if all_trades_dfs:
        all_trades_df = pd.concat(all_trades_dfs, ignore_index=True)
        
        def build_cross_tab(df, target_col, col_keys):
            if target_col not in df.columns or 'direction' not in df.columns or 'pnl_usd' not in df.columns:
                return ["| Data Unavailable |"]
            
            df_c = df.copy()
            df_c[target_col] = df_c[target_col].astype(str).str.lower().str.strip()
            
            # Map direction safely and drop nulls to avoid silent misclassification
            df_c['dir_label'] = pd.to_numeric(df_c['direction'], errors='coerce')
            if df_c['dir_label'].isnull().any():
                print(f"[WARN] Dropping null direction mappings in cross-tab for {target_col}")
            df_c = df_c[df_c['dir_label'].notnull()]
            df_c['dir_label'] = df_c['dir_label'].apply(lambda x: 'Long' if x > 0 else 'Short')
            
            headers = ["Direction"] + list(col_keys.keys())
            lines = ["| " + " | ".join(headers) + " |", "|-" + "-|-".join(["-" * len(h) for h in headers]) + "-|"]
            
            for dir_val in ['Long', 'Short']:
                dir_df = df_c[df_c['dir_label'] == dir_val]
                row_vals = [dir_val]
                for nice_name, raw_val in col_keys.items():
                    cell_df = dir_df[dir_df[target_col] == raw_val]
                    if len(cell_df) == 0:
                        row_vals.append("-")
                        continue
                    trades = len(cell_df)
                    net_pnl = cell_df['pnl_usd'].sum()
                    wins = sum((cell_df['pnl_usd'] > 0).astype(int))
                    wr = (wins / trades) * 100
                    g_prof = float(cell_df[cell_df['pnl_usd'] > 0]['pnl_usd'].sum())
                    g_loss = abs(float(cell_df[cell_df['pnl_usd'] < 0]['pnl_usd'].sum()))
                    if g_loss == 0:
                        pf = float('inf') if g_prof > 0 else 0.0
                    else:
                        pf = g_prof / g_loss
                    
                    flag = ""
                    if trades >= 20 and pf >= 1.5:
                         flag = "✔ "
                    elif trades >= 20 and pf <= 0.9:
                         flag = "✖ "
                    
                    pf_str = "∞" if pf == float('inf') else f"{pf:.2f}"
                    row_vals.append(f"{flag}T:{trades} P:${net_pnl:.2f} W:{wr:.1f}% PF:{pf_str}")
                lines.append("| " + " | ".join(row_vals) + " |")
            return lines
        
        md.append("### A) Direction &times; Volatility\n")
        vol_cols = {"High": "high", "Normal": "normal", "Low": "low"}
        md.extend(build_cross_tab(all_trades_df, "volatility_regime", vol_cols))
        md.append("\n")
        
        md.append("### B) Direction &times; Trend\n")
        trend_cols = {"Strong Up": "strong_up", "Weak Up": "weak_up", "Neutral": "neutral", "Weak Down": "weak_down", "Strong Down": "strong_down"}
        md.extend(build_cross_tab(all_trades_df, "trend_label", trend_cols))
        md.append("\n")
    else:
        md.append("> No trade-level data available for Edge Decomposition.\n")
        
    md_content = "\n".join(md)
    for s_dir in symbol_dirs:
        out_path = s_dir / f"REPORT_{directive_name}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[REPORT] Successfully generated: {out_path}")

    print("\n[STAGE-1 COMPLETE]")
    print("Edge Decomposition Report Generated.")
    print("Next action required:")
    print("1) Reject")
    print("2) Create filtered variant (P01/P02)")
    print("3) Run full pipeline (Stage-2+)")
    print("Awaiting user decision...\n")

def generate_strategy_portfolio_report(strategy_name: str, root_dir: Path):
    """
    Generates a deterministic markdown report at the strategy level (Stage-5B).
    Reads ONLY from portfolio evaluation json artifacts.
    """
    # Source data stays in the strategy's portfolio_evaluation directory (read-only)
    source_dir = root_dir / "strategies" / strategy_name / "portfolio_evaluation"
    if not source_dir.exists():
        print(f"[REPORT-WARN] Portfolio evaluation directory missing for {strategy_name}.")
        return

    # Output goes directly to the strategy's root folder
    report_summary_dir = root_dir / "strategies" / strategy_name
    report_summary_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_summary_dir / f"PORTFOLIO_{strategy_name}.md"

    summary_json = source_dir / "portfolio_summary.json"
    metadata_json = source_dir / "portfolio_metadata.json"
    
    if not summary_json.exists():
        print(f"[REPORT-WARN] portfolio_summary.json missing for {strategy_name}.")
        return
        
    with open(summary_json, "r") as f:
        summary = json.load(f)
        
    # Extract date range from portfolio_summary.json data_range field
    start_date = "YYYY-MM-DD"
    end_date = "YYYY-MM-DD"
    data_range = summary.get("data_range", "")
    if " to " in data_range:
        parts = data_range.split(" to ")
        start_date = parts[0].strip()
        end_date = parts[1].strip()
    
    # Fallback: read metadata if dates are still unresolved
    constituent_runs = []
    evaluated_assets = []
    evaluation_timeframe = summary.get("evaluation_timeframe", "UNKNOWN")
    if metadata_json.exists():
        with open(metadata_json, "r") as f:
            meta = json.load(f)
            if start_date == "YYYY-MM-DD":
                start_date = meta.get("start_date", start_date)
                end_date = meta.get("end_date", end_date)
            constituent_runs = meta.get("constituent_run_ids", [])
            evaluated_assets = meta.get("evaluated_assets", [])
            if "evaluation_timeframe" in meta:
                evaluation_timeframe = meta.get("evaluation_timeframe", evaluation_timeframe)
            
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Explicit key mapping from portfolio_summary.json
    trades = summary.get("total_trades", 0)
    net_pnl = summary.get("net_pnl_usd", 0.0)
    pf = summary.get("profit_factor", 0.0)
    max_dd_pct = summary.get("max_dd_pct", 0.0) * 100  # Convert decimal to percentage
    ret_dd = summary.get("return_dd_ratio", 0.0)
    sharpe = summary.get("sharpe", 0.0)
    sortino = summary.get("sortino", 0.0)
    cagr = summary.get("cagr_pct", 0.0) * 100  # Convert decimal to percentage
    win_rate = summary.get("win_rate", 0.0)
    expectancy = summary.get("expectancy", 0.0)
    avg_corr = summary.get("avg_correlation", 0.0)
    
    md = [
        f"# Strategy Portfolio Report — {strategy_name}\n",
        f"Date Range: {start_date} → {end_date}",
        f"Execution Timeframe: {evaluation_timeframe}",
        f"Generated: {now_utc}\n",
        "---\n",
        "## Base Model & Assumptions\n",
        "> **Note:** The metrics calculated in this report are based on the **raw (unscaled) runs prior to the application of the capital wrapper**. ",
        "> They represent the pure structural edge of the combined trades without dynamic position sizing applied.\n",
        "---\n",
        "## Portfolio Composition\n",
        "**Constituent Runs:**"
    ]
    
    if constituent_runs:
        for run_id in constituent_runs:
            md.append(f"- `{run_id}`")
    else:
        md.append("- No constituent runs recorded.")
        
    md.append("\n**Evaluated Assets:**")
    if evaluated_assets:
        for asset in evaluated_assets:
            md.append(f"- `{asset}`")
    else:
        md.append("- No assets recorded.")
        
    md.extend([
        "\n---\n",
        "## Portfolio Metrics\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Trades | {trades} |",
        f"| Net PnL | ${net_pnl:.2f} |",
        f"| Win Rate | {win_rate:.1f}% |",
        f"| Profit Factor | {pf:.2f} |",
        f"| Expectancy | ${expectancy:.2f} |",
        f"| Max Drawdown | {max_dd_pct:.2f}% |",
        f"| Return/DD Ratio | {ret_dd:.2f} |",
        f"| CAGR | {cagr:.2f}% |",
        f"| Sharpe Ratio | {sharpe:.2f} |",
        f"| Sortino Ratio | {sortino:.2f} |",
        f"| Avg Correlation | {avg_corr:.4f} |"
    ])
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[REPORT] Successfully generated strategy portfolio report: {report_path}")

