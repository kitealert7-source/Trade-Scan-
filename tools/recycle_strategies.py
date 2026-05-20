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
    "ContinuousHoldStrategy",
    "SpreadCrossArmedState",
    "SpreadCrossLegStrategy",
    "CointMeanRevLegStrategy",
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


class CointMeanRevLegStrategy:
    """Leg strategy for COINTREV mean-reversion baskets.

    Sibling of SpreadCrossLegStrategy but uses cointegration features
    instead of SMA-cross. Watches for a 15m |z| crossing the entry
    threshold while the daily cointegration regime is qualified. Single
    round-trip per signal — the basket recycle rule
    (CointMeanRevV1Rule) handles all exits; this strategy never signals
    an exit.

    Entry condition (all four must hold on the same bar):
      1. qualified_daily == True   (forward-filled from history matrix)
      2. |intra_z| >= entry_z      (current bar — local extreme)
      3. |intra_z_prev| < entry_z  (this is the FIRST bar crossing)
      4. sign(intra_z) matches watch_direction
                                   (or watch_direction == 0 = bidirectional)

    Returns {"signal": position_direction} when condition met, None
    otherwise. Direction returned is the leg's fixed position_direction
    (set per directive — typically +1 for the "long-spread leg" and -1
    for the "short-spread leg" of the pair, or inverted for the
    opposite-direction variant of the same pair).

    Required input columns on leg.df (joined by basket_data_loader):
      intra_z          (float) — 15m rolling z-score of the spread
      qualified_daily  (bool)  — daily cointegration regime

    Internal state:
      _prev_z — last observed intra_z value; needed to detect crossings.
                Reset to None on NaN or column-read failure so a fresh
                pair of consecutive valid bars is required for the next
                crossing detection (safe-side default).

    NOT fast-path eligible — requires per-bar evaluation to watch the
    crossing.

    Compared to SpreadCrossLegStrategy, this is simpler:
      * No two-stage arming (no whipsaw delay) — the daily-cointegration
        filter already rejects structural noise
      * No shared armed_state between legs — both legs read identical
        joined columns (intra_z, qualified_daily) so they fire
        deterministically on the same bar
    """

    timeframe = "15m"

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {
        "execution_rules": {
            "entry_logic":           {"type": "cointegration_zscore_signal"},
            "entry_when_flat_only":  True,
            "exit_logic":            {"type": "basket_rule_owned"},
            "pyramiding":            False,
            "reset_on_exit":         False,
            "stop_loss":             {"type": "atr_multiple", "atr_multiplier": 100000.0},
            "take_profit":           {"enabled": False},
            "trailing_stop":         {"enabled": False},
        },
        "indicators":                ["indicators.stats.cointegration_state"],
        "order_placement":           {"type": "market", "execution_timing": "next_bar_open"},
        "position_management":       {"lots": 0.10},
        "signal_version":            1,
        "signature_version":         1,
        "trade_management":          {"direction": "basket_leg", "reentry": {"allowed": True}, "session_reset": "none"},
        "version":                   1,
    }
    # --- STRATEGY SIGNATURE END ---

    def __init__(
        self,
        symbol: str,
        position_direction: int,
        watch_direction: int = 0,
        entry_z: float = 2.0,
        intra_z_column: str = "intra_z",
        qualified_column: str = "qualified_daily",
    ) -> None:
        if position_direction not in (+1, -1):
            raise ValueError(
                f"CointMeanRevLegStrategy: position_direction must be +1 or -1, "
                f"got {position_direction!r}."
            )
        if watch_direction not in (+1, -1, 0):
            raise ValueError(
                f"CointMeanRevLegStrategy: watch_direction must be +1, -1, or 0, "
                f"got {watch_direction!r}."
            )
        if entry_z <= 0:
            raise ValueError(
                f"CointMeanRevLegStrategy: entry_z must be > 0, "
                f"got {entry_z!r}."
            )
        self.symbol = symbol
        self.position_direction = position_direction
        self.watch_direction = watch_direction
        self.entry_z = entry_z
        self.intra_z_column = intra_z_column
        self.qualified_column = qualified_column
        watch_tag = ("bi" if watch_direction == 0
                     else ("+" if watch_direction > 0 else "-"))
        self.name = (
            f"coint_meanrev_{symbol}"
            f"_pos{'+' if position_direction > 0 else '-'}"
            f"_watch{watch_tag}"
        )
        # Last seen intra_z. None = no prior bar (or last was NaN).
        self._prev_z: float | None = None

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Verify required columns are present (joined upstream)."""
        missing = [c for c in (self.intra_z_column, self.qualified_column)
                   if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"CointMeanRevLegStrategy({self.symbol}): leg.df missing "
                f"required columns {missing}. Expected upstream join from "
                f"basket_data_loader + indicators.stats.cointegration_state."
            )
        return df

    def check_entry(self, ctx) -> dict[str, Any] | None:
        # Read current bar's intra_z with safe fallback.
        intra_z_raw = ctx.get(self.intra_z_column, float("nan"))
        try:
            intra_z = float(intra_z_raw) if intra_z_raw is not None else float("nan")
        except (TypeError, ValueError):
            intra_z = float("nan")

        # NaN intra_z (data gap / pre-warmup) → reset prev_z, abstain
        if pd.isna(intra_z):
            self._prev_z = None
            return None

        # Capture prev BEFORE updating self._prev_z
        prev_z = self._prev_z
        self._prev_z = intra_z

        # Daily qualification gate — fast-fail
        try:
            qualified = bool(ctx.get(self.qualified_column, False))
        except (TypeError, ValueError):
            qualified = False
        if not qualified:
            return None

        # Need a previous valid z to detect a crossing
        if prev_z is None or pd.isna(prev_z):
            return None

        # Crossing condition: |z| >= entry_z AND |prev_z| < entry_z
        abs_z = abs(intra_z)
        abs_prev = abs(prev_z)
        if not (abs_z >= self.entry_z and abs_prev < self.entry_z):
            return None

        # Direction filter
        if self.watch_direction != 0:
            z_sign = +1 if intra_z >= 0 else -1
            if z_sign != self.watch_direction:
                return None

        return {"signal": int(self.position_direction)}

    def check_exit(self, ctx) -> bool:
        """Never close via signal. Recycle rule handles all exits."""
        return False
