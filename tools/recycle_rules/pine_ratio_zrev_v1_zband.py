"""pine_ratio_zrev_v1_zband.py — Band-exit variant of pine_ratio_zrev_v1.

A/B test variant of PineRatioZRevRule (2026-06-01). Sibling to
pine_ratio_zrev_v1_zcross. ONLY difference from baseline:

  Baseline exit: LIQUIDATE on opposite-direction cross of |z_active| >= z_entry
                 (always-in-market reversal — exit IS the next entry signal).
  Variant exit:  LIQUIDATE on first bar where |z_active| <= z_exit (default 1.0)
                 — the spread has reverted to the equilibrium band. Strategy
                 goes FLAT after exit; the next |z_active| >= z_entry cross
                 opens a fresh cycle (no same-bar re-proposal).

The band-exit semantic is the equilibrium-band wording flagged in
pine_ratio_zrev_v1_zcross.py's NAMING WARNING — built here as a SEPARATE rule
per that file's explicit instruction. It is NOT a parameterization of the
zero-cross variant.

Entries, filters, hedge lock, sizing, and the warmup contract are inherited
unchanged. The `always_in_market` param is inherited and ignored — the new
exit no longer doubles as a directional reentry signal, so the strategy is
flat between cycles regardless of the flag.

Hypothesis under test: banking partial mean-reversion at the equilibrium band
captures the bulk of the move while exiting before the full reversal arc; this
typically reduces both drawdown (no extreme-against-extreme tail) and per-cycle
upside (no chase to opposite extreme), at the cost of fewer signal-per-bar
opportunities than ZCRS (which fires at sign-flip).

Registered as `pine_ratio_zrev_v1_zband@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version =>
distinct STRATEGY_SIGNATURE hash => no possible ledger/MPS/cointegration_sheet
collision with the baseline or zcross corpus.

Recycle event tag emitted on exit: `LIQUIDATE_BAND_REVERT` (distinct from
baseline's `REVERSAL` and ZCRS's `EQUILIBRIUM`).

Implementation note: subclass extends `_attach_z_r` to additionally compute
the `pine_zrev_zband_exit` boolean column from |z_active| <= z_exit. The
`apply()` override is a near-copy of the ZCRS flow with the band-exit check
replacing the zero-cross exit check.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.cointegration_meanrev_v1_2 import _leg_pnl_usd_universal
from tools.recycle_rules.h2_recycle_v3 import _build_ref_closes
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule


_RULE_NAME = "pine_ratio_zrev_v1_zband"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZBand(PineRatioZRevRule):
    """Pine z_r reversal — equilibrium-band exit variant (A/B test of v1)."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Band-exit threshold. Liquidate when |z_active| <= z_exit. Must be > 0
    # and strictly less than z_entry (else the cycle could exit at the same
    # bar it enters, defeating the mechanic).
    z_exit: float = 1.0

    zband_column: str = "pine_zrev_zband_exit"

    _n_band_exits: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.z_exit <= 0:
            raise ValueError(
                f"PineRatioZRevRuleZBand.z_exit must be > 0, got {self.z_exit!r}."
            )
        if self.z_exit >= self.z_entry:
            raise ValueError(
                f"PineRatioZRevRuleZBand.z_exit ({self.z_exit}) must be < "
                f"z_entry ({self.z_entry}); else exit could fire at entry bar."
            )

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit parent's attach + compute the variant's band-exit column.

        Exit condition: |z_active| <= z_exit. z_active is `pine_zrev_z_centered`
        in centered mode and `pine_zrev_z` in absolute mode (same column the
        baseline cross detection uses)."""
        super()._attach_z_r(legs)

        if self.entry_mode == "centered":
            z_col = "pine_zrev_z_centered"
        else:
            z_col = "pine_zrev_z"

        z = legs[0].df[z_col]
        zband = (z.abs() <= self.z_exit) & (~pd.isna(z))
        zband_series = pd.Series(zband.values, index=z.index)

        for leg in legs:
            leg.df[self.zband_column] = zband_series.reindex(
                leg.df.index, fill_value=False
            )

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Variant flow: same setup as baseline, BAND_EXIT replaces REVERSAL.

        Differences from PineRatioZRevRule.apply:
          (1) First-bar setup calls THIS class's _attach_z_r (which also
              attaches `pine_zrev_zband_exit` via super()).
          (2) The OPEN-basket exit check reads `pine_zrev_zband_exit` instead
              of `signal_value != self._basket_direction`. Tag = LIQUIDATE_BAND_REVERT.
          (3) `not band_exit` guard on the FLAT propose path — same-bar exit
              does NOT re-propose. The next +/- z_entry cross will fire the
              next cycle through the unchanged entry path.
        """
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts
            if not self._z_r_attached:
                self._attach_z_r(legs)
                self._z_r_attached = True
            if self.shared_armed_state is None:
                from tools.recycle_strategies import PineZRevArmedState
                for leg in legs:
                    armed = getattr(leg.strategy, "armed_state", None)
                    if isinstance(armed, PineZRevArmedState):
                        self.shared_armed_state = armed
                        break

        bar_closes: dict[str, float] = {}
        try:
            for leg in legs:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
        except (KeyError, ValueError):
            return

        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (
                _leg_pnl_usd_universal(leg, bar_closes[leg.symbol], ref_closes)
                if leg.state.in_pos else 0.0
            )
            for leg in legs
        }
        floating_total = sum(leg_float.values())
        all_open = all(leg.state.in_pos for leg in legs)

        try:
            signal_value = int(legs[0].df.loc[bar_ts, self.signal_column])
        except (KeyError, ValueError, TypeError):
            signal_value = 0

        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            state = self.shared_armed_state
            if state is not None and state.proposed_direction != 0:
                self._basket_direction = state.proposed_direction
            else:
                self._basket_direction = int(legs[0].state.direction or 0)
            entry_lots = {leg.symbol: leg.lot for leg in legs}
            self._entry_lots = entry_lots
            self._snapshot_cycle_entry_ctx(legs, bar_ts, bar_closes)
            self.recycle_events.append({
                "bar_index":     i,
                "bar_ts":        bar_ts,
                "action":        "BASKET_OPEN",
                "direction":     self._basket_direction,
                "entry_r_bar":   self._entry_r_bar,
                "entry_lots":    entry_lots,
                "leg_directions": {l.symbol: l.effective_direction for l in legs},
            })
            if state is not None:
                state.reset()

        self._update_cycle_excursions(legs, bar_ts, bar_closes)

        band_exit = False
        # Guard (2026-06-01 fix): the band-exit check must not fire on the
        # BASKET_OPEN bar itself. The 2-bar entry protocol means z has often
        # drifted from its trigger level (>= z_entry) back into [-z_exit, +z_exit]
        # by the time the basket fills — without this guard, the cycle would
        # exit on its own entry bar with zero held exposure. ZCRS gets this
        # protection for free via its sign-flip semantics (z[t-1] is on the same
        # side of zero as the entry trigger). ZBAND requires an explicit
        # min-hold-1-bar invariant.
        if (self._basket_open
                and self._entry_bar_idx is not None
                and i > self._entry_bar_idx):
            try:
                zband_now = bool(legs[0].df.loc[bar_ts, self.zband_column])
            except (KeyError, ValueError, TypeError):
                zband_now = False
            if zband_now:
                self._n_band_exits += 1
                # Parent _liquidate prepends "LIQUIDATE_" to the reason when
                # building skip_reason; pass "BAND_REVERT" to get the clean
                # tag "LIQUIDATE_BAND_REVERT".
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="BAND_REVERT",
                    extra={"direction": self._basket_direction,
                           "z_exit_threshold": self.z_exit},
                )
                # Defensive (2026-06-01): clear any in-flight proposal that may
                # have been set earlier this bar (by leg.check_entry's
                # PROPOSAL phase) — without this, stale pending_trigger_ts blocks
                # _maybe_propose on subsequent bars and the strategy fires
                # exactly one cycle then deadlocks. ZCRS doesn't need this
                # because zero-cross bars cannot coincide with +/-z_entry crosses
                # by construction; band-exit bars carry no such guarantee.
                if self.shared_armed_state is not None:
                    self.shared_armed_state.reset()
                band_exit = True
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        if not all_open and not band_exit:
            if signal_value in (+1, -1):
                self._maybe_propose(signal_value, bar_ts)
            self._maybe_approve(legs, i, bar_ts)
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        if band_exit:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="BAND_EXIT_BAR",
            )
            return

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )
