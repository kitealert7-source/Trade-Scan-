"""trade_candidates_view.py -- the pair-level decision-support shortlist for
the MPS "COINT TRADE CANDIDATES" tab.

Where cointegration_view.py projects the run-grain detail (one row per
backtest), this projects to PAIR grain: one row per (pair_a, pair_b),
answering a single operator question -- "after thousands of backtests, which
handful of pairs should I focus research or capital on next?"

Design (operator-locked 2026-06-02):
- Qualification gate: a pair needs >= MIN_QUALIFYING_RUNS runs to appear at
  all. Below that there isn't enough evidence to call it a candidate -- a
  1-run "perfect" pair is universe-explorer noise, not a trade candidate. This
  is the ONE gate consistent with an append-only ledger: a thin pair is not
  excluded forever, it GRADUATES IN as it accumulates runs (the opposite of
  the retired all_profitable cliff). The complete universe stays on the
  detailed Cointegration tab.
- Criterion is reliability-under-exposure, NOT perfection. The retired gate
  `all_profitable` ("never lost") is demoted to a badge so a heavily-tested
  near-perfect pair (e.g. 24 runs / 2 losses) stays VISIBLE instead of being
  banished forever for a single loss -- the append-only consequence of being
  tested more.
- Append-only-friendly: as runs accumulate, a pair drifts DOWN the ranking if
  its robustness genuinely decays -- it never falls off a binary cliff, and no
  pair vanishes from the list because of a single future loss.
- Display and sort are deliberately DIFFERENT. `Losses` is shown as a raw
  COUNT (a human reads "24 runs, 2 losses" instantly); the SORT uses loss_rate
  so exposure is normalised (24/2 and 12/1 are the same 8% quality).

Columns (display): Pair | Coint Status (252d) | Runs | Losses | Median Ret/DD
  - Pair: "pair_a / pair_b", badge-prefixed for zero-loss pairs.
  - Coint Status (252d): current screener regime (cointegrated / breaking /
    broken) for the pair from cointegration_daily's 252-day window -- the source
    behind the screener's "All Pairs (Diagnostic)" sheet. Injected via
    `regime_map`; blank if the pair is not in the current screen. A current-state
    proxy under the standard 252d screen, NOT the per-pair continuous-
    cointegration window each candidate was actually backtested on.
  - Runs: total current runs (every parameter variant and test window).
  - Losses: count of runs with canonical_net_pct <= 0 (break-even is a loss).
  - Median Ret/DD: median canonical_ret_dd over ALL runs (incl. losers);
    median, not mean, so one outlier run cannot dominate.

Sort (descending desirability): loss_rate asc -> median Ret/DD desc -> runs
desc. Rationale: the runs>=5 gate already certifies "enough evidence", so once
loss_rate ties, QUALITY (median) leads and runs is only the final tiebreak -- a
clean 6-run/3.9-Ret/DD pair should rank above a clean 12-run/1.0 one for a
"what to investigate next" shortlist. Pure transform; no Excel, unit-testable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Zero-loss "never lost yet" achievement. ASCII escape keeps the source file
# pure-ASCII (Windows-1252 read safety / encoding lint); renders as the medal
# emoji in the xlsx cell.
BADGE = "\U0001F3C5"

TRADE_CANDIDATES_COLUMNS = [
    "Pair", "Coint Status (252d)", "Runs", "Evaluable", "Losses", "Median Ret/DD",
]

# Qualification gate: a pair needs at least this many current runs to qualify
# as a trade candidate. Below it there isn't enough evidence (a 1-run "perfect"
# pair is universe-explorer noise). Tunable; the full universe lives on the
# Cointegration tab regardless.
MIN_QUALIFYING_RUNS = 5


def build_trade_candidates_df(
    df_raw: pd.DataFrame,
    regime_map: dict | None = None,
) -> pd.DataFrame:
    """Project run-grain cointegration rows to the pair-level shortlist.

    One row per (pair_a, pair_b). See the module docstring for the criterion.
    Caller is responsible for passing the desired row scope (the MPS export
    passes is_current=1 rows).

    `regime_map` (optional): {(pair_a, pair_b): regime} for the "Coint Status
    (252d)" column, sourced from the daily screener (cointegration_db
    .latest_regime_map). Keys are the same canonical (pair_a, pair_b)
    orientation as the candidate rows. A pair absent from the map renders blank;
    regime_map=None (no screener data supplied) leaves the whole column blank.
    Pure transform either way -- the caller owns the cross-DB read."""
    if df_raw is None or len(df_raw) == 0:
        return pd.DataFrame(columns=TRADE_CANDIDATES_COLUMNS)

    needed = {"pair_a", "pair_b", "canonical_net_pct"}
    if not needed.issubset(df_raw.columns):
        return pd.DataFrame(columns=TRADE_CANDIDATES_COLUMNS)

    df = df_raw.copy()
    net = pd.to_numeric(df["canonical_net_pct"], errors="coerce")
    df["_loss"] = ~(net > 0)  # NaN and break-even (<= 0) both count as a loss
    if "canonical_ret_dd" in df.columns:
        df["_rdd"] = pd.to_numeric(
            df["canonical_ret_dd"], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
    else:
        df["_rdd"] = np.nan

    # Evaluable run = completed >= 1 strategy cycle (a real reversion exit), vs a
    # "phantom" run that entered, never reverted, and was force-closed at the
    # window boundary (DATA_END) -- those carry an inflated Ret/DD on a near-zero
    # realized drawdown. Rank QUALITY (median Ret/DD) over evaluable runs ONLY, so
    # phantom runs cannot prop a pair up the shortlist; a pair with zero evaluable
    # runs gets median = NaN and sorts last.
    if "cycles_completed" in df.columns:
        df["_eval"] = pd.to_numeric(df["cycles_completed"], errors="coerce").fillna(0) >= 1
    else:
        df["_eval"] = True  # no cycle data -> legacy behaviour (all evaluable)
    df["_rdd_eval"] = df["_rdd"].where(df["_eval"])

    agg = df.groupby(["pair_a", "pair_b"], dropna=False).agg(
        runs=("_loss", "size"),
        losses=("_loss", "sum"),
        evaluable=("_eval", "sum"),
        median_ret_dd=("_rdd_eval", "median"),
    ).reset_index()

    # Qualification gate: drop under-tested pairs -- not enough evidence to be a
    # candidate yet. The full universe remains on the Cointegration tab.
    agg = agg[agg["runs"] >= MIN_QUALIFYING_RUNS].reset_index(drop=True)
    if agg.empty:
        return pd.DataFrame(columns=TRADE_CANDIDATES_COLUMNS)

    agg["loss_rate"] = agg["losses"] / agg["runs"]
    agg = agg.sort_values(
        by=["loss_rate", "median_ret_dd", "runs"],
        ascending=[True, False, False],
        kind="mergesort",  # stable: deterministic order on exact ties
        na_position="last",
    ).reset_index(drop=True)

    pair = agg["pair_a"].astype(str) + " / " + agg["pair_b"].astype(str)
    # Badge-prefix the zero-loss pairs only.
    pair = pair.mask(agg["losses"] == 0, BADGE + " " + pair)

    # Current 252d screener regime per pair, looked up from the injected map
    # (same canonical (pair_a, pair_b) key orientation). Pairs not in the
    # current screen -> blank, per the operator-chosen no-match rendering;
    # regime_map=None -> the whole column blank (no screener data supplied).
    if regime_map:
        status = [
            regime_map.get((str(a), str(b)), "")
            for a, b in zip(agg["pair_a"], agg["pair_b"])
        ]
    else:
        status = [""] * len(agg)

    return pd.DataFrame({
        "Pair": pair,
        "Coint Status (252d)": status,
        "Runs": agg["runs"].astype(int),
        "Evaluable": agg["evaluable"].astype(int),  # runs with >=1 real strategy cycle
        "Losses": agg["losses"].astype(int),
        "Median Ret/DD": agg["median_ret_dd"].round(2),
    })[TRADE_CANDIDATES_COLUMNS]


__all__ = [
    "TRADE_CANDIDATES_COLUMNS",
    "MIN_QUALIFYING_RUNS",
    "BADGE",
    "build_trade_candidates_df",
]
