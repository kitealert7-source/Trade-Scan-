"""H2CompressionRecycleRule — basket-level recycle on USD_SYNTH compression.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 3.
Validated parameters (MEMORY.md project_usd_basket_recycle_research.md):
  * 0.02 EURUSD long + 0.01 USDJPY short
  * stake_usd = 1000, harvest_threshold_usd = 2000
  * gate: USD_SYNTH.compression_5d >= 10

Behavior (V7 spec, replicated verbatim from tools/research/basket_sim.py):
  Per bar (after per-leg evaluate_bar advances):
    1. compute floating PnL = sum over legs of leg.lot * leg.direction * pnl_per_unit
    2. read regime factor for this bar; gate_open = factor >= threshold
    3. if gate_open AND floating_pnl >= harvest_threshold_usd:
         - close BOTH legs (write exit trades into leg.trades, clear BarState)
         - harvest += floating_pnl
         - re-open BOTH legs at the same direction/lot, entry at current bar close

Implementation notes:
  - This rule directly mutates BarState. evaluate_bar's per-bar order is
    already complete by the time apply() runs (BasketRunner.run() loop).
  - The rule does NOT call evaluate_bar itself. Re-entry registers a
    new entry trade record + sets state.in_pos / state.entry_price /
    state.entry_index manually, matching the format engine entries use.
  - PnL math is inlined for the two H2 conventions only (usd_quote +
    usd_base). Cross-JPY conventions are out of scope for H2.

Registry alignment:
  name = "H2_v7_compression"; version = 1.
  Any change in behavior REQUIRES bumping version + appending to
  governance/recycle_rules/registry.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tools.basket_runner import BasketLeg


_RULE_NAME = "H2_v7_compression"
_RULE_VERSION = 1
_LOT_UNITS = 100_000  # FX standard lot

# Per-symbol PnL conventions used by H2. Extensible later but kept tight
# here to match basket_sim's H2-specific math.
_USD_QUOTE = {"EURUSD"}        # PnL_USD = lot * units * (price - entry)
_USD_BASE  = {"USDJPY"}        # PnL_USD = lot * units * (price - entry) / price


def _leg_pnl_usd(leg: BasketLeg, current_price: float) -> float:
    """Floating PnL for one leg given current bar close."""
    if not leg.state.in_pos:
        return 0.0
    entry = leg.state.entry_price
    if leg.symbol in _USD_QUOTE:
        return leg.direction * leg.lot * _LOT_UNITS * (current_price - entry)
    if leg.symbol in _USD_BASE:
        if current_price <= 0:
            return 0.0
        return leg.direction * leg.lot * _LOT_UNITS * (current_price - entry) / current_price
    raise ValueError(
        f"H2CompressionRecycleRule: symbol {leg.symbol!r} convention unknown. "
        f"H2 supports {_USD_QUOTE | _USD_BASE} only."
    )


@dataclass
class H2CompressionRecycleRule:
    """Basket-level rule: harvest on compression-gated profit threshold.

    Parameters:
      threshold:           USD_SYNTH compression_5d gate, e.g. 10.0
      stake_usd:           target equity contribution per re-entry, e.g. 1000.0
      harvest_threshold_usd: floating PnL trigger, e.g. 2000.0
      factor_column:       DataFrame column on every leg.df that carries the
                           regime factor (forward-filled if sparse). e.g.
                           'compression_5d_5min_ffill'.
    """
    threshold:           float
    stake_usd:           float
    harvest_threshold_usd: float
    factor_column:       str

    name:    str = _RULE_NAME
    version: int = _RULE_VERSION

    # Telemetry — accessible after run() for assertions in tests.
    harvested_total_usd: float = 0.0
    recycle_events:      list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.threshold <= 0:
            raise ValueError("H2 rule threshold must be > 0.")
        if self.stake_usd <= 0:
            raise ValueError("H2 rule stake_usd must be > 0.")
        if self.harvest_threshold_usd <= 0:
            raise ValueError("H2 rule harvest_threshold_usd must be > 0.")
        if not self.factor_column:
            raise ValueError("H2 rule factor_column must be a non-empty string.")

    # ---- BasketRule.apply --------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        # Phase 3 invariant: rule runs AFTER per-leg evaluate_bar. By the
        # time we observe state, any SL/TP exits already fired this bar.
        # We only act on the basket-level recycle decision here.

        # Floating PnL across all legs (only positions currently open count).
        floating_pnl = 0.0
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_close = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                # Sparse data or non-numeric — abort gracefully (no recycle this bar).
                return
            bar_closes[leg.symbol] = bar_close
            floating_pnl += _leg_pnl_usd(leg, bar_close)

        # Regime gate: read the factor from the FIRST leg's df. The factor
        # is broadcast across all legs in the corpus (Phase 7a.0 freeze).
        primary_df = legs[0].df
        if self.factor_column not in primary_df.columns:
            return  # no gate data -> no recycle (fail-safe)
        try:
            factor_val = float(primary_df.loc[bar_ts, self.factor_column])
        except (KeyError, ValueError, TypeError):
            return
        gate_open = factor_val >= self.threshold

        if not gate_open:
            return
        if floating_pnl < self.harvest_threshold_usd:
            return

        # Trigger recycle: close every open leg, harvest, re-open.
        self.harvested_total_usd += floating_pnl
        event: dict[str, Any] = {
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "factor_value":      factor_val,
            "floating_pnl_usd":  floating_pnl,
            "harvested_total":   self.harvested_total_usd,
            "leg_closes":        dict(bar_closes),
            "leg_actions":       [],
        }

        for leg in legs:
            bc = bar_closes[leg.symbol]
            if leg.state.in_pos:
                # Synthesize an exit trade in the engine's trade-dict shape.
                exit_trade = {
                    "entry_index": leg.state.entry_index,
                    "exit_index":  i,
                    "direction":   leg.direction,
                    "entry_price": leg.state.entry_price,
                    "exit_price":  bc,
                    "exit_source": "BASKET_RECYCLE",
                    "exit_reason": _RULE_NAME,
                }
                leg.trades.append(exit_trade)
                # Reset position state.
                leg.state.in_pos = False
                leg.state.direction = 0
                leg.state.entry_index = -1
                leg.state.entry_price = 0.0
                leg.state.partial_taken = False
                leg.state.partial_leg = None
                leg.state.stop_price_active = None
                leg.state.entry_market_state = {}
                event["leg_actions"].append({"symbol": leg.symbol, "action": "closed_for_recycle", "exit_price": bc})

            # Re-open immediately at this bar's close at original direction/lot.
            leg.state.in_pos = True
            leg.state.direction = leg.direction
            leg.state.entry_index = i
            leg.state.entry_price = bc
            leg.state.entry_market_state = {"initial_stop_price": bc}  # no SL — basket-level harvest only
            event["leg_actions"].append({"symbol": leg.symbol, "action": "reopened", "entry_price": bc})

        self.recycle_events.append(event)


__all__ = ["H2CompressionRecycleRule"]
