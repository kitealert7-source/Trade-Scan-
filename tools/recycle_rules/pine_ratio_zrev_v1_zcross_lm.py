"""pine_ratio_zrev_v1_zcross_lm.py — leg-displacement entry-filter overlay on the zero-cross exit.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-12, LM20 arm). It is the
ZCRS champion PLUS one ENTRY condition:

  Champion (zcross): a +/- z_entry cross of z_active proposes a new cycle
                     whenever the strategy is flat.
  Variant (lm):      the SAME proposal is BLOCKED when EITHER leg has just made
                     a large net directional repricing — vol-scaled trailing
                     `lm_window`-bar net move (indicators.stats.
                     normalized_net_move, per-leg closes, causal expanding vol)
                     > `lm_block_above` on either leg at the proposal bar.
                     Exits, sizing, hedge lock, warmup, fill timing inherited.

Hypothesis (LM20, operator-approved 2026-06-12): "don't fade large directional
repricings" — the structural variable BEHIND the HF (persistence) and HL
(reversion-speed) detectors. Characterization (champion corpus, 13,064 entries):
cycle PnL deteriorates MONOTONICALLY with the larger leg's trailing net move in
ALL FOUR pair classes; the >=2-sigma bucket is net-negative everywhere (FX-FX
-1207, IDX-IDX -409, FX-IDX -2779, CRY/MET-X -3277 vs positive kept-sums).
Economically: a z-cross fired by one leg ABSORBING INFORMATION is a
continuation, not a reversion opportunity. 12 / 2.0 operator-fixed — NO
THRESHOLD/WINDOW OPTIMIZATION in this arm.

CAUSALITY NOTE: the characterization normalized by FULL-RUN sigma (mild
lookahead in the normalizer); this rule uses the EXPANDING run-to-date sigma
(min 100 obs) — strictly causal. The pipeline arbitrates the honest version.

LEG SOURCING: per-leg close series on the intersected index — the legs
themselves, not the ratio (a one-leg repricing can leave ratio statistics
ambiguous; the displacement is a property of the LEG).

GATE PLACEMENT + FAIL-OPEN: `_maybe_propose` (proposal bar; same data vintage
as the z signal). NaN (warmup / zero-vol) never blocks.

TELEMETRY: every block appends::

    {"action": "MOVE_BLOCK", "bar_ts": ..., "mm": <max leg nnm>,
     "leg": <symbol of the larger-move leg>, "threshold": ...,
     "direction": <+1|-1>}

Counter: `_n_move_blocks`. Blocks recorded only when the proposal would
otherwise have been armed. Events persist to raw/recycle_events.jsonl.

PARITY PROPERTY: `lm_block_above = math.inf` => gate never fires =>
byte-identical to PineRatioZRevRuleZCross (asserted by the parity test).

Registered as `pine_ratio_zrev_v1_zcross_lm@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version =>
distinct STRATEGY_SIGNATURE hash.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from indicators.stats.normalized_net_move import normalized_net_move
from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zcross_lm"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCrossLM(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + leg-displacement entry filter."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Entry filter (LM20 arm defaults, operator-fixed — no optimization).
    lm_window: int = 12
    lm_block_above: float = 2.0
    lm_min_vol_obs: int = 100

    lm_column: str = "pine_zrev_legmove"

    # Runtime state.
    _n_move_blocks: int = 0
    _lm_by_ts: Optional[pd.DataFrame] = None  # per-leg nnm, indexed by common bars

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.lm_window) < 2:
            raise ValueError(
                f"PineRatioZRevRuleZCrossLM.lm_window must be >= 2, "
                f"got {self.lm_window!r}."
            )
        if not float(self.lm_block_above) > 0:
            raise ValueError(
                f"PineRatioZRevRuleZCrossLM.lm_block_above must be > 0, "
                f"got {self.lm_block_above!r}."
            )

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit the full parent attach, then compute each LEG's vol-scaled
        trailing net move on the intersected index (per-leg closes — the
        displacement is a property of the leg, not the ratio)."""
        super()._attach_z_r(legs)

        common_idx = legs[0].df.index.intersection(legs[1].df.index)
        per_leg = {}
        for leg in legs:
            close = leg.df["close"].reindex(common_idx)
            per_leg[leg.symbol] = normalized_net_move(
                close, window=int(self.lm_window),
                min_vol_obs=int(self.lm_min_vol_obs),
            )
        self._lm_by_ts = pd.DataFrame(per_leg)
        mm = self._lm_by_ts.max(axis=1)
        for leg in legs:
            leg.df[self.lm_column] = mm.reindex(leg.df.index)

    def _maybe_propose(self, signal_value: int, bar_ts: pd.Timestamp) -> None:
        """Block the proposal when either leg's trailing net move exceeds the
        threshold (don't fade an information move). NaN never blocks."""
        state = self.shared_armed_state
        would_arm = (
            signal_value in (+1, -1)
            and state is not None
            and state.pending_trigger_ts is None
            and state.approved_fire_ts is None
        )
        if would_arm and self._lm_by_ts is not None and bar_ts in self._lm_by_ts.index:
            row = self._lm_by_ts.loc[bar_ts]
            mm = row.max()
            if mm == mm and float(mm) > float(self.lm_block_above):
                self._n_move_blocks += 1
                self.recycle_events.append({
                    "bar_ts":    bar_ts,
                    "action":    "MOVE_BLOCK",
                    "mm":        float(mm),
                    "leg":       str(row.idxmax()),
                    "threshold": float(self.lm_block_above),
                    "direction": int(signal_value),
                })
                return
        super()._maybe_propose(signal_value, bar_ts)
