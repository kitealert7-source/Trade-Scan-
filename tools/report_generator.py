import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone
import json
from tools.pipeline_utils import get_engine_version

def _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf):
    """Auto-derive 3-5 mechanical insights from existing report data. No narrative."""
    insights = []
    if not all_trades_dfs:
        return ["Insufficient data for insights."]

    df = pd.concat(all_trades_dfs, ignore_index=True)
    if len(df) == 0:
        return ["Insufficient data for insights."]

    # --- 1. Strong / Weak cells from Direction x Volatility x Trend ---
    strong_cells = []
    weak_cells = []

    for target_col, col_map in [
        ("volatility_regime", {"High": "high", "Normal": "normal", "Low": "low"}),
        ("trend_label", {"StrongUp": "strong_up", "WeakUp": "weak_up",
                         "Neutral": "neutral", "WeakDn": "weak_down", "StrongDn": "strong_down"}),
    ]:
        if target_col not in df.columns:
            continue
        df_c = df.copy()
        df_c[target_col] = df_c[target_col].astype(str).str.lower().str.strip()
        for dir_val, dir_label in [(1, "Long"), (-1, "Short")]:
            dir_df = df_c[df_c["direction"] == dir_val]
            for nice, raw in col_map.items():
                cell = dir_df[dir_df[target_col] == raw]
                if len(cell) < 5:
                    continue
                gp = float(cell[cell["pnl_usd"] > 0]["pnl_usd"].sum())
                gl = abs(float(cell[cell["pnl_usd"] < 0]["pnl_usd"].sum()))
                pf = (gp / gl) if gl > 0 else (gp if gp > 0 else 0.0)
                pnl = cell["pnl_usd"].sum()
                label = f"{dir_label} x {nice}"
                if pf >= 2.0 and len(cell) >= 10:
                    strong_cells.append((pf, pnl, len(cell), label))
                elif pf <= 1.0 and len(cell) >= 10:
                    weak_cells.append((pf, pnl, len(cell), label))

    # Sort: strongest first, weakest first
    strong_cells.sort(key=lambda x: -x[0])
    weak_cells.sort(key=lambda x: x[0])

    if strong_cells:
        top = strong_cells[:2]
        parts = [f"{c[3]} (PF {c[0]:.2f}, {c[2]}T)" for c in top]
        insights.append(f"Strong edge: {', '.join(parts)}")

    if weak_cells:
        w = weak_cells[0]
        action = "candidate for exclusion" if w[1] < 0 else "drag on portfolio"
        insights.append(f"Weak cell: {w[3]} (PF {w[0]:.2f}, {w[2]}T, ${w[1]:.0f}) — {action}")

    # --- 2. Direction asymmetry ---
    if "direction" in df.columns:
        longs = df[df["direction"] == 1]
        shorts = df[df["direction"] == -1]
        if len(longs) >= 5 and len(shorts) >= 5:
            l_gp = float(longs[longs["pnl_usd"] > 0]["pnl_usd"].sum())
            l_gl = abs(float(longs[longs["pnl_usd"] < 0]["pnl_usd"].sum()))
            s_gp = float(shorts[shorts["pnl_usd"] > 0]["pnl_usd"].sum())
            s_gl = abs(float(shorts[shorts["pnl_usd"] < 0]["pnl_usd"].sum()))
            l_pf = (l_gp / l_gl) if l_gl > 0 else l_gp
            s_pf = (s_gp / s_gl) if s_gl > 0 else s_gp
            ratio = max(l_pf, s_pf) / min(l_pf, s_pf) if min(l_pf, s_pf) > 0 else 99
            if ratio >= 1.5:
                stronger = "Long" if l_pf > s_pf else "Short"
                weaker = "Short" if stronger == "Long" else "Long"
                insights.append(
                    f"Direction bias: {stronger} PF {max(l_pf, s_pf):.2f} vs {weaker} PF {min(l_pf, s_pf):.2f} — asymmetric edge"
                )

    # --- 3. Exit structure ---
    if "bars_held" in df.columns and "r_multiple" in df.columns:
        max_bars = int(df["bars_held"].max())
        time_exits = df[df["bars_held"] >= max_bars]
        sl_exits = df[(df["bars_held"] < max_bars) & (df["r_multiple"] <= -0.9)]
        time_pct = len(time_exits) / len(df) * 100
        sl_pct = len(sl_exits) / len(df) * 100
        avg_bars = df["bars_held"].mean()

        if time_pct >= 90:
            insights.append(
                f"Exit dependency: {time_pct:.0f}% TIME exits, avg {avg_bars:.1f} bars — edge is short-lived"
            )
        if sl_pct <= 3 and len(df) >= 50:
            insights.append(
                f"Low SL rate ({sl_pct:.1f}%) — risk distribution compressed, DD may understate tail exposure"
            )
        elif sl_pct >= 20:
            insights.append(
                f"High SL rate ({sl_pct:.1f}%) — {len(sl_exits)} stop-outs, check entry timing or stop distance"
            )

    # --- 4. MFE giveback ---
    if "mfe_r" in df.columns and "r_multiple" in df.columns and "bars_held" in df.columns:
        max_bars = int(df["bars_held"].max())
        time_exits = df[df["bars_held"] >= max_bars]
        if len(time_exits) > 0:
            high_mfe = time_exits[time_exits["mfe_r"] >= 1.0]
            if len(high_mfe) >= 3:
                avg_giveback = (high_mfe["mfe_r"] - high_mfe["r_multiple"]).mean()
                insights.append(
                    f"MFE waste: {len(high_mfe)} trades reached >= 1.0R MFE, gave back {avg_giveback:+.2f}R avg — TP or trail opportunity"
                )

    # --- 5. Trade density ---
    if portfolio_trades > 0 and "entry_timestamp" in df.columns:
        first = pd.to_datetime(df["entry_timestamp"]).min()
        last = pd.to_datetime(df["exit_timestamp"]).max()
        days = (last - first).days
        if days > 0:
            trades_per_month = portfolio_trades / (days / 30.44)
            if trades_per_month < 3:
                insights.append(
                    f"Low density: {trades_per_month:.1f} trades/month — statistical significance requires longer test window"
                )

    # Fallback if nothing triggered
    if not insights:
        if port_pf >= 1.5:
            insights.append("No structural issues detected — strategy passes all mechanical checks")
        else:
            insights.append(f"Marginal edge (PF {port_pf:.2f}) — decompose by direction and regime before iterating")

    return insights


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

    # Aggregate risk metrics across symbols for portfolio-level Key Metrics
    portfolio_max_dd_usd = 0.0
    portfolio_max_dd_pct = 0.0
    portfolio_ret_dd = 0.0
    portfolio_sharpe = 0.0
    portfolio_sortino = 0.0
    portfolio_k_ratio = 0.0
    portfolio_sqn = 0.0
    portfolio_win_rate = 0.0
    portfolio_avg_r = 0.0

    symbols_data = []
    risk_data_list = []  # Collect per-symbol risk rows for aggregation
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
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if meta.get("timeframe"):
                        timeframe = meta.get("timeframe")
            except Exception:
                pass

        # Compute avg_r, vol edges, and trend edges from results_tradelevel.csv
        avg_r = 0.0
        h_vol = 0.0; n_vol = 0.0; l_vol = 0.0
        h_vol_t = 0; n_vol_t = 0; l_vol_t = 0
        s_up = 0.0; w_up = 0.0; neu = 0.0; w_dn = 0.0; s_dn = 0.0
        s_up_t = 0; w_up_t = 0; neu_t = 0; w_dn_t = 0; s_dn_t = 0

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
                    vol_counts = tdf.groupby('volatility_regime_clean')['pnl_usd'].count()
                    h_vol = float(vol_groups.get('high', 0.0))
                    n_vol = float(vol_groups.get('normal', 0.0))
                    l_vol = float(vol_groups.get('low', 0.0))
                    h_vol_t = int(vol_counts.get('high', 0))
                    n_vol_t = int(vol_counts.get('normal', 0))
                    l_vol_t = int(vol_counts.get('low', 0))

                if 'trend_label' in tdf.columns and 'pnl_usd' in tdf.columns:
                    tdf['trend_label_clean'] = tdf['trend_label'].astype(str).str.lower().str.strip()
                    trend_groups = tdf.groupby('trend_label_clean')['pnl_usd'].sum()
                    trend_counts = tdf.groupby('trend_label_clean')['pnl_usd'].count()
                    s_up = float(trend_groups.get('strong_up', 0.0))
                    w_up = float(trend_groups.get('weak_up', 0.0))
                    neu = float(trend_groups.get('neutral', 0.0))
                    w_dn = float(trend_groups.get('weak_down', 0.0))
                    s_dn = float(trend_groups.get('strong_down', 0.0))
                    s_up_t = int(trend_counts.get('strong_up', 0))
                    w_up_t = int(trend_counts.get('weak_up', 0))
                    neu_t = int(trend_counts.get('neutral', 0))
                    w_dn_t = int(trend_counts.get('weak_down', 0))
                    s_dn_t = int(trend_counts.get('strong_down', 0))

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

                # Collect risk metrics for portfolio-level aggregation
                risk_data_list.append({
                    "trades": trades,
                    "max_dd_usd": float(risk_row.get("max_drawdown_usd", 0.0)),
                    "max_dd_pct": max_dd,
                    "return_dd": ret_dd,
                    "sharpe": float(risk_row.get("sharpe_ratio", 0.0)),
                    "sortino": float(risk_row.get("sortino_ratio", 0.0)),
                    "k_ratio": float(risk_row.get("k_ratio", 0.0)),
                    "sqn": float(risk_row.get("sqn", 0.0)),
                    "win_rate": win_rate,
                })

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

        vol_data.append({"Symbol": symbol, "High": h_vol, "Normal": n_vol, "Low": l_vol, "High_T": h_vol_t, "Normal_T": n_vol_t, "Low_T": l_vol_t})
        trend_data.append({"Symbol": symbol, "StrongUp": s_up, "WeakUp": w_up, "Neutral": neu, "WeakDn": w_dn, "StrongDn": s_dn, "StrongUp_T": s_up_t, "WeakUp_T": w_up_t, "Neutral_T": neu_t, "WeakDn_T": w_dn_t, "StrongDn_T": s_dn_t})

        if has_stage1 and start_date == "YYYY-MM-DD":
            if tdf is not None and len(tdf) > 0 and 'entry_timestamp' in tdf.columns:
                start_date = str(tdf['entry_timestamp'].min())[:10]
                end_date = str(tdf['exit_timestamp'].max())[:10]

    port_pf = (portfolio_gross_profit / portfolio_gross_loss) if portfolio_gross_loss != 0 else portfolio_gross_profit
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Aggregate portfolio-level risk metrics
    # For single-symbol: propagate directly. For multi-symbol: trade-weighted average
    # where appropriate, worst-case for drawdown.
    if risk_data_list:
        total_risk_trades = sum(r["trades"] for r in risk_data_list)
        if total_risk_trades > 0:
            # Drawdown: use worst single-symbol DD (conservative; true portfolio DD
            # requires combined equity curve which is computed downstream in capital_wrapper)
            portfolio_max_dd_usd = max(r["max_dd_usd"] for r in risk_data_list)
            portfolio_max_dd_pct = max(r["max_dd_pct"] for r in risk_data_list)
            portfolio_ret_dd = (portfolio_pnl / portfolio_max_dd_usd) if portfolio_max_dd_usd > 0 else 0.0
            # Trade-weighted averages for ratio metrics
            portfolio_sharpe = sum(r["sharpe"] * r["trades"] for r in risk_data_list) / total_risk_trades
            portfolio_sortino = sum(r["sortino"] * r["trades"] for r in risk_data_list) / total_risk_trades
            portfolio_k_ratio = sum(r["k_ratio"] * r["trades"] for r in risk_data_list) / total_risk_trades
            portfolio_sqn = sum(r["sqn"] * r["trades"] for r in risk_data_list) / total_risk_trades
            portfolio_win_rate = sum(r["win_rate"] * r["trades"] for r in risk_data_list) / total_risk_trades

    # Compute portfolio avg_r from all trades
    if all_trades_dfs:
        _all_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'r_multiple' in _all_df.columns:
            portfolio_avg_r = float(_all_df['r_multiple'].mean())

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

    # --- Key Metrics (decision block — first section after header) ---
    md.append("## Key Metrics\n")
    expectancy = (portfolio_pnl / portfolio_trades) if portfolio_trades > 0 else 0.0
    if risk_data_list:
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trades | {portfolio_trades} |")
        md.append(f"| Net PnL | ${portfolio_pnl:.2f} |")
        md.append(f"| Expectancy | ${expectancy:.2f} |")
        md.append(f"| Profit Factor | {port_pf_str} |")
        md.append(f"| Sharpe | {portfolio_sharpe:.2f} |")
        md.append(f"| Sortino | {portfolio_sortino:.2f} |")
        md.append(f"| K-Ratio | {portfolio_k_ratio:.2f} |")
        md.append(f"| Max DD | ${portfolio_max_dd_usd:.2f} ({portfolio_max_dd_pct:.2f}%) |")
        md.append(f"| Return/DD | {portfolio_ret_dd:.2f} |")
        md.append(f"| Win Rate | {portfolio_win_rate * 100:.1f}% |")
        md.append(f"| Avg R | {portfolio_avg_r:+.3f} |")
        md.append(f"| SQN | {portfolio_sqn:.2f} |")
    else:
        # Stage-1 only fallback: show what we can
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trades | {portfolio_trades} |")
        md.append(f"| Net PnL | ${portfolio_pnl:.2f} |")
        md.append(f"| Expectancy | ${expectancy:.2f} |")
        md.append(f"| Profit Factor | {port_pf_str} |")
        md.append(f"| Avg R | {portfolio_avg_r:+.3f} |")
        md.append(f"| Sharpe | N/A (S1) |")
        md.append(f"| Max DD | N/A (S1) |")
    md.append("\n---\n")

    # --- Direction Split ---
    md.append("## Direction Split\n")
    if all_trades_dfs:
        _dir_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'direction' in _dir_df.columns and 'pnl_usd' in _dir_df.columns:
            md.append("| Direction | Trades | Net PnL | PF | Win % | Avg Bars |")
            md.append("|-----------|--------|---------|-----|-------|----------|")
            for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
                _ds = _dir_df[_dir_df['direction'] == _dv]
                if len(_ds) == 0:
                    continue
                _d_trades = len(_ds)
                _d_pnl = _ds['pnl_usd'].sum()
                _d_gp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
                _d_gl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
                _d_pf = (_d_gp / _d_gl) if _d_gl > 0 else (_d_gp if _d_gp > 0 else 0.0)
                _d_pf_str = f"{_d_pf:.2f}" if _d_pf != float('inf') else "∞"
                _d_wr = (_ds['pnl_usd'] > 0).mean() * 100
                _d_bars = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
                md.append(f"| {_dl} | {_d_trades} | ${_d_pnl:.2f} | {_d_pf_str} | {_d_wr:.1f}% | {_d_bars} |")
    else:
        md.append("> No trade-level data available for Direction Split.\n")
    md.append("\n---\n")

    # --- Symbol Summary ---
    md.append("## Symbol Summary\n")
    md.append("| Symbol | Trades | Net PnL | PF | Max DD | Return/DD | Win % | Avg R |")
    md.append("|--------|--------|---------|----|--------|-----------|-------|-------|")
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
        md.append(f"| {row['Symbol']} | T:{row['High_T']} ${row['High']:.2f} | T:{row['Normal_T']} ${row['Normal']:.2f} | T:{row['Low_T']} ${row['Low']:.2f} |")
    md.append("\n---\n")

    md.append("## Trend Edge\n")
    md.append("| Symbol | StrongUp | WeakUp | Neutral | WeakDn | StrongDn |")
    md.append("|--------|----------|--------|---------|--------|----------|")
    for row in trend_data:
        md.append(f"| {row['Symbol']} | T:{row['StrongUp_T']} ${row['StrongUp']:.2f} | T:{row['WeakUp_T']} ${row['WeakUp']:.2f} | T:{row['Neutral_T']} ${row['Neutral']:.2f} | T:{row['WeakDn_T']} ${row['WeakDn']:.2f} | T:{row['StrongDn_T']} ${row['StrongDn']:.2f} |")
    
    # --- Exit Analysis ---
    md.append("\n---\n")
    md.append("## Exit Analysis\n")

    if all_trades_dfs:
        _exit_df = pd.concat(all_trades_dfs, ignore_index=True).copy()

        _has_r = 'r_multiple' in _exit_df.columns
        _has_bars = 'bars_held' in _exit_df.columns
        _has_mfe = 'mfe_r' in _exit_df.columns

        # Infer exit type from r_multiple and bars_held
        if _has_r and _has_bars:
            import numpy as _np
            _exit_df['_exit_type'] = 'OTHER'
            _max_bars_val = int(_exit_df['bars_held'].max())
            _exit_df.loc[_exit_df['bars_held'] >= _max_bars_val, '_exit_type'] = 'TIME'
            _exit_df.loc[(_exit_df['bars_held'] < _max_bars_val) & (_exit_df['r_multiple'] <= -0.9), '_exit_type'] = 'SL'
            _exit_df.loc[(_exit_df['bars_held'] < _max_bars_val) & (_exit_df['r_multiple'] >= 1.2), '_exit_type'] = 'TP'

            md.append("### Exit Type Summary\n")
            md.append("| Type | Trades | % | PnL | Avg R |")
            md.append("|------|--------|---|-----|-------|")
            for _et in ['SL', 'TP', 'TIME']:
                _s = _exit_df[_exit_df['_exit_type'] == _et]
                if len(_s) == 0:
                    continue
                _pct = len(_s) / len(_exit_df) * 100
                _pnl = _s['pnl_usd'].sum()
                _avg_r = _s['r_multiple'].mean()
                md.append(f"| {_et} | {len(_s)} | {_pct:.1f}% | ${_pnl:.2f} | {_avg_r:+.2f}R |")
            md.append("")

            # Exit type by direction
            md.append("### Exit Type by Direction\n")
            md.append("| Direction | SL % | TP % | Time % | Trades |")
            md.append("|-----------|------|------|--------|--------|")
            for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
                _ds = _exit_df[_exit_df['direction'] == _dv]
                if len(_ds) == 0:
                    continue
                _sl_pct = (_ds['_exit_type'] == 'SL').mean() * 100
                _tp_pct = (_ds['_exit_type'] == 'TP').mean() * 100
                _tm_pct = (_ds['_exit_type'] == 'TIME').mean() * 100
                md.append(f"| {_dl} | {_sl_pct:.1f}% | {_tp_pct:.1f}% | {_tm_pct:.1f}% | {len(_ds)} |")
            md.append("")

        # R-Multiple Summary
        if _has_r:
            _rmean = _exit_df['r_multiple'].mean()
            _rmedian = _exit_df['r_multiple'].median()
            md.append(f"**R-Multiple:** Mean {_rmean:+.3f} | Median {_rmedian:+.3f}\n")

        # MFE Giveback (time exits)
        if _has_mfe and '_exit_type' in _exit_df.columns:
            _time_exits = _exit_df[_exit_df['_exit_type'] == 'TIME']
            if len(_time_exits) > 0:
                _gave_back = _time_exits[_time_exits['mfe_r'] >= 0.5]
                _gb_pct = len(_gave_back) / len(_time_exits) * 100
                if len(_gave_back) > 0:
                    _avg_left = (_gave_back['mfe_r'] - _gave_back['r_multiple']).mean()
                    md.append(f"**MFE Giveback:** {_gb_pct:.0f}% of time exits had MFE >= 0.5R, gave back {_avg_left:+.2f}R avg\n")

        # Immediate Adverse (SL trades with no favorable excursion)
        if _has_mfe and '_exit_type' in _exit_df.columns:
            _sl_trades = _exit_df[_exit_df['_exit_type'] == 'SL']
            if len(_sl_trades) > 0:
                _imm_adv = _sl_trades[_sl_trades['mfe_r'] < 0.1]
                _ia_pct = len(_imm_adv) / len(_sl_trades) * 100
                md.append(f"**Immediate Adverse:** {len(_imm_adv)}/{len(_sl_trades)} SL trades ({_ia_pct:.0f}%) never reached 0.1R MFE\n")

        # Avg Bars to Exit
        if _has_bars:
            md.append("### Avg Bars to Exit\n")
            md.append("| Type | Avg Bars | Median Bars |")
            md.append("|------|----------|-------------|")
            if '_exit_type' in _exit_df.columns:
                for _et in ['SL', 'TP', 'TIME']:
                    _s = _exit_df[_exit_df['_exit_type'] == _et]
                    if len(_s) == 0:
                        continue
                    md.append(f"| {_et} | {_s['bars_held'].mean():.1f} | {_s['bars_held'].median():.0f} |")
            _all_avg = _exit_df['bars_held'].mean()
            _all_med = _exit_df['bars_held'].median()
            md.append(f"| ALL | {_all_avg:.1f} | {_all_med:.0f} |")
            md.append("")
    else:
        md.append("> No trade-level data available for Exit Analysis.\n")

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

    # --- Actionable Insights (auto-derived, max 5 bullets) ---
    md.append("---\n")
    md.append("## Actionable Insights\n")
    insights = _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf)
    for bullet in insights[:5]:
        md.append(f"- {bullet}")
    md.append("")

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
        
    with open(summary_json, "r", encoding="utf-8") as f:
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
        with open(metadata_json, "r", encoding="utf-8") as f:
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

