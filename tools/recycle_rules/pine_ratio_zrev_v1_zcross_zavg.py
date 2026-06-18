"""pine_ratio_zrev_v1_zcross_zavg.py — 2-bar z-average entry trigger on the zcross champion.

A/B test variant of `PineRatioZRevRuleZCross` (2026-06-13, ZAVG2 arm). It is the ZCRS
champion (zero-crossing exit) with ONE change to the ENTRY trigger:

  Champion (zcross): a +/- z_entry cross of the SINGLE-BAR z_active proposes a new
                     cycle whenever the strategy is flat.
  Variant  (zavg):   the proposal fires on a +/- z_entry cross of the TRAILING
                     `zavg_window`-bar MEAN of z_active instead of the single bar.
                     Exits (zcross), sizing, hedge lock, warmup, and fill timing are
                     inherited UNCHANGED.

Hypothesis (ZAVG2, operator-directed 2026-06-13): smoothing the entry trigger over
2 bars rejects single-bar threshold spikes (the live real-time-noise failure mode of
the 2026-06 demo, acct 213872531) and enters deeper on sustained moves. The settled-
data cost (skipping shallow quick-revert crossings) vs the live noise-rejection benefit
is the empirical question; the backtest pipeline measures the SETTLED side only (it
contains no real-time noise). Step-1 report-only PROVISIONAL evidence: an
averaging-keeps (AVG_CONFIRMED) vs averaging-skips/delays (SINGLE_ONLY) stratification
on the _LIVEWK deployed pairs. `zavg_window=2` operator-fixed; no sweeps.

ONE MOVING VARIABLE: only the ENTRY signal series changes (single-bar z -> 2-bar mean
z). The EXIT stays on the RAW single-bar z (the inherited zcross sign-change), so this
isolates the entry-trigger smoothing — nothing else moves.

GATE PLACEMENT + NO-LOOKAHEAD: the 2-bar mean at bar M uses z[M-1], z[M] — closes up to
and including M, the same data vintage as the single-bar cross it replaces; the fill
still happens via the inherited approve/fire path on a later bar. No lookahead.

PARITY PROPERTY (the clean-toggle gate): with `zavg_window=1` the "mean" is the single
bar and the rule is byte-identical to `PineRatioZRevRuleZCross` — that is what the
parity test asserts.

Registered as `pine_ratio_zrev_v1_zcross_zavg@1` in
`governance/recycle_rules/registry.yaml`. Distinct rule name + version => distinct
STRATEGY_SIGNATURE hash => no ledger / MPS / cointegration_sheet collision with the
zcross champion corpus.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tools.basket_runner import BasketLeg
from tools.recycle_rules.pine_ratio_zrev_v1_zcross import PineRatioZRevRuleZCross


_RULE_NAME = "pine_ratio_zrev_v1_zcross_zavg"
_RULE_VERSION = 1


@dataclass
class PineRatioZRevRuleZCrossZAvg(PineRatioZRevRuleZCross):
    """Pine z_r reversal — zero-cross exit + 2-bar z-average entry trigger."""

    name: str = _RULE_NAME
    version: int = _RULE_VERSION

    # Entry-trigger smoothing window (ZAVG2 arm default, operator-fixed — no sweeps).
    # 1 => single-bar trigger == byte-identical to the zcross champion (parity gate).
    zavg_window: int = 2

    zavg_column: str = "pine_zrev_zavg"

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.zavg_window) < 1:
            raise ValueError(
                f"PineRatioZRevRuleZCrossZAvg.zavg_window must be >= 1, "
                f"got {self.zavg_window!r}."
            )

    def _attach_z_r(self, legs: list[BasketLeg]) -> None:
        """Inherit the full parent attach (raw z + single-bar signal + zcross exit),
        then OVERWRITE the entry signal with the `zavg_window`-bar mean-z cross.

        The averaged series is computed on the INTERSECTED leg index (mirrors how the
        parent computes z itself), so holiday bars stay out of the rolling mean, then
        reindexed to each leg with fill 0 (no fire on a missing-partner bar). The EXIT
        column (`pine_zrev_zcross_exit`, sign-change of the RAW z) is left UNTOUCHED —
        only the ENTRY trigger changes.
        """
        super()._attach_z_r(legs)

        z_col = "pine_zrev_z_centered" if self.entry_mode == "centered" else "pine_zrev_z"
        win = int(self.zavg_window)

        if win <= 1:
            # Parity: the single-bar trigger == the inherited signal; only attach the
            # diagnostic column (the active z itself) and leave the signal as-is.
            for leg in legs:
                leg.df[self.zavg_column] = leg.df[z_col]
            return

        common_idx = legs[0].df.index.intersection(legs[1].df.index)
        z_active = legs[0].df[z_col].reindex(common_idx)
        z_avg = z_active.rolling(window=win, min_periods=win).mean()

        # Cross detection on the AVERAGED series — same convention as the parent's
        # single-bar cross (indicators sourcing + sign mapping unchanged):
        #   Cross UP through +z_entry  -> SHORT_SPREAD (-1): z high, A rich
        #   Cross DN through -z_entry  -> LONG_SPREAD  (+1): z low,  A cheap
        prev = z_avg.shift(1)
        crossed_up = (prev <= self.z_entry) & (z_avg > self.z_entry)
        crossed_dn = (prev >= -self.z_entry) & (z_avg < -self.z_entry)
        signal_aligned = pd.Series(0, index=z_avg.index, dtype="int64")
        signal_aligned[crossed_dn] = +1   # LONG_SPREAD
        signal_aligned[crossed_up] = -1   # SHORT_SPREAD

        for leg in legs:
            leg.df[self.signal_column] = signal_aligned.reindex(leg.df.index, fill_value=0)
            leg.df[self.zavg_column] = z_avg.reindex(leg.df.index)
