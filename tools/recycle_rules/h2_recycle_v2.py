"""H2RecycleRuleV2 — H2 recycle with loser-leg lot cap (Phase 1 Experiment A).

Plan ref: 2026-05-15 regime-feature probe finding. The probe demonstrated
that compression IS the strongest single-axis regime discriminator (median
chop on healthy bars is 6.5x the all-bars median), yet the strategy still
spends ~47% of bars in DD-freeze even at the strictest compression gate.
This means the failure mode lives INSIDE the cycle (loser-leg lot
accumulation makes the basket progressively pip-sensitive), not at gate
selection. The cap mechanic targets that failure mode directly.

Mechanic (identical to H2_recycle@1 except at commit):
  * Same Variant G trigger: winner (>= +$10 floating) AND loser (< $0).
  * Same gate, freezes, exits as v1.
  * NEW: on commit, if projected `loser.lot + add_lot > max_leg_lot`,
    realize the winner anyway (bank cash) but DO NOT grow the loser's
    lot. The loser stays at its current lot, entry price unchanged.
    A `_n_cap_skipped` counter tracks how often this fires.
  * Set `max_leg_lot = None` to disable the cap (equivalent to v1).

Registry: governance/recycle_rules/registry.yaml -> H2_recycle@2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.h2_recycle import (
    _leg_pnl_usd,
    _leg_margin_usd,
    _LOT_UNITS,
    _USD_QUOTE,
    _USD_BASE,
)


_RULE_NAME = "H2_recycle"
_RULE_VERSION = 2


@dataclass
class H2RecycleRuleV2:
    """H2 recycle with loser-leg lot cap.

    All v1 parameters preserved; adds:
      max_leg_lot: float | None  - cap on any single leg's cumulative lot.
                                   None disables the cap (== v1 behavior).
    """

    # Recycle parameters (v1)
    trigger_usd: float = 10.0
    add_lot: float = 0.01

    # Account / harvest parameters (v1)
    starting_equity: float = 1000.0
    harvest_target_usd: float = 2000.0
    equity_floor_usd: Optional[float] = None
    time_stop_days: Optional[int] = None

    # Safety caps (v1)
    dd_freeze_frac: float = 0.10
    margin_freeze_frac: float = 0.15
    leverage: float = 1000.0

    # Regime gate (operator-aware, S12 2026-05-16 — mirrors @1/@3)
    factor_column: str = "compression_5d"
    factor_min: float = 10.0
    factor_operator: str = ">="

    # NEW v2 parameter: loser-leg lot cap
    max_leg_lot: Optional[float] = None

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # ---- Telemetry / state ----
    realized_total: float = 0.0
    harvested_total_usd: float = 0.0
    harvested: bool = False
    exit_reason: Optional[str] = None
    exit_ts: Optional[pd.Timestamp] = None
    recycle_events: list[dict[str, Any]] = field(default_factory=list)

    # Bookkeeping
    _first_bar_ts: Optional[pd.Timestamp] = None
    _n_dd_freezes: int = 0
    _n_margin_freezes: int = 0
    _n_regime_freezes: int = 0
    _n_cap_skipped: int = 0   # NEW: count of recycle events where cap prevented loser-lot growth

    def __post_init__(self) -> None:
        if self.trigger_usd <= 0:
            raise ValueError("H2RecycleRuleV2.trigger_usd must be > 0.")
        if self.add_lot <= 0:
            raise ValueError("H2RecycleRuleV2.add_lot must be > 0.")
        if self.harvest_target_usd <= self.starting_equity:
            raise ValueError(
                f"H2RecycleRuleV2.harvest_target_usd ({self.harvest_target_usd}) must exceed "
                f"starting_equity ({self.starting_equity})."
            )
        if not (0 < self.dd_freeze_frac < 1):
            raise ValueError("H2RecycleRuleV2.dd_freeze_frac must be in (0, 1).")
        if not (0 < self.margin_freeze_frac < 1):
            raise ValueError("H2RecycleRuleV2.margin_freeze_frac must be in (0, 1).")
        if not self.factor_column:
            raise ValueError("H2RecycleRuleV2.factor_column must be a non-empty string.")
        if self.max_leg_lot is not None and self.max_leg_lot <= 0:
            raise ValueError("H2RecycleRuleV2.max_leg_lot must be > 0 or None.")
        if self.factor_operator not in (">=", "<=", "abs_<="):
            raise ValueError(
                f"H2RecycleRuleV2.factor_operator must be '>=', '<=', or 'abs_<='; "
                f"got {self.factor_operator!r}."
            )

    # ---- BasketRule.apply --------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        # Once harvested, nothing else fires.
        if self.harvested:
            return

        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # Read bar closes once per leg.
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                return

        # Per-leg floating + totals
        leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # ---- Exit checks (same as v1) ----
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

        # ---- Safety freezes (same as v1) ----
        margin_used = sum(_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage) for leg in legs)
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1
        if dd_breach or margin_breach:
            return

        # ---- Regime gate (operator-aware; S12 2026-05-16) ----
        primary_df = legs[0].df
        if self.factor_column not in primary_df.columns:
            return
        try:
            factor_val = float(primary_df.loc[bar_ts, self.factor_column])
        except (KeyError, ValueError, TypeError):
            return
        if pd.isna(factor_val):
            self._n_regime_freezes += 1
            return
        if self.factor_operator == ">=":
            regime_blocked = factor_val < self.factor_min
        elif self.factor_operator == "<=":
            regime_blocked = factor_val > self.factor_min
        else:  # "abs_<="  (S13: stretch_z20 family)
            regime_blocked = abs(factor_val) > self.factor_min
        if regime_blocked:
            self._n_regime_freezes += 1
            return

        # ---- Recycle trigger (Variant G — same as v1) ----
        winner: Optional[BasketLeg] = None
        loser: Optional[BasketLeg] = None
        for leg in legs:
            if not leg.state.in_pos or leg.lot <= 0:
                continue
            if leg_float[leg.symbol] >= self.trigger_usd:
                winner = leg
                break
        if winner is None:
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
            return

        # ---- v2 cap check: would the projected lot exceed max_leg_lot? ----
        projected_new_lot = loser.lot + self.add_lot
        cap_skipped = (
            self.max_leg_lot is not None
            and projected_new_lot > self.max_leg_lot
        )
        # `effective_new_lot` is what the loser would actually grow to.
        # When cap_skipped: loser stays at its current lot (winner still realizes).
        effective_new_lot = loser.lot if cap_skipped else projected_new_lot

        # ---- Projection check: margin after the commit ----
        # (uses effective_new_lot — if cap-skipped, no new margin from the loser)
        proj_margin = 0.0
        for leg in legs:
            lot = effective_new_lot if leg is loser else leg.lot
            if leg.symbol in _USD_QUOTE:
                proj_margin += lot * _LOT_UNITS * bar_closes[leg.symbol] / self.leverage
            elif leg.symbol in _USD_BASE:
                proj_margin += lot * _LOT_UNITS / self.leverage
        proj_realized = self.realized_total + leg_float[winner.symbol]
        proj_floating = sum(
            leg_float[leg.symbol] for leg in legs if leg is not winner
        )
        proj_equity = self.starting_equity + proj_realized + proj_floating
        if proj_margin >= self.margin_freeze_frac * proj_equity:
            self._n_margin_freezes += 1
            return

        # ---- Commit the recycle ----
        winner_realized = leg_float[winner.symbol]
        self.realized_total = proj_realized

        # Winner: realize floating, reset entry to current bar close (lot unchanged)
        winner_old_entry = winner.state.entry_price
        winner.state.entry_price = bar_closes[winner.symbol]
        winner.state.entry_index = i

        # Loser: cap-aware commit
        loser_old_avg = loser.state.entry_price
        loser_old_lot = loser.lot
        if cap_skipped:
            # Loser stays put; lot and entry unchanged.
            self._n_cap_skipped += 1
            new_avg = loser_old_avg
        else:
            # Weighted-avg new entry, lot grows (same as v1).
            new_avg = (
                loser_old_lot * loser_old_avg
                + self.add_lot * bar_closes[loser.symbol]
            ) / effective_new_lot
            loser.state.entry_price = new_avg
            loser.lot = effective_new_lot

        # Record the recycle event
        event = {
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "factor_value":      factor_val,
            "winner_symbol":     winner.symbol,
            "winner_realized":   winner_realized,
            "winner_old_entry":  winner_old_entry,
            "winner_new_entry":  bar_closes[winner.symbol],
            "loser_symbol":      loser.symbol,
            "loser_old_lot":     loser_old_lot,
            "loser_new_lot":     effective_new_lot,  # equals loser_old_lot if cap_skipped
            "loser_old_avg":     loser_old_avg,
            "loser_new_avg":     new_avg,
            "realized_total":    self.realized_total,
            "floating_total":    floating_total,
            "equity_before":     equity,
            "cap_skipped":       cap_skipped,        # NEW v2 telemetry
        }
        self.recycle_events.append(event)

        # Append synthetic trade record for the winner's realized leg.
        winner.trades.append({
            "entry_index": winner.state.entry_index,
            "exit_index":  i,
            "direction":   winner.direction,
            "entry_price": winner_old_entry,
            "exit_price":  bar_closes[winner.symbol],
            "exit_source": "BASKET_RECYCLE_WINNER",
            "exit_reason": _RULE_NAME,
            "pnl_usd":     winner_realized,
        })

    # ---- helpers ----------------------------------------------------------

    def _exit_all(
        self,
        legs: list[BasketLeg],
        i: int,
        bar_ts: pd.Timestamp,
        bar_closes: dict[str, float],
        leg_float: dict[str, float],
        *,
        reason: str,
    ) -> None:
        """Same as v1 — close every open leg, bank floating into harvested_total."""
        floating_total = sum(leg_float.values())
        self.harvested_total_usd = (
            self.starting_equity + self.realized_total + floating_total - self.starting_equity
        )
        self.harvested = True
        self.exit_reason = reason
        self.exit_ts = bar_ts
        for leg in legs:
            if leg.state.in_pos:
                bc = bar_closes[leg.symbol]
                leg.trades.append({
                    "entry_index": leg.state.entry_index,
                    "exit_index":  i,
                    "direction":   leg.direction,
                    "entry_price": leg.state.entry_price,
                    "exit_price":  bc,
                    "exit_source": f"BASKET_HARVEST_{reason}",
                    "exit_reason": _RULE_NAME,
                    "pnl_usd":     leg_float[leg.symbol],
                })
                leg.state.in_pos = False
                leg.state.direction = 0
                leg.state.entry_index = -1
                leg.state.entry_price = 0.0
                leg.state.partial_taken = False
                leg.state.partial_leg = None
                leg.state.stop_price_active = None
                leg.state.entry_market_state = {}


__all__ = ["H2RecycleRuleV2"]
