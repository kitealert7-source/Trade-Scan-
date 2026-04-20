"""
22_CONT_FX_15M_RSIAVG_TRENDFILT_S07_V1_P02 - RSI(2) Average Pullback, FX 15M, Trend-Aligned + USD_SYNTH Z-Score Gate

Same as S07 P00 (Z>=1.5) but with max_bars=3 (tighter time exit).
Bars-held analysis showed bars 4-12 have negative expectancy.
  - Only take LONG when macro_allowed == 1 (USD overbought -> fade USD)
  - Only take SHORT when macro_allowed == -1 (USD oversold -> fade USD)
  - Skip entry when macro_allowed == 0 (neutral zone)
"""

from indicators.momentum.rsi import rsi
from indicators.volatility.atr import atr
from indicators.macro.usd_synth_zscore import usd_synth_zscore
from engines.filter_stack import FilterStack
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime
import numpy as np


class Strategy:

    name = "22_CONT_FX_15M_RSIAVG_TRENDFILT_S07_V1_P02_EURUSD"
    timeframe = "15m"

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
        "indicators.volatility.atr",
        "indicators.macro.usd_synth_zscore"
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
            "max_bars": 3,
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
    "version": 1
}
    # --- STRATEGY SIGNATURE END ---
    # --- SIGNATURE HASH: 3b3a8fa62c20c6a0 ---

    _Z_LOOKBACK  = 100
    _Z_THRESHOLD = 1.5

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

        # ----- MACRO DIRECTION FILTER: USD_SYNTH Z-Score (indicator module) -----
        df = usd_synth_zscore(df, lookback=self._Z_LOOKBACK, threshold=self._Z_THRESHOLD)

        return df

    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        cfg = self.STRATEGY_SIGNATURE["mean_reversion_rules"]["entry"]

        # Macro direction gate: skip entry in neutral zone
        macro = ctx.get("macro_allowed", 0)
        if macro == 0:
            return None

        trend_score = ctx.get("trend_score")
        if trend_score is None:
            return None

        rsi_avg = ctx.get("rsi_2_avg")
        close = ctx.get("close")

        atr_val = ctx.get("atr")
        if rsi_avg is None or close is None or atr_val is None:
            return None
        if np.isnan(rsi_avg) or np.isnan(atr_val) or atr_val <= 0:
            return None

        # Long: strong uptrend + deeply oversold pullback + macro allows long
        if (macro == 1
                and trend_score >= cfg["min_abs_trend_score"]
                and rsi_avg < cfg["long_threshold"]):
            return {
                "signal": 1,
                "entry_reference_price": close,
                "entry_reason": "rsiavg_oversold_long",
            }

        # Short: strong downtrend + deeply overbought bounce + macro allows short
        if (macro == -1
                and trend_score <= -cfg["min_abs_trend_score"]
                and rsi_avg > cfg["short_threshold"]):
            return {
                "signal": -1,
                "entry_reference_price": close,
                "entry_reason": "rsiavg_overbought_short",
            }

        return None

    def check_exit(self, ctx):
        cfg = self.STRATEGY_SIGNATURE["mean_reversion_rules"]["exit"]

        if ctx.bars_held >= cfg["max_bars"]:
            return True

        pos = ctx.direction
        if not pos:
            return False

        rsi_val = ctx.get("rsi_2")
        if rsi_val is None:
            return False

        if pos == 1 and rsi_val >= cfg["rsi_exit_long"]:
            return True
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
