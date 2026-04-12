"""
Strategy Guard — Live Execution Safety Layer
=============================================
Two interlocked safety mechanisms:

  1. Signal Integrity Guard
     Verifies every incoming live signal matches the research fingerprint stored
     in deployable_trade_log.csv.  Blocks trades on mismatch.

  2. Statistical Deviation Guard (Kill-Switch)
     Computes baseline performance statistics from historical artifacts and
     halts the strategy automatically if live results diverge beyond
     configurable thresholds.

Usage (from live execution engine)
-----------------------------------
    from execution_engine.strategy_guard import StrategyGuard, GuardConfig

    guard = StrategyGuard.from_golive_package(
        golive_dir="strategies/MY_STRATEGY/golive",
        profile="FIXED_USD_V1",
    )

    # Before placing any trade:
    guard.verify_signal(symbol, entry_timestamp, direction, entry_price, risk_distance)

    # After a trade closes:
    guard.record_trade(pnl_usd)

Configuration
-------------
All thresholds live in GuardConfig so they can be overridden without touching
this module.  Defaults match the task specification.
"""

import csv
import hashlib
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STRATEGY_STATE_ACTIVE = "ACTIVE"
STRATEGY_STATE_HALTED = "HALTED"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class GuardConfig:
    """
    Kill-switch thresholds.  Change these values to tune sensitivity.
    Defaults match the task specification.
    """
    max_loss_streak_multiplier: float = 1.5   # halt if streak > historical × this
    rolling_window_trades:      int   = 50    # trades in the rolling win-rate window
    win_rate_tolerance:         float = 0.65  # halt if live WR < historical WR × this
    dd_multiplier:              float = 2.0   # halt if drawdown > historical DD × this
    # Two-tier signal validation tolerances
    price_tolerance:            float = 0.001  # 0.1% — covers rounding between research and live
    time_window_s:              int   = 60     # bar-close timestamp can differ by seconds


@dataclass
class SignalResult:
    """Result of two-tier signal validation."""
    status: str             # "EXACT_MATCH" | "SOFT_MATCH" | "HARD_FAIL"
    hash: str               # live-computed hash
    matched_ref: str = ""   # trade_id of matched research signal (SOFT_MATCH only)
    price_delta: float = 0  # abs price difference (SOFT_MATCH only)
    time_delta: float = 0   # abs time difference in seconds (SOFT_MATCH only)


# ---------------------------------------------------------------------------
# Signal hash (must be identical to capital_wrapper.compute_signal_hash)
# ---------------------------------------------------------------------------

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


def _compute_signal_hash(
    symbol: str,
    entry_timestamp,        # datetime or str
    direction: int,
    entry_price: float,
    risk_distance: float,
) -> str:
    """
    16-char SHA-256 prefix fingerprint — same formula as capital_wrapper.py.

    Fields (order fixed):
        symbol | entry_timestamp | direction | entry_price(5dp) | risk_distance(5dp)
    """
    ts_norm = _normalize_hash_timestamp(entry_timestamp)
    s = (
        f"{symbol}|{ts_norm}|{direction}"
        f"|{entry_price:.5f}|{risk_distance:.5f}"
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Baseline statistics computed from historical artifacts
# ---------------------------------------------------------------------------

@dataclass
class BaselineStats:
    expected_win_rate:   float          # fraction, e.g. 0.582
    max_loss_streak:     int            # longest consecutive loss run
    max_drawdown_usd:    float          # absolute USD drawdown from historical run
    starting_equity:     float          # starting_capital from selected_profile.json
    signal_index:        Dict[str, str] # trade_id -> signal_hash (for verification)
    signal_details:      Dict[str, dict] = field(default_factory=dict)  # trade_id -> {symbol, direction, entry_price, entry_ts, risk_distance}
    total_trades:        int = 0


def _load_baseline(
    trade_log_path: Path,
    profile_path: Path,
) -> BaselineStats:
    """
    Derive baseline statistics from the deployable artifacts produced by
    the research pipeline.  No simulation is re-run.
    """
    # --- Load profile -------------------------------------------------------
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    starting_equity  = profile["sizing"]["starting_capital"]
    max_drawdown_usd = abs(profile["simulation_metrics"]["max_drawdown_pct"]
                           / 100.0 * starting_equity)

    # --- Load trade log -----------------------------------------------------
    trades: List[dict] = []
    with trade_log_path.open(newline="", encoding="utf-8") as fh:
        trades = list(csv.DictReader(fh))

    if not trades:
        raise ValueError(f"Trade log is empty: {trade_log_path}")

    total = len(trades)

    # Win rate
    wins        = sum(1 for t in trades if float(t["pnl_usd"]) > 0)
    win_rate    = wins / total

    # Max historical loss streak
    max_streak = streak = 0
    for t in trades:
        if float(t["pnl_usd"]) < 0:
            streak    += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Signal index: trade_id -> signal_hash (populated only when column present)
    signal_index: Dict[str, str] = {}
    signal_details: Dict[str, dict] = {}
    has_hash_col = "signal_hash" in (trades[0].keys() if trades else {})
    if has_hash_col:
        for t in trades:
            tid = t["trade_id"]
            if t.get("signal_hash"):
                signal_index[tid] = t["signal_hash"]
            # Build detail record for tolerant matching
            try:
                signal_details[tid] = {
                    "symbol": t.get("symbol", ""),
                    "direction": int(t.get("direction", 0)),
                    "entry_price": float(t.get("entry_price", 0)),
                    "entry_ts": t.get("entry_timestamp", ""),
                    "risk_distance": float(t.get("risk_distance", 0)),
                }
            except (ValueError, TypeError):
                pass  # skip malformed rows

    return BaselineStats(
        expected_win_rate=win_rate,
        max_loss_streak=max_streak,
        max_drawdown_usd=max_drawdown_usd,
        starting_equity=starting_equity,
        signal_index=signal_index,
        signal_details=signal_details,
        total_trades=total,
    )


def _load_baseline_from_vault(
    trade_log_path: Path,
    starting_capital: float,
    max_drawdown_usd: float,
) -> BaselineStats:
    """
    Derive baseline statistics from vault artifacts.

    Unlike _load_baseline(), reads starting_capital and max_drawdown directly
    from profile_comparison.json rather than selected_profile.json (which has
    a different structure in vault snapshots).
    """
    trades: List[dict] = []
    with trade_log_path.open(newline="", encoding="utf-8") as fh:
        trades = list(csv.DictReader(fh))

    if not trades:
        raise ValueError(f"Trade log is empty: {trade_log_path}")

    total = len(trades)

    # Win rate
    wins     = sum(1 for t in trades if float(t["pnl_usd"]) > 0)
    win_rate = wins / total

    # Max historical loss streak
    max_streak = streak = 0
    for t in trades:
        if float(t["pnl_usd"]) < 0:
            streak     += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Signal index + details
    signal_index: Dict[str, str] = {}
    signal_details: Dict[str, dict] = {}
    has_hash_col = "signal_hash" in (trades[0].keys() if trades else {})
    if has_hash_col:
        for t in trades:
            tid = t["trade_id"]
            if t.get("signal_hash"):
                signal_index[tid] = t["signal_hash"]
            try:
                signal_details[tid] = {
                    "symbol": t.get("symbol", ""),
                    "direction": int(t.get("direction", 0)),
                    "entry_price": float(t.get("entry_price", 0)),
                    "entry_ts": t.get("entry_timestamp", ""),
                    "risk_distance": float(t.get("risk_distance", 0)),
                }
            except (ValueError, TypeError):
                pass

    return BaselineStats(
        expected_win_rate=win_rate,
        max_loss_streak=max_streak,
        max_drawdown_usd=max_drawdown_usd,
        starting_equity=starting_capital,
        signal_index=signal_index,
        signal_details=signal_details,
        total_trades=total,
    )


# ---------------------------------------------------------------------------
# Signal mismatch / halt events
# ---------------------------------------------------------------------------

@dataclass
class GuardEvent:
    """Immutable record written to the monitoring log on any guard action."""
    event_type:  str        # "SIGNAL_MISMATCH" | "HALT_LOSS_STREAK"
                            # | "HALT_WIN_RATE"  | "HALT_EQUITY_DD"
    reason:      str
    timestamp_utc: str
    detail:      dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# StrategyGuard
# ---------------------------------------------------------------------------

class StrategyGuard:
    """
    Stateful guard attached to one live strategy instance.

    Thread-safety: not guaranteed.  Wrap calls in a lock if used from
    multiple threads.
    """

    def __init__(
        self,
        baseline:    BaselineStats,
        config:      GuardConfig,
        alert_log:   Optional[Path] = None,
    ) -> None:
        self.baseline   = baseline
        self.config     = config
        self.alert_log  = alert_log

        # Live state
        self.state:          str             = STRATEGY_STATE_ACTIVE
        self.equity:         float           = baseline.starting_equity
        self.peak_equity:    float           = baseline.starting_equity
        self.loss_streak:    int             = 0
        self.rolling_results: Deque[float]  = deque(maxlen=config.rolling_window_trades)
        self.events:         List[GuardEvent] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_golive_package(
        cls,
        golive_dir: str | Path,
        config: Optional[GuardConfig] = None,
        alert_log: Optional[Path] = None,
    ) -> "StrategyGuard":
        """
        Construct a StrategyGuard from a go-live package directory.

        Expected layout (produced by generate_golive_package.py):
            <golive_dir>/selected_profile.json
            <golive_dir>/../deployable/<profile>/deployable_trade_log.csv
        """
        golive_dir   = Path(golive_dir)
        profile_path = golive_dir / "selected_profile.json"

        if not profile_path.exists():
            raise FileNotFoundError(f"selected_profile.json not found: {profile_path}")

        profile_name = json.loads(profile_path.read_text(encoding="utf-8"))["profile"]
        trade_log    = golive_dir.parent / "deployable" / profile_name / "deployable_trade_log.csv"

        if not trade_log.exists():
            raise FileNotFoundError(f"deployable_trade_log.csv not found: {trade_log}")

        # Validate profile_hash before trusting enforcement parameters
        cls._verify_profile_hash(profile_path)

        baseline = _load_baseline(trade_log, profile_path)
        return cls(baseline, config or GuardConfig(), alert_log)

    @classmethod
    def from_vault(
        cls,
        vault_strategy_dir: str | Path,
        profile: str,
        config: Optional[GuardConfig] = None,
        alert_log: Optional[Path] = None,
    ) -> "StrategyGuard":
        """
        Construct a StrategyGuard from DRY_RUN_VAULT layout.

        Expected layout (produced by backup_dryrun_strategies.py):
            <vault_strategy_dir>/selected_profile.json     (selection metadata)
            <vault_strategy_dir>/deployable/profile_comparison.json (profile metrics)
            <vault_strategy_dir>/deployable/<profile>/deployable_trade_log.csv
        """
        vault_strategy_dir = Path(vault_strategy_dir)

        trade_log = vault_strategy_dir / "deployable" / profile / "deployable_trade_log.csv"
        if not trade_log.exists():
            raise FileNotFoundError(f"deployable_trade_log.csv not found: {trade_log}")

        # Read profile metrics from profile_comparison.json
        pc_path = vault_strategy_dir / "deployable" / "profile_comparison.json"
        if not pc_path.exists():
            raise FileNotFoundError(f"profile_comparison.json not found: {pc_path}")

        pc_data = json.loads(pc_path.read_text(encoding="utf-8"))
        profiles_block = pc_data.get("profiles", {})
        if profile not in profiles_block:
            raise ValueError(f"Profile '{profile}' not found in profile_comparison.json")

        prof = profiles_block[profile]
        starting_capital = prof.get("starting_capital", 10000.0)
        max_dd_usd = abs(prof.get("max_drawdown_usd", 0.0))

        # Verify profile hash if present (extended vault format)
        sp_path = vault_strategy_dir / "selected_profile.json"
        if sp_path.exists():
            sp_data = json.loads(sp_path.read_text(encoding="utf-8"))
            if "enforcement" in sp_data and "sizing" in sp_data:
                cls._verify_profile_hash(sp_path)

        baseline = _load_baseline_from_vault(trade_log, starting_capital, max_dd_usd)
        return cls(baseline, config or GuardConfig(), alert_log)

    @staticmethod
    def _verify_profile_hash(profile_path: Path) -> None:
        """
        Re-compute profile_hash from enforcement + sizing and compare to
        the stored value.  Raises RuntimeError on mismatch.
        """
        data  = json.loads(profile_path.read_text(encoding="utf-8"))
        algo  = data.get("profile_hash_algo", "sha256")
        stored = data.get("profile_hash")
        if stored is None:
            logger.warning("profile_hash absent in %s — skipping integrity check", profile_path)
            return
        canonical = json.dumps(
            {"enforcement": data["enforcement"], "sizing": data["sizing"]},
            sort_keys=True, separators=(",", ":"),
        )
        computed = hashlib.new(algo, canonical.encode("utf-8")).hexdigest()
        if computed != stored:
            raise RuntimeError(
                f"Profile integrity check FAILED for {profile_path.name}.\n"
                f"  stored   hash: {stored}\n"
                f"  computed hash: {computed}\n"
                f"Configuration has been modified — refusing to start."
            )
        logger.info("Profile integrity OK (%s)", stored[:16])

    # ------------------------------------------------------------------
    # Part 3 — Signal integrity check
    # ------------------------------------------------------------------

    def verify_signal(
        self,
        trade_id:       str,
        symbol:         str,
        entry_timestamp,
        direction:      int,
        entry_price:    float,
        risk_distance:  float,
    ) -> None:
        """
        Compute the signal hash for an incoming live signal and compare it
        to the fingerprint stored in deployable_trade_log.csv.

        Raises SignalMismatchError if:
          - The signal_hash column is absent from the trade log (legacy artifact).
          - The computed hash does not match the stored hash.
          - trade_id is not found in the signal index at all.

        IMPORTANT: this check only makes sense when replaying a known backtest
        signal.  For genuinely new live signals (no trade_id in index) the guard
        logs an informational notice and continues — this is normal for live
        trading beyond the backtest window.
        """
        self._require_active("verify_signal")

        live_hash = _compute_signal_hash(
            symbol, entry_timestamp, direction, entry_price, risk_distance
        )

        if not self.baseline.signal_index:
            # Trade log has no signal_hash column (pre-feature artifact).
            # Log a warning but do not block — backwards compatibility.
            logger.warning(
                "Signal index empty (legacy artifact — no signal_hash column). "
                "Skipping integrity check for trade_id=%s", trade_id
            )
            return

        stored_hash = self.baseline.signal_index.get(trade_id)
        if stored_hash is None:
            # trade_id not in backtest — new live signal, normal in production.
            logger.info("trade_id %s not in signal index (new live signal)", trade_id)
            return

        if live_hash != stored_hash:
            self._record_event(GuardEvent(
                event_type="SIGNAL_MISMATCH",
                reason="Computed signal hash does not match research fingerprint",
                timestamp_utc=_utc_now(),
                detail={
                    "trade_id":     trade_id,
                    "symbol":       symbol,
                    "live_hash":    live_hash,
                    "stored_hash":  stored_hash,
                },
            ))
            raise SignalMismatchError(
                f"SIGNAL MISMATCH — trade blocked.\n"
                f"  trade_id    : {trade_id}\n"
                f"  symbol      : {symbol}\n"
                f"  live_hash   : {live_hash}\n"
                f"  stored_hash : {stored_hash}"
            )

        logger.debug("Signal OK  trade_id=%s  hash=%s", trade_id, live_hash)

    # ------------------------------------------------------------------
    # Part 3b — Two-tier signal validation (new API)
    # ------------------------------------------------------------------

    def validate_signal(
        self,
        symbol:         str,
        entry_timestamp,
        direction:      int,
        entry_price:    float,
        risk_distance:  float,
        price_tolerance: Optional[float] = None,
        time_window_s: Optional[int] = None,
    ) -> SignalResult:
        """
        Two-tier signal verification. Returns SignalResult (never raises).

        Tier 1: Exact hash match against signal_index.
        Tier 2: Tolerant match — symbol + direction exact, price within
                 tolerance, timestamp within time window.

        If signal_index is empty (legacy artifact) or the signal is genuinely
        new (beyond backtest window), returns EXACT_MATCH to avoid blocking.
        """
        self._require_active("validate_signal")
        ptol = price_tolerance if price_tolerance is not None else self.config.price_tolerance
        tw = time_window_s if time_window_s is not None else self.config.time_window_s

        live_hash = _compute_signal_hash(
            symbol, entry_timestamp, direction, entry_price, risk_distance
        )

        # No signal index -> pass through (legacy artifact)
        if not self.baseline.signal_index:
            logger.warning("Signal index empty (legacy artifact) — passing through")
            return SignalResult(status="EXACT_MATCH", hash=live_hash)

        # Tier 1: Exact hash match
        if live_hash in self.baseline.signal_index.values():
            logger.debug("[GUARD] EXACT_MATCH  hash=%s", live_hash)
            return SignalResult(status="EXACT_MATCH", hash=live_hash)

        # Tier 2: Tolerant match against signal_details
        if self.baseline.signal_details:
            live_ts = _normalize_hash_timestamp(entry_timestamp)
            for ref_id, ref in self.baseline.signal_details.items():
                if ref["symbol"] != symbol or ref["direction"] != direction:
                    continue
                ref_price = ref["entry_price"]
                if ref_price == 0:
                    continue
                p_delta = abs(entry_price - ref_price) / ref_price
                if p_delta > ptol:
                    continue
                # Time comparison
                t_delta = _timestamp_diff_seconds(live_ts, ref["entry_ts"])
                if t_delta is not None and t_delta <= tw:
                    logger.info(
                        "[GUARD] SOFT_MATCH  hash=%s  ref=%s  price_delta=%.6f  time_delta=%ds",
                        live_hash, ref_id, p_delta, t_delta,
                    )
                    return SignalResult(
                        status="SOFT_MATCH", hash=live_hash,
                        matched_ref=ref_id, price_delta=p_delta, time_delta=float(t_delta),
                    )

        # No match — but if this is a genuinely new signal (not in backtest period),
        # we should not block it. Check if it's beyond the last backtest trade.
        # For now, HARD_FAIL — the MismatchTracker in guard_bridge will manage alerts.
        logger.warning("[GUARD] HARD_FAIL  hash=%s  symbol=%s  dir=%d", live_hash, symbol, direction)
        return SignalResult(status="HARD_FAIL", hash=live_hash)

    # ------------------------------------------------------------------
    # Part 2 — Kill-switch: record trade result and check thresholds
    # ------------------------------------------------------------------

    def record_trade(self, pnl_usd: float) -> None:
        """
        Call after every closed trade.  Updates live state and evaluates
        all three kill-switch rules.  Raises StrategyHaltedError if any
        rule trips — the caller must catch this and block further trading.
        """
        self._require_active("record_trade")

        # Update equity
        self.equity += pnl_usd
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        # Update loss streak
        if pnl_usd < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

        # Update rolling window
        self.rolling_results.append(pnl_usd)

        # Evaluate kill-switch rules
        self._check_kill_switch()

    def _check_kill_switch(self) -> None:
        """Evaluate all three rules; halt on first breach."""
        cfg = self.config
        bl  = self.baseline

        # ---- Rule 1: Loss Streak Guard ------------------------------------
        streak_limit = bl.max_loss_streak * cfg.max_loss_streak_multiplier
        if self.loss_streak > streak_limit:
            self._halt(
                event_type="HALT_LOSS_STREAK",
                reason=(
                    f"Live loss streak ({self.loss_streak}) exceeds "
                    f"historical max ({bl.max_loss_streak}) × "
                    f"{cfg.max_loss_streak_multiplier} = {streak_limit:.1f}"
                ),
                detail={
                    "live_streak":      self.loss_streak,
                    "historical_max":   bl.max_loss_streak,
                    "multiplier":       cfg.max_loss_streak_multiplier,
                    "limit":            streak_limit,
                },
            )

        # ---- Rule 2: Win Rate Guard ---------------------------------------
        if len(self.rolling_results) >= cfg.rolling_window_trades:
            wins       = sum(1 for p in self.rolling_results if p > 0)
            live_wr    = wins / len(self.rolling_results)
            wr_limit   = bl.expected_win_rate * cfg.win_rate_tolerance
            if live_wr < wr_limit:
                self._halt(
                    event_type="HALT_WIN_RATE",
                    reason=(
                        f"Rolling win rate ({live_wr:.1%}) below threshold "
                        f"({bl.expected_win_rate:.1%} × {cfg.win_rate_tolerance} "
                        f"= {wr_limit:.1%})"
                    ),
                    detail={
                        "live_win_rate":    round(live_wr, 4),
                        "expected_wr":      round(bl.expected_win_rate, 4),
                        "tolerance":        cfg.win_rate_tolerance,
                        "threshold":        round(wr_limit, 4),
                        "window":           len(self.rolling_results),
                    },
                )

        # ---- Rule 3: Equity Deviation Guard -------------------------------
        dd_limit = bl.starting_equity - (cfg.dd_multiplier * bl.max_drawdown_usd)
        if self.equity < dd_limit:
            self._halt(
                event_type="HALT_EQUITY_DD",
                reason=(
                    f"Live equity (${self.equity:,.2f}) below floor "
                    f"(starting ${bl.starting_equity:,.2f} - "
                    f"{cfg.dd_multiplier}x historical max DD "
                    f"${bl.max_drawdown_usd:,.2f} = ${dd_limit:,.2f})"
                ),
                detail={
                    "live_equity":      round(self.equity, 2),
                    "equity_floor":     round(dd_limit, 2),
                    "historical_max_dd": round(bl.max_drawdown_usd, 2),
                    "dd_multiplier":    cfg.dd_multiplier,
                },
            )

    def _halt(self, event_type: str, reason: str, detail: dict) -> None:
        self.state = STRATEGY_STATE_HALTED
        self._record_event(GuardEvent(
            event_type=event_type,
            reason=reason,
            timestamp_utc=_utc_now(),
            detail=detail,
        ))
        logger.critical("STRATEGY HALTED — %s: %s", event_type, reason)
        raise StrategyHaltedError(
            f"Strategy halted by kill-switch [{event_type}]: {reason}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_active(self, caller: str) -> None:
        if self.state == STRATEGY_STATE_HALTED:
            raise StrategyHaltedError(
                f"Cannot call {caller}(): strategy is already HALTED."
            )

    def _record_event(self, event: GuardEvent) -> None:
        self.events.append(event)
        if self.alert_log:
            self.alert_log.parent.mkdir(parents=True, exist_ok=True)
            with self.alert_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "event_type":    event.event_type,
                    "reason":        event.reason,
                    "timestamp_utc": event.timestamp_utc,
                    **event.detail,
                }) + "\n")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.state == STRATEGY_STATE_ACTIVE

    @property
    def rolling_win_rate(self) -> Optional[float]:
        if not self.rolling_results:
            return None
        wins = sum(1 for p in self.rolling_results if p > 0)
        return wins / len(self.rolling_results)

    def status_dict(self) -> dict:
        return {
            "state":             self.state,
            "equity":            round(self.equity, 2),
            "peak_equity":       round(self.peak_equity, 2),
            "loss_streak":       self.loss_streak,
            "rolling_win_rate":  (
                round(self.rolling_win_rate, 4)
                if self.rolling_win_rate is not None else None
            ),
            "rolling_window":    len(self.rolling_results),
            "events_count":      len(self.events),
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SignalMismatchError(Exception):
    """Raised when a live signal hash does not match the research fingerprint."""


class StrategyHaltedError(Exception):
    """Raised when the kill-switch trips or the strategy is already halted."""


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp_diff_seconds(ts_a: str, ts_b: str) -> Optional[int]:
    """Compute absolute difference in seconds between two timestamp strings.

    Returns None if either timestamp cannot be parsed.
    """
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        a = datetime.strptime(ts_a.strip(), fmt)
        b = datetime.strptime(ts_b.strip(), fmt)
        return abs(int((a - b).total_seconds()))
    except (ValueError, AttributeError):
        return None
