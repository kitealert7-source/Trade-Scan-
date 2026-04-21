"""PROFILES + PortfolioState — single-profile capital simulation state.

This is the core module. Imports from:
  - capital_events (TradeEvent, OpenTrade, compute_signal_hash, EVENT_* constants)
  - capital_broker_spec (_normalize_lot_broker)

NO reverse dependency. Other modules import FROM this module, not into it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from tools.capital.capital_broker_spec import _normalize_lot_broker
from tools.capital.capital_events import OpenTrade, TradeEvent, compute_signal_hash


FLOAT_TOLERANCE = 1e-9


# ======================================================================
# CAPITAL PROFILES
# ======================================================================

PROFILES = {
    # Baseline diagnostic: raw directional edge at minimum lot — no constraints.
    # raw_lot_mode bypasses all sizing/heat/leverage gates; every signal executes
    # at 0.01 lot unconditionally. Useful as a "is the signal itself real?" probe.
    "RAW_MIN_LOT_V1": {
        "starting_capital": 1000.0,
        "risk_per_trade": 0.0,
        "heat_cap": 9999.0,
        "leverage_cap": 9999,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "raw_lot_mode": True,
    },
    # Retail-amateur conservative: $1k seed, 2% risk with $20 floor.
    # risk = max(2% of current equity, $20). Floor keeps trade size meaningful
    # if equity dips below starting; 2% path allows compounding as equity grows.
    # No heat/leverage caps (real retail has no portfolio heat monitor).
    # Trades below min_lot SKIP honestly (no fallback).
    "FIXED_USD_V1": {
        "starting_capital": 1000.0,
        "risk_per_trade": 0.02,
        "fixed_risk_usd_floor": 20.0,
        "heat_cap": 9999.0,
        "leverage_cap": 9999,
        "min_lot": 0.01,
        "lot_step": 0.01,
    },
    # Retail-amateur aggressive: $1k seed, tier-ramp risk (2% base, +1% per
    # 2x equity doubling, capped at 5%, symmetric retrace). No heat/leverage
    # caps. Trades below min_lot SKIP. retail_max_lot=10 enforces broker-
    # realistic ceiling — trades requiring more than 10 lots SKIP (OctaFx
    # vol_max=500 is an admin/marketing cap; real retail above 10 lots
    # brings slippage and platform scrutiny).
    "REAL_MODEL_V1": {
        "starting_capital": 1000.0,
        "risk_per_trade": 0.02,
        "heat_cap": 9999.0,
        "leverage_cap": 9999,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "tier_ramp": True,
        "tier_base_pct": 0.02,
        "tier_step_pct": 0.01,
        "tier_cap_pct": 0.05,
        "tier_multiplier": 2.0,
        "retail_max_lot": 10.0,
    },
    # Retail defensive: same as REAL_MODEL_V1 but tier_cap_pct lowered from 5%
    # to 3%. Defensible choice for tail-dependent strategies. S21 sweep evidence:
    # eliminates MC blow-ups (7 -> 0), halves realized Max DD (23.6% -> 16.2%),
    # lifts PF after top-5% removal (0.37 -> 0.50), preserves compounding.
    # Opt-in only via --profile; not in the profile_selector candidate set.
    "REAL_MODEL_V2_DEFENSIVE": {
        "starting_capital": 1000.0,
        "risk_per_trade": 0.02,
        "heat_cap": 9999.0,
        "leverage_cap": 9999,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "tier_ramp": True,
        "tier_base_pct": 0.02,
        "tier_step_pct": 0.01,
        "tier_cap_pct": 0.03,
        "tier_multiplier": 2.0,
        "retail_max_lot": 10.0,
    },
}


# ======================================================================
# PORTFOLIO STATE
# ======================================================================

@dataclass
class PortfolioState:
    """Tracks running portfolio equity and constraints for one capital profile."""
    profile_name: str
    starting_capital: float
    risk_per_trade: float
    heat_cap: float
    leverage_cap: float
    min_lot: float
    lot_step: float
    concurrency_cap: Optional[int] = None
    fixed_risk_usd: Optional[float] = None    # Fixed USD mode (e.g. $50)
    dynamic_scaling: bool = False              # Dynamic heat-aware scaling
    min_position_pct: float = 0.0             # Skip if scaled < X% of base
    min_lot_fallback: bool = False            # Execute at min_lot if sized < min_lot
    max_risk_multiple: Optional[float] = 3.0  # Max allowable risk/target ratio (None=Uncapped)
    track_risk_override: bool = False         # Log override metrics
    raw_lot_mode: bool = False                # Bypass all gates — execute every signal at min_lot
    # --- Tier-ramp risk schedule (REAL_MODEL_V1) ---
    # When enabled, risk_per_trade increases by +1% for each equity doubling
    # (2x starting_capital crossing), capped at 5%. Symmetric retrace.
    tier_ramp: bool = False
    tier_base_pct: float = 0.02               # Starting risk fraction (2%)
    tier_step_pct: float = 0.01               # +1% per doubling
    tier_cap_pct: float = 0.05                # Cap at 5%
    tier_multiplier: float = 2.0              # Equity-crossing multiplier (2x)
    # --- Retail-prudence per-trade volume cap ---
    # Separate from broker vol_max (500 at OctaFx — CFD admin cap, not liquidity).
    # A retail account shouldn't actually execute 50+ lot orders regardless of
    # equity: slippage, platform scrutiny, and one-sided CFD books make it
    # dangerous. When set, trades with normalized_lot > retail_max_lot are
    # SKIPPED (not scaled down) so rejection_rate honestly reflects executability.
    retail_max_lot: Optional[float] = None
    # Running state
    equity: float = 0.0
    realized_pnl: float = 0.0
    total_open_risk: float = 0.0
    total_notional: float = 0.0
    peak_equity: float = 0.0
    max_drawdown_usd: float = 0.0
    max_concurrent: int = 0
    total_risk_overrides: int = 0
    risk_multiples: List[float] = field(default_factory=list)

    open_trades: Dict[str, OpenTrade] = field(default_factory=dict)
    rejection_log: List[dict] = field(default_factory=list)
    equity_timeline: List[Tuple[datetime, float]] = field(default_factory=list)
    closed_trades_log: List[dict] = field(default_factory=list)  # Phase 5
    heat_samples: List[float] = field(default_factory=list)       # Phase 5
    symbol_notional: Dict[str, float] = field(default_factory=dict)  # Per-symbol exposure

    # Counters
    total_accepted: int = 0
    total_rejected: int = 0
    accepted_trade_ids: List[str] = field(default_factory=list)

    # Assertion tracking
    _heat_breach: bool = False
    _leverage_breach: bool = False
    _equity_negative: bool = False

    def __post_init__(self):
        # Invariant: risk_per_trade in [0, 0.50]; starting_capital > 0.
        # Malformed profile would otherwise silently produce oversized lots or
        # divide-by-zero downstream.
        _MAX_RISK_PER_TRADE = 0.50
        if not (0.0 <= self.risk_per_trade <= _MAX_RISK_PER_TRADE):
            raise ValueError(
                f"[CAPITAL_WRAPPER] risk_per_trade={self.risk_per_trade} out of range "
                f"[0, {_MAX_RISK_PER_TRADE}] for profile {self.profile_name!r}. "
                f"Check PROFILES dict in capital_wrapper.py."
            )
        if self.starting_capital <= 0.0:
            raise ValueError(
                f"[CAPITAL_WRAPPER] starting_capital={self.starting_capital} must be > 0 "
                f"for profile {self.profile_name!r}."
            )
        self.equity = self.starting_capital
        self.peak_equity = self.starting_capital

    # ------------------------------------------------------------------
    # LOT SIZING
    # ------------------------------------------------------------------

    def _floor_to_step(self, lots: float) -> float:
        """Floor lot size to nearest lot_step."""
        steps = math.floor(lots / self.lot_step)
        return round(steps * self.lot_step, 8)

    def _compute_risk_capital(self) -> tuple:
        """Single source of truth for risk capital computation.

        Returns (base_risk_capital, risk_capital) where:
          - base_risk_capital: pre-scaling amount (fixed USD or fractional)
          - risk_capital: after dynamic heat scaling + clamp
        """
        if self.fixed_risk_usd is not None:
            base_risk_capital = self.fixed_risk_usd
        elif self.tier_ramp and self.starting_capital > 0 and self.equity > 0:
            # REAL_MODEL_V1 tier ramp: +step% per tier_multiplier-crossing of equity.
            ratio = self.equity / self.starting_capital
            if ratio < 1.0:
                tier = 0
            else:
                tier = int(math.floor(math.log(ratio) / math.log(self.tier_multiplier)))
                if tier < 0:
                    tier = 0
            effective_risk = min(self.tier_base_pct + self.tier_step_pct * tier,
                                 self.tier_cap_pct)
            base_risk_capital = self.equity * effective_risk
        else:
            base_risk_capital = self.equity * self.risk_per_trade

        risk_capital = base_risk_capital

        if self.dynamic_scaling and self.equity > 0:
            remaining_heat_usd = (self.heat_cap * self.equity) - self.total_open_risk
            remaining_heat_usd = max(remaining_heat_usd, 0.0)
            risk_capital = min(risk_capital, remaining_heat_usd)

        risk_capital = max(risk_capital, 0.0)
        return base_risk_capital, risk_capital

    def compute_lot_size(self, risk_distance: float, usd_per_pu_per_lot: float,
                         _precomputed_risk: tuple = None) -> float:
        """
        Multi-mode position sizing.

        Modes:
          - Fixed USD:        risk_capital = fixed_risk_usd
          - Fixed Fractional: risk_capital = equity * risk_per_trade
          - Dynamic Scaling:  risk_capital = min(base, remaining_heat)

        Min position filter: skip if scaled risk < min_position_pct of base.

        Args:
            _precomputed_risk: Optional (base_risk_capital, risk_capital) tuple
                from _compute_risk_capital(). When provided, skips recomputation.
        """
        if _precomputed_risk is not None:
            base_risk_capital, risk_capital = _precomputed_risk
        else:
            base_risk_capital, risk_capital = self._compute_risk_capital()

        # Step C: Min position filter
        if self.min_position_pct > 0 and base_risk_capital > 0:
            if risk_capital < base_risk_capital * self.min_position_pct:
                return 0.0  # Will be caught by LOT_TOO_SMALL rejection

        risk_per_lot = risk_distance * usd_per_pu_per_lot
        if risk_per_lot <= 0:
            return 0.0
        raw_lots = risk_capital / risk_per_lot
        return self._floor_to_step(raw_lots)

    # ------------------------------------------------------------------
    # ENTRY PROCESSING
    # ------------------------------------------------------------------

    def process_entry(self, event: TradeEvent, usd_per_pu_per_lot: float,
                      contract_size: float) -> bool:
        """
        Process an ENTRY event. Returns True if accepted, False if rejected.

        Steps:
          0. Concurrency cap
          1-2. Resolve lot (compute + broker normalize + retail cap + min_lot fallback)
          3. Compute trade risk + notional
          3.5-5. Risk multiple + heat cap + leverage cap
          6. Record open trade + emit timeline/invariants
        """
        # RAW mode: bypass all gates — unconditionally accept at min_lot
        if self.raw_lot_mode:
            return self._process_entry_raw(event, usd_per_pu_per_lot)

        # 0. Explicit concurrency cap check (if configured).
        if self.concurrency_cap is not None and len(self.open_trades) >= int(self.concurrency_cap):
            self._reject(
                event,
                "CONCURRENCY_CAP",
                f"open={len(self.open_trades)} >= cap={int(self.concurrency_cap)}",
            )
            return False

        # 1-2. Resolve lot size (handles compute, broker normalize, retail cap, min_lot fallback)
        lot_result = self._resolve_lot(event, usd_per_pu_per_lot)
        if lot_result is None:
            return False
        lot_size, risk_override, target_risk = lot_result

        # 3. Compute trade risk and notional (USD-normalised)
        #    usd_per_pu_per_lot = contract_size × quote_ccy_to_USD_rate
        #    → notional = lot × entry_price × usd_per_pu_per_lot
        #      = lot × entry_price × contract_size × rate   (USD for all pairs)
        #    For EURUSD (rate=1): lot × 1.09 × 100000 × 1.0  = USD notional  ✓
        #    For USDJPY (rate=1/148): lot × 148 × 100000 × (1/148) = lot × 100000 ✓
        trade_risk_usd = event.risk_distance * usd_per_pu_per_lot * lot_size
        trade_notional = lot_size * event.entry_price * usd_per_pu_per_lot

        # 3.5 + 4 + 5. Risk multiple + heat cap + leverage cap.
        risk_multiple = self._check_risk_constraints(
            event, risk_override, target_risk, trade_risk_usd, trade_notional,
        )
        if risk_multiple is None:
            return False

        # 6. Accept
        self._record_open_trade(
            event, lot_size, usd_per_pu_per_lot, trade_risk_usd, trade_notional,
            risk_override, target_risk, risk_multiple,
        )
        self._emit_accepted_trade(event, check_invariants=True)
        return True

    # ------------------------------------------------------------------
    # process_entry helpers (Phase A decomposition)
    # ------------------------------------------------------------------

    def _process_entry_raw(self, event: TradeEvent, usd_per_pu_per_lot: float) -> bool:
        """RAW mode: bypass all gates — accept unconditionally at min_lot.

        No risk_override bookkeeping and no invariant check (gates bypassed).
        """
        lot_size = self.min_lot
        trade_risk_usd = event.risk_distance * usd_per_pu_per_lot * lot_size
        trade_notional  = lot_size * event.entry_price * usd_per_pu_per_lot
        trade = OpenTrade(
            trade_id=event.trade_id, symbol=event.symbol, direction=event.direction,
            entry_price=event.entry_price, exit_price=event.exit_price, lot_size=lot_size,
            risk_usd=trade_risk_usd, notional_usd=trade_notional,
            risk_distance=event.risk_distance,
            usd_per_price_unit_per_lot=usd_per_pu_per_lot,
            entry_timestamp=event.timestamp,
            initial_stop_price=event.initial_stop_price, atr_entry=event.atr_entry,
            r_multiple=event.r_multiple, volatility_regime=event.volatility_regime,
            trend_regime=event.trend_regime, trend_label=event.trend_label,
        )
        self.open_trades[event.trade_id] = trade
        self.total_open_risk += trade_risk_usd
        self.total_notional  += trade_notional
        self.symbol_notional[event.symbol] = self.symbol_notional.get(event.symbol, 0.0) + trade_notional
        self.total_accepted += 1
        self.accepted_trade_ids.append(event.trade_id)
        if len(self.open_trades) > self.max_concurrent:
            self.max_concurrent = len(self.open_trades)
        self.equity_timeline.append((event.timestamp, self.equity))
        return True

    def _resolve_lot(self, event: TradeEvent, usd_per_pu_per_lot: float):
        """Steps 1–2: compute lot + broker normalize + retail cap + min_lot fallback.

        Returns (lot_size, risk_override, target_risk) on accept, or None on reject
        (rejection already logged via self._reject).
        """
        # 1. Compute risk capital once — used for both lot sizing and risk multiple check
        _risk = self._compute_risk_capital()
        target_risk = _risk[1]

        lot_size = self.compute_lot_size(event.risk_distance, usd_per_pu_per_lot,
                                         _precomputed_risk=_risk)

        # 1.5 Broker volume normalization — must match live execution order exactly.
        #   sequence: compute_lot → normalize_lot → cap checks → simulate
        #   None return = lot below volume_min → drop trade (no min-lot fallback here).
        lot_size = _normalize_lot_broker(lot_size, event.symbol)
        if lot_size is None:
            self._reject(event, "LOT_BELOW_VOL_MIN",
                         f"normalized_lot < volume_min after broker spec alignment"
                         f"  symbol={event.symbol}")
            return None

        # 1.75 Retail-prudence cap — SKIP (don't scale) so rejection_rate tells
        #       the truth about executability. CFD broker vol_max (500) already
        #       applied above by _normalize_lot_broker; this is the tighter
        #       retail-reality ceiling.
        if self.retail_max_lot is not None and lot_size > self.retail_max_lot:
            self._reject(event, "RETAIL_MAX_LOT_EXCEEDED",
                         f"normalized_lot={lot_size:.2f} > retail_max={self.retail_max_lot:.2f}"
                         f"  symbol={event.symbol}")
            return None

        # 2. Min lot check with fallback
        risk_override = False

        if lot_size < self.min_lot:
            if self.min_lot_fallback:
                lot_size = self.min_lot
                risk_override = True
            else:
                self._reject(event, "LOT_TOO_SMALL",
                             f"computed={lot_size:.4f} < min={self.min_lot}")
                return None

        return lot_size, risk_override, target_risk

    def _check_risk_constraints(self, event: TradeEvent, risk_override: bool,
                                target_risk: float, trade_risk_usd: float,
                                trade_notional: float):
        """Steps 3.5 + 4 + 5: risk multiple + heat cap + leverage cap.

        Returns computed risk_multiple on accept, or None on reject (logged).
        Override tracking counters are updated here only after the check passes.
        """
        # 3.5 Risk Multiple Safety Check
        risk_multiple = trade_risk_usd / target_risk if target_risk > 0 else float("inf")
        if risk_override:
            if self.max_risk_multiple is not None:
                if risk_multiple > self.max_risk_multiple:
                    reason_str = "RISK_MULTIPLE_EXCEEDED" if self.profile_name == "BOUNDED_MIN_LOT_V1" else "RISK_MULT_EXCEEDED"
                    self._reject(event, reason_str,
                                 f"multiple={risk_multiple:.2f} > cap={self.max_risk_multiple}")
                    return None
            self.total_risk_overrides += 1
            self.risk_multiples.append(risk_multiple)

        # 4. Heat cap check
        #    When dynamic_scaling is enabled, compute_lot_size already
        #    clamped the position to fit remaining heat. Only reject if
        #    a rounding edge case still causes a breach.
        new_risk = self.total_open_risk + trade_risk_usd
        heat_pct = new_risk / self.equity if self.equity > 0 else float('inf')
        if heat_pct > self.heat_cap + FLOAT_TOLERANCE:
            if self.dynamic_scaling:
                self._reject(event, "HEAT_CAP_EDGE",
                             f"dynamic_scaled but rounding breach: {heat_pct:.4f} > {self.heat_cap}")
            else:
                self._reject(event, "HEAT_CAP",
                             f"would_be={heat_pct:.4f} > cap={self.heat_cap}")
            return None

        # 5. Leverage cap check
        new_notional = self.total_notional + trade_notional
        leverage_ratio = new_notional / self.equity if self.equity > 0 else float('inf')
        if leverage_ratio > self.leverage_cap + FLOAT_TOLERANCE:
            self._reject(event, "LEVERAGE_CAP",
                         f"would_be={leverage_ratio:.2f}x > cap={self.leverage_cap}x")
            return None

        return risk_multiple

    def _record_open_trade(self, event: TradeEvent, lot_size: float,
                           usd_per_pu_per_lot: float, trade_risk_usd: float,
                           trade_notional: float, risk_override: bool,
                           target_risk: float, risk_multiple: float) -> OpenTrade:
        """Step 6: build OpenTrade and mutate running state.

        Updates open_trades, total_open_risk, total_notional, symbol_notional,
        total_accepted, accepted_trade_ids, and max_concurrent.
        """
        trade = OpenTrade(
            trade_id=event.trade_id,
            symbol=event.symbol,
            direction=event.direction,
            entry_price=event.entry_price,
            exit_price=event.exit_price,
            lot_size=lot_size,
            risk_usd=trade_risk_usd,
            notional_usd=trade_notional,
            risk_distance=event.risk_distance,
            usd_per_price_unit_per_lot=usd_per_pu_per_lot,
            entry_timestamp=event.timestamp,
            risk_override_flag=risk_override,
            target_risk_usd=target_risk,
            actual_risk_usd=trade_risk_usd,
            risk_multiple=risk_multiple,
            initial_stop_price=event.initial_stop_price,
            atr_entry=event.atr_entry,
            r_multiple=event.r_multiple,
            volatility_regime=event.volatility_regime,
            trend_regime=event.trend_regime,
            trend_label=event.trend_label,
        )

        self.open_trades[event.trade_id] = trade
        self.total_open_risk += trade_risk_usd
        self.total_notional += trade_notional
        self.symbol_notional[event.symbol] = self.symbol_notional.get(event.symbol, 0.0) + trade_notional
        self.total_accepted += 1
        self.accepted_trade_ids.append(event.trade_id)

        # Track max concurrent
        if len(self.open_trades) > self.max_concurrent:
            self.max_concurrent = len(self.open_trades)

        return trade

    def _emit_accepted_trade(self, event: TradeEvent, check_invariants: bool = True) -> None:
        """Snapshot equity to timeline and (optionally) run invariant checks."""
        self.equity_timeline.append((event.timestamp, self.equity))
        if check_invariants:
            self._check_invariants()

    # ------------------------------------------------------------------
    # EXIT PROCESSING
    # ------------------------------------------------------------------

    def process_exit(self, event: TradeEvent) -> Optional[float]:
        """
        Process an EXIT event. Returns realized PnL or None if trade not found.
        """
        trade = self.open_trades.get(event.trade_id)
        if trade is None:
            return None  # Trade was rejected at entry or already closed

        # Compute PnL from price delta
        price_delta = (trade.exit_price - trade.entry_price) * trade.direction
        pnl_usd = price_delta * trade.usd_per_price_unit_per_lot * trade.lot_size

        # Update equity
        self.equity += pnl_usd
        self.realized_pnl += pnl_usd

        # Update peak / drawdown
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        dd = self.peak_equity - self.equity
        if dd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd

        # Reduce totals
        self.total_open_risk -= trade.risk_usd
        self.total_notional -= trade.notional_usd
        self.symbol_notional[trade.symbol] = self.symbol_notional.get(trade.symbol, 0.0) - trade.notional_usd
        if self.symbol_notional.get(trade.symbol, 0.0) <= 0:
            self.symbol_notional.pop(trade.symbol, None)

        # Clamp floating point drift
        if self.total_open_risk < 0:
            if abs(self.total_open_risk) > FLOAT_TOLERANCE:
                print(f"[WARN] total_open_risk drift detected ({self.total_open_risk:.12f}); clamped to 0.")
            self.total_open_risk = 0.0
        if self.total_notional < 0:
            if abs(self.total_notional) > FLOAT_TOLERANCE:
                print(f"[WARN] total_notional drift detected ({self.total_notional:.12f}); clamped to 0.")
            self.total_notional = 0.0

        # Remove trade
        del self.open_trades[event.trade_id]

        # Log completed trade (Phase 5)
        entry_ts_str = str(trade.entry_timestamp) if trade.entry_timestamp else ""
        log_entry = {
            "trade_id":        trade.trade_id,
            "symbol":          trade.symbol,
            "direction":       trade.direction,
            "lot_size":        trade.lot_size,
            "entry_price":     trade.entry_price,
            "exit_price":      trade.exit_price,
            "risk_distance":   trade.risk_distance,
            "initial_stop_price": trade.initial_stop_price,
            "atr_entry":       trade.atr_entry,
            "r_multiple":      trade.r_multiple,
            "volatility_regime": trade.volatility_regime,
            "trend_regime":    trade.trend_regime,
            "trend_label":     trade.trend_label,
            "pnl_usd":         round(pnl_usd, 2),
            "entry_timestamp": entry_ts_str,
            "exit_timestamp":  str(event.timestamp),
            "signal_hash":     compute_signal_hash(
                                   trade.symbol, entry_ts_str,
                                   trade.direction, trade.entry_price,
                                   trade.risk_distance,
                               ),
        }
        if trade.risk_override_flag:
            log_entry.update({
                "risk_override_flag": True,
                "target_risk_usd": round(trade.target_risk_usd, 2),
                "actual_risk_usd": round(trade.actual_risk_usd, 2),
                "risk_multiple": round(trade.risk_multiple, 2),
            })
        self.closed_trades_log.append(log_entry)

        # Sample heat utilization (Phase 5)
        if self.equity > 0:
            self.heat_samples.append(self.total_open_risk / self.equity)

        # Snapshot equity
        self.equity_timeline.append((event.timestamp, self.equity))

        # Assertion checks
        self._check_invariants()

        return pnl_usd

    # ------------------------------------------------------------------
    # REJECTION LOGGING
    # ------------------------------------------------------------------

    def _reject(self, event: TradeEvent, reason: str, detail: str):
        """Log a trade rejection."""
        self.rejection_log.append({
            "trade_id": event.trade_id,
            "symbol": event.symbol,
            "timestamp": str(event.timestamp),
            "reason": reason,
            "detail": detail,
            "equity_at_rejection": round(self.equity, 2),
            "open_risk_at_rejection": round(self.total_open_risk, 2),
        })
        self.total_rejected += 1

    # ------------------------------------------------------------------
    # INVARIANT ASSERTIONS
    # ------------------------------------------------------------------

    def _check_invariants(self):
        """Check that caps are never breached."""
        if self.equity > 0:
            heat_pct = self.total_open_risk / self.equity
            if heat_pct > self.heat_cap + FLOAT_TOLERANCE:
                self._heat_breach = True
            lev_ratio = self.total_notional / self.equity
            if lev_ratio > self.leverage_cap + FLOAT_TOLERANCE:
                self._leverage_breach = True
        if self.equity < 0:
            self._equity_negative = True
