"""cointegration_state.py — runtime cointegration-feature lookup.

Reads the historical cointegration matrix produced by
`tools/cointegration_history_matrix.py` and exposes per-bar features
(qualified, daily_z, beta, spread mean/std, ADF p-values) keyed by
(date, pair_a, pair_b).

At backtest time, the basket data loader uses this module to join
cointegration features into each leg's 15m DataFrame, so the strategy
sees columns like `leg_df.qualified` and `leg_df.daily_z` alongside
price. The qualification is daily-cadence; sub-daily bars within a
session see the forward-filled value of the most recent CLOSED daily
bar — preserving the no-look-ahead invariant.

API:
    resolve_latest_hash()                       -> str
    load_history_matrix(matrix_hash=None)       -> pd.DataFrame
    get_pair_features(matrix, pair_a, pair_b,
                       target_index, *, ffill)  -> pd.DataFrame
    list_available_hashes()                     -> list[str]

The module intentionally provides primitives rather than a single
end-to-end function — basket_data_loader chooses when to load the
matrix (once per backtest run) and how to project it onto leg dfs.

Versioning:
    matrix_hash=None  -> reads LATEST pointer (current build)
    matrix_hash="..." -> pins to a specific historical build for
                          reproducibility (a backtest directive that
                          records its matrix_hash can be re-run weeks
                          later against the same hash and produce
                          bit-identical results)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import DATA_ROOT


MATRIX_DIR = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION"
LATEST_POINTER = MATRIX_DIR / "coint_1d_history_matrix_LATEST.json"

# Columns exposed by get_pair_features (after pair selection).
# `date` is dropped because it becomes the output index.
FEATURE_COLUMNS = [
    "beta", "spread_mean", "spread_std",
    "daily_z", "adf_p_252", "adf_p_504", "qualified",
]

# In-process cache of loaded matrices keyed by hash. Matrices are
# ~12 MB each — a small cache amortizes repeated reads cheaply.
_MATRIX_CACHE: dict[str, pd.DataFrame] = {}


# ---------------------------------------------------------------------------
# Hash resolution
# ---------------------------------------------------------------------------


def resolve_latest_hash() -> str:
    """Read the LATEST pointer JSON and return the current matrix hash.

    Raises FileNotFoundError if no matrix has been built (operator must
    run `tools/cointegration_history_matrix.py` first).
    """
    if not LATEST_POINTER.exists():
        raise FileNotFoundError(
            f"LATEST pointer not found at {LATEST_POINTER}. "
            f"Build a matrix first: python tools/cointegration_history_matrix.py"
        )
    return json.loads(LATEST_POINTER.read_text(encoding="utf-8"))["matrix_hash"]


def list_available_hashes() -> list[str]:
    """List all hash IDs of matrices currently on disk."""
    out: list[str] = []
    for p in sorted(MATRIX_DIR.glob("coint_1d_history_matrix_*.parquet")):
        stem = p.stem  # coint_1d_history_matrix_<HASH>
        h = stem.rsplit("_", 1)[-1]
        if h and h != "LATEST":
            out.append(h)
    return out


def hash_to_parquet_path(matrix_hash: str) -> Path:
    return MATRIX_DIR / f"coint_1d_history_matrix_{matrix_hash}.parquet"


def hash_to_manifest_path(matrix_hash: str) -> Path:
    return MATRIX_DIR / f"coint_1d_history_matrix_{matrix_hash}.manifest.json"


# ---------------------------------------------------------------------------
# Matrix load
# ---------------------------------------------------------------------------


def load_history_matrix(matrix_hash: str | None = None) -> pd.DataFrame:
    """Load the cointegration history matrix by hash.

    `matrix_hash=None` reads the LATEST pointer (most-recent build).
    Cached in-process; subsequent calls with same hash are free.

    Returns DataFrame with columns:
      date (datetime64[ns]), pair_a, pair_b, beta, spread_mean,
      spread_std, daily_z, adf_p_252, adf_p_504, qualified
    """
    if matrix_hash is None:
        matrix_hash = resolve_latest_hash()

    if matrix_hash in _MATRIX_CACHE:
        return _MATRIX_CACHE[matrix_hash]

    p = hash_to_parquet_path(matrix_hash)
    if not p.exists():
        raise FileNotFoundError(
            f"matrix not found at {p}. "
            f"Available hashes: {list_available_hashes()}"
        )
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    _MATRIX_CACHE[matrix_hash] = df
    return df


def clear_cache() -> None:
    """Drop the in-process matrix cache (forces reload). Mostly for tests."""
    _MATRIX_CACHE.clear()


# ---------------------------------------------------------------------------
# Per-pair feature extraction + projection onto target index
# ---------------------------------------------------------------------------


def get_pair_features(
    matrix: pd.DataFrame,
    pair_a: str,
    pair_b: str,
    target_index: pd.DatetimeIndex,
    *,
    ffill: bool = True,
) -> pd.DataFrame:
    """Extract per-bar cointegration features for (pair_a, pair_b) and
    reindex onto `target_index`.

    Pair lookup canonicalizes alphabetically (the matrix stores each
    unordered pair-pair once, with legs sorted), so callers can pass
    pairs in any order.

    `target_index` is typically a 15m DatetimeIndex from the leg df.
    With `ffill=True` (default), each 15m bar gets the most-recent
    closed daily bar's values — the standard no-look-ahead daily→15m
    projection.

    Returns DataFrame indexed by `target_index` with columns:
      beta, spread_mean, spread_std, daily_z,
      adf_p_252, adf_p_504, qualified
    """
    a, b = sorted([pair_a, pair_b])
    sub = matrix.loc[(matrix["pair_a"] == a) & (matrix["pair_b"] == b)]
    if sub.empty:
        raise KeyError(
            f"pair {a}/{b} not in matrix "
            f"(matrix has {matrix.groupby(['pair_a','pair_b']).ngroups} pair-pairs)"
        )
    sub = sub.set_index("date")[FEATURE_COLUMNS].sort_index().copy()

    # Convert qualified bool→float8 BEFORE reindex so the NaN that
    # reindex introduces lands in a float column (cleanly fillable to
    # 0.0). Bool→object→fillna(False) path triggers a pandas
    # FutureWarning we don't want in production logs.
    sub["qualified"] = sub["qualified"].astype("float32")

    if ffill:
        # Standard daily->intraday projection: each target bar inherits
        # the most recent <= bar daily value.
        out = sub.reindex(target_index, method="ffill")
    else:
        out = sub.reindex(target_index)

    # Cast qualified back to bool, mapping NaN (pre-matrix dates) to False.
    out["qualified"] = out["qualified"].fillna(0.0).astype("bool")
    return out
