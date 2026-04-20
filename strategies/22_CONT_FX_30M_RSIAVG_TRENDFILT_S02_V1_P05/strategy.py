"""
22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05 - RSI(2) Average Pullback, FX 30M, Filtered
Locked filter: strong trend (|trend_regime|>=2) + low volatility + |score|>=2.
Exit change: max_bars=2 (bar-3 was net -$162 damage on filtered subset).
Bar 1 RSI exits: PF 2.95 (81% win). Bar 2 time exits: PF 2.54 (81% win).
Only bar 3 was destructive (PF 0.66, 43% win) — removed.
Filters routed through FilterStack: volatility_filter + trend_filter direction_gate.
"""

from indicators.momentum.rsi import rsi
from indicators.volatility.atr import atr
from engines.filter_stack import FilterStack
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime
import numpy as np


class Strategy:

    name = "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05"
    timeframe = "30m"

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
    "execution_rules": {
        "entry_when_flat_only": True,
        "pyramiding": False,
        "reset_on_exit": True,
        "stop_loss": {
            "atr_multiplier": 2.0,
            "type": "atr_multiple"
        },
        "take_profit": {
            "enabled": False
        },
        "trailing_stop": {
            "enabled": False
        }
    },
    "indicators": [
        "indicators.trend.linreg_regime",
        "indicators.trend.linreg_regime_htf",
        "indicators.trend.kalman_regime",
        "indicators.trend.trend_persistence",
        "indicators.trend.efficiency_ratio_regime",
        "indicators.momentum.rsi",
        "indicators.volatility.atr"
    ],
    "mean_reversion_rules": {
        "entry": {
            "avg_bars": 2,
            "long_threshold": 25,
            "min_abs_trend_score": 2,
            "rsi_period": 2,
            "short_threshold": 75
        },
        "exit": {
            "max_bars": 2,
            "rsi_exit_long": 75,
            "rsi_exit_short": 25
        }
    },
    "order_placement": {
        "execution_timing": "next_bar_open",
        "type": "market"
    },
    "signature_version": 2,
    "trade_management": {
        "direction_restriction": "none",
        "reentry": {
            "allowed": True
        }
    },
    "trend_filter": {
        "direction_gate": True,
        "enabled": True,
        "long_when": {
            "operator": "gte",
            "required_regime": 2
        },
        "short_when": {
            "operator": "lte",
            "required_regime": -2
        }
    },
    "version": 1,
    "volatility_filter": {
        "enabled": True,
        "operator": "eq",
        "required_regime": -1
    }
}
    # --- STRATEGY SIGNATURE END ---
    # --- SIGNATURE HASH: a5982fa77d0175e5 ---

    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)

    @staticmethod
    def _schema_sample() -> dict:
        return {
            "signal": 1,
            "stop_price": 1.0820,
            "entry_reference_price": 1.0850,
            "entry_reason": "rsiavg_oversold_long",
        }

    def prepare_indicators(self, df):
        cfg = self.STRATEGY_SIGNATURE["mean_reversion_rules"]["entry"]
        df["atr"] = atr(df, window=14)
        df["rsi_2"] = rsi(df["close"], period=cfg["rsi_period"])
        rsi_prev = df["rsi_2"].shift(1)
        df["rsi_2_avg"] = (df["rsi_2"] + rsi_prev) / cfg["avg_bars"]
        return df

    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        cfg = self.STRATEGY_SIGNATURE["mean_reversion_rules"]["entry"]

        # F3: trend_score guard
        trend_score = ctx.get("trend_score")
        if trend_score is None:
            return None

        rsi_avg = ctx.get("rsi_2_avg")
        close = ctx.get("close")

        # F1: ATR guard
        atr_val = ctx.get("atr")
        if rsi_avg is None or close is None or atr_val is None:
            return None
        if np.isnan(rsi_avg) or np.isnan(atr_val) or atr_val <= 0:
            return None

        atr_mult = self.STRATEGY_SIGNATURE["execution_rules"]["stop_loss"]["atr_multiplier"]

        # Long: strong uptrend + deeply oversold pullback
        if (trend_score >= cfg["min_abs_trend_score"]
                and rsi_avg < cfg["long_threshold"]):
            if not self.filter_stack.allow_direction(1):
                return None
            return {
                "signal": 1,
                "entry_reference_price": close,
                "stop_price": close - atr_val * atr_mult,
                "entry_reason": "rsiavg_oversold_long",
            }

        # Short: strong downtrend + deeply overbought bounce
        if (trend_score <= -cfg["min_abs_trend_score"]
                and rsi_avg > cfg["short_threshold"]):
            if not self.filter_stack.allow_direction(-1):
                return None
            return {
                "signal": -1,
                "entry_reference_price": close,
                "stop_price": close + atr_val * atr_mult,
                "entry_reason": "rsiavg_overbought_short",
            }

        return None

    def check_exit(self, ctx):
        cfg = self.STRATEGY_SIGNATURE["mean_reversion_rules"]["exit"]

        # Time exit: 2 bars (60 minutes on 30m)
        if ctx.bars_held >= cfg["max_bars"]:
            return True

        pos = ctx.direction
        if not pos:
            return False

        rsi_val = ctx.get("rsi_2")
        if rsi_val is None:
            return False

        # Long exit: RSI(2) reaches overbought
        if pos == 1 and rsi_val >= cfg["rsi_exit_long"]:
            return True

        # Short exit: RSI(2) reaches oversold
        if pos == -1 and rsi_val <= cfg["rsi_exit_short"]:
            return True

        return False

# --- CAPABILITY REQUIREMENTS START ---
REQUIRED_CAPABILITIES = [
    "execution.entry.v1",
    "execution.exit.v1",
]
REQUIRED_CONTRACT_IDS = [
    "sha256:962bfed53b6e7b4ce7de7feb70d614625ff7b576fe18441356fca501f0010cef",
]
# --- CAPABILITY REQUIREMENTS END ---
