"""
47_STR_FX_1H_CHOCH_S01_V3_P00 — Cross-Regime-Flip Probe Variant (FX basket)

Twin of 46_STR_XAU_1H_CHOCH_S01_V3_P00 for the FX 4-pair basket
(EURUSD, GBPUSD, USDJPY, AUDUSD). Identical logic — only asset scope
differs. Admits a trade ONLY when regime at signal bar differs from
regime at fill bar. Long-only, CHOCH_v2, ATR 1.5x SL / 3.0x TP,
next_bar_open fills. Pooled alongside 46_V3_P00 for rare-event sample.
"""

# --- IMPORTS (Deterministic from Directive) ---
from indicators.volatility.atr import atr
from indicators.structure.choch_v2 import choch_v2
from engines.filter_stack import FilterStack

class Strategy:

    # --- IDENTITY ---
    name = "47_STR_FX_1H_CHOCH_S01_V3_P00"
    timeframe = "1h"

    # --- PARAMETERS ---
    _ATR_WINDOW = 14
    _SL_ATR_MULT = 1.5
    _TP_ATR_MULT = 3.0

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
    "execution_rules": {
        "entry_logic": {
            "type": "choch_structural_break"
        },
        "entry_when_flat_only": True,
        "exit_logic": {
            "type": "sl_or_tp"
        },
        "pyramiding": False,
        "reset_on_exit": True,
        "stop_loss": {
            "atr_multiplier": 1.5,
            "type": "atr_multiple"
        },
        "take_profit": {
            "atr_multiplier": 3.0,
            "enabled": True,
            "type": "atr_multiple"
        },
        "trailing_stop": {
            "enabled": False
        }
    },
    "exit_rules": {
        "type": "sl_tp"
    },
    "indicators": [
        "indicators.volatility.atr",
        "indicators.structure.choch_v2"
    ],
    "order_placement": {
        "execution_timing": "next_bar_open",
        "type": "market"
    },
    "position_management": {
        "lots": 0.01
    },
    "regime_age_filter": {
        "enabled": 0,
        "exclude_max": 0,
        "exclude_min": 0
    },
    "signal_version": 10,
    "signature_version": 2,
    "state_machine": {
        "entry": {
            "direction": "long_only",
            "trigger": "signal_bar"
        },
        "no_reentry_after_stop": True,
        "session_reset": "none"
    },
    "trade_management": {
        "direction_restriction": "long_only",
        "reentry": {
            "allowed": True
        },
        "session_reset": "none"
    },
    "version": 1
}
    # --- STRATEGY SIGNATURE END ---
    # --- SIGNATURE HASH: 413d39c3f5053597 ---

    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)

    @staticmethod
    def _schema_sample() -> dict:
        return {
            "signal": 1,
            "stop_price": 0.0,
            "tp_price": 0.0,
            "entry_reference_price": 0.0,
            "entry_reason": "choch_v2_bullish_break_regime_flip",
        }

    def prepare_indicators(self, df):
        df['atr'] = atr(df, self._ATR_WINDOW)
        df = choch_v2(df)
        return df

    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None
        event = int(ctx.require('choch_event_v2'))
        if event != 1:
            return None  # long-only variant — suppress bearish CHOCH

        # --- CROSS-REGIME-FLIP FILTER (probe, 2026-04-14) ---
        # Admit the trade ONLY when the regime at the fill bar (N+1
        # under next_bar_open) differs from the regime at the signal
        # bar. regime_id_fill is emitted by run_stage1's patched_prepare
        # via shift(-1) on regime_id. Filter-only — never used for
        # signal construction.
        try:
            if ctx.require('regime_id') == ctx.require('regime_id_fill'):
                return None
        except RuntimeError:
            return None

        close = float(ctx.require('close'))
        atr_val = float(ctx.require('atr'))
        if atr_val <= 0 or not (atr_val == atr_val):
            return None
        reason = "choch_v2_bullish_break_regime_flip"
        return {
            "signal": event,
            "entry_reference_price": close,
            "entry_reason": reason,
        }

    def check_exit(self, ctx):
        return False
