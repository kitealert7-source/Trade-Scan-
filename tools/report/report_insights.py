"""Actionable-insights derivation.

Each insight category returns a list of (score, text) tuples.
_derive_insights orchestrates + sorts + applies fallback.
_build_insights_section wraps the result in markdown bullets.
"""

from __future__ import annotations

import pandas as pd

from tools.report.report_sessions import (
    _classify_session, _is_late_ny, _conf_tag,
)


def _insight_direction_volatility_trend(df):
    """Section 1: Strong / Weak cells from Direction x Volatility x Trend."""
    out = []
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

    strong_cells.sort(key=lambda x: -x[0])
    weak_cells.sort(key=lambda x: x[0])

    if strong_cells:
        top = strong_cells[:2]
        _best_pf = min(top[0][0], 5.0)
        _best_trades = top[0][2]
        _sc = _best_pf * min(1.0, _best_trades / 30)
        parts = [f"{c[3]} (PF {c[0]:.2f}, {c[2]}T)" for c in top]
        out.append((_sc, f"Strong edge ({_conf_tag(_best_trades)}): {', '.join(parts)}"))

    if weak_cells:
        w = weak_cells[0]
        action = "candidate for exclusion" if w[1] < 0 else "drag on portfolio"
        _wsc = min(1.0 / max(w[0], 0.01), 10.0) * min(1.0, w[2] / 30)
        out.append((_wsc, f"Weak cell ({_conf_tag(w[2])}): {w[3]} (PF {w[0]:.2f}, {w[2]}T, ${w[1]:.0f}) — {action}"))

    return out


def _insight_direction_asymmetry(df):
    """Section 2: Direction asymmetry."""
    out = []
    if "direction" not in df.columns:
        return out
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
            out.append(
                (ratio * _dir_weight,
                 f"Direction bias ({_conf_tag(min(len(longs), len(shorts)))}): {stronger} PF {max(l_pf, s_pf):.2f} vs {weaker} PF {min(l_pf, s_pf):.2f} — asymmetric edge")
            )
    return out


def _insight_exit_structure(df):
    """Section 3: Exit structure."""
    out = []
    if "bars_held" not in df.columns or "r_multiple" not in df.columns:
        return out
    max_bars = int(df["bars_held"].max())
    time_exits = df[df["bars_held"] >= max_bars]
    sl_exits = df[(df["bars_held"] < max_bars) & (df["r_multiple"] <= -0.9)]
    time_pct = len(time_exits) / len(df) * 100
    sl_pct = len(sl_exits) / len(df) * 100
    avg_bars = df["bars_held"].mean()

    if time_pct >= 90:
        out.append(
            (time_pct / 100,
             f"Exit dependency ({_conf_tag(len(time_exits))}): {time_pct:.0f}% TIME exits, avg {avg_bars:.1f} bars — edge is short-lived")
        )
    if sl_pct <= 3 and len(df) >= 50:
        out.append(
            (0.5,
             f"Low SL rate ({_conf_tag(len(df))}): {sl_pct:.1f}% — risk distribution compressed, DD may understate tail exposure")
        )
    elif sl_pct >= 20:
        out.append(
            (sl_pct / 100,
             f"High SL rate ({_conf_tag(len(sl_exits))}): {sl_pct:.1f}% — {len(sl_exits)} stop-outs, check entry timing or stop distance")
        )
    return out


def _insight_mfe_giveback(df):
    """Section 4: MFE giveback."""
    out = []
    if not all(c in df.columns for c in ("mfe_r", "r_multiple", "bars_held")):
        return out
    max_bars = int(df["bars_held"].max())
    time_exits = df[df["bars_held"] >= max_bars]
    if len(time_exits) > 0:
        high_mfe = time_exits[time_exits["mfe_r"] >= 1.0]
        if len(high_mfe) >= 3:
            avg_giveback = (high_mfe["mfe_r"] - high_mfe["r_multiple"]).mean()
            out.append(
                (avg_giveback,
                 f"MFE waste ({_conf_tag(len(high_mfe))}): {len(high_mfe)} trades reached >= 1.0R MFE, gave back {avg_giveback:+.2f}R avg — TP or trail opportunity")
            )
    return out


def _insight_trade_density(df, portfolio_trades):
    """Section 5: Trade density."""
    out = []
    if portfolio_trades <= 0 or "entry_timestamp" not in df.columns:
        return out
    first = pd.to_datetime(df["entry_timestamp"]).min()
    last = pd.to_datetime(df["exit_timestamp"]).max()
    days = (last - first).days
    if days > 0:
        trades_per_month = portfolio_trades / (days / 30.44)
        if trades_per_month < 3:
            out.append(
                (0.3,
                 f"Low density ({_conf_tag(portfolio_trades)}): {trades_per_month:.1f} trades/month — statistical significance requires longer test window")
            )
    return out


def _insight_session_divergence(df):
    """Section 6: Session divergence."""
    out = []
    if "entry_timestamp" not in df.columns or "pnl_usd" not in df.columns:
        return out
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
            out.append(
                (_sess_gap * _sess_weight,
                 f"Session divergence ({_conf_tag(_sess_min_t)}): {nice[best_s]} PF {sess_pfs[best_s]:.2f} vs {nice[worst_s]} PF {sess_pfs[worst_s]:.2f} — filter candidate")
            )
    return out


def _insight_late_ny_asymmetry(df):
    """Section 7: Late NY directional asymmetry."""
    out = []
    if not all(c in df.columns for c in ("entry_timestamp", "direction", "pnl_usd")):
        return out
    df_lny = df.copy()
    df_lny['_is_late_ny'] = df_lny['entry_timestamp'].apply(_is_late_ny)
    df_lny['_session'] = df_lny['entry_timestamp'].apply(_classify_session)
    _ny_trades = df_lny[df_lny['_session'] == 'ny']
    _ny_core = _ny_trades[~_ny_trades['_is_late_ny']]
    _ny_late = _ny_trades[_ny_trades['_is_late_ny']]
    if len(_ny_late) < 10:
        return out

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
        if _core_pf < 1.0:
            continue
        _og = float(_late_opp[_late_opp['pnl_usd'] > 0]['pnl_usd'].sum())
        _ol = abs(float(_late_opp[_late_opp['pnl_usd'] < 0]['pnl_usd'].sum()))
        _opp_pf = (_og / _ol) if _ol > 0 else (_og if _og > 0 else 0.0)
        if _late_pf >= _core_pf * 1.5 and _opp_pf < 1.0:
            _opp_label = "Short" if _dv == 1 else "Long"
            _late_pf_c = min(_late_pf, 5.0)
            _asym_score = (_late_pf_c / _core_pf) * (1.0 - _opp_pf) * min(1.0, len(_late_d) / 30)
            _lny_min_t = min(len(_late_d), len(_late_opp))
            out.append(
                (_asym_score,
                 f"Late NY asymmetry ({_conf_tag(_lny_min_t)}): {_dl} PF {_late_pf:.2f} (late) vs {_core_pf:.2f} (core), "
                 f"{_opp_label} PF {_opp_pf:.2f} — directional filter candidate")
            )
            break  # one insight is enough
    return out


def _insight_regime_age_gradient(df):
    """Section 8: Regime age gradient."""
    out = []
    if "regime_age" not in df.columns or "pnl_usd" not in df.columns:
        return out
    from tools.metrics_core import compute_regime_age_breakdown
    age_rows = compute_regime_age_breakdown(df.to_dict("records"))
    qualified = [r for r in age_rows if r["trades"] >= 10]
    if len(qualified) < 2:
        return out
    best = max(qualified, key=lambda r: r["profit_factor"])
    worst = min(qualified, key=lambda r: r["profit_factor"])
    gap = best["profit_factor"] - worst["profit_factor"]
    if gap < 0.5:
        return out
    _age_min_t = min(best["trades"], worst["trades"])
    _age_weight = min(1.0, _age_min_t / 30)
    if worst["profit_factor"] < 1.0 and worst["net_pnl"] < 0:
        action = "exclusion candidate"
    else:
        action = "weaker bucket"
    out.append(
        (gap * _age_weight,
         f"Regime age gradient ({_conf_tag(_age_min_t)}): "
         f"{best['label']} PF {best['profit_factor']:.2f} ({best['trades']}T) vs "
         f"{worst['label']} PF {worst['profit_factor']:.2f} ({worst['trades']}T, ${worst['net_pnl']:.0f}) — {action}")
    )
    return out


def _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf):
    """Auto-derive mechanical insights from existing report data, ranked by strength. No narrative."""
    if not all_trades_dfs:
        return ["Insufficient data for insights."]

    df = pd.concat(all_trades_dfs, ignore_index=True)
    if len(df) == 0:
        return ["Insufficient data for insights."]

    scored = []
    scored.extend(_insight_direction_volatility_trend(df))
    scored.extend(_insight_direction_asymmetry(df))
    scored.extend(_insight_exit_structure(df))
    scored.extend(_insight_mfe_giveback(df))
    scored.extend(_insight_trade_density(df, portfolio_trades))
    scored.extend(_insight_session_divergence(df))
    scored.extend(_insight_late_ny_asymmetry(df))
    scored.extend(_insight_regime_age_gradient(df))

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


def _build_insights_section(all_trades_dfs, risk_data_list, portfolio_pnl,
                            portfolio_trades, port_pf):
    md = ["---\n", "## Actionable Insights\n"]
    insights = _derive_insights(all_trades_dfs, risk_data_list, portfolio_pnl, portfolio_trades, port_pf)
    for bullet in insights[:7]:
        md.append(f"- {bullet}")
    md.append("")
    return md
