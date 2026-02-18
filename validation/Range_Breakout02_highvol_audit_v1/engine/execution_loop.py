"""
Universal Research Engine v1.2.0 — Execution Loop
Strategy-agnostic. Provides ctx per STRATEGY_PLUGIN_CONTRACT.md.
"""


def run_execution_loop(df, strategy):
    """
    Fixed execution loop. Strategy-agnostic.
    
    Returns list of trade dicts with entry/exit details.
    Tracks trade_high (MAX of bar highs) and trade_low (MIN of bar lows)
    from entry_bar to exit_bar inclusive.
    """
    df = strategy.prepare_indicators(df)
    trades = []
    
    in_pos = False
    direction = 0      # 1 = LONG, -1 = SHORT, 0 = flat
    entry_index = 0
    entry_price = 0.0
    trade_high = 0.0   # MAX(high) during trade
    trade_low = float('inf')  # MIN(low) during trade

    for i in range(len(df)):
        row = df.iloc[i]
        
        # Build context
        ctx = {
            "row": row,
            "index": i,
            "direction": direction,
            "entry_index": entry_index if in_pos else None,
            "bars_held": (i - entry_index) if in_pos else 0
        }

        if not in_pos:
            # --- ENTRY CHECK ---
            entry_signal = strategy.check_entry(ctx)
            if entry_signal:
                in_pos = True
                entry_index = i
                entry_price = row['close']
                direction = entry_signal.get("signal", 1)
                # Initialize trade extrema with entry bar
                trade_high = row.get('high', row['close'])
                trade_low = row.get('low', row['close'])
                
        else:
            # --- UPDATE TRADE EXTREMA ---
            bar_high = row.get('high', row['close'])
            bar_low = row.get('low', row['close'])
            if bar_high > trade_high:
                trade_high = bar_high
            if bar_low < trade_low:
                trade_low = bar_low
            
            # --- EXIT CHECK ---
            if strategy.check_exit(ctx):
                exit_price = row['close']
                
                trade = {
                    "entry_index": entry_index,
                    "exit_index": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "direction": direction,
                    "bars_held": i - entry_index,
                    "entry_timestamp": df.iloc[entry_index].get('timestamp', df.iloc[entry_index].get('time', None)),
                    "exit_timestamp": row.get('timestamp', row.get('time', None)),
                    "trade_high": trade_high,
                    "trade_low": trade_low
                }
                trades.append(trade)
                
                # Reset to flat
                in_pos = False
                direction = 0
                entry_index = 0
                entry_price = 0.0
                trade_high = 0.0
                trade_low = float('inf')

    return trades
