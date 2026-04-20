"""
News calendar loader for the News Policy Impact report section.

Reads RESEARCH-layer news calendar CSVs from
data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/,
builds blackout windows, and groups by currency.

ALL normalization (timezone conversion, dedup, impact filtering) is done
upstream in the CLEAN layer (DATA_INGRESS build_news_calendar.py).
This module does NO normalization — only parse, validate, build windows.
"""

import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CALENDAR_CACHE: dict = {}


# ---------------------------------------------------------------------------
# Symbol → Currency mapping
# ---------------------------------------------------------------------------

_SYMBOL_CURRENCY_OVERRIDES = {
    "XAUUSD": ["USD"], "XAGUSD": ["USD"],
    "BTCUSD": ["USD"], "ETHUSD": ["USD"],
    "US30": ["USD"], "NAS100": ["USD"], "SPX500": ["USD"],
    "GER40": ["EUR"], "UK100": ["GBP"], "FRA40": ["EUR"],
    "JPN225": ["JPY"], "AUS200": ["AUD"], "ESP35": ["EUR"],
    "EUSTX50": ["EUR"],
}

_KNOWN_CURRENCIES = frozenset({
    "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF",
    "NOK", "SEK", "SGD", "HKD", "CNY", "ZAR", "MXN", "TRY",
})


def derive_currencies(symbol: str) -> list:
    """Derive affected currencies from a trading symbol.

    Resolution order:
      1. Override dict (commodities, crypto, indices)
      2. 6-char FX pair parse (EURUSD → [EUR, USD])
      3. Fallback → [USD] with logged warning
    """
    sym = symbol.upper()
    if sym in _SYMBOL_CURRENCY_OVERRIDES:
        return _SYMBOL_CURRENCY_OVERRIDES[sym]
    if len(sym) == 6:
        base, quote = sym[:3], sym[3:]
        if base in _KNOWN_CURRENCIES and quote in _KNOWN_CURRENCIES:
            return [base, quote]
    print(f"[NEWS-CAL] Cannot derive currencies for '{symbol}', defaulting to USD")
    return ["USD"]


# ---------------------------------------------------------------------------
# RESEARCH-layer calendar loading (NO normalization)
# ---------------------------------------------------------------------------

def _load_research_calendar(calendar_dir: Path):
    """Read RESEARCH-layer news calendar CSVs. No normalization needed.

    RESEARCH data is already:
      - UTC-naive (timezone stripped at CLEAN layer)
      - Deduped on (datetime_utc, currency, event)
      - Impact-validated
      - Sorted chronologically
    """
    if not calendar_dir.exists() or not calendar_dir.is_dir():
        return None
    csv_files = sorted(calendar_dir.glob("*.csv"))
    if not csv_files:
        return None
    frames = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-8")
            if len(df) > 0:
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
                frames.append(df)
        except Exception as e:
            print(f"[NEWS-CAL] Failed to read {f.name}: {e}")
    if not frames:
        return None
    result = pd.concat(frames, ignore_index=True)

    # Runtime guards — catch double-normalization or corrupt RESEARCH data
    assert result['datetime_utc'].dt.tz is None, \
        "RESEARCH datetime_utc must be UTC-naive — timezone attached means double-normalization or corrupt source"
    assert result['datetime_utc'].min().year >= 2000, \
        f"RESEARCH datetime_utc min year {result['datetime_utc'].min().year} < 2000 — likely parse corruption"

    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_calendar(df: pd.DataFrame):
    """Validate schema, drop bad rows. Returns (clean_df, warnings) or (None, warnings)."""
    warnings = []

    for col in ('datetime_utc', 'currency', 'impact'):
        if col not in df.columns:
            # Try capitalized version for backward compatibility
            cap_col = col.capitalize() if col != 'datetime_utc' else col
            if cap_col in df.columns:
                df = df.rename(columns={cap_col: col})
            else:
                return None, [f"Missing required column: '{col}'"]

    df = df.copy()
    df['impact'] = df['impact'].astype(str).str.strip().str.capitalize()
    df['currency'] = df['currency'].astype(str).str.strip().str.upper()
    if 'event' not in df.columns:
        df['event'] = 'Unknown'

    valid_impacts = {'High', 'Medium', 'Low'}
    invalid_mask = ~df['impact'].isin(valid_impacts)
    if invalid_mask.any():
        warnings.append(f"Dropped {invalid_mask.sum()} rows with invalid impact")
        df = df[~invalid_mask]

    before = len(df)
    df = df.drop_duplicates(
        subset=['datetime_utc', 'currency', 'event'], keep='first'
    )
    duped = before - len(df)
    if duped:
        warnings.append(f"Removed {duped} duplicate events")

    if len(df) == 0:
        return None, warnings + ["No valid events after validation"]

    return df, warnings


# ---------------------------------------------------------------------------
# Window construction
# ---------------------------------------------------------------------------

def _build_windows(df: pd.DataFrame, pre_min: int, post_min: int) -> pd.DataFrame:
    """Expand each event into a (window_start, window_end) blackout window."""
    df = df.copy()
    df['window_start'] = df['datetime_utc'] - pd.Timedelta(minutes=pre_min)
    df['window_end'] = df['datetime_utc'] + pd.Timedelta(minutes=post_min)
    return df[['window_start', 'window_end', 'currency', 'event',
               'impact', 'datetime_utc']].copy()


def group_windows_by_currency(windows_df: pd.DataFrame) -> dict:
    """Group and sort windows by currency for efficient per-trade lookup."""
    result = {}
    for ccy, group in windows_df.groupby('currency'):
        result[ccy] = group.sort_values('window_start').reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_news_calendar(calendar_dir: Path, *, pre_min: int = 15,
                       post_min: int = 15, impact_filter: str = "High"):
    """Load, validate, and build news windows from RESEARCH calendar CSVs.

    Returns (windows_df, windows_by_currency) or None if unavailable.
    Result is cached per unique parameter set within the process.
    """
    cache_key = (str(calendar_dir), pre_min, post_min, impact_filter)
    if cache_key in _CALENDAR_CACHE:
        return _CALENDAR_CACHE[cache_key]

    raw = _load_research_calendar(calendar_dir)
    if raw is None:
        _CALENDAR_CACHE[cache_key] = None
        return None

    validated, warnings = _validate_calendar(raw)
    for w in warnings:
        print(f"[NEWS-CAL] {w}")

    if validated is None:
        _CALENDAR_CACHE[cache_key] = None
        return None

    if impact_filter:
        validated = validated[validated['impact'] == impact_filter].copy()
        if len(validated) == 0:
            print(f"[NEWS-CAL] No events remaining after '{impact_filter}' filter")
            _CALENDAR_CACHE[cache_key] = None
            return None

    windows = _build_windows(validated, pre_min, post_min)
    by_ccy = group_windows_by_currency(windows)

    result = (windows, by_ccy)
    _CALENDAR_CACHE[cache_key] = result
    print(f"[NEWS-CAL] Loaded {len(windows)} {impact_filter}-impact event windows")
    return result
