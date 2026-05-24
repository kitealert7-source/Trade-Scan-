"""cointegration_meanrev_v1_2.py — COINTREV v1.2 β-weighted spread rule.

Strategy spec: outputs/cointegration_screener_v1/v1_2_strategy_design/DESIGN_DOC.md
Architecture: H2_ENGINE_PROMOTION_PLAN.md Phase 3 (recycle_rule infrastructure).

Distinct from the retired COINTREV v1 (equal-lot, no trigger ledger). v1.2
trades the screener's `cointegration_triggers` ledger via β-weighted lots
(`cointegration_excel._compute_neutral_basket`) with regime-degradation as
the de facto stop loss.

Architectural notes
-------------------
Trigger consumption uses a two-bar leg ↔ rule protocol:
  Bar N    : CointTriggerLegStrategy detects coint_trigger=True and writes
             pending_trigger_ts + proposed_direction into a shared
             CointTriggerArmedState. Returns None (no fire signal).
  Bar N    : This rule's apply() inspects the proposal, enforces min-gap
             and no-open-position policy, computes β-sized lots from
             coint_beta_at_trigger, MUTATES leg.lot to those values, sets
             approved_fire_ts = legs[0].df.index[loc(N)+1] (STRICTLY > N).
  Bar N+1  : Leg returns {"signal": position_direction * proposed_direction}.
             Engine queues open at next_bar_open (Bar N+2) with the already-
             correct β-sized lot. No "open-then-mutate" hazard.
  Bar N+2  : Both legs in_pos. Rule detects BASKET_OPEN transition, records
             event with β-sized lots, sets _last_entry_as_of (drives the
             next cycle's min-gap dedupe), clears shared state.

Exits (priority order — BASE RUN, no hard z-stop):
  1. MEAN_REVERSION       : abs(coint_current_zscore) <= exit_z
  2. REGIME_DEGRADATION   : coint_regime in regime_exit_states
                            (default ['breaking', 'broken'] — LOCKED per
                            §4 of the design doc; the de facto stop loss)
  3. TIME_STOP            : elapsed bars in position >= time_stop_bars

After liquidation, basket continues. The leg strategy resumes watching for
the next coint_trigger (subject to min-gap on the rule side).

Compatibility shim
------------------
Inherits H2RecycleRule for the 1.3.0-basket per-bar parquet emission and
recycle_events machinery (same pattern as H3SpreadV1Rule). The inherited
compression-gate / harvest / floor params are present but unused — kept
for parquet schema compatibility (so _emit_record's reads don't crash).

Reference
---------
DESIGN_DOC.md §§4, 11 (resume notes captured 2026-05-24).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.cointegration_excel import _compute_neutral_basket
from tools.recycle_rules.h2_recycle import H2RecycleRule
from tools.recycle_rules.h2_recycle_v3 import (
    _build_ref_closes,
    _leg_pnl_usd,
    _leg_margin_usd,
)
from tools.recycle_strategies import CointTriggerArmedState

_RULE_NAME = "cointegration_meanrev_v1_2"
_RULE_VERSION = 1


@dataclass
class CointegrationMeanRevV1_2Rule(H2RecycleRule):
    """β-weighted spread rule consuming `cointegration_triggers` ledger.

    Inherits H2RecycleRule for parquet emission + recycle_events list
    machinery. Overrides apply() entirely. The inherited harvest / floor /
    compression-gate params are present but unused (kept for parquet schema
    compatibility).
    """

    # --- v1.2 params ---
    min_gap_days_between_triggers: int = 5
    exit_z: float = 1.0
    time_stop_bars: int = 60
    regime_exit_states: tuple[str, ...] = ("breaking", "broken")
    initial_notional_usd: float = 1000.0

    # Leg-df column contract (matches basket_data_loader auto-join)
    trigger_column: str = "coint_trigger"
    regime_column: str = "coint_regime"
    zscore_column: str = "coint_current_zscore"
    beta_column: str = "coint_beta_at_trigger"
    direction_column: str = "coint_direction"

    # Fallback lot if β-sizing returns None (broker spec missing, etc.)
    default_initial_lot: float = 0.01

    # Injected by basket_pipeline dispatch — same instance is also passed to
    # both CointTriggerLegStrategy legs. Required for production flow;
    # per-rule fresh instance is unit-test convenience only.
    shared_armed_state: Optional[CointTriggerArmedState] = None

    # --- Name + version overrides (parent fields) ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- Per-cycle state ---
    _basket_open: bool = False
    _entry_bar_idx: Optional[int] = None
    _last_entry_as_of: Optional[pd.Timestamp] = None
    _entry_beta: Optional[float] = None
    _entry_lots: dict[str, float] = field(default_factory=dict)

    _n_proposals_seen: int = 0
    _n_approvals: int = 0
    _n_rejected_min_gap: int = 0
    _n_rejected_open_position: int = 0
    _n_rejected_bad_direction: int = 0
    _n_rejected_beta_unavailable: int = 0
    _n_rejected_no_next_bar: int = 0
    _n_liquidations: int = 0
    _n_mean_rev_exits: int = 0
    _n_regime_exits: int = 0
    _n_time_stops: int = 0
    _peak_equity_v12: float = 0.0

    # --- Back-reference (populated by BasketRunner.__init__) ---
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # Skip parent validation — our schema is different. Validate v1.2 params.
        if self.min_gap_days_between_triggers < 0:
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.min_gap_days_between_triggers must "
                f"be >= 0; got {self.min_gap_days_between_triggers!r}."
            )
        if not (self.exit_z > 0):
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.exit_z must be > 0; "
                f"got {self.exit_z!r}."
            )
        if self.time_stop_bars <= 0:
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.time_stop_bars must be > 0; "
                f"got {self.time_stop_bars!r}."
            )
        if not self.regime_exit_states:
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.regime_exit_states must be a "
                f"non-empty tuple; got {self.regime_exit_states!r}."
            )
        if self.initial_notional_usd <= 0:
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.initial_notional_usd must be > 0; "
                f"got {self.initial_notional_usd!r}."
            )
        if self.default_initial_lot <= 0:
            raise ValueError(
                f"CointegrationMeanRevV1_2Rule.default_initial_lot must be > 0; "
                f"got {self.default_initial_lot!r}."
            )

        # Initialize parent attributes the inherited _record_bar / _emit_record
        # machinery reads but our flow doesn't update — same compatibility
        # shim H3SpreadV1Rule uses.
        self.realized_total = 0.0
        self.harvested = False
        self.recycle_events: list[dict[str, Any]] = []
        self.per_bar_records: list[dict[str, Any]] = []
        self._first_bar_ts: Optional[pd.Timestamp] = None
        self._n_dd_freezes = 0
        self._n_margin_freezes = 0
        self._n_regime_freezes = 0
        self.trigger_usd = 10.0
        self.add_lot = self.default_initial_lot
        self.starting_equity = self.initial_notional_usd
        self.harvest_target_usd = 1e12
        self.equity_floor_usd = None
        self.time_stop_days = None
        self.dd_freeze_frac = 0.999
        self.margin_freeze_frac = 0.999
        self.leverage = 1000.0
        self.factor_column = ""
        self.factor_min = 0.0
        self.factor_operator = ">="

        self._peak_equity_v12 = self.starting_equity
        self.summary_stats: dict[str, Any] = {
            "peak_floating_dd_usd":         0.0,
            "peak_floating_dd_pct":         0.0,
            "dd_freeze_count":              0,
            "margin_freeze_count":          0,
            "regime_freeze_count":          0,
            "peak_margin_used_usd":         0.0,
            "min_margin_level_pct":         float("inf"),
            "worst_floating_at_freeze_usd": 0.0,
            "peak_lots":                    {},
            "final_pnl_usd":                None,
            "return_on_real_capital_pct":   None,
            "harvest_bar_index":            None,
            "harvest_bar_ts":               None,
            "harvest_reason":               None,
        }

    # ---- core mechanic ---------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts
            # Auto-discover shared state from the leg strategy on first bar.
            # basket_pipeline._instantiate_rule cannot pass the shared state
            # directly (it's created in run_pipeline alongside legs); the rule
            # discovers it via leg.strategy.armed_state instead. Explicit
            # injection (constructor `shared_armed_state=`) wins if provided
            # — covers unit-test paths.
            if self.shared_armed_state is None:
                for leg in legs:
                    armed = getattr(leg.strategy, "armed_state", None)
                    if isinstance(armed, CointTriggerArmedState):
                        self.shared_armed_state = armed
                        break

        # Bar-close reads with data-gap guard.
        bar_closes: dict[str, float] = {}
        try:
            for leg in legs:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
        except (KeyError, ValueError):
            return  # data gap; skip silently

        # Per-leg floating P&L via V3 cross-pair helpers (same as H3).
        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (_leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                         if leg.state.in_pos else 0.0)
            for leg in legs
        }
        floating_total = sum(leg_float.values())

        all_open = all(leg.state.in_pos for leg in legs)

        # BASKET_OPEN transition: legs opened by CointTriggerLegStrategy.
        # Lock entry_bar; record event with β-sized lots; commit min-gap
        # state (_last_entry_as_of); clear shared_armed_state for next cycle.
        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            # _last_entry_as_of derives from the pending_trigger_as_of that
            # was approved; pull from shared state if still present, else
            # fall back to bar_ts.normalize() (defensive — should not happen).
            state = self.shared_armed_state
            if state is not None and state.pending_trigger_as_of is not None:
                self._last_entry_as_of = state.pending_trigger_as_of
            else:
                self._last_entry_as_of = pd.Timestamp(bar_ts).normalize()
            # Snapshot β-sized lots for the audit event (captured BEFORE
            # any subsequent mutations).
            entry_lots = {leg.symbol: leg.lot for leg in legs}
            self._entry_lots = entry_lots
            self.recycle_events.append({
                "bar_index":           i,
                "bar_ts":              bar_ts,
                "action":              "BASKET_OPEN",
                "entry_beta":          self._entry_beta,
                "entry_lots":          entry_lots,
                "leg_directions":      {l.symbol: l.direction for l in legs},
                "approved_as_of":      self._last_entry_as_of,
            })
            # Reset shared coordinator — cycle is in flight now.
            if state is not None:
                state.reset()

        # If basket NOT open: handle APPROVAL phase (if shared state has a
        # fresh proposal from this bar), then emit AWAITING record.
        if not all_open:
            self._maybe_approve(legs, i, bar_ts)
            self._emit_record(
                legs, i, bar_ts, bar_closes, leg_float,
                floating_total=0.0,
                skip_reason="AWAITING_ENTRY",
            )
            return

        # ---- Exit checks (priority order) -------------------------------

        try:
            zscore_now = float(legs[0].df.loc[bar_ts, self.zscore_column])
        except (KeyError, ValueError, TypeError):
            zscore_now = float("nan")
        try:
            regime_now = legs[0].df.loc[bar_ts, self.regime_column]
            if not isinstance(regime_now, str):
                regime_now = ""
        except (KeyError, ValueError, TypeError):
            regime_now = ""

        # 1. MEAN_REVERSION — abs(z) inside exit band (primary success path)
        if zscore_now == zscore_now and abs(zscore_now) <= self.exit_z:
            self._n_mean_rev_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="MEAN_REVERSION",
                            extra={"exit_zscore": zscore_now})
            return

        # 2. REGIME_DEGRADATION — first non-cointegrated reading (de facto stop)
        if regime_now in self.regime_exit_states:
            self._n_regime_exits += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="REGIME_DEGRADATION",
                            extra={"exit_regime": regime_now,
                                   "exit_zscore": zscore_now})
            return

        # 3. TIME_STOP — elapsed bars >= time_stop_bars
        # NB: `is not None` check (not `or`) — _entry_bar_idx can be 0 on
        # the first bar of a window, and `0 or i` would evaluate to `i`.
        entry_idx = self._entry_bar_idx if self._entry_bar_idx is not None else i
        elapsed = i - entry_idx
        if elapsed >= self.time_stop_bars:
            self._n_time_stops += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float,
                            floating_total, reason="TIME_STOP",
                            extra={"elapsed_bars": elapsed,
                                   "exit_zscore": zscore_now})
            return

        # No exit — emit per-bar record.
        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason="HOLDING",
        )

    # ---- Approval phase --------------------------------------------------

    def _maybe_approve(
        self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
    ) -> None:
        """Inspect a fresh leg-side proposal and decide admit/reject.

        Runs ONLY when basket is not open. The leg's check_entry has already
        run (per-bar order: leg evaluate → rule apply), so any pending
        proposal in shared state from THIS bar is ready for inspection.

        Decisions:
          - bad_direction       (proposed_direction == 0)
          - min_gap_violation   (days since _last_entry_as_of < min_gap_days)
          - open_position       (basket already in cycle — defensive; shouldn't
                                 trigger here since we gate on `not all_open`)
          - beta_unavailable    (β missing or _compute_neutral_basket returns None)
          - no_next_bar         (data gap at end of series)
          - ACCEPTED → mutate leg.lot to β-sized; set approved_fire_ts +
                       approved=True. Strict-greater invariant asserted.
        """
        state = self.shared_armed_state
        if state is None:
            return  # Test mode without shared state — nothing to approve.

        # Only act on FRESH proposals from this bar.
        if state.pending_trigger_ts != bar_ts:
            return

        self._n_proposals_seen += 1

        # Reject: bad direction (auto-join contract guarantees a valid string
        # on trigger=True bars; this branch is defensive).
        if state.proposed_direction not in (+1, -1):
            self._n_rejected_bad_direction += 1
            self._reject(state, i, bar_ts, reason="BAD_DIRECTION")
            return

        # Reject: min-gap violation.
        if (self._last_entry_as_of is not None
                and state.pending_trigger_as_of is not None):
            gap_days = (state.pending_trigger_as_of - self._last_entry_as_of).days
            if gap_days < self.min_gap_days_between_triggers:
                self._n_rejected_min_gap += 1
                self._reject(state, i, bar_ts, reason="MIN_GAP_VIOLATION",
                             extra={"gap_days": gap_days,
                                    "last_entry_as_of": self._last_entry_as_of,
                                    "pending_as_of": state.pending_trigger_as_of})
                return

        # Reject: open-position (defensive — basket should not be open here).
        if self._basket_open:
            self._n_rejected_open_position += 1
            self._reject(state, i, bar_ts, reason="OPEN_POSITION")
            return

        # Compute β-sized lots. Canonical alphabetical pair order matches
        # the cointegration_triggers ledger's β computation convention.
        try:
            beta = float(legs[0].df.loc[bar_ts, self.beta_column])
        except (KeyError, ValueError, TypeError):
            beta = float("nan")
        if beta != beta:   # NaN check
            self._n_rejected_beta_unavailable += 1
            self._reject(state, i, bar_ts, reason="BETA_NAN")
            return

        sym_alpha, sym_beta = sorted([legs[0].symbol, legs[1].symbol])
        lot_a, lot_b = _compute_neutral_basket(sym_alpha, sym_beta, beta)
        if lot_a is None or lot_b is None:
            self._n_rejected_beta_unavailable += 1
            self._reject(state, i, bar_ts, reason="NEUTRAL_BASKET_UNAVAILABLE",
                         extra={"beta": beta})
            return

        # Resolve the next bar timestamp for approved_fire_ts.
        # Uses legs[0]'s full index; data gaps on legs[1] at N+1 are rare
        # and would manifest as the leg's check_entry not seeing fire_at_ts.
        df_index = legs[0].df.index
        try:
            loc = df_index.get_loc(bar_ts)
        except KeyError:
            self._n_rejected_no_next_bar += 1
            self._reject(state, i, bar_ts, reason="NO_NEXT_BAR")
            return
        if not isinstance(loc, int) or (loc + 1) >= len(df_index):
            self._n_rejected_no_next_bar += 1
            self._reject(state, i, bar_ts, reason="NO_NEXT_BAR")
            return
        next_bar_ts = df_index[loc + 1]

        # Mutate leg.lot — pre-open sizing (engine reads leg.lot at fire bar
        # to size the open at next_bar_open of that fire bar).
        lots_by_sym = {sym_alpha: lot_a, sym_beta: lot_b}
        for leg in legs:
            leg.lot = lots_by_sym[leg.symbol]

        # Set APPROVED phase + invariant assertion.
        state.approved_fire_ts = next_bar_ts
        state.approved = True
        self._entry_beta = beta

        assert state.approved_fire_ts > state.pending_trigger_ts, (
            f"COINTREV approval invariant violated: approved_fire_ts "
            f"({state.approved_fire_ts}) must be strictly > pending_trigger_ts "
            f"({state.pending_trigger_ts})."
        )

        self._n_approvals += 1
        self.recycle_events.append({
            "bar_index":           i,
            "bar_ts":              bar_ts,
            "action":              "APPROVED",
            "proposed_direction":  state.proposed_direction,
            "approved_fire_ts":    next_bar_ts,
            "beta":                beta,
            "lots_by_symbol":      dict(lots_by_sym),
            "pending_as_of":       state.pending_trigger_as_of,
        })

    def _reject(
        self, state: CointTriggerArmedState, i: int, bar_ts: pd.Timestamp,
        *, reason: str, extra: dict[str, Any] | None = None,
    ) -> None:
        """Reject a proposal — log event, reset shared state."""
        event = {
            "bar_index":           i,
            "bar_ts":              bar_ts,
            "action":              "REJECTED",
            "reason":              reason,
            "proposed_direction":  state.proposed_direction,
            "pending_as_of":       state.pending_trigger_as_of,
        }
        if extra:
            event.update(extra)
        self.recycle_events.append(event)
        state.reset()

    # ---- Liquidation -----------------------------------------------------

    def _liquidate(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, reason: str,
        *, extra: dict[str, Any] | None = None,
    ) -> None:
        """Close all legs at bar close, realize P&L, reset cycle state.
        Restores leg.lot to default_initial_lot (next cycle's β-sized lots
        are computed at the next approval bar).
        """
        if self.basket_runner is None:
            raise RuntimeError(
                "CointegrationMeanRevV1_2Rule._liquidate: basket_runner is None. "
                "Did __init__ skip the back-reference injection?"
            )

        realized_pnl = floating_total
        self.realized_total += realized_pnl

        for leg in legs:
            if not leg.state.in_pos:
                continue
            exit_trade = {
                "entry_index":    leg.state.entry_index,
                "entry_price":    leg.state.entry_price,
                "exit_index":     i,
                "exit_price":     bar_closes[leg.symbol],
                "direction":      leg.direction,
                "lot":            leg.lot,
                "exit_source":    f"COINTREV_{reason}",
                "exit_timestamp": bar_ts,
            }
            leg.trades.append(exit_trade)
            leg.state.in_pos = False
            leg.state.direction = 0
            leg.state.pending_entry = None
            # Restore initial-lot placeholder; next cycle's β-sized lots
            # are computed at the next approval.
            leg.lot = self.basket_runner._initial_lots[leg.symbol]

        self._n_liquidations += 1
        self._basket_open = False
        self._entry_bar_idx = None
        self._entry_beta = None
        self._entry_lots = {}

        event: dict[str, Any] = {
            "bar_index":               i,
            "bar_ts":                  bar_ts,
            "action":                  "LIQUIDATE",
            "reason":                  reason,
            "realized_pnl_usd":        realized_pnl,
            "cumulative_realized_usd": self.realized_total,
            "exit_prices":             dict(bar_closes),
        }
        if extra:
            event.update(extra)
        self.recycle_events.append(event)

        self._emit_record(
            legs, i, bar_ts, bar_closes, leg_float, floating_total,
            skip_reason=f"LIQUIDATE_{reason}",
        )

    # ---- Per-bar record (1.3.0-basket schema; mirrors H3SpreadV1Rule) ---

    def _emit_record(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, skip_reason: str,
    ) -> None:
        """Emit one per-bar record matching the 1.3.0-basket fixed schema +
        8 cols per leg. Same shape as H3SpreadV1Rule._emit_record (which
        sets the canonical pattern for non-H2 inheritors).

        COINTREV-specific mappings:
          - recycle_attempted / recycle_executed: always False (no pyramid
            in base run).
          - harvest_triggered: always False (no equity target).
          - regime_gate_blocked / dd_freeze_active / margin_freeze_active:
            always False.
          - gate_factor_value / gate_factor_name: NaN / "".
          - winner_leg_idx / loser_leg_idx: None (no winner/loser concept).
        """
        equity = self.starting_equity + self.realized_total + floating_total
        if equity > self._peak_equity_v12:
            self._peak_equity_v12 = equity
        dd_from_peak_usd = equity - self._peak_equity_v12
        if self._peak_equity_v12 > 0:
            dd_from_peak_pct = dd_from_peak_usd / self._peak_equity_v12 * 100.0
        else:
            dd_from_peak_pct = 0.0

        ref_closes = _build_ref_closes(legs, bar_ts)
        margin_used = 0.0
        notional_total = 0.0
        per_leg_margin: dict[str, float] = {}
        per_leg_notional: dict[str, float] = {}
        for leg in legs:
            bc = bar_closes.get(leg.symbol, float("nan"))
            if bc != bc or not leg.state.in_pos:
                per_leg_margin[leg.symbol] = 0.0
                per_leg_notional[leg.symbol] = 0.0
                continue
            m = _leg_margin_usd(leg, bc, self.leverage, ref_closes)
            per_leg_margin[leg.symbol] = m
            margin_used += m
            n = m * self.leverage
            per_leg_notional[leg.symbol] = n
            notional_total += n

        free_margin = equity - margin_used
        margin_level_pct = (equity / margin_used * 100.0) if margin_used > 0 else float("nan")

        in_pos_lots = [leg.lot for leg in legs if leg.state.in_pos]
        active_legs = len(in_pos_lots)
        total_lot = sum(in_pos_lots) if in_pos_lots else 0.0
        largest_leg_lot = max(in_pos_lots) if in_pos_lots else 0.0
        smallest_leg_lot = min(in_pos_lots) if in_pos_lots else 0.0

        bars_since_last_recycle = None
        bars_since_last_harvest = (
            (i - self._entry_bar_idx) if self._entry_bar_idx is not None else 0
        )

        record: dict[str, Any] = {
            "timestamp":               bar_ts,
            "directive_id":            self.directive_id,
            "basket_id":               self.basket_id,
            "bar_index":               i,
            "run_id":                  self.run_id,
            "floating_total_usd":      floating_total,
            "realized_total_usd":      self.realized_total,
            "equity_total_usd":        equity,
            "peak_equity_usd":         self._peak_equity_v12,
            "dd_from_peak_usd":        dd_from_peak_usd,
            "dd_from_peak_pct":        dd_from_peak_pct,
            "margin_used_usd":         margin_used,
            "free_margin_usd":         free_margin,
            "margin_level_pct":        margin_level_pct,
            "leverage_effective":      self.leverage,
            "notional_total_usd":      notional_total,
            "total_lot":               total_lot,
            "active_legs":             active_legs,
            "largest_leg_lot":         largest_leg_lot,
            "smallest_leg_lot":        smallest_leg_lot,
            "recycle_attempted":       False,
            "recycle_executed":        False,
            "recycle_count":           self._n_liquidations,
            "harvest_triggered":       False,
            "regime_gate_blocked":     False,
            "dd_freeze_active":        False,
            "margin_freeze_active":    False,
            "engine_paused":           False,
            "gate_factor_value":       float("nan"),
            "gate_factor_name":        "",
            "winner_leg_idx":          None,
            "loser_leg_idx":           None,
            "bars_since_last_recycle": bars_since_last_recycle,
            "bars_since_last_harvest": bars_since_last_harvest,
            "skip_reason":             skip_reason,
        }
        for idx, leg in enumerate(legs):
            bc = bar_closes.get(leg.symbol, float("nan"))
            record[f"leg_{idx}_symbol"]       = leg.symbol
            record[f"leg_{idx}_side"]         = leg.direction
            record[f"leg_{idx}_lot"]          = leg.lot
            record[f"leg_{idx}_avg_entry"]    = leg.state.entry_price
            record[f"leg_{idx}_mark"]         = bc
            record[f"leg_{idx}_floating_usd"] = leg_float.get(leg.symbol, 0.0)
            record[f"leg_{idx}_margin_usd"]   = per_leg_margin.get(leg.symbol, 0.0)
            record[f"leg_{idx}_notional_usd"] = per_leg_notional.get(leg.symbol, 0.0)

        self.per_bar_records.append(record)
