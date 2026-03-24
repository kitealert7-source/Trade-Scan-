"""Capital simulation and state engine extracted from capital_wrapper."""

from __future__ import annotations

import bisect
import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOAT_TOLERANCE = 1e-9

EVENT_TYPE_ENTRY = "ENTRY"
EVENT_TYPE_EXIT = "EXIT"
SIMULATION_SEED = 42
EVENT_TYPE_PRIORITY = {
    EVENT_TYPE_EXIT: 0,
    EVENT_TYPE_ENTRY: 1,
}

CONVERSION_MAP = {
    "USD": None,
    "JPY": ("USDJPY", True),
    "CAD": ("USDCAD", True),
    "CHF": ("USDCHF", True),
    "GBP": ("GBPUSD", False),
    "AUD": ("AUDUSD", False),
    "NZD": ("NZDUSD", False),
    "EUR": ("EURUSD", False),
}


def _normalize_hash_timestamp(entry_timestamp) -> str:
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
    entry_timestamp,
    direction: int,
    entry_price: float,
    risk_distance: float,
) -> str:
    ts_norm = _normalize_hash_timestamp(entry_timestamp)
    s = (
        f"{symbol}|{ts_norm}|{direction}"
        f"|{entry_price:.5f}|{risk_distance:.5f}"
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class TradeEvent:
    timestamp: datetime
    event_type: str
    trade_id: str
    symbol: str
    direction: int
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
        return (self.timestamp, EVENT_TYPE_PRIORITY[self.event_type], self.trade_id)


def _parse_fx_currencies(symbol: str) -> Tuple[str, str]:
    if len(symbol) == 6 and symbol.isalpha():
        return symbol[:3], symbol[3:]
    return "", ""


def load_broker_spec(symbol: str) -> dict:
    broker_specs_root = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
    spec_path = broker_specs_root / f"{symbol}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"Missing broker spec: {spec_path}")
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_usd_per_price_unit_static(spec: dict) -> float:
    cal = spec.get("calibration", {})
    usd_per_pu_0p01 = cal.get("usd_pnl_per_price_unit_0p01")
    if usd_per_pu_0p01 is None:
        raise ValueError(
            f"Broker spec for {spec.get('symbol','?')} missing calibration.usd_pnl_per_price_unit_0p01"
        )
    return float(usd_per_pu_0p01) * 100.0


class ConversionLookup:
    def __init__(self):
        self._series: Dict[str, List[Tuple[date_type, float]]] = {}
        self._dates: Dict[str, List[date_type]] = {}
        self._fallback_warned: set = set()

    def load(self, currencies_needed: set, data_root: Optional[Path] = None):
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
                entries = []
                for _, row in df.iterrows():
                    ts = pd.to_datetime(row.get("timestamp", row.get("date")), utc=True)
                    close = float(row["close"])
                    rate = (1.0 / close if close != 0 else 0.0) if inverted else close
                    entries.append((ts.date(), rate))

                entries.sort(key=lambda x: x[0])
                self._series[ccy] = entries
                self._dates[ccy] = [e[0] for e in entries]
                print(f"[CONV] Loaded {pair_symbol} -> {ccy}/USD: {len(entries)} daily bars")
            except FileNotFoundError:
                print(f"[WARN] Conversion data not found for {pair_symbol}. Will use YAML fallback for {ccy}.")

    @staticmethod
    def _normalize_lookup_date(lookup_input) -> date_type:
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
        if currency == "USD":
            return 1.0

        dates = self._dates.get(currency)
        series = self._series.get(currency)
        if dates is None or series is None:
            return None

        lookup_date = self._normalize_lookup_date(lookup_input)
        idx = bisect.bisect_right(dates, lookup_date) - 1
        if idx < 0:
            idx = 0
        return series[idx][1]


def get_usd_per_price_unit_dynamic(
    contract_size: float,
    quote_ccy: str,
    entry_timestamp,
    conv_lookup: ConversionLookup,
    static_fallback: float,
    symbol: str,
) -> Tuple[float, str]:
    del symbol
    rate = conv_lookup.get_rate(quote_ccy, entry_timestamp)
    if rate is not None:
        return contract_size * rate, "DYNAMIC"
    return static_fallback, "STATIC_FALLBACK"


@dataclass
class OpenTrade:
    trade_id: str
    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    lot_size: float
    risk_usd: float
    notional_usd: float
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


@dataclass
class PortfolioState:
    profile_name: str
    starting_capital: float
    risk_per_trade: float
    heat_cap: float
    leverage_cap: float
    min_lot: float
    lot_step: float
    concurrency_cap: Optional[int] = None
    fixed_risk_usd: Optional[float] = None
    dynamic_scaling: bool = False
    min_position_pct: float = 0.0
    min_lot_fallback: bool = False
    max_risk_multiple: Optional[float] = 3.0
    track_risk_override: bool = False
    raw_lot_mode: bool = False  # If True: bypass all gates, execute every signal at min_lot
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
    closed_trades_log: List[dict] = field(default_factory=list)
    heat_samples: List[float] = field(default_factory=list)
    symbol_notional: Dict[str, float] = field(default_factory=dict)
    total_accepted: int = 0
    total_rejected: int = 0
    accepted_trade_ids: List[str] = field(default_factory=list)
    _heat_breach: bool = False
    _leverage_breach: bool = False
    _equity_negative: bool = False

    def __post_init__(self):
        self.equity = self.starting_capital
        self.peak_equity = self.starting_capital

    def _floor_to_step(self, lots: float) -> float:
        steps = math.floor(lots / self.lot_step)
        return round(steps * self.lot_step, 8)

    def compute_lot_size(self, risk_distance: float, usd_per_pu_per_lot: float) -> float:
        if self.fixed_risk_usd is not None:
            base_risk_capital = self.fixed_risk_usd
        else:
            base_risk_capital = self.equity * self.risk_per_trade

        risk_capital = base_risk_capital
        if self.dynamic_scaling and self.equity > 0:
            remaining_heat_usd = (self.heat_cap * self.equity) - self.total_open_risk
            remaining_heat_usd = max(remaining_heat_usd, 0.0)
            risk_capital = min(risk_capital, remaining_heat_usd)

        risk_capital = max(risk_capital, 0.0)

        if self.min_position_pct > 0 and base_risk_capital > 0:
            if risk_capital < base_risk_capital * self.min_position_pct:
                return 0.0

        risk_per_lot = risk_distance * usd_per_pu_per_lot
        if risk_per_lot <= 0:
            return 0.0
        raw_lots = risk_capital / risk_per_lot
        return self._floor_to_step(raw_lots)

    def process_entry(self, event: TradeEvent, usd_per_pu_per_lot: float, contract_size: float) -> bool:
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

        if self.concurrency_cap is not None and len(self.open_trades) >= int(self.concurrency_cap):
            self._reject(
                event,
                "CONCURRENCY_CAP",
                f"open={len(self.open_trades)} >= cap={int(self.concurrency_cap)}",
            )
            return False

        lot_size = self.compute_lot_size(event.risk_distance, usd_per_pu_per_lot)
        risk_override = False

        if self.fixed_risk_usd is not None:
            target_risk = self.fixed_risk_usd
        else:
            target_risk = self.equity * self.risk_per_trade

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
                self._reject(event, "LOT_TOO_SMALL", f"computed={lot_size:.4f} < min={self.min_lot}")
                return False

        trade_risk_usd = event.risk_distance * usd_per_pu_per_lot * lot_size
        trade_notional = lot_size * event.entry_price * usd_per_pu_per_lot

        risk_multiple = trade_risk_usd / target_risk if target_risk > 0 else float("inf")
        if risk_override:
            if self.max_risk_multiple is not None and risk_multiple > self.max_risk_multiple:
                reason_str = "RISK_MULTIPLE_EXCEEDED" if self.profile_name == "BOUNDED_MIN_LOT_V1" else "RISK_MULT_EXCEEDED"
                self._reject(
                    event,
                    reason_str,
                    f"multiple={risk_multiple:.2f} > cap={self.max_risk_multiple}",
                )
                return False
            self.total_risk_overrides += 1
            self.risk_multiples.append(risk_multiple)

        new_risk = self.total_open_risk + trade_risk_usd
        heat_pct = new_risk / self.equity if self.equity > 0 else float("inf")
        if heat_pct > self.heat_cap + FLOAT_TOLERANCE:
            if self.dynamic_scaling:
                self._reject(event, "HEAT_CAP_EDGE", f"dynamic_scaled but rounding breach: {heat_pct:.4f} > {self.heat_cap}")
            else:
                self._reject(event, "HEAT_CAP", f"would_be={heat_pct:.4f} > cap={self.heat_cap}")
            return False

        new_notional = self.total_notional + trade_notional
        leverage_ratio = new_notional / self.equity if self.equity > 0 else float("inf")
        if leverage_ratio > self.leverage_cap + FLOAT_TOLERANCE:
            self._reject(event, "LEVERAGE_CAP", f"would_be={leverage_ratio:.2f}x > cap={self.leverage_cap}x")
            return False

        del contract_size
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

        if len(self.open_trades) > self.max_concurrent:
            self.max_concurrent = len(self.open_trades)

        self.equity_timeline.append((event.timestamp, self.equity))
        self._check_invariants()
        return True

    def process_exit(self, event: TradeEvent) -> Optional[float]:
        trade = self.open_trades.get(event.trade_id)
        if trade is None:
            return None

        price_delta = (trade.exit_price - trade.entry_price) * trade.direction
        pnl_usd = price_delta * trade.usd_per_price_unit_per_lot * trade.lot_size
        self.equity += pnl_usd
        self.realized_pnl += pnl_usd

        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        dd = self.peak_equity - self.equity
        if dd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd

        self.total_open_risk -= trade.risk_usd
        self.total_notional -= trade.notional_usd
        self.symbol_notional[trade.symbol] = self.symbol_notional.get(trade.symbol, 0.0) - trade.notional_usd
        if self.symbol_notional.get(trade.symbol, 0.0) <= 0:
            self.symbol_notional.pop(trade.symbol, None)

        if self.total_open_risk < 0:
            if abs(self.total_open_risk) > FLOAT_TOLERANCE:
                print(f"[WARN] total_open_risk drift detected ({self.total_open_risk:.12f}); clamped to 0.")
            self.total_open_risk = 0.0
        if self.total_notional < 0:
            if abs(self.total_notional) > FLOAT_TOLERANCE:
                print(f"[WARN] total_notional drift detected ({self.total_notional:.12f}); clamped to 0.")
            self.total_notional = 0.0

        del self.open_trades[event.trade_id]

        entry_ts_str = str(trade.entry_timestamp) if trade.entry_timestamp else ""
        log_entry = {
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "lot_size": trade.lot_size,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "risk_distance": trade.risk_distance,
            "initial_stop_price": trade.initial_stop_price,
            "atr_entry": trade.atr_entry,
            "r_multiple": trade.r_multiple,
            "volatility_regime": trade.volatility_regime,
            "trend_regime": trade.trend_regime,
            "trend_label": trade.trend_label,
            "pnl_usd": round(pnl_usd, 2),
            "entry_timestamp": entry_ts_str,
            "exit_timestamp": str(event.timestamp),
            "signal_hash": compute_signal_hash(
                trade.symbol, entry_ts_str, trade.direction, trade.entry_price, trade.risk_distance
            ),
        }
        if trade.risk_override_flag:
            log_entry.update(
                {
                    "risk_override_flag": True,
                    "target_risk_usd": round(trade.target_risk_usd, 2),
                    "actual_risk_usd": round(trade.actual_risk_usd, 2),
                    "risk_multiple": round(trade.risk_multiple, 2),
                }
            )
        self.closed_trades_log.append(log_entry)

        if self.equity > 0:
            self.heat_samples.append(self.total_open_risk / self.equity)
        self.equity_timeline.append((event.timestamp, self.equity))
        self._check_invariants()
        return pnl_usd

    def _reject(self, event: TradeEvent, reason: str, detail: str):
        self.rejection_log.append(
            {
                "trade_id": event.trade_id,
                "symbol": event.symbol,
                "timestamp": str(event.timestamp),
                "reason": reason,
                "detail": detail,
                "equity_at_rejection": round(self.equity, 2),
                "open_risk_at_rejection": round(self.total_open_risk, 2),
            }
        )
        self.total_rejected += 1

    def _check_invariants(self):
        if self.equity > 0:
            heat_pct = self.total_open_risk / self.equity
            if heat_pct > self.heat_cap + FLOAT_TOLERANCE:
                self._heat_breach = True
            lev_ratio = self.total_notional / self.equity
            if lev_ratio > self.leverage_cap + FLOAT_TOLERANCE:
                self._leverage_breach = True
        if self.equity < 0:
            self._equity_negative = True


def run_simulation(
    sorted_events: List[TradeEvent],
    broker_specs: Dict[str, dict],
    profiles: Optional[Dict[str, dict]] = None,
    conv_lookup: Optional[ConversionLookup] = None,
) -> Dict[str, PortfolioState]:
    if profiles is None:
        raise ValueError("profiles must be provided")

    states: Dict[str, PortfolioState] = {}
    for name, params in profiles.items():
        states[name] = PortfolioState(
            profile_name=name,
            starting_capital=params["starting_capital"],
            risk_per_trade=params.get("risk_per_trade", 0.0),
            heat_cap=params["heat_cap"],
            leverage_cap=params["leverage_cap"],
            min_lot=params["min_lot"],
            lot_step=params["lot_step"],
            concurrency_cap=params.get("concurrency_cap"),
            fixed_risk_usd=params.get("fixed_risk_usd"),
            dynamic_scaling=params.get("dynamic_scaling", False),
            min_position_pct=params.get("min_position_pct", 0.0),
            min_lot_fallback=params.get("min_lot_fallback", False),
            max_risk_multiple=params.get("max_risk_multiple", 3.0),
            track_risk_override=params.get("track_risk_override", False),
            raw_lot_mode=params.get("raw_lot_mode", False),
        )

    symbol_static_fallback: Dict[str, float] = {}
    symbol_contract_size: Dict[str, float] = {}
    symbol_quote_ccy: Dict[str, str] = {}
    for sym, spec in broker_specs.items():
        symbol_static_fallback[sym] = get_usd_per_price_unit_static(spec)
        symbol_contract_size[sym] = float(spec["contract_size"])
        _, quote = _parse_fx_currencies(sym)
        if quote:
            symbol_quote_ccy[sym] = quote
        else:
            symbol_quote_ccy[sym] = "USD"
            print(f"[ASSUMPTION] Non-FX symbol '{sym}' treated as USD-quoted for conversion.")

    rng = random.Random(SIMULATION_SEED)
    i = 0
    n = len(sorted_events)
    while i < n:
        ts = sorted_events[i].timestamp
        j = i
        while j < n and sorted_events[j].timestamp == ts:
            j += 1
        group = sorted_events[i:j]
        i = j

        exits = [e for e in group if e.event_type == EVENT_TYPE_EXIT]
        entries = [e for e in group if e.event_type == EVENT_TYPE_ENTRY]
        rng.shuffle(entries)

        for event in exits + entries:
            sym = event.symbol
            if sym not in symbol_contract_size:
                raise ValueError(f"No broker spec loaded for symbol: {sym}")

            cs = symbol_contract_size[sym]

            if event.event_type == EVENT_TYPE_ENTRY:
                if conv_lookup is not None:
                    usd_per_pu, _ = get_usd_per_price_unit_dynamic(
                        contract_size=cs,
                        quote_ccy=symbol_quote_ccy[sym],
                        entry_timestamp=event.timestamp,
                        conv_lookup=conv_lookup,
                        static_fallback=symbol_static_fallback[sym],
                        symbol=sym,
                    )
                else:
                    usd_per_pu = symbol_static_fallback[sym]

                for state in states.values():
                    state.process_entry(event, usd_per_pu, cs)
            elif event.event_type == EVENT_TYPE_EXIT:
                for state in states.values():
                    state.process_exit(event)

    return states
