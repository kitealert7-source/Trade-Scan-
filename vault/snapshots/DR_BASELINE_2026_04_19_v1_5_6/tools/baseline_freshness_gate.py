"""
baseline_freshness_gate.py — Blocking freshness check for deploy gates.

Compares the last baseline trade timestamp (per symbol) against the latest
available market data (data_root/freshness_index.json). If the gap exceeds
the configured threshold, the gate blocks promotion.

Called from:
    - tools/promote_to_burnin.py (threshold = 14 days) — BEFORE Layer 2 replay.
    - tools/promote_readiness.py (advisory, no threshold enforcement).

Not called from transition_to_live.py: once a strategy is in BURN_IN with a
fresh baseline, transitions onward (WAITING, LIVE) do not re-check freshness —
burn-in produces its own live-dry-run data which supersedes the backtest
baseline as the reference for subsequent validation.

Fail-fast (invariant #1) on missing freshness_index.json or unknown symbol.

Boundary rule: age > threshold blocks; age == threshold passes ("stale means
older than N days").
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.state_paths import BACKTESTS_DIR  # noqa: E402

FRESHNESS_INDEX_PATH = PROJECT_ROOT / "data_root" / "freshness_index.json"

Status = Literal["OK", "BLOCKED", "FAIL"]


@dataclass
class SymbolAge:
    symbol: str
    backtest_dir: str            # "<strategy_id>_<SYMBOL>" leaf name
    last_entry_date: str | None  # "YYYY-MM-DD"
    latest_data_date: str | None # "YYYY-MM-DD"
    age_days: int | None         # (latest_data - last_entry).days
    tf_key: str                  # e.g. "EURUSD_OCTAFX_15m"
    fail_reason: str | None = None


@dataclass
class FreshnessResult:
    strategy_id: str
    threshold_days: int
    status: Status
    worst_age_days: int | None
    per_symbol: list[SymbolAge] = field(default_factory=list)
    message: str = ""


# ────────────────────────────────────────────────────────────────────────────
# Public entry points
# ────────────────────────────────────────────────────────────────────────────

def check_freshness(strategy_id: str, threshold_days: int) -> FreshnessResult:
    """Run the full freshness gate. Returns a result; the caller decides to exit."""
    return _compute(strategy_id, threshold_days, enforce=True)


def compute_baseline_age(strategy_id: str) -> FreshnessResult:
    """Pure lookup — returns worst age with threshold=0 (never BLOCKED on age alone).
    Still returns FAIL if freshness_index is missing or the symbol isn't in the index."""
    return _compute(strategy_id, threshold_days=0, enforce=False)


def format_blocked_message(result: FreshnessResult) -> str:
    """Render the user-facing BLOCKED/FAIL block with remediation commands."""
    if result.status == "FAIL":
        reason_line = result.message.splitlines()[0] if result.message else "(no reason)"
        return (
            f"\n[FAIL] Baseline Freshness Gate — fail-fast (invariant #1)\n"
            f"  Reason: {reason_line}\n"
            f"  Resolve the upstream data invariant before retrying. Do not bypass.\n"
        )

    # BLOCKED path
    lines = [
        f"\n[BLOCKED] Baseline Freshness Gate failed for {result.strategy_id}",
        f"  Threshold:        {result.threshold_days} days",
    ]
    worst = _worst_symbol(result)
    if worst is not None:
        lines += [
            f"  Worst symbol:     {worst.symbol}  (age: {worst.age_days} days)",
            f"  Last trade:       {worst.last_entry_date}",
            f"  Latest data:      {worst.latest_data_date}",
        ]
    lines.append("")
    lines.append("  Per-symbol breakdown:")
    for s in result.per_symbol:
        if s.age_days is None:
            lines.append(f"    {s.symbol:<8} age=?    {s.fail_reason or ''}")
        else:
            lines.append(
                f"    {s.symbol:<8} age={s.age_days}d  "
                f"last={s.last_entry_date}  data={s.latest_data_date}"
            )
    lines += [
        "",
        "  Remediation — re-run the backtest against current data:",
        f"    1. python tools/reset_directive.py {result.strategy_id} --supersede --reason \"refresh stale baseline\"",
        f"       (retires prior ledger rows in place; Excel views regenerate from SQLite)",
        f"    2. python tools/run_pipeline.py {result.strategy_id}",
        f"       (Stages 3-4 append fresh Master Filter + MPS rows)",
        "",
    ]
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# Core
# ────────────────────────────────────────────────────────────────────────────

def _compute(strategy_id: str, threshold_days: int, enforce: bool) -> FreshnessResult:
    # 1. Freshness index must exist (invariant #1)
    if not FRESHNESS_INDEX_PATH.exists():
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="FAIL",
            worst_age_days=None,
            message=f"freshness_index.json missing at {FRESHNESS_INDEX_PATH}",
        )

    try:
        idx = json.loads(FRESHNESS_INDEX_PATH.read_text(encoding="utf-8"))
        entries = idx.get("entries", {})
    except (OSError, json.JSONDecodeError) as e:
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="FAIL",
            worst_age_days=None,
            message=f"freshness_index.json unreadable: {e}",
        )

    # 2. Resolve timeframe once from the strategy module
    tf = _resolve_tf_from_strategy(strategy_id)
    if tf is None:
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="FAIL",
            worst_age_days=None,
            message=f"Cannot resolve timeframe for strategy {strategy_id}",
        )

    # 3. Enumerate baselines
    baselines = _enumerate_baselines(strategy_id)
    if not baselines:
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="FAIL",
            worst_age_days=None,
            message=f"No baseline CSVs found under {BACKTESTS_DIR} for {strategy_id}",
        )

    per_symbol: list[SymbolAge] = []
    has_fail = False

    for csv_path in baselines:
        backtest_dir = csv_path.parents[1].name  # "<strategy_id>_<SYMBOL>"
        symbol = _extract_symbol_from_backtest_dir(backtest_dir, strategy_id)
        if symbol is None:
            per_symbol.append(SymbolAge(
                symbol="?", backtest_dir=backtest_dir,
                last_entry_date=None, latest_data_date=None,
                age_days=None, tf_key="",
                fail_reason=f"cannot parse symbol from {backtest_dir}",
            ))
            has_fail = True
            continue

        tf_key = f"{symbol}_OCTAFX_{tf}"
        last_entry = _read_last_entry_date(csv_path)
        fresh_entry = entries.get(tf_key)

        if fresh_entry is None:
            per_symbol.append(SymbolAge(
                symbol=symbol, backtest_dir=backtest_dir,
                last_entry_date=last_entry, latest_data_date=None,
                age_days=None, tf_key=tf_key,
                fail_reason=f"{tf_key} not in freshness_index",
            ))
            has_fail = True
            continue

        latest = fresh_entry.get("latest_date")
        if last_entry is None:
            per_symbol.append(SymbolAge(
                symbol=symbol, backtest_dir=backtest_dir,
                last_entry_date=None, latest_data_date=latest,
                age_days=None, tf_key=tf_key,
                fail_reason=f"baseline CSV empty or unreadable: {csv_path.name}",
            ))
            has_fail = True
            continue

        try:
            age = (date.fromisoformat(latest) - date.fromisoformat(last_entry)).days
        except ValueError as e:
            per_symbol.append(SymbolAge(
                symbol=symbol, backtest_dir=backtest_dir,
                last_entry_date=last_entry, latest_data_date=latest,
                age_days=None, tf_key=tf_key,
                fail_reason=f"date parse failed: {e}",
            ))
            has_fail = True
            continue

        per_symbol.append(SymbolAge(
            symbol=symbol, backtest_dir=backtest_dir,
            last_entry_date=last_entry, latest_data_date=latest,
            age_days=max(age, 0), tf_key=tf_key,
        ))

    if has_fail:
        bad = [s for s in per_symbol if s.fail_reason]
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="FAIL",
            worst_age_days=None,
            per_symbol=per_symbol,
            message="; ".join(s.fail_reason for s in bad if s.fail_reason),
        )

    worst = max((s.age_days or 0) for s in per_symbol)

    if enforce and worst > threshold_days:
        return FreshnessResult(
            strategy_id=strategy_id,
            threshold_days=threshold_days,
            status="BLOCKED",
            worst_age_days=worst,
            per_symbol=per_symbol,
            message=f"Worst baseline age {worst}d > threshold {threshold_days}d",
        )

    return FreshnessResult(
        strategy_id=strategy_id,
        threshold_days=threshold_days,
        status="OK",
        worst_age_days=worst,
        per_symbol=per_symbol,
    )


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _enumerate_baselines(strategy_id: str) -> list[Path]:
    """All results_tradelevel.csv under BACKTESTS_DIR for this strategy_id."""
    direct = BACKTESTS_DIR / strategy_id / "raw" / "results_tradelevel.csv"
    multi = list(BACKTESTS_DIR.glob(f"{strategy_id}_*/raw/results_tradelevel.csv"))
    result = []
    if direct.exists():
        result.append(direct)
    result.extend(multi)
    # Dedupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in result:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def _read_last_entry_date(csv_path: Path) -> str | None:
    """Read last non-empty entry_timestamp from CSV → YYYY-MM-DD. Streams the
    whole file but keeps only the last value (single column); memory-bounded."""
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "entry_timestamp" not in (reader.fieldnames or []):
                return None
            last = None
            for row in reader:
                ts = (row.get("entry_timestamp") or "").strip()
                if ts:
                    last = ts
        if not last:
            return None
        return last[:10]  # "YYYY-MM-DD..." → "YYYY-MM-DD"
    except (OSError, csv.Error):
        return None


def _extract_symbol_from_backtest_dir(dirname: str, strategy_id: str) -> str | None:
    """'<strategy_id>_EURUSD' → 'EURUSD'. Handles strategy_ids with underscores
    by stripping only the known prefix."""
    prefix = f"{strategy_id}_"
    if dirname == strategy_id:
        # Single-symbol folder with no suffix — try to derive from strategy_id itself
        from config.asset_classification import parse_strategy_name
        parsed = parse_strategy_name(strategy_id)
        if parsed and parsed.get("symbol_suffix"):
            return parsed["symbol_suffix"].upper()
        return None
    if not dirname.startswith(prefix):
        return None
    suffix = dirname[len(prefix):]
    return suffix.upper() if suffix else None


def _resolve_tf_from_strategy(strategy_id: str) -> str | None:
    """Load the strategy module and return its timeframe as the freshness_index
    key form (lowercase, e.g. '15m', '1h')."""
    try:
        import importlib
        mod = importlib.import_module(f"strategies.{strategy_id}.strategy")
        cls = getattr(mod, "Strategy", None)
        tf = None
        if cls is not None:
            tf = getattr(cls, "timeframe", None)
            if tf is None:
                sig = getattr(cls, "STRATEGY_SIGNATURE", None)
                if isinstance(sig, dict):
                    tf = sig.get("timeframe")
        if tf is None:
            tf = getattr(mod, "TIMEFRAME", None)
        if not isinstance(tf, str):
            return None
        # Normalize to lowercase form used by freshness_index ("15m", "1h", "1d")
        tf_low = tf.lower()
        _map = {"m1": "1m", "m5": "5m", "m15": "15m", "m30": "30m",
                "h1": "1h", "h4": "4h", "d1": "1d", "w1": "1w"}
        return _map.get(tf_low, tf_low)
    except (ImportError, AttributeError):
        return None


def _worst_symbol(result: FreshnessResult) -> SymbolAge | None:
    candidates = [s for s in result.per_symbol if s.age_days is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.age_days or 0)


# ────────────────────────────────────────────────────────────────────────────
# CLI (debug only, not part of deploy flow)
# ────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Baseline Freshness Gate (debug CLI)")
    ap.add_argument("strategy_id")
    ap.add_argument("--threshold", type=int, default=14)
    args = ap.parse_args()

    r = check_freshness(args.strategy_id, args.threshold)
    if r.status == "OK":
        print(f"[OK] {r.strategy_id}  worst_age={r.worst_age_days}d  threshold={r.threshold_days}d")
        for s in r.per_symbol:
            print(f"  {s.symbol:<8} age={s.age_days}d  last={s.last_entry_date}  data={s.latest_data_date}")
        sys.exit(0)
    print(format_blocked_message(r))
    sys.exit(1)


if __name__ == "__main__":
    main()
