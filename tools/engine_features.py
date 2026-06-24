"""
engine_features.py — minimal directive `engine_features:` block resolver.

Authority: Engine Patch A (v1.5.10 -> v1.5.11), design §6
  outputs/system_reports/02_engine_core/ENGINE_PATCH_A_DESIGN_v1_5_11_2026-06-23.md

Scope (LOCKED — minimum mechanism, no framework):
  The directive may carry an optional top-level block

      engine_features:
          invalid_fill_policy: SKIP     # default FAIL

  with EXACTLY ONE recognized key, `invalid_fill_policy`, taking one of two
  values: ``FAIL`` (default; today's fail-fast behaviour) or ``SKIP`` (the
  opt-in skip path authored in Patch B). In Patch A the flag is resolved,
  validated, stamped into run_metadata.json, and folded into the classifier
  (a change to it is SIGNAL-level, so it forces a signal_version bump) — it
  does NOT alter a trade. The SKIP compute path lands in Patch B.

  No FLAG_SCHEMA registry, no behavior_affecting table, no feature_set_hash.
  The second flag, if one ever comes, earns the generalization (design §6).

This module is pure: it operates on a parsed directive dict and performs no
I/O. Validation is a hard ValueError so the admission gate can fail-fast.
"""

from __future__ import annotations

from typing import Any

# The single recognized engine_features sub-key and its value domain.
ENGINE_FEATURES_KEY = "engine_features"
INVALID_FILL_POLICY_KEY = "invalid_fill_policy"
DEFAULT_INVALID_FILL_POLICY = "FAIL"
VALID_INVALID_FILL_POLICIES = frozenset({"FAIL", "SKIP"})

# The flattened (dot-separated) leaf path the directive_diff_classifier keys on
# to treat a change to this flag as an execution-state SIGNAL-level change.
INVALID_FILL_POLICY_LEAF = f"{ENGINE_FEATURES_KEY}.{INVALID_FILL_POLICY_KEY}"


def resolve_invalid_fill_policy(directive: dict[str, Any]) -> str:
    """Resolve and validate the directive's invalid_fill_policy.

    Args:
        directive: A parsed directive dict (root-level access; the
            `engine_features` block is a top-level sibling of `order_placement`).

    Returns:
        "FAIL" (default, when the block or key is absent) or "SKIP".

    Raises:
        ValueError: if `engine_features` is present but not a mapping, carries
            any key other than `invalid_fill_policy`, or `invalid_fill_policy`
            holds a value outside {"FAIL", "SKIP"}. Hard-fail by design so the
            admission gate aborts before a run is spent.
    """
    block = directive.get(ENGINE_FEATURES_KEY)
    if block is None:
        return DEFAULT_INVALID_FILL_POLICY

    if not isinstance(block, dict):
        raise ValueError(
            f"'{ENGINE_FEATURES_KEY}' must be a mapping, "
            f"got {type(block).__name__}."
        )

    unknown = set(block) - {INVALID_FILL_POLICY_KEY}
    if unknown:
        raise ValueError(
            f"'{ENGINE_FEATURES_KEY}': unknown key(s) {sorted(unknown)}; "
            f"only '{INVALID_FILL_POLICY_KEY}' is recognized."
        )

    value = block.get(INVALID_FILL_POLICY_KEY, DEFAULT_INVALID_FILL_POLICY)
    if value not in VALID_INVALID_FILL_POLICIES:
        raise ValueError(
            f"'{ENGINE_FEATURES_KEY}.{INVALID_FILL_POLICY_KEY}' must be one of "
            f"{sorted(VALID_INVALID_FILL_POLICIES)}, got {value!r}."
        )
    return value
