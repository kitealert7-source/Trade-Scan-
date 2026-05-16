"""H2RecycleRuleV3 — H2 recycle with cross-pair PnL support + 1.3.0-basket emitter.

Plan ref: 2026-05-15 operator request to test cross pairs (AUDJPY+GBPAUD,
EURGBP+GBPAUD, etc.) where USD is in NEITHER leg. The USD-anchored
_USD_QUOTE / _USD_BASE convention from v1/v2 doesn't apply — we need a
generalized currency conversion for any major pair.

Phase B extension (2026-05-16): 1.3.0-basket per-bar parquet emitter
mirroring `h2_recycle.py:H2RecycleRule` (@1). Schema identical (35 + 8N
columns, 7 blocks A-G); the only differences are cross-pair-aware PnL +
margin computation routed through `_usd_value_of_ccy`. Every early-return
in apply() now records a bar with the correct `skip_reason` enum value.
Recycle-bar post-state recompute preserved for equity invariant.

Mechanic vs v2:
  * v1 / v2 hardcoded PnL formulas for 7 USD-anchored pairs.
  * v3 GENERALIZES: parses base+quote currency from the 6-letter symbol,
    looks up the USD-conversion factor for each via a _USD_REF table,
    computes PnL in quote currency, converts to USD via the quote-ccy
    USD rate at the current bar.
  * Margin computation same generalization (base-ccy USD rate × notional
    / leverage).
  * For USD-anchored pairs (EUR/USD, USDJPY, etc.) the math collapses
    cleanly back to v1/v2's hardcoded formulas — validated by parity tests.
  * Cap mechanic (max_leg_lot) PRESERVED from v2.

Requires: leg.df has columns `usd_ref_<CCY>_close` for every non-USD
currency referenced in the basket. The basket_data_loader auto-loads these.

Registry: governance/recycle_rules/registry.yaml -> H2_recycle@3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg


_RULE_NAME = "H2_recycle"
_RULE_VERSION = 3
_LOT_UNITS = 100_000  # FX standard lot

# Per-currency USD-conversion reference pair.
# Format: ccy -> usd_anchored_pair_to_use
# Convention: if pair starts with "USD" (USDxxx), the pair's price is xxx-per-USD;
# to get USD-per-xxx, INVERT (1/price). Otherwise (xxxUSD form), the pair's price
# IS USD-per-xxx, use DIRECTLY.
_USD_REF = {
    "USD": None,        # USD value of 1 USD = 1.0 (no lookup)
    "EUR": "EURUSD",    # USD per EUR = EURUSD price directly
    "GBP": "GBPUSD",
    "AUD": "AUDUSD",
    "NZD": "NZDUSD",
    "JPY": "USDJPY",    # USD per JPY = 1.0 / USDJPY price (USDJPY is JPY-per-USD)
    "CHF": "USDCHF",
    "CAD": "USDCAD",
}


def _split_pair(symbol: str) -> tuple[str, str]:
    """Split 6-letter FX symbol into base, quote currencies. e.g. 'AUDJPY' -> ('AUD', 'JPY')."""
    if len(symbol) != 6:
        raise ValueError(
            f"H2RecycleRuleV3: symbol {symbol!r} must be 6 chars (base + quote ccy)."
        )
    return symbol[:3].upper(), symbol[3:].upper()


def _usd_value_of_ccy(ccy: str, ref_closes: dict[str, float]) -> float:
    """Compute the USD value of 1 unit of `ccy` given current bar's reference closes.

    `ref_closes` is a dict mapping USD-anchored pair symbols -> their close at this bar.
    Returns USD per 1 unit of ccy (e.g. for JPY at USDJPY=150, returns 1/150 ≈ 0.00667).

    Raises KeyError if a required reference rate is missing.
    """
    if ccy == "USD":
        return 1.0
    pair = _USD_REF.get(ccy)
    if pair is None:
        raise ValueError(f"H2RecycleRuleV3: no USD reference defined for currency {ccy!r}.")
    rate = ref_closes[pair]
    if rate <= 0:
        raise ValueError(
            f"H2RecycleRuleV3: invalid reference rate {rate!r} for pair {pair!r}."
        )
    # If pair starts with USD (USDxxx form): rate is xxx-per-USD, invert.
    if pair.startswith("USD"):
        return 1.0 / rate
    # Else (xxxUSD form): rate is USD-per-xxx, use directly.
    return rate


def _build_ref_closes(legs: list[BasketLeg], bar_ts: pd.Timestamp) -> dict[str, float]:
    """Build the dict of USD-anchored reference pair closes at this bar.

    Looks for columns named `usd_ref_<PAIR>_close` on each leg's df. Also
    self-references the leg's own price if the leg IS a USD-anchored pair.
    """
    out: dict[str, float] = {}
    for leg in legs:
        # Self-reference: if leg itself is one of the USD-anchored ref pairs,
        # its close IS the reference rate.
        if leg.symbol in {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
                          "USDJPY", "USDCHF", "USDCAD"}:
            try:
                out[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                pass
        # External reference rates loaded by basket_data_loader
        for ref_pair in _USD_REF.values():
            if ref_pair is None:
                continue
            col = f"usd_ref_{ref_pair}_close"
            if col in leg.df.columns and ref_pair not in out:
                try:
                    val = float(leg.df.loc[bar_ts, col])
                    if not pd.isna(val):
                        out[ref_pair] = val
                except (KeyError, ValueError):
                    pass
    return out


def _leg_pnl_usd(leg: BasketLeg, current_price: float,
                 ref_closes: dict[str, float]) -> float:
    """USD-denominated floating PnL for any FX pair (USD-anchored or cross)."""
    if not leg.state.in_pos:
        return 0.0
    _, quote_ccy = _split_pair(leg.symbol)
    pnl_in_quote = leg.direction * leg.lot * _LOT_UNITS * (current_price - leg.state.entry_price)
    usd_per_quote = _usd_value_of_ccy(quote_ccy, ref_closes)
    return pnl_in_quote * usd_per_quote


def _leg_margin_usd(leg: BasketLeg, current_price: float, leverage: float,
                    ref_closes: dict[str, float]) -> float:
    """USD-denominated margin requirement for any FX pair."""
    if not leg.state.in_pos or leg.lot <= 0:
        return 0.0
    base_ccy, _ = _split_pair(leg.symbol)
    notional_in_base = leg.lot * _LOT_UNITS
    usd_per_base = _usd_value_of_ccy(base_ccy, ref_closes)
    return notional_in_base * usd_per_base / leverage


def _leg_notional_usd(leg: BasketLeg, ref_closes: dict[str, float]) -> float:
    """USD-denominated notional exposure for any FX pair (lot × 100k × USD-per-base)."""
    if not leg.state.in_pos or leg.lot <= 0:
        return 0.0
    base_ccy, _ = _split_pair(leg.symbol)
    notional_in_base = leg.lot * _LOT_UNITS
    usd_per_base = _usd_value_of_ccy(base_ccy, ref_closes)
    return notional_in_base * usd_per_base


@dataclass
class H2RecycleRuleV3:
    """H2 recycle with cross-pair PnL support + cap mechanic (inherits v2 cap) +
    1.3.0-basket per-bar emitter (mirrors @1).

    Supports any FX pair whose currencies are in {USD, EUR, GBP, AUD, NZD,
    JPY, CHF, CAD}. Requires basket_data_loader to populate USD reference
    rate columns on each leg's df.
    """

    # Recycle parameters
    trigger_usd: float = 10.0
    add_lot: float = 0.01

    # Account / harvest parameters
    starting_equity: float = 1000.0
    harvest_target_usd: float = 2000.0
    equity_floor_usd: Optional[float] = None
    time_stop_days: Optional[int] = None

    # Safety caps
    dd_freeze_frac: float = 0.10
    margin_freeze_frac: float = 0.15
    leverage: float = 1000.0

    # Regime gate
    factor_column: str = "compression_5d"
    factor_min: float = 10.0

    # v2 cap mechanic (preserved)
    max_leg_lot: Optional[float] = None

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Telemetry / state
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
    _n_cap_skipped: int = 0

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
            raise ValueError("trigger_usd must be > 0.")
        if self.add_lot <= 0:
            raise ValueError("add_lot must be > 0.")
        if self.harvest_target_usd <= self.starting_equity:
            raise ValueError(
                f"harvest_target_usd ({self.harvest_target_usd}) must exceed "
                f"starting_equity ({self.starting_equity})."
            )
        if not (0 < self.dd_freeze_frac < 1):
            raise ValueError("dd_freeze_frac must be in (0, 1).")
        if not (0 < self.margin_freeze_frac < 1):
            raise ValueError("margin_freeze_frac must be in (0, 1).")
        if self.max_leg_lot is not None and self.max_leg_lot <= 0:
            raise ValueError("max_leg_lot must be > 0 or None.")

        # 1.3.0-basket schema: initialize summary_stats accumulator with sentinels.
        # Updated each call inside _record_bar(); finalized in _exit_all() at harvest.
        self.summary_stats = {
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
        self._peak_equity = self.starting_equity

    # ---- BasketRule.apply --------------------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        # Once harvested, nothing else fires — basket is closed (no per-bar record).
        if self.harvested:
            return

        # Establish the entry timestamp for time-stop bookkeeping on first call.
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # Bar closes for each leg
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
                    ref_closes={},
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

        # Build reference closes (USD-anchored pair prices for currency conversion)
        try:
            ref_closes = _build_ref_closes(legs, bar_ts)
        except (KeyError, ValueError):
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes,
                leg_float={l.symbol: 0.0 for l in legs},
                ref_closes={},
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

        # Per-leg floating PnL + totals
        try:
            leg_float = {
                leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                for leg in legs
            }
        except (KeyError, ValueError):
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes,
                leg_float={l.symbol: 0.0 for l in legs},
                ref_closes=ref_closes,
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
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # ---- Exit checks ----
        if equity >= self.harvest_target_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, ref_closes, reason="TARGET")
            return
        if self.equity_floor_usd is not None and equity <= self.equity_floor_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, ref_closes, reason="FLOOR")
            return
        if equity <= 0:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, ref_closes, reason="BLOWN")
            return
        if (
            self.time_stop_days is not None
            and self._first_bar_ts is not None
            and (bar_ts - self._first_bar_ts).days >= self.time_stop_days
        ):
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, ref_closes, reason="TIME")
            return

        # ---- Safety freezes ----
        try:
            margin_used = sum(
                _leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage, ref_closes)
                for leg in legs
            )
        except (KeyError, ValueError):
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
                floating_total=floating_total, equity=equity, margin_used=0.0,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=None,
                skip_reason="RULE_NOT_INVOKED",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return
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
                column_missing = True
        regime_blocked = (factor_val is not None) and (factor_val < self.factor_min)
        if factor_present_but_nan or regime_blocked:
            self._n_regime_freezes += 1

        # Early-return: freeze fired this bar (DD takes precedence over MARGIN label).
        if dd_breach or margin_breach:
            skip_reason = "DD_FREEZE" if dd_breach else "MARGIN_FREEZE"
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
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
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
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
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=True,
                factor_val=factor_val,
                skip_reason="REGIME_GATE",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- Recycle trigger (Variant G) ----
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
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
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
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="NO_LOSER",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- v2 cap check ----
        projected_new_lot = loser.lot + self.add_lot
        cap_skipped = (
            self.max_leg_lot is not None
            and projected_new_lot > self.max_leg_lot
        )
        effective_new_lot = loser.lot if cap_skipped else projected_new_lot

        # ---- Projection: margin after commit ----
        proj_margin = 0.0
        try:
            for leg in legs:
                lot = effective_new_lot if leg is loser else leg.lot
                base_ccy, _ = _split_pair(leg.symbol)
                usd_per_base = _usd_value_of_ccy(base_ccy, ref_closes)
                proj_margin += lot * _LOT_UNITS * usd_per_base / self.leverage
        except (KeyError, ValueError):
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="RULE_NOT_INVOKED",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return
        proj_realized = self.realized_total + leg_float[winner.symbol]
        proj_floating = sum(
            leg_float[leg.symbol] for leg in legs if leg is not winner
        )
        proj_equity = self.starting_equity + proj_realized + proj_floating
        if proj_margin >= self.margin_freeze_frac * proj_equity:
            self._n_margin_freezes += 1
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="PROJECTED_MARGIN_BREACH",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # ---- Commit ----
        winner_realized = leg_float[winner.symbol]
        self.realized_total = proj_realized

        winner_old_entry = winner.state.entry_price
        winner.state.entry_price = bar_closes[winner.symbol]
        winner.state.entry_index = i

        loser_old_avg = loser.state.entry_price
        loser_old_lot = loser.lot
        if cap_skipped:
            self._n_cap_skipped += 1
            new_avg = loser_old_avg
        else:
            new_avg = (
                loser_old_lot * loser_old_avg
                + self.add_lot * bar_closes[loser.symbol]
            ) / effective_new_lot
            loser.state.entry_price = new_avg
            loser.lot = effective_new_lot

        winner_leg_idx = legs.index(winner)
        loser_leg_idx = legs.index(loser)

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
            "loser_new_lot":     effective_new_lot,
            "loser_old_avg":     loser_old_avg,
            "loser_new_avg":     new_avg,
            "realized_total":    self.realized_total,
            "floating_total":    floating_total,
            "equity_before":     equity,
            "cap_skipped":       cap_skipped,
        }
        self.recycle_events.append(event)

        winner.trades.append({
            "entry_index": winner.state.entry_index,
            "exit_index":  i,
            "direction":   winner.direction,
            "entry_price": winner_old_entry,
            "exit_price":  bar_closes[winner.symbol],
            "exit_source": "BASKET_RECYCLE_WINNER",
            "exit_reason": _RULE_NAME,
            "pnl_usd":     winner_realized,
        })

        # Per-bar record for the recycle-executed bar (POST-state recompute
        # to preserve equity = stake + realized + floating invariant).
        post_leg_float = {
            leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
            for leg in legs
        }
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float, ref_closes=ref_closes,
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
        ref_closes: dict[str, float],
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

        Cross-pair version: per-leg margin/notional routed through
        `_usd_value_of_ccy` for any currency in _USD_REF.
        """
        # Running peak equity (cummax)
        if equity > self._peak_equity:
            self._peak_equity = equity
        dd_from_peak_usd = equity - self._peak_equity
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

        # Total notional across legs (cross-pair-aware)
        notional_total = 0.0
        for leg in legs:
            try:
                notional_total += _leg_notional_usd(leg, ref_closes)
            except (KeyError, ValueError):
                pass

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
        bars_since_last_harvest = i

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

        # Block F — per-leg state (wide format), cross-pair-aware
        for idx, leg in enumerate(legs):
            bc = bar_closes.get(leg.symbol, float("nan"))
            try:
                leg_margin = _leg_margin_usd(leg, bc, self.leverage, ref_closes)
                leg_notional = _leg_notional_usd(leg, ref_closes)
            except (KeyError, ValueError):
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
        ref_closes: dict[str, float],
        *,
        reason: str,
    ) -> None:
        """Close every open leg, banking floating into harvested_total_usd.

        Records the harvest bar to per_bar_records BEFORE clearing leg state
        so the ledger captures end-of-cycle lot/entry/floating per leg. Then
        finalizes summary_stats (final_pnl_usd, return_on_real_capital_pct).
        """
        floating_total = sum(leg_float.values())
        try:
            margin_used = sum(
                _leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage, ref_closes)
                for leg in legs
            )
        except (KeyError, ValueError):
            margin_used = 0.0
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
            bar_closes=bar_closes, leg_float=leg_float, ref_closes=ref_closes,
            floating_total=floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=None,
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


__all__ = ["H2RecycleRuleV3", "_USD_REF", "_split_pair", "_usd_value_of_ccy"]
