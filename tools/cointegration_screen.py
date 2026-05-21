"""cointegration_screen.py — Phase 1: compute → parquet.

Daily-cadence cointegration screener for the 21-symbol cross-asset
universe (18 FX pairs + XAU/BTC/ETH added 2026-05-21).
Reads native daily closes from MASTER_DATA, computes ADF / half-life /
hedge-ratio / z-score per unordered pair-pair × lookback window, and
writes a single parquet snapshot.

Per COINTEGRATION_SCREENER_V1_SPEC.md §6. Phase 1 scope is ONLY the
parquet write — SQLite + Excel + scheduled task come in later phases.

Outputs:
    DATA_ROOT / SYSTEM_FACTORS / FX_COINTEGRATION / coint_1d_latest.parquet
    DATA_ROOT / SYSTEM_FACTORS / FX_COINTEGRATION / metadata.json

CLI:
    python tools/cointegration_screen.py                  # use latest data
    python tools/cointegration_screen.py --as-of 2026-05-19

Reproducibility:
    Running with the same MASTER_DATA snapshot and the same code commit
    produces a bit-identical parquet (modulo the `generated_at` column).
    The `data_version` column captures input identity for audit.

Phase 1 simplifications (lifted in later phases):
  * `pvalue_rolling_median_5d` is always NaN — needs SQLite history (P2).
  * `regime` uses the bootstrap classifier (current p-value only) —
    hysteresis-aware classifier needs SQLite history (P2).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller

from config.path_authority import DATA_ROOT
# Private import is intentional (per spec §V1 "for v1 just call it directly");
# TODO v1.1: lift _load_native_closes into a shared tools/factors/_loaders.py.
from tools.factors.fx_correlation_matrix import _load_native_closes, FX_UNIVERSE


# Cross-asset cointegration universe (2026-05-21).
# Starts from the 18-pair FX universe + adds XAUUSD/BTCUSD/ETHUSD so the
# screener can detect cross-asset cointegrations (e.g., commodity-currency
# blocks, USD-anchored crypto, gold/risk-asset spreads). The cointegration
# math is symbol-agnostic — same OLS+ADF compute applies. ETHUSD has only
# ~2.5 years of daily history; the 504d window will yield reduced sample
# size on ETH pairings (screener already handles via the
# `sample_size < lookback // 2` reject path).
COINT_UNIVERSE: list[str] = list(FX_UNIVERSE) + ["XAUUSD", "BTCUSD", "ETHUSD"]


SCHEMA_VERSION = "1.0.0"
TF = "1d"
LOOKBACK_WINDOWS = (252, 504)  # 1y, 2y
BETA_METHOD = "ols_static"
TEST_METHOD = "adf"

OUTPUT_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION"
PARQUET_PATH = OUTPUT_DIR / "coint_1d_latest.parquet"
METADATA_PATH = OUTPUT_DIR / "metadata.json"
SINGLES_PARQUET_PATH = OUTPUT_DIR / "singles_1d_latest.parquet"
SINGLES_METADATA_PATH = OUTPUT_DIR / "singles_metadata.json"

# Columns in canonical order (matches spec §5a). Locked here so any
# accidental reorder fails the byte-identity test in Phase 1.
PARQUET_COLUMNS = [
    "pair_a", "pair_b", "tf", "lookback_days",
    "window_start", "window_end", "sample_size",
    "adf_pvalue", "pvalue_rolling_median_5d", "adf_statistic",
    "half_life_days", "hedge_ratio", "beta_method", "test_method",
    "current_zscore", "regime",
    "data_version", "generated_at",
]

# Single-series mean-reversion candidates parquet schema. `symbol` may be
# either a direct broker symbol (e.g., "AUDNZD") or a synthetic series tag
# (e.g., "RATIO:BTCUSD/ETHUSD") computed from two symbols' close ratio.
SINGLES_PARQUET_COLUMNS = [
    "symbol", "tf", "lookback_days",
    "window_start", "window_end", "sample_size",
    "adf_pvalue", "pvalue_rolling_median_5d", "adf_statistic",
    "half_life_days", "current_zscore", "regime",
    "data_version", "generated_at",
]


# ---------------------------------------------------------------------------
# Per-pair compute
# ---------------------------------------------------------------------------


def compute_pair_stats(close_a: pd.Series, close_b: pd.Series,
                       lookback: int) -> dict | None:
    """Compute cointegration stats for one (A, B) pair over `lookback` bars.

    Returns a dict of stats, or None if too few aligned bars to compute.

    Both inputs are pandas Series of closes (indexed by timestamp).
    Series are aligned on inner-join index, last `lookback` bars taken.
    """
    aligned = pd.concat([close_a, close_b], axis=1, join="inner").dropna()
    aligned.columns = ["a", "b"]
    aligned = aligned.tail(lookback)

    sample_size = len(aligned)
    # Reject if fewer than half the requested bars survived alignment.
    if sample_size < lookback // 2 or sample_size < 30:
        return None

    a_vals = aligned["a"].values
    b_vals = aligned["b"].values

    # --- OLS hedge ratio: B = α + β·A + ε
    X = sm.add_constant(a_vals)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ols = sm.OLS(b_vals, X).fit()
    alpha = float(ols.params[0])
    beta = float(ols.params[1])
    spread = b_vals - beta * a_vals

    # --- ADF test on the spread
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf_result = adfuller(spread, autolag="AIC")
        adf_statistic = float(adf_result[0])
        adf_pvalue = float(adf_result[1])
    except Exception:
        adf_statistic = float("nan")
        adf_pvalue = 1.0  # treat compute failure as fully non-stationary

    # --- Half-life via OU fit: Δs_t = λ · s_{t-1} + ε
    spread_series = pd.Series(spread, index=aligned.index)
    delta = spread_series.diff().dropna()
    prev = spread_series.shift(1).dropna().loc[delta.index]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            X_ou = sm.add_constant(prev.values)
            ou_fit = sm.OLS(delta.values, X_ou).fit()
        lambda_ = float(ou_fit.params[1])
        if lambda_ < 0:
            half_life_days = float(-math.log(2) / lambda_)
        else:
            half_life_days = float("nan")
    except Exception:
        half_life_days = float("nan")

    # --- Current spread z-score (in-sample σ)
    spread_mean = float(np.mean(spread))
    spread_std = float(np.std(spread, ddof=1))
    current_zscore = float((spread[-1] - spread_mean) / spread_std) if spread_std > 0 else float("nan")

    # --- Bootstrap regime classifier (current p-value only; Phase 1).
    # Phase 2 will overwrite this with the hysteresis-aware variant
    # using SQLite history.
    if adf_pvalue < 0.05:
        regime = "cointegrated"
    elif adf_pvalue < 0.10:
        regime = "breaking"
    else:
        regime = "broken"

    return {
        "sample_size": sample_size,
        "window_start": aligned.index[0],
        "window_end": aligned.index[-1],
        "adf_pvalue": adf_pvalue,
        "adf_statistic": adf_statistic,
        "half_life_days": half_life_days,
        "hedge_ratio": beta,
        "current_zscore": current_zscore,
        "regime": regime,
    }


# ---------------------------------------------------------------------------
# Per-symbol compute (single-pair mean-reversion candidates)
# ---------------------------------------------------------------------------


def compute_single_series_adf(close: pd.Series, lookback: int) -> dict | None:
    """Compute mean-reversion stats for ONE series's log-price over `lookback` bars.

    Returns dict with adf_pvalue, half_life_days, current_zscore, regime, or
    None if too few bars survived the alignment.

    Unlike compute_pair_stats (which does OLS on two series + ADF on residual),
    this is direct ADF on log(close). Log-space is used so z-scores and
    half-lives are comparable across symbols with very different price levels
    (e.g., XAU ~3500 vs EURUSD ~1.05).
    """
    series = close.dropna().tail(lookback)
    sample_size = len(series)
    # Reject if fewer than half the requested bars or below absolute floor.
    if sample_size < lookback // 2 or sample_size < 30:
        return None

    log_close = np.log(series.values)

    # --- ADF on log-price
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf_result = adfuller(log_close, autolag="AIC")
        adf_statistic = float(adf_result[0])
        adf_pvalue = float(adf_result[1])
    except Exception:
        adf_statistic = float("nan")
        adf_pvalue = 1.0

    # --- Half-life via OU fit on log-price: Δs_t = λ · s_{t-1} + ε
    s = pd.Series(log_close, index=series.index)
    delta = s.diff().dropna()
    prev = s.shift(1).dropna().loc[delta.index]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            X_ou = sm.add_constant(prev.values)
            ou_fit = sm.OLS(delta.values, X_ou).fit()
        lambda_ = float(ou_fit.params[1])
        if lambda_ < 0:
            half_life_days = float(-math.log(2) / lambda_)
        else:
            half_life_days = float("nan")
    except Exception:
        half_life_days = float("nan")

    # --- Current log-price z-score (in-sample σ)
    log_mean = float(np.mean(log_close))
    log_std = float(np.std(log_close, ddof=1))
    current_zscore = (
        float((log_close[-1] - log_mean) / log_std) if log_std > 0 else float("nan")
    )

    # --- Same bootstrap classifier as pair-pair (current p-value only).
    if adf_pvalue < 0.05:
        regime = "cointegrated"   # naming kept for cross-table consistency
    elif adf_pvalue < 0.10:
        regime = "breaking"
    else:
        regime = "broken"

    return {
        "sample_size": sample_size,
        "window_start": series.index[0],
        "window_end": series.index[-1],
        "adf_pvalue": adf_pvalue,
        "adf_statistic": adf_statistic,
        "half_life_days": half_life_days,
        "current_zscore": current_zscore,
        "regime": regime,
    }


def compute_synthetic_log_ratio(
    close_a: pd.Series, close_b: pd.Series, lookback: int,
) -> dict | None:
    """ADF on log(close_a / close_b) — synthetic ratio series.

    Used for candidates like BTC/ETH ratio where the underlying broker symbol
    doesn't exist but the ratio is the structural mean-reversion candidate.
    Equivalent to ADF on log(close_a) − log(close_b), i.e. testing whether
    the two log-prices are cointegrated with β=1 specifically (not OLS-fitted).
    """
    aligned = pd.concat([close_a, close_b], axis=1, join="inner").dropna()
    aligned.columns = ["a", "b"]
    aligned = aligned.tail(lookback)
    if len(aligned) < lookback // 2 or len(aligned) < 30:
        return None
    ratio = aligned["a"] / aligned["b"]
    return compute_single_series_adf(ratio, lookback)


# ---------------------------------------------------------------------------
# Data versioning
# ---------------------------------------------------------------------------


def compute_data_version(universe: list[str], as_of: pd.Timestamp | None) -> str:
    """Hash of the input MASTER_DATA state (file paths + mtimes + as_of).

    12-char SHA-256 prefix; collisions are functionally impossible for
    this universe size. Lets us detect silent historical rewrites: same
    code + same data_version => bit-identical compute.
    """
    parts: list[str] = [f"as_of={as_of.isoformat() if as_of is not None else 'latest'}"]
    for sym in sorted(universe):
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        for f in sorted(research.glob(f"{sym}_OCTAFX_{TF}_*_RESEARCH.csv")):
            parts.append(f"{f.name}={int(f.stat().st_mtime)}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(as_of: pd.Timestamp | None = None,
        universe: list[str] | None = None,
        windows: tuple[int, ...] = LOOKBACK_WINDOWS,
        ) -> pd.DataFrame:
    """Compute the full 153 × len(windows) matrix and return DataFrame.

    Does NOT write to disk; caller writes via `write_parquet()`. This
    split is intentional so unit tests can verify compute without
    needing write access.
    """
    universe = list(universe) if universe is not None else list(COINT_UNIVERSE)

    # Load all daily closes once (much faster than reloading per pair).
    closes: dict[str, pd.Series] = {}
    for sym in universe:
        closes[sym] = _load_native_closes(sym, TF, start=None, end=as_of)

    data_version = compute_data_version(universe, as_of)
    generated_at = pd.Timestamp.now(tz="UTC")

    rows: list[dict] = []
    for sym_a, sym_b in itertools.combinations(sorted(universe), 2):
        for lookback in windows:
            stats = compute_pair_stats(closes[sym_a], closes[sym_b], lookback)
            if stats is None:
                # Record a "broken" placeholder row so the universe is
                # complete in the snapshot even when alignment fails.
                rows.append({
                    "pair_a": sym_a, "pair_b": sym_b,
                    "tf": TF, "lookback_days": lookback,
                    "window_start": pd.NaT, "window_end": pd.NaT,
                    "sample_size": 0,
                    "adf_pvalue": 1.0,
                    "pvalue_rolling_median_5d": float("nan"),
                    "adf_statistic": float("nan"),
                    "half_life_days": float("nan"),
                    "hedge_ratio": float("nan"),
                    "beta_method": BETA_METHOD,
                    "test_method": TEST_METHOD,
                    "current_zscore": float("nan"),
                    "regime": "broken",
                    "data_version": data_version,
                    "generated_at": generated_at,
                })
                continue
            rows.append({
                "pair_a": sym_a, "pair_b": sym_b,
                "tf": TF, "lookback_days": lookback,
                "window_start": stats["window_start"],
                "window_end": stats["window_end"],
                "sample_size": stats["sample_size"],
                "adf_pvalue": stats["adf_pvalue"],
                "pvalue_rolling_median_5d": float("nan"),  # Phase 2 backfill
                "adf_statistic": stats["adf_statistic"],
                "half_life_days": stats["half_life_days"],
                "hedge_ratio": stats["hedge_ratio"],
                "beta_method": BETA_METHOD,
                "test_method": TEST_METHOD,
                "current_zscore": stats["current_zscore"],
                "regime": stats["regime"],
                "data_version": data_version,
                "generated_at": generated_at,
            })

    df = pd.DataFrame(rows, columns=PARQUET_COLUMNS)
    # Cast to spec dtypes (float32 for stats, int32 for counts).
    df = df.astype({
        "lookback_days": "int32",
        "sample_size": "int32",
        "adf_pvalue": "float32",
        "pvalue_rolling_median_5d": "float32",
        "adf_statistic": "float32",
        "half_life_days": "float32",
        "hedge_ratio": "float32",
        "current_zscore": "float32",
    })
    return df


def write_parquet(df: pd.DataFrame, path: Path = PARQUET_PATH) -> None:
    """Write the compute result and a metadata.json companion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)

    meta = {
        "schema_version": SCHEMA_VERSION,
        "tf": TF,
        "lookback_windows": list(LOOKBACK_WINDOWS),
        "universe": list(COINT_UNIVERSE),
        "n_pairs": len(COINT_UNIVERSE),
        "n_pair_pairs": len(list(itertools.combinations(COINT_UNIVERSE, 2))),
        "rows_written": len(df),
        "data_version": df["data_version"].iloc[0] if len(df) else None,
        "generated_at": (
            df["generated_at"].iloc[0].isoformat() if len(df) else None
        ),
        "phase": "v1-phase1",
        "notes": (
            "Phase 1: regime uses bootstrap classifier (current p-value only); "
            "pvalue_rolling_median_5d is NaN until Phase 2 (SQLite history)."
        ),
    }
    METADATA_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Single-series orchestrator (mean-reversion candidates)
# ---------------------------------------------------------------------------


def run_singles(
    as_of: pd.Timestamp | None = None,
    universe: list[str] | None = None,
    windows: tuple[int, ...] = LOOKBACK_WINDOWS,
    synthetic_specs: list[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Compute single-series ADF for each symbol in `universe`, plus optional
    synthetic ratio series.

    `synthetic_specs` is a list of (sym_a, sym_b) tuples; the screener emits a
    row with `symbol=f"RATIO:{sym_a}/{sym_b}"` for each, computed via
    `compute_synthetic_log_ratio` (ADF on close_a / close_b ratio, β=1 fixed).

    Returns DataFrame in canonical column order, with float32/int32 dtypes.
    """
    universe = list(universe) if universe is not None else list(COINT_UNIVERSE)
    synthetic_specs = list(synthetic_specs) if synthetic_specs else []

    closes: dict[str, pd.Series] = {}
    needed = set(universe)
    for a, b in synthetic_specs:
        needed.add(a)
        needed.add(b)
    for sym in sorted(needed):
        closes[sym] = _load_native_closes(sym, TF, start=None, end=as_of)

    data_version = compute_data_version(sorted(needed), as_of)
    generated_at = pd.Timestamp.now(tz="UTC")

    rows: list[dict] = []
    placeholder_template = {
        "tf": TF,
        "window_start": pd.NaT, "window_end": pd.NaT,
        "sample_size": 0,
        "adf_pvalue": 1.0,
        "pvalue_rolling_median_5d": float("nan"),
        "adf_statistic": float("nan"),
        "half_life_days": float("nan"),
        "current_zscore": float("nan"),
        "regime": "broken",
        "data_version": data_version,
        "generated_at": generated_at,
    }
    for sym in sorted(universe):
        for lookback in windows:
            stats = compute_single_series_adf(closes[sym], lookback)
            if stats is None:
                rows.append({
                    "symbol": sym, "lookback_days": lookback,
                    **placeholder_template,
                })
                continue
            rows.append({
                "symbol": sym, "lookback_days": lookback,
                "tf": TF,
                "window_start": stats["window_start"],
                "window_end": stats["window_end"],
                "sample_size": stats["sample_size"],
                "adf_pvalue": stats["adf_pvalue"],
                "pvalue_rolling_median_5d": float("nan"),
                "adf_statistic": stats["adf_statistic"],
                "half_life_days": stats["half_life_days"],
                "current_zscore": stats["current_zscore"],
                "regime": stats["regime"],
                "data_version": data_version,
                "generated_at": generated_at,
            })
    for a, b in synthetic_specs:
        for lookback in windows:
            stats = compute_synthetic_log_ratio(closes[a], closes[b], lookback)
            tag = f"RATIO:{a}/{b}"
            if stats is None:
                rows.append({
                    "symbol": tag, "lookback_days": lookback,
                    **placeholder_template,
                })
                continue
            rows.append({
                "symbol": tag, "lookback_days": lookback,
                "tf": TF,
                "window_start": stats["window_start"],
                "window_end": stats["window_end"],
                "sample_size": stats["sample_size"],
                "adf_pvalue": stats["adf_pvalue"],
                "pvalue_rolling_median_5d": float("nan"),
                "adf_statistic": stats["adf_statistic"],
                "half_life_days": stats["half_life_days"],
                "current_zscore": stats["current_zscore"],
                "regime": stats["regime"],
                "data_version": data_version,
                "generated_at": generated_at,
            })

    df = pd.DataFrame(rows, columns=SINGLES_PARQUET_COLUMNS)
    df = df.astype({
        "lookback_days": "int32",
        "sample_size": "int32",
        "adf_pvalue": "float32",
        "pvalue_rolling_median_5d": "float32",
        "adf_statistic": "float32",
        "half_life_days": "float32",
        "current_zscore": "float32",
    })
    return df


def write_singles_parquet(df: pd.DataFrame, path: Path = SINGLES_PARQUET_PATH) -> None:
    """Write singles compute result + companion metadata json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "tf": TF,
        "lookback_windows": list(LOOKBACK_WINDOWS),
        "rows_written": len(df),
        "n_distinct_symbols": int(df["symbol"].nunique()) if len(df) else 0,
        "data_version": df["data_version"].iloc[0] if len(df) else None,
        "generated_at": (
            df["generated_at"].iloc[0].isoformat() if len(df) else None
        ),
        "phase": "v1-phase1-singles",
        "notes": (
            "Single-series ADF on log-price (and log-ratio for synthetic specs). "
            "Hypothesis-led — candidates are chosen with structural rationale, "
            "not data-mined."
        ),
    }
    SINGLES_METADATA_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cointegration screener — Phase 1 compute → parquet."
    )
    p.add_argument("--as-of", type=str, default=None,
                   help="ISO date (YYYY-MM-DD) cutoff. Default: latest data.")
    p.add_argument("--no-write", action="store_true",
                   help="Compute only; do not write parquet (debug).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    as_of = pd.Timestamp(args.as_of) if args.as_of else None

    print(f"[cointegration_screen] universe={len(COINT_UNIVERSE)} symbols "
          f"windows={LOOKBACK_WINDOWS} as_of={as_of}")
    t0 = datetime.now(timezone.utc)
    df = run(as_of=as_of)
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"[cointegration_screen] pair-pair: {len(df)} rows in {elapsed:.1f}s")

    # Singles: ADF on each symbol's log-price + the BTC/ETH synthetic ratio.
    # Synthetic specs are explicit here (matches the curated candidates list);
    # the daily runner picks these up via the same main() invocation.
    t1 = datetime.now(timezone.utc)
    synthetic_specs = [("BTCUSD", "ETHUSD")]
    df_singles = run_singles(as_of=as_of, synthetic_specs=synthetic_specs)
    elapsed_singles = (datetime.now(timezone.utc) - t1).total_seconds()
    print(f"[cointegration_screen] singles : {len(df_singles)} rows in {elapsed_singles:.1f}s")

    if args.no_write:
        print("[cointegration_screen] --no-write: skipping parquet writes")
    else:
        write_parquet(df)
        write_singles_parquet(df_singles)
        print(f"[cointegration_screen] wrote {PARQUET_PATH}")
        print(f"[cointegration_screen] wrote {SINGLES_PARQUET_PATH}")

    # Quick summary
    regime_counts = df["regime"].value_counts().to_dict()
    singles_regime_counts = df_singles["regime"].value_counts().to_dict()
    print(f"[cointegration_screen] pair-pair regimes: {regime_counts}")
    print(f"[cointegration_screen] singles regimes  : {singles_regime_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
