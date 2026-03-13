"""
S10_V1_P00: Limit entry at k=0.05*ATR below/above signal close. limit_expiry_bars=2.
"""
from indicators.trend.linreg_regime import linreg_regime
from indicators.trend.linreg_regime_htf import linreg_regime_htf
from indicators.trend.kalman_regime import kalman_regime
from indicators.trend.trend_persistence import trend_persistence
from indicators.trend.efficiency_ratio_regime import efficiency_ratio_regime
from indicators.momentum.ultimate_c_percent import ultimate_c_percent
from indicators.momentum.rsi import rsi
from indicators.volatility.volatility_regime import volatility_regime
from indicators.volatility.atr import atr
from indicators.stats.rolling_zscore import rolling_zscore
from engines.filter_stack import FilterStack
from datetime import datetime

class Strategy:

    # --- IDENTITY ---
    name = "01_MR_FX_1H_ULTC_REGFILT_S10_V1_P00"
    timeframe = "1h"

    BLOCKED_UTC_HOURS = {14, 18}
    ENFORCE_NORMAL_VOL_SYMBOLS = {"AUDUSD", "NZDUSD"}
    COOLDOWN_BARS = 1
    ZSCORE_WINDOW = 100
    TP_ZSCORE_ABS = 0.40
    RSI_PERIOD = 2
    RSI_EXIT_UPPER = 75.0
    RSI_EXIT_LOWER = 25.0
    EXIT_MODE = "HYBRID"
    COMPONENT_FIELDS = ("linreg_regime_htf", "kalman_regime")
    MAX_ABS_COMPONENT_SCORE = 0

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
    "execution_rules": {
        "stop_loss": {
            "multiple": 1.35,
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
        "indicators.momentum.ultimate_c_percent",
        "indicators.momentum.rsi",
        "indicators.volatility.volatility_regime",
        "indicators.volatility.atr",
        "indicators.stats.rolling_zscore"
    ],
    "mean_reversion_rules": {
        "entry": {
            "limit_entry_k": 0.05,
            "limit_expiry_bars": 2,
            "long": {
                "max_abs_trend_score": 1,
                "ultimate_signal": -1
            },
            "short": {
                "max_abs_trend_score": 1,
                "ultimate_signal": 1
            }
        },
        "exit": {
            "max_bars": 20,
            "min_bars_before_exit": 3,
            "type": "opposite_signal_or_time"
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
    }
}
    # --- STRATEGY SIGNATURE END ---

    def __init__(self):
        self.filter_stack = FilterStack(self.STRATEGY_SIGNATURE)
        mr = self.STRATEGY_SIGNATURE.get("mean_reversion_rules", {})
        entry = mr.get("entry", {})
        exit_cfg = mr.get("exit", {})
        stop_cfg = self.STRATEGY_SIGNATURE.get("execution_rules", {}).get("stop_loss", {})
        self.long_signal = entry.get("long", {}).get("ultimate_signal", -1)
        self.short_signal = entry.get("short", {}).get("ultimate_signal", 1)
        self.max_abs_trend = entry.get("long", {}).get("max_abs_trend_score", 1)
        self.max_bars = int(exit_cfg.get("max_bars", 20))
        self.min_bars_before_exit = int(exit_cfg.get("min_bars_before_exit", 0))
        self.atr_multiple = float(stop_cfg.get("multiple", 1.35))
        self.limit_entry_k = float(entry.get("limit_entry_k", 0))
        self.limit_expiry_bars = int(entry.get("limit_expiry_bars", 0))
        self.pending_limit_price = None
        self.pending_limit_direction = 0
        self.pending_limit_bars_left = 0
        self.session_low = None
        self.session_high = None
        self.last_exit_index = -10**9
        self.active_symbol = None

    def prepare_indicators(self, df):
        df["atr"] = atr(df, window=14)
        vol_df = volatility_regime(df["atr"], window=100)
        df["volatility_regime"] = vol_df["regime"]
        uc_df = ultimate_c_percent(df)
        df["ultimate_signal"] = uc_df["ultimate_signal"]
        df["rsi_2"] = rsi(df["close"], period=self.RSI_PERIOD)
        df["zscore_50"] = rolling_zscore(df["close"], window=self.ZSCORE_WINDOW)
        if "symbol" in df.columns and len(df) > 0:
            self.active_symbol = str(df["symbol"].iloc[0]).upper()
        return df

    def _entry_hour_utc(self, row):
        ts = getattr(row, "name", None)
        if ts is None:
            ts = row.get("timestamp")
        if ts is None:
            return None
        hour = getattr(ts, "hour", None)
        if hour is not None:
            return int(hour)
        try:
            return int(datetime.fromisoformat(str(ts)).hour)
        except Exception:
            return None

    def _mark_exit(self, ctx):
        idx = getattr(ctx, "index", None)
        if idx is not None:
            self.last_exit_index = idx
        return True

    def _component_score(self, row):
        score = 0
        for field in self.COMPONENT_FIELDS:
            val = row.get(field, None)
            if val is None:
                return None
            try:
                score += int(val)
            except Exception:
                return None
        return score

    def _clear_pending(self):
        self.pending_limit_price = None
        self.pending_limit_direction = 0
        self.pending_limit_bars_left = 0

    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None

        row = ctx.row
        direction = ctx.direction

        # --- Pending limit order logic ---
        if self.pending_limit_bars_left > 0:
            self.pending_limit_bars_left -= 1
            if self.pending_limit_direction == 1:
                low_price = row.get("low")
                if low_price is not None and low_price <= self.pending_limit_price:
                    limit_fill_price = self.pending_limit_price
                    atr_val = row.get("atr", 0.0)
                    if atr_val and atr_val > 0:
                        risk_dist = atr_val * self.atr_multiple
                        self.session_low = limit_fill_price - risk_dist
                        self.session_high = None
                    self._clear_pending()
                    return {"signal": 1}
            elif self.pending_limit_direction == -1:
                high_price = row.get("high")
                if high_price is not None and high_price >= self.pending_limit_price:
                    limit_fill_price = self.pending_limit_price
                    atr_val = row.get("atr", 0.0)
                    if atr_val and atr_val > 0:
                        risk_dist = atr_val * self.atr_multiple
                        self.session_high = limit_fill_price + risk_dist
                        self.session_low = None
                    self._clear_pending()
                    return {"signal": -1}
            # If bars_left just hit 0 after decrement, clear pending and fall through to new signal check
            if self.pending_limit_bars_left <= 0:
                self._clear_pending()
            else:
                return None

        # --- Normal entry signal check ---
        ult_sig = row.get("ultimate_signal", 0)
        atr_val = row.get("atr", 0.0)
        if atr_val is None or atr_val <= 0:
            return None
        comp_score = self._component_score(row)
        if comp_score is None:
            return None
        if abs(comp_score) > self.MAX_ABS_COMPONENT_SCORE:
            return None
        linreg_htf = row.get("linreg_regime_htf")
        vol_regime = str(row.get("volatility_regime", "")).lower()
        try:
            if linreg_htf is None:
                return None
            if abs(int(linreg_htf)) == 1 and vol_regime == "low":
                return None
        except Exception:
            return None
        hour = self._entry_hour_utc(row)
        if hour is not None and hour in self.BLOCKED_UTC_HOURS:
            return None
        symbol = row.get("symbol")
        if symbol is None:
            symbol = self.active_symbol
        if symbol is not None:
            symbol = str(symbol).upper()
            if symbol in self.ENFORCE_NORMAL_VOL_SYMBOLS:
                if str(row.get("volatility_regime", "")).lower() != "normal":
                    return None
        idx = getattr(ctx, "index", None)
        if self.COOLDOWN_BARS > 0 and idx is not None:
            if idx - self.last_exit_index <= self.COOLDOWN_BARS:
                return None

        close_price = row.get("close")

        if ult_sig == self.long_signal and direction != 1:
            if self.limit_entry_k > 0:
                # Set pending limit below close
                self.pending_limit_price = close_price - self.limit_entry_k * atr_val
                self.pending_limit_direction = 1
                self.pending_limit_bars_left = self.limit_expiry_bars
                return None
            else:
                risk_dist = atr_val * self.atr_multiple
                self.session_low = close_price - risk_dist
                self.session_high = None
                return {"signal": 1}

        if ult_sig == self.short_signal and direction != -1:
            if self.limit_entry_k > 0:
                # Set pending limit above close
                self.pending_limit_price = close_price + self.limit_entry_k * atr_val
                self.pending_limit_direction = -1
                self.pending_limit_bars_left = self.limit_expiry_bars
                return None
            else:
                risk_dist = atr_val * self.atr_multiple
                self.session_high = close_price + risk_dist
                self.session_low = None
                return {"signal": -1}

        return None

    def check_exit(self, ctx):
        row = ctx.row
        direction = ctx.direction
        if direction == 0:
            return False

        bars_held = getattr(ctx, "bars_held", 0)
        current_price = row.get("close")

        # ATR stop-loss — always fires regardless of min_bars
        if direction == 1 and self.session_low is not None and current_price < self.session_low:
            return self._mark_exit(ctx)
        if direction == -1 and self.session_high is not None and current_price > self.session_high:
            return self._mark_exit(ctx)

        # Time exit — always fires
        if bars_held >= self.max_bars:
            return self._mark_exit(ctx)

        # Opposite signal exit — always fires
        ult_sig = row.get("ultimate_signal", 0)
        if direction == 1 and ult_sig == self.short_signal:
            return self._mark_exit(ctx)
        if direction == -1 and ult_sig == self.long_signal:
            return self._mark_exit(ctx)

        # RSI and Z-score soft exits — blocked until min_bars_before_exit satisfied
        if bars_held < self.min_bars_before_exit:
            return False

        zscore = row.get("zscore_50")
        z = None
        if zscore is not None:
            try:
                z = float(zscore)
            except Exception:
                z = None
        rsi_2_val = row.get("rsi_2")
        r2 = None
        if rsi_2_val is not None:
            try:
                r2 = float(rsi_2_val)
            except Exception:
                r2 = None
        zscore_exit = False
        rsi_exit = False
        mode = str(self.EXIT_MODE).upper()
        if mode in {"BASE", "HYBRID"} and z is not None:
            if direction == 1 and z >= self.TP_ZSCORE_ABS:
                zscore_exit = True
            if direction == -1 and z <= -self.TP_ZSCORE_ABS:
                zscore_exit = True
        if mode in {"HYBRID", "PURE_RSI"} and r2 is not None:
            if direction == 1 and r2 >= self.RSI_EXIT_UPPER:
                rsi_exit = True
            if direction == -1 and r2 <= self.RSI_EXIT_LOWER:
                rsi_exit = True
        if zscore_exit or rsi_exit:
            return self._mark_exit(ctx)
        return False
