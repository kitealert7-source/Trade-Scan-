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

Phase 5b.4b (engine bypass): `run(fast_path=...)` selects between two
execution paths. The engine path is always correct. The fast path skips
per-bar `evaluate_bar` for trivial leg strategies that opt in via the
`_basket_fast_path = True` class marker (only ContinuousHoldStrategy
today). Auto-detect picks fast when every leg qualifies; otherwise the
engine path runs. Fast vs engine parity is locked by
`tests/test_basket_fast_path_phase5b4b.py`.
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

    Basket-level primitives (extension point — see "PRIMITIVE OPERATIONS"
    section near the bottom of this class)
    ---------------------------------------------------------------------
    Methods grouped under that section are *mechanism-only* primitives that
    rules call to effect basket-level state changes. Rules decide WHEN; the
    runner decides HOW. This split is the long-term target so that:
      (a) Rule code is policy-only — no direct mutation of leg.lot or
          leg.state internals.
      (b) The same primitive can be reused by multiple basket strategies
          (the H2_recycle@1 / @2 / @3 / @4 family + future basket designs).
      (c) Primitives are testable in isolation against synthetic legs.

    Currently implemented:
      - soft_reset_basket(at_index, at_ts, at_prices): close all current
        sub-basket positions, reopen each leg fresh at initial_lot at the
        given prices. Used by cyclical strategies (e.g. H2_recycle@4
        bump-and-liquidate) that need to reset basket state mid-window
        without ending the basket lifecycle.

    Future primitives (intentionally deferred — added only when a new
    strategy needs them; doing them speculatively would be premature):
      - close_basket(reason): terminate basket lifecycle (would replace
        H2RecycleRule._exit_all).
      - add_to_leg(symbol, additional_lot, at_price): grow a leg's lot
        with weighted-avg entry-price update (would replace direct lot
        mutation in H2RecycleRule's recycle-add path).
      - realize_winner(symbol, at_price): close one leg's floating to a
        realized accumulator + reopen at current price (would replace
        H2RecycleRule's winner-bank path).

    Rule access to the runner
    ---------------------------------------------------------------------
    On `__init__`, the runner assigns `rule.basket_runner = self` on every
    attached rule. Rules that need to call primitives read this attribute;
    rules that don't need it (legacy rules) simply ignore it. No protocol
    change required — keeps existing rules untouched.
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

        # Capture initial lots — read by basket-level primitives such as
        # soft_reset_basket. Immutable for the lifetime of the runner; only
        # __init__ writes here. Rules that mutate leg.lot (e.g. recycle
        # adds) do NOT mutate this dict.
        self._initial_lots: dict[str, float] = {leg.symbol: leg.lot for leg in self.legs}

        # Back-reference injection — gives rules access to basket-level
        # primitives. Cyclical strategies (e.g. H2_recycle@4) read
        # `self.basket_runner` to call `soft_reset_basket`. Legacy rules
        # that don't need this attribute simply ignore it.
        for rule in self.rules:
            rule.basket_runner = self  # type: ignore[attr-defined]

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

    # --- fast-path detection ---------------------------------------------

    def _can_use_fast_path(self) -> bool:
        """Auto-detect whether every leg's strategy is fast-path eligible.

        A strategy opts in by setting `_basket_fast_path = True` as a class
        attribute. The marker is the strategy's promise that:
          (a) check_entry signals once on the first bar, returns None forever after
          (b) check_exit always returns False (only the rule closes positions)
          (c) prepare_indicators is idempotent / cheap (still called)

        Phase 5b.4b: only `tools.recycle_strategies.ContinuousHoldStrategy`
        carries this marker. Any custom strategy that does not set it falls
        back to the engine path automatically — the engine is the
        always-correct default.
        """
        return all(getattr(leg.strategy, "_basket_fast_path", False) for leg in self.legs)

    # --- run --------------------------------------------------------------

    def run(self, *, fast_path: bool | None = None) -> dict[str, list[dict[str, Any]]]:
        """Execute the basket. Returns per-leg trade lists keyed by symbol.

        Per-bar order (aligned timestamp `t`, engine path):
          1. for each leg: trade = evaluate_bar(view, i, leg.state, leg.strategy, leg.config)
          2. for each rule: rule.apply(self.legs, i, bar_ts=t)        [Phase 3+]
        After the loop: finalize_force_close per leg.

        Phase 5b.4b — `fast_path` selector:
          * None (default): auto-detect via `_can_use_fast_path()`. Every leg
            strategy must declare `_basket_fast_path = True`.
          * True: force fast path (raises if any leg lacks the marker).
          * False: force engine path (the always-correct fallback; useful
            when introducing a new rule and confirming parity).

        The fast path skips per-bar evaluate_bar entirely — it manually
        opens each leg at the next-bar open, runs only the rule loop, and
        finalizes. For ContinuousHold + H2RecycleRule on the canonical
        ~150k-bar windows this collapses ~300k evaluate_bar calls to zero,
        the dominant per-window runtime cost.
        """
        if fast_path is None:
            use_fast = self._can_use_fast_path()
        else:
            use_fast = bool(fast_path)
            if use_fast and not self._can_use_fast_path():
                missing = [
                    leg.symbol for leg in self.legs
                    if not getattr(leg.strategy, "_basket_fast_path", False)
                ]
                raise ValueError(
                    f"BasketRunner.run(fast_path=True) but legs {missing!r} have "
                    f"strategies without `_basket_fast_path = True`. Either add the "
                    f"marker (and confirm the strategy obeys the fast-path contract) "
                    f"or call run(fast_path=False)."
                )

        if use_fast:
            return self._run_fast_path()
        return self._run_engine_path()

    def _run_engine_path(self) -> dict[str, list[dict[str, Any]]]:
        """The original Phase 2 implementation — always correct, slower."""
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

    def _run_fast_path(self) -> dict[str, list[dict[str, Any]]]:
        """Engine-bypass path for trivial leg strategies. Phase 5b.4b.

        Equivalent contract to `_run_engine_path` IF every leg strategy
        obeys the fast-path contract:
          - check_entry signals once on the first bar (signal == direction),
            never again
          - check_exit always returns False (no signal-driven exits)
          - the engine's ATR fallback stop is unreachable (effectively
            disabled, e.g. `atr_multiplier: 100000.0`)

        Under those conditions, the engine path's per-bar work reduces to:
          bar 0  → check_entry returns {"signal": d}; engine sets pending_entry
          bar 1  → engine consumes pending_entry; opens at row.open; sets state.in_pos
          bar 2+ → check_entry returns None; check_exit returns False; in-pos no-op

        The fast path inlines bars 0-1 (manual open at view.iloc[1]['open'])
        and runs only the rule loop for bars 1..end. End-of-window: rule
        either harvested (legs already closed by `_exit_all`) or we call
        `finalize_force_close` which emits a DATA_END trade per still-open
        leg — byte-identical shape to the engine-path equivalent.
        """
        self._prepare()
        aligned = self._aligned_index()
        if len(aligned) < 2:
            raise RuntimeError(
                "BasketRunner._run_fast_path: aligned index has < 2 bars; need at "
                "least bar 0 (signal) + bar 1 (fill) for a next_bar_open open."
            )

        leg_views: list[pd.DataFrame] = [leg.df.loc[aligned].copy() for leg in self.legs]

        # ---- Bar 1: open every leg at next-bar open, mirroring engine path.
        fill_idx = 1
        fill_ts = aligned[fill_idx]
        for leg, view in zip(self.legs, leg_views):
            entry_row = view.iloc[fill_idx]
            entry_open = float(entry_row.get("open", entry_row["close"]))
            leg.state.in_pos = True
            leg.state.direction = leg.direction
            leg.state.entry_index = fill_idx
            leg.state.entry_price = entry_open
            leg.state.trade_high = entry_open
            leg.state.trade_low = entry_open
            # Minimal entry_market_state — matches what the engine populates
            # for finalize_force_close to read. Optional fields stay absent;
            # the rule does not consult any of them.
            leg.state.entry_market_state = {
                "initial_stop_price": entry_open,
                "fill_bar_idx":       fill_idx,
                "signal_bar_idx":     fill_idx - 1,
            }

        # ---- Bar 1..end: rule loop only. evaluate_bar is skipped entirely.
        # Maintain trade_high / trade_low from bar high/low so finalize_force_close
        # reports honest extremes for any leg the rule never closes.
        for i in range(fill_idx, len(aligned)):
            bar_ts = aligned[i]
            for leg, view in zip(self.legs, leg_views):
                if not leg.state.in_pos:
                    continue
                bar_row = view.iloc[i]
                bar_high = float(bar_row.get("high", bar_row.get("close", 0.0)))
                bar_low = float(bar_row.get("low", bar_row.get("close", 0.0)))
                if bar_high > leg.state.trade_high:
                    leg.state.trade_high = bar_high
                if bar_low < leg.state.trade_low:
                    leg.state.trade_low = bar_low
            for rule in self.rules:
                rule.apply(self.legs, i, bar_ts)

        # ---- End of window: any leg still open gets a DATA_END trade.
        for leg, view in zip(self.legs, leg_views):
            finalize_force_close(view, leg.state, leg.trades)

        return {leg.symbol: leg.trades for leg in self.legs}

    # =======================================================================
    # PRIMITIVE OPERATIONS (extension point)
    # =======================================================================
    # Mechanism-only basket-level operations. Rules call these to effect
    # changes; rules don't mutate leg state directly. See class docstring
    # for the design rationale and the list of intentionally-deferred
    # future primitives.

    def soft_reset_basket(
        self,
        at_index: int,
        at_ts: pd.Timestamp,
        at_prices: dict[str, float],
    ) -> None:
        """Close current sub-basket positions and reopen at initial_lot.

        Used by cyclical basket strategies (e.g. H2_recycle@4
        bump-and-liquidate) that need to reset basket state mid-window
        without terminating the basket lifecycle. The basket continues; a
        fresh sub-basket starts at `at_ts` at the given prices.

        Semantics
        ---------
        For each leg:
          - `leg.lot` resets to its initial value (captured in __init__).
          - `leg.state.entry_price` resets to `at_prices[symbol]`.
          - `leg.state.entry_index` resets to `at_index`.
          - `leg.state.trade_high` and `leg.state.trade_low` reset to
            `at_prices[symbol]` (fresh high/low tracking for the new
            sub-basket).
          - `leg.state.in_pos` stays True — basket is still alive.
          - `leg.state.entry_market_state` is preserved (engine internals
            are untouched; the rule does not consult them, and resetting
            them would break the engine's force-close path).

        What this method does NOT do (caller responsibilities)
        -------------------------------------------------------
          - Realize floating PnL. The caller (rule) must compute floating
            and add it to its own realized accumulator BEFORE calling
            this primitive. This split keeps realization-accounting
            policy with the rule (currency conventions, P&L formulas) and
            state-reset mechanics with the runner.
          - Reset rule-internal state. The rule resets its own counters
            (mode, consec_same_loser, peaks, etc.) after calling.
          - Record an event for analysis. The rule logs the cycle event
            in its own recycle_events / per_bar_records.
          - Mark the basket as exited. This is mid-window reset only —
            for true basket termination, use the (future) close_basket
            primitive or the legacy `_exit_all` rule method.

        Args
        ----
        at_index : bar index for entry_index field on each leg's BarState.
        at_ts    : bar timestamp (logged in events by callers; not stored
                   on legs by this primitive).
        at_prices: {symbol: current bar's price} for every leg in the
                   basket. Used to reset entry_price + trade_high + trade_low.

        Raises
        ------
        ValueError : if `at_prices` is missing any basket leg symbol or
                     contains a non-positive price (invariant: prices must
                     be valid for entry).
        """
        for leg in self.legs:
            if leg.symbol not in at_prices:
                raise ValueError(
                    f"BasketRunner.soft_reset_basket: at_prices missing symbol "
                    f"{leg.symbol!r}; got keys {sorted(at_prices.keys())}."
                )
            price = at_prices[leg.symbol]
            if not isinstance(price, (int, float)) or price <= 0:
                raise ValueError(
                    f"BasketRunner.soft_reset_basket: at_prices[{leg.symbol!r}] "
                    f"must be a positive number, got {price!r}."
                )

        for leg in self.legs:
            price = float(at_prices[leg.symbol])
            leg.lot = self._initial_lots[leg.symbol]
            leg.state.entry_price = price
            leg.state.entry_index = at_index
            leg.state.trade_high = price
            leg.state.trade_low = price
            # leg.state.in_pos intentionally NOT reset — basket continues
            # leg.state.entry_market_state intentionally NOT reset — engine
            #   internals (e.g. initial_stop_price, fill_bar_idx) are
            #   preserved so finalize_force_close on basket-end still works
