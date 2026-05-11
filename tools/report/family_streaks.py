"""Win/loss streak helpers for trade-level analysis.

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4: this module
duplicates the inline logic at ``tools/robustness/runner.py:203-237`` rather
than extracting it. The original implementation in `runner.py` stays untouched
in the first release. A follow-up proposal may consolidate the two callers.

Function bodies are byte-equivalent to the inline copy in `runner.py`. The
unit tests pin both implementations against the same fixture inputs so any
future divergence is detectable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_streaks(pnls) -> dict:
    """Return {max_win_streak, max_loss_streak, avg_win_streak, avg_loss_streak, total_trades}.

    Accepts a numpy array, pandas Series, or list of per-trade PnL values.
    A "win" is pnl > 0; a "loss" is pnl < 0. Zero-PnL trades break both runs.
    """
    arr = np.asarray(pnls, dtype=float)
    wins = (arr > 0).astype(int)
    losses = (arr < 0).astype(int)
    return {
        "max_win_streak": _max_streak(wins),
        "max_loss_streak": _max_streak(losses),
        "avg_win_streak": float(_avg_streak(wins)),
        "avg_loss_streak": float(_avg_streak(losses)),
        "total_trades": int(len(arr)),
    }


def _max_streak(arr) -> int:
    """Longest consecutive run of 1s in `arr`. Byte-equivalent to
    `_max_streak` in `tools/robustness/runner.py:207-215`.
    """
    mx, cur = 0, 0
    for v in arr:
        if v:
            cur += 1
            if cur > mx:
                mx = cur
        else:
            cur = 0
    return int(mx)


def _avg_streak(arr) -> float:
    """Mean run length over all positive runs in `arr`. Byte-equivalent to
    `_avg_streak` in `tools/robustness/runner.py:217-229`.
    """
    streaks: list[int] = []
    cur = 0
    for v in arr:
        if v:
            cur += 1
        else:
            if cur > 0:
                streaks.append(cur)
            cur = 0
    if cur > 0:
        streaks.append(cur)
    return (sum(streaks) / len(streaks)) if streaks else 0.0
