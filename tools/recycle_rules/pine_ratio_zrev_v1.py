"""pine_ratio_zrev_v1.py — Pine z_r reversal rule (always-in-market).

Strategy spec: Pine source at `Pine Indicators/Cointegrated Pair Strategy.txt`.
Companion indicator: `Pine Indicators/Cointegrated Pair Overlay.txt`.
Lineage: preserved follow-on arc #2 from COINTREV_v1_2 retirement (see
`outputs/cointegration_screener_v1/v1_2_backtest/REPORT_pilot_2026-05-24.md`
addendum 5). Material delta vs retired v1.2:
  (1) Hedge ratio = SMA(A/B, N), not Pearson β from `_compute_neutral_basket`
  (2) Signal = per-bar z_r computed in rule from close prices (via
      `indicators.stats.ratio_hedged_spread_zscore`), not screener-snapshot
      daily z from `cointegration_triggers` ledger
  (3) Exit logic = always-in-market reversal at |z_r| >= z_entry (Centered mode
      subtracts z_r's own rolling mean before threshold check), not three-exit
      (mean-rev / regime / time-stop)
  (4) Hedge ratio LOCKED at entry per CLAUDE.md invariant 4 (snapshot-immutable)

Architectural notes
-------------------
Reuses v1.2's two-bar protocol for entries — the leg sets pending in shared
state, the rule approves and sets `approved_fire_ts = next aligned bar`,
the leg fires on that bar, engine queues open at next_bar_open.

Always-in-market reversal: when the basket is OPEN in direction X and a
z_r cross in the OPPOSITE direction fires, the rule LIQUIDATEs the current
basket AND sets a fresh proposal (with reversed direction) in the SAME
apply() pass. No idle gap between cycles.

Z_r computation happens once at first apply() — the rule calls
`ratio_hedged_spread_zscore(a_close, b_close, N, n_meta)` from both legs'
close series and attaches result columns to BOTH legs' DataFrames:
  pine_zrev_z          : raw z_r series
  pine_zrev_z_centered : z_r minus its rolling mean (Centered mode only)
  pine_zrev_mean_zr    : z_r's rolling mean (Centered mode only)
  pine_zrev_r_bar      : the hedge ratio SMA(A/B, N)
  pine_zrev_signal     : +1 / -1 / 0 cross events derived from the active z

The leg strategy reads `pine_zrev_signal` and propagates via shared state.

Inherits H2RecycleRule for parquet emission + recycle_events machinery
(same pattern as H3SpreadV1Rule and cointegration_meanrev_v1_2). The
inherited harvest / floor / compression-gate params are unused (kept for
parquet schema compatibility).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.capital.capital_broker_spec import load_broker_spec
from tools.recycle_rules.cointegration_meanrev_v1_2 import (
    _leg_pnl_usd_universal,
    _leg_margin_usd_universal,
)
from tools.recycle_rules.h2_recycle import H2RecycleRule
from tools.recycle_rules.h2_recycle_v3 import _build_ref_closes
from tools.recycle_strategies import PineZRevArmedState
from indicators.stats.ratio_hedged_spread_zscore import ratio_hedged_spread_zscore


_RULE_NAME = "pine_ratio_zrev_v1"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRule(H2RecycleRule):
    """Pine z_r reversal rule — always-in-market.

    Inherits H2RecycleRule for parquet emission + recycle_events list. Overrides
    apply() entirely. Inherited harvest/floor/compression params unused
    (kept for parquet schema compatibility).
    """

    # --- Pine port params ---
    n_window: int = 100          # rolling window for r_bar + z-score
    n_meta: int = 100            # centering window for z_r's own rolling mean
    z_entry: float = 2.0         # reversal threshold (|z_r| or |z_r - mean|)
    entry_mode: str = "centered" # "absolute" | "centered"
    hedge_lock_at_entry: bool = True  # snapshot r_bar at entry (always True for now)
    always_in_market: bool = True     # liquidate+reverse on opposite cross
    initial_notional_usd: float = 1000.0
    # Notional-balanced sizing (v1.1 fix for v1.0's lot-equal blowup pathology).
    # Each leg gets lot such that $-notional == target_notional_per_leg_usd at
    # entry, computed from broker's usd_per_pu_per_lot. Matches Pine's approach
    # (notional in A's price units → both legs hold equal dollar exposure).
    # Default 10000 matches Pine Strategy's `notional = 10000` default.
    target_notional_per_leg_usd: float = 10000.0

    # Leg column the rule will attach
    signal_column: str = "pine_zrev_signal"
    r_bar_column: str = "pine_zrev_r_bar"

    # Fallback lot
    default_initial_lot: float = 0.01

    # Injected by basket_pipeline dispatch — same instance passed to both legs
    shared_armed_state: Optional[PineZRevArmedState] = None

    # --- Name + version overrides (parent fields) ---
    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # --- Per-cycle state ---
    _z_r_attached: bool = False
    _basket_open: bool = False
    _basket_direction: int = 0   # +1 LONG_SPREAD / -1 SHORT_SPREAD
    _entry_bar_idx: Optional[int] = None
    _entry_r_bar: Optional[float] = None
    _entry_lots: dict[str, float] = field(default_factory=dict)
    # Tradelevel enrichment state (_cycle_entry_ctx, _cycle_mfe_price,
    # _cycle_mae_price) + helpers (_snapshot_cycle_entry_ctx,
    # _update_cycle_excursions, _enrich_exit_trade) are inherited from
    # H2RecycleRule (lifted there 2026-05-31 to share across the H2/H3/Pine
    # basket rule family).

    # --- Telemetry ---
    _n_signals_seen: int = 0
    _n_approvals: int = 0
    _n_liquidations: int = 0
    _n_reversals: int = 0
    _peak_equity_pz: float = 0.0

    # --- Back-reference (populated by BasketRunner.__init__) ---
    basket_runner: Optional[BasketRunner] = None

    # ---- Warmup contract (BasketRule Protocol extension, 2026-05-30) ----

    def required_warmup_bars(self) -> int:
        """Bars of pre-start_date data the rule's z_r needs for validity.

        Mechanism, NOT comfort — every number traces to a line of code:

        - Absolute mode: ratio_hedged_spread_zscore computes z_r over a
          rolling n_window window. The first valid z_r value is at bar
          index `n_window - 1` (uses bars 0..n_window-1 inclusive). The
          rule's own published floor is the line-215 assertion
          `len(common_idx) >= 2 * n_window`. We mirror that exactly —
          with 2*n_window bars there are n_window+1 valid z_r values,
          sufficient for cross detection (requires 2 consecutive valid
          values). No safety buffer: if a directive trips this floor at
          execution time, the failure is real (data shortage), not
          warmup-shortfall, and should surface — not be padded over.

        - Centered mode: `z_r_centered` = z_r minus its own rolling mean
          over n_meta past z_r values. The centering mean is first valid
          n_meta bars AFTER z_r becomes valid, so the first valid
          centered z_r is at bar `n_window - 1 + n_meta`. Pre-extension
          floor: `n_window + n_meta` bars (off by 1 vs the strict
          n_window + n_meta - 1, accepted as a single-bar over-allocation
          to keep the formula intuitive and self-documenting).

        Pipeline reads this via
        `getattr(rule, 'required_warmup_bars', lambda: 0)()` and passes
        the value to both the data loader (extends [start_date, end_date]
        backward) and BasketRunner.warmup_bars (mutes leg signals +
        rule.apply during the warmup region).
        """
        if self.entry_mode == "centered":
            return self.n_window + self.n_meta
        return 2 * self.n_window

    def __post_init__(self) -> None:
        # Validate params
        if self.n_window < 2:
            raise ValueError(
                f"PineRatioZRevRule.n_window must be >= 2, got {self.n_window!r}."
            )
        if self.entry_mode not in ("absolute", "centered"):
            raise ValueError(
                f"PineRatioZRevRule.entry_mode must be 'absolute' or 'centered', "
                f"got {self.entry_mode!r}."
            )
        if self.entry_mode == "centered" and self.n_meta < 2:
            raise ValueError(
                f"PineRatioZRevRule.n_meta must be >= 2 in centered mode, "
                f"got {self.n_meta!r}."
            )
        if self.z_entry <= 0:
            raise ValueError(
                f"PineRatioZRevRule.z_entry must be > 0, got {self.z_entry!r}."
            )
        if self.initial_notional_usd <= 0:
            raise ValueError(
                f"PineRatioZRevRule.initial_notional_usd must be > 0, "
                f"got {self.initial_notional_usd!r}."
            )
        if self.default_initial_lot <= 0:
            raise ValueError(
                f"PineRatioZRevRule.default_initial_lot must be > 0, "
                f"got {self.default_initial_lot!r}."
            )

        # Initialize parent attributes the inherited _record_bar / _emit_record
        # machinery reads but our flow doesn't update — same compatibility
        # shim H3SpreadV1Rule + COINTREV v1.2 use.
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

        self._peak_equity_pz = self.starting_equity
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

    # ---- z_r attach (one-time on first apply) ----------------------------

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Compute z_r from both legs and attach signal columns to leg.df.

        Cross-region pairs (e.g. CHFJPY/UK100) have divergent market holidays;
        each leg's df can have a different index length. We compute z_r on the
        INTERSECTED index (= bars where BOTH legs have data) and reindex back
        to each leg's full index, leaving signal=0 (no fire) on holiday bars
        the partner leg is missing. This mirrors v1.2's daily-TF cross-region
        holiday fix (REPORT_pilot_2026-05-24.md addendum 5).

        Cross events are derived from the active z series (centered or raw)
        per the Pine reference (Pine Indicators/Cointegrated Pair Overlay.txt
        line 173-176): cross from below +z_entry → short spread (-1);
        cross from above -z_entry → long spread (+1).
        """
        common_idx = legs[0].df.index.intersection(legs[1].df.index)
        if len(common_idx) < self.n_window * 2:
            raise RuntimeError(
                f"PineRatioZRevRule._attach_z_r: intersected leg index has "
                f"only {len(common_idx)} bars; need at least 2 * n_window "
                f"({2 * self.n_window}) for valid z_r warmup. "
                f"len_a={len(legs[0].df)}, len_b={len(legs[1].df)}."
            )

        a_close = legs[0].df["close"].reindex(common_idx)
        b_close = legs[1].df["close"].reindex(common_idx)

        n_meta = self.n_meta if self.entry_mode == "centered" else None
        z_data = ratio_hedged_spread_zscore(
            a_close, b_close,
            n=self.n_window,
            n_meta=n_meta,
        )

        # Active z series for cross detection
        if self.entry_mode == "centered":
            z_active = z_data["z_r_centered"]
        else:
            z_active = z_data["z_r"]

        # Cross detection (same as Pine ta.cross logic):
        # Cross UP through +z_entry  → SHORT_SPREAD (-1): z_r is HIGH, A is rich
        # Cross DN through -z_entry  → LONG_SPREAD  (+1): z_r is LOW, A is cheap
        prev_z = z_active.shift(1)
        crossed_up = (prev_z <= self.z_entry) & (z_active > self.z_entry)
        crossed_dn = (prev_z >= -self.z_entry) & (z_active < -self.z_entry)

        signal_aligned = pd.Series(0, index=z_active.index, dtype="int64")
        signal_aligned[crossed_dn] = +1   # LONG_SPREAD
        signal_aligned[crossed_up] = -1   # SHORT_SPREAD

        # Attach to BOTH legs' dfs — reindex to each leg's full index, fill
        # missing-partner-bars with 0 signal / NaN values (won't fire)
        for leg in legs:
            leg.df[self.signal_column] = signal_aligned.reindex(leg.df.index, fill_value=0)
            leg.df[self.r_bar_column] = z_data["r_bar"].reindex(leg.df.index)
            leg.df["pine_zrev_z"] = z_data["z_r"].reindex(leg.df.index)
            if self.entry_mode == "centered":
                leg.df["pine_zrev_z_centered"] = z_data["z_r_centered"].reindex(leg.df.index)
                leg.df["pine_zrev_mean_zr"] = z_data["mean_zr"].reindex(leg.df.index)

        self._z_r_attached = True

    # ---- core mechanic ---------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts
            if not self._z_r_attached:
                self._attach_z_r(legs)
            # Auto-discover shared state from the leg strategy on first bar
            if self.shared_armed_state is None:
                for leg in legs:
                    armed = getattr(leg.strategy, "armed_state", None)
                    if isinstance(armed, PineZRevArmedState):
                        self.shared_armed_state = armed
                        break

        # Bar-close reads with data-gap guard
        bar_closes: dict[str, float] = {}
        try:
            for leg in legs:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
        except (KeyError, ValueError):
            return  # data gap; skip silently

        # Per-leg floating P&L via universal helper (FX delegates to v3;
        # non-FX uses broker spec usd_per_pu_per_lot). Reuses v1.2's helpers.
        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {
            leg.symbol: (_leg_pnl_usd_universal(leg, bar_closes[leg.symbol], ref_closes)
                         if leg.state.in_pos else 0.0)
            for leg in legs
        }
        floating_total = sum(leg_float.values())
        all_open = all(leg.state.in_pos for leg in legs)

        # Current bar's z_r cross signal
        try:
            signal_value = int(legs[0].df.loc[bar_ts, self.signal_column])
        except (KeyError, ValueError, TypeError):
            signal_value = 0

        # BASKET_OPEN transition: legs were opened by PineZRevLegStrategy
        if all_open and not self._basket_open:
            self._basket_open = True
            self._entry_bar_idx = i
            state = self.shared_armed_state
            if state is not None and state.proposed_direction != 0:
                self._basket_direction = state.proposed_direction
            else:
                # Defensive: derive from leg state.direction (cycle-aware) if
                # shared state missing. Reading leg.direction would give YAML
                # BASE and mis-sign SHORT cycles.
                self._basket_direction = int(legs[0].state.direction or 0)
            entry_lots = {leg.symbol: leg.lot for leg in legs}
            self._entry_lots = entry_lots
            # Tradelevel enrichment: snapshot per-leg entry context for the
            # exit_trade dict; init MFE/MAE trackers to this bar's high/low.
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

        # OPEN basket + opposite-direction cross → REVERSAL (liquidate + repropose)
        reversal_triggered = False
        if self._basket_open and signal_value != 0 and signal_value != self._basket_direction:
            self._n_reversals += 1
            self._liquidate(legs, i, bar_ts, bar_closes, leg_float, floating_total,
                            reason="REVERSAL",
                            extra={"new_direction": signal_value,
                                   "old_direction": self._basket_direction})
            reversal_triggered = True
            all_open = False  # state has changed
            # Floating now zero; signal_value is the new direction to propose
            floating_total = 0.0
            leg_float = {leg.symbol: 0.0 for leg in legs}

        # FLAT state: try to propose + approve
        if not all_open:
            # Use the reversal's signal_value if we just liquidated, else current bar's
            propose_signal = signal_value if reversal_triggered else signal_value
            if propose_signal in (+1, -1):
                self._maybe_propose(propose_signal, bar_ts)
            self._maybe_approve(legs, i, bar_ts)
            self._emit_record(legs, i, bar_ts, bar_closes, leg_float,
                              floating_total=0.0,
                              skip_reason="REVERSAL_PENDING" if reversal_triggered else "AWAITING_ENTRY")
            return

        # Basket open, no exit signal → emit per-bar HOLDING record
        self._emit_record(legs, i, bar_ts, bar_closes, leg_float, floating_total,
                          skip_reason="HOLDING")

    # ---- Proposal / Approval phase ---------------------------------------

    def _maybe_propose(self, signal_value: int, bar_ts: pd.Timestamp) -> None:
        """Set shared state's pending proposal if signal is non-zero and no
        cycle in flight."""
        if signal_value not in (+1, -1):
            return
        state = self.shared_armed_state
        if state is None:
            return
        if state.pending_trigger_ts is None and state.approved_fire_ts is None:
            state.pending_trigger_ts = bar_ts
            state.proposed_direction = signal_value
            self._n_signals_seen += 1

    def _maybe_approve(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        """Approve pending proposal: lock r_bar at entry, mutate leg.lot to
        default_initial_lot, set approved_fire_ts = next aligned bar."""
        state = self.shared_armed_state
        if state is None or state.pending_trigger_ts != bar_ts:
            return
        if state.proposed_direction not in (+1, -1):
            return

        # Snapshot r_bar at entry bar — locked hedge ratio per CLAUDE.md invariant 4
        try:
            r_bar_now = float(legs[0].df.loc[bar_ts, self.r_bar_column])
        except (KeyError, ValueError, TypeError):
            r_bar_now = float("nan")
        if r_bar_now != r_bar_now or r_bar_now <= 0:
            # Warmup (r_bar NaN) or bad data — skip this signal
            state.reset()
            return

        # Resolve next-bar timestamp via intersection of leg indices (same
        # cross-region market-holiday safety as v1.2 daily-TF fix)
        aligned_after_now = legs[0].df.index[legs[0].df.index > bar_ts]
        for other_leg in legs[1:]:
            aligned_after_now = aligned_after_now.intersection(
                other_leg.df.index[other_leg.df.index > bar_ts]
            )
        if len(aligned_after_now) == 0:
            # No next bar (end of data) — drop the signal
            state.reset()
            return
        next_bar_ts = aligned_after_now[0]

        # Notional-balanced sizing (v1.1 fix). Each leg's lot is computed so
        # that $-notional at entry equals target_notional_per_leg_usd. Matches
        # Pine's approach (notional in A's price units, hedge leg sized to
        # the same dollar notional via r̄).
        #
        # Formula: notional_usd ≈ lot × price × usd_per_pu_per_lot
        # Solving: lot = target_notional_per_leg_usd / (price × usd_per_pu_per_lot)
        # Floor to broker's min_lot (rounded down to lot_step), reject if
        # broker spec missing.
        #
        # Distinct from v1.2's β-neutral _compute_neutral_basket (which
        # produces 1:15,000 lot ratios for small-r̄ pairs — see v1.2 addendum 3
        # for why that backfires on outright moves).
        lots_by_sym: dict[str, float] = {}
        sizing_failed = False
        for leg in legs:
            try:
                spec = load_broker_spec(leg.symbol)
            except FileNotFoundError:
                sizing_failed = True
                break
            usd_per_pu = float((spec.get("calibration", {}) or {}).get("usd_per_pu_per_lot", 0) or 0)
            min_lot = float(spec.get("min_lot", 0.01) or 0.01)
            lot_step = float(spec.get("lot_step", 0.01) or 0.01)
            if usd_per_pu <= 0 or lot_step <= 0:
                sizing_failed = True
                break
            price_now = float(legs[0].df.loc[bar_ts, "close"]) if leg.symbol == legs[0].symbol else float(legs[1].df.loc[bar_ts, "close"])
            raw_lot = self.target_notional_per_leg_usd / (price_now * usd_per_pu)
            # Round down to lot_step, floor at min_lot
            lot = max(min_lot, int(raw_lot / lot_step) * lot_step)
            lots_by_sym[leg.symbol] = lot
        if sizing_failed:
            # Broker spec missing or calibration invalid — reject this signal
            # rather than fall back to vol-mismatched lots.
            state.reset()
            return
        for leg in legs:
            leg.lot = lots_by_sym[leg.symbol]

        # Lock entry-bar hedge ratio
        self._entry_r_bar = r_bar_now

        # Set APPROVED phase + invariant assertion
        state.approved_fire_ts = next_bar_ts
        state.approved = True

        assert state.approved_fire_ts > state.pending_trigger_ts, (
            f"PINE_ZREV approval invariant violated: approved_fire_ts "
            f"({state.approved_fire_ts}) must be strictly > pending_trigger_ts "
            f"({state.pending_trigger_ts})."
        )

        self._n_approvals += 1
        self.recycle_events.append({
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "action":            "APPROVED",
            "proposed_direction": state.proposed_direction,
            "approved_fire_ts":  next_bar_ts,
            "entry_r_bar":       r_bar_now,
        })

    # ---- Liquidation -----------------------------------------------------

    # Tradelevel enrichment helpers (_snapshot_cycle_entry_ctx,
    # _update_cycle_excursions, _enrich_exit_trade) and the
    # _ENTRY_PASSTHROUGH_COLS constant live on H2RecycleRule (parent class).

    def _liquidate(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, reason: str,
        *, extra: dict[str, Any] | None = None,
    ) -> None:
        """Close all legs at bar close, realize P&L, reset cycle state.
        Restores leg.lot to initial value. Same shape as v1.2._liquidate.

        Tradelevel enrichment (2026-05-31): the rule constructs the minimal
        per-leg exit_trade dict (basics + pnl_usd) and the inherited
        `_enrich_exit_trade` from H2RecycleRule adds the analytical fields
        (atr_entry, risk_distance, initial_stop_price, r_multiple, mfe/mae
        prices + R units, vol/trend/regime passthroughs).
        """
        if self.basket_runner is None:
            raise RuntimeError(
                "PineRatioZRevRule._liquidate: basket_runner is None. "
                "Did __init__ skip the back-reference injection?"
            )

        realized_pnl = floating_total
        self.realized_total += realized_pnl

        for leg in legs:
            if not leg.state.in_pos:
                continue
            exit_trade: dict[str, Any] = {
                "entry_index":    leg.state.entry_index,
                "entry_price":    leg.state.entry_price,
                "exit_index":     i,
                "exit_price":     bar_closes[leg.symbol],
                "direction":      leg.effective_direction,
                "lot":             leg.lot,
                "exit_source":    f"PINE_ZREV_{reason}",
                "exit_timestamp": bar_ts,
                "pnl_usd":         leg_float.get(leg.symbol, 0.0),
            }
            # Enrich in place — adds r_multiple, mfe/mae prices + R units,
            # atr_entry, risk_distance, initial_stop_price, vol/trend/regime
            # passthroughs from the cycle's BASKET_OPEN snapshot.
            self._enrich_exit_trade(exit_trade, leg)
            leg.trades.append(exit_trade)
            leg.state.in_pos = False
            leg.state.direction = 0
            leg.state.pending_entry = None
            leg.lot = self.basket_runner._initial_lots[leg.symbol]

        self._n_liquidations += 1
        self._basket_open = False
        self._basket_direction = 0
        self._entry_bar_idx = None
        self._entry_r_bar = None
        self._entry_lots = {}
        # Reset enrichment trackers for next cycle.
        self._cycle_entry_ctx = {}
        self._cycle_mfe_price = {}
        self._cycle_mae_price = {}

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

    # ---- Per-bar record (1.3.0-basket schema; mirrors v1.2 _emit_record) ----

    def _emit_record(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, skip_reason: str,
    ) -> None:
        """Per-bar record matching 1.3.0-basket fixed schema + 8 cols per leg.
        Schema identical to CointegrationMeanRevV1_2Rule._emit_record so the
        existing basket_report tooling parses both rule types uniformly."""
        equity = self.starting_equity + self.realized_total + floating_total
        if equity > self._peak_equity_pz:
            self._peak_equity_pz = equity
        dd_from_peak_usd = equity - self._peak_equity_pz
        if self._peak_equity_pz > 0:
            dd_from_peak_pct = dd_from_peak_usd / self._peak_equity_pz * 100.0
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
            m = _leg_margin_usd_universal(leg, bc, self.leverage, ref_closes)
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
            "peak_equity_usd":         self._peak_equity_pz,
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
            record[f"leg_{idx}_side"]         = leg.effective_direction
            record[f"leg_{idx}_lot"]          = leg.lot
            record[f"leg_{idx}_avg_entry"]    = leg.state.entry_price
            record[f"leg_{idx}_mark"]         = bc
            record[f"leg_{idx}_floating_usd"] = leg_float.get(leg.symbol, 0.0)
            record[f"leg_{idx}_margin_usd"]   = per_leg_margin.get(leg.symbol, 0.0)
            record[f"leg_{idx}_notional_usd"] = per_leg_notional.get(leg.symbol, 0.0)

        self.per_bar_records.append(record)
