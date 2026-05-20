"""cointegration_meanrev_v1.py — COINTREV mean-reversion basket rule.

A LONG-SHORT spread basket rule for cointegrated FX pair-pairs. Distinct
from H3_spread@1/@2 (which pyramids into trend-following winners) and
H2_recycle@1-5 (which manages USD-cancelling LONG-LONG baskets):
COINTREV manages a single round-trip mean-reversion trade per signal,
with NO pyramiding and three explicit exit conditions.

Hypothesis (concept-validation 2026-05-20, event study + operator review)
------------------------------------------------------------------------
For FX pair-pairs that are structurally cointegrated (daily-TF ADF p
<0.05 in BOTH 252d AND 504d windows — qualified_daily=True) and currently
dislocated (15m |z| ≥ entry_z), the spread tends to revert toward
its local mean within hours-to-days. Capture by:

  - opening LONG-SHORT spread basket on 15m |z| crossing (leg strategy)
  - holding for reversion (this rule)
  - exiting on first of: 15m |z| ≤ exit_z (winner), 15m |z| ≥ stop_z
    (stop), or `time_stop_bars` elapsed (drift exhaustion)

NO pyramiding — single round-trip per signal. After exit, leg strategy
resumes watching for next signal. Brokerage spreads already in OctaFx
prices, so we model none.

Required factors
----------------
  intra_z         (float) — 15m z-score of spread, joined onto leg.df
                            by basket_data_loader at backtest time
  qualified_daily (bool)  — daily cointegration regime forward-filled
                            from coint_1d_history_matrix_<HASH>.parquet

Mechanic (per bar, priority order)
----------------------------------
  1. TIME STOP: liquidate if elapsed bars ≥ time_stop_bars
  2. STOP_LOSS: directional — for short-spread entry (z>0 at open),
     stop if intra_z >= +stop_z (spread blew higher); for long-spread
     entry (z<0 at open), stop if intra_z <= -stop_z (spread blew lower)
  3. REVERSION: liquidate if |intra_z| ≤ exit_z (winner — back to normal)

Exits use the same `_liquidate` flow as h3_spread_v1 — close all legs at
bar-close, realize PnL, reset state. Leg strategy re-arms on the next
qualified 15m |z|≥entry_z crossing.

v1 limitations
--------------
- Bar-close P&L only for stop loss (no intra-bar OHLC). Engine v1_5_8
  intrabar machinery would tighten this; deferred to v1.1.
- Equal-lot sizing (matches 90-series convention); no β-weighting.
- No qualification recheck during the trade (we assume daily-qualified
  at entry implies the structural relationship holds through the
  short holding period; event study showed 92-100% regime degradation
  on multi-week holds, but at our 48h time-stop the proportion that
  break MID-TRADE should be much lower).

Reference
---------
- Concept spec: outputs/cointegration_screener_v1/phase_c0/PHASE_C0_MANIFEST.md
- Event study: outputs/cointegration_screener_v1/event_study/EVENT_STUDY_REPORT.md
- Template: tools/recycle_rules/h3_spread_v1.py (structurally — without pyramid)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle import H2RecycleRule
from tools.recycle_rules.h2_recycle_v3 import (
    _build_ref_closes,
    _leg_pnl_usd,
    _leg_margin_usd,
)


_RULE_NAME = "COINTREV_meanrev"
_RULE_VERSION = 1


@dataclass
class CointMeanRevV1Rule(H2RecycleRule):
    """Single-cycle cointegration mean-reversion basket rule.

    Inherits from H2RecycleRule for parquet emission + recycle_events list
    machinery. Overrides apply() entirely with COINTREV logic.
    """

    # --- COINTREV params (new) ---
    entry_z: float = 2.0
    exit_z: float = 1.0
    stop_z: float = 4.0
    time_stop_bars: int = 192          # 48 hours at 15m TF
    initial_notional_usd: float = 1000.0
    intra_z_column: str = "intra_z"    # column on leg.df with 15m z-score
    qualified_column: str = "qualified_daily"
    # Optional matrix hash pin (informational; basket_data_loader resolves)
    matrix_hash: str = ""

    # --- Name + version overrides ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- Per-cycle state ---
    _basket_open: bool = False
    _entry_bar_idx: Optional[int] = None
    _entry_z_at_open: float = 0.0
    _n_liquidations: int = 0
    _n_reversion_exits: int = 0
    _n_stop_exits: int = 0
    _n_time_exits: int = 0
    _cycle_peak_floating: float = 0.0
    _peak_equity: float = 0.0

    # Back-reference (populated by BasketRunner.__init__)
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # COINTREV-specific param validation.
        if not (0.0 < self.exit_z < self.entry_z < self.stop_z):
            raise ValueError(
                f"CointMeanRevV1Rule requires 0 < exit_z < entry_z < stop_z; "
                f"got exit_z={self.exit_z!r}, entry_z={self.entry_z!r}, "
                f"stop_z={self.stop_z!r}."
            )
        if self.time_stop_bars <= 0:
            raise ValueError(
                f"CointMeanRevV1Rule.time_stop_bars must be > 0; "
                f"got {self.time_stop_bars!r}."
            )
        if self.initial_notional_usd <= 0:
            raise ValueError(
                f"CointMeanRevV1Rule.initial_notional_usd must be > 0; "
                f"got {self.initial_notional_usd!r}."
            )

        # Manually initialize parent attributes that _record_bar reads
        # but our flow doesn't update (we don't pyramid or use compression).
        self.realized_total = 0.0
        self.harvested = False
        self.recycle_events: list[dict[str, Any]] = []
        self.per_bar_records: list[dict[str, Any]] = []
        self._first_bar_ts: Optional[pd.Timestamp] = None
        self._n_dd_freezes: int = 0
        self._n_margin_freezes: int = 0
        self._n_regime_freezes: int = 0
        # Parent attributes required by parent's machinery:
        self.trigger_usd = 10.0
        self.add_lot = 0.0                   # no adds for COINTREV
        self.starting_equity = self.initial_notional_usd
        self.harvest_target_usd = 1e12       # effectively disabled
        self.equity_floor_usd = None
        self.time_stop_days = None
        self.dd_freeze_frac = 0.999          # disabled
        self.margin_freeze_frac = 0.999      # disabled
        self.leverage = 1000.0
        self.factor_column = ""              # no factor gate
        self.factor_min = 0.0
        self.factor_operator = ">="

        self._peak_equity = self.starting_equity
        self.summary_stats: dict[str, Any] = {
            "peak_floating_dd_usd":         0.0,
            "peak_floating_dd_pct":         0.0,
            "dd_freeze_count":              0,
            "margin_freeze_count":          0,
            "regime_freeze_count":          0,
            "peak_margin_used_usd":         0.0,
            "min_margin_level_pct":         float("inf"),
            "worst_floating_at_freeze_usd": 0.0,
            "peak_lots":                    {},
            "final_pnl_usd":                None,
            "return_on_real_capital_pct":   None,
            "harvest_bar_index":            None,
            "harvest_bar_ts":               None,
            "harvest_reason":               None,
        }

    # ---- core mechanic ---------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self.harvested:
            return
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        all_open = all(leg.state.in_pos for leg in legs)

        bar_closes: dict[str, float] = {}
        try:
            for leg in legs:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
        except (KeyError, ValueError):
            return  # data gap

        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (_leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                         if leg.state.in_pos else 0.0)
            for leg in legs
        }
        floating_total = sum(leg_float.values())

        # Newly opened — lock entry bar
        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            self._cycle_peak_floating = 0.0
            try:
                self._entry_z_at_open = float(
                    legs[0].df.loc[bar_ts, self.intra_z_column])
            except (KeyError, ValueError, TypeError):
                self._entry_z_at_open = 0.0
            self.recycle_events.append({
                "bar_index": i,
                "bar_ts": bar_ts,
                "action": "BASKET_OPEN",
                "entry_z": self._entry_z_at_open,
                "initial_lots": dict(self.basket_runner._initial_lots)
                if self.basket_runner is not None else {},
                "leg_directions": {l.symbol: l.direction for l in legs},
            })

        if not all_open:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        if floating_total > self._cycle_peak_floating:
            self._cycle_peak_floating = floating_total

        # ---- Exit checks (priority order) -------------------------------

        # 1. TIME STOP
        elapsed = i - (self._entry_bar_idx or i)
        if elapsed >= self.time_stop_bars:
            self._n_time_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                             floating_total, reason="TIME_STOP")
            return

        # 2/3 — read current 15m z-score
        try:
            intra_z = float(legs[0].df.loc[bar_ts, self.intra_z_column])
        except (KeyError, ValueError, TypeError):
            # Without a valid z-score we can't evaluate stop/reversion;
            # hold this bar and let next bar try again.
            self._emit_record(legs, i, bar_ts, bar_closes, leg_float,
                                floating_total, skip_reason="Z_UNAVAILABLE")
            return

        abs_z = abs(intra_z)

        # 2. STOP LOSS — DIRECTIONAL.
        # Short-spread entry: opened when z >= +entry_z (betting reversion DOWN).
        #   Stop fires when z continues UP through +stop_z.
        # Long-spread entry: opened when z <= -entry_z (betting reversion UP).
        #   Stop fires when z continues DOWN through -stop_z.
        # _entry_z_at_open carries the SIGN of the entry-side z.
        if self._entry_z_at_open > 0 and intra_z >= self.stop_z:
            self._n_stop_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                             floating_total, reason="STOP_LOSS")
            return
        if self._entry_z_at_open < 0 and intra_z <= -self.stop_z:
            self._n_stop_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                             floating_total, reason="STOP_LOSS")
            return

        # 3. REVERSION (|z| back inside exit_z — winning exit)
        if abs_z <= self.exit_z:
            self._n_reversion_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                             floating_total, reason="REVERSION_EXIT")
            return

        # Hold — no action
        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )

    # ---- Liquidation -----------------------------------------------------

    def _liquidate(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, reason: str,
    ) -> None:
        """Close all legs at bar close. NO soft_reset_basket — leg strategy
        re-opens on next signal naturally."""
        if self.basket_runner is None:
            raise RuntimeError(
                "CointMeanRevV1Rule._liquidate: basket_runner is None.")

        realized_pnl = floating_total
        self.realized_total += realized_pnl

        for leg in legs:
            if not leg.state.in_pos:
                continue
            exit_trade = {
                "entry_index": leg.state.entry_index,
                "entry_price": leg.state.entry_price,
                "exit_index": i,
                "exit_price": bar_closes[leg.symbol],
                "direction": leg.direction,
                "lot": leg.lot,
                "exit_source": f"BASKET_RULE_{reason}",
                "exit_timestamp": bar_ts,
            }
            leg.trades.append(exit_trade)
            leg.state.in_pos = False
            leg.state.direction = 0
            leg.state.pending_entry = None
            # Reset lot to initial (next cycle starts at initial size).
            leg.lot = self.basket_runner._initial_lots[leg.symbol]

        self._n_liquidations += 1
        self._basket_open = False
        self._entry_bar_idx = None
        self._cycle_peak_floating = 0.0
        self._entry_z_at_open = 0.0

        self.recycle_events.append({
            "bar_index": i,
            "bar_ts": bar_ts,
            "action": "LIQUIDATE",
            "reason": reason,
            "realized_pnl_usd": realized_pnl,
            "cumulative_realized_usd": self.realized_total,
            "exit_prices": dict(bar_closes),
        })

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason=f"LIQUIDATE_{reason}",
        )

    # ---- Per-bar record (1.3.0-basket 35-col fixed schema) --------------

    def _emit_record(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, skip_reason: str,
        *,
        recycle_attempted: bool = False,
        recycle_executed: bool = False,
    ) -> None:
        equity = self.starting_equity + self.realized_total + floating_total
        if equity > self._peak_equity:
            self._peak_equity = equity
        dd_from_peak_usd = equity - self._peak_equity
        dd_from_peak_pct = (
            dd_from_peak_usd / self._peak_equity * 100.0
            if self._peak_equity > 0 else 0.0
        )

        ref_closes = _build_ref_closes(legs, bar_ts)
        margin_used = 0.0
        notional_total = 0.0
        per_leg_margin: dict[str, float] = {}
        per_leg_notional: dict[str, float] = {}
        for leg in legs:
            bc = bar_closes.get(leg.symbol, float("nan"))
            if bc != bc or not leg.state.in_pos:
                per_leg_margin[leg.symbol] = 0.0
                per_leg_notional[leg.symbol] = 0.0
                continue
            m = _leg_margin_usd(leg, bc, self.leverage, ref_closes)
            per_leg_margin[leg.symbol] = m
            margin_used += m
            n = m * self.leverage
            per_leg_notional[leg.symbol] = n
            notional_total += n

        free_margin = equity - margin_used
        margin_level_pct = (equity / margin_used * 100.0) if margin_used > 0 else float("nan")

        in_pos_lots = [leg.lot for leg in legs if leg.state.in_pos]
        active_legs = len(in_pos_lots)
        total_lot = sum(in_pos_lots) if in_pos_lots else 0.0
        largest_leg_lot = max(in_pos_lots) if in_pos_lots else 0.0
        smallest_leg_lot = min(in_pos_lots) if in_pos_lots else 0.0

        bars_since_last_recycle = None   # COINTREV has no pyramids
        bars_since_last_harvest = (
            (i - self._entry_bar_idx) if self._entry_bar_idx is not None else 0
        )

        record: dict[str, Any] = {
            # Block A — Time/identity (5)
            "timestamp":               bar_ts,
            "directive_id":            self.directive_id,
            "basket_id":               self.basket_id,
            "bar_index":               i,
            "run_id":                  self.run_id,
            # Block B — Equity state (6)
            "floating_total_usd":      floating_total,
            "realized_total_usd":      self.realized_total,
            "equity_total_usd":        equity,
            "peak_equity_usd":         self._peak_equity,
            "dd_from_peak_usd":        dd_from_peak_usd,
            "dd_from_peak_pct":        dd_from_peak_pct,
            # Block C — Margin/capital state (5)
            "margin_used_usd":         margin_used,
            "free_margin_usd":         free_margin,
            "margin_level_pct":        margin_level_pct,
            "notional_total_usd":      notional_total,
            "leverage_effective":      self.leverage,
            # Block D — Engine control state (8). COINTREV has no
            # DD/margin/regime gates.
            "dd_freeze_active":        False,
            "margin_freeze_active":    False,
            "regime_gate_blocked":     False,
            "recycle_attempted":       recycle_attempted,
            "recycle_executed":        recycle_executed,
            "harvest_triggered":       False,
            "engine_paused":           False,
            "skip_reason":             skip_reason,
            # Block E — Position state (4)
            "active_legs":             active_legs,
            "total_lot":               total_lot,
            "largest_leg_lot":         largest_leg_lot,
            "smallest_leg_lot":        smallest_leg_lot,
            # Block G — Strategy state (7)
            "recycle_count":           0,                 # COINTREV never pyramids
            "bars_since_last_recycle": bars_since_last_recycle,
            "bars_since_last_harvest": bars_since_last_harvest,
            "gate_factor_value":       float("nan"),
            "gate_factor_name":        self.factor_column,
            "winner_leg_idx":          None,
            "loser_leg_idx":           None,
        }

        # Block F — per-leg state
        for idx, leg in enumerate(legs):
            bc = bar_closes.get(leg.symbol, float("nan"))
            record[f"leg_{idx}_symbol"]       = leg.symbol
            record[f"leg_{idx}_side"]         = "long" if leg.direction == 1 else "short"
            record[f"leg_{idx}_lot"]          = leg.lot
            record[f"leg_{idx}_avg_entry"]    = leg.state.entry_price
            record[f"leg_{idx}_mark"]         = bc
            record[f"leg_{idx}_floating_usd"] = leg_float.get(leg.symbol, 0.0)
            record[f"leg_{idx}_margin_usd"]   = per_leg_margin.get(leg.symbol, 0.0)
            record[f"leg_{idx}_notional_usd"] = per_leg_notional.get(leg.symbol, 0.0)

        self.per_bar_records.append(record)

        # Running summary_stats aggregates
        stats = self.summary_stats
        if dd_from_peak_usd < stats["peak_floating_dd_usd"]:
            stats["peak_floating_dd_usd"] = dd_from_peak_usd
            stats["peak_floating_dd_pct"] = dd_from_peak_pct
        if margin_used > stats["peak_margin_used_usd"]:
            stats["peak_margin_used_usd"] = margin_used
        if margin_used > 0 and not pd.isna(margin_level_pct):
            if margin_level_pct < stats["min_margin_level_pct"]:
                stats["min_margin_level_pct"] = margin_level_pct
        for leg in legs:
            prev = stats["peak_lots"].get(leg.symbol, 0.0)
            if leg.lot > prev:
                stats["peak_lots"][leg.symbol] = leg.lot


__all__ = ["CointMeanRevV1Rule"]
