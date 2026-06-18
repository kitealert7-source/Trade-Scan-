"""pine_ratio_zrev_v1_zcross_hf.py — Hurst entry-filter overlay on the zero-cross exit variant.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-12, HF55 arm). It is the ZCRS
champion (zero-crossing exit) PLUS one ENTRY condition:

  Champion (zcross): a +/- z_entry cross of z_active proposes a new cycle whenever
                     the strategy is flat.
  Variant (hf):      the SAME proposal is BLOCKED when the pair's canonical price
                     ratio is locally PERSISTENT — trailing `hurst_window`-bar R/S
                     Hurst exponent of the ratio > `hurst_block_above` at the
                     proposal (signal) bar. Exits, sizing, hedge lock, warmup, and
                     fill timing are inherited unchanged.

Hypothesis (HF55, operator-approved 2026-06-12): blocking entries when the spread's
local Hurst exceeds 0.55 (window 50) improves median cycle PnL, win rate, and tail
p05 across all pair classes at the cost of ~25% fewer cycles; run-level blowup count
expected UNCHANGED (Step-1 report-only evidence: tmp/hurst_step1_report.md,
PROVISIONAL, 421 champion runs / 13,461 cycles). THRESHOLD/WINDOW OPTIMIZATION IS
EXPLICITLY OUT OF SCOPE for this arm — 50 / 0.55 are operator-fixed.

CANONICAL RATIO SOURCING (operator requirement)
-----------------------------------------------
The Hurst input is the `pine_zrev_ratio` column the parent attaches in
`_attach_z_r` — i.e. the `ratio` output of
`indicators.stats.ratio_hedged_spread_zscore` (A/B on the intersected leg index,
zero-denominator-safe). The SAME series the hedge ratio r_bar is averaged from.
This rule never reconstructs the ratio from leg closes independently — if the
parent's ratio definition ever changes, the filter follows automatically.

The estimator is `indicators.trend.hurst_rs.hurst_rs` (classical R/S on log
returns, Pine-faithful, population std) — the SAME estimator the Step-1
calibration used. Do NOT swap in `indicators.trend.hurst_regime` (lag-variance):
the two produce different absolute H values and 0.55 is not transferable.

GATE PLACEMENT + NO-LOOKAHEAD
-----------------------------
The gate lives in `_maybe_propose` — the proposal bar, per the hypothesis text.
H at bar M is computed from closes up to and including M, the same data vintage
as the z-cross signal that fires there; the fill still happens via the inherited
approve/fire path on a later bar. No lookahead is introduced.

FAIL-OPEN CONTRACT
------------------
The filter can only block on a VALID estimate. `hurst_rs` yields NaN for the
first `hurst_window` bars and 0.5 (neutral) for degenerate windows; NaN never
blocks (explicit nan-check) and 0.5 < any sane threshold. Missing bar_ts in the
H series (holiday bars) likewise falls through to the inherited propose path.

TELEMETRY (operator requirement: distribution of blocked H values)
------------------------------------------------------------------
Every block appends a recycle_event::

    {"action": "HURST_BLOCK", "bar_ts": ..., "h": <blocked H>,
     "threshold": <hurst_block_above>, "direction": <+1|-1>}

so the full distribution of blocked H values is reconstructable from the run's
events. `_n_hurst_blocks` carries the count. A block is recorded ONLY when the
proposal would otherwise have been armed (mirrors the parent's idle-state guard)
— the count is exactly "entries removed by the filter", not raw signal bars.

PARITY PROPERTY (the clean-toggle gate): with `hurst_block_above` beyond the
estimator's reach (e.g. 1e9; hurst_rs guard-rails H to [-0.5, 1.5]) the gate
never fires and the rule is byte-identical to `PineRatioZRevRuleZCross` — that
is what the parity test asserts.

Registered as `pine_ratio_zrev_v1_zcross_hf@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version =>
distinct STRATEGY_SIGNATURE hash => no ledger / MPS / cointegration_sheet
collision with the zcross champion corpus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from indicators.trend.hurst_rs import hurst_rs
from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zcross_hf"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCrossHF(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + Hurst persistence entry filter."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Entry filter (HF55 arm defaults, operator-fixed — no optimization).
    hurst_window: int = 50
    hurst_block_above: float = 0.55

    hurst_column: str = "pine_zrev_hurst"

    # Runtime state.
    _n_hurst_blocks: int = 0
    _hurst_by_ts: Optional[pd.Series] = None  # H indexed by the intersected bar index

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.hurst_window) < 10:
            raise ValueError(
                f"PineRatioZRevRuleZCrossHF.hurst_window must be >= 10 for a "
                f"usable R/S estimate, got {self.hurst_window!r}."
            )
        if not float(self.hurst_block_above) > 0:
            raise ValueError(
                f"PineRatioZRevRuleZCrossHF.hurst_block_above must be > 0, "
                f"got {self.hurst_block_above!r}."
            )

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit the full parent attach, then compute the entry-filter H series.

        The Hurst input is the parent-attached `pine_zrev_ratio` column (the
        canonical `ratio` output of ratio_hedged_spread_zscore) restricted to
        the intersected leg index — NOT a locally reconstructed close ratio.
        Computing on the intersected index keeps holiday bars (NaN on the
        reindexed leg frame) out of the R/S windows, mirroring how the z itself
        is computed.
        """
        super()._attach_z_r(legs)

        common_idx = legs[0].df.index.intersection(legs[1].df.index)
        ratio = legs[0].df["pine_zrev_ratio"].reindex(common_idx)
        h = hurst_rs(ratio, window=int(self.hurst_window))
        self._hurst_by_ts = h
        for leg in legs:
            leg.df[self.hurst_column] = h.reindex(leg.df.index)

    def _maybe_propose(self, signal_value: int, bar_ts: pd.Timestamp) -> None:
        """Block the proposal when the ratio is locally persistent (H > threshold).

        The block is evaluated (and the telemetry event recorded) ONLY when the
        inherited propose path would actually arm a proposal — same idle-state
        guard as the parent — so `_n_hurst_blocks` counts true removed entries.
        All other paths fall through to the inherited behavior unchanged.
        """
        state = self.shared_armed_state
        would_arm = (
            signal_value in (+1, -1)
            and state is not None
            and state.pending_trigger_ts is None
            and state.approved_fire_ts is None
        )
        if would_arm and self._hurst_by_ts is not None:
            try:
                h_now = float(self._hurst_by_ts.get(bar_ts, float("nan")))
            except (TypeError, ValueError):
                h_now = float("nan")
            # nan-safe: only a VALID estimate may block (fail-open contract).
            if h_now == h_now and h_now > float(self.hurst_block_above):
                self._n_hurst_blocks += 1
                self.recycle_events.append({
                    "bar_ts":    bar_ts,
                    "action":    "HURST_BLOCK",
                    "h":         h_now,
                    "threshold": float(self.hurst_block_above),
                    "direction": int(signal_value),
                })
                return
        super()._maybe_propose(signal_value, bar_ts)
