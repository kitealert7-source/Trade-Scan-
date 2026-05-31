"""pine_ratio_zrev_v1_zcross.py — Zero-crossing exit variant of pine_ratio_zrev_v1.

NAMING WARNING (operator clarification 2026-05-31):
  This rule implements ZERO-CROSSING SIGN-CHANGE exit. It does NOT implement
  a |z| <= 0.25 equilibrium-band exit. The original spec contained BOTH
  wordings — the operator selected zero-cross. If a future variant of the
  band-exit concept is needed, build it as a separate rule (e.g.
  pine_ratio_zrev_v1_zband), do NOT parameterize this one with a |z| <= theta
  threshold. See [[project_pine_zrev_zcross_exit_variant]] in auto-memory.

A/B test variant of PineRatioZRevRule (2026-05-31). ONLY difference from
baseline:

  Baseline exit: LIQUIDATE on opposite-direction cross of |z_active| >= z_entry
                 (always-in-market reversal — exit IS the next entry signal).
  Variant exit:  LIQUIDATE on first zero-crossing of z_active (sign change
                 between consecutive 15m bars). Strategy goes FLAT after
                 exit; the next +/- z_entry cross opens a fresh cycle (no
                 same-bar re-proposal).

Concretely:
  - LONG cycle (entered at z<-z_entry) exits at first bar where sign(z[t])
    != sign(z[t-1]) — i.e. z crosses up through zero.
  - SHORT cycle (entered at z>+z_entry) exits at first bar where sign flips
    the other way — z crosses down through zero.

Entries, filters, hedge lock, sizing, and the warmup contract are inherited
unchanged. The `always_in_market` param is inherited and ignored — the new
exit no longer doubles as a directional reentry signal, so the strategy is
flat between cycles regardless of the flag.

Hypothesis under test: banking partial mean-reversion at equilibrium caps
drawdown vs holding for the full extreme-to-extreme swing (the v1.2
retirement risk pattern). Expected behavioral deltas vs baseline:
  - More cycles per episode (exit-at-zero opens room for next +/-2 sigma entry)
  - Smaller per-cycle PnL magnitudes (banks reversion, doesn't chase the
    extreme)
  - Tighter drawdown distribution (no extreme-against-extreme tail)

Registered as `pine_ratio_zrev_v1_zcross@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version =>
distinct STRATEGY_SIGNATURE hash => no possible ledger/MPS/cointegration_sheet
collision with the baseline corpus.

Recycle event tag emitted on exit: `LIQUIDATE_EQUILIBRIUM` (distinct from
baseline's `REVERSAL`).

Implementation note: subclass extends `_attach_z_r` to additionally compute
the `pine_zrev_zcross_exit` boolean column from sign(z_active[t]) !=
sign(z_active[t-1]). The `apply()` override is a near-copy of the baseline
flow with the REVERSAL check replaced by the EQUILIBRIUM_EXIT check, plus
a `not equilibrium_exit` guard on the FLAT-state propose path so the same
bar that exited cannot also re-propose.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.cointegration_meanrev_v1_2 import _leg_pnl_usd_universal
from tools.recycle_rules.h2_recycle_v3 import _build_ref_closes
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule


_RULE_NAME = "pine_ratio_zrev_v1_zcross"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCross(PineRatioZRevRule):
    """Pine z_r reversal — zero-crossing exit variant (A/B test of v1)."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    zcross_column: str = "pine_zrev_zcross_exit"

    _n_equilibrium_exits: int = 0

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit parent's attach + compute the variant's sign-change column.

        The exit signal is sign(z_active[t]) != sign(z_active[t-1]) where
        z_active is `pine_zrev_z_centered` in centered mode and `pine_zrev_z`
        in absolute mode (same column the baseline cross detection uses).
        """
        super()._attach_z_r(legs)

        if self.entry_mode == "centered":
            z_col = "pine_zrev_z_centered"
        else:
            z_col = "pine_zrev_z"

        z = legs[0].df[z_col]
        prev_z = z.shift(1)

        sign_now = np.sign(z.values)
        sign_prev = np.sign(prev_z.values)
        valid = ~(pd.isna(z) | pd.isna(prev_z))
        zcross = (sign_now != sign_prev) & valid
        zcross_series = pd.Series(zcross, index=z.index)

        for leg in legs:
            leg.df[self.zcross_column] = zcross_series.reindex(
                leg.df.index, fill_value=False
            )

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Variant flow: same setup as baseline, EQUILIBRIUM_EXIT replaces REVERSAL.

        Differences from PineRatioZRevRule.apply:
          (1) First-bar setup calls THIS class's _attach_z_r (which also attaches
              `pine_zrev_zcross_exit` via super()).
          (2) The OPEN-basket exit check reads `pine_zrev_zcross_exit` instead
              of `signal_value != self._basket_direction`. Tag = LIQUIDATE_EQUILIBRIUM.
          (3) `not equilibrium_exit` guard on the FLAT propose path — same-bar
              exit does NOT re-propose. The next +/- z_entry cross will fire
              the next cycle through the unchanged entry path.
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
            # Tradelevel enrichment: inherited from baseline rule.
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

        # Per-bar excursion tracking for the open cycle (no-op if flat).
        self._update_cycle_excursions(legs, bar_ts, bar_closes)

        equilibrium_exit = False
        if self._basket_open:
            try:
                zcross_now = bool(legs[0].df.loc[bar_ts, self.zcross_column])
            except (KeyError, ValueError, TypeError):
                zcross_now = False
            if zcross_now:
                self._n_equilibrium_exits += 1
                # NOTE: parent _liquidate prepends "LIQUIDATE_" to the reason
                # when building skip_reason, so pass "EQUILIBRIUM" to get the
                # clean tag "LIQUIDATE_EQUILIBRIUM" (matches canonical_metrics).
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction},
                )
                equilibrium_exit = True
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        if not all_open and not equilibrium_exit:
            if signal_value in (+1, -1):
                self._maybe_propose(signal_value, bar_ts)
            self._maybe_approve(legs, i, bar_ts)
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        if equilibrium_exit:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="EQUILIBRIUM_EXIT_BAR",
            )
            return

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )
