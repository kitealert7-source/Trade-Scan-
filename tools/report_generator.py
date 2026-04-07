import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone
import json
from tools.pipeline_utils import get_engine_version

# Session boundaries (UTC hours) — mirrored from stage2_compiler.py
_ASIA_START, _ASIA_END = 0, 8
_LONDON_START, _LONDON_END = 8, 16
_NY_START, _NY_END = 16, 24


def _classify_session(ts) -> str:
    """Classify entry_timestamp string → session label. Mirrors stage2 _get_session."""
    if pd.isna(ts):
        return "unknown"
    try:
        dt = pd.Timestamp(ts)
        hour = dt.hour
    except Exception:
        return "unknown"
    if _ASIA_START <= hour < _ASIA_END:
        return "asia"
    elif _LONDON_START <= hour < _LONDON_END:
        return "london"
    else:
        return "ny"

_OVERLAP_START, _OVERLAP_END = 13, 16  # London-NY overlap window (UTC)
_LATE_NY_START, _LATE_NY_END = 21, 24  # Late NY / off-hours window (UTC)


def _is_overlap(ts) -> bool:
    """True if entry_timestamp falls in London-NY overlap (13:00-15:59 UTC)."""
    if pd.isna(ts):
        return False
    try:
        hour = pd.Timestamp(ts).hour
    except Exception:
        return False
    return _OVERLAP_START <= hour < _OVERLAP_END


def _is_late_ny(ts) -> bool:
    """True if entry_timestamp falls in Late NY window (21:00-23:59 UTC)."""
    if pd.isna(ts):
        return False
    try:
        hour = pd.Timestamp(ts).hour
    except Exception:
        return False
    return _LATE_NY_START <= hour < _LATE_NY_END


def _conf_tag(trades: int) -> str:
    """Confidence tag based on primary trade count: High (>=50), Medium (20-49), Low (<20)."""
    if trades >= 50:
        return "High"
    elif trades >= 20:
        return "Medium"
    return "Low"


_WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _classify_weekday(ts) -> str:
    """Classify entry_timestamp → weekday name."""
    if pd.isna(ts):
        return "unknown"
    try:
        return _WEEKDAY_NAMES[pd.Timestamp(ts).weekday()]
    except Exception:
        return "unknown"


def _build_cross_tab(df, target_col, col_keys):
    """Build a Direction x <target_col> markdown cross-tab from trade-level data."""
    if target_col not in df.columns or 'direction' not in df.columns or 'pnl_usd' not in df.columns:
        return ["| Data Unavailable |"]

    df_c = df.copy()
    df_c[target_col] = df_c[target_col].astype(str).str.lower().str.strip()

    # Map direction safely and drop nulls to avoid silent misclassification
    df_c['dir_label'] = pd.to_numeric(df_c['direction'], errors='coerce')
    if df_c['dir_label'].isnull().any():
        print("[WARN] Dropping null direction mappings in cross-tab for {}".format(target_col))
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
            row_vals.append("{flag}T:{t} P:${pnl:.2f} W:{wr:.1f}% PF:{pf}".format(
                flag=flag, t=trades, pnl=net_pnl, wr=wr, pf=pf_str))
        lines.append("| " + " | ".join(row_vals) + " |")
    return lines


def _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf):
    """Auto-derive mechanical insights from existing report data, ranked by strength. No narrative."""
    # Each insight is (score, text). Higher score = more actionable. Sorted descending at return.
    scored = []
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
        _best_pf = min(top[0][0], 5.0)
        _best_trades = top[0][2]
        _sc = _best_pf * min(1.0, _best_trades / 30)
        parts = [f"{c[3]} (PF {c[0]:.2f}, {c[2]}T)" for c in top]
        scored.append((_sc, f"Strong edge ({_conf_tag(_best_trades)}): {', '.join(parts)}"))

    if weak_cells:
        w = weak_cells[0]
        action = "candidate for exclusion" if w[1] < 0 else "drag on portfolio"
        _wsc = min(1.0 / max(w[0], 0.01), 10.0) * min(1.0, w[2] / 30)
        scored.append((_wsc, f"Weak cell ({_conf_tag(w[2])}): {w[3]} (PF {w[0]:.2f}, {w[2]}T, ${w[1]:.0f}) — {action}"))

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
                _dir_weight = min(1.0, min(len(longs), len(shorts)) / 30)
                scored.append(
                    (ratio * _dir_weight,
                     f"Direction bias ({_conf_tag(min(len(longs), len(shorts)))}): {stronger} PF {max(l_pf, s_pf):.2f} vs {weaker} PF {min(l_pf, s_pf):.2f} — asymmetric edge")
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
            scored.append(
                (time_pct / 100,
                 f"Exit dependency ({_conf_tag(len(time_exits))}): {time_pct:.0f}% TIME exits, avg {avg_bars:.1f} bars — edge is short-lived")
            )
        if sl_pct <= 3 and len(df) >= 50:
            scored.append(
                (0.5,
                 f"Low SL rate ({_conf_tag(len(df))}): {sl_pct:.1f}% — risk distribution compressed, DD may understate tail exposure")
            )
        elif sl_pct >= 20:
            scored.append(
                (sl_pct / 100,
                 f"High SL rate ({_conf_tag(len(sl_exits))}): {sl_pct:.1f}% — {len(sl_exits)} stop-outs, check entry timing or stop distance")
            )

    # --- 4. MFE giveback ---
    if "mfe_r" in df.columns and "r_multiple" in df.columns and "bars_held" in df.columns:
        max_bars = int(df["bars_held"].max())
        time_exits = df[df["bars_held"] >= max_bars]
        if len(time_exits) > 0:
            high_mfe = time_exits[time_exits["mfe_r"] >= 1.0]
            if len(high_mfe) >= 3:
                avg_giveback = (high_mfe["mfe_r"] - high_mfe["r_multiple"]).mean()
                scored.append(
                    (avg_giveback,
                     f"MFE waste ({_conf_tag(len(high_mfe))}): {len(high_mfe)} trades reached >= 1.0R MFE, gave back {avg_giveback:+.2f}R avg — TP or trail opportunity")
                )

    # --- 5. Trade density ---
    if portfolio_trades > 0 and "entry_timestamp" in df.columns:
        first = pd.to_datetime(df["entry_timestamp"]).min()
        last = pd.to_datetime(df["exit_timestamp"]).max()
        days = (last - first).days
        if days > 0:
            trades_per_month = portfolio_trades / (days / 30.44)
            if trades_per_month < 3:
                scored.append(
                    (0.3,
                     f"Low density ({_conf_tag(portfolio_trades)}): {trades_per_month:.1f} trades/month — statistical significance requires longer test window")
                )

    # --- 6. Session divergence ---
    if "entry_timestamp" in df.columns and "pnl_usd" in df.columns:
        df_s = df.copy()
        df_s['_session'] = df_s['entry_timestamp'].apply(_classify_session)
        sess_pfs = {}
        sess_counts = {}
        for sl in ['asia', 'london', 'ny']:
            ss = df_s[df_s['_session'] == sl]
            if len(ss) < 5:
                continue
            gp = float(ss[ss['pnl_usd'] > 0]['pnl_usd'].sum())
            gl = abs(float(ss[ss['pnl_usd'] < 0]['pnl_usd'].sum()))
            sess_pfs[sl] = (gp / gl) if gl > 0 else (gp if gp > 0 else 0.0)
            sess_counts[sl] = len(ss)
        if len(sess_pfs) >= 2:
            best_s = max(sess_pfs, key=sess_pfs.get)
            worst_s = min(sess_pfs, key=sess_pfs.get)
            _sess_gap = sess_pfs[best_s] - sess_pfs[worst_s]
            if _sess_gap > 0.5:
                nice = {"asia": "Asia", "london": "London", "ny": "NY"}
                _sess_weight = min(1.0, min(sess_counts[best_s], sess_counts[worst_s]) / 30)
                _sess_min_t = min(sess_counts[best_s], sess_counts[worst_s])
                scored.append(
                    (_sess_gap * _sess_weight,
                     f"Session divergence ({_conf_tag(_sess_min_t)}): {nice[best_s]} PF {sess_pfs[best_s]:.2f} vs {nice[worst_s]} PF {sess_pfs[worst_s]:.2f} — filter candidate")
                )

    # --- 7. Late NY directional asymmetry ---
    if "entry_timestamp" in df.columns and "direction" in df.columns and "pnl_usd" in df.columns:
        df_lny = df.copy()
        df_lny['_is_late_ny'] = df_lny['entry_timestamp'].apply(_is_late_ny)
        df_lny['_session'] = df_lny['entry_timestamp'].apply(_classify_session)
        _ny_trades = df_lny[df_lny['_session'] == 'ny']
        _ny_core = _ny_trades[~_ny_trades['_is_late_ny']]
        _ny_late = _ny_trades[_ny_trades['_is_late_ny']]
        if len(_ny_late) >= 10:
            for _dv, _dl in [(1, "Long"), (-1, "Short")]:
                _late_d = _ny_late[_ny_late['direction'] == _dv]
                _core_d = _ny_core[_ny_core['direction'] == _dv]
                _opp = -_dv
                _late_opp = _ny_late[_ny_late['direction'] == _opp]
                # Min 10 trades per direction in Late NY
                if len(_late_d) < 10 or len(_late_opp) < 10 or len(_core_d) < 10:
                    continue
                _lg = float(_late_d[_late_d['pnl_usd'] > 0]['pnl_usd'].sum())
                _ll = abs(float(_late_d[_late_d['pnl_usd'] < 0]['pnl_usd'].sum()))
                _late_pf = (_lg / _ll) if _ll > 0 else (_lg if _lg > 0 else 0.0)
                _cg = float(_core_d[_core_d['pnl_usd'] > 0]['pnl_usd'].sum())
                _cl = abs(float(_core_d[_core_d['pnl_usd'] < 0]['pnl_usd'].sum()))
                _core_pf = (_cg / _cl) if _cl > 0 else 0.0
                # Skip if core baseline is below breakeven — no valid reference
                if _core_pf < 1.0:
                    continue
                _og = float(_late_opp[_late_opp['pnl_usd'] > 0]['pnl_usd'].sum())
                _ol = abs(float(_late_opp[_late_opp['pnl_usd'] < 0]['pnl_usd'].sum()))
                _opp_pf = (_og / _ol) if _ol > 0 else (_og if _og > 0 else 0.0)
                if _late_pf >= _core_pf * 1.5 and _opp_pf < 1.0:
                    _opp_label = "Short" if _dv == 1 else "Long"
                    # score = clamped(late_pf / core_pf) * (1 - opp_pf) * trade_weight
                    _late_pf_c = min(_late_pf, 5.0)
                    _asym_score = (_late_pf_c / _core_pf) * (1.0 - _opp_pf) * min(1.0, len(_late_d) / 30)
                    _lny_min_t = min(len(_late_d), len(_late_opp))
                    scored.append(
                        (_asym_score,
                         f"Late NY asymmetry ({_conf_tag(_lny_min_t)}): {_dl} PF {_late_pf:.2f} (late) vs {_core_pf:.2f} (core), "
                         f"{_opp_label} PF {_opp_pf:.2f} — directional filter candidate")
                    )
                    break  # one insight is enough

    # --- 8. Regime age gradient ---
    if "regime_age" in df.columns and "pnl_usd" in df.columns:
        from tools.metrics_core import compute_regime_age_breakdown
        age_rows = compute_regime_age_breakdown(df.to_dict("records"))
        qualified = [r for r in age_rows if r["trades"] >= 10]
        if len(qualified) >= 2:
            best = max(qualified, key=lambda r: r["profit_factor"])
            worst = min(qualified, key=lambda r: r["profit_factor"])
            gap = best["profit_factor"] - worst["profit_factor"]
            if gap >= 0.5:
                _age_min_t = min(best["trades"], worst["trades"])
                _age_weight = min(1.0, _age_min_t / 30)
                if worst["profit_factor"] < 1.0 and worst["net_pnl"] < 0:
                    action = "exclusion candidate"
                else:
                    action = "weaker bucket"
                scored.append(
                    (gap * _age_weight,
                     f"Regime age gradient ({_conf_tag(_age_min_t)}): "
                     f"{best['label']} PF {best['profit_factor']:.2f} ({best['trades']}T) vs "
                     f"{worst['label']} PF {worst['profit_factor']:.2f} ({worst['trades']}T, ${worst['net_pnl']:.0f}) — {action}")
                )

    # Sort by strength (descending) and extract text
    scored.sort(key=lambda x: -x[0])
    insights = [text for _, text in scored]

    # Fallback if nothing triggered
    if not insights:
        if port_pf >= 1.5:
            insights.append("No structural issues detected — strategy passes all mechanical checks")
        else:
            insights.append(f"Marginal edge (PF {port_pf:.2f}) — decompose by direction and regime before iterating")

    return insights


def generate_backtest_report(directive_name: str, backtest_root: Path, *,
                             show_overlap: bool = False, show_late_ny: bool = False,
                             show_weekday: bool = False):
    """
    Generates a deterministic markdown report from raw CSV artifacts without altering state.
    Provides run-level metrics (Stage-5A).
    The generated report is saved inside each matching symbol directory within the backtest namespace.

    Args:
        show_overlap: If True, append London-NY overlap analysis (13-16 UTC) to Session Breakdown.
        show_late_ny: If True, append Late NY analysis (21-24 UTC) to Session Breakdown.
        show_weekday: If True, append weekday breakdown + Direction × Day cross-tab.
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
    age_data = []
    session_data = []
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

        # Regime Lifecycle (Age) breakdown
        if tdf is not None and len(tdf) > 0 and 'regime_age' in tdf.columns and 'pnl_usd' in tdf.columns:
            from tools.metrics_core import compute_regime_age_breakdown
            trade_dicts = tdf.to_dict('records')
            age_rows = compute_regime_age_breakdown(trade_dicts)
            age_entry = {"Symbol": symbol}
            for r in age_rows:
                key = r["label"].replace(" ", "_").replace("-", "_").replace("+", "plus")
                age_entry[f"{key}_T"] = r["trades"]
                age_entry[f"{key}_PnL"] = r["net_pnl"]
                age_entry[f"{key}_PF"] = r["profit_factor"]
                age_entry[f"{key}_WR"] = r["win_rate"]
            age_data.append(age_entry)

        # Session breakdown (computed from trade-level entry_timestamp)
        asia_pnl = 0.0; london_pnl = 0.0; ny_pnl = 0.0
        asia_t = 0; london_t = 0; ny_t = 0
        if tdf is not None and len(tdf) > 0 and 'entry_timestamp' in tdf.columns:
            tdf['_session'] = tdf['entry_timestamp'].apply(_classify_session)
            sess_groups = tdf.groupby('_session')['pnl_usd'].sum()
            sess_counts = tdf.groupby('_session')['pnl_usd'].count()
            asia_pnl = float(sess_groups.get('asia', 0.0))
            london_pnl = float(sess_groups.get('london', 0.0))
            ny_pnl = float(sess_groups.get('ny', 0.0))
            asia_t = int(sess_counts.get('asia', 0))
            london_t = int(sess_counts.get('london', 0))
            ny_t = int(sess_counts.get('ny', 0))
        session_data.append({"Symbol": symbol, "Asia": asia_pnl, "London": london_pnl, "NY": ny_pnl, "Asia_T": asia_t, "London_T": london_t, "NY_T": ny_t})

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
    
    # --- Yearwise Performance (always on) ---
    md.append("## Yearwise Performance\n")
    if all_trades_dfs:
        _yr_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'entry_timestamp' in _yr_df.columns and 'pnl_usd' in _yr_df.columns:
            _yr_df['_year'] = pd.to_datetime(_yr_df['entry_timestamp'], errors='coerce').dt.year
            _yr_df = _yr_df[_yr_df['_year'].notna()]
            _yr_df['_year'] = _yr_df['_year'].astype(int)
            _years = sorted(_yr_df['_year'].unique())
            md.append("| Year | Trades | Net PnL | PF | Win % | Max DD |")
            md.append("|------|--------|---------|-----|-------|--------|")
            for _y in _years:
                _ys = _yr_df[_yr_df['_year'] == _y]
                _yt = len(_ys)
                _ypnl = _ys['pnl_usd'].sum()
                _ygp = float(_ys[_ys['pnl_usd'] > 0]['pnl_usd'].sum())
                _ygl = abs(float(_ys[_ys['pnl_usd'] < 0]['pnl_usd'].sum()))
                _ypf = (_ygp / _ygl) if _ygl > 0 else (_ygp if _ygp > 0 else 0.0)
                _ypf_s = f"{_ypf:.2f}" if _ypf != float('inf') else "inf"
                _ywr = (_ys['pnl_usd'] > 0).mean() * 100
                # Compute intra-year max drawdown from cumulative PnL
                _cum = _ys['pnl_usd'].cumsum()
                _peak = _cum.cummax()
                _dd = _cum - _peak
                _max_dd = abs(float(_dd.min())) if len(_dd) > 0 else 0.0
                md.append(f"| {_y} | {_yt} | ${_ypnl:.2f} | {_ypf_s} | {_ywr:.1f}% | ${_max_dd:.2f} |")
            md.append("")
        else:
            md.append("> No timestamp data available for Yearwise Performance.\n")
    else:
        md.append("> No trade-level data available for Yearwise Performance.\n")
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
    md.append("\n---\n")

    if age_data:
        md.append("## Regime Lifecycle (Age)\n")
        _age_buckets = ["Age_0", "Age_1", "Age_2", "Age_3_5", "Age_6_10", "Age_11plus"]
        _age_labels = ["Age 0", "Age 1", "Age 2", "Age 3-5", "Age 6-10", "Age 11+"]
        md.append("| Symbol | " + " | ".join(_age_labels) + " |")
        md.append("|--------" + "|-------" * len(_age_labels) + "|")
        for row in age_data:
            cells = []
            for bk in _age_buckets:
                t = row.get(f"{bk}_T", 0)
                pnl = row.get(f"{bk}_PnL", 0.0)
                pf = row.get(f"{bk}_PF", 0.0)
                wr = row.get(f"{bk}_WR", 0.0)
                cells.append(f"T:{t} ${pnl:.2f} PF:{pf:.2f} WR:{wr:.0f}%")
            md.append(f"| {row['Symbol']} | " + " | ".join(cells) + " |")
        md.append("\n---\n")

    # --- Session Breakdown ---
    md.append("## Session Breakdown\n")
    if all_trades_dfs:
        _sess_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'entry_timestamp' in _sess_df.columns and 'pnl_usd' in _sess_df.columns:
            _sess_df['_session'] = _sess_df['entry_timestamp'].apply(_classify_session)
            md.append("| Session | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
            md.append("|---------|--------|---------|-----|-------|-------|----------|")
            for _sl, _sn in [('asia', 'Asia'), ('london', 'London'), ('ny', 'New York')]:
                _ss = _sess_df[_sess_df['_session'] == _sl]
                if len(_ss) == 0:
                    md.append(f"| {_sn} | 0 | - | - | - | - | - |")
                    continue
                _s_trades = len(_ss)
                _s_pnl = _ss['pnl_usd'].sum()
                _s_gp = float(_ss[_ss['pnl_usd'] > 0]['pnl_usd'].sum())
                _s_gl = abs(float(_ss[_ss['pnl_usd'] < 0]['pnl_usd'].sum()))
                _s_pf = (_s_gp / _s_gl) if _s_gl > 0 else (_s_gp if _s_gp > 0 else 0.0)
                _s_pf_str = f"{_s_pf:.2f}" if _s_pf != float('inf') else "∞"
                _s_wr = (_ss['pnl_usd'] > 0).mean() * 100
                _s_avg_r = f"{_ss['r_multiple'].mean():+.3f}" if 'r_multiple' in _ss.columns else "N/A"
                _s_bars = f"{_ss['bars_held'].mean():.1f}" if 'bars_held' in _ss.columns else "N/A"
                md.append(f"| {_sn} | {_s_trades} | ${_s_pnl:.2f} | {_s_pf_str} | {_s_wr:.1f}% | {_s_avg_r} | {_s_bars} |")
            md.append("")

            # Per-symbol session grid (only if multi-symbol)
            if len(session_data) > 1:
                md.append("### Per-Symbol Session Grid\n")
                md.append("| Symbol | Asia | London | NY |")
                md.append("|--------|------|--------|-----|")
                for row in session_data:
                    md.append(f"| {row['Symbol']} | T:{row['Asia_T']} ${row['Asia']:.2f} | T:{row['London_T']} ${row['London']:.2f} | T:{row['NY_T']} ${row['NY']:.2f} |")
                md.append("")

            # --- Optional: London-NY Overlap Analysis ---
            if show_overlap:
                _sess_df['_is_overlap'] = _sess_df['entry_timestamp'].apply(_is_overlap)
                _ov = _sess_df[_sess_df['_is_overlap']]
                _non_ov = _sess_df[~_sess_df['_is_overlap']]

                md.append("### Overlap Analysis (London-NY, 13-16 UTC)\n")

                if len(_ov) < 10:
                    md.append(f"> Only {len(_ov)} trades in overlap window — insufficient for analysis.\n")
                else:
                    md.append("| Segment | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
                    md.append("|---------|--------|---------|-----|-------|-------|----------|")
                    for _label, _sub in [('Overlap (13-16)', _ov), ('Non-overlap', _non_ov)]:
                        _t = len(_sub)
                        if _t == 0:
                            md.append(f"| {_label} | 0 | - | - | - | - | - |")
                            continue
                        _pnl = _sub['pnl_usd'].sum()
                        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                        _pf_s = f"{_pf:.2f}" if _pf != float('inf') else "∞"
                        _wr = (_sub['pnl_usd'] > 0).mean() * 100
                        _ar = f"{_sub['r_multiple'].mean():+.3f}" if 'r_multiple' in _sub.columns else "N/A"
                        _ab = f"{_sub['bars_held'].mean():.1f}" if 'bars_held' in _sub.columns else "N/A"
                        md.append(f"| {_label} | {_t} | ${_pnl:.2f} | {_pf_s} | {_wr:.1f}% | {_ar} | {_ab} |")
                    md.append("")

                    # Session × Overlap cross-tab (London and NY only — Asia can't overlap)
                    md.append("### Session x Overlap\n")
                    md.append("| Session | Core (no overlap) | Overlap (13-16) |")
                    md.append("|---------|-------------------|-----------------|")
                    for _sl, _sn in [('london', 'London'), ('ny', 'New York')]:
                        _s_all = _sess_df[_sess_df['_session'] == _sl]
                        _s_core = _s_all[~_s_all['_is_overlap']]
                        _s_ov = _s_all[_s_all['_is_overlap']]
                        parts = []
                        for _sub in [_s_core, _s_ov]:
                            if len(_sub) == 0:
                                parts.append("-")
                                continue
                            _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                            _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                            _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                            _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
                            parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s}")
                        md.append(f"| {_sn} | {parts[0]} | {parts[1]} |")
                    md.append("")

            # --- Optional: Late NY Analysis ---
            if show_late_ny:
                _sess_df['_is_late_ny'] = _sess_df['entry_timestamp'].apply(_is_late_ny)
                _lny = _sess_df[_sess_df['_is_late_ny']]
                _non_lny = _sess_df[~_sess_df['_is_late_ny']]

                md.append("### Late NY Analysis (21-24 UTC)\n")

                if len(_lny) < 10:
                    md.append(f"> Only {len(_lny)} trades in Late NY window — insufficient for analysis.\n")
                else:
                    md.append("| Segment | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
                    md.append("|---------|--------|---------|-----|-------|-------|----------|")
                    for _label, _sub in [('Late NY (21-24)', _lny), ('Rest', _non_lny)]:
                        _t = len(_sub)
                        if _t == 0:
                            md.append(f"| {_label} | 0 | - | - | - | - | - |")
                            continue
                        _pnl = _sub['pnl_usd'].sum()
                        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                        _pf_s = f"{_pf:.2f}" if _pf != float('inf') else "∞"
                        _wr = (_sub['pnl_usd'] > 0).mean() * 100
                        _ar = f"{_sub['r_multiple'].mean():+.3f}" if 'r_multiple' in _sub.columns else "N/A"
                        _ab = f"{_sub['bars_held'].mean():.1f}" if 'bars_held' in _sub.columns else "N/A"
                        md.append(f"| {_label} | {_t} | ${_pnl:.2f} | {_pf_s} | {_wr:.1f}% | {_ar} | {_ab} |")
                    md.append("")

                    # NY core vs Late NY split
                    md.append("### NY x Late Session\n")
                    md.append("| Segment | Core NY (16-21) | Late NY (21-24) |")
                    md.append("|---------|-----------------|-----------------|")
                    _ny_all = _sess_df[_sess_df['_session'] == 'ny']
                    _ny_core = _ny_all[~_ny_all['_is_late_ny']]
                    _ny_late = _ny_all[_ny_all['_is_late_ny']]
                    parts = []
                    for _sub in [_ny_core, _ny_late]:
                        if len(_sub) == 0:
                            parts.append("-")
                            continue
                        _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                        _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                        _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                        _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
                        parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s}")
                    md.append(f"| NY | {parts[0]} | {parts[1]} |")
                    md.append("")

                    # Direction × Late NY
                    if 'direction' in _sess_df.columns:
                        md.append("### Direction x Late NY\n")
                        md.append("| Direction | Core NY (16-21) | Late NY (21-24) |")
                        md.append("|-----------|-----------------|-----------------|")
                        for _dv, _dl in [(1, 'Long'), (-1, 'Short')]:
                            _d_ny = _ny_all[_ny_all['direction'] == _dv]
                            _d_core = _d_ny[~_d_ny['_is_late_ny']]
                            _d_late = _d_ny[_d_ny['_is_late_ny']]
                            parts = []
                            for _sub in [_d_core, _d_late]:
                                if len(_sub) == 0:
                                    parts.append("-")
                                    continue
                                _gp = float(_sub[_sub['pnl_usd'] > 0]['pnl_usd'].sum())
                                _gl = abs(float(_sub[_sub['pnl_usd'] < 0]['pnl_usd'].sum()))
                                _pf = (_gp / _gl) if _gl > 0 else (_gp if _gp > 0 else 0.0)
                                _pf_s = "∞" if _pf == float('inf') else f"{_pf:.2f}"
                                _wr = (_sub['pnl_usd'] > 0).mean() * 100
                                parts.append(f"T:{len(_sub)} ${_sub['pnl_usd'].sum():.2f} PF:{_pf_s} W:{_wr:.0f}%")
                            md.append(f"| {_dl} | {parts[0]} | {parts[1]} |")
                        md.append("")
        else:
            md.append("> No entry_timestamp data available for Session Breakdown.\n")
    else:
        md.append("> No trade-level data available for Session Breakdown.\n")

    # --- Optional: Weekday Breakdown ---
    if show_weekday and all_trades_dfs:
        _wd_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'entry_timestamp' in _wd_df.columns and 'pnl_usd' in _wd_df.columns:
            _wd_df['_weekday'] = _wd_df['entry_timestamp'].apply(_classify_weekday)
            _wd_valid = _wd_df[_wd_df['_weekday'] != 'unknown']
            if len(_wd_valid) >= 10:
                md.append("\n---\n")
                md.append("## Weekday Breakdown\n")
                md.append("| Day | Trades | Net PnL | PF | Win % | Avg R | Avg Bars |")
                md.append("|-----|--------|---------|-----|-------|-------|----------|")
                for _day in _WEEKDAY_NAMES[:5]:  # Mon-Fri only (Sat/Sun typically empty)
                    _ds = _wd_valid[_wd_valid['_weekday'] == _day]
                    if len(_ds) == 0:
                        md.append(f"| {_day} | 0 | - | - | - | - | - |")
                        continue
                    _dt = len(_ds)
                    _dpnl = _ds['pnl_usd'].sum()
                    _dgp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
                    _dgl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
                    _dpf = (_dgp / _dgl) if _dgl > 0 else (_dgp if _dgp > 0 else 0.0)
                    _dpf_s = f"{_dpf:.2f}" if _dpf != float('inf') else "inf"
                    _dwr = (_ds['pnl_usd'] > 0).mean() * 100
                    _dar = f"{_ds['r_multiple'].mean():+.3f}" if 'r_multiple' in _ds.columns else "N/A"
                    _dab = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
                    md.append(f"| {_day} | {_dt} | ${_dpnl:.2f} | {_dpf_s} | {_dwr:.1f}% | {_dar} | {_dab} |")
                # Weekend rows only if trades exist
                for _day in _WEEKDAY_NAMES[5:]:
                    _ds = _wd_valid[_wd_valid['_weekday'] == _day]
                    if len(_ds) > 0:
                        _dt = len(_ds)
                        _dpnl = _ds['pnl_usd'].sum()
                        _dgp = float(_ds[_ds['pnl_usd'] > 0]['pnl_usd'].sum())
                        _dgl = abs(float(_ds[_ds['pnl_usd'] < 0]['pnl_usd'].sum()))
                        _dpf = (_dgp / _dgl) if _dgl > 0 else (_dgp if _dgp > 0 else 0.0)
                        _dpf_s = f"{_dpf:.2f}" if _dpf != float('inf') else "inf"
                        _dwr = (_ds['pnl_usd'] > 0).mean() * 100
                        _dar = f"{_ds['r_multiple'].mean():+.3f}" if 'r_multiple' in _ds.columns else "N/A"
                        _dab = f"{_ds['bars_held'].mean():.1f}" if 'bars_held' in _ds.columns else "N/A"
                        md.append(f"| {_day} | {_dt} | ${_dpnl:.2f} | {_dpf_s} | {_dwr:.1f}% | {_dar} | {_dab} |")
                md.append("")

                # Direction × Day cross-tab
                _wd_valid['_weekday_lc'] = _wd_valid['_weekday'].str.lower()
                _day_cols = {d: d.lower() for d in _WEEKDAY_NAMES[:5]}
                # Add weekend if trades exist
                for _day in _WEEKDAY_NAMES[5:]:
                    if len(_wd_valid[_wd_valid['_weekday'] == _day]) > 0:
                        _day_cols[_day] = _day.lower()
                md.append("### Direction &times; Day\n")
                md.extend(_build_cross_tab(_wd_valid, "_weekday_lc", _day_cols))
                md.append("")

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

        md.append("### A) Direction &times; Volatility\n")
        vol_cols = {"High": "high", "Normal": "normal", "Low": "low"}
        md.extend(_build_cross_tab(all_trades_df, "volatility_regime", vol_cols))
        md.append("\n")

        md.append("### B) Direction &times; Trend\n")
        trend_cols = {"Strong Up": "strong_up", "Weak Up": "weak_up", "Neutral": "neutral", "Weak Down": "weak_down", "Strong Down": "strong_down"}
        md.extend(_build_cross_tab(all_trades_df, "trend_label", trend_cols))
        md.append("\n")

        # C) Direction × Session
        if 'entry_timestamp' in all_trades_df.columns:
            all_trades_df['_session'] = all_trades_df['entry_timestamp'].apply(_classify_session)
            md.append("### C) Direction &times; Session\n")
            session_cols = {"Asia": "asia", "London": "london", "NY": "ny"}
            md.extend(_build_cross_tab(all_trades_df, "_session", session_cols))
            md.append("\n")
    else:
        md.append("> No trade-level data available for Edge Decomposition.\n")

    # --- Risk Characteristics ---
    md.append("---\n")
    md.append("## Risk Characteristics\n")
    if all_trades_dfs:
        _risk_df = pd.concat(all_trades_dfs, ignore_index=True)
        if 'pnl_usd' in _risk_df.columns and len(_risk_df) > 0:
            md.append("| Metric | Value |")
            md.append("|--------|-------|")

            # Max Consecutive Losses
            _losses = (_risk_df['pnl_usd'] <= 0).astype(int)
            _max_consec = 0
            _cur = 0
            for _v in _losses:
                if _v == 1:
                    _cur += 1
                    _max_consec = max(_max_consec, _cur)
                else:
                    _cur = 0
            md.append(f"| Max Consecutive Losses | {_max_consec} |")

            # Longest Flat Period (calendar days between equity highs)
            if 'entry_timestamp' in _risk_df.columns:
                _risk_df_sorted = _risk_df.sort_values('entry_timestamp').copy()
                _cum_pnl = _risk_df_sorted['pnl_usd'].cumsum()
                _peak = _cum_pnl.cummax()
                _ts = pd.to_datetime(_risk_df_sorted['entry_timestamp'], errors='coerce')
                _at_peak = _cum_pnl >= _peak
                _peak_dates = _ts[_at_peak]
                if len(_peak_dates) >= 2:
                    _gaps = _peak_dates.diff().dt.days.dropna()
                    _flat_days = int(_gaps.max()) if len(_gaps) > 0 else 0
                else:
                    _flat_days = 0
                md.append(f"| Longest Flat Period | {_flat_days} days |")

            # Top-5 Trade Concentration (% of total PnL from top-5 winners)
            _total_abs_pnl = abs(_risk_df['pnl_usd'].sum())
            if _total_abs_pnl > 0:
                _top5 = _risk_df.nlargest(5, 'pnl_usd')['pnl_usd'].sum()
                _top5_pct = (_top5 / _total_abs_pnl) * 100
                md.append(f"| Top-5 Trade Concentration | {_top5_pct:.1f}% of Net PnL |")

            # Edge Ratio (avg MFE / avg MAE)
            if 'mfe_r' in _risk_df.columns and 'mae_r' in _risk_df.columns:
                _avg_mfe = _risk_df['mfe_r'].mean()
                _avg_mae = abs(_risk_df['mae_r'].mean())
                _edge_ratio = (_avg_mfe / _avg_mae) if _avg_mae > 0 else 0.0
                md.append(f"| Edge Ratio (MFE/MAE) | {_edge_ratio:.2f} |")

            md.append("")
        else:
            md.append("> Insufficient data for Risk Characteristics.\n")
    else:
        md.append("> No trade-level data available for Risk Characteristics.\n")

    # --- Actionable Insights (auto-derived, max 5 bullets) ---
    md.append("---\n")
    md.append("## Actionable Insights\n")
    insights = _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf)
    for bullet in insights[:7]:
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

