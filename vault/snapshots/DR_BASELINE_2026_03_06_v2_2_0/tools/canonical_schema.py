"""
canonical_schema.py — Frozen Directive Schema Definition

Authority: Stage -0.25 Canonicalization Gate
Schema Policy: FREEZE (Option B) — Single strict directive format.

This file is the SINGLE SOURCE OF TRUTH for directive structure.
All structural validation MUST reference these definitions.
No dynamic schema extension is permitted.

This tool MUST NOT be modified by the agent without human approval.
"""

# === CANONICAL BLOCKS (ordered — defines serialization order) ===
CANONICAL_BLOCKS = [
    "test",                      # Identity envelope
    "symbols",                   # Symbol list
    "indicators",                # Indicator imports
    "execution_rules",           # Entry/exit/stop logic
    "order_placement",           # Order type and timing
    "trade_management",          # Direction, reentry, position rules
    # --- Strategy-family optional blocks ---
    "range_definition",          # ORB: frozen range parameters
    "exit_rules",                # ORB: time-based exit rules
    "state_machine",             # AK/Persistence: streak-based state machine
    "usd_stress_filter",         # AK/Persistence: USD stress index filter
    "volatility_filter",         # Volatility-gated strategies
    "position_management",       # Stop-and-reverse, max positions
    "mean_reversion_rules",      # MR: mean reversion parameters
    "regime_transition_rules",   # RT: regime transition parameters
    "polarity_override",         # RT: polarity override rules
]

REQUIRED_BLOCKS = {"test", "symbols", "indicators", "execution_rules"}
OPTIONAL_BLOCKS = {
    "order_placement", "trade_management",
    "range_definition", "exit_rules",
    "state_machine", "usd_stress_filter", "volatility_filter",
    "position_management", "mean_reversion_rules",
    "regime_transition_rules", "polarity_override",
}

# === STRUCTURAL BLOCKS (may NOT appear inside test: envelope) ===
STRUCTURAL_BLOCKS = {
    "symbols", "indicators", "execution_rules",
    "order_placement", "trade_management",
    "range_definition", "exit_rules",
}

# === BLOCK TYPE ENFORCEMENT ===
BLOCK_TYPES = {
    "test":             dict,
    "symbols":          list,
    "indicators":       list,
    "execution_rules":  dict,
    "trade_management": dict,
    "order_placement":  dict,
}

# === REQUIRED SUB-BLOCKS (structural presence only, no semantic check) ===
# NOTE: entry_logic is NOT required here because some strategy families
# (e.g., UltimateC) use different execution patterns without entry_logic.
# The gate enforces allowed-key whitelists, not mandatory internal shape.
REQUIRED_SUB_BLOCKS = {}

# === LEGACY KEY MIGRATIONS (finite, not extensible) ===
MIGRATION_TABLE = {
    "execution_rules": "execution",   # AK30 used "execution:"
}

# === MISPLACEMENT TABLE (explicit relocations only) ===
MISPLACEMENT_TABLE = {
    "direction":      ("root", "trade_management"),
    "entry_logic":    ("root", "execution_rules"),
    "exit_logic":     ("root", "execution_rules"),
    "entry_timing":   ("execution_rules", "order_placement"),
    "order_type":     ("execution_rules", "order_placement"),
}

# === ALLOWED NESTED KEYS — Level 1 (per block) ===
ALLOWED_NESTED_KEYS = {
    "test": {
        "name", "family", "strategy", "version", "broker",
        "timeframe", "session_time_reference", "start_date",
        "end_date", "research_mode", "tuning_allowed",
        "parameter_mutation", "description", "notes",
    },
    "execution_rules": {
        "entry_logic", "exit_logic", "stop_loss",
        "trailing_stop", "take_profit", "pyramiding",
        "entry_when_flat_only", "reset_on_exit",
        "cancel_opposite_on_fill",
    },
    "trade_management": {
        "direction", "direction_restriction",
        "reentry", "max_trades_per_session",
        "trade_counting_mode", "max_positions",
        "mode", "no_reentry_after_second_trade",
    },
    "order_placement": {
        "type", "execution_timing", "trigger", "time",
        "execution_timeframe", "price_validation",
        "orders", "entry_timing", "order_type",
    },
}

# === ALLOWED SUB-KEYS — Level 2 (per sub-block) ===
ALLOWED_SUB_KEYS = {
    "entry_logic": {
        "type", "lookback_bars", "atr_length",
        "atr_multiplier", "condition",
        "long_condition", "short_condition",
    },
    "exit_logic": {
        "type", "price_exit", "time_exit_bars", "time_exit",
        "exit_long_if", "exit_short_if",
    },
    "stop_loss": {
        "type", "atr_multiplier", "fixed_points", "multiple",
    },
    "trailing_stop": {
        "enabled", "type", "atr_multiplier",
        "activation_threshold",
    },
    "take_profit": {
        "enabled", "type", "atr_multiplier", "fixed_points",
    },
    "reentry": {
        "allowed", "reuse_original_range",
        "place_both_orders_on_reentry",
        "allowed_until_trade_count",
    },
    "price_validation": {
        "ignore_pre_breakouts",
    },
}

# === CANONICAL KEY ORDER (for deterministic serialization) ===
CANONICAL_KEY_ORDER = {
    "test": [
        "name", "family", "strategy", "version", "broker",
        "timeframe", "session_time_reference", "start_date", "end_date",
        "research_mode", "tuning_allowed", "parameter_mutation",
        "description", "notes",
    ],
    "execution_rules": [
        "pyramiding", "entry_when_flat_only", "reset_on_exit",
        "cancel_opposite_on_fill", "entry_logic", "exit_logic",
        "stop_loss", "trailing_stop", "take_profit",
    ],
    "trade_management": [
        "direction", "direction_restriction", "mode",
        "max_positions", "max_trades_per_session",
        "trade_counting_mode", "reentry",
        "no_reentry_after_second_trade",
    ],
    "order_placement": [
        "type", "execution_timing", "trigger",
        "execution_timeframe", "price_validation", "orders",
    ],
}
