"""mfe_giveback.py — per-cycle MFE / MAE / give-back analytics.

For each completed cycle in a basket run (one LIQUIDATE_* event per cycle),
compute:
  - MFE  = max floating_total_usd between entry_bar and exit_bar
  - MAE  = min floating_total_usd in the same window
  - exit_floating = floating_total_usd at the exit bar (≈ cycle realized PnL)
  - give_back_usd = mfe - exit_floating   (only meaningful when mfe > 0)
  - give_back_pct = give_back_usd / mfe * 100

The diagnostic quantifies how much unrealized profit each cycle reached at
its peak and how much was surrendered before the exit signal fired. A
strategy that captures (say) 80% of its peak unrealized profit on average
has a tight exit; one that captures 25% is leaking edge.

Rule-family agnostic: any cycle-mechanic basket that emits LIQUIDATE_* skip
reasons in the per-bar parquet is supported (h3_spread@1, H2_recycle@4/@5,
future variants).

Source-of-truth invariants (same as canonical_metrics):
  - cycle entry = first bar in (prev_exit, this_exit] with active_legs > 0
                  (or this_exit itself if the cycle opens AND closes within
                  one bar — rare but legal for tight adverse stops).
  - cycle exit = the LIQUIDATE_* bar (skip_reason).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from tools.basket_hypothesis.canonical_metrics import detect_rule_family


# Liquidation tags by rule family — mirrors canonical_metrics._cycle_pnl_from_parquet.
_LIQ_TAGS_BY_FAMILY: dict[str, list[str]] = {
    "h3_spread": [
        "LIQUIDATE_TIME_STOP",
        "LIQUIDATE_ADVERSE_STOP",
        "LIQUIDATE_REVERSE_CROSS",
        "LIQUIDATE_TRAIL_STOP",
        "LIQUIDATE_HARVEST_COMPLETE",   # H3_spread@2 terminal harvest exit
    ],
    "v4_bump_liquidate": ["LIQUIDATE_RESET"],
    "v5_pyramid": [
        "TREND_LIQUIDATE_RECOVERY",
        "TREND_LIQUIDATE_FLOOR",
        "TREND_LIQUIDATE_CORRELATION",
    ],
    "v1_recycle": [],  # no cycle-mechanic exits
}


def _stats(s: pd.Series) -> dict[str, float]:
    """Robust descriptive stats for a numeric Series; returns NaNs for empty."""
    s = s.dropna()
    if s.empty:
        return {"n": 0, "mean": float("nan"), "median": float("nan"),
                "p25": float("nan"), "p75": float("nan"),
                "p90": float("nan"), "max": float("nan")}
    return {
        "n":      int(len(s)),
        "mean":   float(s.mean()),
        "median": float(s.median()),
        "p25":    float(s.quantile(0.25)),
        "p75":    float(s.quantile(0.75)),
        "p90":    float(s.quantile(0.90)),
        "max":    float(s.max()),
    }


def _giveback_pct_histogram(s: pd.Series) -> list[dict[str, Any]]:
    """Bucket give-back % into 0-10, 10-25, 25-50, 50-75, 75-90, 90-100.
    Returns one row per bucket with count + share."""
    s = s.dropna()
    if s.empty:
        return []
    buckets = [(0, 10), (10, 25), (25, 50), (50, 75), (75, 90), (90, 101)]
    n = len(s)
    rows: list[dict[str, Any]] = []
    for lo, hi in buckets:
        cnt = int(((s >= lo) & (s < hi)).sum())
        rows.append({
            "lo": lo,
            "hi": hi if hi != 101 else 100,
            "count": cnt,
            "share_pct": cnt / n * 100.0,
        })
    return rows


def compute_mfe_giveback(
    parquet_path: str | Path,
    *,
    rule_family: Optional[str] = None,
) -> dict[str, Any]:
    """Compute per-cycle MFE / MAE / give-back analytics from the per-bar parquet.

    Args:
        parquet_path: path to `results_basket_per_bar.parquet`.
        rule_family: optional override for the LIQUIDATE_* tag set. If None,
            auto-detect via `canonical_metrics.detect_rule_family`.

    Returns:
        Dict with keys:
          - cycles: list[dict] per cycle (one row per liquidation)
          - summary: aggregate stats over all cycles
          - by_exit_tag: {tag -> aggregate stats}
          - profitable: aggregate stats over cycles with cycle_pnl > 0
          - losing: aggregate stats over cycles with cycle_pnl <= 0
          - giveback_pct_histogram: bucketed distribution
          - capture_rate_pct: total exit_floating / total mfe (clipped at 0)
          - rule_family: detected family
        If the parquet has no LIQUIDATE_* events, returns {"cycles": []}.
    """
    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)
    rf = rule_family or detect_rule_family(df)
    liq_tags = _LIQ_TAGS_BY_FAMILY.get(rf, [])
    if not liq_tags or "skip_reason" not in df.columns:
        return {"cycles": [], "rule_family": rf, "summary": {},
                "by_exit_tag": {}, "profitable": {}, "losing": {},
                "giveback_pct_histogram": [], "capture_rate_pct": 0.0}

    # Required columns. floating_total_usd is the canonical per-bar basket PnL
    # tracked by the engine (sum of leg_*_floating_usd at the bar's close).
    needed = {"skip_reason", "active_legs", "floating_total_usd",
              "realized_total_usd"}
    missing = needed - set(df.columns)
    if missing:
        raise KeyError(
            f"mfe_giveback: parquet missing required columns: {sorted(missing)}"
        )

    skip = df["skip_reason"].to_numpy()
    active = df["active_legs"].to_numpy()
    floating = df["floating_total_usd"].to_numpy(dtype=float)
    realized = df["realized_total_usd"].to_numpy(dtype=float)
    ts = (pd.to_datetime(df["timestamp"]) if "timestamp" in df.columns
          else pd.Series(range(len(df))))

    # Identify (entry_idx, exit_idx) pairs. Same logic as the original
    # diagnostic script: walk LIQUIDATE bars; entry = first active_legs > 0
    # in (prev_exit, this_exit], or this_exit itself for 1-bar cycles.
    liq_set = set(liq_tags)
    liq_bars: list[int] = [i for i in range(len(df))
                           if isinstance(skip[i], str) and skip[i] in liq_set]

    cycles: list[dict[str, Any]] = []
    prev_exit = -1
    prev_realized = 0.0
    for exit_i in liq_bars:
        in_pos = [j for j in range(prev_exit + 1, exit_i + 1) if active[j] > 0]
        entry_i = in_pos[0] if in_pos else exit_i

        # Window: entry .. exit inclusive. At the LIQUIDATE bar itself, the
        # engine logs the pre-liquidation floating (the value that tripped
        # the rule). After this bar, floating resets toward 0.
        window = floating[entry_i:exit_i + 1]
        if window.size == 0:
            continue
        # NaN-safe (the engine occasionally writes NaN during data gaps).
        mfe = float(np.nanmax(window))
        mae = float(np.nanmin(window))
        exit_floating = float(floating[exit_i])
        if np.isnan(exit_floating):
            exit_floating = 0.0
        bars_held = exit_i - entry_i

        give_back_usd = mfe - exit_floating
        give_back_pct = (
            (give_back_usd / mfe * 100.0) if mfe > 0 else float("nan")
        )

        # Cycle realized PnL = delta of realized_total_usd at the liq bar.
        cur_realized = float(realized[exit_i])
        cycle_pnl = cur_realized - prev_realized
        prev_realized = cur_realized

        cycles.append({
            "entry_idx":     int(entry_i),
            "exit_idx":      int(exit_i),
            "entry_ts":      ts.iloc[entry_i] if hasattr(ts, "iloc") else None,
            "exit_ts":       ts.iloc[exit_i] if hasattr(ts, "iloc") else None,
            "bars_held":     int(bars_held),
            "exit_tag":      str(skip[exit_i]),
            "exit_floating": exit_floating,
            "cycle_pnl":     cycle_pnl,
            "mfe":           mfe,
            "mae":           mae,
            "give_back_usd": give_back_usd,
            "give_back_pct": give_back_pct,
        })
        prev_exit = exit_i

    if not cycles:
        return {"cycles": [], "rule_family": rf, "summary": {},
                "by_exit_tag": {}, "profitable": {}, "losing": {},
                "giveback_pct_histogram": [], "capture_rate_pct": 0.0}

    cdf = pd.DataFrame(cycles)

    # Aggregate summary
    total_mfe = float(cdf["mfe"].clip(lower=0).sum())
    total_exit = float(cdf["exit_floating"].sum())
    total_giveback = total_mfe - total_exit
    capture_rate = (total_exit / total_mfe * 100.0) if total_mfe > 0 else 0.0

    summary: dict[str, Any] = {
        "n_cycles":              int(len(cdf)),
        "mean_mfe_usd":          float(cdf["mfe"].mean()),
        "median_mfe_usd":        float(cdf["mfe"].median()),
        "mean_exit_floating":    float(cdf["exit_floating"].mean()),
        "median_exit_floating":  float(cdf["exit_floating"].median()),
        "mean_giveback_usd":     float(cdf["give_back_usd"].mean()),
        "median_giveback_usd":   float(cdf["give_back_usd"].median()),
        "total_mfe_usd":         total_mfe,
        "total_exit_floating":   total_exit,
        "total_giveback_usd":    total_giveback,
        "giveback_pct_stats":    _stats(cdf["give_back_pct"]),
    }

    # By-exit-tag breakdown
    by_tag: dict[str, dict[str, Any]] = {}
    for tag, sub in cdf.groupby("exit_tag"):
        tag_mfe = float(sub["mfe"].clip(lower=0).sum())
        tag_exit = float(sub["exit_floating"].sum())
        tag_capture = (tag_exit / tag_mfe * 100.0) if tag_mfe > 0 else 0.0
        by_tag[str(tag)] = {
            "n":                  int(len(sub)),
            "mean_mfe_usd":       float(sub["mfe"].mean()),
            "mean_exit_floating": float(sub["exit_floating"].mean()),
            "mean_giveback_usd":  float(sub["give_back_usd"].mean()),
            "median_giveback_pct": (
                float(sub["give_back_pct"].dropna().median())
                if sub["give_back_pct"].notna().any() else float("nan")
            ),
            "capture_rate_pct":   tag_capture,
        }

    # Profitable / losing segmentation
    profitable = cdf[cdf["cycle_pnl"] > 0]
    losing = cdf[cdf["cycle_pnl"] <= 0]

    def _segment_stats(sub: pd.DataFrame) -> dict[str, Any]:
        if sub.empty:
            return {"n": 0}
        had_profit = sub[sub["mfe"] > 0]
        never_profit = sub[sub["mfe"] <= 0]
        sub_total_mfe = float(sub["mfe"].clip(lower=0).sum())
        sub_total_exit = float(sub["exit_floating"].sum())
        sub_capture = (
            (sub_total_exit / sub_total_mfe * 100.0) if sub_total_mfe > 0 else 0.0
        )
        return {
            "n":                   int(len(sub)),
            "mean_mfe_usd":        float(sub["mfe"].mean()),
            "mean_exit_floating":  float(sub["exit_floating"].mean()),
            "mean_giveback_usd":   float(sub["give_back_usd"].mean()),
            "median_giveback_pct": (
                float(sub["give_back_pct"].dropna().median())
                if sub["give_back_pct"].notna().any() else float("nan")
            ),
            "capture_rate_pct":    sub_capture,
            "n_had_mfe_positive":  int(len(had_profit)),
            "n_never_profitable":  int(len(never_profit)),
        }

    profitable_stats = _segment_stats(profitable)
    losing_stats = _segment_stats(losing)

    return {
        "cycles":                cycles,
        "rule_family":           rf,
        "summary":               summary,
        "by_exit_tag":           by_tag,
        "profitable":            profitable_stats,
        "losing":                losing_stats,
        "giveback_pct_histogram": _giveback_pct_histogram(cdf["give_back_pct"]),
        "capture_rate_pct":      capture_rate,
    }


__all__ = ["compute_mfe_giveback"]
