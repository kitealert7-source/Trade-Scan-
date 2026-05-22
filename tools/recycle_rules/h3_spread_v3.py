"""h3_spread_v3.py -- H3_spread@3: extreme-z exit + ARMED-for-reentry.

Structural extension over @2 (2026-05-22). Adds two composable mechanics
designed to capture multi-leg trend continuation within a single macro
regime, addressing the failure mode where @2 cycles fully harvest into
CORE_HOLD and then surrender residual on a slow reverse-cross while a
NEW leg of the same regime starts running.

  Mechanic A -- EXTREME-Z EXIT
    When `cycle_dir * diff > extreme_z_threshold`, the cycle liquidates
    via a new exit reason `LIQUIDATE_EXTREME_Z`. The spread is over-
    extended in the cycle's direction; locking in residual before the
    inevitable mean-reversion is the profit-take semantic. Priority
    slot: TIME > ADVERSE > EXTREME_Z > REVERSE > HARVEST > TRAIL.
    Side-aware: extreme excursion AGAINST cycle_dir is left to
    ADVERSE_STOP -- the wrong-direction extreme is a losing leg, not
    a profit-take.

  Mechanic B -- RE-ENTRY (ARMED_FOR_REENTRY phase)
    After an EXTREME_Z exit (and ONLY that exit), the rule transitions
    to an ARMED_FOR_REENTRY phase rather than fully terminating. While
    armed:
      - Position is flat (lot=0); no PnL accrues
      - Watch the diff column for `0 < cycle_dir * diff < reentry_z_threshold`
        AND cross_side still aligned with cycle_dir
        AND htf_direction still aligned with cycle_dir (if macro_check on)
      - On match -> RE-ENTER (fresh cycle, pyramid stack restarts at 0,
        cycle_dir preserved, _reentries_this_regime += 1)
    Abort conditions (transition to terminal flat, await new cross_event):
      - cross_side flips (regime change detected)
      - htf_direction flips (macro change detected, if macro_check on)
      - `_reentries_this_regime` reaches `reentry_max_per_regime`

Both mechanics default OFF. With `extreme_z_threshold=None` and
`reentry_z_threshold=None`, this class is byte-equivalent to
H3SpreadV2Rule -- enforced by `test_h3_spread_v3_byte_equiv_to_v2`.

Why this rule
-------------
S16 result (2026-05-22): the unsmoothed cross_side_raw exit on @2 was
net-neutral on Net% vs S10 baseline. It cut adverse cycles (-24.5%) and
cycles ending at lower MFE in trade for cycles missing harvest territory
(-15.3% scale-to-core), a roughly 1:1 swap. The conclusion was that
"exit faster" alone cannot move the Net% needle on this strategy --
single-leg edge is already largely captured by @2's harvest mechanic.

The remaining edge lives in MULTI-LEG capture: within a macro regime
that lasts months, the spread oscillates around its long-run mean,
producing multiple distinct legs. @2 only captures ONE leg per
cross_event before sitting in CORE_HOLD waiting for the macro turn.
If we can profit-take at peak (mechanic A) and re-engage when the
spread normalizes (mechanic B), each cross_event spawns potentially
multiple harvest-then-take-profit cycles.

This is a probe, not a final architecture. Sweep extreme_z_threshold
+ reentry_z_threshold once mechanism is validated.

Reference
---------
SYSTEM_STATE manual block 2026-05-22 (this session). Plan + op-spec
documented in-conversation; preserved here via field comments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tools.recycle_rules.h3_spread_v2 import H3SpreadV2Rule


_RULE_NAME = "H3_spread"
_RULE_VERSION = 3


@dataclass
class H3SpreadV3Rule(H3SpreadV2Rule):
    """@3 = @2 + extreme-z exit + ARMED-for-reentry phase.

    Inherits ALL @2 mechanics (harvest, keep_core, bidirectional, macro
    filter, correlation filter wiring) and adds two composable mechanics
    that default off. With defaults, this class is byte-equivalent to
    H3SpreadV2Rule -- explicit regression test enforces this.
    """

    # --- V3 new params ---

    # Mechanic A: extreme-z exit threshold. When None (default), the
    # extreme-z exit branch never fires and behavior is identical to @2.
    # When set to a positive float, the cycle liquidates via
    # LIQUIDATE_EXTREME_Z when cycle_dir * diff > extreme_z_threshold.
    # The threshold is in the same units as the indicator's `diff` column
    # (SMA(z_a) - SMA(z_b)); 2.0 means "spread is 2 sigma-equivalents
    # above its smoothed long-run mean".
    extreme_z_threshold: Optional[float] = None

    # Mechanic B: re-entry threshold. When None (default), an EXTREME_Z
    # exit fully terminates the cycle (same as any other liquidation).
    # When set, after an EXTREME_Z exit the rule transitions to
    # ARMED_FOR_REENTRY and watches for `0 < cycle_dir * diff <
    # reentry_z_threshold` (spread has normalized back from the extreme
    # but is still on the cycle's side). Must be less than
    # extreme_z_threshold (enforced by validator) -- a re-entry threshold
    # >= extreme_z would immediately re-arm and re-exit in a loop.
    reentry_z_threshold: Optional[float] = None

    # Whether re-entry requires htf_direction to still align with
    # cycle_dir. Default True (macro coherence required). Only matters
    # when reentry_z_threshold is set.
    reentry_macro_check: bool = True

    # Whether re-entry requires cross_side to still align with cycle_dir.
    # Default True (regime not yet flipped). Only matters when
    # reentry_z_threshold is set. If False, re-entry can occur even
    # mid-cross -- not recommended; here for explicit composability.
    reentry_cross_check: bool = True

    # Safety cap on re-entries within a single regime (cross_event to
    # cross_event). Default 3. Prevents pathological loop on mean-
    # reverting chop where diff repeatedly bounces between extreme and
    # reentry thresholds.
    reentry_max_per_regime: int = 3

    # --- Name/version overrides ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- V3 internal state ---

    # True between an EXTREME_Z exit and either re-entry (-> back to
    # normal cycle state) or abort (-> fully flat, await new cross_event).
    _armed_for_reentry: bool = False

    # Telemetry counters (cumulative across cycles for the lifetime of
    # the rule instance; not reset per cycle).
    _n_extreme_z_exits: int = 0
    _n_reentries: int = 0

    # Per-regime re-entry counter. Increments on each re-entry; resets
    # when a non-EXTREME_Z liquidation fires (REVERSE / ADVERSE / TIME /
    # HARVEST_COMPLETE), because those end the regime / await a new
    # cross_event.
    _reentries_this_regime: int = 0

    def __post_init__(self) -> None:
        # Inherit @2 validation (and through it @1).
        super().__post_init__()

        # V3-specific validation.
        if self.extreme_z_threshold is not None:
            if not isinstance(self.extreme_z_threshold, (int, float)):
                raise ValueError(
                    f"H3SpreadV3Rule.extreme_z_threshold must be None or "
                    f"numeric; got {self.extreme_z_threshold!r}."
                )
            if self.extreme_z_threshold <= 0.0:
                raise ValueError(
                    f"H3SpreadV3Rule.extreme_z_threshold must be > 0; "
                    f"got {self.extreme_z_threshold!r}."
                )

        if self.reentry_z_threshold is not None:
            if self.extreme_z_threshold is None:
                raise ValueError(
                    "H3SpreadV3Rule.reentry_z_threshold requires "
                    "extreme_z_threshold to be set (re-entry has no "
                    "meaning without an extreme-z exit to re-enter from)."
                )
            if not isinstance(self.reentry_z_threshold, (int, float)):
                raise ValueError(
                    f"H3SpreadV3Rule.reentry_z_threshold must be None or "
                    f"numeric; got {self.reentry_z_threshold!r}."
                )
            if self.reentry_z_threshold <= 0.0:
                raise ValueError(
                    f"H3SpreadV3Rule.reentry_z_threshold must be > 0; "
                    f"got {self.reentry_z_threshold!r}."
                )
            if self.reentry_z_threshold >= self.extreme_z_threshold:
                raise ValueError(
                    f"H3SpreadV3Rule.reentry_z_threshold "
                    f"({self.reentry_z_threshold}) must be < "
                    f"extreme_z_threshold ({self.extreme_z_threshold}); "
                    f"otherwise re-entry would immediately re-arm and "
                    f"re-exit in a loop."
                )

        if not isinstance(self.reentry_macro_check, bool):
            raise ValueError(
                f"H3SpreadV3Rule.reentry_macro_check must be a bool; "
                f"got {self.reentry_macro_check!r}."
            )
        if not isinstance(self.reentry_cross_check, bool):
            raise ValueError(
                f"H3SpreadV3Rule.reentry_cross_check must be a bool; "
                f"got {self.reentry_cross_check!r}."
            )
        if (not isinstance(self.reentry_max_per_regime, int)
                or self.reentry_max_per_regime < 1):
            raise ValueError(
                f"H3SpreadV3Rule.reentry_max_per_regime must be a positive "
                f"int; got {self.reentry_max_per_regime!r}."
            )

    # ---- _liquidate override ---
    # @2 clears its own state flags (_in_harvest_phase, _in_hold_phase,
    # _hold_levels_consumed, _in_core_hold_phase, _cycle_direction).
    # @3 additionally clears the per-cycle re-entry state. The cumulative
    # telemetry counters (_n_extreme_z_exits, _n_reentries) are NOT reset.
    # The per-regime counter _reentries_this_regime is reset here for
    # NON-EXTREME-Z liquidations; B.3 will refine this to preserve the
    # counter across an EXTREME_Z exit so re-entries accumulate within
    # one regime.

    def _liquidate(self, legs, i, bar_ts, bar_closes, leg_float,
                   floating_total, reason: str) -> None:
        # Non-EXTREME_Z liquidations end the regime -- reset re-entry
        # state. EXTREME_Z liquidations may transition to ARMED in B.4;
        # for B.3 the cycle just terminates like any other reason (the
        # ARMED transition is gated on reentry_z_threshold being set,
        # which has no apply()-side logic yet -- coming in B.4).
        if reason != "EXTREME_Z":
            self._armed_for_reentry = False
            self._reentries_this_regime = 0
        super()._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                           floating_total, reason)

    # ---- Hook override: extreme-z take-profit exit -----------------------
    # Fires when extreme_z_threshold is set AND cycle_dir * diff exceeds
    # the threshold (the spread is over-extended in the cycle's direction).
    # Side-aware: wrong-direction extremes (e.g., LONG cycle with diff
    # deeply negative) are NOT triggers -- those are losing-leg scenarios
    # handled by ADVERSE_STOP. Priority slot per @2's call site:
    # TIME > ADVERSE > EXTREME_Z > TRAIL > REVERSE > HARVEST.

    def _check_extreme_z_exit_hook(
        self, legs, i, bar_ts, bar_closes, leg_float, floating_total,
    ) -> bool:
        if self.extreme_z_threshold is None:
            return False

        try:
            diff = float(legs[0].df.loc[bar_ts, "diff"])
        except (KeyError, ValueError, TypeError):
            return False

        # cycle_dir mirrors the reverse_cross check's dir resolution.
        cycle_dir = (
            self._cycle_direction if self.bidirectional
            else int(self.entry_direction)
        )

        # Side-aware extreme: trigger only when the spread is extended
        # IN the cycle's direction. Wrong-direction extremes are losing-
        # leg scenarios for ADVERSE_STOP, not profit-take candidates.
        if cycle_dir * diff > self.extreme_z_threshold:
            self._n_extreme_z_exits += 1
            self._liquidate(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total, reason="EXTREME_Z",
            )
            return True

        return False
