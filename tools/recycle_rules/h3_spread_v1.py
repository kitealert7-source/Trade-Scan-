"""h3_spread_v1.py - H3_spread@1: LONG-SHORT spread basket rule.

Distinct from H2_recycle@1-5 (which manage LONG-LONG / EURJPY-synthetic
baskets via leg-asymmetric loser-driven mechanics). This rule manages
LONG-SHORT pair-spread baskets (e.g. LONG EURUSD + SHORT USDJPY for a
USD-bear bet) where both legs share USD on opposite sides and basket
P&L isolates USD-direction.

Hypothesis (2026-05-18)
-----------------------
After a z-normalized SMA crossover between two USD-anchored pairs, the
USD-direction spread tends to drift in the current macro regime
direction. We capture this by:
  - opening the spread basket on a cross signal (handled by
    SpreadCrossLegStrategy on each leg)
  - holding while the regime persists
  - pyramiding into winners (anti-Martingale) when basket P&L extends favorably
  - exiting on: reverse cross (regime flip), adverse basket P&L threshold,
    or time stop (drift exhaustion)

Mechanic
--------
On each bar (in priority order):
  1. TIME STOP: liquidate if elapsed bars since entry >= time_stop_bars
  2. ADVERSE STOP: liquidate if basket floating P&L <= adverse_stop_pct
     of initial_notional_usd (negative threshold)
  3. REVERSE CROSS: liquidate if leg.df[bar_ts].cross_side != entry_direction
     (regime flip detected by feature inversion)
  4. PYRAMID: if basket_pnl_pct >= next pyramid level threshold AND
     we haven't already pyramided to that level, add `pyramid_add_lot`
     to BOTH legs preserving their initial directions

Exits use soft_reset_basket primitive to close + reopen at initial lots.
The leg strategy (SpreadCrossLegStrategy) re-enters on the NEXT matching
cross signal — so the basket continues but only takes new positions when
the signal fires again.

Parameters
----------
pyramid_level_pcts: list[float]
    Basket P&L thresholds (as % of initial notional) at which pyramids fire.
    Default [0.15, 0.30] = first add at +0.15%, second at +0.30%.
pyramid_add_lot: float
    Lot to add to each leg per pyramid event. Default 0.05
    (= 50% of initial 0.10 leg lot → 2x final exposure after 2 levels).
adverse_stop_pct: float
    Basket-level adverse stop as fraction of initial notional. Default 0.0020
    (= -0.20% loss triggers liquidation).
time_stop_bars: int
    Maximum bars in position before liquidation. Default 288 (3 days at 15m).
reverse_cross_column: str
    Column on leg.df carrying the cross_side signal. Default "cross_side".
entry_direction: int
    Basket's directional intent: +1 = first leg long & second leg short
    (USD-bear); -1 = first leg short & second leg long (USD-bull). Matches
    the BasketLeg.direction set at construction.
initial_notional_usd: float
    Reference notional used to express adverse_stop_pct + pyramid_level_pcts
    as fractions. Default 1000.0 (matches starting_equity).
v2 limitations
--------------
- Bar-close P&L only for adverse stop (no intra-bar OHLC resolution).
  Will be enhanced in v2 using engine v1_5_8's unrealized_r_intrabar.
- Pyramid adds to BOTH legs uniformly (preserves spread structure).
  An asymmetric variant (add only to the better-performing leg) is a v2 option.

Reference
---------
Session brief 2026-05-18; design notes in conversation transcript.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle import H2RecycleRule
from tools.recycle_rules.h2_recycle_v3 import (
    _build_ref_closes,
    _leg_pnl_usd,
    _leg_margin_usd,
)

# 1.3.0-basket per-leg suffixes — mirrors tools.basket_report._PER_LEG_SUFFIXES.
# Kept literal here so we don't import a downstream module just for a tuple.
_PER_LEG_SUFFIXES = (
    "symbol", "side", "lot", "avg_entry", "mark",
    "floating_usd", "margin_usd", "notional_usd",
)


_RULE_NAME = "H3_spread"
_RULE_VERSION = 1


@dataclass
class H3SpreadV1Rule(H2RecycleRule):
    """LONG-SHORT spread basket rule (H3 family).

    Inherits from H2RecycleRule for parquet emission + recycle_events list
    machinery. Overrides apply() entirely with spread-basket logic. The
    inherited compression-gate / harvest / floor params are present but
    unused by this rule's flow (kept for parquet schema compatibility).
    """

    # --- H3 spread params (new) ---
    pyramid_level_pcts: tuple[float, ...] = (0.15, 0.30)
    pyramid_add_lot: float = 0.05
    adverse_stop_pct: float = 0.0020   # = 0.20% of initial notional
    time_stop_bars: int = 288
    reverse_cross_column: str = "cross_side"
    entry_direction: int = +1          # +1 = first-leg-long; -1 = first-leg-short
    initial_notional_usd: float = 1000.0
    # Peak-relative trailing stop (2026-05-18). Arms once cycle running-peak
    # floating exceeds `trail_arm_floating_usd`. Once armed, liquidates when
    # current floating retraces by `trail_retrace_pct`% of the running peak.
    # Both default 0.0 (= disabled) so existing directives (P00-P03) behave
    # byte-identically. Evaluated AFTER adverse-stop and BEFORE reverse-cross.
    trail_arm_floating_usd: float = 0.0
    trail_retrace_pct: float = 0.0     # 50.0 = exit at 50% retrace from peak

    # --- Name + version overrides (parent fields) ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- Per-cycle state ---
    _basket_open: bool = False          # True once both legs have opened
    _entry_bar_idx: Optional[int] = None
    _next_pyramid_level: int = 0        # index into pyramid_level_pcts
    _n_pyramids_total: int = 0
    _n_liquidations: int = 0
    _n_adverse_stops: int = 0
    _n_reverse_cross_exits: int = 0
    _n_time_stops: int = 0
    _n_trail_stops: int = 0
    # Running max floating since cycle open; reset on each liquidation.
    # Drives the peak-relative trail-stop logic.
    _cycle_peak_floating: float = 0.0
    # 1.3.0-basket ledger tracking (running peaks consumed inside _emit_record).
    _peak_equity_h3: float = 0.0
    _last_pyramid_bar: Optional[int] = None

    # --- Back-reference (populated by BasketRunner.__init__) ---
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # Skip parent validation entirely — our schema is different. Keep
        # inherited attributes initialized to default values so the parent's
        # _record_bar machinery still works.
        # Validate H3-specific params.
        if not (0.0 < self.adverse_stop_pct < 1.0):
            raise ValueError(
                f"H3SpreadV1Rule.adverse_stop_pct must be in (0, 1); "
                f"got {self.adverse_stop_pct!r}."
            )
        if self.time_stop_bars <= 0:
            raise ValueError(
                f"H3SpreadV1Rule.time_stop_bars must be > 0; "
                f"got {self.time_stop_bars!r}."
            )
        if self.entry_direction not in (-1, +1):
            raise ValueError(
                f"H3SpreadV1Rule.entry_direction must be +1 or -1; "
                f"got {self.entry_direction!r}."
            )
        if self.pyramid_add_lot < 0:
            raise ValueError(
                f"H3SpreadV1Rule.pyramid_add_lot must be >= 0; "
                f"got {self.pyramid_add_lot!r}."
            )
        if not all(p > 0 for p in self.pyramid_level_pcts):
            raise ValueError(
                f"H3SpreadV1Rule.pyramid_level_pcts must all be > 0; "
                f"got {self.pyramid_level_pcts!r}."
            )
        if list(self.pyramid_level_pcts) != sorted(self.pyramid_level_pcts):
            raise ValueError(
                f"H3SpreadV1Rule.pyramid_level_pcts must be monotonically increasing; "
                f"got {self.pyramid_level_pcts!r}."
            )
        if self.trail_arm_floating_usd < 0:
            raise ValueError(
                f"H3SpreadV1Rule.trail_arm_floating_usd must be >= 0; "
                f"got {self.trail_arm_floating_usd!r}."
            )
        if not (0.0 <= self.trail_retrace_pct < 100.0):
            raise ValueError(
                f"H3SpreadV1Rule.trail_retrace_pct must be in [0, 100); "
                f"got {self.trail_retrace_pct!r}."
            )

        # Manually initialize parent-class attributes that _record_bar reads
        # but our flow doesn't update.
        self.realized_total = 0.0
        self.harvested = False
        self.recycle_events: list[dict[str, Any]] = []
        self.per_bar_records: list[dict[str, Any]] = []
        self._first_bar_ts: Optional[pd.Timestamp] = None
        self._n_dd_freezes: int = 0
        self._n_margin_freezes: int = 0
        self._n_regime_freezes: int = 0
        # Parent attributes set so isinstance checks don't break:
        self.trigger_usd = 10.0
        self.add_lot = self.pyramid_add_lot   # alias for parent's machinery
        self.starting_equity = self.initial_notional_usd
        self.harvest_target_usd = 1e12        # effectively disabled
        self.equity_floor_usd = None
        self.time_stop_days = None             # parent's time-stop disabled (we use bars)
        self.dd_freeze_frac = 0.999            # effectively disabled
        self.margin_freeze_frac = 0.999        # effectively disabled
        self.leverage = 1000.0
        self.factor_column = ""                # not used
        self.factor_min = 0.0
        self.factor_operator = ">="

        # 1.3.0-basket schema: initialize peak + summary_stats so per-bar
        # records emit the 35-col standard schema and downstream basket_report
        # can build per-window cycle metrics. Schema reference:
        # tools.basket_report._FIXED_LEDGER_COLUMNS + _PER_LEG_SUFFIXES.
        self._peak_equity_h3 = self.starting_equity
        self.summary_stats: dict[str, Any] = {
            "peak_floating_dd_usd":         0.0,
            "peak_floating_dd_pct":         0.0,
            "dd_freeze_count":              0,      # H3 has no dd-freeze gate
            "margin_freeze_count":          0,      # H3 has no margin-freeze gate
            "regime_freeze_count":          0,      # H3 has no regime gate
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

        # Detect basket-open state from legs (both must be in_pos)
        all_open = all(leg.state.in_pos for leg in legs)

        # Read bar closes (data-gap guard)
        bar_closes: dict[str, float] = {}
        try:
            for leg in legs:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
        except (KeyError, ValueError):
            return  # data gap; skip silently (parent _record_bar would log)

        # Compute floating P&L (cross-pair aware via V3 helpers)
        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (_leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                         if leg.state.in_pos else 0.0)
            for leg in legs
        }
        floating_total = sum(leg_float.values())

        # Newly-opened transition: legs opened by SpreadCrossLegStrategy on
        # this or prior bar. Lock entry_bar on the FIRST bar where both legs
        # are in position. (Bar 1 generally; could be later if signal
        # delayed.) Once locked, _basket_open stays True until a liquidation
        # event resets state.
        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            self._next_pyramid_level = 0
            self.recycle_events.append({
                "bar_index": i,
                "bar_ts": bar_ts,
                "action": "BASKET_OPEN",
                "direction": self.entry_direction,
                "initial_lots": dict(self.basket_runner._initial_lots)
                if self.basket_runner is not None else {},
                "leg_directions": {l.symbol: l.direction for l in legs},
            })

        # If basket not yet active (awaiting SpreadCrossLeg signal),
        # nothing for the rule to do besides emit a per-bar record.
        if not all_open:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        # Update running cycle peak floating BEFORE exit checks so the trail
        # check sees the most recent peak. Set on every in-position bar.
        if floating_total > self._cycle_peak_floating:
            self._cycle_peak_floating = floating_total

        # ---- Exit checks (priority order) -------------------------------

        # 1. TIME STOP
        elapsed = i - (self._entry_bar_idx or i)
        if elapsed >= self.time_stop_bars:
            self._n_time_stops += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="TIME_STOP")
            return

        # 2. ADVERSE STOP (bar-close basket P&L)
        # adverse threshold = -adverse_stop_pct * initial_notional_usd
        adverse_threshold = -self.adverse_stop_pct * self.initial_notional_usd
        if floating_total <= adverse_threshold:
            self._n_adverse_stops += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="ADVERSE_STOP")
            return

        # 2.5 TRAIL STOP (peak-relative; armed once running peak >= arm threshold)
        # Disabled when either param == 0 → no behavioral change for P00-P03.
        if (self.trail_retrace_pct > 0.0
                and self.trail_arm_floating_usd > 0.0
                and self._cycle_peak_floating >= self.trail_arm_floating_usd):
            retrace_floor = (
                self._cycle_peak_floating * (1.0 - self.trail_retrace_pct / 100.0)
            )
            if floating_total <= retrace_floor:
                self._n_trail_stops += 1
                self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                                floating_total, reason="TRAIL_STOP")
                return

        # 3. REVERSE CROSS
        try:
            cross_side = int(legs[0].df.loc[bar_ts, self.reverse_cross_column])
        except (KeyError, ValueError, TypeError):
            cross_side = 0
        if cross_side != 0 and cross_side != self.entry_direction:
            self._n_reverse_cross_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="REVERSE_CROSS")
            return

        # ---- Pyramid check ----------------------------------------------
        if self._next_pyramid_level < len(self.pyramid_level_pcts):
            next_threshold_usd = (
                self.pyramid_level_pcts[self._next_pyramid_level]
                * self.initial_notional_usd / 100.0
            )
            # Note: pyramid_level_pcts are interpreted as percentage points
            # (0.15 means 0.15% of notional, not 15%). Convert to USD.
            if floating_total >= next_threshold_usd:
                self._commit_pyramid(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    level=self._next_pyramid_level,
                )
                return

        # No action this bar
        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )

    # ---- Pyramid action --------------------------------------------------

    def _commit_pyramid(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, level: int,
    ) -> None:
        """Add pyramid_add_lot to BOTH legs, preserving their directions.
        Weighted-avg entry-price update per leg."""
        threshold_usd = (
            self.pyramid_level_pcts[level] * self.initial_notional_usd / 100.0
        )
        actions = []
        for leg in legs:
            old_avg = leg.state.entry_price
            old_lot = leg.lot
            new_lot = old_lot + self.pyramid_add_lot
            # Weighted-avg new entry price based on direction-aware fill.
            # For long: weighted avg using current close as new chunk's price.
            # For short: same math (entry_price tracks the average regardless
            # of direction; PnL formula uses direction sign elsewhere).
            new_avg = (
                (old_lot * old_avg + self.pyramid_add_lot * bar_closes[leg.symbol])
                / new_lot
            )
            leg.state.entry_price = new_avg
            leg.lot = new_lot
            actions.append({
                "symbol": leg.symbol,
                "old_lot": old_lot,
                "new_lot": new_lot,
                "old_avg": old_avg,
                "new_avg": new_avg,
                "fill_price": bar_closes[leg.symbol],
            })

        self._next_pyramid_level = level + 1
        self._n_pyramids_total += 1

        self.recycle_events.append({
            "bar_index": i,
            "bar_ts": bar_ts,
            "action": "PYRAMID",
            "level": level + 1,
            "threshold_usd": threshold_usd,
            "floating_total": floating_total,
            "leg_actions": actions,
        })

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="PYRAMID",
            recycle_attempted=True,
            recycle_executed=True,
        )

    # ---- Liquidation -----------------------------------------------------

    def _liquidate(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, reason: str,
    ) -> None:
        """Close all leg positions at current bar close, realize P&L, reset
        cycle state. Leaves legs OUT-OF-POSITION (in_pos=False) so the
        SpreadCrossLegStrategy resumes watching for next entry signal.
        """
        if self.basket_runner is None:
            raise RuntimeError(
                "H3SpreadV1Rule._liquidate: basket_runner is None. "
                "Did __init__ skip the back-reference injection?"
            )

        # Record per-leg realized P&L and force the engine to emit a trade.
        realized_pnl = floating_total
        self.realized_total += realized_pnl

        # Manually transition each leg out of position. We mimic engine's
        # exit flow: set in_pos=False, append a manual exit trade to leg.trades.
        for leg in legs:
            if not leg.state.in_pos:
                continue
            # Build a minimal exit trade record matching engine conventions.
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
        self._next_pyramid_level = 0
        self._cycle_peak_floating = 0.0   # reset for next cycle's trail-stop

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

    # ---- Per-bar record (1.3.0-basket 35-col parquet emission) ----------

    def _emit_record(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, skip_reason: str,
        *,
        recycle_attempted: bool = False,
        recycle_executed: bool = False,
    ) -> None:
        """Emit one per-bar record matching the 1.3.0-basket 35-col fixed
        schema + 8 cols per leg (Block F). Schema is locked in
        tools.basket_report._FIXED_LEDGER_COLUMNS / _PER_LEG_SUFFIXES;
        downstream basket_report._write_per_bar_ledger raises if any fixed
        column is missing.

        H3-specific mappings:
          - recycle_attempted / recycle_executed: pyramid-add events
            (H3's analog of H2's winner-add-to-loser recycle).
          - harvest_triggered: always False (H3 has no equity target).
          - regime_gate_blocked / dd_freeze_active / margin_freeze_active:
            always False (H3 has no factor gate or DD/margin freezes).
          - gate_factor_value / gate_factor_name: NaN / "" (no gate).
          - winner_leg_idx / loser_leg_idx: None (H3 pyramids both legs
            uniformly; winner/loser concept doesn't apply).
        """
        # Equity + drawdown tracking (running peak across the whole basket)
        equity = self.starting_equity + self.realized_total + floating_total
        if equity > self._peak_equity_h3:
            self._peak_equity_h3 = equity
        dd_from_peak_usd = equity - self._peak_equity_h3
        if self._peak_equity_h3 > 0:
            dd_from_peak_pct = dd_from_peak_usd / self._peak_equity_h3 * 100.0
        else:
            dd_from_peak_pct = 0.0

        # Margin / notional aggregates via v3 cross-pair helpers.
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
            # Notional = margin * leverage (in USD)
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

        bars_since_last_recycle = (
            (i - self._last_pyramid_bar) if self._last_pyramid_bar is not None else None
        )
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
            "peak_equity_usd":         self._peak_equity_h3,
            "dd_from_peak_usd":        dd_from_peak_usd,
            "dd_from_peak_pct":        dd_from_peak_pct,
            # Block C — Margin/capital state (5)
            "margin_used_usd":         margin_used,
            "free_margin_usd":         free_margin,
            "margin_level_pct":        margin_level_pct,
            "notional_total_usd":      notional_total,
            "leverage_effective":      self.leverage,
            # Block D — Engine control state (8). H3 has no DD-freeze /
            # margin-freeze / regime gate, so those flags are constant False.
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
            "recycle_count":           self._n_pyramids_total,
            "bars_since_last_recycle": bars_since_last_recycle,
            "bars_since_last_harvest": bars_since_last_harvest,
            "gate_factor_value":       float("nan"),
            "gate_factor_name":        self.factor_column,  # "" by default
            "winner_leg_idx":          None,
            "loser_leg_idx":           None,
        }

        # Block F — per-leg state (8 cols × N legs)
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

        # ---- summary_stats running aggregates (consumed by canonical_metrics) ----
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

        if recycle_executed:
            self._last_pyramid_bar = i


__all__ = ["H3SpreadV1Rule"]
