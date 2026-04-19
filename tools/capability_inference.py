"""
Capability inference — static analysis of strategy.py.

Derives the set of capability tokens implied by a strategy's structure.
Never imports or executes strategy code. Consumed by the preflight
capability-resolution step before engine binding.

Primary signal  : AST trigger rules from governance/capability_catalog.yaml
                  (presence of a top-level or class-level function whose
                  name matches the token's ast_trigger).

Secondary signal: substring fallback for "PartialLegRecord" or
                  "partial_exit" anywhere in source — catches partial-exit
                  usage that escapes the AST rule (e.g. dynamic dispatch).
                  Merged into the inferred set; never weakens the strict
                  inferred == declared equality check enforced at preflight.
"""
import ast
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CATALOG_PATH = PROJECT_ROOT / "governance" / "capability_catalog.yaml"


def load_catalog() -> dict:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["capabilities"]


def _collect_function_names(tree: ast.AST) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def infer_capabilities(strategy_path: Path) -> set:
    """
    Return the set of capability tokens inferred from the strategy.

    Primary: catalog-driven AST rule match.
    Secondary: substring fallback for partial-exit usage.
    """
    source = strategy_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    catalog = load_catalog()
    fn_names = _collect_function_names(tree)

    inferred = set()
    for token, spec in catalog.items():
        trigger = (spec or {}).get("ast_trigger")
        if trigger == "always":
            inferred.add(token)
        elif trigger and trigger in fn_names:
            inferred.add(token)

    if "PartialLegRecord" in source or "partial_exit" in source:
        inferred.add("execution.partial_exit.v1")

    return inferred


def read_declared_fields(strategy_path: Path) -> tuple:
    """
    Extract (required_capabilities, required_contract_ids) from the
    STRATEGY_SIGNATURE dict embedded in strategy.py, using ast.literal_eval.

    Returns (value, value) where each value is a list or None. None
    signals the key is absent from the signature (distinguishing F1/F2
    from F3-empty-list at preflight). Returns (None, None) if the
    signature itself cannot be located or parsed.
    """
    source = strategy_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not node.targets or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != "STRATEGY_SIGNATURE":
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        try:
            sig = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None, None
        return sig.get("required_capabilities"), sig.get("required_contract_ids")

    return None, None
