"""h2_recycle_v5.py — H2_recycle@5: trend-follow pyramid mechanic.

Inverse-H2. Pyramids the WINNER leg each `pyramid_increment_usd` of new
loss on the LOSER leg. Loser is held at its initial lot — never grows —
serving as a tripwire + trend-distance sensor. Exits the basket when
the loser's floating PnL recovers `exit_recovery_usd` from its trough
(regime reversal signal), then soft-resets to a fresh 0.01+0.01 basket.

Mechanic
--------
- Add 0.01 to WINNER each time the LOSER leg's floating PnL hits a new
  low at `pyramid_increment_usd` increments below the previous add level.
- Loser leg is NEVER added to (anti-Martingale on winner).
- Loser identity is LOCKED at first pyramid event for the cycle's
  duration — once we start pyramiding direction X, direction Y stays
  the loser/tripwire for this cycle even if intra-bar floating flips.
- Exit when LOSER floating recovers `exit_recovery_usd` from its trough
  (= trend reversing) OR basket floating breaches `hard_floor_loss_usd`
  (defensive floor; should rarely fire if exit_recovery_usd is set
  conservatively).
- On exit: realize ALL floating, call `BasketRunner.soft_reset_basket`
  to reopen fresh 0.01+0.01, reset rule state. Next cycle starts.

Convex payoff design
--------------------
Per-cycle loss is bounded at ~$10 plus brokerage (≈ 1.1% of $1k stake)
by construction. Per-cycle upside is unbounded — pyramided winner
accumulates while loser is held at fixed exposure; trend continuation
generates positive equity at increasing pip-rate. Anti-Martingale
position sizing: heavy position is held only after the trend has
proven itself, not on hope.

References
----------
- Hypothesis spec: backtest_directives/hypotheses/H3_TREND_FOLLOW_V1.yaml
- Parent design: tools/recycle_rules/h2_recycle.py (H2RecycleRule)
- BasketRunner primitive consumed: BasketRunner.soft_reset_basket
  (commit 62018ab, 2026-05-16)
- Pipeline-only build per "Path B" decision (2026-05-17): no basket_sim
  duplicate; the pipeline parquet IS the reference. Rationale in YAML
  evidence_required.reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.recycle_rules.h2_recycle import (
    H2RecycleRule,
    _USD_BASE,
    _USD_QUOTE,
    _LOT_UNITS,
)
# Cross-pair extension (2026-05-17): swap V1's USD-anchored PnL/margin
# helpers for V3's cross-pair-aware versions. Per V3 docstring "for
# USD-anchored pairs the math collapses cleanly back to v1/v2's hardcoded
# formulas — validated by parity tests" — so existing V5 USD-pair runs
# (S16, S22-S32 etc.) stay byte-identical under this swap. The change
# enables cross-pair legs (EURJPY, GBPAUD, AUDNZD, etc.) to be used in
# H3 baskets — exercised by S33+ directives.
#
# Caveat: the parent's _record_bar (inherited from H2RecycleRule) still
# uses V1's USD_QUOTE/USD_BASE constants for per-leg notional + margin
# columns in the per-bar parquet. Those columns become silently zero for
# cross-pair legs — they are informational only and not used by
# canonical_metrics, BASKET_REPORT, or any control path. The control
# path (margin_used computation for freeze checks) flows through the
# helpers we swap here and IS correct for cross pairs.
from tools.recycle_rules.h2_recycle_v3 import (
    _build_ref_closes,
    _leg_pnl_usd,
    _leg_margin_usd,
)

# ABI ANCHOR: H2_RECYCLE_V5_RULE
_RULE_NAME_V5 = "H2_recycle"
_RULE_VERSION_V5 = 5


@dataclass
class H2RecycleRuleV5(H2RecycleRule):
    """Trend-follow pyramid variant of H2_recycle.

    Inherits from H2RecycleRule (@1) for params, helpers, and parquet
    emission machinery. Overrides `apply()` entirely — the H2_recycle@1
    Variant G mechanic (bank winner, add loser) is NOT used here.

    Parameters added
    ----------------
    pyramid_increment_usd : float (default 10.0)
        Add 0.01 to winner each time loser's floating PnL hits a new low
        at this dollar increment below the previous add level. At 0.01
        loser lot, $10 ≈ 100 pips of adverse on the loser side — clean
        trend-distance measure.
    exit_recovery_usd : float (default 10.0)
        Liquidate basket when loser's floating PnL recovers this many
        dollars from its trough. Symmetric to `pyramid_increment_usd`
        on the recovery side.
    hard_floor_loss_usd : float (default -10.0, must be negative)
        Defensive hard floor — if basket floating PnL drops below this
        threshold, liquidate immediately. Should rarely fire if the
        recovery-based exit is functioning; protects against fast moves
        that exit_recovery can't catch in time.

    State added
    -----------
    _loser_sym              : str  — locked at first pyramid event; the
                              leg used as tripwire/trend-distance sensor
                              for this cycle's duration
    _pyramid_winner_sym     : str  — the leg being pyramided (opposite
                              of _loser_sym)
    _loser_trough_float     : float — running minimum of loser's floating PnL
    _last_add_loser_level   : float — loser_floating at the last pyramid add;
                              the next add fires at this minus pyramid_increment_usd
    _n_pyramids             : int  — pyramid events in current cycle
    _n_liquidations         : int  — total liquidation events (cycles completed)

    Back-reference (injected by BasketRunner.__init__)
    --------------------------------------------------
    basket_runner : BasketRunner | None — used for soft_reset_basket on
                    liquidation. RuntimeError raised if None at liquidation
                    time (defensive — orchestrator should always attach
                    the rule via BasketRunner).
    """

    # --- New parameters ---
    pyramid_increment_usd: float = 10.0
    exit_recovery_usd: float = 10.0
    hard_floor_loss_usd: float = -10.0

    # --- Correlation gate (2026-05-17, isolation-first per operator brief) ---
    # OFF by default — leaving correlation_enabled=False keeps every
    # existing S22-S40 directive byte-identical under this version.
    # When enabled, the rule blocks the FIRST PYRAMID of each cycle if
    # the leg-pair's Pearson correlation (read from leg.df at the bar)
    # falls outside the entry band on BOTH timeframes (1H AND 4H).
    # In-cycle, hysteresis: a cycle is force-liquidated if 1H rho moves
    # OUTSIDE the exit band (drivers locked up = no pyramid edge OR
    # degenerate-synthetic territory).
    correlation_enabled: bool = False
    correlation_column_1h: str = "fx_corr_1h"
    correlation_column_4h: str = "fx_corr_4h"
    # Per-TF enable flags (2026-05-17): for walk-forward windows where
    # one TF's matrix lacks history (e.g., 1H only goes back to 2024 for
    # several USD pairs), set the corresponding flag to False so the
    # gate runs in degraded-but-honest single-TF mode rather than
    # blocking everything because the missing TF returns NaN.
    correlation_use_1h: bool = True
    correlation_use_4h: bool = True
    # Persistence gate (2026-05-17): require correlation to have been
    # in entry band for last N *4H* bars before first pyramid is allowed.
    # 0 = disabled (any single in-band bar allows entry — current default).
    # 3 = require 3 consecutive 4H bars (12 hours of in-band history)
    # before the gate fires. Filters out transient correlation flips that
    # cross the band momentarily and back out. Counted in 4H bars; the
    # internal 5m counter equivalents are persistence * 48.
    correlation_persistence_4h_bars: int = 0
    # Entry band: pyramid permitted only when rho is INSIDE this band on
    # BOTH timeframes. Default targets moderately negative regime
    # (independent drivers without degenerate-synthetic collapse).
    correlation_entry_low: float = -0.70    # too negative -> degenerate synth
    correlation_entry_high: float = -0.20   # too positive -> drivers locked
    # Exit hysteresis: in-cycle, force-liquidate if 1H rho leaves this
    # WIDER band (gap below entry low / above entry high to avoid whipsaw).
    correlation_exit_low: float = -0.85
    correlation_exit_high: float = -0.05

    # --- Version override ---
    version: int = _RULE_VERSION_V5

    # --- New state (initialized in __post_init__ via dataclass defaults) ---
    _loser_sym: Optional[str] = None
    _pyramid_winner_sym: Optional[str] = None
    _loser_trough_float: float = 0.0
    _last_add_loser_level: float = 0.0
    _n_pyramids: int = 0
    _n_liquidations: int = 0
    _n_correlation_blocks: int = 0   # diag: pre-pyramid bars blocked by gate
    _n_correlation_exits: int = 0    # diag: cycles closed via correlation exit
    _consec_in_band_5m: int = 0      # running count of consecutive 5m bars in-band (for persistence gate)

    # Back-reference (populated by BasketRunner.__init__ via injection)
    basket_runner: Optional[BasketRunner] = None

    def __post_init__(self) -> None:
        # Parent validation (trigger_usd, dd_freeze_frac, factor_operator, etc.)
        super().__post_init__()

        # V5-specific validation
        if self.pyramid_increment_usd <= 0:
            raise ValueError(
                f"H2RecycleRuleV5.pyramid_increment_usd must be > 0; "
                f"got {self.pyramid_increment_usd!r}."
            )
        if self.exit_recovery_usd <= 0:
            raise ValueError(
                f"H2RecycleRuleV5.exit_recovery_usd must be > 0; "
                f"got {self.exit_recovery_usd!r}."
            )
        if self.hard_floor_loss_usd >= 0:
            raise ValueError(
                f"H2RecycleRuleV5.hard_floor_loss_usd must be < 0 "
                f"(it's a floor on basket floating, expressed as a "
                f"negative dollar threshold); got {self.hard_floor_loss_usd!r}."
            )
        # Correlation gate validation (only when enabled; defaults are sane).
        if self.correlation_enabled:
            if not (-1.0 <= self.correlation_entry_low <
                    self.correlation_entry_high <= 1.0):
                raise ValueError(
                    f"H2RecycleRuleV5: correlation_entry_low ({self.correlation_entry_low}) "
                    f"must be < correlation_entry_high ({self.correlation_entry_high}), "
                    f"both in [-1.0, 1.0]."
                )
            if not (self.correlation_exit_low <= self.correlation_entry_low):
                raise ValueError(
                    f"H2RecycleRuleV5: correlation_exit_low ({self.correlation_exit_low}) "
                    f"must be <= correlation_entry_low ({self.correlation_entry_low}); "
                    f"hysteresis requires exit band to be WIDER than entry band."
                )
            if not (self.correlation_exit_high >= self.correlation_entry_high):
                raise ValueError(
                    f"H2RecycleRuleV5: correlation_exit_high ({self.correlation_exit_high}) "
                    f"must be >= correlation_entry_high ({self.correlation_entry_high}); "
                    f"hysteresis requires exit band to be WIDER than entry band."
                )

    # ---- Correlation helpers ----------------------------------------------

    def _read_correlation(self, legs: list[BasketLeg], bar_ts: pd.Timestamp
                          ) -> tuple[Optional[float], Optional[float]]:
        """Return (rho_1h, rho_4h) for the current bar from the leg-pair
        FX correlation factor (joined by basket_data_loader). Returns
        (None, None) if columns are missing or the value is NaN.

        Reads from legs[0].df only — both legs see the same correlation
        series (it's a pair-level property; loader joins identical
        columns onto every leg). NaN values during warmup propagate as
        None.
        """
        df = legs[0].df
        rho_1h: Optional[float] = None
        rho_4h: Optional[float] = None
        if self.correlation_column_1h in df.columns:
            try:
                v = float(df.loc[bar_ts, self.correlation_column_1h])
                if not pd.isna(v):
                    rho_1h = v
            except (KeyError, ValueError, TypeError):
                pass
        if self.correlation_column_4h in df.columns:
            try:
                v = float(df.loc[bar_ts, self.correlation_column_4h])
                if not pd.isna(v):
                    rho_4h = v
            except (KeyError, ValueError, TypeError):
                pass
        return rho_1h, rho_4h

    def _correlation_in_entry_band(self, rho_1h: Optional[float],
                                   rho_4h: Optional[float]) -> bool:
        """True if all ENABLED timeframes have rho inside [entry_low,
        entry_high]. Disabled timeframes (correlation_use_1h/4h=False)
        are skipped entirely. Missing values on an ENABLED TF fail the
        gate (defensive: NO data on an enabled TF = NO entry)."""
        if self.correlation_use_1h:
            if rho_1h is None:
                return False
            if not (self.correlation_entry_low <= rho_1h <= self.correlation_entry_high):
                return False
        if self.correlation_use_4h:
            if rho_4h is None:
                return False
            if not (self.correlation_entry_low <= rho_4h <= self.correlation_entry_high):
                return False
        # At least one TF must be enabled (otherwise the gate is meaningless).
        return self.correlation_use_1h or self.correlation_use_4h

    def _correlation_breached_exit(self, rho_1h: Optional[float],
                                   rho_4h: Optional[float] = None) -> bool:
        """True if in-cycle rho has moved OUTSIDE the WIDER exit band
        on any ENABLED timeframe (drivers locked up OR degenerate-
        synthetic territory). Disabled timeframes are skipped. Missing
        value on an enabled TF does NOT trigger exit (avoids spurious
        early-exits when data is absent at a single bar)."""
        if self.correlation_use_1h and rho_1h is not None:
            if not (self.correlation_exit_low <= rho_1h <= self.correlation_exit_high):
                return True
        if self.correlation_use_4h and rho_4h is not None:
            if not (self.correlation_exit_low <= rho_4h <= self.correlation_exit_high):
                return True
        return False

    # ---- BasketRule.apply override ----------------------------------------

    def apply(self, legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp) -> None:
        if self.harvested:
            return

        if self._first_bar_ts is None:
            self._first_bar_ts = bar_ts

        # ---- Data gap (same as @1/@4) ----
        bar_closes: dict[str, float] = {}
        for leg in legs:
            try:
                bar_closes[leg.symbol] = float(leg.df.loc[bar_ts, "close"])
            except (KeyError, ValueError):
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes={l.symbol: float("nan") for l in legs},
                    leg_float={l.symbol: 0.0 for l in legs},
                    floating_total=0.0,
                    equity=self.starting_equity + self.realized_total,
                    margin_used=0.0,
                    dd_freeze=False, margin_freeze=False, regime_blocked=False,
                    factor_val=None,
                    skip_reason="RULE_NOT_INVOKED",
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

        # ---- Floating + equity (same as @1/@4, now cross-pair aware via V3 helpers) ----
        ref_closes = _build_ref_closes(legs, bar_ts)
        leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], ref_closes) for leg in legs}
        floating_total = sum(leg_float.values())
        equity = self.starting_equity + self.realized_total + floating_total

        # Tradelevel enrichment: lazy per-leg snapshot (detects initial open
        # + pyramid commits that shift winner avg-entry + soft_reset basket
        # cycles), then per-bar excursion update. Pyramid commits silently
        # re-baseline ctx + MFE/MAE (no trade row emitted, position stays
        # open) — see _maybe_resnapshot_legs docstring for the documented
        # decision.
        self._maybe_resnapshot_legs(legs, bar_ts, bar_closes)
        self._update_cycle_excursions(legs, bar_ts, bar_closes)

        # ---- Exit checks (same as @1/@4) ----
        if equity >= self.harvest_target_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TARGET")
            return
        if self.equity_floor_usd is not None and equity <= self.equity_floor_usd:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="FLOOR")
            return
        if equity <= 0:
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="BLOWN")
            return
        if (
            self.time_stop_days is not None
            and self._first_bar_ts is not None
            and (bar_ts - self._first_bar_ts).days >= self.time_stop_days
        ):
            self._exit_all(legs, i, bar_ts, bar_closes, leg_float, reason="TIME")
            return

        # ---- Freeze checks (same as @1/@4) ----
        margin_used = sum(_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage, ref_closes) for leg in legs)
        dd_breach = (floating_total < 0) and (abs(floating_total) >= self.dd_freeze_frac * equity)
        margin_breach = margin_used >= self.margin_freeze_frac * equity
        if dd_breach:
            self._n_dd_freezes += 1
        if margin_breach:
            self._n_margin_freezes += 1

        # ---- Regime gate (same as @1, but typical V5 directive uses
        #      inverted operator: factor_operator='<=' with factor_min=5
        #      → gate fires (blocks pyramid) when compression > 5 (chop).
        #      The factor_operator field is inherited from parent.) ----
        primary_df = legs[0].df
        column_missing = self.factor_column not in primary_df.columns
        factor_val: Optional[float] = None
        factor_present_but_nan = False
        if not column_missing:
            try:
                raw_val = float(primary_df.loc[bar_ts, self.factor_column])
                if pd.isna(raw_val):
                    factor_present_but_nan = True
                else:
                    factor_val = raw_val
            except (KeyError, ValueError, TypeError):
                column_missing = True
        if factor_val is None:
            regime_blocked = False
        elif self.factor_operator == ">=":
            regime_blocked = factor_val < self.factor_min
        elif self.factor_operator == "<=":
            regime_blocked = factor_val > self.factor_min
        else:  # "abs_<="
            regime_blocked = abs(factor_val) > self.factor_min
        if factor_present_but_nan or regime_blocked:
            self._n_regime_freezes += 1

        # ---- Correlation persistence counter update (runs every bar) ----
        # Tracks consecutive 5m bars where the entry-band check passes,
        # so the pre-pyramid gate can require N continuous in-band bars
        # before allowing first pyramid. 0 = disabled.
        if self.correlation_enabled and self.correlation_persistence_4h_bars > 0:
            _rho_1h_p, _rho_4h_p = self._read_correlation(legs, bar_ts)
            if self._correlation_in_entry_band(_rho_1h_p, _rho_4h_p):
                self._consec_in_band_5m += 1
            else:
                self._consec_in_band_5m = 0

        # ---- Identify CURRENT bar's winner / loser (highest / lowest floating) ----
        # If we're in a pyramid cycle, we use the LOCKED _loser_sym
        # rather than the bar-identified loser (the trend's loser side
        # is fixed at first pyramid for the cycle's duration).
        floats_sorted = sorted(leg_float.items(), key=lambda x: x[1], reverse=True)
        bar_winner_sym, bar_winner_float = floats_sorted[0]
        bar_loser_sym, bar_loser_float = floats_sorted[-1]

        # ---- Branch: in pyramid cycle or pre-pyramid ----
        if self._n_pyramids > 0:
            # We're in a cycle — use locked loser identity
            cur_loser_float = leg_float[self._loser_sym]
            cur_winner_sym = self._pyramid_winner_sym

            # Update trough (running min)
            if cur_loser_float < self._loser_trough_float:
                self._loser_trough_float = cur_loser_float

            # Exit trigger 1: loser recovered from trough by exit_recovery_usd
            if cur_loser_float > self._loser_trough_float + self.exit_recovery_usd:
                self._commit_liquidation(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    reason="TREND_LIQUIDATE_RECOVERY",
                )
                return

            # Exit trigger 2: hard floor on basket floating
            if floating_total <= self.hard_floor_loss_usd:
                self._commit_liquidation(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    reason="TREND_LIQUIDATE_FLOOR",
                )
                return

            # Exit trigger 3 (2026-05-17): correlation regime breach.
            # Only fires when enabled. Liquidates the cycle if 1H rho has
            # moved OUTSIDE the WIDER exit band (drivers locked up =
            # no pyramid edge remaining, OR degenerate-synthetic territory).
            if self.correlation_enabled:
                rho_1h, rho_4h = self._read_correlation(legs, bar_ts)
                if self._correlation_breached_exit(rho_1h, rho_4h):
                    self._n_correlation_exits += 1
                    self._commit_liquidation(
                        legs, i, bar_ts, bar_closes, leg_float, floating_total,
                        equity, margin_used, factor_val,
                        reason="TREND_LIQUIDATE_CORRELATION",
                    )
                    return

            # Hard freezes block pyramid (but not exit checks above)
            if dd_breach or margin_breach or regime_blocked:
                skip = (
                    "DD_FREEZE" if dd_breach
                    else "MARGIN_FREEZE" if margin_breach
                    else "REGIME_GATE"
                )
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes=bar_closes, leg_float=leg_float,
                    floating_total=floating_total, equity=equity, margin_used=margin_used,
                    dd_freeze=dd_breach, margin_freeze=margin_breach, regime_blocked=regime_blocked,
                    factor_val=factor_val,
                    skip_reason=skip,
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

            # Pyramid trigger: loser dropped below last add level by pyramid_increment
            trigger_level = self._last_add_loser_level - self.pyramid_increment_usd
            if cur_loser_float <= trigger_level:
                # Find the winner leg object by symbol
                winner_leg = next(l for l in legs if l.symbol == cur_winner_sym)
                self._commit_pyramid(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    winner=winner_leg, cur_loser_float=cur_loser_float,
                )
                return

            # No add, no exit — just record holding
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="HOLDING_PYRAMID",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )

        else:
            # Pre-pyramid: no cycle started yet for this basket
            # First pyramid fires when bar_loser_float <= -pyramid_increment_usd
            # (= 100 pips of adverse on the loser side at $10 increment for 0.01 lot)
            if dd_breach or margin_breach or regime_blocked:
                skip = (
                    "DD_FREEZE" if dd_breach
                    else "MARGIN_FREEZE" if margin_breach
                    else "REGIME_GATE"
                )
                self._record_bar(
                    legs, i, bar_ts,
                    bar_closes=bar_closes, leg_float=leg_float,
                    floating_total=floating_total, equity=equity, margin_used=margin_used,
                    dd_freeze=dd_breach, margin_freeze=margin_breach, regime_blocked=regime_blocked,
                    factor_val=factor_val,
                    skip_reason=skip,
                    recycle_attempted=False, recycle_executed=False,
                    harvest_triggered=False,
                )
                return

            # Correlation gate (2026-05-17): block FIRST PYRAMID if the
            # leg-pair correlation is outside the entry band on either
            # timeframe. Only fires when enabled — disabled is byte-
            # identical to V5 pre-patch behavior.
            if self.correlation_enabled:
                rho_1h, rho_4h = self._read_correlation(legs, bar_ts)
                if not self._correlation_in_entry_band(rho_1h, rho_4h):
                    self._n_correlation_blocks += 1
                    self._record_bar(
                        legs, i, bar_ts,
                        bar_closes=bar_closes, leg_float=leg_float,
                        floating_total=floating_total, equity=equity, margin_used=margin_used,
                        dd_freeze=False, margin_freeze=False, regime_blocked=False,
                        factor_val=factor_val,
                        skip_reason="CORRELATION_GATE",
                        recycle_attempted=False, recycle_executed=False,
                        harvest_triggered=False,
                    )
                    return
                # Persistence sub-gate: require N consecutive 4H bars
                # (= N*48 consecutive 5m bars) of in-band correlation
                # before allowing first pyramid. Filters transient flips.
                if self.correlation_persistence_4h_bars > 0:
                    required_5m_bars = self.correlation_persistence_4h_bars * 48
                    if self._consec_in_band_5m < required_5m_bars:
                        self._n_correlation_blocks += 1
                        self._record_bar(
                            legs, i, bar_ts,
                            bar_closes=bar_closes, leg_float=leg_float,
                            floating_total=floating_total, equity=equity, margin_used=margin_used,
                            dd_freeze=False, margin_freeze=False, regime_blocked=False,
                            factor_val=factor_val,
                            skip_reason="CORRELATION_PERSISTENCE",
                            recycle_attempted=False, recycle_executed=False,
                            harvest_triggered=False,
                        )
                        return

            if bar_loser_float <= -self.pyramid_increment_usd:
                # First pyramid event of the cycle — lock loser identity
                winner_leg = next(l for l in legs if l.symbol == bar_winner_sym)
                self._loser_sym = bar_loser_sym
                self._pyramid_winner_sym = bar_winner_sym
                self._loser_trough_float = bar_loser_float
                # _last_add_loser_level starts at 0 for the first trigger calc;
                # set it to current loser_float now so the NEXT trigger fires at
                # current - pyramid_increment_usd.
                self._commit_pyramid(
                    legs, i, bar_ts, bar_closes, leg_float, floating_total,
                    equity, margin_used, factor_val,
                    winner=winner_leg, cur_loser_float=bar_loser_float,
                )
                return

            # Waiting for first pyramid trigger
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=False, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="WAITING_FOR_PYRAMID",
                recycle_attempted=False, recycle_executed=False,
                harvest_triggered=False,
            )

    # ---- PYRAMID action ---------------------------------------------------

    def _commit_pyramid(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        winner: BasketLeg, cur_loser_float: float,
    ) -> None:
        """Add `add_lot` to winner; update state."""
        new_winner_lot = winner.lot + self.add_lot

        # Margin projection (cross-pair aware via V3 helper).
        # Temporarily mutate winner lot to project post-add margin, then restore.
        ref_closes = _build_ref_closes(legs, bar_ts)
        orig_winner_lot = winner.lot
        winner.lot = new_winner_lot
        proj_margin = sum(
            _leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage, ref_closes)
            for leg in legs
        )
        winner.lot = orig_winner_lot
        if proj_margin >= self.margin_freeze_frac * equity:
            self._n_margin_freezes += 1
            self._record_bar(
                legs, i, bar_ts,
                bar_closes=bar_closes, leg_float=leg_float,
                floating_total=floating_total, equity=equity, margin_used=margin_used,
                dd_freeze=False, margin_freeze=True, regime_blocked=False,
                factor_val=factor_val,
                skip_reason="PYRAMID_REJECTED_MARGIN",
                recycle_attempted=True, recycle_executed=False,
                harvest_triggered=False,
            )
            return

        # Commit: weighted-avg new entry on winner, lot grows
        winner_old_avg = winner.state.entry_price
        winner_old_lot = winner.lot
        new_avg = (
            (winner_old_lot * winner_old_avg + self.add_lot * bar_closes[winner.symbol])
            / new_winner_lot
        )
        winner.state.entry_price = new_avg
        winner.state.entry_index = i
        winner.lot = new_winner_lot

        # Update rule state
        self._last_add_loser_level = cur_loser_float
        self._n_pyramids += 1

        # Event log
        winner_leg_idx = legs.index(winner)
        loser_leg_idx = next(j for j, l in enumerate(legs) if l.symbol == self._loser_sym)
        event = {
            "bar_index":              i,
            "bar_ts":                 bar_ts,
            "action":                 "PYRAMID",
            "winner_symbol":          winner.symbol,
            "loser_symbol":           self._loser_sym,
            "add_lot":                self.add_lot,
            "winner_old_lot":         winner_old_lot,
            "winner_new_lot":         new_winner_lot,
            "winner_old_avg":         winner_old_avg,
            "winner_new_avg":         new_avg,
            "cur_loser_float":        cur_loser_float,
            "loser_trough_float":     self._loser_trough_float,
            "n_pyramids":             self._n_pyramids,
            "realized_total":         self.realized_total,
            "floating_total":         floating_total,
            "equity_before":          equity,
        }
        self.recycle_events.append(event)

        # Recompute leg_float after the add (new lot on winner)
        post_ref_closes = _build_ref_closes(legs, bar_ts)
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], post_ref_closes) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason="PYRAMID_ADDED",
            recycle_attempted=True, recycle_executed=False,
            harvest_triggered=False,
            winner_leg_idx=winner_leg_idx,
            loser_leg_idx=loser_leg_idx,
        )

    # ---- LIQUIDATION action ------------------------------------------------

    def _commit_liquidation(
        self,
        legs: list[BasketLeg], i: int, bar_ts: pd.Timestamp,
        bar_closes: dict[str, float], leg_float: dict[str, float],
        floating_total: float, equity: float, margin_used: float,
        factor_val: Optional[float],
        reason: str,
    ) -> None:
        """Realize all floating, soft_reset basket, restore pre-pyramid state."""
        if self.basket_runner is None:
            raise RuntimeError(
                "H2RecycleRuleV5._commit_liquidation: basket_runner is None. "
                "Either the rule was instantiated outside a BasketRunner, or "
                "the back-reference injection in BasketRunner.__init__ failed."
            )

        # Realize all floating into rule's realized_total (rule-side accounting)
        realized_at_liquidation = floating_total
        old_realized = self.realized_total
        self.realized_total += realized_at_liquidation

        # Capture pre-reset state for event log
        pre_reset_lots = {leg.symbol: leg.lot for leg in legs}
        pre_reset_loser_sym = self._loser_sym
        pre_reset_winner_sym = self._pyramid_winner_sym
        pre_reset_trough = self._loser_trough_float
        pre_reset_n_pyramids = self._n_pyramids

        # Soft reset (closes positions + reopens fresh at initial_lot at current prices)
        self.basket_runner.soft_reset_basket(
            at_index=i, at_ts=bar_ts, at_prices=bar_closes,
        )

        # Reset rule state (back to pre-pyramid)
        self._loser_sym = None
        self._pyramid_winner_sym = None
        self._loser_trough_float = 0.0
        self._last_add_loser_level = 0.0
        self._n_pyramids = 0
        self._n_liquidations += 1

        # Event log
        event = {
            "bar_index":              i,
            "bar_ts":                 bar_ts,
            "action":                 reason,  # TREND_LIQUIDATE_RECOVERY | TREND_LIQUIDATE_FLOOR
            "loser_symbol":           pre_reset_loser_sym,
            "winner_symbol":          pre_reset_winner_sym,
            "loser_trough_float":     pre_reset_trough,
            "n_pyramids_in_cycle":    pre_reset_n_pyramids,
            "pre_reset_lots":         pre_reset_lots,
            "realized_at_liquidation": realized_at_liquidation,
            "realized_total_before":  old_realized,
            "realized_total_after":   self.realized_total,
            "floating_total_before":  floating_total,
            "equity_before":          equity,
        }
        self.recycle_events.append(event)

        # After soft_reset, leg state is fresh (lots=initial, entry=bar_close,
        # leg_float ~= 0 since entry==mark). Recompute and record.
        post_ref_closes = _build_ref_closes(legs, bar_ts)
        post_leg_float = {leg.symbol: _leg_pnl_usd(leg, bar_closes[leg.symbol], post_ref_closes) for leg in legs}
        post_floating_total = sum(post_leg_float.values())
        # Equity invariant: total equity unchanged by liquidation+reset
        # (floating moved into realized, then reopened at market = 0 float).
        self._record_bar(
            legs, i, bar_ts,
            bar_closes=bar_closes, leg_float=post_leg_float,
            floating_total=post_floating_total, equity=equity, margin_used=margin_used,
            dd_freeze=False, margin_freeze=False, regime_blocked=False,
            factor_val=factor_val,
            skip_reason=reason,
            recycle_attempted=False, recycle_executed=False,
            harvest_triggered=False,
        )


__all__ = ["H2RecycleRuleV5"]
