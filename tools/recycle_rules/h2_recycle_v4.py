"""h2_recycle_v4.py — H2_recycle@4: bump-and-liquidate variant.

Phase C of the H2_recycle@4 pipeline-routing effort. Subclasses
`H2RecycleRule` (@1) and overrides `apply()` to implement the bump-and-
liquidate mechanic empirically validated in `tmp/h2_bump_liquidate_sim.py`
across the 10-window matrix (research doc §5.4b).

Mechanic
--------
**Mode 1 (RECYCLE, default):** standard Variant G recycle with the regime
gate. Bank winner's floating, add `add_lot` to loser.

**Switch trigger:** after `switch_n` consecutive same-loser adds without a
reversal, the rule fires a one-time BUMP and enters Mode 2.

**Bump:** add `(switch_n + 1) * add_lot` (e.g. 6 × 0.01 = 0.06) lot to the
current winner at the current bar's close, with weighted-avg entry-price
update. The bump's primary effect is asymmetric exposure: winner_lot >
loser_lot for the first time in the trend, so trend continuation banks
more (per pip) than the loser bleeds.

**Mode 2 (HOLD):** no further trades. The rule tracks `winner_peak_float`
on the trend_winner leg and waits for a retrace.

**Liquidation:** when current winner floating retraces `retrace_pct` from
its Mode-2 peak (e.g. 30%), the rule:
  1. Updates `realized_total += floating_total` (rule-side accounting).
  2. Calls `self.basket_runner.soft_reset_basket(...)` (runner-side
     state-reset primitive, Phase B).
  3. Resets its own mode/counter state: mode → RECYCLE, consec_same_loser
     → 0, last_loser_sym → None, winner_peak_float → 0, trend_winner_sym
     → None.
  4. Records a `LIQUIDATE_RESET` event in `recycle_events`.

The basket continues — a fresh sub-basket starts at `initial_lot` on each
leg at the liquidation bar's close. Multiple cycles per window are
expected (the empirical sim had 4-7 cycles per window typical).

References
----------
- `tmp/h2_bump_liquidate_sim.py` — basket_sim implementation (parity
  target for the pipeline path).
- `research/FX_BASKET_RECYCLE_RESEARCH.md` §5.4b — 10-window matrix
  results. Bump-and-liquidate dominates mode-switch on every metric;
  10/10 survival both baskets, max DD halved 120%→60%, B2 COVID blow-up
  prevented.
- `tools/basket_runner.py::BasketRunner.soft_reset_basket` — Phase B
  primitive this rule consumes.
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

# ABI ANCHOR: H2_RECYCLE_V4_RULE
_RULE_NAME_V4 = "H2_recycle"
_RULE_VERSION_V4 = 4


@dataclass
class H2RecycleRuleV4(H2RecycleRule):
    """Bump-and-liquidate variant of H2_recycle.

    Inherits all parameters and machinery from H2RecycleRule (@1). Adds two
    new parameters (`switch_n`, `retrace_pct`) and the mode-state needed
    for the bump-and-liquidate flow.

    Parameters added
    ----------------
    switch_n     : int (default 5)
        Number of consecutive same-loser recycle adds before the rule
        fires a one-time BUMP and enters HOLD mode. 5 covers the 75th
        percentile of B1 adverse runs in the 10-window matrix.
    retrace_pct  : float (default 0.30, valid range (0, 1))
        Fractional retrace from the Mode-2 winner-peak floating that
        triggers liquidation + soft-reset. 0.30 captures most of the
        trend without picking the exact top.

    State added (initialized in __post_init__)
    -------------------------------------------
    _mode               : "RECYCLE" | "HOLD"
    _consec_same_loser  : int
    _last_loser_sym     : str | None
    _winner_peak_float  : float
    _trend_winner_sym   : str | None
    _n_bumps            : int
    _n_liquidations     : int

    Provided by the back-ref injection at `BasketRunner.__init__`:
    basket_runner       : BasketRunner | None
        Used to call `soft_reset_basket(...)` on liquidation.
    """

    # New parameters
    switch_n: int = 5
    retrace_pct: float = 0.30

    # New name/version override (inherits name slot from parent)
    version: int = _RULE_VERSION_V4

    # New state — all defaultable so dataclass inheritance accepts them
    _mode: str = "RECYCLE"
    _consec_same_loser: int = 0
    _last_loser_sym: Optional[str] = None
    _winner_peak_float: float = 0.0
    _trend_winner_sym: Optional[str] = None
    _n_bumps: int = 0
    _n_liquidations: int = 0

    # Back-reference injected by BasketRunner.__init__ (Phase B)
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # Validate parent's fields first
        super().__post_init__()
        # Then V4-specific validation
        if not isinstance(self.switch_n, int) or self.switch_n < 1:
            raise ValueError(
                f"H2RecycleRuleV4.switch_n must be a positive integer; "
                f"got {self.switch_n!r}."
            )
        if not (0.0 < self.retrace_pct < 1.0):
            raise ValueError(
                f"H2RecycleRuleV4.retrace_pct must be in (0, 1); "
                f"got {self.retrace_pct!r}."
            )

    # ---- BasketRule.apply override ----------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self.harvested:
            return

        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # Data gap check (same as @1) ----------------------------------------
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

        # Compute floating + equity (same as @1) -----------------------------
        leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # Exit checks (same as @1) -------------------------------------------
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

        # Safety freezes (same as @1) ----------------------------------------
        margin_used = sum(_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage) for leg in legs)
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1

        # ===== Mode dispatch ================================================
        if self._mode == "HOLD":
            self._apply_hold_mode(
                legs, i, bar_ts, bar_closes, leg_float, floating_total,
                equity, margin_used,
            )
            return

        # ===== Mode 1: RECYCLE =============================================
        # Regime gate read (same as @1)
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

        # Hard-cap freezes: skip recycle this bar
        if dd_breach:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=True, margin_freeze=margin_breach, regime_blocked=regime_blocked,
                factor_val=factor_val,
                skip_reason="DD_FREEZE",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return
        if margin_breach:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=regime_blocked,
                factor_val=factor_val,
                skip_reason="MARGIN_FREEZE",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return
        if regime_blocked:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=True,
                factor_val=factor_val,
                skip_reason="REGIME_GATE",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Winner / loser identification (same as @1)
        winner: Optional[BasketLeg] = None
        loser: Optional[BasketLeg] = None
        for leg in legs:
            if not leg.state.in_pos or leg.lot <= 0:
                continue
            if leg_float[leg.symbol] >= self.trigger_usd:
                winner = leg
                break
        if winner is None:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="NO_WINNER",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return
        for leg in legs:
            if leg is winner:
                continue
            if not leg.state.in_pos or leg.lot <= 0:
                continue
            if leg_float[leg.symbol] < 0:
                loser = leg
                break
        if loser is None:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="NO_LOSER",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # === V4-specific: track consec_same_loser and decide BUMP vs RECYCLE
        if loser.symbol == self._last_loser_sym:
            self._consec_same_loser += 1
        else:
            self._consec_same_loser = 1
            self._last_loser_sym = loser.symbol

        if self._consec_same_loser >= self.switch_n:
            # BUMP attempt
            self._attempt_bump(
                legs, i, bar_ts, bar_closes, leg_float, floating_total,
                equity, margin_used, factor_val, winner, loser,
            )
            return

        # === Normal recycle (same as @1's recycle commit) ==================
        self._commit_recycle(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            equity, margin_used, factor_val, winner, loser,
        )

    # ---- Mode 2: HOLD logic -----------------------------------------------

    def _apply_hold_mode(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
    ) -> None:
        """Track winner peak; trigger soft-reset on retrace."""
        if self._trend_winner_sym is None:
            # Defensive — shouldn't happen
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=None,
                skip_reason="HOLD_NO_TREND_WINNER",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        current_winner_float = leg_float[self._trend_winner_sym]
        if current_winner_float > self._winner_peak_float:
            self._winner_peak_float = current_winner_float

        # Retrace check
        retrace_triggered = (
            self._winner_peak_float > 0
            and current_winner_float < self._winner_peak_float * (1.0 - self.retrace_pct)
        )

        if retrace_triggered:
            # Liquidate: realize all floating, soft_reset, return to RECYCLE
            self._commit_liquidation(
                legs, i, bar_ts, bar_closes, leg_float, floating_total,
                equity, margin_used,
            )
            return

        # Holding — just record the bar
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=leg_float,
            floating_total=floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=None,
            skip_reason="HOLD_MODE",
            recycle_attempted=False, recycle_executed=False,
            harvest_triggered=False,
        )

    # ---- BUMP action -------------------------------------------------------

    def _attempt_bump(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        winner: BasketLeg, loser: BasketLeg,
    ) -> None:
        """Try to add (switch_n + 1) * add_lot to winner. On margin breach, skip."""
        bump_size = (self.switch_n + 1) * self.add_lot
        new_winner_lot = winner.lot + bump_size

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
                skip_reason="BUMP_REJECTED_MARGIN",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Commit bump: weighted-avg entry, lot grows
        winner_old_avg = winner.state.entry_price
        winner_old_lot = winner.lot
        new_winner_avg = (
            (winner_old_lot * winner_old_avg + bump_size * bar_closes[winner.symbol])
            / new_winner_lot
        )
        winner.state.entry_price = new_winner_avg
        winner.state.entry_index = i
        winner.lot = new_winner_lot

        # Enter HOLD mode
        self._mode = "HOLD"
        self._trend_winner_sym = winner.symbol
        # Recompute winner floating post-bump (close to 0 since most lot is at market)
        post_winner_float = _leg_pnl_usd(winner, bar_closes[winner.symbol])
        self._winner_peak_float = post_winner_float
        self._n_bumps += 1

        # Record event
        winner_leg_idx = legs.index(winner)
        loser_leg_idx = legs.index(loser)
        event = {
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "action":            "BUMP",
            "winner_symbol":     winner.symbol,
            "loser_symbol":      loser.symbol,
            "bump_size":         bump_size,
            "winner_old_lot":    winner_old_lot,
            "winner_new_lot":    new_winner_lot,
            "winner_old_avg":    winner_old_avg,
            "winner_new_avg":    new_winner_avg,
            "consec_same_loser": self._consec_same_loser,
            "realized_total":    self.realized_total,
            "floating_total":    floating_total,
            "equity_before":     equity,
        }
        self.recycle_events.append(event)

        # Record bar — bump is treated as recycle_attempted=True / recycle_executed=False
        # so the parquet ledger can distinguish it from normal recycles. The
        # skip_reason="BUMP_INTO_HOLD" tags the event for downstream analysis.
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason="BUMP_INTO_HOLD",
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
    ) -> None:
        """Realize all floating, soft_reset basket, restore RECYCLE mode."""
        if self.basket_runner is None:
            raise RuntimeError(
                "H2RecycleRuleV4._commit_liquidation: basket_runner is None. "
                "Either the rule was instantiated outside a BasketRunner, or the "
                "back-reference injection in BasketRunner.__init__ failed."
            )

        # Realize all floating into rule's realized_total (rule-side accounting)
        realized_at_liquidation = floating_total
        old_realized = self.realized_total
        self.realized_total += realized_at_liquidation

        # Capture state pre-reset for the event log
        pre_reset_lots = {leg.symbol: leg.lot for leg in legs}
        pre_reset_winner_sym = self._trend_winner_sym
        winner_peak_at_liquidation = self._winner_peak_float

        # Call runner primitive — closes positions + reopens fresh at initial_lot
        self.basket_runner.soft_reset_basket(
            at_index=i, at_ts=bar_ts, at_prices=bar_closes,
        )

        # Reset rule-internal state (back to RECYCLE mode for fresh cycle)
        self._mode = "RECYCLE"
        self._consec_same_loser = 0
        self._last_loser_sym = None
        self._winner_peak_float = 0.0
        self._trend_winner_sym = None
        self._n_liquidations += 1

        # Record event
        event = {
            "bar_index":              i,
            "bar_ts":                 bar_ts,
            "action":                 "LIQUIDATE_RESET",
            "trend_winner_symbol":    pre_reset_winner_sym,
            "winner_peak_at_event":   winner_peak_at_liquidation,
            "current_winner_float":   leg_float.get(pre_reset_winner_sym, 0.0)
                                       if pre_reset_winner_sym else 0.0,
            "realized_at_liquidation": realized_at_liquidation,
            "realized_total_before":  old_realized,
            "realized_total_after":   self.realized_total,
            "pre_reset_lots":         pre_reset_lots,
            "floating_total_before":  floating_total,
            "equity_before":          equity,
        }
        self.recycle_events.append(event)

        # Record bar — after soft_reset_basket, leg state is fresh (lots=initial,
        # entry_price=bar_close). Recompute leg_float (will be 0 since entry==mark).
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        # Equity invariant: total equity unchanged by liquidation+reset (we just
        # moved float into realized, then reopened at market = 0 float).
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=None,
            skip_reason="LIQUIDATE_RESET",
            recycle_attempted=False, recycle_executed=False,
            harvest_triggered=False,
        )

    # ---- Normal RECYCLE commit (same semantics as @1) ---------------------

    def _commit_recycle(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        winner: BasketLeg, loser: BasketLeg,
    ) -> None:
        """Bank winner + add to loser. Verbatim port of @1's recycle path."""
        new_loser_lot = loser.lot + self.add_lot
        proj_margin = 0.0
        for leg in legs:
            lot = new_loser_lot if leg is loser else leg.lot
            if leg.symbol in _USD_QUOTE:
                proj_margin += lot * _LOT_UNITS * bar_closes[leg.symbol] / self.leverage
            elif leg.symbol in _USD_BASE:
                proj_margin += lot * _LOT_UNITS / self.leverage
        proj_realized = self.realized_total + leg_float[winner.symbol]
        proj_floating = sum(leg_float[leg.symbol] for leg in legs if leg is not winner)
        proj_equity = self.starting_equity + proj_realized + proj_floating
        if proj_margin >= self.margin_freeze_frac * proj_equity:
            self._n_margin_freezes += 1
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="PROJECTED_MARGIN_BREACH",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        winner_realized = leg_float[winner.symbol]
        self.realized_total = proj_realized

        winner_old_entry = winner.state.entry_price
        winner.state.entry_price = bar_closes[winner.symbol]
        winner.state.entry_index = i

        loser_old_avg = loser.state.entry_price
        loser_old_lot = loser.lot
        new_avg = (loser_old_lot * loser_old_avg + self.add_lot * bar_closes[loser.symbol]) / new_loser_lot
        loser.state.entry_price = new_avg
        loser.lot = new_loser_lot

        winner_leg_idx = legs.index(winner)
        loser_leg_idx = legs.index(loser)

        event = {
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "action":            "RECYCLE",
            "factor_value":      factor_val,
            "winner_symbol":     winner.symbol,
            "winner_realized":   winner_realized,
            "winner_old_entry":  winner_old_entry,
            "winner_new_entry":  bar_closes[winner.symbol],
            "loser_symbol":      loser.symbol,
            "loser_old_lot":     loser_old_lot,
            "loser_new_lot":     new_loser_lot,
            "loser_old_avg":     loser_old_avg,
            "loser_new_avg":     new_avg,
            "consec_same_loser": self._consec_same_loser,
            "realized_total":    self.realized_total,
            "floating_total":    floating_total,
            "equity_before":     equity,
        }
        self.recycle_events.append(event)

        winner.trades.append({
            "entry_index": winner.state.entry_index,
            "exit_index":  i,
            "direction":   winner.direction,
            "entry_price": winner_old_entry,
            "exit_price":  bar_closes[winner.symbol],
            "exit_source": "BASKET_RECYCLE_WINNER",
            "exit_reason": _RULE_NAME_V4,
            "pnl_usd":     winner_realized,
        })

        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason="NONE",
            recycle_attempted=True, recycle_executed=True,
            harvest_triggered=False,
            winner_leg_idx=winner_leg_idx,
            loser_leg_idx=loser_leg_idx,
        )


__all__ = ["H2RecycleRuleV4"]
