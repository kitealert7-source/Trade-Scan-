"""Trade path geometry section — generic, reusable across breakout-style systems.

Characterises *how* trades move from entry to exit, independent of strategy.
Four behavioural archetypes:
  Fast Expand      — immediate clean expansion, minimal adverse excursion
  Recover Win      — went adverse first, recovered to positive exit
  Profit Giveback  — reached 1R+ MFE, then reversed into the stop
  Stall-Decay      — partial or no MFE, slow bleed into stop or time exit

Requires: mfe_r, mae_r, r_multiple
Optional: exit_source (for SL identification), bars_held, direction
"""

from __future__ import annotations

import pandas as pd

_SL_SRC    = "ENGINE_STOP"
_TIME_SRCS = frozenset({"STRATEGY_DAY_CLOSE", "ENGINE_SESSION_RESET", "ENGINE_DATA_END"})

# Adverse excursion below this level is considered "minimal" for FAST_EXPAND
_FAST_MAE_CAP = 0.25


def _classify_path(row) -> str:
    src = row.get("exit_source", "")
    r   = float(row["r_multiple"])
    mfe = float(row["mfe_r"])
    mae = float(row["mae_r"])

    if src == _SL_SRC:
        if mfe < 0.1:
            return "IMMEDIATE_ADVERSE"
        if mfe >= 1.0:
            return "PROFIT_GIVEBACK"
        return "STALL_DECAY"

    if r > 0:
        return "FAST_EXPAND" if mae <= _FAST_MAE_CAP else "RECOVER_WIN"

    return "TIME_FLAT"


_ARCHETYPE_ORDER = [
    "FAST_EXPAND", "RECOVER_WIN",
    "PROFIT_GIVEBACK", "STALL_DECAY", "IMMEDIATE_ADVERSE",
    "TIME_FLAT",
]

_ARCHETYPE_LABELS = {
    "FAST_EXPAND":       "Fast Expand      (pos exit, mae <= 0.25R)",
    "RECOVER_WIN":       "Recover Win      (pos exit, adverse first)",
    "PROFIT_GIVEBACK":   "Profit Giveback  (SL, mfe >= 1R)",
    "STALL_DECAY":       "Stall-Decay      (SL, mfe 0.1–1R)",
    "IMMEDIATE_ADVERSE": "Immediate Adverse(SL, mfe < 0.1R)",
    "TIME_FLAT":         "Time-Flat        (non-SL exit, r <= 0)",
}


def _build_path_geometry_section(all_trades_dfs) -> list[str]:
    md = ["\n---\n", "## Trade Path Geometry\n"]
    if not all_trades_dfs:
        md.append("> No trade-level data available for Path Geometry.\n")
        return md

    _req = {"mfe_r", "mae_r", "r_multiple"}
    df = pd.concat(all_trades_dfs, ignore_index=True).copy()
    if not _req.issubset(df.columns):
        md.append("> Insufficient columns (need mfe_r, mae_r, r_multiple).\n")
        return md

    _has_src  = "exit_source" in df.columns
    _has_bars = "bars_held"   in df.columns

    if not _has_src:
        df["exit_source"] = ""

    df["_path"] = df.apply(_classify_path, axis=1)
    n_total = len(df)

    # ── Archetype table ────────────────────────────────────────────────────────
    md.append("### Path Archetypes\n")
    md.append("| Archetype | N | % | Avg R | Med MFE |")
    md.append("|-----------|---|---|-------|---------|")
    for key in _ARCHETYPE_ORDER:
        sub = df[df["_path"] == key]
        if len(sub) == 0:
            continue
        avg_r   = sub["r_multiple"].mean()
        med_mfe = sub["mfe_r"].median()
        pct     = len(sub) / n_total * 100
        md.append(
            f"| {_ARCHETYPE_LABELS[key]} | {len(sub)} | {pct:.1f}% "
            f"| {avg_r:+.2f}R | {med_mfe:.2f}R |"
        )
    md.append("")

    # ── Capture quality ────────────────────────────────────────────────────────
    md.append("### Capture Quality\n")
    md.append("| Metric | Value |")
    md.append("|--------|-------|")

    winners   = df[df["r_multiple"] > 0]
    sl_trades = df[df["exit_source"] == _SL_SRC]

    if len(winners):
        cap_ratio = (winners["r_multiple"] / winners["mfe_r"].clip(lower=0.001)).mean()
        md.append(f"| MFE Capture Ratio (winners) | {cap_ratio*100:.1f}% |")

    if len(sl_trades):
        wasted_n   = (sl_trades["mfe_r"] >= 0.5).sum()
        wasted_pct = wasted_n / len(sl_trades) * 100
        imm_n      = (sl_trades["mfe_r"] < 0.1).sum()
        imm_pct    = imm_n / len(sl_trades) * 100
        md.append(f"| Wasted-Edge (SL with mfe >= 0.5R) | {wasted_pct:.1f}% ({wasted_n} trades) |")
        md.append(f"| Immediate-Adverse (SL, mfe < 0.1R) | {imm_pct:.1f}% ({imm_n} trades) |")

    md.append("")

    # ── Recovery Boundary ────────────────────────────────────────────────────
    # Exclusive bands defined by cumulative thresholds: (prev, thr]. Each row
    # shows trades whose MAE landed in that band; recovery rate degrades as
    # the band deepens, exposing where recovery probability collapses.
    md.append("### Recovery Boundary\n")
    md.append("| MAE Threshold | Recovery % | Avg Final R |")
    md.append("|---|---|---|")
    _thresholds = [0.25, 0.50, 0.75, 0.90]
    _rates: list[float | None] = []
    _prev = 0.0
    for thr in _thresholds:
        if _prev == 0.0:
            sub = df[df["mae_r"] <= thr]
        else:
            sub = df[(df["mae_r"] > _prev) & (df["mae_r"] <= thr)]
        if len(sub) == 0:
            md.append(f"| <= {thr:.2f}R | --- | --- |")
            _rates.append(None)
        else:
            rec_pct = (sub["r_multiple"] > 0).mean() * 100
            avg_r   = sub["r_multiple"].mean()
            _rates.append(rec_pct)
            md.append(f"| <= {thr:.2f}R | {rec_pct:.0f}% | {avg_r:+.2f}R |")
        _prev = thr
    md.append("")

    below_50 = next((t for t, r in zip(_thresholds, _rates) if r is not None and r < 50), None)
    below_25 = next((t for t, r in zip(_thresholds, _rates) if r is not None and r < 25), None)
    if below_50 is not None or below_25 is not None:
        parts = []
        if below_50 is not None:
            parts.append(f"recovery falls below 50% beyond {below_50:.2f}R MAE")
        if below_25 is not None:
            parts.append(f"below 25% beyond {below_25:.2f}R")
        md.append(f"**Recovery Collapse:** " + " and ".join(parts) + ".\n")

    # ── Spotlight lines ────────────────────────────────────────────────────────
    stall = df[df["_path"] == "STALL_DECAY"]
    if len(stall):
        bars_str = (
            f"avg {stall['bars_held'].mean():.0f} bars held | " if _has_bars else ""
        )
        md.append(
            f"**Stall-Decay:** {len(stall)} trades ({len(stall)/n_total*100:.1f}%) | "
            f"{bars_str}"
            f"avg MFE {stall['mfe_r'].mean():.2f}R | "
            f"avg exit {stall['r_multiple'].mean():+.2f}R — "
            f"primary DD driver; investigate time-in-trade trail.\n"
        )

    giveback = df[df["_path"] == "PROFIT_GIVEBACK"]
    if len(giveback) and len(sl_trades):
        md.append(
            f"**Profit Giveback:** {len(giveback)} trades "
            f"({len(giveback)/len(sl_trades)*100:.1f}% of SL) | "
            f"avg peak MFE {giveback['mfe_r'].mean():.2f}R | "
            f"avg final R {giveback['r_multiple'].mean():+.2f}R — "
            f"investigate partial/lock trigger level.\n"
        )

    return md
