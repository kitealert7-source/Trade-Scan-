"""h2_recycle_v5.py — H2_recycle@5: trend-follow pyramid mechanic.

Inverse-H2. Pyramids the WINNER leg each `pyramid_increment_usd` of new
loss on the LOSER leg. Loser is held at its initial lot — never grows —
serving as a tripwire + trend-distance sensor. Exits the basket when
the loser's floating PnL recovers `exit_recovery_usd` from its trough
(regime reversal signal), then soft-resets to a fresh 0.01+0.01 basket.

Mechanic
--------
- Add 0.01 to WINNER each time the LOSER leg's floating PnL hits a new
  low at `pyramid_increment_usd` increments below the previous add level.
- Loser leg is NEVER added to (anti-Martingale on winner).
- Loser identity is LOCKED at first pyramid event for the cycle's
  duration — once we start pyramiding direction X, direction Y stays
  the loser/tripwire for this cycle even if intra-bar floating flips.
- Exit when LOSER floating recovers `exit_recovery_usd` from its trough
  (= trend reversing) OR basket floating breaches `hard_floor_loss_usd`
  (defensive floor; should rarely fire if exit_recovery_usd is set
  conservatively).
- On exit: realize ALL floating, call `BasketRunner.soft_reset_basket`
  to reopen fresh 0.01+0.01, reset rule state. Next cycle starts.

Convex payoff design
--------------------
Per-cycle loss is bounded at ~$10 plus brokerage (≈ 1.1% of $1k stake)
by construction. Per-cycle upside is unbounded — pyramided winner
accumulates while loser is held at fixed exposure; trend continuation
generates positive equity at increasing pip-rate. Anti-Martingale
position sizing: heavy position is held only after the trend has
proven itself, not on hope.

References
----------
- Hypothesis spec: backtest_directives/hypotheses/H3_TREND_FOLLOW_V1.yaml
- Parent design: tools/recycle_rules/h2_recycle.py (H2RecycleRule)
- BasketRunner primitive consumed: BasketRunner.soft_reset_basket
  (commit 62018ab, 2026-05-16)
- Pipeline-only build per "Path B" decision (2026-05-17): no basket_sim
  duplicate; the pipeline parquet IS the reference. Rationale in YAML
  evidence_required.reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle import (
    H2RecycleRule,
    _leg_margin_usd,
    _leg_pnl_usd,
    _USD_BASE,
    _USD_QUOTE,
    _LOT_UNITS,
)

# ABI ANCHOR: H2_RECYCLE_V5_RULE
_RULE_NAME_V5 = "H2_recycle"
_RULE_VERSION_V5 = 5


@dataclass
class H2RecycleRuleV5(H2RecycleRule):
    """Trend-follow pyramid variant of H2_recycle.

    Inherits from H2RecycleRule (@1) for params, helpers, and parquet
    emission machinery. Overrides `apply()` entirely — the H2_recycle@1
    Variant G mechanic (bank winner, add loser) is NOT used here.

    Parameters added
    ----------------
    pyramid_increment_usd : float (default 10.0)
        Add 0.01 to winner each time loser's floating PnL hits a new low
        at this dollar increment below the previous add level. At 0.01
        loser lot, $10 ≈ 100 pips of adverse on the loser side — clean
        trend-distance measure.
    exit_recovery_usd : float (default 10.0)
        Liquidate basket when loser's floating PnL recovers this many
        dollars from its trough. Symmetric to `pyramid_increment_usd`
        on the recovery side.
    hard_floor_loss_usd : float (default -10.0, must be negative)
        Defensive hard floor — if basket floating PnL drops below this
        threshold, liquidate immediately. Should rarely fire if the
        recovery-based exit is functioning; protects against fast moves
        that exit_recovery can't catch in time.

    State added
    -----------
    _loser_sym              : str  — locked at first pyramid event; the
                              leg used as tripwire/trend-distance sensor
                              for this cycle's duration
    _pyramid_winner_sym     : str  — the leg being pyramided (opposite
                              of _loser_sym)
    _loser_trough_float     : float — running minimum of loser's floating PnL
    _last_add_loser_level   : float — loser_floating at the last pyramid add;
                              the next add fires at this minus pyramid_increment_usd
    _n_pyramids             : int  — pyramid events in current cycle
    _n_liquidations         : int  — total liquidation events (cycles completed)

    Back-reference (injected by BasketRunner.__init__)
    --------------------------------------------------
    basket_runner : BasketRunner | None — used for soft_reset_basket on
                    liquidation. RuntimeError raised if None at liquidation
                    time (defensive — orchestrator should always attach
                    the rule via BasketRunner).
    """

    # --- New parameters ---
    pyramid_increment_usd: float = 10.0
    exit_recovery_usd: float = 10.0
    hard_floor_loss_usd: float = -10.0

    # --- Version override ---
    version: int = _RULE_VERSION_V5

    # --- New state (initialized in __post_init__ via dataclass defaults) ---
    _loser_sym: Optional[str] = None
    _pyramid_winner_sym: Optional[str] = None
    _loser_trough_float: float = 0.0
    _last_add_loser_level: float = 0.0
    _n_pyramids: int = 0
    _n_liquidations: int = 0

    # Back-reference (populated by BasketRunner.__init__ via injection)
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # Parent validation (trigger_usd, dd_freeze_frac, factor_operator, etc.)
        super().__post_init__()

        # V5-specific validation
        if self.pyramid_increment_usd <= 0:
            raise ValueError(
                f"H2RecycleRuleV5.pyramid_increment_usd must be > 0; "
                f"got {self.pyramid_increment_usd!r}."
            )
        if self.exit_recovery_usd <= 0:
            raise ValueError(
                f"H2RecycleRuleV5.exit_recovery_usd must be > 0; "
                f"got {self.exit_recovery_usd!r}."
            )
        if self.hard_floor_loss_usd >= 0:
            raise ValueError(
                f"H2RecycleRuleV5.hard_floor_loss_usd must be < 0 "
                f"(it's a floor on basket floating, expressed as a "
                f"negative dollar threshold); got {self.hard_floor_loss_usd!r}."
            )

    # ---- BasketRule.apply override ----------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self.harvested:
            return

        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # ---- Data gap (same as @1/@4) ----
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes={l.symbol: float("nan") for l in legs},
                    leg_float={l.symbol: 0.0 for l in legs},
                    floating_total=0.0,
                    equity=self.starting_equity + self.realized_total,
                    margin_used=0.0,
                    dd_freeze=False, margin_freeze=False, regime_blocked=False,
                    factor_val=None,
                    skip_reason="RULE_NOT_INVOKED",
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

        # ---- Floating + equity (same as @1/@4) ----
        leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # ---- Exit checks (same as @1/@4) ----
        if equity >= self.harvest_target_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TARGET")
            return
        if self.equity_floor_usd is not None and equity <= self.equity_floor_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="FLOOR")
            return
        if equity <= 0:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="BLOWN")
            return
        if (
            self.time_stop_days is not None
            and self._first_bar_ts is not None
            and (bar_ts - self._first_bar_ts).days >= self.time_stop_days
        ):
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TIME")
            return

        # ---- Freeze checks (same as @1/@4) ----
        margin_used = sum(_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage) for leg in legs)
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1

        # ---- Regime gate (same as @1, but typical V5 directive uses
        #      inverted operator: factor_operator='<=' with factor_min=5
        #      → gate fires (blocks pyramid) when compression > 5 (chop).
        #      The factor_operator field is inherited from parent.) ----
        primary_df = legs[0].df
        column_missing = self.factor_column not in primary_df.columns
        factor_val: Optional[float] = None
        factor_present_but_nan = False
        if not column_missing:
            try:
                raw_val = float(primary_df.loc[bar_ts, self.factor_column])
                if pd.isna(raw_val):
                    factor_present_but_nan = True
                else:
                    factor_val = raw_val
            except (KeyError, ValueError, TypeError):
                column_missing = True
        if factor_val is None:
            regime_blocked = False
        elif self.factor_operator == ">=":
            regime_blocked = factor_val < self.factor_min
        elif self.factor_operator == "<=":
            regime_blocked = factor_val > self.factor_min
        else:  # "abs_<="
            regime_blocked = abs(factor_val) > self.factor_min
        if factor_present_but_nan or regime_blocked:
            self._n_regime_freezes += 1

        # ---- Identify CURRENT bar's winner / loser (highest / lowest floating) ----
        # If we're in a pyramid cycle, we use the LOCKED _loser_sym
        # rather than the bar-identified loser (the trend's loser side
        # is fixed at first pyramid for the cycle's duration).
        floats_sorted = sorted(leg_float.items(), key=lambda x: x[1], reverse=True)
        bar_winner_sym, bar_winner_float = floats_sorted[0]
        bar_loser_sym, bar_loser_float = floats_sorted[-1]

        # ---- Branch: in pyramid cycle or pre-pyramid ----
        if self._n_pyramids > 0:
            # We're in a cycle — use locked loser identity
            cur_loser_float = leg_float[self._loser_sym]
            cur_winner_sym = self._pyramid_winner_sym

            # Update trough (running min)
            if cur_loser_float < self._loser_trough_float:
                self._loser_trough_float = cur_loser_float

            # Exit trigger 1: loser recovered from trough by exit_recovery_usd
            if cur_loser_float > self._loser_trough_float + self.exit_recovery_usd:
                self._commit_liquidation(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    reason="TREND_LIQUIDATE_RECOVERY",
                )
                return

            # Exit trigger 2: hard floor on basket floating
            if floating_total <= self.hard_floor_loss_usd:
                self._commit_liquidation(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    reason="TREND_LIQUIDATE_FLOOR",
                )
                return

            # Hard freezes block pyramid (but not exit checks above)
            if dd_breach or margin_breach or regime_blocked:
                skip = (
                    "DD_FREEZE" if dd_breach
                    else "MARGIN_FREEZE" if margin_breach
                    else "REGIME_GATE"
                )
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes=bar_closes, leg_float=leg_float,
                    floating_total=floating_total, equity=equity, margin_used=margin_used,
                    dd_freeze=dd_breach, margin_freeze=margin_breach, regime_blocked=regime_blocked,
                    factor_val=factor_val,
                    skip_reason=skip,
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

            # Pyramid trigger: loser dropped below last add level by pyramid_increment
            trigger_level = self._last_add_loser_level - self.pyramid_increment_usd
            if cur_loser_float <= trigger_level:
                # Find the winner leg object by symbol
                winner_leg = next(l for l in legs if l.symbol == cur_winner_sym)
                self._commit_pyramid(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    winner=winner_leg, cur_loser_float=cur_loser_float,
                )
                return

            # No add, no exit — just record holding
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="HOLDING_PYRAMID",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )

        else:
            # Pre-pyramid: no cycle started yet for this basket
            # First pyramid fires when bar_loser_float <= -pyramid_increment_usd
            # (= 100 pips of adverse on the loser side at $10 increment for 0.01 lot)
            if dd_breach or margin_breach or regime_blocked:
                skip = (
                    "DD_FREEZE" if dd_breach
                    else "MARGIN_FREEZE" if margin_breach
                    else "REGIME_GATE"
                )
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes=bar_closes, leg_float=leg_float,
                    floating_total=floating_total, equity=equity, margin_used=margin_used,
                    dd_freeze=dd_breach, margin_freeze=margin_breach, regime_blocked=regime_blocked,
                    factor_val=factor_val,
                    skip_reason=skip,
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

            if bar_loser_float <= -self.pyramid_increment_usd:
                # First pyramid event of the cycle — lock loser identity
                winner_leg = next(l for l in legs if l.symbol == bar_winner_sym)
                self._loser_sym = bar_loser_sym
                self._pyramid_winner_sym = bar_winner_sym
                self._loser_trough_float = bar_loser_float
                # _last_add_loser_level starts at 0 for the first trigger calc;
                # set it to current loser_float now so the NEXT trigger fires at
                # current - pyramid_increment_usd.
                self._commit_pyramid(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    winner=winner_leg, cur_loser_float=bar_loser_float,
                )
                return

            # Waiting for first pyramid trigger
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="WAITING_FOR_PYRAMID",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )

    # ---- PYRAMID action ---------------------------------------------------

    def _commit_pyramid(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        winner: BasketLeg, cur_loser_float: float,
    ) -> None:
        """Add `add_lot` to winner; update state."""
        new_winner_lot = winner.lot + self.add_lot

        # Margin projection
        proj_margin = 0.0
        for leg in legs:
            lot = new_winner_lot if leg is winner else leg.lot
            if leg.symbol in _USD_QUOTE:
                proj_margin += lot * _LOT_UNITS * bar_closes[leg.symbol] / self.leverage
            elif leg.symbol in _USD_BASE:
                proj_margin += lot * _LOT_UNITS / self.leverage
        if proj_margin >= self.margin_freeze_frac * equity:
            self._n_margin_freezes += 1
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="PYRAMID_REJECTED_MARGIN",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Commit: weighted-avg new entry on winner, lot grows
        winner_old_avg = winner.state.entry_price
        winner_old_lot = winner.lot
        new_avg = (
            (winner_old_lot * winner_old_avg + self.add_lot * bar_closes[winner.symbol])
            / new_winner_lot
        )
        winner.state.entry_price = new_avg
        winner.state.entry_index = i
        winner.lot = new_winner_lot

        # Update rule state
        self._last_add_loser_level = cur_loser_float
        self._n_pyramids += 1

        # Event log
        winner_leg_idx = legs.index(winner)
        loser_leg_idx = next(j for j, l in enumerate(legs) if l.symbol == self._loser_sym)
        event = {
            "bar_index":              i,
            "bar_ts":                 bar_ts,
            "action":                 "PYRAMID",
            "winner_symbol":          winner.symbol,
            "loser_symbol":           self._loser_sym,
            "add_lot":                self.add_lot,
            "winner_old_lot":         winner_old_lot,
            "winner_new_lot":         new_winner_lot,
            "winner_old_avg":         winner_old_avg,
            "winner_new_avg":         new_avg,
            "cur_loser_float":        cur_loser_float,
            "loser_trough_float":     self._loser_trough_float,
            "n_pyramids":             self._n_pyramids,
            "realized_total":         self.realized_total,
            "floating_total":         floating_total,
            "equity_before":          equity,
        }
        self.recycle_events.append(event)

        # Recompute leg_float after the add (new lot on winner)
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason="PYRAMID_ADDED",
            recycle_attempted=True, recycle_executed=False,
            harvest_triggered=False,
            winner_leg_idx=winner_leg_idx,
            loser_leg_idx=loser_leg_idx,
        )

    # ---- LIQUIDATION action ------------------------------------------------

    def _commit_liquidation(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        reason: str,
    ) -> None:
        """Realize all floating, soft_reset basket, restore pre-pyramid state."""
        if self.basket_runner is None:
            raise RuntimeError(
                "H2RecycleRuleV5._commit_liquidation: basket_runner is None. "
                "Either the rule was instantiated outside a BasketRunner, or "
                "the back-reference injection in BasketRunner.__init__ failed."
            )

        # Realize all floating into rule's realized_total (rule-side accounting)
        realized_at_liquidation = floating_total
        old_realized = self.realized_total
        self.realized_total += realized_at_liquidation

        # Capture pre-reset state for event log
        pre_reset_lots = {leg.symbol: leg.lot for leg in legs}
        pre_reset_loser_sym = self._loser_sym
        pre_reset_winner_sym = self._pyramid_winner_sym
        pre_reset_trough = self._loser_trough_float
        pre_reset_n_pyramids = self._n_pyramids

        # Soft reset (closes positions + reopens fresh at initial_lot at current prices)
        self.basket_runner.soft_reset_basket(
            at_index=i, at_ts=bar_ts, at_prices=bar_closes,
        )

        # Reset rule state (back to pre-pyramid)
        self._loser_sym = None
        self._pyramid_winner_sym = None
        self._loser_trough_float = 0.0
        self._last_add_loser_level = 0.0
        self._n_pyramids = 0
        self._n_liquidations += 1

        # Event log
        event = {
            "bar_index":              i,
            "bar_ts":                 bar_ts,
            "action":                 reason,  # TREND_LIQUIDATE_RECOVERY | TREND_LIQUIDATE_FLOOR
            "loser_symbol":           pre_reset_loser_sym,
            "winner_symbol":          pre_reset_winner_sym,
            "loser_trough_float":     pre_reset_trough,
            "n_pyramids_in_cycle":    pre_reset_n_pyramids,
            "pre_reset_lots":         pre_reset_lots,
            "realized_at_liquidation": realized_at_liquidation,
            "realized_total_before":  old_realized,
            "realized_total_after":   self.realized_total,
            "floating_total_before":  floating_total,
            "equity_before":          equity,
        }
        self.recycle_events.append(event)

        # After soft_reset, leg state is fresh (lots=initial, entry=bar_close,
        # leg_float ~= 0 since entry==mark). Recompute and record.
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        # Equity invariant: total equity unchanged by liquidation+reset
        # (floating moved into realized, then reopened at market = 0 float).
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason=reason,
            recycle_attempted=False, recycle_executed=False,
            harvest_triggered=False,
        )


__all__ = ["H2RecycleRuleV5"]
