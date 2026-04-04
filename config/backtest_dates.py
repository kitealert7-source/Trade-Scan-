"""
backtest_dates.py — Resolve backtest start/end dates from policy + data freshness.

Usage:
    from config.backtest_dates import resolve_dates

    start, end = resolve_dates("15m")
    # start = "2025-01-02", end = "2026-03-31"

    start, end = resolve_dates("15m", stage="extended")
    # start = "2024-01-02", end = "2026-03-31"

    # For multi-symbol: resolves end_date to the earliest latest_date
    # across all requested symbols (conservative — no future-peeking).
    start, end = resolve_dates("15m", symbols=["XAUUSD", "AUDUSD"])
"""

import json
from datetime import date, timedelta
from pathlib import Path

import yaml

__all__ = ["resolve_dates", "report"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH  = PROJECT_ROOT / "config" / "backtest_date_policy.yaml"
FRESHNESS_PATH = PROJECT_ROOT / "data_root" / "freshness_index.json"

# Cache
_policy: dict | None = None
_freshness: dict | None = None


def _load_policy() -> dict:
    global _policy
    if _policy is not None:
        return _policy
    with open(POLICY_PATH, encoding="utf-8") as f:
        _policy = yaml.safe_load(f)
    return _policy


def _load_freshness() -> dict:
    """Load freshness_index.json entries. Returns {} on missing/corrupt."""
    global _freshness
    if _freshness is not None:
        return _freshness
    try:
        with open(FRESHNESS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _freshness = data.get("entries", {}) if isinstance(data, dict) else {}
    except Exception:
        _freshness = {}
    return _freshness


def _freshness_key(symbol: str, timeframe: str) -> str:
    """Build the freshness index key: SYMBOL_BROKER_tf (e.g. XAUUSD_OCTAFX_1h)."""
    return f"{symbol.upper()}_OCTAFX_{timeframe.lower()}"


def _resolve_end_date(timeframe: str, symbols: list[str] | None = None) -> str:
    """Resolve end_date from freshness index.

    If symbols provided: returns the earliest latest_date across all symbols
    (conservative — ensures all symbols have data up to this date).
    If no symbols or no freshness data: returns today's date.
    """
    entries = _load_freshness()
    if not entries:
        return date.today().isoformat()

    if symbols:
        dates = []
        for sym in symbols:
            key = _freshness_key(sym, timeframe)
            if key in entries:
                dates.append(entries[key]["latest_date"])
        if dates:
            return min(dates)  # conservative: earliest latest_date

    # Fallback: find any entry matching this timeframe
    tf_dates = [
        v["latest_date"] for k, v in entries.items()
        if k.endswith(f"_{timeframe.lower()}")
    ]
    if tf_dates:
        return min(tf_dates)

    return date.today().isoformat()


def resolve_dates(
    timeframe: str,
    *,
    stage: str = "initial",
    symbols: list[str] | None = None,
) -> tuple[str, str]:
    """Resolve (start_date, end_date) for a backtest directive.

    Args:
        timeframe: e.g. "15m", "1h", "1d"
        stage: "initial" (screening) or "extended" (full validation)
        symbols: optional list of symbols to resolve end_date conservatively

    Returns:
        (start_date, end_date) as ISO strings ("2025-01-02", "2026-03-31")
    """
    policy = _load_policy()
    tf = timeframe.lower()

    # Start date
    if stage == "extended":
        start = policy.get("extended", {}).get("start_date", "2024-01-02")
    else:
        initial = policy.get("initial", {})
        if tf in initial:
            start = initial[tf]["start_date"]
        else:
            # Unknown timeframe — use most conservative (full period)
            start = "2024-01-02"
            print(f"[WARN] No date policy for timeframe '{tf}' — using {start}")

    # End date — always from freshness index
    end = _resolve_end_date(tf, symbols)

    return str(start), str(end)


def report() -> None:
    """Print current date policy and freshness status."""
    policy = _load_policy()
    entries = _load_freshness()

    print("Backtest Date Policy")
    print("=" * 55)
    print(f"{'Timeframe':<10} {'Start':<12} {'End (latest)':<12} {'Period'}")
    print("-" * 55)

    for tf in ["1d", "4h", "1h", "30m", "15m", "5m"]:
        start, end = resolve_dates(tf)
        try:
            d_start = date.fromisoformat(start)
            d_end = date.fromisoformat(end)
            days = (d_end - d_start).days
            months = days / 30.44
            period = f"~{months:.1f} months ({days}d)"
        except Exception:
            period = "?"
        print(f"{tf:<10} {start:<12} {end:<12} {period}")

    print("-" * 55)
    ext_start = policy.get("extended", {}).get("start_date", "2024-01-02")
    print(f"{'Extended':<10} {ext_start:<12} {'(same)':<12} Full history for PROMOTE candidates")
    print("=" * 55)

    if not entries:
        print("\n[WARN] freshness_index.json not found — end_date falls back to today")
    else:
        stale = {k: v for k, v in entries.items() if v.get("days_behind", 0) > 3}
        if stale:
            print(f"\n[WARN] {len(stale)} stale symbols (>3 days behind)")
        else:
            print(f"\nData freshness: OK ({len(entries)} symbols, all current)")


if __name__ == "__main__":
    report()
