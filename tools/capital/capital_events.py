"""Trade events, signal hashing, and artifact loading.

Exposes:
  TradeEvent / OpenTrade                  — dataclasses
  EVENT_TYPE_ENTRY/EXIT/PARTIAL           — type tokens
  EVENT_TYPE_PRIORITY, SIMULATION_SEED    — sort + RNG constants
  compute_signal_hash                     — 16-char SHA-256 signal fingerprint
  _normalize_hash_timestamp               — UTC-second normalisation for hashing
  REQUIRED_COLUMNS / OPTIONAL_RECON_COLUMNS
  _parse_ts / _optional_float             — parsing helpers
  load_trades / load_partial_legs         — raw-artifact loaders
  build_events / sort_events              — event-stream assembly
  print_events                            — diagnostic dump
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


# ======================================================================
# EVENT TYPE TOKENS + ORDERING
# ======================================================================

EVENT_TYPE_ENTRY = "ENTRY"
EVENT_TYPE_EXIT = "EXIT"
EVENT_TYPE_PARTIAL = "PARTIAL"
SIMULATION_SEED = 42          # RNG seed for deterministic collision-randomisation

# EXIT frees capital -> first; PARTIAL operates on still-open trade; ENTRY last.
EVENT_TYPE_PRIORITY = {
    EVENT_TYPE_EXIT: 0,
    EVENT_TYPE_PARTIAL: 1,
    EVENT_TYPE_ENTRY: 2,
}


# ======================================================================
# SIGNAL INTEGRITY
# ======================================================================

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


# ======================================================================
# EVENT + OPEN-TRADE DATACLASSES
# ======================================================================

@dataclass
class TradeEvent:
    """Single chronological event in the portfolio simulation queue."""
    timestamp: datetime
    event_type: str         # "ENTRY" | "PARTIAL" | "EXIT"
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
    # PARTIAL-only fields (None on ENTRY/EXIT).
    partial_fraction: Optional[float] = None
    partial_exit_price: Optional[float] = None

    @property
    def sort_key(self):
        """Deterministic sort: timestamp -> event_type priority -> trade_id."""
        return (self.timestamp, EVENT_TYPE_PRIORITY[self.event_type], self.trade_id)


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
# COLUMN CONTRACTS
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


# ======================================================================
# PARSING HELPERS
# ======================================================================

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


# ======================================================================
# ARTIFACT LOADERS
# ======================================================================

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


def load_partial_legs(run_dirs: List[Path]) -> dict:
    """Load results_partial_legs.csv sidecar per run_dir.

    Keyed by composite `trade_id` used by build_events: `strategy_name|parent_trade_id`.
    Sidecar is optional; missing file = pre-v1.5.7 run (empty dict returned).
    Engine contract: at most one partial per parent.
    """
    partials: dict = {}
    REQUIRED = [
        "strategy_name", "parent_trade_id",
        "partial_exit_timestamp", "partial_exit_price",
        "partial_fraction", "partial_pnl_usd",
    ]
    for run_dir in run_dirs:
        csv_path = run_dir / "raw" / "results_partial_legs.csv"
        if not csv_path.exists():
            continue
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"[FATAL] {csv_path} missing required columns: {missing}"
                )
            for row in reader:
                tid = f"{row['strategy_name']}|{row['parent_trade_id']}"
                if tid in partials:
                    raise ValueError(
                        f"[FATAL] duplicate partial for {tid} in {csv_path}"
                    )
                partials[tid] = {
                    "timestamp": _parse_ts(row["partial_exit_timestamp"]),
                    "exit_price": float(row["partial_exit_price"]),
                    "fraction":   float(row["partial_fraction"]),
                    "pnl_usd_sidecar": float(row["partial_pnl_usd"]),
                }
    if partials:
        print(f"[LOAD] Partial legs loaded: {len(partials)}")
    return partials


# ======================================================================
# EVENT ASSEMBLY + ORDERING
# ======================================================================

def build_events(trades: list, partials_by_parent: Optional[dict] = None) -> List[TradeEvent]:
    """Decompose each trade into ENTRY + (optional PARTIAL) + EXIT events."""
    events = []
    partials_by_parent = partials_by_parent or {}
    partials_emitted = 0

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

        pl = partials_by_parent.get(trade_id)
        if pl is not None:
            # Sanity: partial must sit inside [entry, exit] window.
            if not (entry_ts <= pl["timestamp"] <= exit_ts):
                raise ValueError(
                    f"[FATAL] partial timestamp {pl['timestamp']} outside "
                    f"[{entry_ts}, {exit_ts}] for {trade_id}"
                )
            events.append(TradeEvent(
                timestamp=pl["timestamp"], event_type=EVENT_TYPE_PARTIAL,
                trade_id=trade_id, symbol=symbol, direction=direction,
                entry_price=entry_price, exit_price=exit_price,
                risk_distance=risk_distance,
                initial_stop_price=initial_stop_price,
                atr_entry=atr_entry,
                r_multiple=r_multiple,
                volatility_regime=volatility_regime,
                trend_regime=trend_regime,
                trend_label=trend_label,
                partial_fraction=pl["fraction"],
                partial_exit_price=pl["exit_price"],
            ))
            partials_emitted += 1

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

    expected = len(trades) * 2 + partials_emitted
    print(f"[BUILD] Total events created: {len(events)}  (expected: {expected})")
    if len(events) != expected:
        raise RuntimeError(f"Event count mismatch: {len(events)} != {expected}")
    return events


def sort_events(events: List[TradeEvent]) -> List[TradeEvent]:
    """Sort: timestamp ASC -> ENTRY before EXIT -> trade_id ASC."""
    return sorted(events, key=lambda e: e.sort_key)


# ======================================================================
# VALIDATION OUTPUT
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
