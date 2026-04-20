"""
Capability inference — static analysis of strategy.py.

Derives the set of capability tokens implied by a strategy's structure.
Never imports or executes strategy code. Consumed by the preflight
capability-resolution step before engine binding.

Primary signal  : AST trigger rules from governance/capability_catalog.yaml
                  (presence of a top-level or class-level function whose
                  name matches the token's ast_trigger). Every capability
                  is tied to a concrete AST symbol — there is no "always"
                  baseline. A strategy missing check_entry or check_exit
                  will fail preflight F5 (declared-not-inferred) instead
                  of AttributeError at engine runtime.

Secondary signal: substring fallback for "PartialLegRecord" or
                  "partial_exit" anywhere in source — catches partial-exit
                  usage that escapes the AST rule (e.g. dynamic dispatch).
                  Merged into the inferred set; never weakens the strict
                  inferred == declared equality check enforced at preflight.
"""
import ast
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CATALOG_PATH = PROJECT_ROOT / "governance" / "capability_catalog.yaml"

CAP_BLOCK_START = "# --- CAPABILITY REQUIREMENTS START ---"
CAP_BLOCK_END = "# --- CAPABILITY REQUIREMENTS END ---"


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
        if trigger and trigger in fn_names:
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


def resolve_frozen_contract_id(required_caps) -> str:
    """
    Select the FROZEN engine whose capability set satisfies the required
    set, return its contract_id. Raises if zero satisfying engines.
    Shared between the backfill tool and strategy_provisioner so that
    both emit identical REQUIRED_CONTRACT_IDS values at write time.
    """
    engine_dev = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
    vault = PROJECT_ROOT / "vault" / "engines" / "Universal_Research_Engine"
    required = set(required_caps)

    candidates = []
    for root in (engine_dev, vault):
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            mpath = d / "engine_manifest.json"
            if not mpath.exists():
                continue
            with open(mpath, encoding="utf-8") as f:
                m = json.load(f)
            if m.get("engine_status") != "FROZEN":
                continue
            if not m.get("contract_id"):
                continue
            engine_caps = set(m.get("capabilities") or [])
            if not required.issubset(engine_caps):
                continue
            candidates.append(m["contract_id"])

    unique = sorted(set(candidates))
    if not unique:
        raise RuntimeError(
            f"no FROZEN engine with contract_id satisfies {sorted(required)}"
        )
    return unique[0]


def render_capability_block(caps, contracts) -> str:
    """
    Render the module-level REQUIRED_CAPABILITIES / REQUIRED_CONTRACT_IDS
    block with sentinel markers. Shared between provisioner (new files)
    and backfill tool (existing files) so bytes match exactly, keeping
    idempotency checks stable across both codepaths.
    """
    def _fmt(items):
        inner = ",\n    ".join(f'"{x}"' for x in sorted(items))
        return f"[\n    {inner},\n]" if items else "[]"
    return (
        f"{CAP_BLOCK_START}\n"
        f"REQUIRED_CAPABILITIES = {_fmt(caps)}\n"
        f"REQUIRED_CONTRACT_IDS = {_fmt(contracts)}\n"
        f"{CAP_BLOCK_END}\n"
    )
