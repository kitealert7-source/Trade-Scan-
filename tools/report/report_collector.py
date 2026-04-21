"""Per-symbol data collection + portfolio aggregation.

Loads raw CSV artifacts (the DB) into a SymbolPayloads container that the
section builders consume read-only.

Dependency: tools.report.report_sessions (for _classify_session).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from tools.report.report_sessions import _classify_session


def _collect_vol_trend_edges(tdf):
    """Compute avg_r + volatility/trend PnL+count breakdowns from trade-level df."""
    out = {
        "avg_r": 0.0,
        "h_vol": 0.0, "n_vol": 0.0, "l_vol": 0.0,
        "h_vol_t": 0, "n_vol_t": 0, "l_vol_t": 0,
        "s_up": 0.0, "w_up": 0.0, "neu": 0.0, "w_dn": 0.0, "s_dn": 0.0,
        "s_up_t": 0, "w_up_t": 0, "neu_t": 0, "w_dn_t": 0, "s_dn_t": 0,
    }
    if tdf is None or len(tdf) == 0:
        return out

    if 'r_multiple' in tdf.columns:
        out["avg_r"] = float(tdf['r_multiple'].mean())

    if 'volatility_regime' in tdf.columns and 'pnl_usd' in tdf.columns:
        tdf['volatility_regime_clean'] = tdf['volatility_regime'].astype(str).str.lower().str.strip()
        vol_groups = tdf.groupby('volatility_regime_clean')['pnl_usd'].sum()
        vol_counts = tdf.groupby('volatility_regime_clean')['pnl_usd'].count()
        out["h_vol"] = float(vol_groups.get('high', 0.0))
        out["n_vol"] = float(vol_groups.get('normal', 0.0))
        out["l_vol"] = float(vol_groups.get('low', 0.0))
        out["h_vol_t"] = int(vol_counts.get('high', 0))
        out["n_vol_t"] = int(vol_counts.get('normal', 0))
        out["l_vol_t"] = int(vol_counts.get('low', 0))

    if 'trend_label' in tdf.columns and 'pnl_usd' in tdf.columns:
        tdf['trend_label_clean'] = tdf['trend_label'].astype(str).str.lower().str.strip()
        trend_groups = tdf.groupby('trend_label_clean')['pnl_usd'].sum()
        trend_counts = tdf.groupby('trend_label_clean')['pnl_usd'].count()
        out["s_up"] = float(trend_groups.get('strong_up', 0.0))
        out["w_up"] = float(trend_groups.get('weak_up', 0.0))
        out["neu"] = float(trend_groups.get('neutral', 0.0))
        out["w_dn"] = float(trend_groups.get('weak_down', 0.0))
        out["s_dn"] = float(trend_groups.get('strong_down', 0.0))
        out["s_up_t"] = int(trend_counts.get('strong_up', 0))
        out["w_up_t"] = int(trend_counts.get('weak_up', 0))
        out["neu_t"] = int(trend_counts.get('neutral', 0))
        out["w_dn_t"] = int(trend_counts.get('weak_down', 0))
        out["s_dn_t"] = int(trend_counts.get('strong_down', 0))
    return out


def _collect_age_entry(symbol, tdf):
    """Regime Lifecycle (Age) row keyed by symbol. Returns None if unavailable."""
    if (tdf is None or len(tdf) == 0
            or 'regime_age' not in tdf.columns or 'pnl_usd' not in tdf.columns):
        return None
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
    return age_entry


def _collect_dual_age(symbol, tdf):
    """Fill-age + delta + meta entries for v1.5.5+ dual-time breakdown."""
    if (tdf is None or len(tdf) == 0 or 'pnl_usd' not in tdf.columns
            or not ('regime_age_signal' in tdf.columns or 'regime_age_fill' in tdf.columns)):
        return None
    from tools.metrics_core import compute_age_dual_breakdown
    trade_dicts_dual = tdf.to_dict('records')
    dual = compute_age_dual_breakdown(trade_dicts_dual)

    fill_entry = {"Symbol": symbol}
    for r in dual["fill_buckets"]:
        key = (r["label"]
               .replace(" / ", "_")
               .replace(" ", "_")
               .replace("-", "_")
               .replace("+", "plus"))
        fill_entry[f"{key}_T"] = r["trades"]
        fill_entry[f"{key}_PnL"] = r["net_pnl"]
        fill_entry[f"{key}_PF"] = r["profit_factor"]
        fill_entry[f"{key}_WR"] = r["win_rate"]

    delta_entry = {"Symbol": symbol}
    for r in dual["delta_buckets"]:
        key = (r["label"].replace(" ", "_").replace("<=", "le").replace(">=", "ge")
                          .replace("-", "neg").replace("/", ""))
        delta_entry[f"{key}_T"] = r["trades"]
        delta_entry[f"{key}_PnL"] = r["net_pnl"]
        delta_entry[f"{key}_PF"] = r["profit_factor"]
        delta_entry[f"{key}_WR"] = r["win_rate"]

    meta_entry = {"Symbol": symbol, **dual["meta"]}
    return fill_entry, delta_entry, meta_entry


def _collect_exec_delta(symbol, tdf):
    """v1.5.6 exec-TF delta distribution. Returns (exec_entry, meta_entry) or None."""
    if (tdf is None or len(tdf) == 0 or 'pnl_usd' not in tdf.columns
            or not ('regime_age_exec_signal' in tdf.columns
                    or 'regime_age_exec_fill' in tdf.columns)):
        return None
    from tools.metrics_core import compute_exec_delta_distribution
    exec_out = compute_exec_delta_distribution(tdf.to_dict('records'))
    exec_entry = {"Symbol": symbol}
    for r in exec_out["delta_buckets"]:
        key = (r["label"].replace(" ", "_").replace("<=", "le").replace(">=", "ge")
                          .replace("-", "neg"))
        exec_entry[f"{key}_T"] = r["trades"]
        exec_entry[f"{key}_PnL"] = r["net_pnl"]
        exec_entry[f"{key}_PF"] = r["profit_factor"]
        exec_entry[f"{key}_WR"] = r["win_rate"]
    meta_entry = {"Symbol": symbol, **exec_out["meta"]}
    return exec_entry, meta_entry


def _collect_session_row(symbol, tdf):
    """Session-level PnL+counts row for symbol."""
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
    return {"Symbol": symbol, "Asia": asia_pnl, "London": london_pnl, "NY": ny_pnl,
            "Asia_T": asia_t, "London_T": london_t, "NY_T": ny_t}


@dataclass
class SymbolPayloads:
    """Collected per-symbol data used by section builders.

    Treated as a read-only container — builders must not mutate.
    """
    symbols_data: list = field(default_factory=list)
    risk_data_list: list = field(default_factory=list)
    vol_data: list = field(default_factory=list)
    trend_data: list = field(default_factory=list)
    age_data: list = field(default_factory=list)
    fill_age_data: list = field(default_factory=list)
    delta_age_data: list = field(default_factory=list)
    dual_meta_data: list = field(default_factory=list)
    exec_delta_data: list = field(default_factory=list)
    exec_meta_data: list = field(default_factory=list)
    session_data: list = field(default_factory=list)
    all_trades_dfs: list = field(default_factory=list)
    timeframe: str = "Unknown"
    start_date: str = "YYYY-MM-DD"
    end_date: str = "YYYY-MM-DD"
    global_has_stage3: bool = False
    portfolio_pnl: float = 0.0
    portfolio_trades: int = 0
    portfolio_gross_profit: float = 0.0
    portfolio_gross_loss: float = 0.0


def _load_symbol_data(pl: SymbolPayloads, s_dir: Path, directive_name: str) -> None:
    """Load a single symbol directory's artifacts into *pl*."""
    symbol = s_dir.name.replace(f"{directive_name}_", "")
    raw_dir = s_dir / "raw"
    if not raw_dir.exists():
        return

    std_csv = raw_dir / "results_standard.csv"
    risk_csv = raw_dir / "results_risk.csv"
    trade_csv = raw_dir / "results_tradelevel.csv"

    has_stage3 = std_csv.exists() and risk_csv.exists()
    has_stage1 = trade_csv.exists()
    if not has_stage1:
        return

    meta_path = s_dir / "metadata" / "run_metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                if meta.get("timeframe"):
                    pl.timeframe = meta.get("timeframe")
        except Exception:
            pass

    tdf = None
    if has_stage1:
        tdf = pd.read_csv(trade_csv)
        if len(tdf) > 0:
            if 'volatility_regime' in tdf.columns:
                tdf['volatility_regime'] = tdf['volatility_regime'].replace({
                    -1: 'low', 0: 'normal', 1: 'high',
                    '-1': 'low', '0': 'normal', '1': 'high',
                    '-1.0': 'low', '0.0': 'normal', '1.0': 'high'
                })
            pl.all_trades_dfs.append(tdf)

    edges = _collect_vol_trend_edges(tdf)
    avg_r = edges["avg_r"]

    if has_stage3:
        std_df = pd.read_csv(std_csv)
        risk_df = pd.read_csv(risk_csv)
        if len(std_df) == 0 or len(risk_df) == 0:
            has_stage3 = False
        else:
            pl.global_has_stage3 = True
            std_row = std_df.iloc[-1]
            risk_row = risk_df.iloc[-1]

            trades = int(std_row.get("total_trades", std_row.get("trade_count", 0)))
            net_pnl = float(std_row.get("net_profit", std_row.get("net_pnl_usd", 0.0)))
            win_rate = float(std_row.get("win_rate", 0.0))
            pf = float(std_row.get("profit_factor", 0.0))

            gross_profit = float(std_row.get("gross_profit", 0.0))
            gross_loss = float(std_row.get("gross_loss", 0.0))
            pl.portfolio_gross_profit += gross_profit
            pl.portfolio_gross_loss += abs(gross_loss)

            max_dd = float(risk_row.get("max_drawdown_pct", 0.0))
            ret_dd = float(risk_row.get("return_dd_ratio", 0.0))

            pl.risk_data_list.append({
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

            pl.symbols_data.append({
                "Symbol": symbol,
                "Trades": trades,
                "Net PnL": net_pnl,
                "PF": pf,
                "Max DD": max_dd,
                "Return/DD": ret_dd,
                "Win %": win_rate * 100,
                "Avg R": avg_r,
            })
            pl.portfolio_trades += trades
            pl.portfolio_pnl += net_pnl

    if not has_stage3:
        trades = len(tdf) if tdf is not None else 0
        net_pnl = float(tdf['pnl_usd'].sum()) if tdf is not None and 'pnl_usd' in tdf.columns else 0.0
        pl.symbols_data.append({
            "Symbol": symbol, "Trades": trades, "Net PnL": net_pnl,
            "PF": None, "Max DD": None, "Return/DD": None, "Win %": None,
            "Avg R": avg_r,
        })
        pl.portfolio_trades += trades
        pl.portfolio_pnl += net_pnl

    pl.vol_data.append({"Symbol": symbol,
                        "High": edges["h_vol"], "Normal": edges["n_vol"], "Low": edges["l_vol"],
                        "High_T": edges["h_vol_t"], "Normal_T": edges["n_vol_t"], "Low_T": edges["l_vol_t"]})
    pl.trend_data.append({"Symbol": symbol,
                          "StrongUp": edges["s_up"], "WeakUp": edges["w_up"], "Neutral": edges["neu"],
                          "WeakDn": edges["w_dn"], "StrongDn": edges["s_dn"],
                          "StrongUp_T": edges["s_up_t"], "WeakUp_T": edges["w_up_t"],
                          "Neutral_T": edges["neu_t"], "WeakDn_T": edges["w_dn_t"],
                          "StrongDn_T": edges["s_dn_t"]})

    age_entry = _collect_age_entry(symbol, tdf)
    if age_entry is not None:
        pl.age_data.append(age_entry)

    dual = _collect_dual_age(symbol, tdf)
    if dual is not None:
        fill_entry, delta_entry, meta_entry = dual
        pl.fill_age_data.append(fill_entry)
        pl.delta_age_data.append(delta_entry)
        pl.dual_meta_data.append(meta_entry)

    exec_out = _collect_exec_delta(symbol, tdf)
    if exec_out is not None:
        exec_entry, exec_meta = exec_out
        pl.exec_delta_data.append(exec_entry)
        pl.exec_meta_data.append(exec_meta)

    pl.session_data.append(_collect_session_row(symbol, tdf))

    if has_stage1 and pl.start_date == "YYYY-MM-DD":
        if tdf is not None and len(tdf) > 0 and 'entry_timestamp' in tdf.columns:
            pl.start_date = str(tdf['entry_timestamp'].min())[:10]
            pl.end_date = str(tdf['exit_timestamp'].max())[:10]


def _collect_symbol_payloads(symbol_dirs, directive_name: str) -> SymbolPayloads:
    """Walk each symbol dir and accumulate per-symbol payloads."""
    pl = SymbolPayloads()
    for s_dir in symbol_dirs:
        _load_symbol_data(pl, s_dir, directive_name)
    return pl


def _compute_portfolio_totals(pl: SymbolPayloads) -> dict:
    """Portfolio-level aggregates (trade-weighted averages + worst-case DD)."""
    totals = {
        "port_pf": 0.0,
        "max_dd_usd": 0.0, "max_dd_pct": 0.0,
        "ret_dd": 0.0,
        "sharpe": 0.0, "sortino": 0.0, "k_ratio": 0.0, "sqn": 0.0,
        "win_rate": 0.0, "avg_r": 0.0,
    }
    gp = pl.portfolio_gross_profit
    gl = pl.portfolio_gross_loss
    totals["port_pf"] = (gp / gl) if gl != 0 else gp

    if pl.risk_data_list:
        total_risk_trades = sum(r["trades"] for r in pl.risk_data_list)
        if total_risk_trades > 0:
            totals["max_dd_usd"] = max(r["max_dd_usd"] for r in pl.risk_data_list)
            totals["max_dd_pct"] = max(r["max_dd_pct"] for r in pl.risk_data_list)
            totals["ret_dd"] = (pl.portfolio_pnl / totals["max_dd_usd"]) if totals["max_dd_usd"] > 0 else 0.0
            totals["sharpe"] = sum(r["sharpe"] * r["trades"] for r in pl.risk_data_list) / total_risk_trades
            totals["sortino"] = sum(r["sortino"] * r["trades"] for r in pl.risk_data_list) / total_risk_trades
            totals["k_ratio"] = sum(r["k_ratio"] * r["trades"] for r in pl.risk_data_list) / total_risk_trades
            totals["sqn"] = sum(r["sqn"] * r["trades"] for r in pl.risk_data_list) / total_risk_trades
            totals["win_rate"] = sum(r["win_rate"] * r["trades"] for r in pl.risk_data_list) / total_risk_trades

    if pl.all_trades_dfs:
        _all_df = pd.concat(pl.all_trades_dfs, ignore_index=True)
        if 'r_multiple' in _all_df.columns:
            totals["avg_r"] = float(_all_df['r_multiple'].mean())
    return totals
