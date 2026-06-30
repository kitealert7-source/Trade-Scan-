"""basket_runner.py — N-leg basket orchestrator over engine_abi.v1_5_11.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 2 (Section 7-8). New consumer
of `engine_abi.v1_5_11`; imports nothing from the engine source directly.
The Phase 0a ABI is the only path in.

Phase 2 contract (skeleton): per-leg state is independent, no basket-level
rules. Output is byte-identical to running engine_abi.v1_5_11.evaluate_bar
N times independently on each leg. The `rules` argument is the future
extension point for Phase 3's RecycleRule + regime_gate + harvest logic;
when empty (Phase 2 default), the runner is pure orchestration.

Phase 3+ (NOT in this module yet):
  * RecycleRule plugin interface (BasketRule below is the reserved seam).
  * Cross-leg state: equity, floating PnL, margin, harvest events.
  * Regime-gate adapter (USD_SYNTH.compression_5d etc.).

Acceptance gate (Phase 2): `tests/test_basket_runner_phase2.py` exercises
the equivalence test against engine_abi.v1_5_11.evaluate_bar in two ways:
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

from engines.execution_fill import bar_spread, exec_fill

from engine_abi.v1_5_11 import (
    BarState,
    ENGINE_VERSION,
    EngineConfig,
    StrategyProtocol,
    apply_regime_model,
    evaluate_bar,
    finalize_force_close,
    resolve_engine_config,
)

# SINGLE SOURCE OF TRUTH for the basket ENGINE IDENTITY. basket_runner is the
# ONE module that imports the basket compute ABI (the `from engine_abi.v1_5_11`
# line above); ENGINE_VERSION re-exported here IS that module's version. EVERY
# basket engine STAMP must derive from these symbols, never from a second
# independent `from engine_abi.v1_5_X import` or get_engine_version() -- that is
# how a stamp drifts from the compute (in EITHER direction). Consumers:
# run_pipeline._basket_compute_engine_version() (backtest stamps) and the
# live_basket producers (heartbeat stamp). If a future engine promotion bumps
# the import above, ENGINE_VERSION/ENGINE_ABI follow automatically and every
# stamp moves with the compute. Locked by tests/test_engine_identity_convergence.py.
# Doctrine: memory engine_identity_is_compute_not_stamp.
#
# ENGINE_ABI is sourced from config.engine_authority (the canonical-engine NAME
# authority, which imports no engine) and asserted == the `:38` static import
# target above. The two can never silently disagree: a one-sided edit (changing
# :38 OR the authority but not both) fails closed at module load. This is
# compute-binding by verification, not dispatch -- UNIFIED_ENGINE_AUTHORITY_PLAN.md.
from config.engine_authority import CANONICAL_ENGINE_ABI as ENGINE_ABI

assert ENGINE_ABI == "engine_abi.v1_5_11", (
    "basket ENGINE_ABI diverged from the static import target at "
    f"basket_runner.py:40 (got {ENGINE_ABI!r}, expected 'engine_abi.v1_5_11'). "
    "The authority constant and the :40 import must name the same module; flip "
    "them together (engine re-point, V1_5_10_CANONICAL_FLIP_DESIGN.md §3a)."
)

__all__ = [
    "BasketLeg", "BasketRule", "BasketRunner", "ENGINE_VERSION", "ENGINE_ABI",
]


# ---------------------------------------------------------------------------
# Leg + Rule shapes
# ---------------------------------------------------------------------------


@dataclass
class BasketLeg:
    """One leg of a basket — symbol, lot, direction, per-leg strategy, state.

    `df` is the per-symbol OHLC DataFrame. It is mutated in place by
    `strategy.prepare_indicators` and `apply_regime_model` during _prepare(),
    so the caller must pass a copy if it intends to reuse the source frame.

    Direction model — IMPORTANT
    ---------------------------
    `leg.direction` is the **YAML BASE** orientation declared in the directive
    (+1 long, -1 short). It is set once at __init__ and is NOT cycle-aware.
    For leg strategies that produce variable-sign signals (PineZRev,
    CointTrigger, H3 bidirectional), the per-cycle direction lives on
    `leg.state.direction` after the engine fills.

    P&L / margin / trade-emit / per-bar-record code MUST read
    `leg.effective_direction` (cycle-aware property below), not
    `leg.direction` (which would sign-flip P&L on SHORT_SPREAD cycles).
    This was the root of the 2026-05-24 leg_direction_flip_bug — see
    RESEARCH_MEMORY entry of that date and commits 92fb187 / e0a1d8c for
    forensic context.
    """
    symbol:    str
    lot:       float
    direction: int                                  # +1 long, -1 short (YAML BASE; immutable post-init)
    df:        pd.DataFrame
    strategy:  StrategyProtocol
    state:     BarState           = field(default_factory=BarState)
    config:    EngineConfig | None = None
    trades:    list[dict[str, Any]] = field(default_factory=list)

    @property
    def effective_direction(self) -> int:
        """Cycle-aware direction. Use this everywhere P&L / margin /
        trade-emit / per-bar-record code needs the position's actual sign.

        Returns `state.direction` (set by the engine from check_entry's
        signal sign on open) when the leg is in-position with a signed
        direction; falls back to `self.direction` (YAML BASE) otherwise.

        Why this exists: leg strategies like PineZRevLegStrategy and
        CointTriggerLegStrategy emit `signal = position_direction *
        proposed_direction`, so SHORT_SPREAD cycles open with
        `state.direction == -direction`. Reading `leg.direction` directly
        in PnL math would sign-flip the accounting on those cycles.
        """
        if self.state.in_pos and self.state.direction in (-1, +1):
            return self.state.direction
        return self.direction


class BasketRule(Protocol):
    """Phase 3+ extension point. A rule mutates basket-level state across
    legs between per-bar leg evaluations.

    Phase 2 defines the Protocol shape only — there are no implementations
    yet, and `BasketRunner.run()` with no rules is required to be a pure
    orchestrator. A future RecycleRule will implement this interface.

    Warmup contract (2026-05-30, Protocol extension):
        Rules MAY implement `required_warmup_bars(self) -> int` to declare
        how many bars of pre-start_date data their indicators need to be
        fully computed by the directive's start_date. Default by absence
        of implementation is 0 (no warmup). The pipeline reads this via
        `getattr(rule, 'required_warmup_bars', lambda: 0)()` and passes
        the max across all rules to BasketRunner.warmup_bars +
        basket_data_loader.leg_warmup_bars.

        Rules that need warmup override the method based on their own
        param-derived window math (NOT pipeline-side hard-coded formulas).
        See PineRatioZRevRule.required_warmup_bars for the reference
        implementation.
    """

    name: str

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Called after each per-bar leg evaluation. May mutate leg state."""
        ...

    def required_warmup_bars(self) -> int:
        """Bars of pre-start_date data this rule's indicators require for
        validity by start_date. Default 0 = no warmup. Optional Protocol
        method — pipeline uses getattr fallback for rules that don't
        implement it. Rules with windowing dependencies (z-score, ATR,
        EMA, half-life, etc.) override based on their own params."""
        ...


# ---------------------------------------------------------------------------
# BasketRunner
# ---------------------------------------------------------------------------


class BasketRunner:
    """Orchestrates a multi-leg basket via engine_abi.v1_5_11.evaluate_bar.

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

    def __init__(
        self,
        legs: list[BasketLeg],
        rules: list[BasketRule] | None = None,
        warmup_bars: int = 0,
    ) -> None:
        if not legs or len(legs) < 2:
            raise ValueError(f"BasketRunner requires >= 2 legs; got {len(legs)}.")
        if warmup_bars < 0:
            raise ValueError(
                f"BasketRunner: warmup_bars must be >= 0, got {warmup_bars!r}."
            )
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
        # Bars at the front of the aligned index that exist for indicator
        # warmup only — leg strategies AND basket rules see no signals /
        # apply during this window. Default 0 = byte-equivalent to pre-
        # 2026-05-30 behavior (every aligned bar is signal-eligible).
        # Mirrors the proven engine-side mute pattern in the canonical engine
        # (engine_dev/universal_research_engine/v1_5_11/main.py; originated in
        # v1_5_8, now in git history — consolidation 2026-06-30).
        self.warmup_bars: int = int(warmup_bars)

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

        Mirrors the setup block of engine_abi.v1_5_11.run_execution_loop.
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
        """The original Phase 2 implementation — always correct, slower.

        Warmup mute (2026-05-30): when `self.warmup_bars > 0`, the first
        `warmup_bars` aligned bars are processed for indicator computation
        only — leg strategies' check_entry / check_exit are wrapped to
        return None / False, and basket rules' apply() is skipped. This
        mirrors engine_dev/v1_5_8/main.py:88-104 (single-strategy path)
        so the basket pipeline has the same warmup contract as run_stage1.
        Default warmup_bars=0 → wrappers no-op → byte-equivalent to the
        pre-2026-05-30 behavior; every existing basket result is unchanged.
        """
        self._prepare()
        aligned = self._aligned_index()
        if len(aligned) == 0:
            raise RuntimeError(
                "BasketRunner: aligned index empty — leg DatetimeIndexes do not intersect."
            )

        # Construct positional views per leg over the aligned set.
        leg_views: list[pd.DataFrame] = [leg.df.loc[aligned].copy() for leg in self.legs]

        # --- Warmup mute setup (no-op when warmup_bars == 0). ---
        wrap_targets: list[tuple[Any, Any, Any]] = []  # (strategy, orig_check_entry, orig_check_exit)
        if self.warmup_bars > 0:
            warmup = self.warmup_bars
            for leg in self.legs:
                orig_ce = leg.strategy.check_entry
                orig_cx = leg.strategy.check_exit
                wrap_targets.append((leg.strategy, orig_ce, orig_cx))
                def _make_wrapped_check_entry(orig):
                    def wrapped(ctx):
                        if getattr(ctx, "index", 0) < warmup:
                            return None
                        return orig(ctx)
                    return wrapped
                def _make_wrapped_check_exit(orig):
                    def wrapped(ctx):
                        if getattr(ctx, "index", 0) < warmup:
                            return False
                        return orig(ctx)
                    return wrapped
                leg.strategy.check_entry = _make_wrapped_check_entry(orig_ce)
                leg.strategy.check_exit = _make_wrapped_check_exit(orig_cx)

        try:
            for i in range(len(aligned)):
                bar_ts = aligned[i]
                for leg, view in zip(self.legs, leg_views):
                    trade = evaluate_bar(view, i, leg.state, leg.strategy, leg.config)
                    if trade is not None:
                        leg.trades.append(trade)
                # Phase 3+: basket-level rules run after all legs have advanced.
                # Skip rule.apply during warmup — the rule's signal columns and
                # internal state would not be valid against muted legs.
                if i >= self.warmup_bars:
                    for rule in self.rules:
                        rule.apply(self.legs, i, bar_ts)
        finally:
            # Restore original strategy methods so subsequent runs of the
            # same strategy object (e.g. in tests) see un-wrapped behavior.
            for strategy, orig_ce, orig_cx in wrap_targets:
                strategy.check_entry = orig_ce
                strategy.check_exit = orig_cx

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
        min_bars = max(2, self.warmup_bars + 2)  # need warmup + signal-bar + fill-bar
        if len(aligned) < min_bars:
            raise RuntimeError(
                f"BasketRunner._run_fast_path: aligned index has {len(aligned)} bars; "
                f"need at least {min_bars} (warmup={self.warmup_bars} + signal-bar + fill-bar)."
            )

        leg_views: list[pd.DataFrame] = [leg.df.loc[aligned].copy() for leg in self.legs]

        # ---- Open every leg at the bar after warmup completes.
        # Fast-path strategies (ContinuousHoldStrategy + variants) signal once
        # at bar 0 with signal == direction; engine fills at bar 1 (next open).
        # When warmup_bars > 0, the equivalent positions are signal at
        # warmup_bars and fill at warmup_bars + 1. Default warmup_bars == 0
        # keeps fill_idx == 1 → byte-equivalent to pre-2026-05-30 behavior.
        fill_idx = self.warmup_bars + 1
        fill_ts = aligned[fill_idx]
        for leg, view in zip(self.legs, leg_views):
            entry_row = view.iloc[fill_idx]
            entry_open = float(entry_row.get("open", entry_row["close"]))
            # v1.5.10 direction-aware entry fill (fast path bypasses evaluate_bar,
            # so it charges here): long (BUY) at ask (raw), short (SELL) at bid
            # (= ask - per-bar embedded spread). No-op at spread=0 -> byte-identical
            # to frozen v1.5.9. Mirrors engine_abi.v1_5_11 evaluate_bar._exec_fill.
            fill_price = exec_fill(entry_open, is_sell=(leg.direction == -1),
                                   spread=bar_spread(entry_row))
            leg.state.in_pos = True
            leg.state.direction = leg.direction
            leg.state.entry_index = fill_idx
            leg.state.entry_price = fill_price
            # Seed extremes + initial stop from the CHARGED fill (not raw open),
            # else MFE/MAE enrichment + finalize_force_close desync fast-vs-engine.
            leg.state.trade_high = fill_price
            leg.state.trade_low = fill_price
            # Minimal entry_market_state — matches what the engine populates
            # for finalize_force_close to read. Optional fields stay absent;
            # the rule does not consult any of them.
            leg.state.entry_market_state = {
                "initial_stop_price": fill_price,
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
