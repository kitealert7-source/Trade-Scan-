"""recycle_strategies.py — Per-leg strategies for basket directives.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5c.

Phase 5c provides real per-leg strategies that open positions for the
basket's recycle rule to act on. The simplest (and the one H2 needs) is
`ContinuousHoldStrategy` — opens once on the first bar, holds the
position continuously, never signals an exit. The H2CompressionRecycleRule
handles close+reopen events.

Why this exists separately from the per-symbol `strategies/<id>/strategy.py`
directories: basket legs are infrastructure-owned (the basket recycle rule
defines the strategy), not research-stage. Putting the leg strategies
under `tools/` makes the ownership explicit and keeps them out of the
per-symbol governance flow (no namespace_gate, no idea_registry entry,
no SIGNATURE_HASH).
"""
from __future__ import annotations

from typing import Any

import pandas as pd


__all__ = [
    "CointTriggerArmedState",
    "CointTriggerLegStrategy",
    "ContinuousHoldStrategy",
    "PineZRevArmedState",
    "PineZRevLegStrategy",
    "SpreadCrossArmedState",
    "SpreadCrossLegStrategy",
]


class SpreadCrossArmedState:
    """Shared arming state across both legs of a spread basket.

    Eliminates per-leg state drift in SpreadCrossLegStrategy. Both legs
    of the basket reference the SAME instance — arming and fire decisions
    are made atomically once per bar (by whichever leg evaluates first),
    and the other leg consults the shared state to fire at the SAME bar.

    Without this, if one leg's `check_entry` was called more times than
    the other's (which happens transiently around basket open / liquidate
    transitions), per-leg bar counters would drift and the two legs would
    fire entries on different bars.

    Mutated by SpreadCrossLegStrategy.check_entry. Reset to a fresh
    instance per directive (BasketRunner constructor in run_pipeline).
    """

    def __init__(self) -> None:
        # Last bar_ts at which we ran the per-bar arming logic. Used so
        # only the FIRST leg's check_entry on a given bar updates shared
        # state; the SECOND leg consults the now-current state.
        self.last_processed_ts: pd.Timestamp | None = None
        # Timestamp at which a cross_event was last seen that matches the
        # basket's watch direction. None = not armed.
        self.armed_ts: pd.Timestamp | None = None
        # Timestamp at which entry signal should fire (both legs read this
        # and return signal on a matching bar_ts).
        self.fire_at_ts: pd.Timestamp | None = None
        # Direction in which the basket was armed / will fire. +1 = UP-cross
        # entry (LONG spread); -1 = DN-cross entry (SHORT spread). In
        # uni-directional mode this stays at the strategy's cross_watch_direction.
        # In bidirectional mode (cross_watch_direction=0), this captures the
        # signed direction of whichever cross fired and flows through to the
        # entry signal so legs open with the correct per-cycle direction.
        self.armed_direction: int = 0
        # Direction stored at fire time so both legs see the same signed
        # direction when fire_at_ts == bar_ts (separate from armed_direction
        # because armed_direction is cleared on a confirmed fire).
        self.fire_direction: int = 0


class ContinuousHoldStrategy:
    """Open once at the first available bar; hold continuously.

    Used by basket directives where the recycle rule defines all exit
    behaviour. Returns a signal on the first `check_entry` call (signal
    sign = direction); returns None thereafter. `check_exit` always
    returns False so the engine never closes the position via signal —
    the recycle rule does that via direct BarState mutation.

    STRATEGY_SIGNATURE: declared explicitly to override the engine's
    default 2× ATR stop. Basket recycle rules own exit behaviour
    end-to-end; engine fallback stops would close positions before the
    rule's harvest target / floor can engage. Setting
    `atr_multiplier: 100000.0` makes the engine stop effectively
    unreachable (≈ 10,000 pips on 5m FX) — the recycle rule's safety
    caps (DD freeze 10%, margin freeze 15%, equity floor) provide the
    real risk control.
    """

    timeframe = "5m"

    # Marker for tools/basket_runner.py fast-path detection. ContinuousHold
    # only signals once (bar 1) and never asks the engine to evaluate
    # signals after, so BasketRunner can skip evaluate_bar entirely.
    # See Phase 5b.4b.
    _basket_fast_path = True

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "continuous_hold_first_bar"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators": [],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.01},   # actual lot set on BasketLeg
        "signal_version":            1,
        "signature_version":         2,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": False}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

    def __init__(self, symbol: str, direction: int = +1) -> None:
        if direction not in (+1, -1):
            raise ValueError(
                f"ContinuousHoldStrategy: direction must be +1 or -1, got {direction!r}."
            )
        self.symbol = symbol
        self.direction = direction
        self.name = f"continuous_hold_{symbol}"
        self._has_opened = False

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """No indicators required — pure time-based entry. The engine
        computes ATR internally when needed for its (now effectively
        disabled) stop fallback."""
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        if self._has_opened:
            return None
        self._has_opened = True
        return {"signal": int(self.direction)}

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False


class SpreadCrossLegStrategy:
    """Signal-triggered leg strategy for H3 spread baskets.

    Unlike ContinuousHoldStrategy (which opens once on bar 1 unconditionally),
    this strategy waits for an SMA-crossover signal on a pre-computed column
    in the leg's DataFrame. The basket recycle rule (e.g. H3SpreadV1Rule)
    handles all exits; this strategy never signals an exit.

    Two-stage entry logic (whipsaw filter):
      1. When `cross_event` column on the current bar equals our `direction`,
         enter "armed" state — record current bar index.
      2. After `delay_bars` have elapsed since arming, re-check `cross_side`
         on the current bar. If still equal to `direction`, return entry
         signal. If reverted during the wait, drop the arm (no entry).

    State persists across cycles: after the rule closes the leg
    (in_pos=False), check_entry is called again on subsequent bars and
    arming-on-cross resumes naturally. No internal reset needed.

    Required input columns on leg.df:
        cross_event: int (+1, -1, 0) — fires once per crossover
        cross_side : int (+1, -1, 0) — current side of SMA diff

    These are produced by indicators.stats.spread_sma_cross and joined
    onto each basket leg by tools.basket_data_loader.

    NOT fast-path eligible. Fast-path requires the leg to open on bar 1;
    we open conditionally and only after the warmup of the upstream
    spread_sma_cross indicator. BasketRunner auto-detects via the absence
    of `_basket_fast_path` and routes through the engine path.

    STRATEGY_SIGNATURE: same shape as ContinuousHoldStrategy — the engine
    ATR-fallback stop is effectively disabled (atr_multiplier 100000) so
    that exits are owned entirely by the recycle rule.
    """

    timeframe = "15m"

    # Deliberately NOT setting `_basket_fast_path` — we need evaluate_bar
    # to be called every bar so check_entry can watch the cross signal.

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "spread_sma_cross_signal"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators": ["indicators.stats.spread_sma_cross"],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.10},
        "signal_version":            1,
        "signature_version":         2,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": True}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

    def __init__(
        self,
        symbol: str,
        position_direction: int = +1,
        cross_watch_direction: int = +1,
        armed_state: SpreadCrossArmedState | None = None,
        signal_column: str = "cross_event",
        side_column: str = "cross_side",
        delay_bars: int = 12,
        bar_seconds: int = 300,
    ) -> None:
        """Init.

        Args:
            symbol: leg symbol (e.g. EURUSD).
            position_direction: +1 for long leg, -1 for short leg. Returned
                as the engine signal value on entry. Determines leg.direction.
            cross_watch_direction: +1 to enter on UP-cross (cross_event=+1),
                -1 to enter on DN-cross (cross_event=-1). For a USD-BEAR
                basket (long EURUSD + short USDJPY), BOTH legs watch UP-cross
                (cross_watch_direction=+1) but their position_direction differs.
            armed_state: SHARED SpreadCrossArmedState instance. Both legs
                of the same basket MUST reference the same instance so that
                arming + fire decisions are atomic at the basket level. If
                None, a fresh per-leg instance is created (unit-test
                convenience only — never use in production multi-leg flow).
            signal_column: leg.df column carrying cross_event.
            side_column: leg.df column carrying cross_side (used for whipsaw
                reconfirmation after the delay).
            delay_bars: number of bars to wait after cross_event fires before
                actually entering, to filter whipsaws. Default 12 (= 1 hour
                at 5m grid; equivalent to 4 bars on 15m). Reconfirmation
                checks cross_side == cross_watch_direction at end of wait.
            bar_seconds: seconds per bar at the leg's timeframe (default 300
                for 5m). Used to convert elapsed timestamp delta into bar
                count for the delay check.
        """
        if position_direction not in (+1, -1):
            raise ValueError(
                f"SpreadCrossLegStrategy: position_direction must be +1 or -1, "
                f"got {position_direction!r}."
            )
        if cross_watch_direction not in (+1, -1, 0):
            raise ValueError(
                f"SpreadCrossLegStrategy: cross_watch_direction must be +1, -1, or 0 "
                f"(bidirectional), got {cross_watch_direction!r}."
            )
        if delay_bars < 0:
            raise ValueError(
                f"SpreadCrossLegStrategy: delay_bars must be >= 0, got {delay_bars!r}."
            )
        if bar_seconds <= 0:
            raise ValueError(
                f"SpreadCrossLegStrategy: bar_seconds must be > 0, got {bar_seconds!r}."
            )
        self.symbol = symbol
        self.position_direction = position_direction
        self.cross_watch_direction = cross_watch_direction
        self.armed_state = armed_state if armed_state is not None else SpreadCrossArmedState()
        self.signal_column = signal_column
        self.side_column = side_column
        self.delay_bars = delay_bars
        self.bar_seconds = bar_seconds
        if cross_watch_direction == 0:
            xwatch_tag = "bi"
        else:
            xwatch_tag = "+" if cross_watch_direction > 0 else "-"
        self.name = (
            f"spread_cross_{symbol}_pos{'+' if position_direction > 0 else '-'}"
            f"_xwatch{xwatch_tag}"
        )

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Spread-cross columns are joined upstream by basket_data_loader.

        Verifies the expected columns exist on entry — fail-fast invariant
        (per Inv 1, no silent missing-column handling).
        """
        missing = [c for c in (self.signal_column, self.side_column)
                   if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"SpreadCrossLegStrategy({self.symbol}): leg.df missing required "
                f"columns {missing}. Expected upstream join from "
                f"basket_data_loader / spread_sma_cross indicator."
            )
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        """Two-leg synchronized entry decision.

        The first leg's check_entry on a given bar_ts updates the shared
        SpreadCrossArmedState (arm / reconfirm / set fire_at_ts). The
        second leg sees the updated state and returns the same signal at
        the same bar.

        Per-leg state drift is structurally impossible because all state
        lives in `self.armed_state` (shared) and is updated only ONCE per
        bar (gated by `last_processed_ts`).
        """
        # bar_ts from the row's index name (df is DatetimeIndex-keyed).
        # ctx.time is not always present on ContextView (depends on whether
        # 'time' is a column in the df, which it isn't for basket loads);
        # row.name is the canonical way to get the bar timestamp.
        bar_ts = pd.Timestamp(ctx.row.name)
        cross_event = int(ctx.get(self.signal_column, 0) or 0)
        cross_side = int(ctx.get(self.side_column, 0) or 0)
        state = self.armed_state

        # Per-bar atomic update: only run the arming logic once per bar_ts
        # regardless of which leg processed first.
        if state.last_processed_ts != bar_ts:
            state.last_processed_ts = bar_ts

            # Arm on cross_event match. In uni-directional mode (+1 or -1),
            # only that direction arms. In bidirectional mode (cross_watch_direction=0),
            # EITHER direction arms; the signed direction is stored in
            # state.armed_direction and flows through to fire_direction.
            should_arm = (
                cross_event != 0 and (
                    self.cross_watch_direction == 0
                    or cross_event == self.cross_watch_direction
                )
            )
            if should_arm:
                state.armed_ts = bar_ts
                state.armed_direction = cross_event

            # Confirmation check
            if state.armed_ts is not None:
                elapsed_seconds = (bar_ts - state.armed_ts).total_seconds()
                elapsed_bars = int(elapsed_seconds // self.bar_seconds)
                if elapsed_bars >= self.delay_bars:
                    expected_side = state.armed_direction
                    if cross_side == expected_side and expected_side != 0:
                        # Both legs will fire at this bar_ts.
                        state.fire_at_ts = bar_ts
                        state.fire_direction = expected_side
                        state.armed_ts = None
                        state.armed_direction = 0
                    else:
                        # Whipsaw — reverted during the wait. Drop the arm.
                        state.armed_ts = None
                        state.armed_direction = 0

        # Each leg reads shared fire_at_ts; if it matches current bar_ts,
        # the leg returns its own position_direction scaled by fire_direction.
        # In uni-directional mode fire_direction == cross_watch_direction so the
        # scale is +1 (no-op vs legacy behavior). In bidirectional mode
        # (cross_watch_direction=0), fire_direction matches the cross that
        # actually fired, so legs flip direction per cycle accordingly.
        if state.fire_at_ts == bar_ts:
            if self.cross_watch_direction == 0:
                # Bidirectional: scale by the cross direction that fired.
                signal = int(self.position_direction) * int(state.fire_direction)
            else:
                # Legacy uni-directional: position_direction is the signal.
                signal = int(self.position_direction)
            return {"signal": signal}
        return None

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False


# ---------------------------------------------------------------------------
# Pine port — z_r reversal, always-in-market (pine_ratio_zrev_v1)
# ---------------------------------------------------------------------------


class PineZRevArmedState:
    """Shared coordinator state for Pine z_r reversal baskets.

    Mirrors the PROPOSED/APPROVED phases of CointTriggerArmedState but is
    driven by per-bar z_r crosses computed in the rule (not screener ledger).

    State machine per cycle:
        IDLE      → no signal cross seen (all fields cleared)
        PROPOSED  → leg saw pine_zrev_signal != 0 on bar N; pending_trigger_ts=N
        APPROVED  → rule accepted on bar N; approved_fire_ts = next aligned bar
        FIRED     → leg returned signal at approved_fire_ts; rule clears on next apply
        CLEARED   → IDLE again

    Always-in-market reversal: when basket is OPEN and a cross in the opposite
    direction fires, the rule LIQUIDATEs the current basket AND sets a fresh
    proposal (with reversed direction) in the same apply() pass — no idle gap.

    Field ownership (writes):
        leg.check_entry  : pending_trigger_ts, proposed_direction, last_processed_ts
        rule.apply       : approved_fire_ts, approved, reset() after fire

    A fresh instance must be created per directive (BasketRunner construction).
    Shared across both legs of the basket by reference.
    """

    def __init__(self) -> None:
        self.last_processed_ts: pd.Timestamp | None = None
        # PROPOSED phase
        self.pending_trigger_ts: pd.Timestamp | None = None
        self.proposed_direction: int = 0   # +1 LONG_SPREAD / -1 SHORT_SPREAD
        # APPROVED phase
        self.approved_fire_ts: pd.Timestamp | None = None
        self.approved: bool = False

    def reset(self) -> None:
        """Return to IDLE. Called by the rule after fire/rejection."""
        self.pending_trigger_ts = None
        self.proposed_direction = 0
        self.approved_fire_ts = None
        self.approved = False


class PineZRevLegStrategy:
    """Pine port leg strategy — z_r reversal, always-in-market.

    Reads `pine_zrev_signal` column on leg.df. The column is attached by the
    pine_ratio_zrev_v1 rule on its first apply() call (computed from both legs'
    close prices via the ratio_hedged_spread_zscore indicator).

    Signal semantics on the column:
        +1 = z_r crossed -z_entry from above  → LONG SPREAD (long A, short r̄·B)
        -1 = z_r crossed +z_entry from below  → SHORT SPREAD (short A, long r̄·B)
         0 = no cross this bar

    Two-bar protocol (identical to CointTriggerLegStrategy):
        Bar N    : leg sees signal != 0, sets pending in shared state
        Bar N    : rule.apply inspects pending, locks r̄_entry, sets approved_fire_ts = N+1
        Bar N+1  : leg sees approved_fire_ts == N+1, returns signal
        Bar N+1  : engine queues open at N+2 open

    Always-in-market reversal: when basket is open in direction X and an
    opposite-direction signal fires, the rule liquidates AND re-proposes the
    new direction in the same bar. The leg's check_entry on the next bar
    will then return the reversed signal.

    STRATEGY_SIGNATURE: same boilerplate as CointTriggerLegStrategy — engine
    ATR-fallback stop effectively disabled (atr_multiplier 100000) so that
    exits are owned entirely by the recycle rule.
    """

    timeframe = "1d"

    # Not fast-path eligible — fires conditionally based on z_r crosses.

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "pine_zrev_reversal_proposal"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators": [],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.01},
        "signal_version":            1,
        "signature_version":         2,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": True}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

    def __init__(
        self,
        symbol: str,
        position_direction: int = +1,
        *,
        armed_state: PineZRevArmedState | None = None,
        signal_column: str = "pine_zrev_signal",
    ) -> None:
        """Init.

        Args:
            symbol: leg symbol (e.g. CHFJPY).
            position_direction: +1 long leg, -1 short leg (declared in directive).
                The returned engine signal at fire time is
                position_direction * proposed_direction; LONG_SPREAD preserves
                the directive's base orientation, SHORT_SPREAD inverts it.
            armed_state: SHARED PineZRevArmedState across both legs. Required
                for production multi-leg flow.
            signal_column: leg.df column carrying the z_r cross signal.
                Default matches the column attached by PineRatioZRevRule.
        """
        if position_direction not in (+1, -1):
            raise ValueError(
                f"PineZRevLegStrategy: position_direction must be +1 or -1, "
                f"got {position_direction!r}."
            )
        self.symbol = symbol
        self.position_direction = position_direction
        self.armed_state = armed_state if armed_state is not None else PineZRevArmedState()
        self.signal_column = signal_column
        self.name = f"pine_zrev_{symbol}_pos{'+' if position_direction > 0 else '-'}"

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """No upstream join validation — signal column is attached by the rule
        at first apply() (the column doesn't exist at prepare time)."""
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        """Two-bar protocol — proposal on signal bar, fire on approved bar."""
        bar_ts = pd.Timestamp(ctx.row.name)
        state = self.armed_state

        # PROPOSAL phase: only first leg per bar updates shared state
        if state.last_processed_ts != bar_ts:
            state.last_processed_ts = bar_ts

            # Only propose if no cycle in flight
            if state.pending_trigger_ts is None and state.approved_fire_ts is None:
                signal_value = int(ctx.get(self.signal_column, 0) or 0)
                if signal_value in (+1, -1):
                    state.pending_trigger_ts = bar_ts
                    state.proposed_direction = signal_value

        # FIRE phase: rule approved on prior bar
        if state.approved and state.approved_fire_ts == bar_ts:
            if state.proposed_direction == 0:
                return None
            signal = int(self.position_direction) * int(state.proposed_direction)
            return {"signal": signal}
        return None

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False


# ---------------------------------------------------------------------------
# COINTREV v1.2 — trigger-driven β-weighted spread (cointegration_meanrev_v1_2)
# ---------------------------------------------------------------------------


class CointTriggerArmedState:
    """Shared coordinator state for COINTREV v1.2 baskets.

    Two-bar leg ↔ rule protocol — state machine per cycle:

        IDLE      → no trigger observed (all fields cleared)
        PROPOSED  → leg saw coint_trigger=True on bar N; pending_trigger_ts=N;
                    rule has not yet inspected
        APPROVED  → rule accepted on bar N; approved_fire_ts=<next bar>;
                    β-sized lots already mutated on legs by the rule
        FIRED     → leg returned signal at approved_fire_ts; engine will open
                    at next_bar_open; rule clears state on subsequent apply
        CLEARED   → back to IDLE; waiting for next coint_trigger

    Field ownership (writes):
        leg.check_entry          : pending_trigger_ts, pending_trigger_as_of,
                                   proposed_direction, last_processed_ts
        rule.apply (approval)    : approved_fire_ts, approved
        rule.apply (clear)       : reset() — back to IDLE

    Invariants:
        - approved_fire_ts is STRICTLY GREATER than pending_trigger_ts
          (rule must assert this on approval — same-bar fire would defeat
          the pre-open sizing guarantee).
        - At most one in-flight cycle: leg refuses to propose while
          pending_trigger_ts or approved_fire_ts is non-None.
        - approved=True implies leg.lot was mutated to β-sized values BEFORE
          this state was set.

    A fresh instance must be created per directive (BasketRunner construction
    in run_pipeline). Shared across both legs of the basket by reference.
    """

    def __init__(self) -> None:
        self.last_processed_ts: pd.Timestamp | None = None
        # PROPOSED phase
        self.pending_trigger_ts: pd.Timestamp | None = None
        self.pending_trigger_as_of: pd.Timestamp | None = None
        self.proposed_direction: int = 0   # +1 LONG_SPREAD / -1 SHORT_SPREAD
        # APPROVED phase
        self.approved_fire_ts: pd.Timestamp | None = None
        self.approved: bool = False

    def reset(self) -> None:
        """Return to IDLE. Called by the rule after fire/rejection."""
        self.pending_trigger_ts = None
        self.pending_trigger_as_of = None
        self.proposed_direction = 0
        self.approved_fire_ts = None
        self.approved = False


class CointTriggerLegStrategy:
    """Signal-proposal leg strategy for COINTREV v1.2 β-weighted spread baskets.

    Pure signal-proposal surface — does NOT decide trade-lifecycle policy. The
    leg detects `coint_trigger==True` on a bar, exposes the proposal in shared
    state, and waits. The basket rule (`cointegration_meanrev_v1_2`) inspects
    the proposal, enforces min-gap + open-position policy, computes β-weighted
    lots from `coint_beta_at_trigger`, mutates `leg.lot` to the sized values,
    and signs off via `approved_fire_ts` (strictly LATER than the proposal
    bar). The leg returns the engine entry signal on the approved fire bar.

    The two-bar protocol avoids "open-then-mutate" lot adjustment: by the
    time the engine actually opens the position (next_bar_open after fire),
    `leg.lot` is already at the correct β-sized value.

    Required leg.df columns (joined upstream by basket_data_loader when
    the directive sets `basket.cointegration_join.lookback_days`):
        coint_trigger        : bool                            (this strategy)
        coint_direction      : str ('LONG_SPREAD'/'SHORT_SPREAD')  (this strategy)
        coint_beta_at_trigger: float                           (rule reads)
        coint_z_at_trigger   : float                           (rule may read)
        coint_regime         : str                             (rule reads)
        coint_current_zscore : float                           (rule reads)

    Architectural boundary:
        leg responsibilities = synchronize legs, expose fire signal, expose
            direction, expose trigger timestamp.
        rule responsibilities = consume/reject trigger, enforce min-gap,
            enforce open-position policy, apply lot sizing, manage exits,
            track replay state.

    NOT fast-path eligible — fires conditionally, not on bar 1.

    STRATEGY_SIGNATURE: same boilerplate as SpreadCrossLegStrategy — engine
    ATR-fallback stop effectively disabled (atr_multiplier 100000) so that
    exits are owned entirely by the recycle rule. `position_management.lots`
    is a placeholder; the rule mutates `leg.lot` to β-sized values BEFORE
    the engine opens the position (two-bar protocol).
    """

    timeframe = "15m"

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "coint_trigger_proposal"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators": [],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.01},
        "signal_version":            1,
        "signature_version":         2,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": True}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

    def __init__(
        self,
        symbol: str,
        position_direction: int = +1,
        *,
        armed_state: CointTriggerArmedState | None = None,
        trigger_column: str = "coint_trigger",
        direction_column: str = "coint_direction",
    ) -> None:
        """Init.

        Args:
            symbol: leg symbol (e.g. NZDUSD).
            position_direction: +1 long leg, -1 short leg (declared in directive).
                The returned engine signal at fire time is
                position_direction * proposed_direction; LONG_SPREAD preserves
                the directive's base orientation, SHORT_SPREAD inverts it.
            armed_state: SHARED CointTriggerArmedState across both legs of the
                basket. Required for production multi-leg flow; per-leg
                instantiation (default fallback) is unit-test convenience only.
            trigger_column / direction_column: leg.df column names. Defaults
                match the basket_data_loader auto-join contract.
        """
        if position_direction not in (+1, -1):
            raise ValueError(
                f"CointTriggerLegStrategy: position_direction must be +1 or -1, "
                f"got {position_direction!r}."
            )
        self.symbol = symbol
        self.position_direction = position_direction
        self.armed_state = armed_state if armed_state is not None else CointTriggerArmedState()
        self.trigger_column = trigger_column
        self.direction_column = direction_column
        self.name = (
            f"coint_trigger_{symbol}_pos{'+' if position_direction > 0 else '-'}"
        )

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cointegration columns are joined upstream by basket_data_loader
        when the directive sets `basket.cointegration_join.lookback_days`.

        Fail-fast on missing columns (Inv 1 — no silent missing-column
        handling). `coint_beta_at_trigger` etc. are the rule's concern; we
        only verify what the LEG needs.
        """
        missing = [c for c in (self.trigger_column, self.direction_column)
                   if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"CointTriggerLegStrategy({self.symbol}): leg.df missing required "
                f"columns {missing}. Expected upstream join from basket_data_loader "
                f"(directive must set basket.cointegration_join.lookback_days)."
            )
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        """Two-bar protocol — proposal on trigger bar, fire on approved bar.

        Per-bar atomic update: only the first leg processed on a given bar_ts
        runs the proposal logic; both legs read shared state for fire-decision.
        State machine guarded by ownership rules (see CointTriggerArmedState
        docstring); leg only writes PROPOSED-phase fields.
        """
        bar_ts = pd.Timestamp(ctx.row.name)
        state = self.armed_state

        # PROPOSAL phase (Bar N): single-leg-side per-bar atomicity.
        if state.last_processed_ts != bar_ts:
            state.last_processed_ts = bar_ts

            # Refuse to propose while a cycle is already in flight (one
            # in-flight proposal at a time — base-run invariant; pyramid
            # variants would lift this in a future v1.2.x).
            if state.pending_trigger_ts is None and state.approved_fire_ts is None:
                coint_trigger = bool(ctx.get(self.trigger_column, False))
                if coint_trigger:
                    direction_str = ctx.get(self.direction_column, "")
                    if direction_str == "LONG_SPREAD":
                        proposed_dir = +1
                    elif direction_str == "SHORT_SPREAD":
                        proposed_dir = -1
                    else:
                        # Malformed direction → leave proposal at 0; rule
                        # will reject. Defensive — auto-join contract
                        # guarantees a valid string on trigger=True bars.
                        proposed_dir = 0
                    state.pending_trigger_ts = bar_ts
                    state.pending_trigger_as_of = bar_ts.normalize()
                    state.proposed_direction = proposed_dir

        # FIRE phase (Bar N+1): rule approved on prior bar.
        if state.approved and state.approved_fire_ts == bar_ts:
            if state.proposed_direction == 0:
                # Should never happen post-approval, but guard anyway.
                return None
            signal = int(self.position_direction) * int(state.proposed_direction)
            return {"signal": signal}
        return None

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False
