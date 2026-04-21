"""Per-trade enriched export: portfolio_tradelevel.csv (SOP_PORTFOLIO_ANALYSIS §5)."""

from __future__ import annotations


def generate_portfolio_tradelevel(portfolio_df, output_dir, total_capital):
    """
    Generate and save portfolio_tradelevel.csv with enriched metrics.
    Satisfies SOP_PORTFOLIO_ANALYSIS Section 5.
    """
    df = portfolio_df.copy()

    if 'notional_usd' not in df.columns:
        if 'position_units' in df.columns and 'entry_price' in df.columns:
             df['notional_usd'] = df['position_units'] * df['entry_price']
        else:
             df['notional_usd'] = 0.0

    df.sort_values('entry_timestamp', inplace=True)
    df.reset_index(inplace=True, drop=True)

    events = []
    for idx, row in df.iterrows():
        events.append((row['entry_timestamp'], 1, idx, row['notional_usd']))
        events.append((row['exit_timestamp'], -1, idx, row['notional_usd']))

    events.sort(key=lambda x: (x[0], x[1]))

    current_concurrent = 0
    current_capital = 0.0

    conc_map = {}
    cap_map = {}

    for t, type_, idx, notional in events:
        if type_ == 1:
            current_concurrent += 1
            current_capital += notional
            conc_map[idx] = current_concurrent
            cap_map[idx] = current_capital
        else:
            current_concurrent -= 1
            current_capital -= notional

    df['concurrency_at_entry'] = df.index.map(conc_map)
    df['capital_deployed_at_entry'] = df.index.map(cap_map)

    events_eq = []
    for idx, row in df.iterrows():
        events_eq.append({'t': row['entry_timestamp'], 'type': 'entry', 'idx': idx})
        events_eq.append({'t': row['exit_timestamp'], 'type': 'exit', 'idx': idx, 'pnl': row['pnl_usd']})

    events_eq.sort(key=lambda x: (x['t'], 0 if x['type']=='exit' else 1))

    current_equity = total_capital
    eq_before_map = {}
    eq_after_map = {}

    for e in events_eq:
        if e['type'] == 'entry':
            eq_before_map[e['idx']] = current_equity
        else:
            current_equity += e['pnl']
            eq_after_map[e['idx']] = current_equity

    df['equity_before_trade'] = df.index.map(eq_before_map)
    df['equity_after_trade'] = df.index.map(eq_after_map)

    df.sort_values('exit_timestamp', inplace=True)

    required_cols = [
        'source_run_id', 'strategy_name', 'entry_timestamp', 'exit_timestamp', 'direction',
        'entry_price', 'exit_price', 'pnl_usd', 'position_units', 'notional_usd', 'bars_held',
        'equity_before_trade', 'equity_after_trade', 'concurrency_at_entry', 'capital_deployed_at_entry'
    ]

    for c in required_cols:
        if c not in df.columns:
            df[c] = None

    output_path = output_dir / 'portfolio_tradelevel.csv'
    df[required_cols].to_csv(output_path, index=False)

    if not df.empty:
        peak_idx = df['capital_deployed_at_entry'].idxmax()
        peak_capital = df.loc[peak_idx, 'capital_deployed_at_entry']
        equity_at_peak = df.loc[peak_idx, 'equity_before_trade']
        ratio = (peak_capital / equity_at_peak) if equity_at_peak > 0 else 0.0
    else:
        peak_capital = 0.0
        ratio = 0.0

    return {
        'peak_capital_deployed': peak_capital,
        'capital_overextension_ratio': ratio
    }
