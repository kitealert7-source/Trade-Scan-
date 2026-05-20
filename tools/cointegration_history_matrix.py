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
TF = "1d"
HEDGE_WINDOW = 252
ADF_WINDOW_SHORT = 252
ADF_WINDOW_LONG = 504
ADF_SAMPLE_EVERY = 21
ADF_LAG_BARS = 1
P_QUALIFY = 0.05
SCHEMA_VERSION = "1.0.0"

OUTPUT_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION"
LATEST_POINTER = OUTPUT_DIR / "coint_1d_history_matrix_LATEST.json"

MATRIX_COLUMNS = [
    "date", "pair_a", "pair_b",
    "beta", "spread_mean", "spread_std",
    "daily_z", "adf_p_252", "adf_p_504", "qualified",
]


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} | {msg}", flush=True)


# --- Versioning --------------------------------------------------------


def current_params() -> dict:
    """The parameter set baked into this matrix. Frozen at module level."""
    return {
        "tf": TF,
        "hedge_window": HEDGE_WINDOW,
        "adf_window_short": ADF_WINDOW_SHORT,
        "adf_window_long": ADF_WINDOW_LONG,
        "adf_sample_every": ADF_SAMPLE_EVERY,
        "adf_lag_bars": ADF_LAG_BARS,
        "p_qualify": P_QUALIFY,
        "schema_version": SCHEMA_VERSION,
    }


def compute_version_hash(universe: list[str], params: dict) -> str:
    """SHA-256 of (params + universe + per-symbol CSV mtimes). 12-char hex.

    Provides content-addressable naming:
      same inputs   → same hash → reuse existing artifact (no rebuild)
      different inputs → different hash → new artifact (old preserved)
    """
    parts: list[str] = [
        f"params={json.dumps(params, sort_keys=True)}",
        f"universe={sorted(universe)}",
    ]
    for sym in sorted(universe):
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        files = sorted(research.glob(f"{sym}_OCTAFX_{TF}_*_RESEARCH.csv"))
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


def _compute_pair_history(close_a: pd.Series, close_b: pd.Series) -> pd.DataFrame:
    """Per-bar β, spread, z, ADF p-values for one (a, b) pair."""
    mean_a = close_a.rolling(HEDGE_WINDOW).mean()
    mean_b = close_b.rolling(HEDGE_WINDOW).mean()
    cov_ab = (close_a * close_b).rolling(HEDGE_WINDOW).mean() - mean_a * mean_b
    var_a = close_a.rolling(HEDGE_WINDOW).var(ddof=0)
    beta = cov_ab / var_a
    spread = close_b - beta * close_a
    sp_mean = spread.rolling(HEDGE_WINDOW).mean()
    sp_std = spread.rolling(HEDGE_WINDOW).std(ddof=0)
    z = (spread - sp_mean) / sp_std

    adf_short = _compute_adf_anchors(spread, ADF_WINDOW_SHORT)
    adf_long = _compute_adf_anchors(spread, ADF_WINDOW_LONG)
    qualified = ((adf_short < P_QUALIFY) & (adf_long < P_QUALIFY)).fillna(False)

    return pd.DataFrame({
        "beta": beta.astype("float32"),
        "spread_mean": sp_mean.astype("float32"),
        "spread_std": sp_std.astype("float32"),
        "daily_z": z.astype("float32"),
        "adf_p_252": adf_short.astype("float32"),
        "adf_p_504": adf_long.astype("float32"),
        "qualified": qualified.astype("bool"),
    })


# --- Top-level matrix build --------------------------------------------


def load_aligned_closes(universe: list[str]) -> pd.DataFrame:
    closes = {sym: _load_native_closes(sym, TF, None, None) for sym in universe}
    df = pd.concat(closes, axis=1, join="inner").dropna()
    df.columns = list(closes.keys())
    return df


def build_matrix(closes: pd.DataFrame) -> pd.DataFrame:
    """Compute the full history matrix. Pure compute, no I/O."""
    pairs = list(itertools.combinations(sorted(closes.columns), 2))
    frames: list[pd.DataFrame] = []
    t0 = time.time()
    for i, (sa, sb) in enumerate(pairs):
        ph = _compute_pair_history(closes[sa], closes[sb])
        ph = ph.reset_index().rename(columns={"index": "date", closes.index.name or "index": "date"})
        # The reset_index column name varies; force it to "date":
        if "date" not in ph.columns:
            first_col = ph.columns[0]
            ph = ph.rename(columns={first_col: "date"})
        ph["pair_a"] = sa
        ph["pair_b"] = sb
        frames.append(ph[MATRIX_COLUMNS])
        if (i + 1) % 20 == 0 or (i + 1) == len(pairs):
            _log(f"  pair {i+1}/{len(pairs)}  ({sa}/{sb})  elapsed={time.time()-t0:.1f}s")
    return pd.concat(frames, ignore_index=True)


# --- Artifact write (with versioning discipline) -----------------------


def _enumerate_csv_files(universe: list[str]) -> list[dict]:
    out = []
    for sym in sorted(universe):
        research = DATA_ROOT / "MASTER_DATA" / f"{sym}_OCTAFX_MASTER" / "RESEARCH"
        for f in sorted(research.glob(f"{sym}_OCTAFX_{TF}_*_RESEARCH.csv")):
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
            "rows_with_valid_adf_252": int(matrix["adf_p_252"].notna().sum()),
            "rows_with_valid_adf_504": int(matrix["adf_p_504"].notna().sum()),
        },
        "source_csv_files": csv_files,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/cointegration_history_matrix.py",
    }


def write_artifact(matrix: pd.DataFrame, manifest: dict,
                    matrix_hash: str, *, force: bool = False
                    ) -> tuple[Path, Path]:
    """Write parquet + manifest. NEVER OVERWRITES unless force=True.

    Returns (parquet_path, manifest_path).
    Raises FileExistsError if the hash collision means the artifact
    already exists (and force=False).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"coint_1d_history_matrix_{matrix_hash}.parquet"
    manifest_path = OUTPUT_DIR / f"coint_1d_history_matrix_{matrix_hash}.manifest.json"

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
                            manifest_path: Path) -> None:
    """The LATEST pointer IS allowed to be overwritten — it just records
    the most-recently-built hash for downstream tools that want 'current'.
    The hashed parquets + manifests remain immutable."""
    pointer = {
        "matrix_hash": matrix_hash,
        "parquet_file": parquet_path.name,
        "manifest_file": manifest_path.name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    LATEST_POINTER.write_text(json.dumps(pointer, indent=2), encoding="utf-8")


# --- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--force", action="store_true",
                   help="Force rebuild even if hash matches an existing artifact "
                        "(destroys reproducibility for directives pinned to that hash).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print hash + params + estimated cost; do not compute or write.")
    args = p.parse_args(argv)

    universe = list(FX_UNIVERSE)
    params = current_params()
    matrix_hash = compute_version_hash(universe, params)

    _log(f"params:        {json.dumps(params, sort_keys=True)}")
    _log(f"universe:      {len(universe)} symbols")
    _log(f"matrix_hash:   {matrix_hash}")
    _log(f"target dir:    {OUTPUT_DIR}")

    parquet_path = OUTPUT_DIR / f"coint_1d_history_matrix_{matrix_hash}.parquet"
    manifest_path = OUTPUT_DIR / f"coint_1d_history_matrix_{matrix_hash}.manifest.json"

    if args.dry_run:
        _log(f"DRY RUN — would write to {parquet_path.name}")
        return 0

    if parquet_path.exists() and not args.force:
        _log(f"SKIP — artifact {parquet_path.name} already exists "
             f"(identical hash; use --force to override).")
        update_latest_pointer(matrix_hash, parquet_path, manifest_path)
        _log(f"updated LATEST pointer -> {matrix_hash}")
        return 0

    _log("loading closes...")
    closes = load_aligned_closes(universe)
    _log(f"closes: {len(closes)} bars  {closes.index[0].date()} → {closes.index[-1].date()}")

    _log("building matrix (≈4-5 min for full 14-yr sweep)...")
    t0 = time.time()
    matrix = build_matrix(closes)
    _log(f"matrix built: {len(matrix):,} rows in {time.time()-t0:.1f}s")

    csv_files = _enumerate_csv_files(universe)
    manifest = build_manifest(matrix_hash, params, universe, closes, matrix, csv_files)

    parquet_path, manifest_path = write_artifact(matrix, manifest, matrix_hash, force=args.force)
    update_latest_pointer(matrix_hash, parquet_path, manifest_path)

    _log(f"wrote {parquet_path}  ({parquet_path.stat().st_size / 1024 / 1024:.1f} MB)")
    _log(f"wrote {manifest_path}")
    _log(f"updated LATEST pointer -> {matrix_hash}")
    _log(f"qualified rows: {manifest['matrix_stats']['qualified_rows']:,} / "
         f"{manifest['matrix_stats']['total_rows']:,} "
         f"({manifest['matrix_stats']['qualified_pct']*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
