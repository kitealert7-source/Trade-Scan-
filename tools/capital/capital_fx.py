"""FX currency parsing + dynamic USD conversion.

ConversionLookup caches daily close series for non-USD quote currencies
and supports date-aware bisect lookup. get_usd_per_price_unit_dynamic()
falls back to the provided static value when data is unavailable and
logs once per symbol (see _STATIC_FALLBACK_WARNED).
"""

from __future__ import annotations

import bisect
from datetime import datetime, date as date_type, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ======================================================================
# FX SYMBOL HELPERS
# ======================================================================

# Symbol -> (base_ccy, quote_ccy) for all 18 FX pairs
def _parse_fx_currencies(symbol: str) -> Tuple[str, str]:
    """Extract base and quote currency from a 6-char FX symbol."""
    if len(symbol) == 6 and symbol.isalpha():
        return symbol[:3], symbol[3:]
    return "", ""  # Non-FX (index, commodity, crypto)


# Quote currency -> (conversion_pair_symbol, invert?)
# To get quote_ccy_to_USD rate:
#   if not inverted: rate = close_price of conversion pair
#   if inverted:     rate = 1 / close_price of conversion pair
CONVERSION_MAP = {
    "USD": None,                           # No conversion needed
    "JPY": ("USDJPY", True),               # 1/USDJPY
    "CAD": ("USDCAD", True),               # 1/USDCAD
    "CHF": ("USDCHF", True),               # 1/USDCHF
    "GBP": ("GBPUSD", False),              # GBPUSD directly
    "AUD": ("AUDUSD", False),              # AUDUSD directly
    "NZD": ("NZDUSD", False),              # NZDUSD directly
    "EUR": ("EURUSD", False),              # EURUSD directly
}


# ======================================================================
# CONVERSION LOOKUP
# ======================================================================

class ConversionLookup:
    """
    Provides O(1)-ish USD conversion rate lookups by date.

    Loads daily close prices from RESEARCH data for each required
    conversion pair. Uses bisect to find the nearest available date
    (handles weekends/holidays).
    """

    def __init__(self):
        # {currency: [(date, rate), ...]} sorted by date
        self._series: Dict[str, List[Tuple[date_type, float]]] = {}
        self._dates: Dict[str, List[date_type]] = {}  # for bisect
        self._fallback_warned: set = set()

    def load(self, currencies_needed: set, data_root: Optional[Path] = None):
        """Load daily close series for all needed non-USD quote currencies."""
        from data_access.readers.research_data_reader import load_research_data

        if data_root is None:
            data_root = _PROJECT_ROOT / "data_root" / "MASTER_DATA"

        for ccy in currencies_needed:
            if ccy == "USD":
                continue
            conv = CONVERSION_MAP.get(ccy)
            if conv is None:
                print(f"[WARN] No conversion mapping for currency: {ccy}")
                continue

            pair_symbol, inverted = conv
            try:
                df = load_research_data(
                    symbol=pair_symbol,
                    timeframe="1d",
                    broker="OctaFX",
                    start_date="2005-01-01",
                    end_date="2030-12-31",
                    data_root=data_root,
                )
                # Build sorted (date, rate) list
                entries = []
                for _, row in df.iterrows():
                    ts = pd.to_datetime(row.get("timestamp", row.get("date")), utc=True)
                    close = float(row["close"])
                    if inverted:
                        rate = 1.0 / close if close != 0 else 0.0
                    else:
                        rate = close
                    entries.append((ts.date(), rate))

                entries.sort(key=lambda x: x[0])
                self._series[ccy] = entries
                self._dates[ccy] = [e[0] for e in entries]
                print(f"[CONV] Loaded {pair_symbol} -> {ccy}/USD: {len(entries)} daily bars")

            except FileNotFoundError:
                print(f"[WARN] Conversion data not found for {pair_symbol}. Will use YAML fallback for {ccy}.")

    @staticmethod
    def _normalize_lookup_date(lookup_input) -> date_type:
        """
        Normalize date or datetime inputs to UTC-trading date.

        Naive datetimes are treated as UTC by contract.
        """
        if isinstance(lookup_input, datetime):
            if lookup_input.tzinfo is None:
                lookup_input = lookup_input.replace(tzinfo=timezone.utc)
            else:
                lookup_input = lookup_input.astimezone(timezone.utc)
            return lookup_input.date()
        if isinstance(lookup_input, date_type):
            return lookup_input
        raise TypeError(f"Unsupported lookup date type: {type(lookup_input)}")

    def get_rate(self, currency: str, lookup_input) -> Optional[float]:
        """
        Get quote_ccy -> USD rate for a given date.
        Returns None if data unavailable (caller should use YAML fallback).
        """
        if currency == "USD":
            return 1.0

        dates = self._dates.get(currency)
        series = self._series.get(currency)
        if dates is None or series is None:
            return None

        lookup_date = self._normalize_lookup_date(lookup_input)

        # Bisect to find nearest date <= lookup_date
        idx = bisect.bisect_right(dates, lookup_date) - 1
        if idx < 0:
            idx = 0  # Use earliest available
        return series[idx][1]


# Tracks symbols already warned about static fallback — prevents per-trade log spam.
_STATIC_FALLBACK_WARNED: set = set()


def get_usd_per_price_unit_dynamic(
    contract_size: float,
    quote_ccy: str,
    entry_timestamp,
    conv_lookup: ConversionLookup,
    static_fallback: float,
    symbol: str,
) -> Tuple[float, str]:
    """
    Compute usd_per_price_unit_per_lot dynamically at entry time.

    Formula: contract_size * quote_ccy_to_USD_rate

    Returns (value, source) where source is 'DYNAMIC' or 'STATIC_FALLBACK'.
    """
    rate = conv_lookup.get_rate(quote_ccy, entry_timestamp)
    if rate is not None:
        return contract_size * rate, "DYNAMIC"
    else:
        if symbol not in _STATIC_FALLBACK_WARNED:
            _STATIC_FALLBACK_WARNED.add(symbol)
            print(
                f"[WARN] STATIC_FALLBACK  symbol={symbol}  quote_ccy={quote_ccy}"
                f"  live_rate=unavailable  using static={static_fallback:.6f}"
                f"  — PnL and heat-cap calculations may be inaccurate"
            )
        return static_fallback, "STATIC_FALLBACK"
