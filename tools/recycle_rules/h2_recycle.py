"""H2RecycleRule — faithful port of the research-validated H2 strategy.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 3 (corrected v11.x).

This is the CORRECT H2 implementation. The earlier H2CompressionRecycleRule
(see h2_compression.py; registered as H2_v7_compression@1) misimplemented
the mechanic — its zero-recycles result was a symptom of that bug, not a
basket_sim divergence. This rule is the appended replacement.

Reference (research-validated, 10/10 survival, +62.8% mean across 10
historical 2y windows):
  tools/research/basket_sim.py::simulate + default_recycle_trigger
  tmp/eurjpy_recycle_v2_validation.py::CONFIGS H2 row

H2 mechanic (Variant G + harvest exit + compression gate):

  Per bar, in order:
    1. Compute per-leg floating PnL + total equity = stake + realized + sum(floating)
    2. HARVEST EXIT: if equity >= harvest_target_usd:
         close all legs (realize floating into harvested_total), stop trading
         exit_reason = "TARGET", harvested = True
    3. FLOOR EXIT (optional): if equity <= equity_floor: stop, "FLOOR"
    4. BLOWN: if equity <= 0: stop, "BLOWN"
    5. TIME STOP (optional): if days since entry >= time_stop_days: stop, "TIME"
    6. SAFETY FREEZE (block recycle this bar, no exit):
         dd_breach    = floating_total < 0 AND |floating_total| >= dd_frac * equity
         margin_breach = margin_used >= margin_frac * equity
         regime_gate  = factor_column value < factor_min
    7. RECYCLE TRIGGER (Variant G):
         scan for (winner, loser) leg pair where
           winner_floating >= trigger_usd AND winner.lot > 0
           loser_floating < 0 AND loser.lot > 0
         if found:
           project margin after winner-reset + loser-add-lot;
           if projected margin >= margin_frac * proj_equity -> freeze, skip
           else commit:
             realized_total += winner_floating
             winner: leg.state.entry_price = current bar close (lot unchanged)
             loser:  leg.state.entry_price = weighted-avg with add_lot
                     leg.lot += add_lot

The rule mutates BasketRunner.BasketLeg.{lot, state.entry_price, state.entry_index}
and appends synthetic trade records into leg.trades, mirroring engine entry/exit
trade shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg


_RULE_NAME = "H2_recycle"
_RULE_VERSION = 1
_LOT_UNITS = 100_000  # FX standard lot

# Per-symbol PnL + margin conventions for the H2 supported pairs.
# Extended 2026-05-15 to support new pair-pair experiments (idea 90 S05):
#   - USD_QUOTE: foreign currency is the BASE (e.g. EUR in EURUSD).
#     PnL_USD = lot * units * (price - entry)
#   - USD_BASE: USD is the BASE (e.g. USDJPY). Price is foreign-per-USD.
#     PnL_USD = lot * units * (price - entry) / price
_USD_QUOTE = {"EURUSD", "AUDUSD", "GBPUSD", "NZDUSD"}
_USD_BASE  = {"USDJPY", "USDCHF", "USDCAD"}


def _leg_pnl_usd(leg: BasketLeg, current_price: float) -> float:
    """Floating PnL for one leg given current bar close. Signed by direction."""
    if not leg.state.in_pos:
        return 0.0
    entry = leg.state.entry_price
    if leg.symbol in _USD_QUOTE:
        return leg.direction * leg.lot * _LOT_UNITS * (current_price - entry)
    if leg.symbol in _USD_BASE:
        if current_price <= 0:
            return 0.0
        return leg.direction * leg.lot * _LOT_UNITS * (current_price - entry) / current_price
    raise ValueError(
        f"H2RecycleRule: symbol {leg.symbol!r} convention unknown. "
        f"H2 supports {_USD_QUOTE | _USD_BASE} only."
    )


def _leg_margin_usd(leg: BasketLeg, current_price: float, leverage: float) -> float:
    """Margin used for one leg given current bar close."""
    if not leg.state.in_pos or leg.lot <= 0:
        return 0.0
    if leg.symbol in _USD_QUOTE:
        return leg.lot * _LOT_UNITS * current_price / leverage
    if leg.symbol in _USD_BASE:
        return leg.lot * _LOT_UNITS / leverage
    raise ValueError(f"H2RecycleRule: symbol {leg.symbol!r} convention unknown.")


@dataclass
class H2RecycleRule:
    """The validated H2 strategy: Variant G + $2k harvest exit + compression gate."""

    # Recycle parameters
    trigger_usd: float = 10.0
    add_lot: float = 0.01

    # Account / harvest parameters
    starting_equity: float = 1000.0
    harvest_target_usd: float = 2000.0
    equity_floor_usd: Optional[float] = None      # None = no floor stop
    time_stop_days: Optional[int] = None          # None = no time stop

    # Safety caps
    dd_freeze_frac: float = 0.10
    margin_freeze_frac: float = 0.15
    leverage: float = 1000.0

    # Regime gate (block recycle this bar based on factor / operator / threshold)
    # operator='>=' (default, legacy): gate fires when factor_val < factor_min
    #   — i.e., recycle requires factor >= threshold (LOW = trending = blocked)
    # operator='<=' (S12): gate fires when factor_val > factor_min
    #   — i.e., recycle requires factor <= threshold (HIGH = trending = blocked)
    # operator='abs_<=' (S13): gate fires when abs(factor_val) > factor_min
    #   — i.e., recycle requires |factor| <= threshold (extreme |Z| = blocked)
    #   — for signed factors like stretch_z20 where deviation magnitude
    #     (not sign) classifies the regime.
    # The operator-aware semantics let alternative USD_SYNTH features (vol_5d,
    # autocorr_5d, stretch_z20) which have different "trending" semantics plug
    # into the same rule.
    factor_column: str = "compression_5d"
    factor_min: float = 10.0
    factor_operator: str = ">="

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # ---- Telemetry / state (accessible after run() for tests) -----------
    realized_total: float = 0.0
    harvested_total_usd: float = 0.0
    harvested: bool = False
    exit_reason: Optional[str] = None
    exit_ts: Optional[pd.Timestamp] = None
    recycle_events: list[dict[str, Any]] = field(default_factory=list)

    # Bookkeeping
    _first_bar_ts: Optional[pd.Timestamp] = None
    _n_dd_freezes: int = 0
    _n_margin_freezes: int = 0
    _n_regime_freezes: int = 0

    # ---- 1.3.0-basket schema: per-bar telemetry + summary accumulator ----
    # Identity threading (populated by basket_pipeline._instantiate_rule when known).
    run_id: str = ""
    directive_id: str = ""
    basket_id: str = ""

    # Per-bar record stream — Block A-G of the locked schema (~35 + 8N cols).
    per_bar_records: list[dict[str, Any]] = field(default_factory=list)

    # Running summary accumulator — drives MPS Baskets row (plan §4.5 / §6).
    summary_stats: dict[str, Any] = field(default_factory=dict)

    # Transition-detection state for summary_stats freeze counts.
    _prev_dd_freeze: bool = False
    _prev_margin_freeze: bool = False
    _prev_regime_blocked: bool = False

    # Bookkeeping for bars_since_last_recycle + running peak equity.
    _last_recycle_bar: Optional[int] = None
    _peak_equity: float = 0.0

    def __post_init__(self) -> None:
        if self.trigger_usd <= 0:
            raise ValueError("H2RecycleRule.trigger_usd must be > 0.")
        if self.add_lot <= 0:
            raise ValueError("H2RecycleRule.add_lot must be > 0.")
        if self.harvest_target_usd <= self.starting_equity:
            raise ValueError(
                f"H2RecycleRule.harvest_target_usd ({self.harvest_target_usd}) must exceed "
                f"starting_equity ({self.starting_equity})."
            )
        if not (0 < self.dd_freeze_frac < 1):
            raise ValueError("H2RecycleRule.dd_freeze_frac must be in (0, 1).")
        if not (0 < self.margin_freeze_frac < 1):
            raise ValueError("H2RecycleRule.margin_freeze_frac must be in (0, 1).")
        if not self.factor_column:
            raise ValueError("H2RecycleRule.factor_column must be a non-empty string.")
        if self.factor_operator not in (">=", "<=", "abs_<="):
            raise ValueError(
                f"H2RecycleRule.factor_operator must be '>=', '<=', or 'abs_<='; "
                f"got {self.factor_operator!r}."
            )

        # 1.3.0-basket schema: initialize summary_stats accumulator with sentinels.
        # Updated each call inside _record_bar(); finalized in _exit_all() at harvest.
        self.summary_stats = {
            "peak_floating_dd_usd":         0.0,          # running min of dd_from_peak_usd
            "peak_floating_dd_pct":         0.0,          # running min of dd_from_peak_pct
            "dd_freeze_count":              0,            # False->True transitions
            "margin_freeze_count":          0,            # False->True transitions
            "regime_freeze_count":          0,            # False->True transitions
            "peak_margin_used_usd":         0.0,          # running max
            "min_margin_level_pct":         float("inf"), # running min; finalized to None if never set
            "worst_floating_at_freeze_usd": 0.0,          # running min over freeze bars
            "peak_lots":                    {},           # {symbol: max_lot_seen}
            "final_pnl_usd":                None,         # filled at harvest
            "return_on_real_capital_pct":   None,         # computed at harvest
            "harvest_bar_index":            None,
            "harvest_bar_ts":               None,
            "harvest_reason":               None,
        }
        self._peak_equity = self.starting_equity

    # ---- BasketRule.apply --------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        # Once harvested, nothing else fires — basket is closed (no per-bar record).
        if self.harvested:
            return

        # Establish the entry timestamp for time-stop bookkeeping on first call.
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # Read bar closes once per leg; abort cleanly on sparse data.
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                # Data gap — record RULE_NOT_INVOKED; cannot compute floating/margin.
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes={l.symbol: float("nan") for l in legs},
                    leg_float={l.symbol: 0.0 for l in legs},
                    floating_total=0.0,
                    equity=self.starting_equity + self.realized_total,
                    margin_used=0.0,
                    dd_freeze=False, margin_freeze=False, regime_blocked=False,
                    factor_val=None,
                    skip_reason="RULE_NOT_INVOKED",
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

        # Per-leg floating + totals
        leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # ---- Exit checks (priority order) — _exit_all records the harvest bar ----
        if equity >= self.harvest_target_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TARGET")
            return
        if self.equity_floor_usd is not None and equity <= self.equity_floor_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="FLOOR")
            return
        if equity <= 0:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="BLOWN")
            return
        if (
            self.time_stop_days is not None
            and self._first_bar_ts is not None
            and (bar_ts - self._first_bar_ts).days >= self.time_stop_days
        ):
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TIME")
            return

        # ---- Safety freezes (no exit; just skip recycle this bar) ----
        margin_used = sum(_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage) for leg in legs)
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1

        # ---- Regime gate read (factor may be missing/parse-fail/NaN/below-min) ----
        primary_df = legs[0].df
        column_missing = self.factor_column not in primary_df.columns
        factor_val: Optional[float] = None
        factor_present_but_nan = False
        if not column_missing:
            try:
                raw_val = float(primary_df.loc[bar_ts, self.factor_column])
                if pd.isna(raw_val):
                    factor_present_but_nan = True
                else:
                    factor_val = raw_val
            except (KeyError, ValueError, TypeError):
                # Parse failure — treat as missing.
                column_missing = True
        # Operator-aware regime block (S12 + S13, 2026-05-16):
        #   '>=' (default): block when factor < threshold (compression: LOW=trending)
        #   '<=' (S12): block when factor > threshold (vol/autocorr: HIGH=trending)
        #   'abs_<=' (S13): block when abs(factor) > threshold (stretch: extreme |Z|)
        if factor_val is None:
            regime_blocked = False
        elif self.factor_operator == ">=":
            regime_blocked = factor_val < self.factor_min
        elif self.factor_operator == "<=":
            regime_blocked = factor_val > self.factor_min
        else:  # "abs_<="  (validator restricts to these three)
            regime_blocked = abs(factor_val) > self.factor_min
        # Legacy bar-count: preserve pre-1.3.0 semantics — NaN-factor and below-min
        # both increment _n_regime_freezes. (The new summary_stats counter is
        # transition-based and counts only true REGIME_GATE bars.)
        if factor_present_but_nan or regime_blocked:
            self._n_regime_freezes += 1

        # Early-return: freeze fired this bar (DD takes precedence over MARGIN label).
        if dd_breach or margin_breach:
            skip_reason = "DD_FREEZE" if dd_breach else "MARGIN_FREEZE"
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=dd_breach, margin_freeze=margin_breach,
                regime_blocked=regime_blocked, factor_val=factor_val,
                skip_reason=skip_reason,
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Early-return: factor column missing or NaN — fail-safe to no recycle.
        if column_missing or factor_present_but_nan:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=None,
                skip_reason="RULE_NOT_INVOKED",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Early-return: regime gate blocked.
        if regime_blocked:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=True,
                factor_val=factor_val,
                skip_reason="REGIME_GATE",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- Recycle trigger (Variant G: winner-add-to-loser) ----
        # Pick first eligible (winner, loser) pair; deterministic by leg order.
        winner: Optional[BasketLeg] = None
        loser: Optional[BasketLeg] = None
        for leg in legs:
            if not leg.state.in_pos or leg.lot <= 0:
                continue
            if leg_float[leg.symbol] >= self.trigger_usd:
                winner = leg
                break
        if winner is None:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="NO_WINNER",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return
        for leg in legs:
            if leg is winner:
                continue
            if not leg.state.in_pos or leg.lot <= 0:
                continue
            if leg_float[leg.symbol] < 0:
                loser = leg
                break
        if loser is None:
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="NO_LOSER",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- Projection check: margin after the commit ----
        new_loser_lot = loser.lot + self.add_lot
        # Margin: winner lot unchanged, loser lot grown
        proj_margin = 0.0
        for leg in legs:
            lot = new_loser_lot if leg is loser else leg.lot
            if leg.symbol in _USD_QUOTE:
                proj_margin += lot * _LOT_UNITS * bar_closes[leg.symbol] / self.leverage
            elif leg.symbol in _USD_BASE:
                proj_margin += lot * _LOT_UNITS / self.leverage
        # Equity after realize: realized += winner_floating; winner floating -> 0
        proj_realized = self.realized_total + leg_float[winner.symbol]
        proj_floating = sum(
            leg_float[leg.symbol] for leg in legs if leg is not winner
        )
        proj_equity = self.starting_equity + proj_realized + proj_floating
        if proj_margin >= self.margin_freeze_frac * proj_equity:
            self._n_margin_freezes += 1
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="PROJECTED_MARGIN_BREACH",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- Commit the recycle ----
        winner_realized = leg_float[winner.symbol]
        self.realized_total = proj_realized

        # Winner: realize floating, reset entry to current bar close (lot unchanged)
        winner_old_entry = winner.state.entry_price
        winner.state.entry_price = bar_closes[winner.symbol]
        winner.state.entry_index = i

        # Loser: weighted-avg new entry, lot grows
        loser_old_avg = loser.state.entry_price
        loser_old_lot = loser.lot
        new_avg = (loser_old_lot * loser_old_avg + self.add_lot * bar_closes[loser.symbol]) / new_loser_lot
        loser.state.entry_price = new_avg
        loser.lot = new_loser_lot

        winner_leg_idx = legs.index(winner)
        loser_leg_idx = legs.index(loser)

        # Record the recycle event
        event = {
            "bar_index":         i,
            "bar_ts":            bar_ts,
            "factor_value":      factor_val,
            "winner_symbol":     winner.symbol,
            "winner_realized":   winner_realized,
            "winner_old_entry":  winner_old_entry,
            "winner_new_entry":  bar_closes[winner.symbol],
            "loser_symbol":      loser.symbol,
            "loser_old_lot":     loser_old_lot,
            "loser_new_lot":     new_loser_lot,
            "loser_old_avg":     loser_old_avg,
            "loser_new_avg":     new_avg,
            "realized_total":    self.realized_total,
            "floating_total":    floating_total,
            "equity_before":     equity,
        }
        self.recycle_events.append(event)

        # Also append a synthetic trade record for the winner's realized leg
        # (closes the previous winner entry; the position is conceptually
        # re-opened at the same bar at the new entry price — no exit trade
        # records the re-open, just the close).
        winner.trades.append({
            "entry_index": winner.state.entry_index,  # newly reset == i
            "exit_index":  i,
            "direction":   winner.direction,
            "entry_price": winner_old_entry,
            "exit_price":  bar_closes[winner.symbol],
            "exit_source": "BASKET_RECYCLE_WINNER",
            "exit_reason": _RULE_NAME,
            "pnl_usd":     winner_realized,
        })

        # Per-bar record for the recycle-executed bar.
        # State-capture invariant: at the event bar, the record must show
        # POST-recycle floating to remain internally consistent with the
        # POST-recycle realized_total and POST-recycle per-leg lot/avg_entry
        # (which are already in the leg objects after the mutations above).
        # We recompute leg_float using the mutated state so equity_total =
        # stake + realized + floating holds. Equity itself is invariant under
        # recycle (winner's floating moves into realized; total unchanged).
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol]) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason="NONE",
            recycle_attempted=True, recycle_executed=True,
            harvest_triggered=False,
            winner_leg_idx=winner_leg_idx,
            loser_leg_idx=loser_leg_idx,
        )

    # ---- helpers --------------------------------------------------------

    def _record_bar(
        self,
        legs: list[BasketLeg],
        i: int,
        bar_ts: pd.Timestamp,
        *,
        bar_closes: dict[str, float],
        leg_float: dict[str, float],
        floating_total: float,
        equity: float,
        margin_used: float,
        dd_freeze: bool,
        margin_freeze: bool,
        regime_blocked: bool,
        factor_val: Optional[float],
        skip_reason: str,
        recycle_attempted: bool,
        recycle_executed: bool,
        harvest_triggered: bool,
        winner_leg_idx: Optional[int] = None,
        loser_leg_idx: Optional[int] = None,
    ) -> None:
        """Append one row to per_bar_records and update summary_stats accumulators.

        Single source of truth for both the parquet ledger and the MPS row's
        in-memory summary (plan §4.5 / §6). Called once per apply() invocation
        that doesn't short-circuit on the harvested check.
        """
        # Running peak equity (cummax)
        if equity > self._peak_equity:
            self._peak_equity = equity
        dd_from_peak_usd = equity - self._peak_equity  # <= 0 by construction
        if self._peak_equity > 0:
            dd_from_peak_pct = dd_from_peak_usd / self._peak_equity * 100.0
        else:
            dd_from_peak_pct = 0.0

        # Margin level + free margin
        free_margin = equity - margin_used
        if margin_used > 0:
            margin_level_pct = equity / margin_used * 100.0
        else:
            margin_level_pct = float("nan")

        # Total notional across legs
        notional_total = 0.0
        for leg in legs:
            bc = bar_closes.get(leg.symbol, float("nan"))
            if bc != bc:  # NaN check
                continue
            if leg.symbol in _USD_QUOTE:
                notional_total += leg.lot * _LOT_UNITS * bc
            elif leg.symbol in _USD_BASE:
                notional_total += leg.lot * _LOT_UNITS  # already in USD

        # Block E — basket position state
        in_pos_lots = [leg.lot for leg in legs if leg.state.in_pos]
        active_legs = len(in_pos_lots)
        total_lot = sum(in_pos_lots) if in_pos_lots else 0.0
        largest_leg_lot = max(in_pos_lots) if in_pos_lots else 0.0
        smallest_leg_lot = min(in_pos_lots) if in_pos_lots else 0.0

        # Block G — strategy state
        bars_since_last_recycle = (
            (i - self._last_recycle_bar) if self._last_recycle_bar is not None else None
        )
        bars_since_last_harvest = i  # single-cycle H2: bars since basket open

        record: dict[str, Any] = {
            # Block A — Time/identity
            "timestamp":               bar_ts,
            "directive_id":            self.directive_id,
            "basket_id":               self.basket_id,
            "bar_index":               i,
            "run_id":                  self.run_id,
            # Block B — Equity state
            "floating_total_usd":      floating_total,
            "realized_total_usd":      self.realized_total,
            "equity_total_usd":        equity,
            "peak_equity_usd":         self._peak_equity,
            "dd_from_peak_usd":        dd_from_peak_usd,
            "dd_from_peak_pct":        dd_from_peak_pct,
            # Block C — Margin/capital state
            "margin_used_usd":         margin_used,
            "free_margin_usd":         free_margin,
            "margin_level_pct":        margin_level_pct,
            "notional_total_usd":      notional_total,
            "leverage_effective":      self.leverage,
            # Block D — Engine control state
            "dd_freeze_active":        dd_freeze,
            "margin_freeze_active":    margin_freeze,
            "regime_gate_blocked":     regime_blocked,
            "recycle_attempted":       recycle_attempted,
            "recycle_executed":        recycle_executed,
            "harvest_triggered":       harvest_triggered,
            "engine_paused":           False,
            "skip_reason":             skip_reason,
            # Block E — Position state (basket)
            "active_legs":             active_legs,
            "total_lot":               total_lot,
            "largest_leg_lot":         largest_leg_lot,
            "smallest_leg_lot":        smallest_leg_lot,
            # Block G — Strategy state
            "recycle_count":           len(self.recycle_events),
            "bars_since_last_recycle": bars_since_last_recycle,
            "bars_since_last_harvest": bars_since_last_harvest,
            "gate_factor_value":       factor_val if factor_val is not None else float("nan"),
            "gate_factor_name":        self.factor_column,
            "winner_leg_idx":          winner_leg_idx,
            "loser_leg_idx":           loser_leg_idx,
        }

        # Block F — per-leg state (wide format)
        for idx, leg in enumerate(legs):
            bc = bar_closes.get(leg.symbol, float("nan"))
            if leg.symbol in _USD_QUOTE and bc == bc:
                leg_margin = leg.lot * _LOT_UNITS * bc / self.leverage
                leg_notional = leg.lot * _LOT_UNITS * bc
            elif leg.symbol in _USD_BASE:
                leg_margin = leg.lot * _LOT_UNITS / self.leverage
                leg_notional = leg.lot * _LOT_UNITS
            else:
                leg_margin = 0.0
                leg_notional = 0.0
            record[f"leg_{idx}_symbol"]       = leg.symbol
            record[f"leg_{idx}_side"]         = "long" if leg.direction == 1 else "short"
            record[f"leg_{idx}_lot"]          = leg.lot
            record[f"leg_{idx}_avg_entry"]    = leg.state.entry_price
            record[f"leg_{idx}_mark"]         = bc
            record[f"leg_{idx}_floating_usd"] = leg_float.get(leg.symbol, 0.0)
            record[f"leg_{idx}_margin_usd"]   = leg_margin
            record[f"leg_{idx}_notional_usd"] = leg_notional

        self.per_bar_records.append(record)

        # ---- Update summary_stats accumulators (running aggregates) ----
        stats = self.summary_stats
        if dd_from_peak_usd < stats["peak_floating_dd_usd"]:
            stats["peak_floating_dd_usd"] = dd_from_peak_usd
            stats["peak_floating_dd_pct"] = dd_from_peak_pct
        if dd_freeze and not self._prev_dd_freeze:
            stats["dd_freeze_count"] += 1
        if margin_freeze and not self._prev_margin_freeze:
            stats["margin_freeze_count"] += 1
        if regime_blocked and not self._prev_regime_blocked:
            stats["regime_freeze_count"] += 1
        self._prev_dd_freeze = dd_freeze
        self._prev_margin_freeze = margin_freeze
        self._prev_regime_blocked = regime_blocked
        if margin_used > stats["peak_margin_used_usd"]:
            stats["peak_margin_used_usd"] = margin_used
        if margin_used > 0 and not pd.isna(margin_level_pct):
            if margin_level_pct < stats["min_margin_level_pct"]:
                stats["min_margin_level_pct"] = margin_level_pct
        if dd_freeze or margin_freeze or regime_blocked:
            if floating_total < stats["worst_floating_at_freeze_usd"]:
                stats["worst_floating_at_freeze_usd"] = floating_total
        for leg in legs:
            prev = stats["peak_lots"].get(leg.symbol, 0.0)
            if leg.lot > prev:
                stats["peak_lots"][leg.symbol] = leg.lot

        if recycle_executed:
            self._last_recycle_bar = i

    def _exit_all(
        self,
        legs: list[BasketLeg],
        i: int,
        bar_ts: pd.Timestamp,
        bar_closes: dict[str, float],
        leg_float: dict[str, float],
        *,
        reason: str,
    ) -> None:
        """Close every open leg, banking floating into harvested_total_usd.

        Records the harvest bar to per_bar_records BEFORE clearing leg state
        so the ledger captures end-of-cycle lot/entry/floating per leg. Then
        finalizes summary_stats (final_pnl_usd, return_on_real_capital_pct).
        """
        floating_total = sum(leg_float.values())
        margin_used = sum(
            _leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage) for leg in legs
        )
        equity = self.starting_equity + self.realized_total + floating_total

        self.harvested_total_usd = (
            self.starting_equity + self.realized_total + floating_total - self.starting_equity
        )
        self.harvested = True
        self.exit_reason = reason
        self.exit_ts = bar_ts

        # Record the harvest bar (legs still in pos; per-leg state reflects harvest).
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=leg_float,
            floating_total=floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=None,  # gate not consulted on harvest
            skip_reason="NONE",
            recycle_attempted=False, recycle_executed=False,
            harvest_triggered=True,
        )

        # Finalize summary_stats accumulator with harvest-time values.
        stats = self.summary_stats
        stats["final_pnl_usd"] = self.harvested_total_usd
        peak_dd = abs(stats["peak_floating_dd_usd"])
        if peak_dd > 0:
            stats["return_on_real_capital_pct"] = (
                self.harvested_total_usd / (2.0 * peak_dd) * 100.0
            )
        else:
            stats["return_on_real_capital_pct"] = None
        stats["harvest_bar_index"] = i
        stats["harvest_bar_ts"] = bar_ts
        stats["harvest_reason"] = reason
        if stats["min_margin_level_pct"] == float("inf"):
            stats["min_margin_level_pct"] = None

        # Close all legs.
        for leg in legs:
            if leg.state.in_pos:
                bc = bar_closes[leg.symbol]
                leg.trades.append({
                    "entry_index": leg.state.entry_index,
                    "exit_index":  i,
                    "direction":   leg.direction,
                    "entry_price": leg.state.entry_price,
                    "exit_price":  bc,
                    "exit_source": f"BASKET_HARVEST_{reason}",
                    "exit_reason": _RULE_NAME,
                    "pnl_usd":     leg_float[leg.symbol],
                })
                leg.state.in_pos = False
                leg.state.direction = 0
                leg.state.entry_index = -1
                leg.state.entry_price = 0.0
                leg.state.partial_taken = False
                leg.state.partial_leg = None
                leg.state.stop_price_active = None
                leg.state.entry_market_state = {}


__all__ = ["H2RecycleRule"]
