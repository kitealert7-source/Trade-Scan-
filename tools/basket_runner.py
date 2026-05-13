"""basket_runner.py — N-leg basket orchestrator over engine_abi.v1_5_9.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 2 (Section 7-8). New consumer
of `engine_abi.v1_5_9`; imports nothing from the engine source directly.
The Phase 0a ABI is the only path in.

Phase 2 contract (skeleton): per-leg state is independent, no basket-level
rules. Output is byte-identical to running engine_abi.v1_5_9.evaluate_bar
N times independently on each leg. The `rules` argument is the future
extension point for Phase 3's RecycleRule + regime_gate + harvest logic;
when empty (Phase 2 default), the runner is pure orchestration.

Phase 3+ (NOT in this module yet):
  * RecycleRule plugin interface (BasketRule below is the reserved seam).
  * Cross-leg state: equity, floating PnL, margin, harvest events.
  * Regime-gate adapter (USD_SYNTH.compression_5d etc.).

Acceptance gate (Phase 2): `tests/test_basket_runner_phase2.py` exercises
the equivalence test against engine_abi.v1_5_9.evaluate_bar in two ways:
  (a) per-leg trade lists identical when no rules attached.
  (b) BarState progression observable bar-by-bar identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from engine_abi.v1_5_9 import (
    BarState,
    EngineConfig,
    StrategyProtocol,
    apply_regime_model,
    evaluate_bar,
    finalize_force_close,
    resolve_engine_config,
)

__all__ = ["BasketLeg", "BasketRule", "BasketRunner"]


# ---------------------------------------------------------------------------
# Leg + Rule shapes
# ---------------------------------------------------------------------------


@dataclass
class BasketLeg:
    """One leg of a basket — symbol, lot, direction, per-leg strategy, state.

    `df` is the per-symbol OHLC DataFrame. It is mutated in place by
    `strategy.prepare_indicators` and `apply_regime_model` during _prepare(),
    so the caller must pass a copy if it intends to reuse the source frame.
    """
    symbol:    str
    lot:       float
    direction: int                                  # +1 long, -1 short
    df:        pd.DataFrame
    strategy:  StrategyProtocol
    state:     BarState           = field(default_factory=BarState)
    config:    EngineConfig | None = None
    trades:    list[dict[str, Any]] = field(default_factory=list)


class BasketRule(Protocol):
    """Phase 3+ extension point. A rule mutates basket-level state across
    legs between per-bar leg evaluations.

    Phase 2 defines the Protocol shape only — there are no implementations
    yet, and `BasketRunner.run()` with no rules is required to be a pure
    orchestrator. A future RecycleRule will implement this interface.
    """

    name: str

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Called after each per-bar leg evaluation. May mutate leg state."""
        ...


# ---------------------------------------------------------------------------
# BasketRunner
# ---------------------------------------------------------------------------


class BasketRunner:
    """Orchestrates a multi-leg basket via engine_abi.v1_5_9.evaluate_bar.

    The orchestrator does not own the strategies' behavior — each leg
    supplies its own StrategyProtocol-conforming object. The runner only
    interleaves per-bar evaluations and (Phase 3+) applies basket-level
    rules between them.
    """

    def __init__(self, legs: list[BasketLeg], rules: list[BasketRule] | None = None) -> None:
        if not legs or len(legs) < 2:
            raise ValueError(f"BasketRunner requires >= 2 legs; got {len(legs)}.")
        seen: set[str] = set()
        for leg in legs:
            if leg.symbol in seen:
                raise ValueError(f"BasketRunner: duplicate leg symbol {leg.symbol!r}.")
            seen.add(leg.symbol)
            if leg.direction not in (-1, +1):
                raise ValueError(
                    f"BasketRunner: leg {leg.symbol!r} direction must be +/-1, got {leg.direction!r}."
                )
            if leg.lot <= 0:
                raise ValueError(
                    f"BasketRunner: leg {leg.symbol!r} lot must be > 0, got {leg.lot!r}."
                )
        self.legs = legs
        self.rules: list[BasketRule] = list(rules) if rules else []

    # --- preparation -------------------------------------------------------

    def _prepare(self) -> None:
        """prepare_indicators + apply_regime_model + resolve_engine_config per leg.

        Mirrors the setup block of engine_abi.v1_5_9.run_execution_loop.
        State + trades reset to a fresh start so a runner instance can be
        re-run deterministically.
        """
        for leg in self.legs:
            leg.df = leg.strategy.prepare_indicators(leg.df)
            if not isinstance(leg.df.index, pd.DatetimeIndex):
                if "timestamp" in leg.df.columns:
                    leg.df.index = pd.DatetimeIndex(leg.df["timestamp"])
                elif "time" in leg.df.columns:
                    leg.df.index = pd.DatetimeIndex(leg.df["time"])
            try:
                leg.df = apply_regime_model(leg.df)
            except Exception as e:
                raise RuntimeError(
                    f"BasketRunner: leg {leg.symbol!r} regime model failed: {e}"
                ) from e
            leg.config = resolve_engine_config(leg.strategy)
            leg.state = BarState()
            leg.trades = []

    # --- bar alignment ----------------------------------------------------

    def _aligned_index(self) -> pd.DatetimeIndex:
        """Inner-join of every leg's DatetimeIndex. Phase 2 uses intersection;
        Phase 3+ may switch to outer-join with forward-fill once basket-level
        state requires every leg's price at every cross-leg event timestamp.
        """
        common = self.legs[0].df.index
        for leg in self.legs[1:]:
            common = common.intersection(leg.df.index)
        return common.sort_values()

    # --- run --------------------------------------------------------------

    def run(self) -> dict[str, list[dict[str, Any]]]:
        """Execute the basket. Returns per-leg trade lists keyed by symbol.

        Per-bar order (aligned timestamp `t`):
          1. for each leg: trade = evaluate_bar(view, i, leg.state, leg.strategy, leg.config)
          2. for each rule: rule.apply(self.legs, i, bar_ts=t)        [Phase 3+]
        After the loop: finalize_force_close per leg.
        """
        self._prepare()
        aligned = self._aligned_index()
        if len(aligned) == 0:
            raise RuntimeError(
                "BasketRunner: aligned index empty — leg DatetimeIndexes do not intersect."
            )

        # Construct positional views per leg over the aligned set.
        leg_views: list[pd.DataFrame] = [leg.df.loc[aligned].copy() for leg in self.legs]

        for i in range(len(aligned)):
            bar_ts = aligned[i]
            for leg, view in zip(self.legs, leg_views):
                trade = evaluate_bar(view, i, leg.state, leg.strategy, leg.config)
                if trade is not None:
                    leg.trades.append(trade)
            # Phase 3+: basket-level rules run after all legs have advanced.
            for rule in self.rules:
                rule.apply(self.legs, i, bar_ts)

        for leg, view in zip(self.legs, leg_views):
            finalize_force_close(view, leg.state, leg.trades)

        return {leg.symbol: leg.trades for leg in self.legs}
