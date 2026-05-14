"""basket_data_loader.py — load real OHLC + factor data for basket legs.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 5c.

Provides the runtime side of the basket pipeline: reads the per-symbol
multi-year 5m RESEARCH CSVs and joins the daily USD_SYNTH compression_5d
(forward-filled onto the 5m grid). Returned DataFrames are shaped for
direct consumption by `tools.basket_runner.BasketRunner`.

Conventions:
  * 5m CSVs live under DATA_ROOT/MASTER_DATA/<SYMBOL>_OCTAFX_MASTER/
    RESEARCH/<SYMBOL>_OCTAFX_5m_<YYYY>_RESEARCH.csv (header lines start
    with '#' and are skipped).
  * USD_SYNTH features live under DATA_ROOT/SYSTEM_FACTORS/USD_SYNTH/
    usd_synth_compression_d1.csv (column: compression_5d, daily).
  * The compression series is broadcast onto each leg's 5m index by
    forward-fill on the Date.

Returned dict[symbol] -> DataFrame columns:
    ['open', 'high', 'low', 'close', 'volume', 'spread', 'session',
     'commission_cash', 'slippage', 'compression_5d']
with a DatetimeIndex named 'time' and rows filtered to [start_date, end_date].
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config.path_authority import DATA_ROOT


__all__ = [
    "load_basket_leg_data",
    "load_compression_5d_factor",
    "clear_year_file_cache",
]


# ---------------------------------------------------------------------------
# Phase 5b.4 — process-local year-file cache.
#
# Multi-window matrix runs (e.g., h2_parity_run.py --all) often re-load
# the same year-files across windows (window A 2016-2018 and window E
# 2017-2019 both need 2017 + 2018). Caching at the year-file granularity
# means each year-file is parsed once per process. Cleared by
# clear_year_file_cache() if needed (e.g., between independent matrix
# runs in the same long-running session).
#
# Sized for ~10 years × ~10 symbols = 100 unique frames; an OctaFx 5m
# year-file is ~5-7 MB CSV → ~50-100 MB pandas memory. 64-entry cap
# keeps total RAM under 6 GB even in the worst case.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _read_year_csv_cached(symbol: str, year: int) -> pd.DataFrame:
    """Parse one year of 5m bars for one symbol. Cached process-locally.

    Returned DataFrame is the FULL year (no window filter applied) with
    `time` as a DatetimeIndex. Callers slice by date range themselves.
    Returns an EMPTY DataFrame if the year-file is missing — callers
    should treat that as a gap year.
    """
    research_dir = DATA_ROOT / "MASTER_DATA" / f"{symbol}_OCTAFX_MASTER" / "RESEARCH"
    f = research_dir / f"{symbol}_OCTAFX_5m_{year}_RESEARCH.csv"
    if not f.is_file():
        return pd.DataFrame()  # caller treats as gap year
    df = pd.read_csv(f, comment="#", parse_dates=["time"])
    df = df.set_index("time").sort_index()
    return df


def clear_year_file_cache() -> None:
    """Drop all cached year-files. Call between independent multi-window
    runs in the same process if memory matters."""
    _read_year_csv_cached.cache_clear()


# ---------------------------------------------------------------------------
# Factor loader
# ---------------------------------------------------------------------------


def load_compression_5d_factor(start_date: str, end_date: str) -> pd.Series:
    """Read USD_SYNTH compression_5d daily series filtered to the window.

    Returns a Series indexed by daily DatetimeIndex with name 'compression_5d'.
    NaN rows (pre-warm-up) are retained — caller decides how to handle them.

    Lookahead-safe: applies `shift(1)` so the value at date D is the value
    that was originally for date D-1. This matches the convention in
    `tools/research/regime_gate.py::load_feature_series` and
    `indicators/macro/usd_synth_zscore.py`. Without the shift, a 5m bar at
    D 00:05 would read the compression for day D — a value that is not
    actually known until end of day D in real-time. Phase 5d.1 parity run
    discovered this lookahead bias was responsible for pipeline blocking
    via the regime gate ~50% MORE often than the basket_sim reference (in
    declining-compression regimes) and contributing to the TARGET-count
    divergence (pipeline 2/10 vs reference 5/10).
    """
    path = DATA_ROOT / "SYSTEM_FACTORS" / "USD_SYNTH" / "usd_synth_compression_d1.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"USD_SYNTH compression file missing at {path}. "
            "Confirm DATA_INGRESS has populated SYSTEM_FACTORS/USD_SYNTH/."
        )
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    if "compression_5d" not in df.columns:
        raise ValueError(
            f"compression_5d column missing in {path}; found {list(df.columns)}"
        )
    # Lookahead-safe shift on the full daily series BEFORE window filter
    # (shifting after filter would lose the prior-day value at the start
    # of the window).
    series = df["compression_5d"].shift(1)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    series = series[(series.index >= start_ts) & (series.index <= end_ts)]
    series.name = "compression_5d"
    return series


# ---------------------------------------------------------------------------
# Per-symbol 5m loader (multi-year concat)
# ---------------------------------------------------------------------------


def _load_symbol_5m(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Read every RESEARCH 5m CSV year-file for symbol covering the window,
    concat (via cache), filter to [start, end].

    Year-files are cached process-locally via _read_year_csv_cached so
    cross-window matrix runs (e.g., h2_parity_run.py --all) reuse parsed
    frames instead of re-parsing each window.
    """
    research_dir = DATA_ROOT / "MASTER_DATA" / f"{symbol}_OCTAFX_MASTER" / "RESEARCH"
    if not research_dir.is_dir():
        raise FileNotFoundError(
            f"RESEARCH dir missing for {symbol} at {research_dir}. "
            "Confirm DATA_INGRESS has produced the OctaFx 5m series for this symbol."
        )
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    pieces: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        piece = _read_year_csv_cached(symbol, year)
        if piece.empty:
            continue  # gap year — not necessarily fatal; window filter handles edges
        pieces.append(piece)
    if not pieces:
        raise FileNotFoundError(
            f"No 5m RESEARCH files found for {symbol} in window "
            f"{start_year}-{end_year} under {research_dir}."
        )
    df = pd.concat(pieces).sort_index()
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df[(df.index >= start_ts) & (df.index <= end_ts)]
    if df.empty:
        raise ValueError(
            f"After window filter {start_date}..{end_date}, no 5m bars remain "
            f"for {symbol}. Year files were present but bars fall outside the window."
        )
    return df


# ---------------------------------------------------------------------------
# Compose: per-symbol DF + compression_5d column
# ---------------------------------------------------------------------------


def _join_factor_onto_5m(df_5m: pd.DataFrame, factor: pd.Series) -> pd.DataFrame:
    """Forward-fill the daily factor onto the 5m DatetimeIndex of df_5m.

    The factor's daily date stamp aligns to the START of each UTC day, so
    every 5m bar at-or-after that day's 00:00 inherits the day's value
    until the next daily print. NaN rows (pre-warm-up) propagate.
    """
    out = df_5m.copy()
    # Reindex factor onto 5m index via forward-fill.
    out["compression_5d"] = factor.reindex(out.index, method="ffill")
    return out


def load_basket_leg_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """Load per-symbol 5m OHLC + USD_SYNTH compression_5d for a basket.

    Args:
        symbols:    list of leg symbols, e.g. ['EURUSD', 'USDJPY']
        start_date: 'YYYY-MM-DD'
        end_date:   'YYYY-MM-DD'

    Returns:
        dict mapping symbol -> DataFrame indexed by 'time' with columns:
            open, high, low, close, volume, spread, session,
            commission_cash, slippage, compression_5d
    """
    if not symbols:
        raise ValueError("load_basket_leg_data: symbols must be non-empty.")
    # Validate dates are parseable
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    factor = load_compression_5d_factor(start_date, end_date)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df_5m = _load_symbol_5m(sym, start_date, end_date)
        out[sym] = _join_factor_onto_5m(df_5m, factor)
    return out
