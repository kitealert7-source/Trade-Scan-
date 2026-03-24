"""
directive_schema.py — Single Source of Truth for Directive YAML Contract
Authority: SOP_TESTING (Stage-0 Governance)

NO DUPLICATE DEFINITIONS. Import this everywhere.
All signature construction MUST go through normalize_signature().
"""

# --- SCHEMA VERSION ---
# Bump on ANY structural change to signature contract.
# v1: Original hardcoded keys (legacy)
# v2: Schema-agnostic exclusion-based construction
SIGNATURE_SCHEMA_VERSION = 2

# Keys excluded from signature construction.
# Everything NOT in this set becomes part of the strategy signature.
NON_SIGNATURE_KEYS = frozenset({
    "test", "backtest", "description", "notes", "symbols",
    "name", "family", "strategy", "broker", "timeframe",
    "session_time_reference", "start_date", "end_date",
    "research_mode", "tuning_allowed", "parameter_mutation",
})

# Minimal required signature keys (hard abort if missing)
REQUIRED_SIGNATURE_KEYS = frozenset({"indicators", "execution_rules"})

# Default-injected blocks (injected into signature if absent from directive)
SIGNATURE_DEFAULTS = {
    "order_placement": {"type": "market", "execution_timing": "next_bar_open"},
}


def normalize_signature(d_conf: dict) -> dict:
    """
    Build a deterministic strategy signature from parsed directive config.

    This is the ONLY function that constructs signatures.
    Both provisioner and validator MUST call this — no local logic.

    Steps:
        1. Exclude envelope/identity keys (NON_SIGNATURE_KEYS).
        2. Inject schema version.
        3. Default-inject missing optional blocks (SIGNATURE_DEFAULTS).
        4. Validate required keys present.

    Returns:
        dict: Normalized signature ready for embedding or comparison.

    Raises:
        ValueError: If required signature keys are missing.
    """
    signature = {}
    for key in sorted(d_conf.keys()):
        if key.lower() not in NON_SIGNATURE_KEYS:
            signature[key] = d_conf[key]

    signature["signature_version"] = SIGNATURE_SCHEMA_VERSION

    # Default-inject missing optional blocks
    for key, default_val in SIGNATURE_DEFAULTS.items():
        if key not in signature:
            signature[key] = default_val

    # Validate required keys
    missing = REQUIRED_SIGNATURE_KEYS - set(signature.keys())
    if missing:
        raise ValueError(
            f"Directive missing required signature keys: {missing}"
        )

    return signature
