"""
canonicalizer.py -- Directive Structure Canonicalization Engine

Authority: Stage -0.25 Canonicalization Gate
Schema Policy: FREEZE (Option B) -- Single strict directive format.

Usage:
  python tools/canonicalizer.py <DIRECTIVE_PATH>           # Dry-run (report only)
  python tools/canonicalizer.py <DIRECTIVE_PATH> --execute  # Overwrite original

Purpose:
  Validates and transforms directive YAML into canonical form.
  Detects structural deviations. Requires human approval before overwrite.

This tool MUST NOT be invoked by the agent autonomously during pipeline
execution. The pipeline hook calls canonicalize() programmatically.
"""

import sys
import yaml
import argparse
from copy import deepcopy
from pathlib import Path
from difflib import unified_diff

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.canonical_schema import (
    CANONICAL_BLOCKS,
    REQUIRED_BLOCKS,
    STRUCTURAL_BLOCKS,
    BLOCK_TYPES,
    REQUIRED_SUB_BLOCKS,
    MIGRATION_TABLE,
    MISPLACEMENT_TABLE,
    ALLOWED_NESTED_KEYS,
    ALLOWED_SUB_KEYS,
    CANONICAL_KEY_ORDER,
)


class CanonicalizationError(Exception):
    """Hard failure during canonicalization."""
    pass


def _order_dict(d: dict, key_order: list) -> dict:
    """Reorder dict keys according to key_order. Unknown keys appended at end."""
    ordered = {}
    for key in key_order:
        if key in d:
            ordered[key] = d[key]
    # Append any keys not in the ordering (should not exist if schema is tight)
    for key in d:
        if key not in ordered:
            ordered[key] = d[key]
    return ordered


def serialize_canonical(data: dict) -> str:
    """Deterministic serialization using CANONICAL_BLOCKS order."""
    ordered = {}
    for block_name in CANONICAL_BLOCKS:
        if block_name in data:
            block = data[block_name]
            if isinstance(block, dict) and block_name in CANONICAL_KEY_ORDER:
                block = _order_dict(block, CANONICAL_KEY_ORDER[block_name])
            ordered[block_name] = block
    # Append any blocks not in CANONICAL_BLOCKS (should not exist)
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]
    return yaml.dump(ordered, default_flow_style=False, sort_keys=False,
                     allow_unicode=True)


def canonicalize(parsed: dict) -> tuple:
    """
    Tree Rebuild canonicalization.

    Args:
        parsed: Raw parsed YAML dict from directive file.

    Returns:
        (canonical, violations) where:
            canonical: The canonical dict (or None on hard fail)
            violations: List of (level, message) tuples.
                level: "MIGRATED", "RELOCATED", "INFO", "ERROR"

    Raises:
        CanonicalizationError on any hard failure.
    """
    # Phase 1: Snapshot before mutation
    original_snapshot = deepcopy(parsed)
    original = deepcopy(parsed)
    canonical = {}
    violations = []

    # Phase 2: Unwrap envelope (identity-only guard)
    if "test" in original and isinstance(original["test"], dict):
        envelope = original["test"]
        structural_leak = set(envelope.keys()) & STRUCTURAL_BLOCKS
        if structural_leak:
            raise CanonicalizationError(
                f"ENVELOPE_CONTAMINATION: test: block contains structural keys: "
                f"{sorted(structural_leak)}. Move them to top-level."
            )
        canonical["test"] = envelope
        del original["test"]
    elif "test" in original:
        # test exists but is not a dict
        raise CanonicalizationError(
            f"INVALID_BLOCK_TYPE: 'test' must be dict, "
            f"got {type(original['test']).__name__}"
        )

    # Phase 3: Build canonical tree
    for block_name in CANONICAL_BLOCKS:
        if block_name == "test":
            continue  # Already handled in Phase 2
        if block_name in original:
            canonical[block_name] = original.pop(block_name)
        elif block_name in MIGRATION_TABLE:
            legacy_name = MIGRATION_TABLE[block_name]
            if legacy_name in original:
                canonical[block_name] = original.pop(legacy_name)
                violations.append(("MIGRATED",
                    f"'{legacy_name}' -> '{block_name}'"))
        elif block_name in REQUIRED_BLOCKS:
            raise CanonicalizationError(
                f"STRUCTURALLY_INCOMPLETE: Missing required block: '{block_name}'"
            )

    # Phase 3.5: Block type validation
    for block_name, block_data in canonical.items():
        expected_type = BLOCK_TYPES.get(block_name)
        if expected_type and not isinstance(block_data, expected_type):
            raise CanonicalizationError(
                f"INVALID_BLOCK_TYPE: '{block_name}' must be "
                f"{expected_type.__name__}, got {type(block_data).__name__}"
            )

    # Phase 4: Relocate known misplacements (with conflict detection)
    for key, (illegal_parent, correct_parent) in MISPLACEMENT_TABLE.items():
        source_found = False
        source_value = None

        if illegal_parent == "root":
            # Key is at top-level (still in original leftovers)
            if key in original:
                source_found = True
                source_value = original.pop(key)
        else:
            # Key is inside an already-built canonical block
            if (illegal_parent in canonical
                    and isinstance(canonical[illegal_parent], dict)
                    and key in canonical[illegal_parent]):
                source_found = True
                source_value = canonical[illegal_parent].pop(key)

        if source_found:
            # Conflict check: destination must not already contain this key
            if (correct_parent in canonical
                    and isinstance(canonical[correct_parent], dict)
                    and key in canonical[correct_parent]):
                raise CanonicalizationError(
                    f"CONFLICTING_DEFINITION: '{key}' exists both in "
                    f"'{illegal_parent}' and inside '{correct_parent}'. "
                    f"Cannot relocate. Human must resolve."
                )
            # Safe to relocate
            if correct_parent not in canonical:
                canonical[correct_parent] = {}
            canonical[correct_parent][key] = source_value
            violations.append(("RELOCATED",
                f"'{key}' from {illegal_parent} -> {correct_parent}"))

    # Phase 5: Leftover check
    if original:
        remaining = sorted(original.keys())
        raise CanonicalizationError(
            f"UNKNOWN_STRUCTURE: Unknown top-level keys detected: {remaining}"
        )

    # Phase 6: Nested key validation (depth-2)
    # Level 1 -- block children
    for block_name, block_data in canonical.items():
        if block_name in ALLOWED_NESTED_KEYS and isinstance(block_data, dict):
            unknown = set(block_data.keys()) - ALLOWED_NESTED_KEYS[block_name]
            if unknown:
                raise CanonicalizationError(
                    f"UNKNOWN_NESTED_KEY: Unknown keys in '{block_name}': "
                    f"{sorted(unknown)}"
                )

    # Level 2 -- sub-block children
    for block_name, block_data in canonical.items():
        if not isinstance(block_data, dict):
            continue
        for sub_key, sub_data in block_data.items():
            if isinstance(sub_data, dict) and sub_key in ALLOWED_SUB_KEYS:
                unknown = set(sub_data.keys()) - ALLOWED_SUB_KEYS[sub_key]
                if unknown:
                    raise CanonicalizationError(
                        f"UNKNOWN_SUB_KEY: Unknown keys in "
                        f"'{block_name}.{sub_key}': {sorted(unknown)}"
                    )

    # Phase 6.5: Required sub-block enforcement
    for block_name, required_children in REQUIRED_SUB_BLOCKS.items():
        if block_name in canonical and isinstance(canonical[block_name], dict):
            missing = required_children - set(canonical[block_name].keys())
            if missing:
                raise CanonicalizationError(
                    f"STRUCTURALLY_INCOMPLETE: '{block_name}' is missing "
                    f"required sub-block(s): {sorted(missing)}"
                )

    # Phase 7: Serialize + diff
    canonical_yaml = serialize_canonical(canonical)
    original_yaml = serialize_canonical(original_snapshot)

    diff_lines = list(unified_diff(
        original_yaml.splitlines(keepends=True),
        canonical_yaml.splitlines(keepends=True),
        fromfile="original",
        tofile="canonical",
    ))
    has_drift = len(diff_lines) > 0

    return canonical, canonical_yaml, diff_lines, violations, has_drift


def main():
    parser = argparse.ArgumentParser(
        description="Stage -0.25: Directive Canonicalization Gate"
    )
    parser.add_argument("directive_path", help="Path to directive YAML file")
    parser.add_argument(
        "--execute", action="store_true",
        help="Overwrite original with canonical (requires prior review)"
    )
    args = parser.parse_args()

    d_path = Path(args.directive_path)
    if not d_path.exists():
        print(f"[FATAL] File not found: {d_path}")
        sys.exit(1)

    print("=" * 60)
    print("STAGE -0.25: DIRECTIVE CANONICALIZATION GATE")
    print("=" * 60)
    print(f"  Directive: {d_path.name}")
    print()

    # Parse
    try:
        raw_text = d_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        print(f"[FATAL] YAML_PARSE_ERROR: {e}")
        sys.exit(1)

    if not isinstance(parsed, dict):
        print(f"[FATAL] Parsed YAML is not a dict: {type(parsed).__name__}")
        sys.exit(1)

    # Canonicalize
    try:
        canonical, canonical_yaml, diff_lines, violations, has_drift = \
            canonicalize(parsed)
    except CanonicalizationError as e:
        print(f"[FATAL] {e}")
        sys.exit(1)

    # Report violations
    if violations:
        print("  Structural changes detected:")
        for level, msg in violations:
            print(f"    [{level}] {msg}")
        print()

    if not has_drift:
        print("[PASS] Directive is already in canonical form.")
        return True

    # Show diff
    print("  --- Unified Diff ---")
    for line in diff_lines:
        print(f"  {line}", end="")
    print()

    # Write canonical to tmp
    tmp_path = Path("/tmp") / f"{d_path.stem}_canonical.yaml"
    tmp_path.write_text(canonical_yaml, encoding="utf-8")
    print(f"  Corrected YAML written to: {tmp_path}")
    print()

    if args.execute:
        d_path.write_text(canonical_yaml, encoding="utf-8")
        print(f"[DONE] Overwrote original: {d_path}")
    else:
        print("[HALT] Structural drift detected.")
        print("       Review the diff above.")
        print("       Re-run with --execute to overwrite original.")
        return False

    return True


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
