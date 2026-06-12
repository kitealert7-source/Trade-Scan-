"""pine_ratio_zrev_v1_zstop.py — hard z-stop overlay on the zero-crossing exit variant.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-11). It is the ZCRS champion
(zero-crossing exit) PLUS one thing: a hard stop when the spread blows out.

  Champion (zcross): hold until z zero-crosses (mean-reverts through 0), exit at
                     next_open. Always re-enterable on the next +/- z_entry cross.
  Variant (zstop):   ALSO exit (next_open) the moment |z_active| >= z_stop -- the
                     reversion bet has gone materially against us. After such a stop
                     the strategy LATCHES: no new entry is approved until a zero-cross
                     (sign change of z) confirms the spread has mean-reverted. The
                     next +/- z_entry cross after the reset opens a fresh cycle.

Rationale: the zcross exit banks reversion at equilibrium but has no floor on an
adverse excursion -- a pair that diverges from +2 to +6 sigma is held the whole way.
The z-stop caps that tail; the latch prevents immediately re-entering the still-diverged
spread (re-engage only after it has actually crossed back through zero).

FSM (isomorphic to the cointegration-break latch in pine_ratio_zrev_v1):
  SET    : a |z| >= z_stop bar flags a deferred (next_open) stop; the M+1-open
           liquidation sets `_z_stop_latch = True`.   (tag: LIQUIDATE_ZSTOP)
  RESET  : while latched, a zero-cross (the inherited `pine_zrev_zcross_exit` column)
           clears `_z_stop_latch`.
  GATE   : `_maybe_approve` refuses to approve any entry while `_z_stop_latch` is set
           (mirrors the `_regime_broken` gate -- the sole entry-control point).

Exit precedence (within apply): cointegration-break > deferred z-stop > deferred
zcross > hard time-stop > z-stop trigger > zcross trigger > EOF-finalize. A break is a
safety override that clears BOTH pending flags. The z-stop trigger pre-empts the zcross
trigger (a |z|>=z_stop bar is far from zero, so no zcross fires there anyway).

PARITY PROPERTY (the clean-toggle gate): when `|z_active|` never reaches `z_stop`,
`_pending_zstop` is never set, every z-stop branch is inert, and the rule is
byte-identical to `PineRatioZRevRuleZCross`. Default `z_stop` is finite (4.0); set it
to a value the data never reaches (e.g. 1e9) to recover exact champion behavior --
that is what the parity test asserts.

Registered as `pine_ratio_zrev_v1_zstop@1` in `governance/recycle_rules/registry.yaml`.
Distinct rule name + version => distinct STRATEGY_SIGNATURE hash => no ledger / MPS /
cointegration_sheet collision with the zcross champion corpus.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.h2_recycle_v3 import _build_ref_closes
from tools.recycle_rules.cointegration_meanrev_v1_2 import _leg_pnl_usd_universal
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zstop"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZStop(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + hard z-stop with re-entry latch."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Hard stop: liquidate (next_open) when |z_active| >= z_stop, then latch.
    z_stop: float = 4.0

    # FSM state.
    _z_stop_latch: bool = False   # blocks entry until a zero-cross resets it
    _pending_zstop: bool = False  # deferred (next_open) stop flagged on prior bar
    _n_zstop_exits: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.z_stop <= 0:
            raise ValueError(
                f"PineRatioZRevRuleZStop.z_stop must be > 0, got {self.z_stop!r}."
            )
        # A z_stop at or below the entry threshold would stop out at (or before)
        # entry — almost certainly a misconfiguration; refuse it loudly.
        if self.z_stop <= self.z_entry:
            raise ValueError(
                f"PineRatioZRevRuleZStop.z_stop ({self.z_stop!r}) must be > z_entry "
                f"({self.z_entry!r}); a stop at/below entry stops out immediately."
            )

    def _maybe_approve(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Entry gate: refuse approval while the z-stop latch is set (mirrors the
        `_regime_broken` gate — the rule's sole entry-control point). The leg's
        check_entry sets the proposal directly, so clearing it here is the only
        effective suppression. No-op unless the latch is set; otherwise delegates
        to the inherited approval (which still honors the `_regime_broken` gate)."""
        state = self.shared_armed_state
        if self._z_stop_latch and state is not None and state.pending_trigger_ts == bar_ts:
            state.reset()
            return
        super()._maybe_approve(legs, i, bar_ts)

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Zcross flow + the z-stop overlay. A near-copy of
        `PineRatioZRevRuleZCross.apply` with the z-stop FSM inserted at the points
        documented in the module header. Inert (byte-identical to zcross) on any bar
        where `|z_active| < z_stop` and the latch is clear."""
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

        _z_col = "pine_zrev_z_centered" if self.entry_mode == "centered" else "pine_zrev_z"
        try:
            z_now = float(legs[0].df.loc[bar_ts, _z_col])
        except (KeyError, ValueError, TypeError):
            z_now = float("nan")

        # Zero-cross signal (computed once): drives both the latch RESET and the
        # inherited zcross exit trigger below.
        try:
            zcross_now = bool(legs[0].df.loc[bar_ts, self.zcross_column])
        except (KeyError, ValueError, TypeError):
            zcross_now = False

        # LATCH RESET: a zero-cross clears the z-stop latch (re-entry re-enabled),
        # mirroring the cointegration-break latch's re-cointegration reset.
        if self._z_stop_latch and zcross_now:
            self._z_stop_latch = False

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
            _trigger_z = getattr(self, "_pending_trigger_z", z_now)
            self._cycle_entry_z = _trigger_z
            self._cycle_entry_dir = self._basket_direction
            self._cycle_z_lo = z_now
            self._cycle_z_hi = z_now
            self._snapshot_cycle_entry_ctx(legs, bar_ts, bar_closes)
            self.recycle_events.append({
                "bar_index":     i,
                "bar_ts":        bar_ts,
                "action":        "BASKET_OPEN",
                "direction":     self._basket_direction,
                "entry_r_bar":   self._entry_r_bar,
                "entry_lots":    entry_lots,
                "entry_z":       _trigger_z,
                "entry_fill_z":  z_now,
                "leg_directions": {l.symbol: l.effective_direction for l in legs},
            })
            if state is not None:
                state.reset()

        self._update_cycle_excursions(legs, bar_ts, bar_closes)
        if self._basket_open and z_now == z_now:  # nan-safe
            self._cycle_z_lo = min(getattr(self, "_cycle_z_lo", z_now), z_now)
            self._cycle_z_hi = max(getattr(self, "_cycle_z_hi", z_now), z_now)

        # COINTEGRATION-BREAK EXIT (safety override): fires first, never deferred,
        # and clears BOTH pending flags so neither deferred exit can double-fire.
        if self._maybe_break_exit(legs, i, bar_ts, bar_closes, leg_float, floating_total):
            self._pending_exit = False
            self._pending_zstop = False
            return

        equilibrium_exit = False

        # DEFERRED Z-STOP EXIT (next_open): a |z|>=z_stop blowout flagged on the
        # PRIOR bar M; liquidate at THIS bar's OPEN and LATCH (block re-entry until a
        # zero-cross). Highest precedence among the rule's z-driven exits.
        if self._basket_open and self._pending_zstop:
            self._pending_zstop = False
            self._n_zstop_exits += 1
            self._z_stop_latch = True
            open_prices = self._bar_open_prices(legs, bar_ts)
            if open_prices is not None:
                self._liquidate_at_prices(
                    legs, i, bar_ts, open_prices, reason="ZSTOP",
                    extra={"direction": self._basket_direction,
                           "z_stop": self.z_stop, "exit_fill_timing": "next_open"},
                )
            else:
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="ZSTOP",
                    extra={"direction": self._basket_direction,
                           "z_stop": self.z_stop,
                           "exit_fill_timing": "next_open_fallback_close"},
                )
            equilibrium_exit = True
            all_open = False
            floating_total = 0.0
            leg_float = {leg.symbol: 0.0 for leg in legs}

        # DEFERRED zcross EXIT (next_open) — inherited behavior, now guarded so a
        # z-stop exit on this same bar wins.
        if self._basket_open and self._pending_exit and not equilibrium_exit:
            self._pending_exit = False
            self._n_equilibrium_exits += 1
            open_prices = self._bar_open_prices(legs, bar_ts)
            if open_prices is not None:
                self._liquidate_at_prices(
                    legs, i, bar_ts, open_prices, reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction,
                           "exit_fill_timing": "next_open"},
                )
            else:
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction,
                           "exit_fill_timing": "next_open_fallback_close"},
                )
            equilibrium_exit = True
            all_open = False
            floating_total = 0.0
            leg_float = {leg.symbol: 0.0 for leg in legs}

        # HARD TIME-STOP (opt-in via max_bars_in_trade>0).
        if (self._basket_open and not equilibrium_exit and self.max_bars_in_trade > 0
                and self._entry_bar_idx is not None
                and (i - self._entry_bar_idx) >= self.max_bars_in_trade):
            self._liquidate(
                legs, i, bar_ts, bar_closes, leg_float, floating_total,
                reason="TIMESTOP",
                extra={"direction": self._basket_direction},
            )
            equilibrium_exit = True
            all_open = False
            floating_total = 0.0
            leg_float = {leg.symbol: 0.0 for leg in legs}

        # Z-STOP TRIGGER: |z| has blown out to >= z_stop against the reversion bet.
        # Flag a deferred (next_open) stop-exit. Pre-empts the zcross trigger (a
        # |z|>=z_stop bar is far from zero, so no zcross fires there anyway).
        if (self._basket_open and not equilibrium_exit and z_now == z_now
                and abs(z_now) >= self.z_stop):
            self._pending_zstop = True

        # ZCROSS TRIGGER (inherited) — guarded so a just-flagged z-stop wins.
        if (self._basket_open and not equilibrium_exit and not self._pending_zstop
                and zcross_now):
            if self.exit_fill_timing == "next_open":
                self._pending_exit = True
            else:
                self._n_equilibrium_exits += 1
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction},
                )
                equilibrium_exit = True
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        # END-OF-DATA force-finalize (next_open mode): if EITHER deferred exit is
        # pending but there is no bar M+1, liquidate now at this bar's close. A
        # pending z-stop still latches; a pending zcross does not.
        if (self._basket_open and (self._pending_exit or self._pending_zstop)
                and not equilibrium_exit):
            has_next = False
            try:
                idx0 = legs[0].df.index
                after = idx0[idx0 > bar_ts]
                for other in legs[1:]:
                    oidx = other.df.index
                    after = after.intersection(oidx[oidx > bar_ts])
                has_next = len(after) > 0
            except Exception:
                has_next = False
            if not has_next:
                is_zstop = self._pending_zstop
                self._pending_exit = False
                self._pending_zstop = False
                if is_zstop:
                    self._z_stop_latch = True
                    self._n_zstop_exits += 1
                    _reason, _tag = "ZSTOP", "next_open_eof_close_zstop"
                else:
                    self._n_equilibrium_exits += 1
                    _reason, _tag = "EQUILIBRIUM", "next_open_eof_close"
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason=_reason,
                    extra={"direction": self._basket_direction, "exit_fill_timing": _tag},
                )
                equilibrium_exit = True
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        if equilibrium_exit:
            self.recycle_events.append({
                "bar_ts":    bar_ts,
                "action":    "CYCLE_Z_DIAG",
                "entry_z":   getattr(self, "_cycle_entry_z", float("nan")),
                "exit_z":    z_now,
                "z_lo":      getattr(self, "_cycle_z_lo", float("nan")),
                "z_hi":      getattr(self, "_cycle_z_hi", float("nan")),
                "direction": getattr(self, "_cycle_entry_dir", 0),
            })
            self._cycle_entry_z = None
            self._cycle_z_lo = None
            self._cycle_z_hi = None

        if not all_open and not equilibrium_exit:
            if signal_value in (+1, -1):
                self._pending_trigger_z = z_now
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
