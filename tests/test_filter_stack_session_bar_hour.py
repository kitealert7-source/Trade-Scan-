"""Regression test for INFRA-NEWS-001 — session_filter bar_hour fallback.

Before fix: a strategy with session_filter enabled but no df["bar_hour"] column
populated in prepare_indicators() silently produced zero trades, because
session_filter rejects every bar where ctx.require("bar_hour") returns None.

After fix: session_filter derives bar_hour from ctx.row.name.hour when the
column is absent, only rejecting when neither path resolves a value.

Three cases:
  1. bar_hour column absent + DatetimeIndex available → rejects only on
     excluded hours (would have rejected ALL bars before fix)
  2. bar_hour column present → unchanged behavior
  3. bar_hour column absent + no usable row.name → still rejects
     (true indeterminate state, correct behavior)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from engines.filter_stack import FilterStack
from engines.protocols import ContextViewProtocol


class _MinimalContextView:
    """Minimal ContextViewProtocol-compatible adapter for test isolation."""
    _ENGINE_PROTOCOL = True

    def __init__(self, ns):
        self._ns = ns

    def get(self, key, default=None):
        try:
            val = getattr(self, key)
            if val is None:
                return default
            if pd.isna(val):
                return default
            return val
        except AttributeError:
            return default

    def require(self, key):
        val = self.get(key)
        if val is None:
            raise RuntimeError(f"AUTHORITATIVE_INDICATOR_MISSING: '{key}'")
        return val

    def __getattr__(self, name):
        if hasattr(self._ns, name):
            return getattr(self._ns, name)
        if hasattr(self._ns, 'row'):
            row = getattr(self._ns, 'row')
            if hasattr(row, 'get'):
                val = row.get(name)
                if val is not None and not pd.isna(val):
                    return val
        raise AttributeError(name)


# Tell isinstance() the minimal class satisfies the Protocol — required by
# FilterStack.allow_trade type-check at runtime.
ContextViewProtocol.register(_MinimalContextView)


_SIGNATURE = {
    "session_filter": {
        "enabled": True,
        "exclude_hours_utc": [0, 1, 2, 3, 4, 5, 6, 7],
    },
}


def _ctx(timestamp_str: str | None, *, with_bar_hour: bool = False) -> _MinimalContextView:
    if timestamp_str is None:
        # Construct a row whose name has no .hour attribute (e.g., int index)
        row = pd.Series({"close": 1.0}, name=0)
    else:
        row = pd.Series({"close": 1.0}, name=pd.Timestamp(timestamp_str, tz="UTC"))
    if with_bar_hour:
        row["bar_hour"] = row.name.hour if hasattr(row.name, "hour") else None
    ns = SimpleNamespace(row=row)
    return _MinimalContextView(ns)


def test_bar_hour_fallback_from_index_excluded_hour():
    """Asia hour (3 UTC) with no bar_hour column → derive from index → REJECT."""
    fs = FilterStack(_SIGNATURE)
    ctx = _ctx("2025-06-01 03:00:00+00:00", with_bar_hour=False)
    assert fs.allow_trade(ctx) is False
    assert fs.filter_counts.get("session_filter", 0) == 1


def test_bar_hour_fallback_from_index_allowed_hour():
    """Non-Asia hour (12 UTC) with no bar_hour column → derive from index → ALLOW.

    Before INFRA-NEWS-001 fix: this would REJECT (because bar_hour=None).
    After fix: hour derived from row.name → 12 not in exclude → allow.
    """
    fs = FilterStack(_SIGNATURE)
    ctx = _ctx("2025-06-01 12:30:00+00:00", with_bar_hour=False)
    assert fs.allow_trade(ctx) is True
    assert fs.filter_counts.get("session_filter", 0) == 0


def test_bar_hour_column_unchanged_behavior():
    """When bar_hour column IS present, original behavior preserved.
    Allowed hour 12, no rejection."""
    fs = FilterStack(_SIGNATURE)
    ctx = _ctx("2025-06-01 12:30:00+00:00", with_bar_hour=True)
    assert fs.allow_trade(ctx) is True


def test_bar_hour_column_present_excluded():
    """bar_hour column present, excluded hour → reject (unchanged)."""
    fs = FilterStack(_SIGNATURE)
    ctx = _ctx("2025-06-01 03:00:00+00:00", with_bar_hour=True)
    assert fs.allow_trade(ctx) is False
    assert fs.filter_counts.get("session_filter", 0) == 1


def test_bar_hour_truly_indeterminate_still_rejects():
    """No bar_hour column AND row.name has no .hour → reject as
    indeterminate. This is the correct safe behavior; the fix only adds a
    fallback, doesn't loosen the gate."""
    fs = FilterStack(_SIGNATURE)
    ctx = _ctx(None, with_bar_hour=False)  # int index, no .hour attr
    assert fs.allow_trade(ctx) is False
    assert fs.filter_counts.get("session_filter", 0) == 1


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
