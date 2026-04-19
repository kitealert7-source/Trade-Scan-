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
    Extract (REQUIRED_CAPABILITIES, REQUIRED_CONTRACT_IDS) from module-
    level assignments in strategy.py, using ast.literal_eval.

    These live OUTSIDE STRATEGY_SIGNATURE so that adding them does not
    perturb the strategy↔directive signature hash (CHECK 6.7). They
    describe the strategy↔engine binding, not the trading identity.

    Returns (value, value) where each value is a list or None. None
    signals the constant is absent entirely (distinguishing F1/F2 from
    F3-empty-list at preflight).
    """
    source = strategy_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    caps = None
    contracts = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not node.targets or not isinstance(node.targets[0], ast.Name):
            continue
        target = node.targets[0].id
        if target not in ("REQUIRED_CAPABILITIES", "REQUIRED_CONTRACT_IDS"):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if target == "REQUIRED_CAPABILITIES":
            caps = value
        else:
            contracts = value

    return caps, contracts
