"""pine_ratio_zrev_v1_session_window.py — intraday UTC session-window overlay on the
zero-crossing exit variant.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-14). It is the ZCRS champion
(zero-crossing exit, granular_parity sizing) PLUS one behavioral change: an intraday
UTC session window.

  Champion (zcross):  enter on any +/- z_entry cross, hold until z zero-crosses,
                      re-enterable continuously (24h).
  Variant (session):  entries FILL only when the fill bar's UTC hour is in
                      [entry_open_hour, force_flat_hour); ALL open positions are
                      force-liquidated to flat the moment a bar's UTC hour reaches
                      force_flat_hour (daily "go flat at NY close"), and stay flat
                      until the next day's entry_open_hour.

Hypothesis: trading only the Asian-open -> NY-close window (00:00 -> 21:00 UTC by
default) and going flat overnight reduces overnight tail risk (the v1.5.10 corpus
had a blow-up) at the cost of cutting not-yet-reverted MR cycles short. Compared
matched-pairs vs the GP_ZCRS_Z25 v1.5.10 baseline cohort (a single moving variable:
the session overlay).

Bar timestamps are UTC-naive (OctaFx RESEARCH feed). DST is NOT modelled -- the
force-flat hour is a fixed UTC hour across the whole window (NY close = 21:00 UTC,
the codebase's session_clock_universal convention; in US summer the true close is
20:00 UTC -- a known, documented simplification).

DESIGN (no apply() override) -- the overlay fits two existing hook slots, so the
250-line zcross apply() is inherited UNCHANGED (less fragile than the copy-apply
that the deeper-FSM variants like _zstop needed):

  ENTRY gate  -> `_maybe_approve` (the SOLE entry-control point: the leg's
                 check_entry sets the proposal directly, so the rule's only
                 effective suppression is the approval gate -- same place the
                 _regime_broken / _z_stop_latch gates live). Approval is refused
                 unless the FILL bar (next aligned bar) hour is in
                 [entry_open_hour, force_flat_hour). Gating the FILL bar -- not this
                 signal bar -- means a cycle never opens at/after force_flat_hour
                 (a signal at 20:45 would otherwise fill at 21:00 and be
                 force-flatted the same bar: a pure wash + double spread).
  FORCE-FLAT  -> `_maybe_break_exit` (the forced-exit slot: called after the
                 open-transition and BEFORE all z-exits in the zcross apply(), and
                 returning True makes apply() return immediately). The
                 cointegration-break keeps precedence (live-safety, latches);
                 otherwise an OPEN basket at bar_ts.hour >= force_flat_hour is
                 liquidated to flat (tag LIQUIDATE_SESSION_FLAT). It does NOT latch
                 -- the next day's in-window cross opens a fresh cycle. Clears any
                 pending next_open zcross exit and resets the armed state so no
                 half-armed entry survives into the flat window.

PARITY PROPERTY (clean-toggle gate): with `entry_open_hour=0, force_flat_hour=24`
both gates are inert (every hour is in [0, 24); no hour is >= 24), so the rule is
byte-identical to `PineRatioZRevRuleZCross` -- the parity test asserts this
(mirrors pine_ratio_zrev_v1_zstop's z_stop=1e9 parity).

Registered as `pine_ratio_zrev_v1_session_window@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version => distinct
STRATEGY_SIGNATURE hash => no ledger / MPS / cointegration_sheet collision with the
zcross champion corpus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_session_window"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleSessionWindow(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + intraday UTC session window."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Intraday session window (UTC hours, directive-driven). Entries FILL only when
    # the fill bar's hour is in [entry_open_hour, force_flat_hour); all open
    # positions force-flat at force_flat_hour. Defaults = Asian open (0) -> NY
    # close (21). entry_open_hour=0, force_flat_hour=24 recovers exact champion
    # behavior (parity gate).
    entry_open_hour: int = 0
    force_flat_hour: int = 21

    _n_session_flats: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (isinstance(self.entry_open_hour, int) and not isinstance(self.entry_open_hour, bool)
                and isinstance(self.force_flat_hour, int) and not isinstance(self.force_flat_hour, bool)):
            raise ValueError(
                f"PineRatioZRevRuleSessionWindow: entry_open_hour / force_flat_hour "
                f"must be ints (UTC hours), got {self.entry_open_hour!r} / "
                f"{self.force_flat_hour!r}."
            )
        if not (0 <= self.entry_open_hour < self.force_flat_hour <= 24):
            raise ValueError(
                f"PineRatioZRevRuleSessionWindow requires "
                f"0 <= entry_open_hour < force_flat_hour <= 24; got "
                f"entry_open_hour={self.entry_open_hour!r}, "
                f"force_flat_hour={self.force_flat_hour!r}."
            )

    # ---- helpers ---------------------------------------------------------

    def _next_aligned_bar(self, legs: list[BasketLeg], bar_ts: pd.Timestamp,
                          ) -> Optional[pd.Timestamp]:
        """First bar strictly after `bar_ts` present in EVERY leg's index (the fill
        bar for a proposal made at `bar_ts`), or None at end-of-data. Same
        cross-region intersection logic the inherited _maybe_approve uses to resolve
        approved_fire_ts."""
        after = legs[0].df.index[legs[0].df.index > bar_ts]
        for other in legs[1:]:
            after = after.intersection(other.df.index[other.df.index > bar_ts])
        return after[0] if len(after) > 0 else None

    def _in_entry_window(self, hour: int) -> bool:
        return self.entry_open_hour <= hour < self.force_flat_hour

    # ---- entry gate (sole effective entry-control point) -----------------

    def _maybe_approve(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Refuse approval unless the FILL bar (next aligned bar) lands inside the
        entry window. Gating the fill bar -- not this signal bar -- means a cycle
        never opens at/after force_flat_hour (which would be force-flatted the same
        bar). On block, clear the leg's pending proposal so it cannot linger to the
        next bar. In-window -> defer to super (which still honors the _regime_broken
        gate)."""
        state = self.shared_armed_state
        if state is not None and state.pending_trigger_ts == bar_ts:
            fill_bar = self._next_aligned_bar(legs, bar_ts)
            if fill_bar is None or not self._in_entry_window(int(fill_bar.hour)):
                state.reset()
                return
        super()._maybe_approve(legs, i, bar_ts)

    # ---- forced exit: cointegration-break first, then session force-flat -

    def _maybe_break_exit(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float,
    ) -> bool:
        """Forced-exit hook: the cointegration-break fires first (live-safety,
        latches, keeps precedence), then the daily session force-flat. Returns True
        (=> the caller `return`s immediately) if EITHER fires.

        Session force-flat: an OPEN basket at bar_ts.hour >= force_flat_hour is
        liquidated to flat (tag LIQUIDATE_SESSION_FLAT). It does NOT latch -- the
        next day's in-window cross opens a fresh cycle. Clears any pending next_open
        zcross exit and resets the armed state so no half-armed entry survives into
        the flat window. After the liquidation _basket_open is False, so this is a
        no-op on the remaining flat-window bars (e.g. 21:15..23:45)."""
        if super()._maybe_break_exit(legs, i, bar_ts, bar_closes, leg_float, floating_total):
            return True
        if self._basket_open and int(bar_ts.hour) >= self.force_flat_hour:
            self._n_session_flats += 1
            self._liquidate(
                legs, i, bar_ts, bar_closes, leg_float, floating_total,
                reason="SESSION_FLAT",
                extra={"direction": self._basket_direction,
                       "force_flat_hour": self.force_flat_hour},
            )
            self._pending_exit = False
            if self.shared_armed_state is not None:
                self.shared_armed_state.reset()
            return True
        return False
