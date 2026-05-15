"""H2RecycleRuleV3 — H2 recycle with cross-pair PnL support.

Plan ref: 2026-05-15 operator request to test cross pairs (AUDJPY+GBPAUD,
EURGBP+GBPAUD, etc.) where USD is in NEITHER leg. The USD-anchored
_USD_QUOTE / _USD_BASE convention from v1/v2 doesn't apply — we need a
generalized currency conversion for any major pair.

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


@dataclass
class H2RecycleRuleV3:
    """H2 recycle with cross-pair PnL support + cap mechanic (inherits v2 cap).

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

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self.harvested:
            return
        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # Bar closes for each leg
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                return

        # Build reference closes (USD-anchored pair prices for currency conversion)
        try:
            ref_closes = _build_ref_closes(legs, bar_ts)
        except (KeyError, ValueError):
            return

        # Per-leg floating PnL + totals
        try:
            leg_float = {
                leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes)
                for leg in legs
            }
        except (KeyError, ValueError):
            return
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # ---- Exit checks ----
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

        # ---- Safety freezes ----
        try:
            margin_used = sum(
                _leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage, ref_closes)
                for leg in legs
            )
        except (KeyError, ValueError):
            return
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1
        if dd_breach or margin_breach:
            return

        # ---- Regime gate ----
        primary_df = legs[0].df
        if self.factor_column not in primary_df.columns:
            return
        try:
            factor_val = float(primary_df.loc[bar_ts, self.factor_column])
        except (KeyError, ValueError, TypeError):
            return
        if pd.isna(factor_val) or factor_val < self.factor_min:
            self._n_regime_freezes += 1
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
        for leg in legs:
            lot = effective_new_lot if leg is loser else leg.lot
            base_ccy, _ = _split_pair(leg.symbol)
            try:
                usd_per_base = _usd_value_of_ccy(base_ccy, ref_closes)
            except (KeyError, ValueError):
                return
            proj_margin += lot * _LOT_UNITS * usd_per_base / self.leverage
        proj_realized = self.realized_total + leg_float[winner.symbol]
        proj_floating = sum(
            leg_float[leg.symbol] for leg in legs if leg is not winner
        )
        proj_equity = self.starting_equity + proj_realized + proj_floating
        if proj_margin >= self.margin_freeze_frac * proj_equity:
            self._n_margin_freezes += 1
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
        floating_total = sum(leg_float.values())
        self.harvested_total_usd = (
            self.starting_equity + self.realized_total + floating_total - self.starting_equity
        )
        self.harvested = True
        self.exit_reason = reason
        self.exit_ts = bar_ts
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
