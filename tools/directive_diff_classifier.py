"""
directive_diff_classifier.py - Mechanical delta classifier for two directives.

Authority: Phase 2 of Idea-Gate Evolution Plan
Role: Deterministic, fail-closed, rule-based classification of the delta
      between two parsed directives. Used as an ADVISORY pre-check for the
      Idea Evaluation Gate and as a CLI diagnostic for humans.

This tool does NOT:
  - Parse YAML itself (callers pass parsed dicts from parse_directive).
  - Read the filesystem (except the indicator-module hashes it's explicitly
    given paths for).
  - Make policy decisions (callers interpret the returned classification).

Classification rules (in strict precedence order):
  1. SIGNAL     - indicator import set differs (module path change), OR
                  an indicator module's content hash differs.
  2. PARAMETER  - only numeric leaves differ (int/float), no structural change.
  3. COSMETIC   - only prose / identity fields differ (description, notes,
                  repeat_override_reason).
  4. UNCLASSIFIABLE - anything else. Fail-closed: caller MUST treat this as
                      a signal-level change unless proven otherwise.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from tools.filter_registry import FILTER_STACK_BLOCKS, is_behavioral_filter_config

# Keys whose differences do NOT alter trading behavior. Subset of
# NON_SIGNATURE_KEYS but narrower: we consider ONLY genuinely cosmetic fields.
# Identity fields (name, strategy, etc.) are expected to differ between two
# distinct directives and therefore shouldn't count as "prose differences".
_COSMETIC_KEYS = frozenset({
    "description",
    "notes",
    "repeat_override_reason",
})

_IDENTITY_KEYS = frozenset({
    "name", "family", "strategy", "version", "broker",
    "timeframe", "session_time_reference", "start_date", "end_date",
    "research_mode", "tuning_allowed", "parameter_mutation",
    "test", "backtest", "symbols",
    "signal_version",   # version metadata; hoisted to root by parse_directive
})

# Fields that, when different, definitionally indicate a signal-level change.
# `indicators` is the canonical one — module import set.
_SIGNAL_KEYS = frozenset({
    "indicators",
})

# Specific full leaf paths (dot-separated) that represent execution-state policy
# rather than entry signal logic.  Changes here are SIGNAL-level (require a
# signal_version bump) but are NOT structural/UNCLASSIFIABLE.
# Add paths intentionally — do NOT blanket-list a parent block.
_BEHAVIORAL_EXECUTION_LEAVES = frozenset({
    "state_machine.no_reentry_after_stop",
})

# FilterStack block keys (imported from tools.filter_registry) are
# signal-level ONLY when the diff represents a real behavioral change.
# Crisp rule (see filter_registry.is_behavioral_filter_config):
#   behavioral iff block has enabled=True AND >=1 key other than "enabled".
# Empty-block adds, disabled-block adds, and disabled->disabled tweaks
# are reclassified as cosmetic rather than structural.
_FILTER_BLOCK_KEYS = FILTER_STACK_BLOCKS


def _module_hash(module_path: str, project_root: Path) -> str | None:
    """Return sha256 of a module file's bytes, or None if not locatable.

    module_path is a dotted import like 'indicators.structure.choch_v3'.
    """
    rel = Path(*module_path.split(".")).with_suffix(".py")
    candidate = project_root / rel
    if not candidate.exists():
        return None
    try:
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return None


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into path-keyed leaves. Lists become tuple-leaves."""
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        # Lists are treated as ordered tuples for comparison, not deeply flattened.
        out[prefix] = tuple(d)
    else:
        out[prefix] = d
    return out


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _classify_filter_block_diffs(
    directive_a: dict,
    directive_b: dict,
) -> tuple[list[str], list[str]]:
    """Compare FilterStack top-level blocks between two directives.

    Returns (behavioral_blocks, cosmetic_blocks):
      - behavioral_blocks: filter block keys whose diff represents real
        behavioral change (promotes classification to SIGNAL).
      - cosmetic_blocks: filter block keys whose diff is inert (empty
        adds, disabled->disabled tweaks).

    Rule (crisp, no 'default value' semantics):
      A filter-block diff is behavioral iff at least one side of the
      diff is a behaviorally-effective config (enabled=True AND >=1
      key other than 'enabled'). Otherwise the diff is cosmetic.
    """
    behavioral: list[str] = []
    cosmetic: list[str] = []
    for key in _FILTER_BLOCK_KEYS:
        va = directive_a.get(key, _MISSING)
        vb = directive_b.get(key, _MISSING)
        if va == vb:
            continue
        block_a = va if va is not _MISSING else None
        block_b = vb if vb is not _MISSING else None
        if is_behavioral_filter_config(block_a) or is_behavioral_filter_config(block_b):
            behavioral.append(key)
        else:
            cosmetic.append(key)
    return sorted(behavioral), sorted(cosmetic)


def _partition_diffs(
    leaves_a: dict[str, Any],
    leaves_b: dict[str, Any],
) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    """Partition the union of leaf keys into change classes.

    Returns (cosmetic, identity, numeric, structural, behavioral_execution) sets
    of leaf paths where the two directives differ. Keys present in only one side
    are counted as structural (they indicate shape change), unless they are a
    known execution-state leaf (in _BEHAVIORAL_EXECUTION_LEAVES), in which case
    they go to behavioral_execution regardless of presence/absence.

    Leaves belonging to FilterStack block keys are excluded here and
    handled separately by _classify_filter_block_diffs at the block
    (not leaf) level -- leaf-level partitioning mis-categorizes
    block-level structural changes as numeric or raw structural.
    """
    all_keys = set(leaves_a) | set(leaves_b)
    cosmetic: set[str] = set()
    identity: set[str] = set()
    numeric: set[str] = set()
    structural: set[str] = set()
    behavioral_execution: set[str] = set()

    for key in all_keys:
        va = leaves_a.get(key, _MISSING)
        vb = leaves_b.get(key, _MISSING)
        if va == vb:
            continue

        top = key.split(".", 1)[0]
        if top in _FILTER_BLOCK_KEYS:
            # Handled at block-level elsewhere -- do not leaf-partition.
            continue
        if top in _COSMETIC_KEYS:
            cosmetic.add(key)
        elif top in _IDENTITY_KEYS:
            identity.add(key)
        elif key in _BEHAVIORAL_EXECUTION_LEAVES:
            # Known execution-state policy leaf: SIGNAL-level but not structural.
            # Checked before the _MISSING guard so absence-vs-present is still
            # treated as a policy change rather than a shape change.
            behavioral_execution.add(key)
        elif va is _MISSING or vb is _MISSING:
            structural.add(key)
        elif _is_numeric(va) and _is_numeric(vb):
            numeric.add(key)
        elif type(va) != type(vb):
            structural.add(key)
        else:
            structural.add(key)

    return cosmetic, identity, numeric, structural, behavioral_execution


class _Missing:
    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


def classify_diff(
    directive_a: dict,
    directive_b: dict,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Classify the delta between two parsed directives.

    Args:
        directive_a, directive_b: Parsed directive dicts (from parse_directive).
        project_root: Optional project root for locating indicator modules
            to compute content hashes. If None, module-hash delta is skipped
            (import-set delta still evaluated).

    Returns:
        dict with keys:
            - classification: "SIGNAL" | "PARAMETER" | "COSMETIC" | "UNCLASSIFIABLE"
            - reason: human-readable explanation
            - indicator_import_delta: list of (removed, added) module paths
            - indicator_hash_delta: list of module paths whose content differs
            - numeric_diffs: list of leaf paths differing in numeric value
            - cosmetic_diffs: list of leaf paths differing in prose
            - structural_diffs: list of leaf paths differing structurally
    """
    inds_a = set(directive_a.get("indicators") or [])
    inds_b = set(directive_b.get("indicators") or [])
    removed = sorted(inds_a - inds_b)
    added = sorted(inds_b - inds_a)

    hash_delta: list[str] = []
    if project_root is not None:
        common = inds_a & inds_b
        for mod in sorted(common):
            ha = _module_hash(mod, project_root)
            hb = _module_hash(mod, project_root)
            # Note: a and b share the same file path here; the hash delta
            # is meaningful when comparing across two checkouts. Keep the
            # plumbing in place for future cross-snapshot comparison.
            if ha is None or hb is None:
                continue
            if ha != hb:
                hash_delta.append(mod)

    leaves_a = _flatten(directive_a)
    leaves_b = _flatten(directive_b)
    cosmetic, identity, numeric, structural, behavioral_execution = _partition_diffs(leaves_a, leaves_b)

    # Block-level FilterStack diff handled separately (not via leaves).
    filter_behavioral, filter_cosmetic = _classify_filter_block_diffs(
        directive_a, directive_b
    )
    # Fold inert filter-block diffs into cosmetic set so they don't
    # interfere with downstream SIGNAL/PARAMETER/COSMETIC reasoning.
    for _k in filter_cosmetic:
        cosmetic.add(_k)

    # Rule 1a: indicator import set differs OR module hash differs -> SIGNAL
    if removed or added or hash_delta:
        return {
            "classification": "SIGNAL",
            "reason": (
                f"indicator import delta: -{removed} +{added}"
                + (f"; module-hash delta: {hash_delta}" if hash_delta else "")
            ),
            "indicator_import_delta": {"removed": removed, "added": added},
            "indicator_hash_delta": hash_delta,
            "filter_behavioral_blocks": filter_behavioral,
            "numeric_diffs": sorted(numeric),
            "cosmetic_diffs": sorted(cosmetic),
            "structural_diffs": sorted(structural),
            "behavioral_execution_diffs": sorted(behavioral_execution),
        }

    # Rule 1b: behavioral FilterStack block change -> SIGNAL
    # (add/remove of an effective block, or param change in an enabled block)
    if filter_behavioral:
        return {
            "classification": "SIGNAL",
            "reason": (
                f"filter-stack behavioral change: {filter_behavioral}"
            ),
            "indicator_import_delta": {"removed": [], "added": []},
            "indicator_hash_delta": [],
            "filter_behavioral_blocks": filter_behavioral,
            "numeric_diffs": sorted(numeric),
            "cosmetic_diffs": sorted(cosmetic),
            "structural_diffs": sorted(structural),
            "behavioral_execution_diffs": sorted(behavioral_execution),
        }

    # Rule 1c: known execution-state behavioral leaf changed -> SIGNAL
    # Only fires when there are no unknown structural diffs alongside it.
    # Mixed (behavioral_execution + structural) falls through to UNCLASSIFIABLE.
    if behavioral_execution and not structural:
        return {
            "classification": "SIGNAL",
            "reason": (
                f"execution-state behavioral leaf change: {sorted(behavioral_execution)}"
            ),
            "indicator_import_delta": {"removed": [], "added": []},
            "indicator_hash_delta": [],
            "filter_behavioral_blocks": filter_behavioral,
            "numeric_diffs": sorted(numeric),
            "cosmetic_diffs": sorted(cosmetic),
            "structural_diffs": [],
            "behavioral_execution_diffs": sorted(behavioral_execution),
        }

    # Rule 2: only numeric leaves differ (identity ignored; cosmetic tolerated) -> PARAMETER
    if numeric and not structural:
        return {
            "classification": "PARAMETER",
            "reason": f"only numeric parameter diffs: {sorted(numeric)}",
            "indicator_import_delta": {"removed": [], "added": []},
            "indicator_hash_delta": [],
            "filter_behavioral_blocks": [],
            "numeric_diffs": sorted(numeric),
            "cosmetic_diffs": sorted(cosmetic),
            "structural_diffs": [],
            "behavioral_execution_diffs": [],
        }

    # Rule 3: only cosmetic/identity leaves differ -> COSMETIC
    if not numeric and not structural:
        return {
            "classification": "COSMETIC",
            "reason": (
                f"only cosmetic/identity diffs: cosmetic={sorted(cosmetic)}, "
                f"identity={sorted(identity)}"
            ),
            "indicator_import_delta": {"removed": [], "added": []},
            "indicator_hash_delta": [],
            "filter_behavioral_blocks": [],
            "numeric_diffs": [],
            "cosmetic_diffs": sorted(cosmetic),
            "structural_diffs": [],
            "behavioral_execution_diffs": [],
        }

    # Rule 4: fail-closed
    return {
        "classification": "UNCLASSIFIABLE",
        "reason": (
            f"structural diffs present: {sorted(structural)} "
            f"(numeric={sorted(numeric)}, cosmetic={sorted(cosmetic)})"
        ),
        "indicator_import_delta": {"removed": removed, "added": added},
        "indicator_hash_delta": hash_delta,
        "filter_behavioral_blocks": filter_behavioral,
        "numeric_diffs": sorted(numeric),
        "cosmetic_diffs": sorted(cosmetic),
        "structural_diffs": sorted(structural),
        "behavioral_execution_diffs": sorted(behavioral_execution),
    }


def _main() -> int:
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(
        description="Classify the delta between two directives.",
    )
    p.add_argument("directive_a", type=Path)
    p.add_argument("directive_b", type=Path)
    p.add_argument(
        "--no-hash",
        action="store_true",
        help="Skip indicator module content-hash comparison.",
    )
    args = p.parse_args()

    # Lazy import to avoid circular deps at module load time.
    from tools.pipeline_utils import parse_directive

    da = parse_directive(args.directive_a)
    db = parse_directive(args.directive_b)

    root = None if args.no_hash else Path(__file__).resolve().parent.parent
    result = classify_diff(da, db, project_root=root)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["classification"] != "UNCLASSIFIABLE" else 2


if __name__ == "__main__":
    import sys
    sys.exit(_main())
