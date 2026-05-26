"""cointegration_history_matrix.py — historical state lake pre-compute.

Builds a content-addressable parquet matrix of per-(date, pair_a, pair_b)
cointegration features for the full 14-year FX universe. Consumed at
backtest time by basket_data_loader to inject `daily_z` / `qualified`
into 15m leg dataframes.

VERSIONING DISCIPLINE (frozen per architectural review 2026-05-20):

  Treat each matrix as a versioned, immutable research artifact:
    * hash it          — SHA-256 of (params + CSV files + mtimes); filename
                         encodes the hash so different inputs produce
                         distinct artifacts that coexist on disk.
    * manifest it      — sidecar JSON captures params, universe, source
                         CSV inventory, date range, generated_at,
                         matrix stats, generator commit.
    * freeze per batch — a backtest directive references the matrix by
                         hash. Re-running the directive against the same
                         hash always produces the same trades.
    * never overwrite  — write_artifact() raises FileExistsError if a
                         matrix with the same hash already exists. To
                         force a rebuild, the operator must explicitly
                         delete the old artifact (intentional act).

  A LATEST pointer (coint_1d_history_matrix_LATEST.json) records the
  most recent build, used by downstream tools that want "the latest"
  instead of pinning to a specific hash. The pointer is allowed to be
  overwritten — only the hashed parquets and manifests are immutable.

Output layout (all under data_root/SYSTEM_FACTORS/FX_COINTEGRATION/):

    coint_1d_history_matrix_<HASH12>.parquet         (the matrix)
    coint_1d_history_matrix_<HASH12>.manifest.json   (the manifest)
    coint_1d_history_matrix_LATEST.json              (pointer to current)

Matrix schema (one row per (date, pair_a, pair_b)):

    date          datetime64[ns, UTC]
    pair_a        string  (alphabetically first leg)
    pair_b        string  (alphabetically second leg)
    beta          float32 (rolling OLS hedge ratio over HEDGE_WINDOW)
    spread_mean   float32 (rolling spread mean over HEDGE_WINDOW)
    spread_std    float32 (rolling spread std over HEDGE_WINDOW)
    daily_z       float32 (current spread z-score)
    adf_p_252     float32 (ADF p-value at nearest monthly anchor, 252-bar window)
    adf_p_504     float32 (ADF p-value at nearest monthly anchor, 504-bar window)
    qualified     bool    (both adf_p < P_QUALIFY; forward-filled from last anchor)

CLI:
    python tools/cointegration_history_matrix.py             # build LATEST if hash changed
    python tools/cointegration_history_matrix.py --force     # force rebuild even if hash matches
    python tools/cointegration_history_matrix.py --dry-run   # print hash + params, no compute
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys, "stdout") and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys, "stderr") and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from config.path_authority import DATA_ROOT
from tools.factors.fx_correlation_matrix import FX_UNIVERSE, _load_native_closes


# --- Parameters --------------------------------------------------------
# These MUST match the live screener (cointegration_screen.py) and the
# event study (cointegration_event_study.py) so the historical matrix
# and the live snapshot are computed with identical methodology.
TF = "1d"  # default; per-call override via `tf=...` argument or `--tf` CLI flag
HEDGE_WINDOW = 252
ADF_WINDOW_SHORT = 252
ADF_WINDOW_LONG = 504
ADF_SAMPLE_EVERY = 21
ADF_LAG_BARS = 1
P_QUALIFY = 0.05
SCHEMA_VERSION = "1.0.0"

# Per-TF parameter sets. Calendar-time-matched windows + scaled ADF cadence.
# 1d preserves the legacy values for backward-compat hash equivalence.
PARAMS_BY_TF: dict[str, dict[str, int | float]] = {
    "1d": {
        "hedge_window": 252,
        "adf_window_short": 252,
        "adf_window_long": 504,
        "adf_sample_every": 21,    # ~monthly
        "adf_lag_bars": 1,
        "p_qualify": 0.05,
    },
    "4h": {
        "hedge_window": 1500,       # ~1y in calendar time (24/5 FX, 6 bars/day × 250d)
        "adf_window_short": 1500,
        "adf_window_long": 3000,    # ~2y
        "adf_sample_every": 30,     # ~weekly
        "adf_lag_bars": 1,
        "p_qualify": 0.05,
    },
}
SUPPORTED_TFS: tuple[str, ...] = ("1d", "4h")

OUTPUT_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION"
LATEST_POINTER = OUTPUT_DIR / "coint_1d_history_matrix_LATEST.json"


def latest_pointer_for(tf: str) -> Path:
    return OUTPUT_DIR / f"coint_{tf}_history_matrix_LATEST.json"


def parquet_path_for(tf: str, matrix_hash: str) -> Path:
    return OUTPUT_DIR / f"coint_{tf}_history_matrix_{matrix_hash}.parquet"


def manifest_path_for(tf: str, matrix_hash: str) -> Path:
    return OUTPUT_DIR / f"coint_{tf}_history_matrix_{matrix_hash}.manifest.json"

MATRIX_COLUMNS = [
    "date", "pair_a", "pair_b",
    "beta", "spread_mean", "spread_std",
    "daily_z", "adf_p_252", "adf_p_504", "qualified",
]


def matrix_columns_for(tf: str) -> list[str]:
    """Per-TF matrix schema. Column names encode the lookback bar count
    (adf_p_<short> / adf_p_<long>) so different-TF matrices remain
    self-describing. 1d keeps the legacy `adf_p_252` / `adf_p_504`
    names for consumer backward-compat.
    """
    p = current_params(tf)
    return [
        "date", "pair_a", "pair_b",
        "beta", "spread_mean", "spread_std",
        "daily_z",
        f"adf_p_{p['adf_window_short']}",
        f"adf_p_{p['adf_window_long']}",
        "qualified",
    ]


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}", flush=True)


# --- Versioning --------------------------------------------------------


def current_params(tf: str = TF) -> dict:
    """The parameter set baked into the matrix for `tf`.

    1d returns the legacy values (preserves existing hashes).
    4h returns the calendar-matched, weekly-resample tuning.
    """
    if tf not in PARAMS_BY_TF:
        raise ValueError(f"Unsupported tf: {tf!r}; allowed: {SUPPORTED_TFS}")
    p = dict(PARAMS_BY_TF[tf])
    return {
        "tf": tf,
        **p,
        "schema_version": SCHEMA_VERSION,
    }


def compute_version_hash(universe: list[str], params: dict,
                         tf: str | None = None) -> str:
    """SHA-256 of (params + universe + per-symbol CSV mtimes). 12-char hex.

    Provides content-addressable naming:
      same inputs   → same hash → reuse existing artifact (no rebuild)
      different inputs → different hash → new artifact (old preserved)

    `tf` is read from `params["tf"]` if not passed explicitly; the CSV
    glob uses it to enumerate the right per-TF source files.
    """
    if tf is None:
        tf = params.get("tf", TF)
    parts: list[str] = [
        f"params={json.dumps(params, sort_keys=True)}",
        f"universe={sorted(universe)}",
    ]
    for sym in sorted(universe):
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        files = sorted(research.glob(f"{sym}_OCTAFX_{tf}_*_RESEARCH.csv"))
        for f in files:
            parts.append(f"{f.name}={int(f.stat().st_mtime)}")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


# --- Per-pair compute --------------------------------------------------


def _compute_adf_anchors(spread: pd.Series, anchor_window: int,
                          sample_every: int = ADF_SAMPLE_EVERY,
                          lag_bars: int = ADF_LAG_BARS) -> pd.Series:
    """ADF p-value at monthly anchors, forward-filled then shifted by lag_bars.

    Identical to cointegration_event_study._compute_adf_anchors — kept
    here as a local copy so the matrix script is self-contained.
    """
    valid = spread.dropna()
    if len(valid) < anchor_window:
        return pd.Series(np.nan, index=spread.index)

    pvals: dict[pd.Timestamp, float] = {}
    for end_pos in range(anchor_window - 1, len(valid), sample_every):
        window_data = valid.iloc[end_pos - anchor_window + 1: end_pos + 1].values
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                p = float(adfuller(window_data, autolag="AIC")[1])
        except Exception:
            p = 1.0
        pvals[valid.index[end_pos]] = p

    anchor_series = pd.Series(pvals).sort_index()
    daily = anchor_series.reindex(spread.index, method="ffill")
    return daily.shift(lag_bars)


def _compute_pair_history(close_a: pd.Series, close_b: pd.Series,
                          params: dict | None = None) -> pd.DataFrame:
    """Per-bar β, spread, z, ADF p-values for one (a, b) pair.

    `params` is the per-TF parameter dict from `current_params(tf)`.
    Defaults to 1d params for backward compatibility with the original
    no-arg call signature (preserves existing tests + hash determinism).

    ADF p-value columns are named `adf_p_<bars>` where <bars> is the
    lookback bar count — so 1d has `adf_p_252` / `adf_p_504`, 4h has
    `adf_p_1500` / `adf_p_3000`.
    """
    if params is None:
        params = current_params("1d")
    hedge_window = int(params["hedge_window"])
    adf_short_w = int(params["adf_window_short"])
    adf_long_w = int(params["adf_window_long"])
    adf_sample = int(params["adf_sample_every"])
    adf_lag = int(params["adf_lag_bars"])
    p_qualify = float(params["p_qualify"])

    mean_a = close_a.rolling(hedge_window).mean()
    mean_b = close_b.rolling(hedge_window).mean()
    cov_ab = (close_a * close_b).rolling(hedge_window).mean() - mean_a * mean_b
    var_a = close_a.rolling(hedge_window).var(ddof=0)
    beta = cov_ab / var_a
    spread = close_b - beta * close_a
    sp_mean = spread.rolling(hedge_window).mean()
    sp_std = spread.rolling(hedge_window).std(ddof=0)
    z = (spread - sp_mean) / sp_std

    adf_short = _compute_adf_anchors(spread, adf_short_w,
                                     sample_every=adf_sample, lag_bars=adf_lag)
    adf_long = _compute_adf_anchors(spread, adf_long_w,
                                    sample_every=adf_sample, lag_bars=adf_lag)
    qualified = ((adf_short < p_qualify) & (adf_long < p_qualify)).fillna(False)

    return pd.DataFrame({
        "beta": beta.astype("float32"),
        "spread_mean": sp_mean.astype("float32"),
        "spread_std": sp_std.astype("float32"),
        "daily_z": z.astype("float32"),
        f"adf_p_{adf_short_w}": adf_short.astype("float32"),
        f"adf_p_{adf_long_w}": adf_long.astype("float32"),
        "qualified": qualified.astype("bool"),
    })


# --- Top-level matrix build --------------------------------------------


def load_aligned_closes(universe: list[str], tf: str = TF) -> pd.DataFrame:
    closes = {sym: _load_native_closes(sym, tf, None, None) for sym in universe}
    df = pd.concat(closes, axis=1, join="inner").dropna()
    df.columns = list(closes.keys())
    return df


def build_matrix(closes: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Compute the full history matrix. Pure compute, no I/O.

    `params` is the per-TF parameter dict; defaults to 1d for backward compat.
    """
    if params is None:
        params = current_params("1d")
    tf = str(params.get("tf", "1d"))
    columns = matrix_columns_for(tf)
    pairs = list(itertools.combinations(sorted(closes.columns), 2))
    frames: list[pd.DataFrame] = []
    t0 = time.time()
    for i, (sa, sb) in enumerate(pairs):
        ph = _compute_pair_history(closes[sa], closes[sb], params=params)
        ph = ph.reset_index().rename(columns={"index": "date", closes.index.name or "index": "date"})
        # The reset_index column name varies; force it to "date":
        if "date" not in ph.columns:
            first_col = ph.columns[0]
            ph = ph.rename(columns={first_col: "date"})
        ph["pair_a"] = sa
        ph["pair_b"] = sb
        frames.append(ph[columns])
        if (i + 1) % 20 == 0 or (i + 1) == len(pairs):
            _log(f"  pair {i+1}/{len(pairs)}  ({sa}/{sb})  elapsed={time.time()-t0:.1f}s")
    return pd.concat(frames, ignore_index=True)


# --- Artifact write (with versioning discipline) -----------------------


def _enumerate_csv_files(universe: list[str], tf: str = TF) -> list[dict]:
    out = []
    for sym in sorted(universe):
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        for f in sorted(research.glob(f"{sym}_OCTAFX_{tf}_*_RESEARCH.csv")):
            out.append({
                "symbol": sym,
                "path": str(f.relative_to(DATA_ROOT)),
                "mtime_unix": int(f.stat().st_mtime),
                "size_bytes": f.stat().st_size,
            })
    return out


def build_manifest(matrix_hash: str, params: dict, universe: list[str],
                    closes: pd.DataFrame, matrix: pd.DataFrame,
                    csv_files: list[dict]) -> dict:
    tf = str(params.get("tf", "1d"))
    adf_short_col = f"adf_p_{int(params['adf_window_short'])}"
    adf_long_col = f"adf_p_{int(params['adf_window_long'])}"
    return {
        "schema_version": SCHEMA_VERSION,
        "matrix_hash": matrix_hash,
        "params": params,
        "universe": sorted(universe),
        "universe_n_pairs": len(universe),
        "universe_n_pair_pairs": len(list(itertools.combinations(universe, 2))),
        "date_range": {
            "first": closes.index[0].isoformat(),
            "last": closes.index[-1].isoformat(),
            "bars": int(len(closes)),
        },
        "matrix_stats": {
            "total_rows": int(len(matrix)),
            "qualified_rows": int(matrix["qualified"].sum()),
            "qualified_pct": float(matrix["qualified"].mean()),
            "rows_with_valid_z": int(matrix["daily_z"].notna().sum()),
            f"rows_with_valid_{adf_short_col}": int(matrix[adf_short_col].notna().sum()),
            f"rows_with_valid_{adf_long_col}": int(matrix[adf_long_col].notna().sum()),
        },
        "source_csv_files": csv_files,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/cointegration_history_matrix.py",
    }


def write_artifact(matrix: pd.DataFrame, manifest: dict,
                    matrix_hash: str, *, force: bool = False,
                    tf: str = TF,
                    ) -> tuple[Path, Path]:
    """Write parquet + manifest. NEVER OVERWRITES unless force=True.

    `tf` determines the artifact filename pattern:
      `coint_<tf>_history_matrix_<hash>.parquet/.manifest.json`
    so 1d and 4h matrices coexist in OUTPUT_DIR without collision.

    Returns (parquet_path, manifest_path).
    Raises FileExistsError if the hash collision means the artifact
    already exists (and force=False).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"coint_{tf}_history_matrix_{matrix_hash}.parquet"
    manifest_path = OUTPUT_DIR / f"coint_{tf}_history_matrix_{matrix_hash}.manifest.json"

    if parquet_path.exists() and not force:
        raise FileExistsError(
            f"NEVER OVERWRITE — artifact already exists at {parquet_path.name}. "
            f"A matrix with hash={matrix_hash} was previously built from identical "
            f"inputs. To force a rebuild (intentional act, destroys reproducibility "
            f"for any directive currently pinned to this hash), pass --force or "
            f"delete the parquet+manifest manually."
        )

    matrix.to_parquet(parquet_path, index=False)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return parquet_path, manifest_path


def update_latest_pointer(matrix_hash: str, parquet_path: Path,
                            manifest_path: Path,
                            pointer_path: Path | None = None) -> None:
    """The LATEST pointer IS allowed to be overwritten — it just records
    the most-recently-built hash for downstream tools that want 'current'.
    The hashed parquets + manifests remain immutable.

    `pointer_path` defaults to `LATEST_POINTER` (1d) for backward
    compatibility; pass `latest_pointer_for(tf)` for non-1d TFs.
    """
    if pointer_path is None:
        pointer_path = LATEST_POINTER
    pointer = {
        "matrix_hash": matrix_hash,
        "parquet_file": parquet_path.name,
        "manifest_file": manifest_path.name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    pointer_path.write_text(json.dumps(pointer, indent=2), encoding="utf-8")


# --- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--force", action="store_true",
                   help="Force rebuild even if hash matches an existing artifact "
                        "(destroys reproducibility for directives pinned to that hash).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print hash + params + estimated cost; do not compute or write.")
    p.add_argument("--tf", type=str, default=TF, choices=list(SUPPORTED_TFS),
                   help=f"Timeframe. Default {TF!r}. At 4h: calendar-matched windows "
                        "(1500/3000 bars ≈ 1y/2y), ~weekly ADF resample, FX-only universe.")
    args = p.parse_args(argv)
    tf = args.tf

    universe = list(FX_UNIVERSE)
    params = current_params(tf)
    matrix_hash = compute_version_hash(universe, params, tf=tf)

    _log(f"tf:            {tf}")
    _log(f"params:        {json.dumps(params, sort_keys=True)}")
    _log(f"universe:      {len(universe)} symbols")
    _log(f"matrix_hash:   {matrix_hash}")
    _log(f"target dir:    {OUTPUT_DIR}")

    parquet_path = parquet_path_for(tf, matrix_hash)
    manifest_path = manifest_path_for(tf, matrix_hash)
    pointer_path = latest_pointer_for(tf)

    if args.dry_run:
        _log(f"DRY RUN — would write to {parquet_path.name}")
        return 0

    if parquet_path.exists() and not args.force:
        _log(f"SKIP — artifact {parquet_path.name} already exists "
             f"(identical hash; use --force to override).")
        update_latest_pointer(matrix_hash, parquet_path, manifest_path,
                              pointer_path=pointer_path)
        _log(f"updated LATEST pointer -> {matrix_hash}")
        return 0

    _log("loading closes...")
    closes = load_aligned_closes(universe, tf=tf)
    _log(f"closes: {len(closes)} bars  {closes.index[0].date()} → {closes.index[-1].date()}")

    if tf == "1d":
        _log("building matrix (≈4-5 min for full 14-yr sweep)...")
    else:
        _log(f"building matrix for tf={tf} (compute scales with bar count; expect slower)...")
    t0 = time.time()
    matrix = build_matrix(closes, params=params)
    _log(f"matrix built: {len(matrix):,} rows in {time.time()-t0:.1f}s")

    csv_files = _enumerate_csv_files(universe, tf=tf)
    manifest = build_manifest(matrix_hash, params, universe, closes, matrix, csv_files)

    parquet_path, manifest_path = write_artifact(
        matrix, manifest, matrix_hash, force=args.force, tf=tf,
    )
    update_latest_pointer(matrix_hash, parquet_path, manifest_path,
                          pointer_path=pointer_path)

    _log(f"wrote {parquet_path}  ({parquet_path.stat().st_size / 1024 / 1024:.1f} MB)")
    _log(f"wrote {manifest_path}")
    _log(f"updated LATEST pointer -> {matrix_hash}")
    _log(f"qualified rows: {manifest['matrix_stats']['qualified_rows']:,} / "
         f"{manifest['matrix_stats']['total_rows']:,} "
         f"({manifest['matrix_stats']['qualified_pct']*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
