"""News Policy — pure computation helpers (no markdown rendering).

OHLC lookup, PF helper, trade-window classification, scenario metrics,
and trade-df preparation / Go-Flat reconstruction.

Markdown rendering lives in tools/report/report_sections/news.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# Minimum trade count for optional scenarios (No-Entry / Go-Flat).
_NEWS_MIN_TRADES = 10


def _load_ohlc_for_symbol(symbol: str, timeframe: str, data_root: Path):
    """Load OHLC data for *symbol* at *timeframe* from MASTER_DATA.

    Returns a datetime-indexed DataFrame with at least 'close', or None.
    """
    tf_lower = timeframe.lower()
    master_dir = (
        data_root / "MASTER_DATA"
        / f"{symbol}_OCTAFX_MASTER" / "RESEARCH"
    )
    if not master_dir.exists():
        return None

    pattern = f"{symbol}_OCTAFX_{tf_lower}_*_RESEARCH.csv"
    files = sorted(master_dir.glob(pattern))
    if not files:
        return None

    frames = []
    for f in files:
        try:
            chunk = pd.read_csv(f, comment='#', encoding='utf-8')
            if len(chunk) > 0 and 'time' in chunk.columns:
                frames.append(chunk)
        except Exception:
            continue

    if not frames:
        return None

    ohlc = pd.concat(frames, ignore_index=True)
    ohlc['time'] = pd.to_datetime(ohlc['time'], errors='coerce', utc=True)
    ohlc = ohlc.dropna(subset=['time'])
    ohlc = ohlc.sort_values('time').drop_duplicates(subset=['time'], keep='last')
    ohlc = ohlc.set_index('time')
    return ohlc


def _get_price_at(ohlc_df, target_dt):
    """Return close of the last OHLC bar at or before *target_dt*, or None."""
    if ohlc_df is None or len(ohlc_df) == 0:
        return None
    mask = ohlc_df.index <= target_dt
    if not mask.any():
        return None
    return float(ohlc_df.loc[mask, 'close'].iloc[-1])


def _news_pf(series):
    """Profit factor from a pnl_usd Series."""
    gp = float(series[series > 0].sum())
    gl = abs(float(series[series < 0].sum()))
    if gl == 0:
        return gp if gp > 0 else 0.0
    return gp / gl


def _classify_all_trades_news(df, windows_by_currency, symbol_currencies):
    """Classify every trade's relationship to news windows.

    For each symbol, collects all relevant currency windows, then uses
    vectorised numpy comparisons per trade for speed.

    Returns four Series aligned to *df.index*:
      news_flag, entry_in_window, straddles, earliest_window_start
    """
    n = len(df)
    news_flag = pd.Series(False, index=df.index)
    entry_in_window = pd.Series(False, index=df.index)
    straddles = pd.Series(False, index=df.index)
    earliest_ws = pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns, UTC]')

    for sym in df['symbol'].dropna().unique():
        sym_str = str(sym)
        ccys = symbol_currencies.get(sym_str, ['USD'])

        # Collect all windows for this symbol's currencies, deduplicate
        pairs_set: set = set()
        for ccy in ccys:
            wdf = windows_by_currency.get(ccy)
            if wdf is not None and len(wdf) > 0:
                for ws, we in zip(wdf['window_start'], wdf['window_end']):
                    pairs_set.add((ws, we))

        if not pairs_set:
            continue

        pairs = sorted(pairs_set, key=lambda x: x[0])
        ws_arr = pd.DatetimeIndex([p[0] for p in pairs])
        we_arr = pd.DatetimeIndex([p[1] for p in pairs])
        # Ensure tz-aware (UTC) for comparison with trade timestamps
        if ws_arr.tz is None:
            ws_arr = ws_arr.tz_localize('UTC')
            we_arr = we_arr.tz_localize('UTC')

        sym_mask = df['symbol'] == sym
        sym_df = df.loc[sym_mask]

        for idx in sym_df.index:
            entry = df.at[idx, '_entry_dt']
            exit_ = df.at[idx, '_exit_dt']

            # Vectorised overlap: entry <= window_end AND exit > window_start
            overlap = (entry <= we_arr) & (exit_ > ws_arr)
            if not overlap.any():
                continue

            news_flag.at[idx] = True

            # Entry in window: window_start <= entry <= window_end
            eiw = (ws_arr <= entry) & (entry <= we_arr)
            if eiw.any():
                entry_in_window.at[idx] = True

            # Straddle: entry < window_start < exit
            strad = (entry < ws_arr) & (exit_ > ws_arr)
            if strad.any():
                straddles.at[idx] = True
                earliest_ws.at[idx] = ws_arr[strad].min()

    return news_flag, entry_in_window, straddles, earliest_ws


def _compute_news_metrics(df):
    """Standard scenario metrics: trades, net_pnl, pf, win_pct, max_dd."""
    n = len(df)
    if n == 0:
        return {'trades': 0, 'net_pnl': 0.0, 'pf': 0.0,
                'win_pct': 0.0, 'max_dd': 0.0}

    pnl = df['pnl_usd']
    net = float(pnl.sum())
    pf = _news_pf(pnl)
    win_pct = (pnl > 0).mean() * 100

    sorted_df = df.sort_values('_entry_dt')
    cum = sorted_df['pnl_usd'].cumsum()
    max_dd = float((cum.cummax() - cum).max())

    return {'trades': n, 'net_pnl': net, 'pf': pf,
            'win_pct': win_pct, 'max_dd': max_dd}


def _news_prepare_df(all_trades_dfs):
    """Filter/concatenate trade dfs and add _entry_dt / _exit_dt columns.

    Returns None if insufficient data (or missing required columns).
    """
    required = {'entry_timestamp', 'exit_timestamp', 'entry_price',
                'exit_price', 'pnl_usd', 'direction', 'symbol'}
    valid_dfs = [
        d for d in all_trades_dfs
        if required.issubset(d.columns) and len(d) > 0
    ]
    if not valid_dfs:
        return None

    df = pd.concat(valid_dfs, ignore_index=True).copy()
    df['_entry_dt'] = pd.to_datetime(
        df['entry_timestamp'], errors='coerce', utc=True
    )
    df['_exit_dt'] = pd.to_datetime(
        df['exit_timestamp'], errors='coerce', utc=True
    )
    df = df.dropna(subset=['_entry_dt', '_exit_dt', 'pnl_usd'])
    df = df.sort_values('_entry_dt').reset_index(drop=True)

    if len(df) < _NEWS_MIN_TRADES:
        return None
    return df


def _news_compute_go_flat(df, timeframe, data_root):
    """Exit straddlers at earliest window_start and recompute per-trade pnl."""
    ohlc_map: dict = {}
    if timeframe and timeframe != "Unknown":
        for sym in df['symbol'].dropna().unique():
            ohlc = _load_ohlc_for_symbol(str(sym), timeframe, data_root)
            if ohlc is not None:
                ohlc_map[str(sym)] = ohlc

    df_go_flat = df[~df['_entry_in_window']].copy()

    for idx in df_go_flat.index[df_go_flat['_straddles']]:
        row = df_go_flat.loc[idx]
        sym = str(row['symbol'])
        ws = row['_earliest_ws']

        ohlc = ohlc_map.get(sym)
        new_exit_price = _get_price_at(ohlc, ws)
        if new_exit_price is None:
            continue  # skip modification — no price available

        entry_price = float(row['entry_price'])
        exit_price = float(row['exit_price'])
        direction = int(row['direction'])
        original_pnl = float(row['pnl_usd'])

        price_delta = (exit_price - entry_price) * direction
        if abs(price_delta) < 1e-10:
            new_pnl = 0.0
        else:
            pnl_scale = original_pnl / price_delta
            new_pnl = pnl_scale * (new_exit_price - entry_price) * direction

        df_go_flat.at[idx, 'pnl_usd'] = new_pnl

        # Best-effort r_multiple update
        if 'r_multiple' in df_go_flat.columns:
            r = row.get('r_multiple', 0.0)
            if r and abs(r) > 1e-10:
                risk_per_trade = original_pnl / r
                if abs(risk_per_trade) > 1e-10:
                    df_go_flat.at[idx, 'r_multiple'] = new_pnl / risk_per_trade

    return _compute_news_metrics(df_go_flat)
