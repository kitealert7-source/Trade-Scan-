"""Session-Reset Execution Invariant — one predicate.

Blocks the single directive configuration that silently drops every entry:

    order_placement.execution_timing == "next_bar_open"   (explicit or default)
    AND trade_management.session_reset resolves to "utc_day"  (explicit or default)
    AND the bar duration is >= 1 UTC day

Mechanism: a next_bar_open signal on bar T defers its fill to bar T+1 via
`state.pending_entry`; the engine clears `state.pending_entry` on every new UTC
day when session_reset == "utc_day" (engine_dev/.../v1_5_11/evaluate_bar.py
resolve_engine_config + the utc_day session reset). When each bar spans >= 1 day,
bar T+1 is ALWAYS a new UTC day, so the pending entry is wiped before it can
fill -> zero trades that read as "no edge" rather than an error.

This is a config invariant (like the identity guard), not an engine change: it
converts a silent multi-hour investigation into an immediate, self-explaining
refusal at admission. Encodes WHY it fails, so it correctly PASSES daily
close-entry / same-bar fills, weekly-with-explicit-session_reset, and every
sub-daily timeframe. Verified 2026-07-01 (1D total wipe / 4H ~+9% / 1H ~+1.5%).
See memory feedback_session_reset_daily_footgun.
"""
from __future__ import annotations

from typing import Optional

# Bar duration by timeframe token (seconds). Sub-daily => next bar is usually the
# same UTC day, so the utc_day reset does not wipe every fill (partial loss only).
_BAR_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}
_ONE_UTC_DAY_SECONDS = 86400


def check_session_reset_safety(parsed_directive: dict) -> Optional[str]:
    """Return a one-line diagnostic if the directive violates the session-reset
    execution invariant, else None. Pure — no I/O, no mutation.

    Matches the engine's own resolution: execution_timing defaults to
    'next_bar_open' (only 'current_bar_open' fills same-bar) and session_reset
    defaults to 'utc_day' (evaluate_bar.resolve_engine_config)."""
    test = parsed_directive.get("test", {}) or {}
    tf = str(test.get("timeframe", "")).strip().lower()

    bar_seconds = _BAR_SECONDS.get(tf)
    # Unknown or sub-daily timeframe: the invariant does not fire (conservative —
    # never false-block; unknown tokens are not assumed coarse).
    if bar_seconds is None or bar_seconds < _ONE_UTC_DAY_SECONDS:
        return None

    order_placement = parsed_directive.get("order_placement", {}) or {}
    timing = str(order_placement.get("execution_timing", "next_bar_open")).strip().lower()
    # Only the deferred (next-bar) fill carries a pending_entry across a bar
    # boundary. current_bar_open / same-bar fills are safe.
    if timing != "next_bar_open":
        return None

    trade_management = parsed_directive.get("trade_management", {}) or {}
    session_reset = str(trade_management.get("session_reset", "utc_day")).strip().lower()
    if session_reset != "utc_day":
        return None

    return (
        f"SESSION_RESET_PENDING_WIPE: timeframe='{tf}' (bar >= 1 UTC day) + "
        f"order_placement.execution_timing='next_bar_open' + "
        f"trade_management.session_reset='utc_day' (default if unset). Every next bar is a "
        f"new UTC day, so the utc_day session reset clears the pending entry before it "
        f"fills -> all entries silently dropped (0 trades). "
        f"Fix: set trade_management.session_reset: none (or use current_bar_open / close-bar entry)."
    )
