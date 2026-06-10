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

EXIT-FILL TIMING (opt-in, 2026-06-10) — `exit_fill_timing`
----------------------------------------------------------
The zcross is DETECTED on bar M's close (z[M] vs z[M-1]). The default
exit (`exit_fill_timing="bar_close"`) ALSO FILLS on bar M's close — a
same-bar detect+fill that is unattainable live: a producer computing on
bar M's close emits a market order whose earliest realistic fill is bar
M+1's OPEN. The entry already uses next-bar-open (no lookahead), so the
default exit is asymmetric / lookahead-bearing.

Opt-in `exit_fill_timing="next_open"` makes the exit SYMMETRIC with the
entry: on the zcross bar M it sets a pending-exit (state `_pending_exit`)
instead of liquidating; on the NEXT apply (bar M+1) it liquidates at that
bar's OPEN price (`legs[*].df.loc[bar_ts, "open"]`) and clears the pending
flag. PnL is realized at the M+1 OPEN mark (recomputed via
`_liquidate_at_prices`), exit_index = M+1, exit_price = M+1 open.

Edge cases handled:
  - END OF DATA (no bar M+1): the pending exit is force-liquidated at the
    LAST available bar's close (matches the existing finalize/EOF
    semantics — the basket cannot hang open past the data).
  - COINTEGRATION-BREAK: the break-exit fires first (same priority as in
    the default path) and clears any pending exit, so the two never
    double-fire. A break while a zcross-exit is pending wins (immediate
    flat, no deferral) — the safety override is never deferred.
  - HARD TIME-STOP (`max_bars_in_trade`): if a time-stop fires while a
    zcross-exit is pending, the time-stop liquidates immediately and the
    pending flag is cleared (no double-fire).
  - No re-arm during a pending exit: while `_pending_exit` is set the
    basket is still OPEN, so the FLAT propose path is not reached and no
    fresh cycle is proposed until after the deferred liquidation.

Default `"bar_close"` is BYTE-IDENTICAL to the pre-2026-06-10 behavior
(the pending-exit branch is never entered) — the parity gate is preserved.
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

    # Exit-fill timing (opt-in, 2026-06-10). "bar_close" = liquidate on the
    # zcross bar M's close (default; byte-identical legacy behavior, same-bar
    # detect+fill). "next_open" = defer the zcross liquidation one bar and fill
    # at bar M+1's OPEN (symmetric with the entry's next-bar-open fill, removes
    # the same-bar exit lookahead). See module docstring "EXIT-FILL TIMING".
    exit_fill_timing: str = "bar_close"

    _n_equilibrium_exits: int = 0
    # Per-cycle deferred-exit state (next_open mode only): True between the
    # zcross bar M and the M+1-open liquidation. While True the basket is still
    # OPEN (positions live) and no fresh cycle may be proposed.
    _pending_exit: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.exit_fill_timing not in ("bar_close", "next_open"):
            raise ValueError(
                f"PineRatioZRevRuleZCross.exit_fill_timing must be 'bar_close' "
                f"or 'next_open', got {self.exit_fill_timing!r}."
            )

    def _bar_open_prices(self, legs: list[BasketLeg], bar_ts: pd.Timestamp,
                         ) -> Optional[dict[str, float]]:
        """OPEN price of `bar_ts` for every leg, or None if any is missing.

        Used by the next_open exit to fill the deferred zcross liquidation at
        bar M+1's OPEN rather than its close. Returns None (caller falls back to
        the EOF close-liquidation) when any leg lacks an open at `bar_ts`."""
        out: dict[str, float] = {}
        try:
            for leg in legs:
                out[leg.symbol] = float(leg.df.loc[bar_ts, "open"])
        except (KeyError, ValueError, TypeError):
            return None
        return out

    def _liquidate_at_prices(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        exit_prices: dict[str, float], reason: str,
        *, extra: dict[str, Any] | None = None,
    ) -> float:
        """Liquidate every open leg at the supplied `exit_prices` (not the bar
        close). Recomputes per-leg + total floating PnL at those prices so the
        realized PnL, exit_price, and event exit_prices all reflect the actual
        fill mark (e.g. bar M+1's OPEN for the next_open exit). Returns the
        realized total. Delegates the bookkeeping to the inherited `_liquidate`
        by passing `exit_prices` in the `bar_closes` slot + the freshly-marked
        leg_float — `_liquidate` is mark-agnostic (it reads whatever dict it is
        handed)."""
        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (
                _leg_pnl_usd_universal(leg, exit_prices[leg.symbol], ref_closes)
                if leg.state.in_pos else 0.0
            )
            for leg in legs
        }
        floating_total = sum(leg_float.values())
        self._liquidate(
            legs, i, bar_ts, exit_prices, leg_float, floating_total,
            reason=reason, extra=extra,
        )
        return floating_total

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

        # Z-diagnostics (demo_tradelevel_v1): surface the signal z for the demo
        # outcome ledger. Read-only — never affects entry/exit decisions.
        _z_col = "pine_zrev_z_centered" if self.entry_mode == "centered" else "pine_zrev_z"
        try:
            z_now = float(legs[0].df.loc[bar_ts, _z_col])
        except (KeyError, ValueError, TypeError):
            z_now = float("nan")

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
            # Z-diagnostics: pin entry z (the TRIGGER z, not the lagged fill z) +
            # init the cycle z-excursion trackers from the fill bar.
            _trigger_z = getattr(self, "_pending_trigger_z", z_now)
            self._cycle_entry_z = _trigger_z
            self._cycle_entry_dir = self._basket_direction
            self._cycle_z_lo = z_now
            self._cycle_z_hi = z_now
            # Tradelevel enrichment: inherited from baseline rule.
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

        # Per-bar excursion tracking for the open cycle (no-op if flat).
        self._update_cycle_excursions(legs, bar_ts, bar_closes)
        # Z-excursion (demo_tradelevel_v1): track the cycle's z range for the ledger.
        if self._basket_open and z_now == z_now:  # nan-safe
            self._cycle_z_lo = min(getattr(self, "_cycle_z_lo", z_now), z_now)
            self._cycle_z_hi = max(getattr(self, "_cycle_z_hi", z_now), z_now)

        # COINTEGRATION-BREAK EXIT (live-safety, opt-in; inert in the
        # all-cointegrated backtest corpus) — fires before the equilibrium exit.
        # A break is a safety override: it is never deferred and it WINS over a
        # pending next_open zcross exit (clear the pending flag so the deferred
        # liquidation cannot double-fire on a later bar).
        if self._maybe_break_exit(legs, i, bar_ts, bar_closes, leg_float, floating_total):
            self._pending_exit = False
            return

        equilibrium_exit = False

        # DEFERRED zcross EXIT (next_open mode): a zcross was detected on the
        # PRIOR bar M and we are now on bar M+1. Liquidate at THIS bar's OPEN
        # (symmetric with the entry's next-bar-open fill) and clear the flag.
        # Highest precedence among the rule's own z-driven exits: a decision
        # made on bar M is honored before this bar's time-stop / fresh zcross.
        if self._basket_open and self._pending_exit:
            self._pending_exit = False
            self._n_equilibrium_exits += 1
            open_prices = self._bar_open_prices(legs, bar_ts)
            if open_prices is not None:
                # NOTE: parent _liquidate prepends "LIQUIDATE_" to the reason, so
                # pass "EQUILIBRIUM" to get the clean LIQUIDATE_EQUILIBRIUM tag.
                self._liquidate_at_prices(
                    legs, i, bar_ts, open_prices,
                    reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction,
                           "exit_fill_timing": "next_open"},
                )
            else:
                # Defensive: no open at M+1 (data gap). Force-liquidate at this
                # bar's close so the basket cannot hang open (EOF/finalize-style).
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

        # HARD TIME-STOP (opt-in via max_bars_in_trade>0): force-liquidate after
        # N bars in position, then fall through to the FLAT path so the next
        # +/-z_entry cross opens a fresh cycle (engine handles re-entry natively).
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
        if self._basket_open and not equilibrium_exit:
            try:
                zcross_now = bool(legs[0].df.loc[bar_ts, self.zcross_column])
            except (KeyError, ValueError, TypeError):
                zcross_now = False
            if zcross_now:
                if self.exit_fill_timing == "next_open":
                    # Defer one bar: set the pending flag and KEEP holding. The
                    # M+1-open liquidation runs at the top of the next apply().
                    # End-of-data (no next bar) is handled by the EOF
                    # force-finalize below, which liquidates the still-open
                    # basket at the last bar's close.
                    self._pending_exit = True
                else:
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

        # END-OF-DATA force-finalize (next_open mode only): if a zcross-exit is
        # pending but there is NO bar M+1 to fill at (we are on the last aligned
        # bar), liquidate now at this bar's close so the basket does not hang
        # open past the data. Matches the existing finalize semantics (an open
        # basket at the data boundary is closed at the last mark).
        if (self._basket_open and self._pending_exit and not equilibrium_exit):
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
                self._pending_exit = False
                self._n_equilibrium_exits += 1
                self._liquidate(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    reason="EQUILIBRIUM",
                    extra={"direction": self._basket_direction,
                           "exit_fill_timing": "next_open_eof_close"},
                )
                equilibrium_exit = True
                all_open = False
                floating_total = 0.0
                leg_float = {leg.symbol: 0.0 for leg in legs}

        if equilibrium_exit:
            # Z-diagnostics (demo_tradelevel_v1): one per-cycle z record at exit.
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
                self._pending_trigger_z = z_now   # demo_tradelevel_v1: z that fired the entry
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
