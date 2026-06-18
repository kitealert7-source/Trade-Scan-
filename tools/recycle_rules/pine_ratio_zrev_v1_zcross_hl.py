"""pine_ratio_zrev_v1_zcross_hl.py — local half-life entry-filter overlay on the zero-cross exit.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-12, HL120 arm). It is the
ZCRS champion PLUS one ENTRY condition:

  Champion (zcross): a +/- z_entry cross of z_active proposes a new cycle
                     whenever the strategy is flat.
  Variant (hl):      the SAME proposal is BLOCKED when the canonical ratio's
                     LOCAL reversion is too slow for the trade horizon —
                     rolling AR(1) half-life (hl_window bars,
                     indicators.stats.rolling_half_life) of the ratio
                     > hl_block_above bars, OR locally non-reverting
                     (half-life = +inf). Exits, sizing, hedge lock, warmup,
                     and fill timing are inherited unchanged.

Hypothesis (HL120, operator-approved 2026-06-12): reversion SPEED captures a
toxic entry population that persistence (the HF55/HF60 Hurst arms) may miss —
the zcross exit's payoff is directly "how fast z returns to 0". Threshold
anchoring (measured, 27,184 champion leg-trades): median hold 14 bars / p95 28
bars; HL > 120 bars means local reversion ~9x slower than the median completed
trade and ~4x the p95 — the entry's premise is structurally broken. The Step-1
offline scan (hypothesis-grade) found the HL>=120/non-reverting bucket toxic
while 60-120 was PROFITABLE — hence the loose threshold; do NOT tighten it
without a new tagged arm. NO THRESHOLD/WINDOW OPTIMIZATION in this arm
(100 / 120 operator-fixed).

CANONICAL RATIO SOURCING: identical to the HF arm — input is the parent's
`pine_zrev_ratio` column (the `ratio` output of ratio_hedged_spread_zscore on
the intersected leg index), never a local reconstruction. This is the LOCAL
exec-TF statistic, NOT the screener's `half_life_days` (daily/252d — ~1,300+
15m bars, two orders of magnitude above the trade horizon; ruled out
2026-06-12 for exactly that timescale mismatch).

GATE PLACEMENT + NO-LOOKAHEAD: `_maybe_propose`, the proposal bar — HL at bar
M uses closes up to and including M, the same data vintage as the z-cross
signal. Fill path inherited (no lookahead).

FAIL-OPEN CONTRACT: NaN (warmup / NaN window / zero variance) never blocks.
+inf is NOT NaN — a non-reverting window is a meaningful "too slow" estimate
and IS blocked (inf > any finite threshold).

TELEMETRY: every block appends a recycle_event::

    {"action": "HL_BLOCK", "bar_ts": ..., "hl": <finite HL or None>,
     "non_reverting": <bool>, "threshold": <hl_block_above>,
     "direction": <+1|-1>}

(`hl` is None when the window was non-reverting — +inf is not JSON-portable —
with `non_reverting=true` carrying the information.) Counter:
`_n_hl_blocks`. Blocks are recorded ONLY when the proposal would otherwise
have been armed (parent idle-state guard mirrored) — the count is exactly
"entries removed by the filter". Events persist to raw/recycle_events.jsonl.

PARITY PROPERTY (the clean-toggle gate): with `hl_block_above = math.inf` the
gate never fires (finite > inf is False, and inf > inf is False, so even
non-reverting windows pass) and the rule is byte-identical to
`PineRatioZRevRuleZCross` — asserted by the parity test. Any FINITE threshold
still blocks non-reverting windows, so "very large" is NOT a disable.

Registered as `pine_ratio_zrev_v1_zcross_hl@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version =>
distinct STRATEGY_SIGNATURE hash => no ledger collision with champion / HF
corpora.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from indicators.stats.rolling_half_life import rolling_half_life
from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zcross_hl"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCrossHL(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + local half-life entry filter."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Entry filter (HL120 arm defaults, operator-fixed — no optimization).
    hl_window: int = 100
    hl_block_above: float = 120.0

    hl_column: str = "pine_zrev_half_life"

    # Runtime state.
    _n_hl_blocks: int = 0
    _hl_by_ts: Optional[pd.Series] = None  # HL indexed by the intersected bar index

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.hl_window) < 20:
            raise ValueError(
                f"PineRatioZRevRuleZCrossHL.hl_window must be >= 20 for a "
                f"usable AR(1) fit, got {self.hl_window!r}."
            )
        if not float(self.hl_block_above) > 0:
            raise ValueError(
                f"PineRatioZRevRuleZCrossHL.hl_block_above must be > 0, "
                f"got {self.hl_block_above!r}."
            )

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit the full parent attach, then compute the entry-filter HL
        series from the canonical `pine_zrev_ratio` column on the intersected
        leg index (same sourcing contract as the HF arm)."""
        super()._attach_z_r(legs)

        common_idx = legs[0].df.index.intersection(legs[1].df.index)
        ratio = legs[0].df["pine_zrev_ratio"].reindex(common_idx)
        hl = rolling_half_life(ratio, window=int(self.hl_window))
        self._hl_by_ts = hl
        for leg in legs:
            leg.df[self.hl_column] = hl.reindex(leg.df.index)

    def _maybe_propose(self, signal_value: int, bar_ts: pd.Timestamp) -> None:
        """Block the proposal when local reversion is too slow (HL > threshold,
        including the non-reverting +inf case). NaN never blocks (fail-open).
        Mirrors the parent's idle-state guard so `_n_hl_blocks` counts true
        removed entries; all other paths inherit unchanged."""
        state = self.shared_armed_state
        would_arm = (
            signal_value in (+1, -1)
            and state is not None
            and state.pending_trigger_ts is None
            and state.approved_fire_ts is None
        )
        if would_arm and self._hl_by_ts is not None:
            try:
                hl_now = float(self._hl_by_ts.get(bar_ts, float("nan")))
            except (TypeError, ValueError):
                hl_now = float("nan")
            # nan-safe: only a VALID estimate may block; +inf is valid ("too slow").
            if hl_now == hl_now and hl_now > float(self.hl_block_above):
                self._n_hl_blocks += 1
                self.recycle_events.append({
                    "bar_ts":        bar_ts,
                    "action":        "HL_BLOCK",
                    "hl":            hl_now if math.isfinite(hl_now) else None,
                    "non_reverting": not math.isfinite(hl_now),
                    "threshold":     float(self.hl_block_above),
                    "direction":     int(signal_value),
                })
                return
        super()._maybe_propose(signal_value, bar_ts)
