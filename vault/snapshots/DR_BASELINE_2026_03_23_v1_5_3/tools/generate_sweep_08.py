#!/usr/bin/env python3
"""Generate sweep variants P05-P11 for 08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1.
Baseline: P03 (London close 16:00 exit).
"""
import os, json
from datetime import datetime

BASE = r"c:\Users\faraw\Documents\Trade_Scan"
PREFIX = "08_BRK_XAUUSD_15M_IBREAK_REGFILT_S01_V1"
TS = datetime.now().isoformat()

# (patch, label, desc, is_stop_entry, is_range_stop, exit_h, exit_m, exit_label)
VARIANTS = [
    ("P05", "A",  "Stop-entry breakout (10 tick buffer), 16:00 exit",  True,  False, 16, 0,  "london_close_16utc"),
    ("P06", "B1", "Close-confirm entry, 09:30 exit",                   False, False, 9,  30, "exit_0930utc"),
    ("P07", "B2", "Close-confirm entry, 10:00 exit",                   False, False, 10, 0,  "exit_1000utc"),
    ("P08", "C1", "Stop-entry breakout + 09:30 exit",                  True,  False, 9,  30, "exit_0930utc"),
    ("P09", "C2", "Stop-entry breakout + 10:00 exit",                  True,  False, 10, 0,  "exit_1000utc"),
    ("P10", "D",  "Close-confirm entry, 12:00 exit",                   False, False, 12, 0,  "exit_1200utc"),
    ("P11", "E",  "Close-confirm entry, range-width stop, 16:00 exit", False, True,  16, 0,  "london_close_16utc"),
]

IMPORTS_BLOCK = """import pandas as pd
import numpy as np

# --- IMPORTS (Deterministic from Directive) ---
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime
from indicators.volatility.volatility_regime import volatility_regime
from indicators.volatility.atr import atr
from indicators.structure.range_breakout_session import session_range_structure
from engines.filter_stack import FilterStack"""

PREPARE_BLOCK = """    def prepare_indicators(self, df):
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index(pd.DatetimeIndex(df['timestamp']))

        # Engine-required authoritative columns
        df['atr'] = atr(df, window=14)
        vr = volatility_regime(df['atr'], window=100)
        df['volatility_regime'] = vr['regime']

        # Session range structure
        srs = session_range_structure(df, session_start=_SESSION_START,
                                      session_end=_SESSION_END)
        df['session_high']    = srs['session_high']
        df['session_low']     = srs['session_low']
        df['range_points']    = srs['range_points']
        df['break_direction'] = srs['break_direction']

        # Range quality ratio
        df['range_atr_ratio'] = df['range_points'] / df['atr']

        # Exit time flag
        df['is_exit_time'] = (df.index.hour == _EXIT_HOUR_UTC) & (df.index.minute == _EXIT_MIN_UTC)

        # Penultimate bar safety backstop
        dates = df.index.normalize()
        bar_number  = df.groupby(dates).cumcount()
        bars_in_day = df.groupby(dates)[df.columns[0]].transform('count')
        df['is_penultimate_bar'] = bar_number == (bars_in_day - 2)

        return df"""

ENTRY_CLOSE_CONFIRM = """    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        row = ctx.row

        regime = row.get('volatility_regime')
        if regime not in _ALLOWED_REGIMES:
            return None

        break_dir = row.get('break_direction', 0)
        if break_dir == 0:
            return None

        ratio = row.get('range_atr_ratio')
        if ratio is None or pd.isna(ratio):
            return None
        if ratio < _RANGE_QUALITY_MIN or ratio > _RANGE_QUALITY_MAX:
            return None

        close = row.get('close')
        session_high = row.get('session_high')
        session_low  = row.get('session_low')

        if any(v is None or pd.isna(v) for v in [close, session_high, session_low]):
            return None

        if break_dir == 1 and close > session_high:
            return {"signal": 1}
        if break_dir == -1 and close < session_low:
            return {"signal": -1}

        return None"""

ENTRY_CLOSE_CONFIRM_RANGE_STOP = """    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        row = ctx.row

        regime = row.get('volatility_regime')
        if regime not in _ALLOWED_REGIMES:
            return None

        break_dir = row.get('break_direction', 0)
        if break_dir == 0:
            return None

        ratio = row.get('range_atr_ratio')
        if ratio is None or pd.isna(ratio):
            return None
        if ratio < _RANGE_QUALITY_MIN or ratio > _RANGE_QUALITY_MAX:
            return None

        close = row.get('close')
        session_high = row.get('session_high')
        session_low  = row.get('session_low')

        if any(v is None or pd.isna(v) for v in [close, session_high, session_low]):
            return None

        range_width = row.get('range_points', 50.0)

        if break_dir == 1 and close > session_high:
            self._entry_price = close
            self._range_width = range_width
            return {"signal": 1}
        if break_dir == -1 and close < session_low:
            self._entry_price = close
            self._range_width = range_width
            return {"signal": -1}

        return None"""

ENTRY_STOP_BREAKOUT = """    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        row = ctx.row

        regime = row.get('volatility_regime')
        if regime not in _ALLOWED_REGIMES:
            return None

        ratio = row.get('range_atr_ratio')
        if ratio is None or pd.isna(ratio):
            return None
        if ratio < _RANGE_QUALITY_MIN or ratio > _RANGE_QUALITY_MAX:
            return None

        high = row.get('high')
        low  = row.get('low')
        session_high = row.get('session_high')
        session_low  = row.get('session_low')

        if any(v is None or pd.isna(v) for v in [high, low, session_high, session_low]):
            return None

        long_trigger  = high >= session_high + _ENTRY_BUFFER
        short_trigger = low  <= session_low  - _ENTRY_BUFFER

        if long_trigger and short_trigger:
            return None

        if long_trigger:
            return {"signal": 1}
        if short_trigger:
            return {"signal": -1}

        return None"""

EXIT_TIME_ONLY = """    def check_exit(self, ctx):
        row = ctx.row

        # Exit 1: Time-based exit
        if row.get('is_exit_time', False):
            return True

        # Exit 2: Penultimate bar safety backstop
        if row.get('is_penultimate_bar', False):
            return True

        return False"""

EXIT_RANGE_STOP = """    def check_exit(self, ctx):
        row = ctx.row

        # Exit 1: Range-width stop
        if self._entry_price is not None:
            close = row.get('close')
            direction = ctx.direction
            if close is not None and direction != 0:
                unrealized = (close - self._entry_price) * direction
                if unrealized <= -self._range_width:
                    self._entry_price = None
                    self._range_width = None
                    return True

        # Exit 2: Time-based exit (16:00 UTC)
        if row.get('is_exit_time', False):
            self._entry_price = None
            self._range_width = None
            return True

        # Exit 3: Penultimate bar safety backstop
        if row.get('is_penultimate_bar', False):
            self._entry_price = None
            self._range_width = None
            return True

        return False"""


def build_signature(is_stop_entry, is_range_stop, exit_h, exit_m, exit_label):
    et = f"{exit_h:02d}:{exit_m:02d}"
    rd = {}
    if is_stop_entry:
        rd["buffer_ticks"] = 10
        rd["close_confirmation"] = False
        rd["entry_trigger"] = "stop_breakout"
    else:
        rd["close_confirmation"] = True
    rd["exit_time"] = et
    rd["range_quality_max"] = 2.0
    rd["range_quality_min"] = 0.3
    rd["session_end"] = "07:00"
    rd["session_start"] = "01:00"
    if is_range_stop:
        rd["stop_type"] = "range_width"

    sig = {
        "execution_rules": {
            "stop_loss": {"fixed_points": 50, "type": "fixed_usd"},
            "take_profit": {"enabled": False},
            "trailing_stop": {"enabled": False}
        },
        "exit_rules": {
            "condition_1": {"timing": exit_label, "type": "time_based"},
            "condition_2": {"timing": "penultimate_bar_of_day", "type": "time_based"},
            "logic": "OR",
            "type": "composite"
        },
        "indicators": [
            "indicators.trend.linreg_regime",
            "indicators.trend.linreg_regime_htf",
            "indicators.trend.kalman_regime",
            "indicators.trend.trend_persistence",
            "indicators.trend.efficiency_ratio_regime",
            "indicators.volatility.volatility_regime",
            "indicators.volatility.atr",
            "indicators.structure.range_breakout_session"
        ],
        "order_placement": {"execution_timing": "next_bar_open", "type": "market"},
        "position_management": {"lots": 0.01},
        "range_definition": dict(sorted(rd.items())),
        "signature_version": 2,
        "state_machine": {
            "entry": {"direction": "long_and_short", "trigger": "signal_bar"},
            "no_reentry_after_stop": True,
            "session_reset": "new_day"
        },
        "trade_management": {
            "direction_restriction": "long_and_short",
            "max_trades_per_session": 1,
            "reentry": {"allowed": False}
        },
        "volatility_filter": {"allow_regime": "NORMAL,HIGH", "type": "volatility_regime"}
    }
    return sig


def build_directive(name, is_stop_entry, is_range_stop, exit_h, exit_m, exit_label):
    et = f"{exit_h:02d}:{exit_m:02d}"
    rd_lines = []
    if is_stop_entry:
        rd_lines.append("  buffer_ticks: 10")
        rd_lines.append("  close_confirmation: false")
        rd_lines.append("  entry_trigger: stop_breakout")
    else:
        rd_lines.append("  close_confirmation: true")
    rd_lines.append(f'  exit_time: "{et}"')
    rd_lines.append("  range_quality_max: 2.0")
    rd_lines.append("  range_quality_min: 0.3")
    rd_lines.append('  session_end: "07:00"')
    rd_lines.append('  session_start: "01:00"')
    if is_range_stop:
        rd_lines.append("  stop_type: range_width")
    rd_block = "\n".join(rd_lines)

    return f"""execution_rules:
  stop_loss:
    type: fixed_usd
    fixed_points: 50
  take_profit:
    enabled: false
  trailing_stop:
    enabled: false
indicators:
- indicators.trend.linreg_regime
- indicators.trend.linreg_regime_htf
- indicators.trend.kalman_regime
- indicators.trend.trend_persistence
- indicators.trend.efficiency_ratio_regime
- indicators.volatility.volatility_regime
- indicators.volatility.atr
- indicators.structure.range_breakout_session
range_definition:
{rd_block}
volatility_filter:
  type: volatility_regime
  allow_regime: NORMAL,HIGH
state_machine:
  entry:
    trigger: signal_bar
    direction: long_and_short
  session_reset: new_day
  no_reentry_after_stop: true
exit_rules:
  type: composite
  logic: OR
  condition_1:
    type: time_based
    timing: {exit_label}
  condition_2:
    type: time_based
    timing: penultimate_bar_of_day
position_management:
  lots: 0.01
order_placement:
  execution_timing: next_bar_open
  type: market
trade_management:
  direction_restriction: long_and_short
  max_trades_per_session: 1
  reentry:
    allowed: false
symbols:
- XAUUSD
test:
  name: {name}
  strategy: {name}
  broker: OctaFX
  timeframe: 15m
  start_date: '2024-01-01'
  end_date: '2026-03-01'
"""


def build_strategy(name, label, desc, is_stop_entry, is_range_stop, exit_h, exit_m, exit_label):
    sig = build_signature(is_stop_entry, is_range_stop, exit_h, exit_m, exit_label)
    sig_str = json.dumps(sig, indent=4, sort_keys=True)
    sig_str = sig_str.replace(": true", ": True").replace(": false", ": False")

    # Constants
    consts = []
    consts.append('_SESSION_START     = "01:00"')
    consts.append('_SESSION_END       = "07:00"')
    consts.append('_RANGE_QUALITY_MIN = 0.3')
    consts.append('_RANGE_QUALITY_MAX = 2.0')
    consts.append('_ALLOWED_REGIMES   = {0, 1}')
    if is_stop_entry:
        consts.append('_ENTRY_BUFFER      = 0.10    # 10 ticks')
    consts.append(f'_EXIT_HOUR_UTC     = {exit_h}')
    consts.append(f'_EXIT_MIN_UTC      = {exit_m}')
    consts_str = "\n".join(consts)

    # Init
    if is_range_stop:
        init_code = """    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        self._entry_price = None
        self._range_width = None"""
    else:
        init_code = """    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)"""

    # Entry logic
    if is_stop_entry:
        entry_code = ENTRY_STOP_BREAKOUT
    elif is_range_stop:
        entry_code = ENTRY_CLOSE_CONFIRM_RANGE_STOP
    else:
        entry_code = ENTRY_CLOSE_CONFIRM

    # Exit logic
    if is_range_stop:
        exit_code = EXIT_RANGE_STOP
    else:
        exit_code = EXIT_TIME_ONLY

    # Assemble - use string concatenation to avoid f-string brace issues
    parts = []
    parts.append('"""')
    parts.append(f'{name} -- Generated by Strategy Provisioner')
    parts.append(f'Timestamp: {TS}')
    parts.append(f'Directive: {name}')
    parts.append('')
    parts.append(f'Variant {label}: {desc}')
    parts.append('Baseline: P03 (London close 16:00 exit).')
    parts.append('"""')
    parts.append('')
    parts.append(IMPORTS_BLOCK)
    parts.append('')
    parts.append('# ---------------------------------------------------------------------------')
    parts.append('# Strategy constants')
    parts.append('# ---------------------------------------------------------------------------')
    parts.append(consts_str)
    parts.append('')
    parts.append('class Strategy:')
    parts.append('')
    parts.append('    # --- IDENTITY ---')
    parts.append(f'    name = "{name}"')
    parts.append('    timeframe = "15m"')
    parts.append('')
    parts.append('    # --- STRATEGY SIGNATURE START ---')
    parts.append(f'    STRATEGY_SIGNATURE = {sig_str}')
    parts.append('    # --- STRATEGY SIGNATURE END ---')
    parts.append('')
    parts.append(init_code)
    parts.append('')
    parts.append(PREPARE_BLOCK)
    parts.append('')
    parts.append(entry_code)
    parts.append('')
    parts.append(exit_code)
    parts.append('')

    return "\n".join(parts)


def main():
    created = 0
    for patch, label, desc, is_stop, is_range, exit_h, exit_m, exit_label in VARIANTS:
        name = f"{PREFIX}_{patch}"

        # Directive
        d_path = os.path.join(BASE, "backtest_directives", "active", f"{name}.txt")
        directive = build_directive(name, is_stop, is_range, exit_h, exit_m, exit_label)
        with open(d_path, 'w', newline='\n') as f:
            f.write(directive)
        print(f"[DIRECTIVE] {name}.txt")

        # Strategy directory
        s_dir = os.path.join(BASE, "strategies", name)
        os.makedirs(s_dir, exist_ok=True)

        # Strategy
        s_path = os.path.join(s_dir, "strategy.py")
        strategy = build_strategy(name, label, desc, is_stop, is_range, exit_h, exit_m, exit_label)
        with open(s_path, 'w', newline='\n') as f:
            f.write(strategy)
        print(f"[STRATEGY] {name}/strategy.py")
        created += 1

    print(f"\n[DONE] Generated {created} variants (P05-P11).")


if __name__ == "__main__":
    main()
