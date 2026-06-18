"""pine_ratio_zrev_v1_zcross_hflm.py — HF∩LM intersection entry-filter overlay.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-12, HFLM arm). It is the
ZCRS champion PLUS one entry condition that blocks ONLY when TWO independent
detectors AGREE:

  Block the entry proposal iff
      Hurst(ratio, hurst_window) > hurst_block_above        (persistence)
    AND
      max_leg normalized_net_move(lm_window) > lm_block_above  (displacement)

i.e. the spread is BOTH locally persistent AND one leg has just made a large
directional repricing. Either condition alone does NOT block.

Hypothesis (HFLM, operator-approved 2026-06-12): the overlap analysis (champion
corpus, 12,685 entries, both populations recomputed on canonical data) showed
HF55 (H>0.55) and LM20 (move>2σ) are LARGELY DISTINCT (Jaccard 0.18) but their
INTERSECTION is the toxic core: the BOTH group (6.9% of entries) carries mean
−8.22 / median −1.14 / −7,158 aggregate, an order of magnitude worse than
HF-only (mean −0.73, median +1.29) or LM-only (mean −0.74, median +1.33), which
are near-break-even. The intersection isolates the genuinely bad population
that acting on either filter alone cannot catch without also killing the good
single-flag entries. Surgical (small block set → bounded relocation), and it
inherits HF's ~25h persistence (the relocation-quality ingredient LM20 lacked).
0.55 / 2.0 / 50 / 12 operator-FIXED — NO THRESHOLD/WINDOW OPTIMIZATION.

SOURCING: Hurst on the parent's canonical `pine_zrev_ratio` column (same as the
HF arm); displacement on per-leg closes (same as the LM arm). No reconstruction.

GATE PLACEMENT + FAIL-OPEN: `_maybe_propose` (proposal bar). The AND is True
only when BOTH estimates are valid AND both exceed threshold; any NaN on either
side → that condition is False → no block (fail-open, and stricter than the
single-filter arms since BOTH must be present).

TELEMETRY: every block appends::

    {"action": "BOTH_BLOCK", "bar_ts": ..., "h": <hurst>, "mm": <max nnm>,
     "leg": <driving leg>, "h_threshold": ..., "mm_threshold": ...,
     "direction": <+1|-1>}

Counter: `_n_both_blocks`. Recorded only when the proposal would otherwise have
armed. Persists to raw/recycle_events.jsonl.

PARITY PROPERTY: with EITHER `hurst_block_above` or `lm_block_above` set beyond
reach (math.inf), that condition is never True, so the AND never fires and the
rule is byte-identical to `PineRatioZRevRuleZCross` (parity test asserts both).

Registered as `pine_ratio_zrev_v1_zcross_hflm@1` in
`governance/recycle_rules/registry.yaml`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from indicators.stats.normalized_net_move import normalized_net_move
from indicators.trend.hurst_rs import hurst_rs
from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zcross_hflm"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCrossHFLM(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + Hurst∩displacement (AND) entry filter."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # HF leg (persistence) — HF55 defaults.
    hurst_window: int = 50
    hurst_block_above: float = 0.55
    # LM leg (displacement) — LM20 defaults.
    lm_window: int = 12
    lm_block_above: float = 2.0
    lm_min_vol_obs: int = 100

    hurst_column: str = "pine_zrev_hurst"
    lm_column: str = "pine_zrev_legmove"

    _n_both_blocks: int = 0
    _h_by_ts: Optional[pd.Series] = None
    _lm_by_ts: Optional[pd.DataFrame] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.hurst_window) < 10:
            raise ValueError(
                f"hurst_window must be >= 10, got {self.hurst_window!r}.")
        if int(self.lm_window) < 2:
            raise ValueError(
                f"lm_window must be >= 2, got {self.lm_window!r}.")
        if not float(self.hurst_block_above) > 0:
            raise ValueError(
                f"hurst_block_above must be > 0, got {self.hurst_block_above!r}.")
        if not float(self.lm_block_above) > 0:
            raise ValueError(
                f"lm_block_above must be > 0, got {self.lm_block_above!r}.")

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit parent attach, then compute BOTH detector series:
        Hurst on the canonical ratio, displacement per leg."""
        super()._attach_z_r(legs)
        common_idx = legs[0].df.index.intersection(legs[1].df.index)

        ratio = legs[0].df["pine_zrev_ratio"].reindex(common_idx)
        self._h_by_ts = hurst_rs(ratio, window=int(self.hurst_window))

        per_leg = {
            leg.symbol: normalized_net_move(
                leg.df["close"].reindex(common_idx),
                window=int(self.lm_window),
                min_vol_obs=int(self.lm_min_vol_obs),
            )
            for leg in legs
        }
        self._lm_by_ts = pd.DataFrame(per_leg)

        mm = self._lm_by_ts.max(axis=1)
        for leg in legs:
            leg.df[self.hurst_column] = self._h_by_ts.reindex(leg.df.index)
            leg.df[self.lm_column] = mm.reindex(leg.df.index)

    def _maybe_propose(self, signal_value: int, bar_ts: pd.Timestamp) -> None:
        """Block ONLY when BOTH detectors fire (persistence AND displacement).
        Either NaN, or either condition below threshold → no block."""
        state = self.shared_armed_state
        would_arm = (
            signal_value in (+1, -1)
            and state is not None
            and state.pending_trigger_ts is None
            and state.approved_fire_ts is None
        )
        if (would_arm and self._h_by_ts is not None and self._lm_by_ts is not None
                and bar_ts in self._lm_by_ts.index):
            try:
                h_now = float(self._h_by_ts.get(bar_ts, float("nan")))
            except (TypeError, ValueError):
                h_now = float("nan")
            lm_row = self._lm_by_ts.loc[bar_ts]
            mm = lm_row.max()
            h_hit = (h_now == h_now) and h_now > float(self.hurst_block_above)
            lm_hit = (mm == mm) and float(mm) > float(self.lm_block_above)
            if h_hit and lm_hit:
                self._n_both_blocks += 1
                self.recycle_events.append({
                    "bar_ts":       bar_ts,
                    "action":       "BOTH_BLOCK",
                    "h":            h_now,
                    "mm":           float(mm),
                    "leg":          str(lm_row.idxmax()),
                    "h_threshold":  float(self.hurst_block_above),
                    "mm_threshold": float(self.lm_block_above),
                    "direction":    int(signal_value),
                })
                return
        super()._maybe_propose(signal_value, bar_ts)
