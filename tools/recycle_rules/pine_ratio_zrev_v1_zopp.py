"""pine_ratio_zrev_v1_zopp.py — Opposite-band (overshoot) exit variant of
pine_ratio_zrev_v1.

Exit-only A/B variant (2026-06-04, operator-directed). ONLY the exit differs;
entries remain EXCLUSIVELY at |z_active| >= z_entry (+/-2).

  Baseline exit: LIQUIDATE+REVERSE on the opposite-direction |z| >= z_entry
                 cross (always-in-market; reverse at the opposite +/-2 extreme).
  ZBAND   exit:  LIQUIDATE (flat) on |z| <= z_exit (SAME side; -2 -> -1, early).
  ZOPP    exit:  LIQUIDATE (flat) when z crosses to the OPPOSITE side beyond
                 +/- z_exit (entered at -2 -> exit at +1; entered at +2 ->
                 exit at -1). A LATE exit: rides the full reversion PLUS the
                 overshoot to the opposite +/- z_exit, then goes FLAT. The next
                 |z| >= z_entry (+/-2) cross opens a fresh cycle.

TRUE exit-only modification: entries, sizing (incl. GP granular), hedge lock,
recycle, and warmup are inherited unchanged from PineRatioZRevRule.
`always_in_market` is inherited and IGNORED (flat between cycles). Recycle event
tag emitted on exit: LIQUIDATE_OPP_REVERT.

Direction handling: the exit is direction-aware (which opposite side depends on
the entry extreme). The entry side is captured as sign(z_active) at the
BASKET_OPEN bar — z has not crossed zero from its +/-z_entry trigger in the
2-bar entry window, so the open-bar sign is the entry side. Exit fires when
  z_active * (-entry_z_sign) >= z_exit
i.e. z has reached the opposite +/- z_exit. A min-hold-1-bar guard prevents a
same-bar exit (mirrors ZBAND's guard).

Registered as pine_ratio_zrev_v1_zopp@1. Distinct name+version => distinct
STRATEGY_SIGNATURE => no ledger/MPS/cointegration_sheet collision with the
baseline / zcross / zband corpus.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.cointegration_meanrev_v1_2 import _leg_pnl_usd_universal
from tools.recycle_rules.h2_recycle_v3 import _build_ref_closes
from tools.recycle_rules.pine_ratio_zrev_v1 import PineRatioZRevRule


_RULE_NAME = "pine_ratio_zrev_v1_zopp"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZOpp(PineRatioZRevRule):
    """Pine z_r reversal — opposite-band (overshoot) flat-exit variant."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Opposite-band exit threshold: liquidate FLAT when z reaches the opposite
    # side beyond +/- z_exit (default 1.0). Must be > 0 and strictly < z_entry.
    z_exit: float = 1.0

    # Per-cycle: sign of z at the entry (basket-open) bar; 0 when flat.
    _entry_z_sign: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.z_exit <= 0:
            raise ValueError(
                f"PineRatioZRevRuleZOpp.z_exit must be > 0, got {self.z_exit!r}."
            )
        if self.z_exit >= self.z_entry:
            raise ValueError(
                f"PineRatioZRevRuleZOpp.z_exit ({self.z_exit}) must be < "
                f"z_entry ({self.z_entry}); else exit could fire at entry bar."
            )

    def _z_col(self) -> str:
        return "pine_zrev_z_centered" if self.entry_mode == "centered" else "pine_zrev_z"

    def _opp_exit_fires(self, z_now: float) -> bool:
        """True when z has crossed to the OPPOSITE side of the entry beyond
        +/- z_exit. Entered low (entry_z_sign < 0) -> fires at z >= +z_exit;
        entered high (entry_z_sign > 0) -> fires at z <= -z_exit. False when
        flat (entry_z_sign == 0). This is the ONLY behavioural difference from
        the same-side zband exit; isolated here for direct unit testing."""
        if self._entry_z_sign == 0:
            return False
        return (z_now * (-self._entry_z_sign)) >= self.z_exit

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Variant flow: same setup as baseline; OPP_REVERT (opposite-band flat
        exit) replaces the baseline REVERSAL. Entries unchanged."""
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts
            if not self._z_r_attached:
                self._attach_z_r(legs)   # parent's: computes the z column
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
            # Capture entry side = sign(z) at the open bar (still on the +/-2
            # trigger side; has not crossed zero in the 2-bar entry window).
            try:
                z_open = float(legs[0].df.loc[bar_ts, self._z_col()])
                self._entry_z_sign = 1 if z_open > 0 else -1
            except (KeyError, ValueError, TypeError):
                self._entry_z_sign = 0
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

        opp_exit = False
        # Min-hold-1-bar guard (mirrors ZBAND): never exit on the open bar.
        if (self._basket_open
                and self._entry_bar_idx is not None
                and i > self._entry_bar_idx
                and self._entry_z_sign != 0):
            try:
                z_now = float(legs[0].df.loc[bar_ts, self._z_col()])
                opp_exit = self._opp_exit_fires(z_now)
            except (KeyError, ValueError, TypeError):
                opp_exit = False
            if opp_exit:
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="OPP_REVERT",
                    extra={"direction": self._basket_direction,
                           "z_exit_threshold": self.z_exit,
                           "entry_z_sign": self._entry_z_sign},
                )
                if self.shared_armed_state is not None:
                    self.shared_armed_state.reset()
                self._entry_z_sign = 0
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        if not all_open and not opp_exit:
            if signal_value in (+1, -1):
                self._maybe_propose(signal_value, bar_ts)
            self._maybe_approve(legs, i, bar_ts)
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        if opp_exit:
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="OPP_EXIT_BAR",
            )
            return

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )
