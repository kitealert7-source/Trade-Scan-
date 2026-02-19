"""
Stage-0.5 — Strategy Semantic Validation (Hardened)
Authority: ENGINE REFINEMENT REQUEST — STAGE-0.5 STRICT HARDENING
Status: MANDATORY EXECUTION GATE

Purpose:
Validate strict deterministic identity between Directive (Intent) and Strategy (Implementation).

Rules:
1. PURE: No side effects.
2. STRICT: Exact set equality for indicators. No prefix matching.
3. AUTHORITATIVE: Directive format is final. No regex parsing.
4. SCOPE: Identity & Indicators only. No parameters.
"""

import sys
import ast
from pathlib import Path

# Project root setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import strictly from utils
from tools.pipeline_utils import parse_directive

def validate_semantic_signature(directive_path_str: str) -> bool:
    """
    Perform strict semantic validation.
    Raises Exception on ANY failure.
    Returns True on success.
    """
    print(f"[SEMANTIC] Validating Directive: {Path(directive_path_str).name}")
    
    directive_path = Path(directive_path_str)
    if not directive_path.exists():
        raise FileNotFoundError(f"Directive not found: {directive_path}")

    # 1. Parse Directive (Authoritative)
    # ------------------------------------------------------------------
    # Use only the standardized parser. No regex.
    d_conf = parse_directive(directive_path)
    
    # Extract Identity
    target_strategy_name = d_conf.get("Strategy")
    target_timeframe = d_conf.get("Timeframe")
    
    if not target_strategy_name:
        raise ValueError("Directive missing 'Strategy' field")
    if not target_timeframe:
         raise ValueError("Directive missing 'Timeframe' field")

    # Extract Indicators (Must be a list)
    declared_indicators = d_conf.get("Indicators", [])
    if isinstance(declared_indicators, str):
         # Single item as string? Enforce list in directive, but parse_directive might behave differently.
         # parse_directive handling:
         # If "- item", it becomes list.
         # If single value, it becomes string.
         # Strictness requires us to handle both or fail if not list?
         # "If Indicators is not a list → Hard Fail."
         # But parse_directive might return single string if only one listed without dash?
         # Let's check parse_directive logic. It says: "If not val: ... parsed[current_key] = []" 
         # "If line.startswith("-"): ... parsed[current_key].append(val)"
         # So if written as list in directive, it is list in dict.
         # If written "Indicators: foo", it is string.
         # User Rule: "If Indicators is not a list → Hard Fail."
         raise ValueError("Directive 'Indicators' must be a list (use dash syntax).")
    
    if not isinstance(declared_indicators, list):
         # Could be None if missing
         if "Indicators" not in d_conf:
              raise ValueError("Directive missing 'Indicators' key.")
         raise ValueError(f"Directive 'Indicators' must be a list. Found {type(declared_indicators)}.")

    # 2. Locate Strategy (Implementation)
    # ------------------------------------------------------------------
    strategy_file = PROJECT_ROOT / "strategies" / target_strategy_name / "strategy.py"
    if not strategy_file.exists():
        raise FileNotFoundError(f"Strategy file not found: {strategy_file}")

    print(f"[SEMANTIC] Target Strategy: {target_strategy_name} -> {strategy_file}")

    # 3. Component Extraction (AST)
    # ------------------------------------------------------------------
    try:
        source = strategy_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        raise RuntimeError(f"Failed to parse strategy source: {e}")

    class SemanticVisitor(ast.NodeVisitor):
        def __init__(self):
            self.found_class = False
            self.class_name_attr = None
            self.class_tf_attr = None
            self.imports = set()
            
        def visit_ClassDef(self, node):
            if node.name == "Strategy":
                self.found_class = True
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == "name":
                                    if isinstance(item.value, ast.Constant):
                                        self.class_name_attr = item.value.value
                                    elif isinstance(item.value, ast.Str):
                                        self.class_name_attr = item.value.s
                                elif target.id == "timeframe":
                                    if isinstance(item.value, ast.Constant):
                                        self.class_tf_attr = item.value.value
                                    elif isinstance(item.value, ast.Str):
                                        self.class_tf_attr = item.value.s
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            # Strict Module Extraction
            if node.module and node.module.startswith("indicators"):
                self.imports.add(node.module)

    visitor = SemanticVisitor()
    visitor.visit(tree)

    if not visitor.found_class:
        raise ValueError("No 'class Strategy' found in strategy.py")

    # 4. Strict Validation Logic
    # ------------------------------------------------------------------

    # A. Identity
    if visitor.class_name_attr != target_strategy_name:
        raise ValueError(
            f"Strategy Identity Mismatch. Directive='{target_strategy_name}', Code='{visitor.class_name_attr}'"
        )
    
    if visitor.class_tf_attr != target_timeframe:
        raise ValueError(
            f"Timeframe Mismatch. Directive='{target_timeframe}', Code='{visitor.class_tf_attr}'"
        )

    # B. Indicators (Exact Set Equality)
    
    # Normalize Declared Modules
    # Directive format: "indicators/structure/range_breakout_session.py" 
    # OR "indicators.structure.range_breakout_session" (if user typed that)
    # We must normalize to python module path: "indicators.structure.range_breakout_session"
    
    declared_set = set()
    for d in declared_indicators:
        clean = d.replace("\\", "/").replace(".py", "").replace("/", ".")
        if not clean.startswith("indicators."):
            clean = "indicators." + clean
        declared_set.add(clean)

    code_set = visitor.imports
    
    # 1. Check for Missing Imports (Declared but not in Code)
    missing = declared_set - code_set
    if missing:
        raise ValueError(f"Missing Indicator Import(s): {missing}. Code must import all declared indicators.")

    # 2. Check for Undeclared Imports (In Code but not Declared)
    undeclared = code_set - declared_set
    if undeclared:
        raise ValueError(f"Undeclared Indicator Import(s): {undeclared}. Directive must declare all used indicators.")

    print(f"[SEMANTIC] Identity Verified: {target_strategy_name}")
    print(f"[SEMANTIC] Timeframe Verified: {target_timeframe}")
    print(f"[SEMANTIC] Indicator Set Match: {len(declared_set)} modules")
    
    return True

# NO STANDALONE ENTRY POINT PERMITTED
