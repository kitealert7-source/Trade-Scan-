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

    Backward-compatible 4-tuple wrapper around the extended classifier.
    Returns four Series aligned to *df.index*:
      news_flag, entry_in_window, straddles, earliest_window_start
    """
    out = _classify_all_trades_news_extended(
        df, windows_by_currency, symbol_currencies
    )
    return out['news_flag'], out['entry_in_window'], out['straddles'], out['earliest_ws']


def _classify_all_trades_news_extended(df, windows_by_currency, symbol_currencies):
    """Extended classifier — emits pre/post/overlap split + impact + currency tags.

    Window geometry per matching event:
      pre region  = [window_start, event_dt)
      post region = [event_dt, window_end]

    Per-trade buckets (mutually exclusive when news_flag is True):
      news_overlap   — at least one matched window has trade entry < event_dt
                       < exit (trade straddles the event timestamp itself), OR
                       trade touches both pre region of one event AND post region
                       of a different event.
      news_pre_only  — trade touches at least one window AND for every matched
                       window, exit <= event_dt (entirely before each event).
      news_post_only — trade touches at least one window AND for every matched
                       window, entry >= event_dt (entirely after each event).

    Returns dict of pd.Series aligned to *df.index*:
      news_flag, entry_in_window, straddles, earliest_ws,
      news_pre_only, news_post_only, news_overlap,
      matched_impact, matched_currencies, match_count
    """
    out = {
        'news_flag': pd.Series(False, index=df.index),
        'entry_in_window': pd.Series(False, index=df.index),
        'straddles': pd.Series(False, index=df.index),
        'earliest_ws': pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns, UTC]'),
        'news_pre_only': pd.Series(False, index=df.index),
        'news_post_only': pd.Series(False, index=df.index),
        'news_overlap': pd.Series(False, index=df.index),
        'matched_impact': pd.Series('', index=df.index, dtype=object),
        'matched_currencies': pd.Series('', index=df.index, dtype=object),
        'match_count': pd.Series(0, index=df.index, dtype=int),
    }

    for sym in df['symbol'].dropna().unique():
        sym_str = str(sym)
        ccys = symbol_currencies.get(sym_str, ['USD'])

        # Collect windows with full metadata, dedup on (ws, we, event_dt, impact, ccy)
        rec_set: set = set()
        for ccy in ccys:
            wdf = windows_by_currency.get(ccy)
            if wdf is None or len(wdf) == 0:
                continue
            req = ['window_start', 'window_end', 'datetime_utc',
                   'impact', 'currency']
            if not all(c in wdf.columns for c in req):
                # Fallback: minimal window-only records (impact/ccy unknown).
                for ws, we in zip(wdf['window_start'], wdf['window_end']):
                    rec_set.add((ws, we, ws, '', ccy))
                continue
            for _, row in wdf.iterrows():
                rec_set.add((
                    row['window_start'], row['window_end'],
                    row['datetime_utc'], str(row['impact']),
                    str(row['currency']),
                ))

        if not rec_set:
            continue

        recs = sorted(rec_set, key=lambda x: x[0])
        ws_arr = pd.DatetimeIndex([r[0] for r in recs])
        we_arr = pd.DatetimeIndex([r[1] for r in recs])
        ev_arr = pd.DatetimeIndex([r[2] for r in recs])
        impacts = [r[3] for r in recs]
        ccys_arr = [r[4] for r in recs]

        if ws_arr.tz is None:
            ws_arr = ws_arr.tz_localize('UTC')
            we_arr = we_arr.tz_localize('UTC')
            ev_arr = ev_arr.tz_localize('UTC')

        sym_mask = df['symbol'] == sym
        for idx in df.index[sym_mask]:
            entry = df.at[idx, '_entry_dt']
            exit_ = df.at[idx, '_exit_dt']

            # Overlap = trade interval intersects window interval
            overlap = (entry <= we_arr) & (exit_ > ws_arr)
            if not overlap.any():
                continue

            out['news_flag'].at[idx] = True
            mc = int(overlap.sum())
            out['match_count'].at[idx] = mc

            uniq_imp = sorted({impacts[i] for i in range(len(recs))
                               if overlap[i] and impacts[i]})
            uniq_ccy = sorted({ccys_arr[i] for i in range(len(recs))
                               if overlap[i]})
            out['matched_impact'].at[idx] = ','.join(uniq_imp)
            out['matched_currencies'].at[idx] = ','.join(uniq_ccy)

            eiw = (ws_arr <= entry) & (entry <= we_arr)
            if (eiw & overlap).any():
                out['entry_in_window'].at[idx] = True

            strad = (entry < ws_arr) & (exit_ > ws_arr)
            if strad.any():
                out['straddles'].at[idx] = True
                out['earliest_ws'].at[idx] = ws_arr[strad].min()

            # Pre/post/overlap relative to each matched event_dt
            event_in_trade = (entry < ev_arr) & (exit_ > ev_arr) & overlap
            if event_in_trade.any():
                out['news_overlap'].at[idx] = True
                continue

            # No matched event_dt is straddled by the trade.
            # Decide whether the trade is uniformly before, uniformly after,
            # or split across event_dts of different matched events.
            touched_ev = ev_arr[overlap]
            all_pre = bool((exit_ <= touched_ev).all())
            all_post = bool((entry >= touched_ev).all())
            if all_pre:
                out['news_pre_only'].at[idx] = True
            elif all_post:
                out['news_post_only'].at[idx] = True
            else:
                # Mixed pre+post across multiple events without straddling
                # any single event_dt — count as overlap (multi-event coincidence).
                out['news_overlap'].at[idx] = True

    return out


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


def _compute_news_robustness(df):
    """News-subset robustness metrics mirroring the main quality gate.

    Returns dict with: trades, net_pnl, pf, top5_pct, pf_ex_top5pct,
    longest_flat_days, edge_ratio.

    Designed to be applied to the news subset (df[df['_news_flag']]) so it
    can be compared apples-to-apples against the baseline risk section.
    """
    n = len(df)
    if n == 0:
        return {'trades': 0, 'net_pnl': 0.0, 'pf': 0.0,
                'top5_pct': 0.0, 'pf_ex_top5pct': 0.0,
                'longest_flat_days': 0, 'edge_ratio': 0.0}

    pnl = df['pnl_usd']
    net = float(pnl.sum())
    pf = _news_pf(pnl)

    total_abs = abs(net)
    if total_abs > 0 and n >= 5:
        top5 = float(df.nlargest(5, 'pnl_usd')['pnl_usd'].sum())
        top5_pct = (top5 / total_abs) * 100
    else:
        top5_pct = 0.0

    # PF after removing top 5 % of winning trades by PnL
    wins = df[pnl > 0].sort_values('pnl_usd', ascending=False)
    if len(wins) > 0:
        k = max(1, int(round(len(wins) * 0.05)))
        kept = df.drop(wins.head(k).index)
        pf_ex = _news_pf(kept['pnl_usd']) if len(kept) else 0.0
    else:
        pf_ex = pf

    # Longest flat: days between equity-curve peaks
    longest_flat = 0
    if '_entry_dt' in df.columns and n >= 2:
        sorted_df = df.sort_values('_entry_dt').copy()
        cum = sorted_df['pnl_usd'].cumsum()
        peak = cum.cummax()
        ts = pd.to_datetime(sorted_df['_entry_dt'], errors='coerce')
        at_peak = cum >= peak
        peak_dates = ts[at_peak].dropna()
        if len(peak_dates) >= 2:
            gaps = peak_dates.diff().dt.days.dropna()
            longest_flat = int(gaps.max()) if len(gaps) > 0 else 0

    # Edge ratio (avg MFE / avg MAE)
    if 'mfe_r' in df.columns and 'mae_r' in df.columns and n > 0:
        avg_mfe = float(df['mfe_r'].mean())
        avg_mae = abs(float(df['mae_r'].mean()))
        edge_ratio = (avg_mfe / avg_mae) if avg_mae > 0 else 0.0
    else:
        edge_ratio = 0.0

    return {'trades': n, 'net_pnl': net, 'pf': pf,
            'top5_pct': top5_pct, 'pf_ex_top5pct': pf_ex,
            'longest_flat_days': longest_flat, 'edge_ratio': edge_ratio}


def _compute_news_yearwise(df):
    """News-subset yearwise PF / trades / net_pnl.

    Returns list of dicts sorted by year ascending.
    """
    if len(df) == 0 or '_entry_dt' not in df.columns:
        return []
    work = df.copy()
    work['_year'] = pd.to_datetime(work['_entry_dt'], errors='coerce').dt.year
    work = work.dropna(subset=['_year'])
    out = []
    for y, sub in work.groupby('_year', sort=True):
        out.append({
            'year': int(y),
            'trades': len(sub),
            'net_pnl': float(sub['pnl_usd'].sum()),
            'pf': _news_pf(sub['pnl_usd']),
        })
    return out


def _build_impact_slice_windows(windows_df, impact_label):
    """Slice an all-impact windows_df down to a labeled subset.

    impact_label may be a single string ("High") or a "+"-joined union
    ("High+Medium"). Returns (windows_df_slice, windows_by_currency_slice).
    """
    if windows_df is None or len(windows_df) == 0:
        return None, {}
    if impact_label is None or impact_label == "" or impact_label.lower() == "all":
        sub = windows_df.copy()
    else:
        wanted = {p.strip() for p in impact_label.split('+') if p.strip()}
        sub = windows_df[windows_df['impact'].isin(wanted)].copy()
    if len(sub) == 0:
        return sub, {}
    by_ccy = {}
    for ccy, group in sub.groupby('currency'):
        by_ccy[ccy] = group.sort_values('window_start').reset_index(drop=True)
    return sub, by_ccy


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
