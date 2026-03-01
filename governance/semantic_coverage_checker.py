"""
semantic_coverage_checker.py — Hard-Fail Pre-Execution Coverage Gate

Authority: SOP_TESTING (Stage-0.55)
Purpose:
    Verify that every behavioral parameter declared in a directive is
    structurally referenced in the generated strategy.py.

Rules:
    1. READ-ONLY on directive and strategy.
    2. Static analysis only (AST + source scan).
    3. No runtime instrumentation.
    4. Parent-first matching: leaf keys are only covered if their
       parent block key is also referenced.
    5. Hard-fail on missing coverage.
"""

import ast
import sys
from pathlib import Path

# Project Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import parse_directive

# ==============================================================================
# INFORMATIONAL KEYS (excluded from behavioral coverage)
# ==============================================================================

INFORMATIONAL_KEYS = {
    "test",
    "name",
    "family",
    "strategy",
    "broker",
    "timeframe",
    "start_date",
    "end_date",
    "symbols",
    "indicators",
    "research_mode",
    "tuning_allowed",
    "parameter_mutation",
    "session_time_reference",
    "description",
    "notes",
    "backtest",
    "signature_version",
}


# ==============================================================================
# STEP 1: FLATTEN DIRECTIVE INTO DOT-PATH KEYS
# ==============================================================================

def flatten_directive(parsed_config: dict, prefix: str = "") -> list[tuple[str, str]]:
    """
    Recursively flatten directive dict into (dot_path, parent_block) tuples.
    
    Example:
        execution_rules.stop_loss.type -> parent_block = "stop_loss"
        execution_rules.stop_loss     -> parent_block = "execution_rules"
    
    Excludes informational keys at any level.
    
    Returns:
        List of (dot_path, immediate_parent_key) tuples.
    """
    results = []
    for key, value in parsed_config.items():
        if key.lower() in INFORMATIONAL_KEYS:
            continue

        full_path = f"{prefix}.{key}" if prefix else key
        parent = prefix.rsplit(".", 1)[-1] if prefix else ""

        if isinstance(value, dict):
            # Record the block key itself
            results.append((full_path, parent))
            # Recurse into children
            results.extend(flatten_directive(value, full_path))
        elif isinstance(value, list):
            # Lists of scalars or dicts: record the key but don't recurse
            # into list items (indicator lists, symbol lists, etc.)
            results.append((full_path, parent))
        else:
            # Scalar value (leaf)
            results.append((full_path, parent))
    return results


# ==============================================================================
# STEP 2: EXTRACT REFERENCED KEYS FROM STRATEGY.PY (AST)
# ==============================================================================

def _extract_string_from_node(node) -> str | None:
    """Extract string value from an AST Constant node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_strategy_references(strategy_path: str) -> set[str]:
    """
    Parse strategy.py via AST to find all string keys used in dict access.
    
    Detects patterns:
        - x["key"]           (Subscript with string)
        - x.get("key")       (Call to .get() with string arg)
        - x.get("key", ...)  (Call to .get() with default)
        - cfg["key"]         (Direct dict access)
    
    Also collects keys from the STRATEGY_SIGNATURE dict literal.
    
    Returns:
        Set of all referenced string keys.
    """
    source = Path(strategy_path).read_text(encoding="utf-8")
    
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise RuntimeError(f"SEMANTIC_COVERAGE_FAILURE: Cannot parse strategy.py: {e}")
    
    referenced = set()
    
    for node in ast.walk(tree):
        # Pattern 1: x["key"]
        if isinstance(node, ast.Subscript):
            key = _extract_string_from_node(node.slice)
            if key:
                referenced.add(key)
        
        # Pattern 2: x.get("key") or x.get("key", default)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if node.args:
                    key = _extract_string_from_node(node.args[0])
                    if key:
                        referenced.add(key)
        
        # Pattern 3: String constants in STRATEGY_SIGNATURE dict literal
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STRATEGY_SIGNATURE":
                    _collect_dict_keys(node.value, referenced)
                elif isinstance(target, ast.Attribute) and target.attr == "STRATEGY_SIGNATURE":
                    _collect_dict_keys(node.value, referenced)
        
        # Pattern 4: String constants used in comparisons (== "value")
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                key = _extract_string_from_node(comparator)
                if key:
                    referenced.add(key)
            key = _extract_string_from_node(node.left)
            if key:
                referenced.add(key)
    
    return referenced


def _collect_dict_keys(node, key_set: set):
    """Recursively collect all string keys from an AST Dict node."""
    if isinstance(node, ast.Dict):
        for key_node in node.keys:
            key = _extract_string_from_node(key_node)
            if key:
                key_set.add(key)
        for value_node in node.values:
            _collect_dict_keys(value_node, key_set)
    elif isinstance(node, ast.List):
        for elt in node.elts:
            _collect_dict_keys(elt, key_set)


# ==============================================================================
# STEP 3: COVERAGE CHECK (PARENT-FIRST MATCHING)
# ==============================================================================

def check_semantic_coverage(directive_path: str, strategy_path: str) -> bool:
    """
    Hard-fail coverage check.
    
    Two-Tier Algorithm:
        1. Flatten directive into (dot_path, parent_key) tuples.
        2. Extract all referenced string keys from strategy.py via AST.
        3. Classify each dot_path entry:
           a. BLOCK entry (value is dict): covered if the block's own key
              appears in referenced_keys. This handles dict passthrough.
           b. LEAF entry (value is scalar/list): the leaf key ITSELF must
              appear in referenced_keys. Parent coverage does NOT propagate
              to leaves — this prevents false positives.
        4. If uncovered set is non-empty → raise RuntimeError.
    
    Returns:
        True if all behavioral parameters are covered.
    
    Raises:
        RuntimeError with SEMANTIC_COVERAGE_FAILURE on missing coverage.
    """
    # 1. Parse directive
    parsed = parse_directive(Path(directive_path))
    
    # 2. Extract references from strategy
    referenced_keys = extract_strategy_references(strategy_path)
    
    # 3. Walk directive and check coverage with two-tier logic
    uncovered = []
    _check_coverage_recursive(parsed, "", referenced_keys, uncovered)
    
    # 4. Report
    if uncovered:
        lines = ["SEMANTIC_COVERAGE_FAILURE:", ""]
        lines.append("The following directive parameters are declared but not referenced in strategy.py:")
        lines.append("")
        for path in sorted(uncovered):
            lines.append(f"  - {path}")
        lines.append("")
        lines.append("Update strategy implementation or remove unused directive parameters.")
        
        raise RuntimeError("\n".join(lines))
    
    return True


def _check_coverage_recursive(
    config: dict, prefix: str, referenced: set[str], uncovered: list[str]
):
    """
    Recursively check coverage with two-tier matching.
    
    - Block keys (dicts): covered if key name appears in referenced set.
      If NOT covered, the entire subtree is uncovered.
      If covered, recurse into children to check leaves.
    - Leaf keys (scalars/lists): covered if key name appears in referenced set.
    """
    for key, value in config.items():
        if key.lower() in INFORMATIONAL_KEYS:
            continue
        
        full_path = f"{prefix}.{key}" if prefix else key
        
        if isinstance(value, dict):
            # Block entry: check if block key is referenced
            if key in referenced:
                # Block is accessed — recurse to check leaves
                _check_coverage_recursive(value, full_path, referenced, uncovered)
            else:
                # Block NOT referenced at all — entire subtree uncovered
                uncovered.append(full_path)
        else:
            # Leaf entry: leaf key must independently appear
            if key not in referenced:
                uncovered.append(full_path)

