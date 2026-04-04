"""
Deployable Capital Wrapper â€” Phases 2â€“6
Phase 2: Event Queue Builder (load, decompose, sort)
Phase 3: Single-Profile PortfolioState
Phase 4: Multi-Profile Parallel Execution
Phase 5: Deployable Metric Engine + Artifact Output
Phase 6: Dynamic USD Conversion at Entry Time

Authority: CAPITAL_MIGRATION_IMPACT.md, MODULAR_IMPACT_VALIDATION.md
"""

import bisect
import csv
import hashlib
import json
import math
import random
import sys
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, date as date_type, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from tools.capital_engine import run_simulation as _engine_run_simulation

from config.state_paths import BACKTESTS_DIR, STRATEGIES_DIR
BACKTESTS_ROOT = BACKTESTS_DIR
BROKER_SPECS_ROOT = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"

FLOAT_TOLERANCE = 1e-9

# ======================================================================
# CAPITAL PROFILES
# ======================================================================

PROFILES = {
    # Baseline: raw directional edge at minimum lot — no constraints
    "RAW_MIN_LOT_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.0,
        "heat_cap": 9999.0,       # unused (raw_lot_mode bypasses all gates)
        "leverage_cap": 9999,     # unused
        "min_lot": 0.01,
        "lot_step": 0.01,
        "raw_lot_mode": True,     # unconditional execution — every signal at 0.01 lot
    },
    # Priority 1: Dynamic heat-aware scaling
    "DYNAMIC_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.005,         # 0.5% base risk
        "heat_cap": 0.03,               # 3.0% hard cap
        "leverage_cap": 15,             # 15x
        "dynamic_scaling": True,        # min(base_risk, remaining_heat)
        "min_position_pct": 0.40,       # Skip if scaled risk < 40% of base
        "min_lot": 0.01,
        "lot_step": 0.01,
    },
    # Priority 2: Lower fixed fractional
    "CONSERVATIVE_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.0025,       # 0.25%
        "heat_cap": 0.04,               # 4.0%
        "leverage_cap": 5,              # 5x
        "min_lot": 0.01,
        "lot_step": 0.01,
    },
    # Priority 3: Fixed USD risk per trade
    "FIXED_USD_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.005,        # Fallback (unused when fixed_risk_usd set)
        "fixed_risk_usd": 50.0,         # $50 per trade
        "heat_cap": 0.04,               # 4.0%
        "leverage_cap": 11,             # 11x (calibrated from p99 = 10.67x)
        "min_lot": 0.01,
        "lot_step": 0.01,
    },
    # Priority 4: Min Lot Fallback (Fixed USD $50 with broker min override)
    "MIN_LOT_FALLBACK_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.005,
        "fixed_risk_usd": 50.0,
        "heat_cap": 0.04,
        "leverage_cap": 5,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "min_lot_fallback": True,
        "max_risk_multiple": 3.0,
        "track_risk_override": True,
    },
    # Priority 5: Uncapped Fallback (Research Only)
    "MIN_LOT_FALLBACK_UNCAPPED_V1": {
        "starting_capital": 10000.0,
        "risk_per_trade": 0.005,
        "fixed_risk_usd": 50.0,
        "heat_cap": 0.04,
        "leverage_cap": 5,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "min_lot_fallback": True,
        "max_risk_multiple": None,
        "track_risk_override": True,
    },
    # Priority 6: Bounded Fallback
    "BOUNDED_MIN_LOT_V1": {
        "starting_capital": 10000.0,
        "fixed_risk_usd": 65.0,
        "heat_cap": 0.04,
        "leverage_cap": 5,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "min_lot_fallback": True,
        "max_risk_multiple": 1.5,
    },
}

# ======================================================================
# EVENT DEFINITION
# ======================================================================

EVENT_TYPE_ENTRY = "ENTRY"
EVENT_TYPE_EXIT = "EXIT"
SIMULATION_SEED = 42          # RNG seed for deterministic collision-randomisation

EVENT_TYPE_PRIORITY = {
    EVENT_TYPE_EXIT: 0,
    EVENT_TYPE_ENTRY: 1,
}


# ===========================================================================
# SIGNAL INTEGRITY
# ===========================================================================

def _normalize_hash_timestamp(entry_timestamp) -> str:
    """
    Normalize timestamp input for stable cross-environment signal hashing.

    Output format is always UTC second precision: YYYY-MM-DD HH:MM:SS
    """
    if isinstance(entry_timestamp, datetime):
        dt = entry_timestamp
    else:
        token = str(entry_timestamp).strip()
        if not token:
            return ""
        try:
            dt = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            return token
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def compute_signal_hash(
    symbol: str,
    entry_timestamp,        # datetime or str
    direction: int,
    entry_price: float,
    risk_distance: float,
) -> str:
    """
    Compute a 16-char hex fingerprint for a single research signal.

    The hash is deterministic: same inputs always produce the same digest.
    The live execution engine must recompute this hash for every incoming
    signal and reject it if the digest does not match the value stored in
    deployable_trade_log.csv.

    Fields used (order is fixed and must never change):
        symbol | entry_timestamp | direction | entry_price(5dp) | risk_distance(5dp)
    """
    ts_norm = _normalize_hash_timestamp(entry_timestamp)
    s = (
        f"{symbol}|{ts_norm}|{direction}"
        f"|{entry_price:.5f}|{risk_distance:.5f}"
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class TradeEvent:
    """Single chronological event in the portfolio simulation queue."""
    timestamp: datetime
    event_type: str         # "ENTRY" or "EXIT"
    trade_id: str           # Composite: strategy_name + "|" + parent_trade_id
    symbol: str
    direction: int          # 1 = Long, -1 = Short
    entry_price: float
    exit_price: float
    risk_distance: float
    initial_stop_price: Optional[float] = None
    atr_entry: Optional[float] = None
    r_multiple: Optional[float] = None
    volatility_regime: str = ""
    trend_regime: str = ""
    trend_label: str = ""

    @property
    def sort_key(self):
        """Deterministic sort: timestamp -> event_type priority -> trade_id."""
        return (self.timestamp, EVENT_TYPE_PRIORITY[self.event_type], self.trade_id)


# ======================================================================
# BROKER SPEC LOADER
# ======================================================================

def load_broker_spec(symbol: str) -> dict:
    """Load broker spec YAML for a symbol."""
    spec_path = BROKER_SPECS_ROOT / f"{symbol}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"Missing broker spec: {spec_path}")
    with open(spec_path, "r") as f:
        return yaml.safe_load(f)


def get_usd_per_price_unit_static(spec: dict) -> float:
    """
    STATIC fallback: Derive USD PnL per 1.0 price unit move per 1.0 lot
    from broker YAML calibration.
    """
    cal = spec.get("calibration", {})
    usd_per_pu_0p01 = cal.get("usd_pnl_per_price_unit_0p01")
    if usd_per_pu_0p01 is None:
        raise ValueError(f"Broker spec for {spec.get('symbol','?')} missing calibration.usd_pnl_per_price_unit_0p01")
    return float(usd_per_pu_0p01) * 100.0  # Scale 0.01 lot -> 1.0 lot


# ======================================================================
# PHASE 6: DYNAMIC USD CONVERSION
# ======================================================================

# Symbol -> (base_ccy, quote_ccy) for all 18 FX pairs
def _parse_fx_currencies(symbol: str) -> Tuple[str, str]:
    """Extract base and quote currency from a 6-char FX symbol."""
    if len(symbol) == 6 and symbol.isalpha():
        return symbol[:3], symbol[3:]
    return "", ""  # Non-FX (index, commodity, crypto)


# Quote currency -> (conversion_pair_symbol, invert?)
# To get quote_ccy_to_USD rate:
#   if not inverted: rate = close_price of conversion pair
#   if inverted:     rate = 1 / close_price of conversion pair
CONVERSION_MAP = {
    "USD": None,                           # No conversion needed
    "JPY": ("USDJPY", True),               # 1/USDJPY
    "CAD": ("USDCAD", True),               # 1/USDCAD
    "CHF": ("USDCHF", True),               # 1/USDCHF
    "GBP": ("GBPUSD", False),              # GBPUSD directly
    "AUD": ("AUDUSD", False),              # AUDUSD directly
    "NZD": ("NZDUSD", False),              # NZDUSD directly
    "EUR": ("EURUSD", False),              # EURUSD directly
}


class ConversionLookup:
    """
    Provides O(1)-ish USD conversion rate lookups by date.

    Loads daily close prices from RESEARCH data for each required
    conversion pair. Uses bisect to find the nearest available date
    (handles weekends/holidays).
    """

    def __init__(self):
        # {currency: [(date, rate), ...]} sorted by date
        self._series: Dict[str, List[Tuple[date_type, float]]] = {}
        self._dates: Dict[str, List[date_type]] = {}  # for bisect
        self._fallback_warned: set = set()

    def load(self, currencies_needed: set, data_root: Optional[Path] = None):
        """Load daily close series for all needed non-USD quote currencies."""
        from data_access.readers.research_data_reader import load_research_data

        if data_root is None:
            data_root = PROJECT_ROOT / "data_root" / "MASTER_DATA"

        for ccy in currencies_needed:
            if ccy == "USD":
                continue
            conv = CONVERSION_MAP.get(ccy)
            if conv is None:
                print(f"[WARN] No conversion mapping for currency: {ccy}")
                continue

            pair_symbol, inverted = conv
            try:
                df = load_research_data(
                    symbol=pair_symbol,
                    timeframe="1d",
                    broker="OctaFX",
                    start_date="2005-01-01",
                    end_date="2030-12-31",
                    data_root=data_root,
                )
                # Build sorted (date, rate) list
                entries = []
                for _, row in df.iterrows():
                    ts = pd.to_datetime(row.get("timestamp", row.get("date")), utc=True)
                    close = float(row["close"])
                    if inverted:
                        rate = 1.0 / close if close != 0 else 0.0
                    else:
                        rate = close
                    entries.append((ts.date(), rate))

                entries.sort(key=lambda x: x[0])
                self._series[ccy] = entries
                self._dates[ccy] = [e[0] for e in entries]
                print(f"[CONV] Loaded {pair_symbol} -> {ccy}/USD: {len(entries)} daily bars")

            except FileNotFoundError:
                print(f"[WARN] Conversion data not found for {pair_symbol}. Will use YAML fallback for {ccy}.")

    @staticmethod
    def _normalize_lookup_date(lookup_input) -> date_type:
        """
        Normalize date or datetime inputs to UTC-trading date.

        Naive datetimes are treated as UTC by contract.
        """
        if isinstance(lookup_input, datetime):
            if lookup_input.tzinfo is None:
                lookup_input = lookup_input.replace(tzinfo=timezone.utc)
            else:
                lookup_input = lookup_input.astimezone(timezone.utc)
            return lookup_input.date()
        if isinstance(lookup_input, date_type):
            return lookup_input
        raise TypeError(f"Unsupported lookup date type: {type(lookup_input)}")

    def get_rate(self, currency: str, lookup_input) -> Optional[float]:
        """
        Get quote_ccy -> USD rate for a given date.
        Returns None if data unavailable (caller should use YAML fallback).
        """
        if currency == "USD":
            return 1.0

        dates = self._dates.get(currency)
        series = self._series.get(currency)
        if dates is None or series is None:
            return None

        lookup_date = self._normalize_lookup_date(lookup_input)

        # Bisect to find nearest date <= lookup_date
        idx = bisect.bisect_right(dates, lookup_date) - 1
        if idx < 0:
            idx = 0  # Use earliest available
        return series[idx][1]


def get_usd_per_price_unit_dynamic(
    contract_size: float,
    quote_ccy: str,
    entry_timestamp,
    conv_lookup: ConversionLookup,
    static_fallback: float,
    symbol: str,
) -> Tuple[float, str]:
    """
    Compute usd_per_price_unit_per_lot dynamically at entry time.

    Formula: contract_size * quote_ccy_to_USD_rate

    Returns (value, source) where source is 'DYNAMIC' or 'STATIC_FALLBACK'.
    """
    rate = conv_lookup.get_rate(quote_ccy, entry_timestamp)
    if rate is not None:
        return contract_size * rate, "DYNAMIC"
    else:
        return static_fallback, "STATIC_FALLBACK"


# ======================================================================
# OPEN TRADE RECORD
# ======================================================================

@dataclass
class OpenTrade:
    """Tracks a live position in the portfolio."""
    trade_id: str
    symbol: str
    direction: int
    entry_price: float
    exit_price: float        # Known from backtest (used at exit)
    lot_size: float
    risk_usd: float          # USD at risk for this trade
    notional_usd: float      # Notional exposure
    risk_distance: float
    usd_per_price_unit_per_lot: float
    entry_timestamp: Optional[datetime] = None
    risk_override_flag: bool = False
    target_risk_usd: float = 0.0
    actual_risk_usd: float = 0.0
    risk_multiple: float = 0.0
    initial_stop_price: Optional[float] = None
    atr_entry: Optional[float] = None
    r_multiple: Optional[float] = None
    volatility_regime: str = ""
    trend_regime: str = ""
    trend_label: str = ""


# ======================================================================
# PORTFOLIO STATE (Phase 3 â€” Single Profile)
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
        self.equity = self.starting_capital
        self.peak_equity = self.starting_capital

    # ------------------------------------------------------------------
    # LOT SIZING
    # ------------------------------------------------------------------

    def _floor_to_step(self, lots: float) -> float:
        """Floor lot size to nearest lot_step."""
        steps = math.floor(lots / self.lot_step)
        return round(steps * self.lot_step, 8)

    def compute_lot_size(self, risk_distance: float, usd_per_pu_per_lot: float) -> float:
        """
        Multi-mode position sizing.

        Modes:
          - Fixed USD:        risk_capital = fixed_risk_usd
          - Fixed Fractional: risk_capital = equity * risk_per_trade
          - Dynamic Scaling:  risk_capital = min(base, remaining_heat)

        Min position filter: skip if scaled risk < min_position_pct of base.
        """
        # Step A: Determine base risk capital
        if self.fixed_risk_usd is not None:
            base_risk_capital = self.fixed_risk_usd
        else:
            base_risk_capital = self.equity * self.risk_per_trade

        risk_capital = base_risk_capital

        # Step B: Dynamic heat scaling (clamp to remaining heat budget)
        if self.dynamic_scaling and self.equity > 0:
            remaining_heat_usd = (self.heat_cap * self.equity) - self.total_open_risk
            remaining_heat_usd = max(remaining_heat_usd, 0.0)
            risk_capital = min(risk_capital, remaining_heat_usd)

        # Clamp risk_capital >= 0
        risk_capital = max(risk_capital, 0.0)

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
        # RAW mode: bypass all gates — unconditionally accept at min_lot
        if self.raw_lot_mode:
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

        """
        Process an ENTRY event. Returns True if accepted, False if rejected.

        Steps:
          1. Compute lot size via fixed fractional sizing
          2. Check min_lot
          3. Compute trade risk and notional
          4. Check heat cap
          5. Check leverage cap
          6. Accept or reject
        """
        # 0. Explicit concurrency cap check (if configured).
        if self.concurrency_cap is not None and len(self.open_trades) >= int(self.concurrency_cap):
            self._reject(
                event,
                "CONCURRENCY_CAP",
                f"open={len(self.open_trades)} >= cap={int(self.concurrency_cap)}",
            )
            return False

        # 1. Compute lot size
        lot_size = self.compute_lot_size(event.risk_distance, usd_per_pu_per_lot)

        # 2. Min lot check with fallback
        risk_override = False
        
        # Step A: Determine base risk capital (Target Risk)
        if self.fixed_risk_usd is not None:
            target_risk = self.fixed_risk_usd
        else:
            target_risk = self.equity * self.risk_per_trade

        # Step B: Dynamic heat scaling (clamp to remaining heat budget)
        if self.dynamic_scaling and self.equity > 0:
            remaining_heat_usd = (self.heat_cap * self.equity) - self.total_open_risk
            remaining_heat_usd = max(remaining_heat_usd, 0.0)
            target_risk = min(target_risk, remaining_heat_usd)
        
        target_risk = max(target_risk, 0.0)

        if lot_size < self.min_lot:
            if self.min_lot_fallback:
                lot_size = self.min_lot
                risk_override = True
            else:
                self._reject(event, "LOT_TOO_SMALL",
                             f"computed={lot_size:.4f} < min={self.min_lot}")
                return False

        # 3. Compute trade risk and notional (USD-normalised)
        #    usd_per_pu_per_lot = contract_size × quote_ccy_to_USD_rate
        #    → notional = lot × entry_price × usd_per_pu_per_lot
        #      = lot × entry_price × contract_size × rate   (USD for all pairs)
        #    For EURUSD (rate=1): lot × 1.09 × 100000 × 1.0  = USD notional  ✓
        #    For USDJPY (rate=1/148): lot × 148 × 100000 × (1/148) = lot × 100000 ✓
        trade_risk_usd = event.risk_distance * usd_per_pu_per_lot * lot_size
        trade_notional = lot_size * event.entry_price * usd_per_pu_per_lot

        # 3.5 Risk Multiple Safety Check
        risk_multiple = trade_risk_usd / target_risk if target_risk > 0 else float("inf")
        if risk_override:
            if self.max_risk_multiple is not None:
                if risk_multiple > self.max_risk_multiple:
                    reason_str = "RISK_MULTIPLE_EXCEEDED" if self.profile_name == "BOUNDED_MIN_LOT_V1" else "RISK_MULT_EXCEEDED"
                    self._reject(event, reason_str,
                                 f"multiple={risk_multiple:.2f} > cap={self.max_risk_multiple}")
                    return False
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
            return False

        # 5. Leverage cap check
        new_notional = self.total_notional + trade_notional
        leverage_ratio = new_notional / self.equity if self.equity > 0 else float('inf')
        if leverage_ratio > self.leverage_cap + FLOAT_TOLERANCE:
            self._reject(event, "LEVERAGE_CAP",
                         f"would_be={leverage_ratio:.2f}x > cap={self.leverage_cap}x")
            return False

        # 6. Accept
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

        # Snapshot equity
        self.equity_timeline.append((event.timestamp, self.equity))

        # Assertion checks
        self._check_invariants()

        return True

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


# ======================================================================
# EVENT PROCESSING LOOP
# ======================================================================

def run_simulation(sorted_events: List[TradeEvent], broker_specs: Dict[str, dict],
                   profiles: Optional[Dict[str, dict]] = None,
                   conv_lookup: Optional[ConversionLookup] = None) -> Dict[str, PortfolioState]:
    """Compatibility wrapper that delegates simulation execution to capital_engine."""
    if profiles is None:
        profiles = PROFILES
    return _engine_run_simulation(
        sorted_events=sorted_events,
        broker_specs=broker_specs,
        profiles=profiles,
        conv_lookup=conv_lookup,
    )


# ======================================================================
# VALIDATION SUMMARY
# ======================================================================

def print_validation_summary(state: PortfolioState):
    """Print post-simulation validation output."""
    max_dd_pct = (state.max_drawdown_usd / state.peak_equity * 100) if state.peak_equity > 0 else 0.0

    print(f"\n{'=' * 70}")
    print(f"  PORTFOLIO SIMULATION SUMMARY â€” {state.profile_name}")
    print(f"{'=' * 70}")
    print(f"  Starting Capital:      ${state.starting_capital:>12,.2f}")
    print(f"  Final Equity:          ${state.equity:>12,.2f}")
    print(f"  Peak Equity:           ${state.peak_equity:>12,.2f}")
    print(f"  Realized PnL:          ${state.realized_pnl:>12,.2f}")
    print(f"  Max Drawdown (USD):    ${state.max_drawdown_usd:>12,.2f}")
    print(f"  Max Drawdown (%):       {max_dd_pct:>11.2f}%")
    print(f"  Total Accepted:         {state.total_accepted:>12d}")
    print(f"  Total Rejected:         {state.total_rejected:>12d}")
    print(f"  Max Concurrent (Test):  {state.max_concurrent:>12d}")
    print(f"  Open Trades Remaining:  {len(state.open_trades):>12d}")
    print(f"{'=' * 70}")

    # Assertion results
    print(f"\n  INVARIANT CHECKS:")
    print(f"    Heat cap never breached:     {'PASS' if not state._heat_breach else 'FAIL'}")
    print(f"    Leverage cap never breached:  {'PASS' if not state._leverage_breach else 'FAIL'}")
    print(f"    Equity never negative:        {'PASS' if not state._equity_negative else 'FAIL'}")

    if state.rejection_log:
        print(f"\n  REJECTION BREAKDOWN:")
        reasons = {}
        for r in state.rejection_log:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        for reason, count in sorted(reasons.items()):
            print(f"    {reason}: {count}")

    print(f"{'=' * 70}\n")


def print_comparative_summary(states: Dict[str, PortfolioState]):
    """Print side-by-side comparison and acceptance set analysis."""
    names = sorted(states.keys())

    print(f"\n{'=' * 70}")
    print(f"  COMPARATIVE SUMMARY")
    print(f"{'=' * 70}")

    # Header
    col_w = 20
    print(f"  {'Metric':<25}", end="")
    for n in names:
        print(f"{n:>{col_w}}", end="")
    print()
    print("  " + "-" * (25 + col_w * len(names)))

    # Rows
    def row(label, fn, fmt=",.2f"):
        print(f"  {label:<25}", end="")
        for n in names:
            val = fn(states[n])
            print(f"  ${val:>{col_w - 3}{fmt}}" if "$" in fmt
                  else f"  {val:>{col_w - 2}{fmt}}", end="")
        print()

    def row_dollar(label, fn):
        print(f"  {label:<25}", end="")
        for n in names:
            print(f"{'$' + f'{fn(states[n]):,.2f}':>{col_w}}", end="")
        print()

    def row_num(label, fn):
        print(f"  {label:<25}", end="")
        for n in names:
            print(f"{fn(states[n]):>{col_w}}", end="")
        print()

    def row_pct(label, fn):
        print(f"  {label:<25}", end="")
        for n in names:
            print(f"{fn(states[n]):>{col_w}.2f}%", end="")
        print()

    row_dollar("Starting Capital", lambda s: s.starting_capital)
    row_dollar("Final Equity", lambda s: s.equity)
    row_dollar("Peak Equity", lambda s: s.peak_equity)
    row_dollar("Realized PnL", lambda s: s.realized_pnl)
    row_dollar("Max DD (USD)", lambda s: s.max_drawdown_usd)
    row_pct("Max DD (%)", lambda s: (s.max_drawdown_usd / s.peak_equity * 100) if s.peak_equity > 0 else 0)
    row_num("Accepted", lambda s: s.total_accepted)
    row_num("Rejected", lambda s: s.total_rejected)
    row_num("Max Concurrent", lambda s: s.max_concurrent)

    # Acceptance set analysis
    if len(names) == 2:
        a_name, b_name = names
        a_set = set(states[a_name].accepted_trade_ids)
        b_set = set(states[b_name].accepted_trade_ids)

        both = sorted(a_set & b_set)
        only_a = sorted(a_set - b_set)
        only_b = sorted(b_set - a_set)

        print(f"\n  ACCEPTANCE SET ANALYSIS:")
        print(f"    Accepted in both:            {len(both)}")
        print(f"    Only in {a_name}:  {len(only_a)}")
        print(f"    Only in {b_name}:     {len(only_b)}")

        if only_a:
            print(f"\n    {a_name} exclusive:")
            for tid in only_a[:10]:
                print(f"      {tid}")
        if only_b:
            print(f"\n    {b_name} exclusive:")
            for tid in only_b[:10]:
                print(f"      {tid}")

    print(f"{'=' * 70}\n")


# ======================================================================
# PHASE 5: DEPLOYABLE METRICS + ARTIFACT OUTPUT
# ======================================================================

def compute_deployable_metrics(state: PortfolioState, total_runs: int, total_assets: int) -> dict:
    """Compute all deployable metrics from PortfolioState data only."""
    # CAGR (geometric)
    tl = state.equity_timeline
    if len(tl) >= 2:
        first_ts = tl[0][0]
        last_ts = tl[-1][0]
        delta = last_ts - first_ts
        years = delta.total_seconds() / (365.25 * 86400)
        if years > 0 and state.equity > 0:
            cagr = (state.equity / state.starting_capital) ** (1.0 / years) - 1.0
        else:
            cagr = 0.0
    else:
        cagr = 0.0
        years = 0.0

    # Max DD %
    max_dd_pct = (state.max_drawdown_usd / state.peak_equity) if state.peak_equity > 0 else 0.0

    # MAR
    mar = cagr / max_dd_pct if max_dd_pct > 0 else 0.0

    # Rejection rate
    total_signals = state.total_accepted + state.total_rejected
    rejection_rate = state.total_rejected / total_signals if total_signals > 0 else 0.0

    # Heat utilization
    avg_heat = sum(state.heat_samples) / len(state.heat_samples) if state.heat_samples else 0.0
    pct_at_full_heat = sum(1 for h in state.heat_samples if h >= state.heat_cap * 0.95) / len(state.heat_samples) if state.heat_samples else 0.0

    # Longest loss streak
    longest_loss = 0
    current_loss = 0
    for t in state.closed_trades_log:
        if t["pnl_usd"] < 0:
            current_loss += 1
            if current_loss > longest_loss:
                longest_loss = current_loss
        else:
            current_loss = 0

    metrics = {
        "profile": state.profile_name,
        "total_constituent_runs": total_runs,
        "actual_max_concurrent_trades": state.max_concurrent,
        "configured_concurrency_cap": state.concurrency_cap,
        "total_assets_evaluated": total_assets,
        "starting_capital": state.starting_capital,
        "final_equity": round(state.equity, 2),
        "cagr": round(cagr, 6),
        "cagr_pct": round(cagr * 100, 4),
        "max_drawdown_usd": round(state.max_drawdown_usd, 2),
        "max_drawdown_pct": round(max_dd_pct * 100, 4),
        "mar": round(mar, 4),
        "total_accepted": state.total_accepted,
        "total_rejected": state.total_rejected,
        "rejection_rate_pct": round(rejection_rate * 100, 2),
        "avg_heat_utilization_pct": round(avg_heat * 100, 4),
        "pct_time_at_full_heat": round(pct_at_full_heat * 100, 4),
        "longest_loss_streak": longest_loss,
        "realized_pnl": round(state.realized_pnl, 2),
        "simulation_years": round(years, 2) if len(tl) >= 2 else 0.0,
    }

    if state.min_lot_fallback:
        metrics.update({
            "risk_override_rate": round(state.total_risk_overrides / state.total_accepted * 100, 2) if state.total_accepted > 0 else 0.0,
            "avg_risk_multiple": round(sum(state.risk_multiples) / len(state.risk_multiples), 2) if state.risk_multiples else 0.0,
            "max_risk_multiple": round(max(state.risk_multiples), 2) if state.risk_multiples else 0.0,
        })

    return metrics

def plot_equity_curve(state: PortfolioState, output_dir: Path) -> None:
    """Render equity-curve + drawdown chart and save as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless â€” no display required
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib not installed â€” skipping equity curve plot.")
        return

    if not state.equity_timeline:
        return

    timestamps = [ts for ts, _ in state.equity_timeline]
    equity     = [eq for _, eq in state.equity_timeline]

    # Convert to pandas for resampling convenience
    import pandas as pd
    eq_series = pd.Series(equity, index=pd.to_datetime(timestamps))
    eq_series = eq_series[~eq_series.index.duplicated(keep="last")]
    daily     = eq_series.resample("D").last().ffill()

    peak    = daily.cummax()
    dd_pct  = ((daily - peak) / peak) * 100   # negative values

    dates = daily.index.to_pydatetime()

    # â”€â”€ Layout: 2 rows, shared x-axis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fig, (ax_eq, ax_dd) = plt.subplots(
        2, 1,
        figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
        facecolor="#0d0d12",
    )
    fig.subplots_adjust(hspace=0.05)

    profile_label = state.profile_name
    start_cap     = state.starting_capital
    final_eq      = daily.iloc[-1]

    # â”€â”€ Upper panel: equity curve â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ax_eq.set_facecolor("#0d0d12")
    ax_eq.plot(dates, daily.values, color="#00d4aa", linewidth=1.4, zorder=3)
    ax_eq.fill_between(dates, start_cap, daily.values,
                        where=(daily.values >= start_cap),
                        alpha=0.15, color="#00d4aa", zorder=2)
    ax_eq.axhline(start_cap, color="#555", linewidth=0.8, linestyle="--")

    ax_eq.set_yscale("log")
    ax_eq.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}")
    )
    ax_eq.set_ylabel("Portfolio Equity (log)", color="#ccc", fontsize=11)
    ax_eq.tick_params(colors="#999", labelsize=9)
    ax_eq.spines[:].set_color("#222")
    ax_eq.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)

    # Title
    ax_eq.set_title(
        f"{profile_label}  |  ${start_cap:,.0f}  â†’  ${final_eq:,.0f}",
        color="#eee", fontsize=13, pad=10,
    )

    # â”€â”€ Lower panel: drawdown â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ax_dd.set_facecolor("#0d0d12")
    ax_dd.fill_between(dates, dd_pct.values, 0,
                        where=(dd_pct.values < 0),
                        color="#e05252", alpha=0.7, zorder=2)
    ax_dd.plot(dates, dd_pct.values, color="#e05252", linewidth=0.9, zorder=3)
    ax_dd.axhline(0, color="#555", linewidth=0.8)

    ax_dd.set_ylabel("Drawdown %", color="#ccc", fontsize=10)
    ax_dd.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.1f}%")
    )
    ax_dd.tick_params(colors="#999", labelsize=9)
    ax_dd.spines[:].set_color("#222")
    ax_dd.grid(axis="y", color="#222", linewidth=0.5, linestyle="--", zorder=1)

    # X-axis formatting (shared)
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dd.tick_params(axis="x", colors="#999", labelsize=9)

    out_path = output_dir / "equity_curve.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[EMIT] {state.profile_name} equity curve plot -> {out_path}")


def emit_profile_artifacts(state: PortfolioState, output_dir: Path, total_runs: int, total_assets: int):
    """Write per-profile CSV and JSON artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # equity_curve.csv
    with open(output_dir / "equity_curve.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "equity"])
        w.writeheader()
        for ts, eq in state.equity_timeline:
            w.writerow({"timestamp": str(ts), "equity": round(eq, 2)})

    # deployable_trade_log.csv
    trade_fields = [
        "trade_id", "symbol", "lot_size", "pnl_usd",
        "entry_timestamp", "exit_timestamp", "direction",
        "entry_price", "exit_price", "risk_distance",
        "initial_stop_price", "atr_entry", "r_multiple",
        "volatility_regime", "trend_regime", "trend_label",
        "signal_hash",   # 16-char SHA-256 prefix for signal integrity verification
    ]

    # Check if overrides exist in log
    has_overrides = any(t.get("risk_override_flag") for t in state.closed_trades_log)
    if has_overrides:
        trade_fields.extend(["risk_override_flag", "target_risk_usd", "actual_risk_usd", "risk_multiple"])

    with open(output_dir / "deployable_trade_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=trade_fields, extrasaction='ignore')
        w.writeheader()
        for t in state.closed_trades_log:
            w.writerow(t)

    # rejection_log.csv
    if state.rejection_log:
        rej_fields = list(state.rejection_log[0].keys())
        with open(output_dir / "rejection_log.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rej_fields)
            w.writeheader()
            for r in state.rejection_log:
                w.writerow(r)

    # summary_metrics.json
    metrics = compute_deployable_metrics(state, total_runs, total_assets)
    with open(output_dir / "summary_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # equity_curve.png (equity + drawdown chart)
    plot_equity_curve(state, output_dir)

    print(f"[EMIT] {state.profile_name} artifacts -> {output_dir}")
    return metrics


def emit_comparison_json(all_metrics: Dict[str, dict], states: Dict[str, PortfolioState],
                         output_dir: Path):
    """Write unified profile_comparison.json."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pin RAW_MIN_LOT_V1 first (baseline), then sort the rest alphabetically
    _raw = "RAW_MIN_LOT_V1"
    names = ([_raw] if _raw in all_metrics else []) + sorted(
        [k for k in all_metrics.keys() if k != _raw]
    )
    comparison = {"profiles": {n: all_metrics[n] for n in names}}

    # Acceptance set analysis
    if len(names) == 2:
        a, b = names
        a_set = set(states[a].accepted_trade_ids)
        b_set = set(states[b].accepted_trade_ids)
        comparison["acceptance_analysis"] = {
            "intersection_size": len(a_set & b_set),
            f"exclusive_{a}": len(a_set - b_set),
            f"exclusive_{b}": len(b_set - a_set),
        }
        # Deltas (B - A)
        comparison["deltas"] = {
            "delta_final_equity": round(all_metrics[b]["final_equity"] - all_metrics[a]["final_equity"], 2),
            "delta_max_dd_pct": round(all_metrics[b]["max_drawdown_pct"] - all_metrics[a]["max_drawdown_pct"], 4),
            "delta_cagr_pct": round(all_metrics[b]["cagr_pct"] - all_metrics[a]["cagr_pct"], 4),
        }

    comparison["generated_utc"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    out_path = output_dir / "profile_comparison.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    print(f"[EMIT] Comparison -> {out_path}")
    return comparison


# ======================================================================
# STEP 1: LOAD TRADE ARTIFACTS
# ======================================================================

REQUIRED_COLUMNS = [
    "strategy_name",
    "parent_trade_id",
    "symbol",
    "entry_timestamp",
    "exit_timestamp",
    "direction",
    "entry_price",
    "exit_price",
    "risk_distance",
]

OPTIONAL_RECON_COLUMNS = [
    "initial_stop_price",
    "atr_entry",
    "r_multiple",
    "volatility_regime",
    "trend_regime",
    "trend_label",
]


def _parse_ts(ts_str: str) -> datetime:
    """
    Parse timestamp string to timezone-aware UTC datetime.

    Naive timestamps are treated as UTC.
    """
    ts_str = ts_str.strip()
    if not ts_str:
        raise ValueError("Empty timestamp")

    # Fast-path for ISO forms (supports offsets and trailing 'Z').
    iso_guess = ts_str.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_guess)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(ts_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: '{ts_str}'")


def _optional_float(raw: str) -> Optional[float]:
    token = str(raw).strip()
    if token == "" or token.lower() == "none":
        return None
    return float(token)


def load_trades(run_dirs: List[Path]) -> list:
    """Load trade-level results from run directories. Fails on missing columns."""
    all_trades = []

    for run_dir in run_dirs:
        csv_path = run_dir / "raw" / "results_tradelevel.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing trade artifact: {csv_path}")

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"[FATAL] {csv_path} missing required columns: {missing}"
                )
            for row in reader:
                for col in REQUIRED_COLUMNS:
                    val = row.get(col, "").strip()
                    if val == "" or val.lower() == "none":
                        raise ValueError(
                            f"[FATAL] {csv_path} trade {row.get('parent_trade_id','?')} "
                            f"has empty required field: '{col}'"
                        )
                for col in OPTIONAL_RECON_COLUMNS:
                    if col not in row:
                        row[col] = ""
                all_trades.append(row)

    print(f"[LOAD] Total trades loaded: {len(all_trades)}")
    return all_trades


# ======================================================================
# STEP 2: BUILD EVENT OBJECTS
# ======================================================================

def build_events(trades: list) -> List[TradeEvent]:
    """Decompose each trade into an ENTRY event and an EXIT event."""
    events = []

    for t in trades:
        trade_id = f"{t['strategy_name']}|{t['parent_trade_id']}"
        symbol = t["symbol"]
        direction = int(t["direction"])
        entry_price = float(t["entry_price"])
        exit_price = float(t["exit_price"])
        risk_distance = float(t["risk_distance"])
        initial_stop_price = _optional_float(t.get("initial_stop_price", ""))
        atr_entry = _optional_float(t.get("atr_entry", ""))
        r_multiple = _optional_float(t.get("r_multiple", ""))
        volatility_regime = str(t.get("volatility_regime", "")).strip()
        trend_regime = str(t.get("trend_regime", "")).strip()
        trend_label = str(t.get("trend_label", "")).strip()
        entry_ts = _parse_ts(t["entry_timestamp"])
        exit_ts = _parse_ts(t["exit_timestamp"])

        events.append(TradeEvent(
            timestamp=entry_ts, event_type=EVENT_TYPE_ENTRY,
            trade_id=trade_id, symbol=symbol, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            risk_distance=risk_distance,
            initial_stop_price=initial_stop_price,
            atr_entry=atr_entry,
            r_multiple=r_multiple,
            volatility_regime=volatility_regime,
            trend_regime=trend_regime,
            trend_label=trend_label,
        ))
        events.append(TradeEvent(
            timestamp=exit_ts, event_type=EVENT_TYPE_EXIT,
            trade_id=trade_id, symbol=symbol, direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            risk_distance=risk_distance,
            initial_stop_price=initial_stop_price,
            atr_entry=atr_entry,
            r_multiple=r_multiple,
            volatility_regime=volatility_regime,
            trend_regime=trend_regime,
            trend_label=trend_label,
        ))

    print(f"[BUILD] Total events created: {len(events)}  (expected: {len(trades) * 2})")
    if len(events) != len(trades) * 2:
        raise RuntimeError(f"Event count mismatch: {len(events)} != {len(trades)} * 2")
    return events


# ======================================================================
# STEP 3: SORT EVENTS (DETERMINISTIC)
# ======================================================================

def sort_events(events: List[TradeEvent]) -> List[TradeEvent]:
    """Sort: timestamp ASC -> ENTRY before EXIT -> trade_id ASC."""
    return sorted(events, key=lambda e: e.sort_key)


# ======================================================================
# STEP 4: VALIDATION OUTPUT (Phase 2)
# ======================================================================

def print_events(events: List[TradeEvent], label: str, first_n: int = 20, last_n: int = 5):
    """Print first N and last N events for validation."""
    print(f"\n{'=' * 80}")
    print(f"  {label}")
    print(f"{'=' * 80}")
    print(f"  Total events: {len(events)}")

    header = f"  {'#':>4}  {'Timestamp':<20} {'Type':<6} {'Symbol':<10} {'Dir':>4}  {'Entry':>10}  {'Exit':>10}  {'RiskDist':>10}  Trade ID"
    sep = "  " + "-" * 120

    print(f"\n  FIRST {first_n}:")
    print(header)
    print(sep)
    for i, e in enumerate(events[:first_n]):
        print(
            f"  {i+1:>4}  {str(e.timestamp):<20} {e.event_type:<6} {e.symbol:<10} {e.direction:>4}  "
            f"{e.entry_price:>10.5f}  {e.exit_price:>10.5f}  {e.risk_distance:>10.5f}  {e.trade_id}"
        )

    if last_n > 0 and len(events) > first_n:
        print(f"\n  LAST {last_n}:")
        print(header)
        print(sep)
        for i, e in enumerate(events[-last_n:]):
            idx = len(events) - last_n + i + 1
            print(
                f"  {idx:>4}  {str(e.timestamp):<20} {e.event_type:<6} {e.symbol:<10} {e.direction:>4}  "
                f"{e.entry_price:>10.5f}  {e.exit_price:>10.5f}  {e.risk_distance:>10.5f}  {e.trade_id}"
            )

    print(f"{'=' * 80}\n")


# ======================================================================
# DIRECTIVE-DRIVEN RUN DISCOVERY
# ======================================================================

def _find_directive_file(strategy_prefix: str) -> Optional[Path]:
    candidates = [
        DIRECTIVES_ROOT / "completed" / f"{strategy_prefix}.txt",
        DIRECTIVES_ROOT / "active" / f"{strategy_prefix}.txt",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _load_declared_symbols(directive_file: Path) -> List[str]:
    payload = yaml.safe_load(directive_file.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Directive root is not a mapping: {directive_file}")

    symbols = payload.get("symbols")
    if symbols is None and isinstance(payload.get("test"), dict):
        symbols = payload["test"].get("symbols")

    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    if not isinstance(symbols, list):
        raise ValueError(f"Directive has no valid symbols list: {directive_file}")

    clean = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    if not clean:
        raise ValueError(f"Directive symbols list is empty: {directive_file}")
    return clean


def discover_run_dirs(strategy_prefix: str) -> Tuple[List[Path], Optional[Path], List[str]]:
    """
    Resolve run directories from directive-declared symbols.

    Falls back to prefix scan only if no directive file is found.
    """
    directive_file = _find_directive_file(strategy_prefix)
    if directive_file is None:
        run_dirs = sorted([
            d for d in BACKTESTS_ROOT.iterdir()
            if d.is_dir() and d.name.startswith(strategy_prefix)
        ])
        return run_dirs, None, []

    declared_symbols = _load_declared_symbols(directive_file)
    run_dirs: List[Path] = []
    missing: List[str] = []
    for sym in declared_symbols:
        run_dir = BACKTESTS_ROOT / f"{strategy_prefix}_{sym}"
        if run_dir.is_dir():
            run_dirs.append(run_dir)
        else:
            missing.append(str(run_dir))
    if missing:
        raise FileNotFoundError(
            "Missing backtest directories for directive-declared symbols:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
    return sorted(run_dirs), directive_file, declared_symbols


# ======================================================================
# MAIN
# ======================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Deployable Capital Wrapper â€” Phase 3: Single-Profile Simulation"
    )
    parser.add_argument(
        "strategy_prefix",
        help="Strategy prefix to match backtest folders (e.g. AK31_FX_PORTABILITY_4H)",
    )
    args = parser.parse_args()
    prefix = args.strategy_prefix

    # Discover run directories
    run_dirs, directive_file, declared_symbols = discover_run_dirs(prefix)
    if not run_dirs:
        print(f"[FATAL] No backtest directories found matching prefix: {prefix}")
        sys.exit(1)

    print(f"[INIT] Strategy prefix: {prefix}")
    print(f"[INIT] Matched {len(run_dirs)} run directories")
    if directive_file is not None:
        print(f"[INIT] Directive source: {directive_file}")
        print(f"[INIT] Declared symbols: {declared_symbols}")
    else:
        print("[WARN] No directive found; using prefix-scan discovery (unfrozen universe).")

    # Phase 2: Load â†’ Build â†’ Sort
    trades = load_trades(run_dirs)
    events = build_events(trades)
    sorted_events = sort_events(events)

    # Discover unique symbols and load broker specs
    symbols = sorted(set(e.symbol for e in sorted_events))
    if declared_symbols:
        missing_in_events = sorted(set(declared_symbols) - set(symbols))
        extra_in_events = sorted(set(symbols) - set(declared_symbols))
        if missing_in_events or extra_in_events:
            print("[FATAL] Symbol mismatch between directive and event stream.")
            if missing_in_events:
                print(f"  Missing in events: {missing_in_events}")
            if extra_in_events:
                print(f"  Unexpected in events: {extra_in_events}")
            sys.exit(1)
    print(f"[INIT] Symbols detected: {symbols}")

    broker_specs = {}
    for sym in symbols:
        broker_specs[sym] = load_broker_spec(sym)
    print(f"[INIT] Broker specs loaded: {len(broker_specs)}")
    print(f"[INIT] Profiles: {list(PROFILES.keys())}")

    # MT5-verified static valuation — no dynamic conversion needed.
    # All broker specs now have MT5-derived usd_pnl_per_price_unit_0p01 = tick_value/tick_size*0.01
    # which already accounts for currency conversion (MT5 tick_value is in account currency).
    print("[INIT] Using MT5-verified static valuation (dynamic conversion disabled)")

    # Phase 4: Run multi-profile simulation (static MT5 valuation)
    states = run_simulation(sorted_events, broker_specs, conv_lookup=None)

    # Print per-profile validation
    for state in states.values():
        print_validation_summary(state)

    # Print comparative summary
    print_comparative_summary(states)

    # Phase 5: Emit artifacts
    deployable_root = STRATEGIES_DIR / args.strategy_prefix / "deployable"
    deployable_root.mkdir(parents=True, exist_ok=True)
    all_metrics = {}
    
    true_constituent_runs = len(run_dirs)
    if args.strategy_prefix.startswith("PF_"):
        meta_file = STRATEGIES_DIR / args.strategy_prefix / "portfolio_evaluation" / "portfolio_metadata.json"
        if meta_file.exists():
            try:
                import json
                with open(meta_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                    c_runs = m_data.get("constituent_run_ids", [])
                    if c_runs:
                        true_constituent_runs = len(c_runs)
            except Exception:
                pass
                
    for name, state in states.items():
        profile_dir = deployable_root / name
        metrics = emit_profile_artifacts(state, profile_dir, true_constituent_runs, len(symbols))
        plot_equity_curve(state, profile_dir)
        all_metrics[name] = metrics

    emit_comparison_json(all_metrics, states, deployable_root)

    try:
        from tools.post_process_capital import process_profile_comparison
        process_profile_comparison(args.strategy_prefix)
    except Exception as e:
        print(f"[WARN] post_process_capital failed for {args.strategy_prefix}: {e}")

    print(f"[DONE] All artifacts emitted to {deployable_root}")


if __name__ == "__main__":
    main()
