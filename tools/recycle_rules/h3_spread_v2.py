"""h3_spread_v2.py — H3_spread@2: bounded-exposure + harvest scale-out.

Structural test rule (2026-05-19). Identical to H3_spread@1 P03 in every
respect EXCEPT the pyramid mechanic, which now has a two-phase lifecycle:

  Phase 1 (accumulation). Pyramid threshold crossings ADD `pyramid_add_lot`
    to both legs (weighted-avg entry update), exactly as in @1 — until the
    per-leg lot reaches `max_exposure_multiple * initial_lot` (default 3.0×).

  Phase 2 (harvest). Once the cap is reached, subsequent threshold crossings
    no longer add. Instead they SCALE OUT both legs by `pyramid_add_lot`
    each, realizing the proportional share of the leg's floating P&L into
    cumulative realized. Entry-price is preserved on scale-out. Scale-outs
    continue at each new monotonically-increasing threshold until the
    position would drop to/below zero, at which point the cycle terminates
    with `LIQUIDATE_HARVEST_COMPLETE` and the leg strategy resumes watching
    for the next cross signal.

All other exits (TIME_STOP, ADVERSE_STOP, REVERSE_CROSS, TRAIL_STOP — if
configured) remain in their @1 priority order. Threshold spacing is a
single param `pyramid_threshold_step_pct` (default 0.15% of stake) — the
arithmetic progression from @1's [0.15, 0.30] generalized to all levels.

Why this rule
-------------
Single-window analysis on PAIRX P03 (2026-05-19, tmp/h3_uncapped_pyramid_replay.py)
showed:
  - 5.4% of cycles are runaway winners that would pyramid 50+ levels under
    uncapped expansion (truncated by sentinel cap in the simulator).
  - ALL of the strategy's edge concentrates in those runaway cycles
    (+$18,098 sum). Every other pyramid-count bucket loses money.
  - Adverse-stop dollar losses grow with position size — bigger pyramid
    cycles overshoot the -$20 close threshold up to -$200 in 30-49 pyramid
    cycles.
  - Fixed-level full exit kills the runners (each runner contributes
    $600-$9,600 of realized PnL; exit at level N caps each at ~$N × $1.50).

Hypothesis: a bounded cap + symmetric scale-out preserves the convex tail
(runners keep harvesting in Phase 2 instead of truncating) AND bounds the
tail loss on cycles that mature into adverse exits (smaller residual
position by the time -$20 hits).

This is a structural probe. No predictive filters, no adaptive thresholds.
Generalizes (or fails to) across windows in the same way the @1 sweep did —
that's the v2 test.

Reference
---------
SYSTEM_STATE manual block 2026-05-19 (this session). Op-spec preserved
verbatim above.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg
from tools.capital.capital_broker_spec import load_broker_spec
from tools.recycle_rules.h2_recycle_v3 import (
    _build_ref_closes,
    _leg_margin_usd,
    _leg_pnl_usd,
)
from tools.recycle_rules.h3_spread_v1 import H3SpreadV1Rule


_RULE_NAME = "H3_spread"
_RULE_VERSION = 2


@dataclass
class H3SpreadV2Rule(H3SpreadV1Rule):
    """Two-phase exposure lifecycle: bounded pyramid + symmetric harvest.

    Inherits all @1 machinery (per-bar 35-col schema emission, leg PnL math,
    soft-reset on liquidation) and overrides `apply()` to implement the
    cap+harvest mechanic. The pyramid threshold schedule is regenerated from
    a single arithmetic-progression step rather than a finite list, so
    the harvest phase can fire indefinitely above the cap.
    """

    # --- V2 new params ---
    max_exposure_multiple: float = 3.0
    pyramid_threshold_step_pct: float = 0.15
    # Delayed-harvest extension (2026-05-19). When > 0, the cycle enters a
    # HOLD phase the moment the cap is first reached: subsequent pyramid
    # threshold crossings are *consumed* (one-shot hysteresis preserved) but
    # produce no lot change — neither add nor scale-out. After
    # `harvest_start_after_extra_pyramids` crossings have passed in HOLD, the cycle
    # transitions to HARVEST and the next threshold triggers the first
    # scale-out. Default 0 = byte-identical to original @2 (immediate harvest
    # on cap-reach).
    harvest_start_after_extra_pyramids: int = 0
    # Keep-core extension (2026-05-19). When True, the harvest scale-out
    # chain stops at the initial lot per leg rather than scaling all the way
    # to zero. After reaching the floor, the cycle enters a CORE_HOLD phase
    # — base position held until reverse-cross / adverse-stop / time-stop
    # fires. Designed to separate two effects: leverage escalation
    # (controlled by the cap + harvest) vs. trend participation (preserved
    # by the persistent core position). Default False = scale-to-zero
    # behavior (original @2; cycle ends at LIQUIDATE_HARVEST_COMPLETE).
    harvest_keeps_core: bool = False
    # Bidirectional extension (2026-05-19). When True, the cycle's direction
    # is determined per-cycle from the cross-side at basket-open rather than
    # the static entry_direction param. UP-cross opens a LONG-spread cycle
    # (cycle_direction = +1), DOWN-cross opens a SHORT-spread cycle
    # (cycle_direction = -1). The reverse-cross exit check uses the cycle's
    # own direction, so subsequent crosses correctly trigger liquidation
    # regardless of which direction started the cycle. Requires the leg
    # strategy to also run in bidirectional mode (cross_watch_direction=0).
    # Default False = uni-directional behavior driven by entry_direction
    # (byte-equivalent to original @2 / S01-S05 directives).
    bidirectional: bool = False
    # Vol-neutral sizing extension (2026-05-24, structural-bias fix). The
    # spread_sma_cross indicator computes the SIGNAL on z-normalized prices
    # (vol-neutral by construction). But the directive defaults to equal lot
    # per leg, so EXECUTION captures a $-vol-weighted spread, not the z-
    # normalized one. The mismatch creates directional bias if leg vols
    # differ — the more-volatile leg dominates cycle P&L, and any drift in
    # that leg's price asymmetrically biases LONG vs SHORT cycles. This is
    # the same architectural defect COINTREV v1 had (fixed in v1.2 via
    # `_compute_neutral_basket`). When True, on the bar a signal queues but
    # before the engine fills, each leg's lot is rescaled so all legs have
    # equal $-vol per std (using rolling std over `vol_neutral_window` bars
    # and the broker spec's `usd_per_pu_per_lot`). Geometric-mean target
    # preserves the total $-vol budget vs the directive's base lots.
    # Default False = byte-equivalent to original equal-lot behavior.
    vol_neutral_sizing: bool = False
    vol_neutral_window: int = 200  # matches spread_sma_cross z_window default

    # --- Name/version overrides ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- V2 internal state ---
    _initial_lot_per_leg: Optional[float] = None
    _max_lot_per_leg: Optional[float] = None
    _n_harvests_total: int = 0
    _n_holds_total: int = 0
    # Sticky phase flag. Flips True the first bar current_lot reaches the cap;
    # stays True for the remainder of the cycle (so subsequent scale-outs that
    # drop lot below cap don't accidentally re-enter Phase 1 / re-add). Reset
    # to False on every liquidation (terminal or otherwise) — same lifetime
    # as `_basket_open` and `_next_pyramid_level`.
    _in_harvest_phase: bool = False
    # HOLD-phase state. Active iff `harvest_start_after_extra_pyramids > 0` AND cap has been
    # reached AND `_hold_levels_consumed < harvest_start_after_extra_pyramids`. Each HOLD
    # event increments `_hold_levels_consumed` and consumes one pyramid
    # threshold (via `_next_pyramid_level += 1`) so hysteresis is preserved.
    # Reset on every liquidation.
    _in_hold_phase: bool = False
    _hold_levels_consumed: int = 0
    # CORE_HOLD phase: True after harvest scale-outs have drawn the leg lot
    # down to `_initial_lot_per_leg`. From this point, threshold crossings
    # are consumed silently (record-only; lot unchanged). Cycle exits via
    # reverse-cross / adverse / time only. Reset on every liquidation.
    _in_core_hold_phase: bool = False
    # Per-cycle direction tracker used in bidirectional mode. +1 = LONG spread
    # (UP-cross entry), -1 = SHORT spread (DOWN-cross entry), 0 = flat / not
    # initialized. Replaces the static `entry_direction` param for the
    # reverse-cross exit check when `bidirectional=True`.
    _cycle_direction: int = 0

    def __post_init__(self) -> None:
        # Reuse @1's validation + state init for the inherited params.
        # @1 requires pyramid_level_pcts to be non-empty + monotonically
        # increasing — pass a sentinel single-element tuple to satisfy the
        # parent validator. V2 ignores pyramid_level_pcts in apply().
        if not self.pyramid_level_pcts:
            self.pyramid_level_pcts = (self.pyramid_threshold_step_pct,)
        super().__post_init__()

        # V2-specific validation
        if self.max_exposure_multiple < 1.0:
            raise ValueError(
                f"H3SpreadV2Rule.max_exposure_multiple must be >= 1.0; "
                f"got {self.max_exposure_multiple!r}."
            )
        if self.pyramid_threshold_step_pct <= 0.0:
            raise ValueError(
                f"H3SpreadV2Rule.pyramid_threshold_step_pct must be > 0; "
                f"got {self.pyramid_threshold_step_pct!r}."
            )
        if self.harvest_start_after_extra_pyramids < 0 or not isinstance(self.harvest_start_after_extra_pyramids, int):
            raise ValueError(
                f"H3SpreadV2Rule.harvest_start_after_extra_pyramids must be a non-negative "
                f"int; got {self.harvest_start_after_extra_pyramids!r}."
            )
        if not isinstance(self.harvest_keeps_core, bool):
            raise ValueError(
                f"H3SpreadV2Rule.harvest_keeps_core must be a bool; "
                f"got {self.harvest_keeps_core!r}."
            )
        if not isinstance(self.bidirectional, bool):
            raise ValueError(
                f"H3SpreadV2Rule.bidirectional must be a bool; "
                f"got {self.bidirectional!r}."
            )
        if not isinstance(self.vol_neutral_sizing, bool):
            raise ValueError(
                f"H3SpreadV2Rule.vol_neutral_sizing must be a bool; "
                f"got {self.vol_neutral_sizing!r}."
            )
        if self.vol_neutral_window < 2 or not isinstance(self.vol_neutral_window, int):
            raise ValueError(
                f"H3SpreadV2Rule.vol_neutral_window must be int >= 2; "
                f"got {self.vol_neutral_window!r}."
            )

    # ---- _liquidate override ---
    # Parent @1 resets _basket_open, _entry_bar_idx, _next_pyramid_level,
    # _cycle_peak_floating but knows nothing about _in_harvest_phase (a v2
    # attribute). Override to clear it on every cycle exit so the next
    # cycle starts in Phase 1.

    def _liquidate(self, legs, i, bar_ts, bar_closes, leg_float,
                   floating_total, reason: str) -> None:
        self._in_harvest_phase = False
        self._in_hold_phase = False
        self._hold_levels_consumed = 0
        self._in_core_hold_phase = False
        self._cycle_direction = 0
        super()._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                           floating_total, reason)

    # ---- Subclass hook for additional exit signals -----------------------
    # Default no-op. Subclasses override to inject custom exits between
    # ADVERSE_STOP and TRAIL_STOP in apply(). Must return True if a
    # liquidation fired (apply() will return immediately), False otherwise.
    # Called once per bar AFTER ADVERSE_STOP check has passed.

    def _check_extreme_z_exit_hook(
        self, legs, i, bar_ts, bar_closes, leg_float, floating_total,
    ) -> bool:
        return False

    # ---- Vol-neutral sizing helper --------------------------------------
    # When `vol_neutral_sizing` is True, on the bar a leg signal queues but
    # before the engine fills, rescale each leg's lot so all legs contribute
    # equal $-vol per std. Geometric-mean target preserves the total $-vol
    # budget vs the directive's base lots. No-op when feature is off, when
    # basket is already open, or when no pending entry is queued. Returns
    # True if lots were rebalanced (telemetry), False otherwise.

    def _maybe_apply_vol_neutral_sizing(
        self, legs: list[BasketLeg], bar_ts: pd.Timestamp,
    ) -> bool:
        if not self.vol_neutral_sizing:
            return False
        if any(leg.state.in_pos for leg in legs):
            return False  # already in cycle; don't resize mid-cycle
        if not all(leg.state.pending_entry is not None for leg in legs):
            return False  # not all legs have queued entries yet
        # Compute per-leg $-vol per unit lot from rolling std and broker spec.
        leg_dv: dict[str, float] = {}
        base_lot = (
            self._initial_lot_per_leg
            if self._initial_lot_per_leg is not None
            else max(leg.lot for leg in legs)
        )
        for leg in legs:
            if bar_ts not in leg.df.index:
                return False
            iloc = leg.df.index.get_loc(bar_ts)
            if iloc < self.vol_neutral_window:
                return False  # warmup not satisfied
            recent = leg.df.iloc[iloc - self.vol_neutral_window : iloc]["close"]
            std_price = float(recent.std())
            if std_price <= 0 or not np.isfinite(std_price):
                return False
            try:
                spec = load_broker_spec(leg.symbol)
            except Exception:
                return False
            usd_per_pu = float(
                (spec.get("calibration", {}) or {}).get("usd_per_pu_per_lot", 0) or 0
            )
            if usd_per_pu <= 0:
                return False
            # $-vol per unit lot per std = std_price (in price-units) × usd_per_pu_per_lot
            leg_dv[leg.symbol] = std_price * usd_per_pu
        # Geometric-mean target preserves total $-vol budget at base_lot.
        target_dv = math.exp(sum(math.log(v) for v in leg_dv.values()) / len(leg_dv))
        # Apply per-leg rescale, respecting broker lot_step and min_lot.
        for leg in legs:
            spec = load_broker_spec(leg.symbol)
            min_lot = float(spec.get("min_lot", 0.01) or 0.01)
            lot_step = float(spec.get("lot_step", 0.01) or 0.01)
            raw_lot = base_lot * target_dv / leg_dv[leg.symbol]
            lot = max(min_lot, round(raw_lot / lot_step) * lot_step)
            leg.lot = lot
        return True

    # ---- core mechanic --------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        # Mirror v1.apply() prologue + exit checks verbatim. The only divergence
        # is the pyramid block, which gets a phase-aware dispatch.
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
            return

        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (_leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                         if leg.state.in_pos else 0.0)
            for leg in legs
        }
        floating_total = sum(leg_float.values())

        # Vol-neutral sizing hook: on a bar where signal is queued but
        # basket not yet open, rescale leg lots so each leg contributes
        # equal $-vol per std. No-op when feature is off or basket already
        # open. The engine reads leg.lot at the next-bar fill, so resizing
        # here propagates into the actual position size.
        self._maybe_apply_vol_neutral_sizing(legs, bar_ts)

        # Snapshot initial lot on first bar both legs are open. The basket
        # runner sets leg.lot to the initial value before any pyramid fires,
        # so this records the unmodified starting size. Both legs are assumed
        # to start at the same lot (the H3 schema enforces uniform legs).
        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            self._next_pyramid_level = 0
            if self._initial_lot_per_leg is None:
                self._initial_lot_per_leg = max(leg.lot for leg in legs)
                self._max_lot_per_leg = (
                    self._initial_lot_per_leg * self.max_exposure_multiple
                )
            # Bidirectional mode: capture cycle direction from cross_side at
            # the entry bar (with state.direction fallback). In uni-directional
            # mode the param entry_direction governs. Per-cycle PnL accounting
            # reads leg.effective_direction (which derives from state.direction),
            # so no mutation of leg.direction is needed.
            if self.bidirectional:
                try:
                    cross_side_at_entry = int(
                        legs[0].df.loc[bar_ts, self.reverse_cross_column]
                    )
                except (KeyError, ValueError, TypeError):
                    cross_side_at_entry = 0
                # Fallback: if cross_side at the entry bar isn't ±1 (e.g.,
                # the cross fired delay_bars earlier and the side has since
                # reset to 0), derive direction from the leg's state.direction
                # (set by the engine from the signal returned by check_entry).
                if cross_side_at_entry not in (-1, +1):
                    cross_side_at_entry = int(legs[0].state.direction or 0)
                self._cycle_direction = cross_side_at_entry
            else:
                self._cycle_direction = int(self.entry_direction)
            self.recycle_events.append({
                "bar_index": i,
                "bar_ts": bar_ts,
                "action": "BASKET_OPEN",
                "direction": self._cycle_direction,
                "bidirectional": self.bidirectional,
                "initial_lots": dict(self.basket_runner._initial_lots)
                if self.basket_runner is not None else {},
                "leg_directions": {l.symbol: l.effective_direction for l in legs},
                "max_lot_per_leg": self._max_lot_per_leg,
            })
            # Tradelevel enrichment: snapshot per-leg entry context.
            self._snapshot_cycle_entry_ctx(legs, bar_ts, bar_closes)

        # Per-bar MFE/MAE tracking (no-op when basket flat).
        self._update_cycle_excursions(legs, bar_ts, bar_closes)

        if not all_open:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        if floating_total > self._cycle_peak_floating:
            self._cycle_peak_floating = floating_total

        # ---- Exit checks (identical priority/thresholds to @1) -----------

        elapsed = i - (self._entry_bar_idx or i)
        if elapsed >= self.time_stop_bars:
            self._n_time_stops += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="TIME_STOP")
            return

        adverse_threshold = -self.adverse_stop_pct * self.initial_notional_usd
        if floating_total <= adverse_threshold:
            self._n_adverse_stops += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="ADVERSE_STOP")
            return

        # Subclass hook for additional exit signals at this priority slot
        # (between ADVERSE_STOP and TRAIL_STOP). @2 returns False
        # unconditionally -- behavior bit-identical to pre-hook. @3
        # overrides this to fire the extreme-z take-profit exit when
        # cycle_dir * diff exceeds extreme_z_threshold.
        if self._check_extreme_z_exit_hook(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
        ):
            return

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

        try:
            cross_side = int(legs[0].df.loc[bar_ts, self.reverse_cross_column])
        except (KeyError, ValueError, TypeError):
            cross_side = 0
        # In bidirectional mode the cycle's direction is per-cycle; in
        # uni-directional mode it equals the static entry_direction param.
        cycle_dir = (
            self._cycle_direction if self.bidirectional
            else int(self.entry_direction)
        )
        if cross_side != 0 and cross_side != cycle_dir:
            self._n_reverse_cross_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="REVERSE_CROSS")
            return

        # ---- Phase-aware threshold dispatch ---
        # Next threshold = (level+1) * step_pct of stake, in USD.
        # In Phase 1 (current_lot < cap) it triggers an ADD;
        # in Phase 2 (current_lot >= cap) it triggers a HARVEST scale-out.
        # Hysteresis: each level fires at most once per cycle (monotonic
        # _next_pyramid_level counter — same semantic as @1).
        next_threshold_usd = (
            (self._next_pyramid_level + 1)
            * self.pyramid_threshold_step_pct
            * self.initial_notional_usd
            / 100.0
        )
        if floating_total >= next_threshold_usd:
            cap = self._max_lot_per_leg or float("inf")
            current_lot = max(leg.lot for leg in legs if leg.state.in_pos)
            at_cap = current_lot >= (cap - 1e-9)

            # Phase resolution. Semantics:
            #   harvest_start_after_extra_pyramids=N → exactly N HOLD_AT_CAP events fire
            #   between the last ADD and the first HARVEST_SCALE_OUT.
            # - Already in CORE_HOLD: harvest has scaled to floor; consume
            #   threshold silently (record only, no lot change). Reverse-cross
            #   / adverse / time exits still preempt (handled above).
            # - Already in HARVEST: stay there.
            # - Already in HOLD: this crossing IS a HOLD event; if the
            #   per-cycle HOLD count reaches the target, schedule the
            #   transition to HARVEST for the NEXT crossing (the current
            #   crossing still fires HOLD).
            # - At cap for the FIRST time: cap-reach crossing is HOLD #1
            #   (if delay>0) or HARVEST (if delay=0).
            # - Otherwise: still accumulating.
            if self._in_core_hold_phase:
                phase = "CORE_HOLD"
            elif self._in_harvest_phase:
                phase = "HARVEST"
            elif self._in_hold_phase:
                self._hold_levels_consumed += 1
                phase = "HOLD"
                if self._hold_levels_consumed >= self.harvest_start_after_extra_pyramids:
                    # After THIS HOLD, transition so next crossing fires harvest.
                    self._in_hold_phase = False
                    self._in_harvest_phase = True
            elif at_cap:
                if self.harvest_start_after_extra_pyramids > 0:
                    self._in_hold_phase = True
                    self._hold_levels_consumed = 1
                    phase = "HOLD"
                    if self._hold_levels_consumed >= self.harvest_start_after_extra_pyramids:
                        # delay=1: this single HOLD exhausts the delay; next
                        # crossing transitions to HARVEST.
                        self._in_hold_phase = False
                        self._in_harvest_phase = True
                else:
                    self._in_harvest_phase = True
                    phase = "HARVEST"
            else:
                phase = "ADD"

            if phase == "ADD":
                self._commit_pyramid_v2(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    level=self._next_pyramid_level,
                    threshold_usd=next_threshold_usd,
                )
            elif phase == "HOLD":
                self._commit_hold_at_cap(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    level=self._next_pyramid_level,
                    threshold_usd=next_threshold_usd,
                )
            elif phase == "CORE_HOLD":
                self._commit_core_hold(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    level=self._next_pyramid_level,
                    threshold_usd=next_threshold_usd,
                )
            else:   # HARVEST
                self._commit_harvest(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    level=self._next_pyramid_level,
                    threshold_usd=next_threshold_usd,
                )
            return

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )

    # ---- Phase 1: ADD (same math as @1, but threshold passed in) ----

    def _commit_pyramid_v2(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, level: int, threshold_usd: float,
    ) -> None:
        """Phase-1 pyramid add. Identical to @1 _commit_pyramid in lot/entry
        math; only difference is threshold is passed in (computed from the
        step) rather than read from a list.
        """
        actions = []
        for leg in legs:
            old_avg = leg.state.entry_price
            old_lot = leg.lot
            new_lot = old_lot + self.pyramid_add_lot
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

    # ---- Phase 1.5: HOLD at cap (delayed-harvest extension) ---

    def _commit_hold_at_cap(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, level: int, threshold_usd: float,
    ) -> None:
        """Consume a pyramid threshold without changing lot or realizing PnL.

        The HOLD phase exists to let cycles ride further above the cap before
        any scale-out fires. Each HOLD event consumes one threshold level
        (hysteresis preserved via `_next_pyramid_level`) and counts toward
        `harvest_start_after_extra_pyramids`. Lot is unchanged; entry-price is unchanged;
        realized_total is unchanged.

        Emits per-bar record with skip_reason="HOLD_AT_CAP" so the
        downstream taxonomy can distinguish HOLD bars from PYRAMID/HARVEST.
        """
        self._next_pyramid_level = level + 1
        self._n_holds_total += 1

        self.recycle_events.append({
            "bar_index": i,
            "bar_ts": bar_ts,
            "action": "HOLD_AT_CAP",
            "level": level + 1,
            "threshold_usd": threshold_usd,
            "floating_total": floating_total,
            "hold_levels_consumed": self._hold_levels_consumed,
            "hold_levels_remaining": max(
                0, self.harvest_start_after_extra_pyramids - self._hold_levels_consumed
            ),
        })

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLD_AT_CAP",
        )

    # ---- Phase 4: CORE_HOLD (post-harvest, harvest_keeps_core extension) ---

    def _commit_core_hold(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, level: int, threshold_usd: float,
    ) -> None:
        """Consume a pyramid threshold without changing lot or realizing PnL.

        Distinct from HOLD_AT_CAP — that fires *before* harvest, at the
        cap, during the delayed-harvest window. CORE_HOLD fires *after*
        harvest, at the floor (= initial_lot), preserving trend participation
        until reverse-cross / adverse / time terminates the cycle.

        Hysteresis preserved via `_next_pyramid_level`. Lot unchanged;
        entry-price unchanged; realized_total unchanged.
        """
        self._next_pyramid_level = level + 1
        self.recycle_events.append({
            "bar_index": i,
            "bar_ts": bar_ts,
            "action": "CORE_HOLD",
            "level": level + 1,
            "threshold_usd": threshold_usd,
            "floating_total": floating_total,
        })
        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="CORE_HOLD",
        )

    # ---- Phase 2: HARVEST scale-out -------

    def _commit_harvest(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, level: int, threshold_usd: float,
    ) -> None:
        """Reduce each leg's lot by pyramid_add_lot, realize the proportional
        share of the leg's floating as cycle PnL. Entry price unchanged.

        Terminal case: if the scale-out would drive any leg's lot to <= 0,
        unwind the residual fully and emit a LIQUIDATE_HARVEST_COMPLETE
        event so the leg strategy resumes for the next cross signal.
        """
        delta_lot = self.pyramid_add_lot
        floor_lot = (
            self._initial_lot_per_leg if (self.harvest_keeps_core
                                          and self._initial_lot_per_leg is not None)
            else 0.0
        )

        # Decide if this scale-out lands at-or-below the floor.
        # - harvest_keeps_core=False (floor=0): "reaches floor" = next lot <= 0
        #   → terminal LIQUIDATE_HARVEST_COMPLETE.
        # - harvest_keeps_core=True  (floor=initial_lot): "reaches floor" =
        #   next lot <= initial_lot. The scale-out is TRUNCATED to land
        #   exactly at the floor (may scale less than delta_lot). After it
        #   completes, the cycle enters CORE_HOLD — base position rides
        #   until reverse-cross / adverse / time fires.
        reaches_floor = any(
            (leg.lot - delta_lot) <= (floor_lot + 1e-12)
            for leg in legs if leg.state.in_pos
        )
        terminal = reaches_floor and not self.harvest_keeps_core

        realized_this_event = 0.0
        actions = []
        for leg in legs:
            if not leg.state.in_pos:
                continue
            old_lot = leg.lot
            if terminal:
                # harvest_keeps_core=False: realize the entire residual.
                realized = leg_float[leg.symbol]
                new_lot = 0.0
            elif reaches_floor and self.harvest_keeps_core:
                # Truncate scale-out: land exactly at floor.
                new_lot = floor_lot
                actual_delta = old_lot - new_lot
                if actual_delta <= 1e-12 or old_lot <= 1e-12:
                    realized = 0.0
                else:
                    realized = leg_float[leg.symbol] * (actual_delta / old_lot)
            else:
                # Normal partial scale-out: realize proportional share.
                if old_lot > 1e-12:
                    realized = leg_float[leg.symbol] * (delta_lot / old_lot)
                else:
                    realized = 0.0
                new_lot = old_lot - delta_lot
            leg.lot = new_lot
            realized_this_event += realized
            actions.append({
                "symbol": leg.symbol,
                "old_lot": old_lot,
                "new_lot": new_lot,
                "entry_price": leg.state.entry_price,
                "fill_price": bar_closes[leg.symbol],
                "realized_partial_usd": realized,
            })

        self.realized_total += realized_this_event
        self._next_pyramid_level = level + 1
        self._n_harvests_total += 1

        if terminal:
            # Close out legs the same way _liquidate does.
            for leg in legs:
                if not leg.state.in_pos:
                    continue
                exit_trade = {
                    "entry_index": leg.state.entry_index,
                    "entry_price": leg.state.entry_price,
                    "exit_index": i,
                    "exit_price": bar_closes[leg.symbol],
                    "direction": leg.effective_direction,
                    "lot": 0.0,
                    "exit_source": "BASKET_RULE_HARVEST_COMPLETE",
                    "exit_timestamp": bar_ts,
                    "pnl_usd": leg_float.get(leg.symbol, 0.0),
                }
                self._enrich_exit_trade(exit_trade, leg)
                leg.trades.append(exit_trade)
                leg.state.in_pos = False
                leg.state.direction = 0
                leg.state.pending_entry = None
                # Reset to initial lot so next cycle starts at the right size.
                if self.basket_runner is not None:
                    leg.lot = self.basket_runner._initial_lots[leg.symbol]

            self._n_liquidations += 1
            self._basket_open = False
            self._entry_bar_idx = None
            self._next_pyramid_level = 0
            self._cycle_peak_floating = 0.0
            self._in_harvest_phase = False
            self._in_hold_phase = False
            self._hold_levels_consumed = 0
            self._in_core_hold_phase = False
            self._cycle_direction = 0

            self.recycle_events.append({
                "bar_index": i,
                "bar_ts": bar_ts,
                "action": "LIQUIDATE",
                "reason": "HARVEST_COMPLETE",
                "realized_pnl_usd": realized_this_event,
                "cumulative_realized_usd": self.realized_total,
                "exit_prices": dict(bar_closes),
            })

            # Per-bar record: floating now 0 (all legs flat).
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="LIQUIDATE_HARVEST_COMPLETE",
            )
            return

        # harvest_keeps_core=True branch: this scale-out landed at the floor.
        # Lot is now at initial_lot per leg. Cycle continues; future threshold
        # crossings emit CORE_HOLD records (consume threshold, no lot change).
        # The cycle will exit on reverse-cross / adverse / time. Record this
        # as a SCALE_OUT_TO_CORE event so the action timeline is unambiguous.
        if reaches_floor and self.harvest_keeps_core:
            self._in_core_hold_phase = True
            new_leg_float = {
                leg.symbol: (
                    _leg_pnl_usd(
                        leg, bar_closes[leg.symbol],
                        _build_ref_closes(legs, bar_ts),
                    ) if leg.state.in_pos else 0.0
                )
                for leg in legs
            }
            new_floating_total = sum(new_leg_float.values())

            self.recycle_events.append({
                "bar_index": i,
                "bar_ts": bar_ts,
                "action": "SCALE_OUT_TO_CORE",
                "level": level + 1,
                "threshold_usd": threshold_usd,
                "floating_total_pre": floating_total,
                "floating_total_post": new_floating_total,
                "realized_pnl_usd": realized_this_event,
                "cumulative_realized_usd": self.realized_total,
                "leg_actions": actions,
            })

            self._emit_record(
                legs, i, bar_ts, bar_closes, new_leg_float, new_floating_total,
                skip_reason="SCALE_OUT_TO_CORE",
                recycle_attempted=True,
                recycle_executed=True,
            )
            return

        # Non-terminal scale-out: residual position remains open. Recompute
        # the post-scale-out floating (lower because lot dropped) and update
        # leg_float for the bar record.
        new_leg_float = {
            leg.symbol: (
                _leg_pnl_usd(
                    leg, bar_closes[leg.symbol],
                    _build_ref_closes(legs, bar_ts),
                ) if leg.state.in_pos else 0.0
            )
            for leg in legs
        }
        new_floating_total = sum(new_leg_float.values())

        self.recycle_events.append({
            "bar_index": i,
            "bar_ts": bar_ts,
            "action": "HARVEST_SCALE_OUT",
            "level": level + 1,
            "threshold_usd": threshold_usd,
            "floating_total_pre": floating_total,
            "floating_total_post": new_floating_total,
            "realized_pnl_usd": realized_this_event,
            "cumulative_realized_usd": self.realized_total,
            "leg_actions": actions,
        })

        self._emit_record(
            legs, i, bar_ts, bar_closes, new_leg_float, new_floating_total,
            skip_reason="HARVEST_SCALE_OUT",
            recycle_attempted=True,
            recycle_executed=True,
        )


__all__ = ["H3SpreadV2Rule"]
