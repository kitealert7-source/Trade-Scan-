"""
tools/filter_registry.py — Shared registry of recognized FilterStack block names.

Single source of truth for both:
  - tools/semantic_validator.py (engine-owned-field consumer check)
  - tools/directive_diff_classifier.py (filter-block behavioral diff detection)

Kept outside engines/ to preserve invariant #6 (engine core immutability).
Mirrors the set of top-level signature keys that engines/filter_stack.py
recognizes and dispatches on (market_regime_filter, regime_age_filter,
session_filter, trend_filter, volatility_filter).

When a new filter block is added to engines/filter_stack.py, append it here
and both gates will pick it up without further edits.
"""

from __future__ import annotations

FILTER_STACK_BLOCKS: frozenset[str] = frozenset({
    "market_regime_filter",
    "regime_age_filter",
    "session_filter",
    "trend_filter",
    "volatility_filter",
})


def is_filter_block_key(key: str) -> bool:
    """Return True if `key` is a recognized FilterStack top-level block."""
    return key in FILTER_STACK_BLOCKS


def is_behavioral_filter_config(block: object) -> bool:
    """
    Decide whether a filter-block config is behaviorally effective.

    Crisp rule (no 'default value' ambiguity):
      Behavioral iff the block is a dict with enabled == True AND has at
      least one key other than "enabled".

    Empty dict, missing 'enabled', enabled=False, or {"enabled": True}
    alone are all NOT behavioral (cosmetic / no-op).
    """
    if not isinstance(block, dict):
        return False
    if block.get("enabled") is not True:
        return False
    for k in block:
        if k != "enabled":
            return True
    return False
