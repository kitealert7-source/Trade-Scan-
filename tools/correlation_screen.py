"""correlation_screen.py — pair-pair screener over FX_CORRELATION_MATRIX.

For a given as-of date and entry band, ranks pair-pair combinations by
how persistently they sat inside the band over a preceding lookback
window. Used to honestly select basket candidates for backtests
without lookahead bias.

Used by
-------
- Walk-forward validation harness (manual orchestration today;
  auto-orchestrator deferred).
- Operator at any time to inspect "what would the screener pick today
  if I had to enter a new basket."

CLI
---
    # Default: as-of latest matrix bar, 30-day lookback, top-10, 1H tf
    python tools/correlation_screen.py

    # Walk-forward: screen as-of 2020-05-17 for top-3 candidates
    python tools/correlation_screen.py \\
        --as-of 2020-05-17 \\
        --top 3 \\
        --persistence-days 30

    # Stricter band, 4H timeframe, top-5
    python tools/correlation_screen.py \\
        --timeframe 4h \\
        --band -0.60 -0.30 \\
        --top 5

Output format
-------------
Table with one row per ranked pair-pair:
    rank | pair_A | pair_B | pct_in_band | rho_as_of | mean_rho

Honest-as-of rule
-----------------
The screener restricts the matrix to rows with index ≤ as-of date
BEFORE computing the percentage. No data from after as-of can influence
the ranking — this is the lookahead-bias defense for backtest selection.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.path_authority import DATA_ROOT


_MATRIX_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_CORRELATION_MATRIX"


def screen(
    as_of: pd.Timestamp,
    *,
    timeframe: str = "1h",
    entry_low: float = -0.70,
    entry_high: float = -0.20,
    persistence_days: int = 30,
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank pair-pairs by % of last `persistence_days` inside entry band
    using ONLY data ≤ as_of.

    Returns a DataFrame with columns: pair (e.g. 'AUDUSD_GBPNZD'),
    pct_in_band, rho_as_of, mean_rho. Sorted descending by pct_in_band.
    """
    matrix_path = _MATRIX_DIR / f"fx_correlation_{timeframe}.parquet"
    if not matrix_path.is_file():
        raise FileNotFoundError(
            f"correlation matrix missing at {matrix_path}. "
            f"Run: python -m tools.factors.fx_correlation_matrix"
        )
    df = pd.read_parquet(matrix_path)

    # Honest as-of filter: drop everything after the as-of date.
    df = df.loc[df.index <= as_of]
    if df.empty:
        raise ValueError(
            f"No matrix data on/before as_of={as_of}. "
            f"Earliest matrix bar: {df.index.min() if len(df) else 'n/a'}"
        )

    # Window: last `persistence_days` bars at this TF.
    bars_per_day = {"1h": 24, "4h": 6}.get(timeframe, 24)
    window_bars = persistence_days * bars_per_day
    recent = df.tail(window_bars)
    if len(recent) < window_bars // 2:
        print(f"[WARN] only {len(recent)} bars available for window "
              f"(requested {window_bars}); ranking may be unreliable")

    in_band = (recent >= entry_low) & (recent <= entry_high)
    pct_in_band = in_band.mean(axis=0) * 100
    mean_rho = recent.mean(axis=0) * 100
    rho_asof = df.iloc[-1] * 100

    out = pd.DataFrame({
        "pair": [c.replace("corr_", "") for c in pct_in_band.index],
        "pct_in_band": pct_in_band.values,
        "rho_as_of": rho_asof.reindex(pct_in_band.index).values,
        "mean_rho": mean_rho.values,
    })
    out = out.dropna(subset=["pct_in_band"])
    out = out.sort_values("pct_in_band", ascending=False).head(top_n).reset_index(drop=True)
    out.index = out.index + 1   # 1-based rank
    out.index.name = "rank"
    return out


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Honest as-of screener over the FX correlation matrix."
    )
    p.add_argument("--as-of", type=str, default=None,
                   help="ISO date (YYYY-MM-DD) cutoff. Default: latest matrix bar.")
    p.add_argument("--timeframe", type=str, default="1h", choices=("1h", "4h"),
                   help="Matrix timeframe to screen on (default 1h).")
    p.add_argument("--band", type=float, nargs=2, default=[-0.70, -0.20],
                   metavar=("LOW", "HIGH"),
                   help="Entry band [low, high] for the rho value (default -0.70 -0.20).")
    p.add_argument("--persistence-days", type=int, default=30,
                   help="Lookback window in days for the 'in-band' percentage (default 30).")
    p.add_argument("--top", type=int, default=10,
                   help="Number of top candidates to display (default 10).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    matrix_path = _MATRIX_DIR / f"fx_correlation_{args.timeframe}.parquet"
    if args.as_of:
        as_of = pd.Timestamp(args.as_of)
    else:
        df_full = pd.read_parquet(matrix_path)
        as_of = df_full.index.max()
        print(f"[screener] as_of not specified; using latest matrix bar: {as_of}")

    df = screen(
        as_of=as_of,
        timeframe=args.timeframe,
        entry_low=args.band[0],
        entry_high=args.band[1],
        persistence_days=args.persistence_days,
        top_n=args.top,
    )

    print(f"\nTop {len(df)} pair-pairs by % in band [{args.band[0]:.2f}, {args.band[1]:.2f}]")
    print(f"As-of: {as_of}  TF: {args.timeframe}  Lookback: {args.persistence_days}d")
    print("-" * 70)
    print(f"{'rank':>4}  {'pair':<22} {'% in band':>10}  {'rho as-of':>10}  {'mean rho':>10}")
    for rank, row in df.iterrows():
        print(f"{rank:>4}  {row['pair']:<22} {row['pct_in_band']:>9.1f}%  "
              f"{row['rho_as_of']:>+9.1f}%  {row['mean_rho']:>+9.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
