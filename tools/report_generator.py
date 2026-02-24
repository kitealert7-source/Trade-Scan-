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
    All reports are saved to a centralized reports_summary/ folder.
    """
    report_dir = backtest_root.parent / "reports_summary"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"REPORT_{directive_name}.md"
    
    symbol_dirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith(f"{directive_name}_")]
    
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_gross_profit = 0.0
    portfolio_gross_loss = 0.0
    
    symbols_data = []
    vol_data = []
    trend_data = []
    
    engine_ver = get_engine_version()
    start_date = "YYYY-MM-DD"
    end_date = "YYYY-MM-DD"
    
    for s_dir in symbol_dirs:
        symbol = s_dir.name.replace(f"{directive_name}_", "")
        raw_dir = s_dir / "raw"
        if not raw_dir.exists():
            continue
            
        std_csv = raw_dir / "results_standard.csv"
        risk_csv = raw_dir / "results_risk.csv"
        trade_csv = raw_dir / "results_tradelevel.csv"
        
        if not std_csv.exists() or not risk_csv.exists():
            continue
            
        std_df = pd.read_csv(std_csv)
        if len(std_df) == 0:
            continue
        std_row = std_df.iloc[-1]
        
        risk_df = pd.read_csv(risk_csv)
        if len(risk_df) == 0:
            continue
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
        
        # Compute avg_r, vol edges, and trend edges from results_tradelevel.csv
        avg_r = 0.0
        h_vol = 0.0; n_vol = 0.0; l_vol = 0.0
        s_up = 0.0; w_up = 0.0; neu = 0.0; w_dn = 0.0; s_dn = 0.0
        
        if trade_csv.exists():
            tdf = pd.read_csv(trade_csv)
            if len(tdf) > 0:
                if 'r_multiple' in tdf.columns:
                    avg_r = float(tdf['r_multiple'].mean())
                
                if 'volatility_regime' in tdf.columns and 'pnl_usd' in tdf.columns:
                    vol_groups = tdf.groupby('volatility_regime')['pnl_usd'].sum()
                    h_vol = float(vol_groups.get('high', 0.0))
                    n_vol = float(vol_groups.get('normal', 0.0))
                    l_vol = float(vol_groups.get('low', 0.0))
                
                if 'trend_label' in tdf.columns and 'pnl_usd' in tdf.columns:
                    trend_groups = tdf.groupby('trend_label')['pnl_usd'].sum()
                    s_up = float(trend_groups.get('strong_up', 0.0))
                    w_up = float(trend_groups.get('weak_up', 0.0))
                    neu = float(trend_groups.get('neutral', 0.0))
                    w_dn = float(trend_groups.get('weak_down', 0.0))
                    s_dn = float(trend_groups.get('strong_down', 0.0))
                    
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
        
        vol_data.append({"Symbol": symbol, "High": h_vol, "Normal": n_vol, "Low": l_vol})
        trend_data.append({"Symbol": symbol, "StrongUp": s_up, "WeakUp": w_up, "Neutral": neu, "WeakDn": w_dn, "StrongDn": s_dn})
        
        portfolio_trades += trades
        portfolio_pnl += net_pnl
        
        if trade_csv.exists() and start_date == "YYYY-MM-DD":
            tdf = pd.read_csv(trade_csv)
            if len(tdf) > 0 and 'entry_timestamp' in tdf.columns:
                start_date = str(tdf['entry_timestamp'].min())[:10]
                end_date = str(tdf['exit_timestamp'].max())[:10]

    port_pf = (portfolio_gross_profit / portfolio_gross_loss) if portfolio_gross_loss != 0 else portfolio_gross_profit
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    md = [
        f"# Report Summary — {directive_name}\n",
        f"Engine Version: {engine_ver}",
        f"Timeframe: 4h",
        f"Date Range: {start_date} → {end_date}",
        f"Generated: {now_utc}\n",
        "---\n",
        "## Portfolio Summary\n",
        "| Total Trades | Net PnL | Profit Factor | Max DD | Return/DD |",
        "|--------------|---------|---------------|--------|------------|",
        f"| {portfolio_trades} | ${portfolio_pnl:.2f} | {port_pf:.2f} | N/A | N/A |\n",
        "---\n",
        "## Symbol Summary\n",
        "| Symbol | Trades | Net PnL | PF | Max DD | Return/DD | Win % | Avg R |",
        "|--------|--------|---------|----|--------|-----------|-------|-------|"
    ]
    for row in symbols_data:
        md.append(f"| {row['Symbol']} | {row['Trades']} | ${row['Net PnL']:.2f} | {row['PF']:.2f} | {row['Max DD']:.2f}% | {row['Return/DD']:.2f} | {row['Win %']:.1f}% | {row['Avg R']:.2f} |")
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
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[REPORT] Successfully generated: {report_path}")

def generate_strategy_portfolio_report(strategy_name: str, root_dir: Path):
    """
    Generates a deterministic markdown report at the strategy level (Stage-5B).
    Reads ONLY from portfolio evaluation json artifacts.
    """
    # Output goes to centralized reports_summary/ folder
    report_summary_dir = root_dir / "reports_summary"
    report_summary_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_summary_dir / f"PORTFOLIO_{strategy_name}.md"
    
    # Source data stays in the strategy's portfolio_evaluation directory (read-only)
    source_dir = root_dir / "strategies" / strategy_name / "portfolio_evaluation"
    if not source_dir.exists():
        print(f"[REPORT-WARN] Portfolio evaluation directory missing for {strategy_name}.")
        return
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
    if start_date == "YYYY-MM-DD" and metadata_json.exists():
        with open(metadata_json, "r") as f:
            meta = json.load(f)
            start_date = meta.get("start_date", start_date)
            end_date = meta.get("end_date", end_date)
            
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
        f"Generated: {now_utc}\n",
        "---\n",
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
    ]
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[REPORT] Successfully generated strategy portfolio report: {report_path}")
