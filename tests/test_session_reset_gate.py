"""Regression tests for the session-reset execution invariant gate.

Locks the single predicate: next_bar_open + session_reset=='utc_day' (explicit
or default) + bar_duration >= 1 UTC day => BLOCK; everything else PASS.
See tools/session_reset_gate and memory feedback_session_reset_daily_footgun.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.session_reset_gate import check_session_reset_safety


def _directive(tf, timing="next_bar_open", session_reset="__unset__"):
    d = {
        "test": {"timeframe": tf},
        "order_placement": {"execution_timing": timing} if timing is not None else {},
        "trade_management": {"direction_restriction": "none"},
    }
    if session_reset != "__unset__":
        d["trade_management"]["session_reset"] = session_reset
    return d


# --- The dangerous combo BLOCKS (the bug this gate exists to prevent) ---

def test_daily_next_bar_open_default_reset_blocks():
    msg = check_session_reset_safety(_directive("1d"))  # session_reset unset -> default utc_day
    assert msg is not None and "SESSION_RESET_PENDING_WIPE" in msg


def test_daily_next_bar_open_explicit_utc_day_blocks():
    assert check_session_reset_safety(_directive("1d", session_reset="utc_day")) is not None


def test_daily_missing_execution_timing_blocks():
    # execution_timing omitted -> engine defaults to next_bar_open (deferred) -> dangerous
    d = _directive("1d")
    d["order_placement"] = {}
    assert check_session_reset_safety(d) is not None


def test_weekly_next_bar_open_default_blocks():
    # general invariant: not daily-specific
    assert check_session_reset_safety(_directive("1w")) is not None


# --- The fix and the valid configurations PASS ---

def test_daily_session_reset_none_passes():
    assert check_session_reset_safety(_directive("1d", session_reset="none")) is None


def test_daily_current_bar_open_passes():
    # same-bar fill: no pending_entry carried across a bar boundary
    assert check_session_reset_safety(_directive("1d", timing="current_bar_open")) is None


# --- Sub-daily PASSES (phase-1 scope; partial loss only, not total) ---

def test_4h_next_bar_open_utc_day_passes():
    assert check_session_reset_safety(_directive("4h", session_reset="utc_day")) is None


def test_15m_next_bar_open_default_passes():
    assert check_session_reset_safety(_directive("15m")) is None


# --- Robustness: unknown TF and missing blocks never false-block ---

def test_unknown_timeframe_passes():
    assert check_session_reset_safety(_directive("3d")) is None


def test_no_trade_management_block_daily_blocks():
    # trade_management absent entirely -> session_reset defaults utc_day -> dangerous on daily
    d = {"test": {"timeframe": "1d"}, "order_placement": {"execution_timing": "next_bar_open"}}
    assert check_session_reset_safety(d) is not None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
            passed += 1
        except Exception:
            print(f"[FAIL] {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
