"""fx_correlation_matrix.py — offline rolling-correlation matrix generator.

For each ordered pair of FX symbols in the universe, compute the rolling
Pearson correlation of log returns at 1H and 4H native timeframes and
write the result to:

    DATA_ROOT / SYSTEM_FACTORS / FX_CORRELATION_MATRIX / fx_correlation_1h.parquet
    DATA_ROOT / SYSTEM_FACTORS / FX_CORRELATION_MATRIX / fx_correlation_4h.parquet

Layout: timestamp-indexed DataFrame with one column per UNORDERED pair-pair
named ``corr_<A>_<B>`` (alphabetically sorted leg symbols, deterministic
regardless of input order).

Architectural role mirrors USD_SYNTH (tools/usd_synth_factor_pipeline.py):
one-shot batch compute over historical native data, written to a shared
SYSTEM_FACTORS file, then consumed by basket_data_loader at runtime via
ffill join into each leg's working df. Reusable infrastructure — any
future strategy that needs leg-pair correlation features pulls from the
same matrix.

CLI
---
    # Default: full backfill over the available history.
    python -m tools.factors.fx_correlation_matrix

    # Restrict to a window.
    python -m tools.factors.fx_correlation_matrix \\
        --start 2024-01-01 --end 2026-05-14

Conventions
-----------
- Symbol universe is the union of USD-anchored pairs and the cross-pair
  set we have 5m/1h/4h data for. Hardcoded list at module top; if data
  is added later just append.
- Native 1H and 4H bars from the broker (DO NOT resample from 5m — adds
  interpolation artifacts and slows compute). Native availability
  confirmed for all 18 pairs in data_root/freshness_index.json.
- Rolling window default 200 bars (~8.3 days at 1H, ~33 days at 4H).
  Sized to be slow enough that the correlation isn't dominated by
  noise but fast enough to react to genuine regime change.

References
----------
- Plan: backtest_directives/hypotheses/H3_TREND_FOLLOW_V1.yaml +
  session brief 2026-05-17.
- Pearson indicator: indicators.stats.pearson_correlation.
- Consumed by: tools.basket_data_loader (Phase 2), tools.recycle_rules.h2_recycle_v5
  correlation gate (Phase 3), tools.correlation_screen (Phase 4).
"""
from __future__ import annotations

import argparse
import itertools
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from config.path_authority import DATA_ROOT
from indicators.stats.pearson_correlation import pearson_correlation


# Universe of FX pairs to cover. Order doesn't matter for correlation
# (corr(A,B) == corr(B,A)); the output column naming is alphabetical
# on the leg symbols so the result is deterministic.
FX_UNIVERSE: list[str] = [
    # USD-anchored pairs (7)
    "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD",
    "USDCAD", "USDCHF", "USDJPY",
    # Cross-pairs (11)
    "AUDJPY", "AUDNZD", "CADJPY", "CHFJPY",
    "EURAUD", "EURGBP", "EURJPY",
    "GBPAUD", "GBPJPY", "GBPNZD", "NZDJPY",
]

# Timeframes to process. Each maps to the filename token under
# MASTER_DATA/<SYMBOL>_OCTAFX_MASTER/RESEARCH/.
TIMEFRAMES: list[str] = ["1h", "4h"]

# Rolling window for the Pearson correlation, in bars of the timeframe.
# 200 bars ~ 8.3 days at 1H, 33 days at 4H — both span the multi-day
# horizon that an operator's chart-reading effectively integrates over.
DEFAULT_WINDOW = 200

# Output directory mirrors USD_SYNTH's layout under SYSTEM_FACTORS.
OUTPUT_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_CORRELATION_MATRIX"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _research_dir(symbol: str) -> Path:
    return DATA_ROOT / "MASTER_DATA" / f"{symbol}_OCTAFX_MASTER" / "RESEARCH"


@lru_cache(maxsize=128)
def _load_full_history(symbol: str, tf: str) -> pd.Series:
    """Internal: load + concat + dedupe + sort the FULL (symbol, tf) close series.

    Cached per process (lru_cache, key=(symbol, tf)). First call pays the disk
    I/O (glob year-files, pd.read_csv each, concat, dedupe, sort, astype). All
    subsequent calls within the same process return the cached Series without
    re-reading disk. Date filtering is NOT done here — that happens in
    `_load_native_closes` on read so the cache is reusable across windows.

    Cache scope is process-local. Each ProcessPoolExecutor worker maintains its
    own cache because workers are separate processes (Windows spawn). At BC4
    scale (~150 tasks per worker), this amortizes ~31 symbols × ~7 year-files
    into a single load per (symbol, tf) per worker, vs the previous ~500k
    redundant loads across the full backfill.

    For tests: call `_load_full_history.cache_clear()` to reset between runs.
    Cache hit/miss visible via `_load_full_history.cache_info()`.
    """
    research = _research_dir(symbol)
    if not research.is_dir():
        raise FileNotFoundError(
            f"fx_correlation_matrix: research dir missing for {symbol}: {research}"
        )
    pattern = f"{symbol}_OCTAFX_{tf}_*_RESEARCH.csv"
    files = sorted(research.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"fx_correlation_matrix: no {tf} files for {symbol} matching "
            f"{pattern} under {research}"
        )
    frames: list[pd.DataFrame] = []
    for f in files:
        df = pd.read_csv(f, comment="#", usecols=["time", "close"])
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    full["time"] = pd.to_datetime(full["time"])
    full = full.drop_duplicates(subset=["time"]).set_index("time").sort_index()
    return full["close"].astype(float).rename(symbol)


def _load_native_closes(symbol: str, tf: str,
                        start: pd.Timestamp | None,
                        end: pd.Timestamp | None) -> pd.Series:
    """Load all year-files for ``symbol`` at ``tf`` and return a single
    close-price series indexed by timestamp, filtered to [start, end].

    Backed by a process-local LRU cache (`_load_full_history`) keyed on
    (symbol, tf). First call per key pays the disk I/O; subsequent calls
    return the cached full Series sliced by [start, end]. Slicing via boolean
    indexing produces a new Series (copy semantics), so callers cannot mutate
    the cache via the returned object. When both `start` and `end` are None,
    a defensive `.copy()` is returned to preserve cache isolation against
    callers that might mutate in place.

    Public signature and return value are unchanged from the pre-cache
    implementation. Byte-equivalent results expected.
    """
    series = _load_full_history(symbol, tf)
    if start is None and end is None:
        return series.copy()
    if start is not None:
        series = series.loc[series.index >= start]
    if end is not None:
        series = series.loc[series.index <= end]
    return series


# ---------------------------------------------------------------------------
# Matrix build
# ---------------------------------------------------------------------------


def _pair_col_name(sym_a: str, sym_b: str) -> str:
    """Alphabetically sorted column name so corr(A,B) and corr(B,A) collide."""
    a, b = sorted([sym_a, sym_b])
    return f"corr_{a}_{b}"


def build_matrix(timeframe: str,
                 *,
                 window: int = DEFAULT_WINDOW,
                 start: pd.Timestamp | None = None,
                 end: pd.Timestamp | None = None,
                 ) -> pd.DataFrame:
    """Compute the full rolling-correlation matrix for one timeframe.

    Returns a DataFrame indexed by timestamp with one column per
    unordered pair-pair: ``corr_<A>_<B>`` (alphabetical).

    Strategy:
      1. Load all close series for ``timeframe`` and align on the
         intersection index (so rolling windows are bar-aligned).
      2. For each unordered pair-pair, compute rolling Pearson on log
         returns via ``pearson_correlation``.
      3. Concatenate into a single wide DataFrame.

    The intersection-index alignment costs a little data (early years
    of pairs with shorter history are clipped to the latest 'first_date'
    across the universe) but ensures the rolling window for every
    pair-pair sees the same bars — same warmup, same NaN region.
    """
    # Load close series for all symbols at this TF.
    series: dict[str, pd.Series] = {}
    for sym in FX_UNIVERSE:
        s = _load_native_closes(sym, timeframe, start, end)
        if s.empty:
            raise RuntimeError(
                f"fx_correlation_matrix: empty series for {sym} {timeframe}"
            )
        series[sym] = s

    # 2026-05-17: switched from GLOBAL intersection to PER-PAIR intersection.
    # Rationale: broker history depth varies by symbol (e.g. OctaFX 1H has
    # AUDJPY/EURJPY/etc. back to 2010 but NZDUSD/USDCAD/USDCHF only to
    # 2024). Global intersection clips the whole matrix to the shallowest
    # symbol. Per-pair intersection lets pair-pairs of two deep symbols
    # use their full shared history while still gracefully NaN-ing the
    # bars where one leg is absent. Output master index = UNION of all
    # symbol indices; each pair-pair column is NaN outside its own
    # intersection.
    master_index = None
    for s in series.values():
        master_index = s.index if master_index is None else master_index.union(s.index)
    if master_index is None or len(master_index) == 0:
        raise RuntimeError(
            f"fx_correlation_matrix: empty union index across {len(series)} symbols"
        )

    cols: dict[str, pd.Series] = {}
    for sym_a, sym_b in itertools.combinations(sorted(FX_UNIVERSE), 2):
        pair_idx = series[sym_a].index.intersection(series[sym_b].index)
        if len(pair_idx) < window:
            # Not enough joint history for any rolling correlation; skip.
            cols[_pair_col_name(sym_a, sym_b)] = pd.Series(
                index=master_index, dtype=float
            )
            continue
        s_a = series[sym_a].reindex(pair_idx)
        s_b = series[sym_b].reindex(pair_idx)
        corr_pair = pearson_correlation(s_a, s_b, window=window)
        # Reindex onto master (NaN outside pair's joint history).
        cols[_pair_col_name(sym_a, sym_b)] = corr_pair.reindex(master_index)

    out = pd.DataFrame(cols, index=master_index).sort_index()
    out.index.name = "time"
    return out


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate the FX rolling-correlation matrix at 1H and 4H."
    )
    p.add_argument("--start", type=str, default=None,
                   help="Optional ISO date (YYYY-MM-DD) lower-bound on the source data window.")
    p.add_argument("--end", type=str, default=None,
                   help="Optional ISO date (YYYY-MM-DD) upper-bound on the source data window.")
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                   help=f"Rolling window length in bars of each TF (default {DEFAULT_WINDOW}).")
    p.add_argument("--timeframes", type=str, nargs="+", default=TIMEFRAMES,
                   help=f"Timeframes to build (default: {TIMEFRAMES}).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    start = pd.Timestamp(args.start) if args.start else None
    end = pd.Timestamp(args.end) if args.end else None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for tf in args.timeframes:
        print(f"[fx-correlation] Building {tf} matrix (window={args.window} bars)...")
        df = build_matrix(tf, window=args.window, start=start, end=end)
        n_cols = len(df.columns)
        n_rows = len(df)
        valid_rows = int(df.dropna(how="all").shape[0])
        out_path = OUTPUT_DIR / f"fx_correlation_{tf}.parquet"
        df.to_parquet(out_path)
        first = df.index.min()
        last = df.index.max()
        print(f"  -> wrote {out_path}")
        print(f"     rows={n_rows}  valid_rows={valid_rows}  cols={n_cols}")
        print(f"     range: {first} -> {last}")

    # Metadata file mirrors USD_SYNTH convention.
    import json
    meta = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "window_bars": args.window,
        "timeframes": list(args.timeframes),
        "universe": FX_UNIVERSE,
        "n_pairs": len(FX_UNIVERSE),
        "n_pair_pairs": len(FX_UNIVERSE) * (len(FX_UNIVERSE) - 1) // 2,
        "column_naming": "corr_<A>_<B>  (legs alphabetically sorted)",
        "value_range": "[-1.0, 1.0]; NaN during warmup or missing data",
        "consumed_by": [
            "tools.basket_data_loader (runtime join into leg dfs)",
            "tools.recycle_rules.h2_recycle_v5 (correlation gate)",
            "tools.correlation_screen (operator screener CLI)",
        ],
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[fx-correlation] metadata.json -> {OUTPUT_DIR / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
