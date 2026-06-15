"""cointegration_view.py -- the lean, human-readable projection of the
cointegration_sheet for the MPS "Cointegration" tab.

The DB keeps every column (rich, future-proof). This module projects the
current rows down to the ~20 columns a human scans, with familiar header
names, the deterministic sort, and a 1-based rank. It is a pure transform
(DataFrame -> DataFrame) so it is unit-testable without Excel.

Renaming headers here is safe (unlike the portfolio sheets): the Cointegration
tab is a ONE-WAY render regenerated from the DB on every export, never re-read
and appended to by a writer -- so there is no canonical-name collision risk.

Sort that produces `rank`: canonical_ret_dd desc, then completed_at_utc desc,
then run_id desc -- stable, so exact-ret_dd ties float the most recent run up.

Filter aids (2026-06-01):
- `pair_class`: 5-way structural taxonomy from the leg symbols. Crypto / Metals
  override on either-leg-match (so BTCUSD/EURUSD lands in Crypto, not Cross).
  Raises ValueError on any unenumerated symbol — the value set is closed.
- `coint_friendly`: STRONG (continuous_span_obs >= 90) / FRIENDLY (>= 30) /
  WEAK (< 30 or NaN). Bands are derived from screener-side gate provenance at
  the run's test_end as-of date — NOT a function of the test-window calendar
  length. The 30-obs cutoff is the B-gate admission threshold; the 90-obs
  cutoff matches the 2026-05-28 cohort-shift survey's STRONG bucket.
- `all_profitable`: per (pair_a, pair_b) pair across ALL its runs — every
  parameter variant (P02/P03, lookbacks) AND every test window — "Yes" iff
  every current row has canonical_net_pct > 0, else "No". Every pair gets a
  verdict (no blanks). Generalises the retired 2-variant `both_profitable`
  check to the N-run reality (median 8 runs/pair, up to 39): a hardcoded
  baseline-vs-zcross pairing silently ignored every run beyond those two.
  Plain English: the pair never had a losing or break-even run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Final display order (== the locked human view; column-budget guard caps this).
# methodology added 2026-05-30 (C4): surfaces the cohort tag so operators can
# tell v1_raw_adf legacy rows apart from v2_log_eg / v2_log_adf post-correction
# rows — the two are NOT comparable head-to-head (different EG vs raw-ADF
# criticals, log vs raw spread). See COINTEGRATION_SCREEN_MATH_V2.md.
# pair_class / coint_friendly added 2026-06-01; all_profitable added 2026-06-02
# (replaced both_profitable — see module docstring): filter aids for cross-run
# robustness screening of the cointegration corpus.
COINTEGRATION_VIEW_COLUMNS = [
    "rank",
    "pair",
    "timeframe",
    "lookback",
    "pair_class",        # filter aid: structural taxonomy
    "coint_friendly",    # filter aid: screener-span band
    "all_profitable",    # filter aid: every run of the pair profitable
    "series",            # filter aid: variant/sizing tag (base, GP, GPN, ZCRS, SZVP, P03, ...)
    "run_date",
    "test_start",
    "test_end",
    "return_dd_ratio",
    "net_pct",
    "realized_net%",     # Σ strategy-cycle PnL / stake — net_pct minus the
                         # unrealized floating + DATA_END boundary tail. 0 when a
                         # run entered but never completed a strategy exit.
    "max drawdown %",
    "final_equity_usd",
    "total_trades",
    "spans",             # fragment_count — number of distinct cointegrated spans/periods in the window
    "cycles",
    "win_rate",
    "regime",
    "methodology",
    "backtest",
]

# Hard cap on the human view (enforcement: the budget test asserts this).
COINTEGRATION_VIEW_BUDGET = 23  # +realized_net% (2026-06-05); +spans/fragment_count (2026-06-15)

# DB column -> friendly display header.
_RENAME = {
    "lookback_days": "lookback",
    "canonical_ret_dd": "return_dd_ratio",
    "canonical_net_pct": "net_pct",
    "realized_net_pct": "realized_net%",
    "canonical_max_dd_pct": "max drawdown %",
    "canonical_final_equity_usd": "final_equity_usd",
    "trades_total": "total_trades",
    "fragment_count": "spans",
    "cycles_completed": "cycles",
    "cycle_win_rate_pct": "win_rate",
    "regime_state": "regime",
    "methodology_version": "methodology",
}

# Sort keys (descending): primary metric, then recency, then a stable tiebreak.
_SORT_KEYS = ["canonical_ret_dd", "completed_at_utc", "run_id"]

# Symbol taxonomy for pair_class. FX includes both majors and crosses (the
# strategy's design target is "FX-vs-FX cointegration" regardless of major-
# ness). Crypto/Metals override on either-leg match so BTCUSD/EURUSD lands in
# Crypto. Any leg not in any set yields Unknown — a silent-expansion canary.
_FX = frozenset({
    "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
    "EURGBP", "EURAUD", "GBPAUD", "GBPNZD",
    "AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "AUDNZD",
})
_IDX = frozenset({
    "AUS200", "ESP35", "EUSTX50", "FRA40", "GER40", "JPN225",
    "NAS100", "SPX500", "UK100", "US30",
})
_CRYPTO = frozenset({"BTCUSD", "ETHUSD"})
_METALS = frozenset({"XAUUSD", "XAGUSD"})

_COINT_STRONG_OBS = 90
_COINT_FRIENDLY_OBS = 30


def _classify_pair(pair_a: str, pair_b: str) -> str:
    """Deterministic 5-way taxonomy from leg symbols. Crypto/Metals override
    on either-leg match. Raises ValueError on any unenumerated symbol — the
    column's value set is closed and silent miscategorization is unacceptable
    (operator preference, 2026-06-01)."""
    a = "" if pair_a is None else str(pair_a)
    b = "" if pair_b is None else str(pair_b)
    if a in _CRYPTO or b in _CRYPTO:
        return "Crypto"
    if a in _METALS or b in _METALS:
        return "Metals"
    if a in _FX and b in _FX:
        return "FX"
    if a in _IDX and b in _IDX:
        return "IDX"
    if (a in _FX and b in _IDX) or (a in _IDX and b in _FX):
        return "Cross"
    raise ValueError(
        f"pair_class: unenumerated symbol(s) in pair ({a!r}, {b!r}). "
        f"Add to _FX / _IDX / _CRYPTO / _METALS in cointegration_view.py."
    )


def _friendly_band(span_obs) -> str:
    """STRONG / FRIENDLY / WEAK from continuous_span_obs. NaN -> WEAK.

    Bands map to existing gate constants:
      - 30 obs = B-gate admission threshold (window_validity_gate)
      - 90 obs = 2026-05-28 cohort-shift survey STRONG bucket (top ~3%)
    """
    n = pd.to_numeric(pd.Series([span_obs]), errors="coerce").iloc[0]
    if pd.isna(n):
        return "WEAK"
    if n >= _COINT_STRONG_OBS:
        return "STRONG"
    if n >= _COINT_FRIENDLY_OBS:
        return "FRIENDLY"
    return "WEAK"


def _classify_series(directive_id) -> str:
    """Variant/series tag for the filter column: the cohort token(s) spliced
    after the _L<lookback> segment of the directive id, up to the run-date
    stamp. Examples:
        '...L30_GP__E240109'    -> 'GP'      (granular-parity sizing arm)
        '...L30_GPN__E240109'   -> 'GPN'     (notional-control arm)
        '...L30_ZCRS__E...'     -> 'ZCRS'    (zero-cross exit variant)
        '...L30_SZVP__E240719'  -> 'SZVP'    (vol-parity sizing arm)
        '...L30_P01_N0__E...'   -> 'P01_N0'  (p-threshold + confirmation cohort)
        '...L30_GP_ZCRS_TF4H__E' -> 'GP_ZCRS_TF4H' (4h cointegration basis; 1d untagged)
        '...L30__E...' / '...L100' -> 'base'

    Lets operators filter the corpus by family -- e.g. exclude the SZVP
    sizing-experiment rows whose profit re-staking yields non-deployable
    compounded returns, or isolate a single exit/sizing variant. The existing
    `lookback` + `methodology` columns disambiguate same-tag rows that differ
    only by lookback or screener version."""
    d = "" if directive_id is None else str(directive_id)
    m = re.search(r"_L\d+((?:_[A-Z0-9]+)*?)(?:__E|$)", d)
    if not m:
        return "?"
    tag = m.group(1)
    return tag.lstrip("_") if tag else "base"


def _add_all_profitable(df: pd.DataFrame) -> pd.DataFrame:
    """Per (pair_a, pair_b) pair across ALL its runs — every parameter variant
    and every test window: "Yes" iff every current row has
    canonical_net_pct > 0, else "No".

    Replaces the retired `both_profitable`, which only compared the baseline
    and zcross variants within a single window. With a median of 8 runs/pair
    today — parameter variants (P02/P03, lookbacks) plus a growing set of
    end-date windows — the 2-variant check ignored every run beyond those two.
    `all_profitable` generalises to whatever N runs exist now or later: a pair
    is "Yes" only if it never produced a losing or break-even run. Every pair
    gets a verdict (no blanks). NaN and 0.0 net both count as not-profitable."""
    needed = {"pair_a", "pair_b", "canonical_net_pct"}
    if not needed.issubset(df.columns):
        df["all_profitable"] = pd.NA
        return df

    net = pd.to_numeric(df["canonical_net_pct"], errors="coerce")
    profitable = net > 0  # NaN and break-even (0.0) are not profitable

    key_cols = ["pair_a", "pair_b"]
    work = pd.DataFrame({
        **{c: df[c] for c in key_cols},
        "profitable": profitable,
    })
    agg = work.groupby(key_cols, dropna=False)["profitable"].all().reset_index()
    agg["all_profitable"] = agg["profitable"].map({True: "Yes", False: "No"})

    merged = df.merge(
        agg[key_cols + ["all_profitable"]],
        on=key_cols, how="left",
    )
    return merged


def build_cointegration_view_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Project raw cointegration_sheet rows to the lean human view (sorted,
    ranked, friendly-named). Pure transform; no I/O."""
    if df_raw is None or len(df_raw) == 0:
        return pd.DataFrame(columns=COINTEGRATION_VIEW_COLUMNS)

    df = df_raw.copy()

    sort_keys = [k for k in _SORT_KEYS if k in df.columns]
    if "canonical_ret_dd" in df.columns:
        df["canonical_ret_dd"] = pd.to_numeric(df["canonical_ret_dd"], errors="coerce")
    if sort_keys:
        df = df.sort_values(
            by=sort_keys,
            ascending=[False] * len(sort_keys),
            kind="mergesort",  # stable: preserves recency tiebreak on exact ret_dd ties
            na_position="last",
        ).reset_index(drop=True)

    # Derived display columns.
    if "pair_a" in df.columns and "pair_b" in df.columns:
        df["pair"] = df["pair_a"].astype(str) + " / " + df["pair_b"].astype(str)
        df["pair_class"] = [
            _classify_pair(a, b) for a, b in zip(df["pair_a"], df["pair_b"])
        ]
    if "continuous_span_obs" in df.columns:
        df["coint_friendly"] = df["continuous_span_obs"].apply(_friendly_band)
    if "backtests_path" in df.columns:
        df["backtest"] = df["backtests_path"].fillna("").apply(
            lambda p: Path(str(p)).name if str(p) else ""
        )
    if "completed_at_utc" in df.columns:
        df["run_date"] = df["completed_at_utc"].fillna("").astype(str).str.slice(0, 10)
    if "directive_id" in df.columns:
        df["series"] = df["directive_id"].apply(_classify_series)

    df = _add_all_profitable(df)

    df = df.rename(columns=_RENAME)
    df.insert(0, "rank", range(1, len(df) + 1))

    cols = [c for c in COINTEGRATION_VIEW_COLUMNS if c in df.columns]
    return df[cols]


__all__ = [
    "COINTEGRATION_VIEW_COLUMNS",
    "COINTEGRATION_VIEW_BUDGET",
    "build_cointegration_view_df",
]
