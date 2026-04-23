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
    "trend_filter",              # Trend regime-gated strategies
    "market_regime_filter",      # Market regime hard exclusion gate
    "regime_age_filter",         # Regime age exclusion gate (hypothesis testing)
    "session_filter",            # Trading session exclusion gate (hour-based)
    "position_management",       # Stop-and-reverse, max positions
    "mean_reversion_rules",      # MR: mean reversion parameters
    "regime_transition_rules",   # RT: regime transition parameters
    "polarity_override",         # RT: polarity override rules
]

REQUIRED_BLOCKS = {"test", "symbols", "indicators", "execution_rules"}
OPTIONAL_BLOCKS = {
    "order_placement", "trade_management",
    "range_definition", "exit_rules",
    "state_machine", "usd_stress_filter", "volatility_filter", "trend_filter",
    "market_regime_filter", "regime_age_filter", "session_filter",
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
        # Structured override for Stage -0.20 Idea Gate. Allowed ONLY when
        # the directive represents a genuine semantic shift (signal
        # definition change, data regime change, structural model change)
        # that renders prior REPEAT_FAILED runs semantically stale.
        # NOT for parameter tweaks, casual retries, or low-PF retries.
        # Minimum 50 chars. Logged to governance/idea_gate_overrides.csv.
        "repeat_override_reason",
        # User-declared signal-primitive version (integer). Increments when
        # the underlying signal definition changes (e.g. CHOCH_V2 -> V3).
        # Phase 2 will wire this into the Idea Gate as part of the repeat key
        # (MODEL + ASSET + SIGNAL_VERSION). In Phase 1 it is accepted and
        # flows into the signature hash only.
        "signal_version",
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
        "session_reset",
        "trade_counting_mode", "max_positions",
        "mode", "no_reentry_after_second_trade",
    },
    "order_placement": {
        "type", "execution_timing", "trigger", "time",
        "execution_timeframe", "price_validation",
        "orders", "entry_timing", "order_type",
    },
    "volatility_filter": {
        "enabled", "atr_length", "atr_percentile_lookback",
        "condition", "threshold", "required_regime", "operator",
        # direction_gate mode: long_when / short_when sub-blocks gate direction
        # based on vol_regime cached at signal time (see engines/filter_stack.py).
        "direction_gate", "long_when", "short_when",
    },
    "trend_filter": {
        "enabled", "required_regime", "operator",
        "condition", "threshold", "exclude_regime",
        "direction_gate", "long_when", "short_when",
    },
    "market_regime_filter": {
        "enabled", "exclude",
    },
    "regime_age_filter": {
        "enabled", "exclude_min", "exclude_max", "allowed_values",
        # v1.5.5: explicit dual-time view selector. Must be "signal" (default,
        # backward-compatible) or "fill". No inference — absence == "signal".
        "mode",
    },
    "session_filter": {
        "enabled", "exclude_hours_utc", "exclude_direction",
    },
}

# === ALLOWED SUB-KEYS — Level 2 (per sub-block) ===
ALLOWED_SUB_KEYS = {
    "entry_logic": {
        "type", "lookback_bars", "atr_length",
        "atr_multiplier", "condition",
        "long_condition", "short_condition",
        # Spike-fade
        "confirmation", "direction", "spike_atr_multiplier",
        # BOS pullback
        "swing_lookback", "min_swing_age_bars", "pullback_tolerance_atr",
        # Gap fade
        "gap_threshold_pct",
        # BB squeeze breakout
        "band_std_dev", "breakout_band",
        "squeeze_atr_percentile_threshold", "squeeze_min_bars",
        # False break / stop hunt
        "range_lookback", "break_atr_threshold", "range_min_atr_multiple",
        # Session sweep reversal (London open liquidity sweep)
        "session_start", "session_end", "entry_window_start", "entry_window_end",
        "narrow_range_atr_multiple", "tp_atr_multiple_narrow",
        # Engulfing at structure
        "structure_lookback", "min_body_ratio",
        # HMA trend-follow entry (idea 55 family)
        "hma_period", "slope_lookback",
    },
    "exit_logic": {
        "type", "price_exit", "time_exit_bars", "time_exit", "time_exit_utc",
        "exit_long_if", "exit_short_if", "max_bars",
        # Z-score mean-extension exit (idea 55 family)
        "zscore_window", "zscore_threshold",
    },
    "stop_loss": {
        "type", "atr_multiplier", "fixed_points", "multiple", "target", "pct",
    },
    "trailing_stop": {
        "enabled", "type", "atr_multiplier",
        "activation_threshold", "activation_r", "lock_to",
    },
    "take_profit": {
        "enabled", "type", "atr_multiplier", "fixed_points", "target",
        "r_multiple",
    },
    "reentry": {
        "allowed", "reuse_original_range",
        "place_both_orders_on_reentry",
        "allowed_until_trade_count",
    },
    "price_validation": {
        "ignore_pre_breakouts",
    },
    # direction_gate sub-blocks for volatility_filter
    "long_when": {"required_regime", "operator"},
    "short_when": {"required_regime", "operator"},
}

# === CANONICAL KEY ORDER (for deterministic serialization) ===
CANONICAL_KEY_ORDER = {
    "test": [
        "name", "family", "strategy", "version", "signal_version", "broker",
        "timeframe", "session_time_reference", "start_date", "end_date",
        "research_mode", "tuning_allowed", "parameter_mutation",
        "description", "notes", "repeat_override_reason",
    ],
    "execution_rules": [
        "pyramiding", "entry_when_flat_only", "reset_on_exit",
        "cancel_opposite_on_fill", "entry_logic", "exit_logic",
        "stop_loss", "trailing_stop", "take_profit",
    ],
    "trade_management": [
        "direction", "direction_restriction", "mode",
        "max_positions", "max_trades_per_session",
        "session_reset",
        "trade_counting_mode", "reentry",
        "no_reentry_after_second_trade",
    ],
    "order_placement": [
        "type", "execution_timing", "trigger",
        "execution_timeframe", "price_validation", "orders",
    ],
}
