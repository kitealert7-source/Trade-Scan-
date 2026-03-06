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

# Import specific tools
from tools.directive_utils import load_directive_yaml, get_key_ci

def _canonicalize(obj):
    """
    Return a structural canonical representation for strict deterministic comparison.
    Recursively sorts dictionary keys.
    """
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj)}
    elif isinstance(obj, list):
        return [_canonicalize(x) for x in obj]
    else:
        return obj

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
    # d_conf = parse_directive(directive_path) # ORIGINAL
    
    # UPGRADE: Direct YAML Load via Shared Utility
    try:
        d_conf = load_directive_yaml(directive_path)
    except Exception as e:
        raise ValueError(f"Failed to parse directive YAML: {e}")

    # Extract Identity (Match Provisioner Logic)
    test_block = get_key_ci(d_conf, "test") or {}
    
    target_strategy_name = get_key_ci(test_block, "strategy") or get_key_ci(d_conf, "strategy")
    target_timeframe = get_key_ci(test_block, "timeframe") or get_key_ci(d_conf, "timeframe")
    
    if not target_strategy_name:
        raise ValueError("Directive missing 'Strategy' field")
    if not target_timeframe:
         raise ValueError("Directive missing 'Timeframe' field")

    # Extract Indicators (Must be a list)
    declared_indicators = get_key_ci(d_conf, "indicators") or get_key_ci(test_block, "indicators") or []
    if isinstance(declared_indicators, str): declared_indicators = [declared_indicators]
    
    if not isinstance(declared_indicators, list):
         raise ValueError(f"Directive 'Indicators' must be a list. Found {type(declared_indicators)}.")

    # BUILD EXPECTED SIGNATURE (Single Authority: directive_schema.py)
    from tools.directive_schema import normalize_signature
    expected_signature = normalize_signature(d_conf)

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
            self.signature_dict = None
            
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
                                elif target.id == "STRATEGY_SIGNATURE":
                                    # Safe extraction of dictionary literal
                                    try:
                                        self.signature_dict = ast.literal_eval(item.value)
                                    except ValueError:
                                        print(f"[WARN] Could not eval STRATEGY_SIGNATURE literal. Complexity too high?")
                                        self.signature_dict = None
                                        
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            # Strict Module Extraction
            if node.module and node.module.startswith("indicators"):
                self.imports.add(node.module)

    visitor = SemanticVisitor()
    visitor.visit(tree)

    if not visitor.found_class:
        raise ValueError("No 'class Strategy' found in strategy.py")
    
    if visitor.signature_dict is None:
        raise ValueError("STRATEGY_SIGNATURE not found or invalid literal in strategy.py")

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

    # B. Signature Equality (Deep Canonical Check and Version Enforcement)
    
    actual_version = visitor.signature_dict.get("signature_version")

    from tools.directive_schema import SIGNATURE_SCHEMA_VERSION
    if actual_version != SIGNATURE_SCHEMA_VERSION:
        raise ValueError(
            f"Signature schema version mismatch. "
            f"Expected {SIGNATURE_SCHEMA_VERSION}, "
            f"Found {actual_version}. "
            f"Re-provision required."
        )

    canonical_expected = _canonicalize(expected_signature)
    canonical_actual = _canonicalize(visitor.signature_dict)
    
    if canonical_expected != canonical_actual:
        raise ValueError(
            f"STRATEGY_SIGNATURE Mismatch.\n"
            f"Expected: {canonical_expected}\n"
            f"Actual:   {canonical_actual}"
        )

    # C. Indicators (Exact Set Equality) - REDUNDANT but kept for granular error msg? 
    # Actually if signature matches, imports from indicators must explicitly match?
    # NO: Signature contains strings like "indicators...". 
    # Code contains imports "from indicators...". 
    # We still need to validate imports exist for the indicators listed in signature.
    
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
    print(f"[SEMANTIC] Signature Verified: MATCH")
    print(f"[SEMANTIC] Indicator Set Match: {len(declared_set)} modules")
    
    # 5. Behavioral Guard (Architectural Enforcement)
    # ------------------------------------------------------------------
    class BehavioralGuard(ast.NodeVisitor):
        def __init__(self):
            self.uses_filterstack_import = False
            self.initializes_filterstack = False
            self.calls_allow_trade = False
            self.illegal_regime_compare = False
            self.illegal_nodes = []
            self.regime_aliases = set()

        def visit_ImportFrom(self, node):
            if node.module == "engines.filter_stack" and "FilterStack" in [n.name for n in node.names]:
                self.uses_filterstack_import = True
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            if node.name == "__init__":
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            # Check for self.filter_stack = ...
                            if isinstance(target, ast.Attribute) and \
                               isinstance(target.value, ast.Name) and \
                               target.value.id == "self" and \
                               target.attr == "filter_stack":
                                # Check if value is FilterStack(...)
                                if isinstance(stmt.value, ast.Call) and \
                                   isinstance(stmt.value.func, ast.Name) and \
                                   stmt.value.func.id == "FilterStack":
                                    self.initializes_filterstack = True

            elif node.name == "check_entry":
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Call):
                        # Check for self.filter_stack.allow_trade(...)
                        if isinstance(stmt.func, ast.Attribute) and \
                           stmt.func.attr == "allow_trade" and \
                           isinstance(stmt.func.value, ast.Attribute) and \
                           stmt.func.value.attr == "filter_stack" and \
                           isinstance(stmt.func.value.value, ast.Name) and \
                           stmt.func.value.value.id == "self":
                            self.calls_allow_trade = True
            
            self.generic_visit(node)
        
        def visit_Assign(self, node):
            # Detect alias creation: reg = row.get("regime")
            if isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Attribute):
                    if node.value.func.attr == "get":
                        if len(node.value.args) > 0 and isinstance(node.value.args[0], ast.Constant):
                            if node.value.args[0].value in ["regime", "trend_regime"]:
                                for target in node.targets:
                                    if isinstance(target, ast.Name):
                                        self.regime_aliases.add(target.id)

            # Detect alias: reg = row["regime"]
            if isinstance(node.value, ast.Subscript):
                slice_node = node.value.slice
                key = None

                if isinstance(slice_node, ast.Constant):
                    key = slice_node.value
                elif hasattr(ast, "Index") and isinstance(slice_node, ast.Index) and isinstance(slice_node.value, ast.Constant):
                    key = slice_node.value.value

                if key in ["regime", "trend_regime"]:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.regime_aliases.add(target.id)

            self.generic_visit(node)

        def visit_Compare(self, node):
            # Check left and right operands for illegal access
            # We look for direct string comparisons against "regime" or "trend_regime" values
            
            def is_illegal_access(n):
                # 1. Subscript: row["regime"]
                if isinstance(n, ast.Subscript):
                    if isinstance(n.slice, ast.Constant) and n.slice.value in ["regime", "trend_regime"]:
                        return True
                    # Python < 3.9 uses ast.Index
                    if isinstance(n.slice, ast.Index) and isinstance(n.slice.value, ast.Constant) and n.slice.value.value in ["regime", "trend_regime"]:
                        return True
                        
                # 2. Call: row.get("regime")
                if isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Attribute) and n.func.attr == "get":
                        if len(n.args) > 0 and isinstance(n.args[0], ast.Constant) and n.args[0].value in ["regime", "trend_regime"]:
                            return True
                return False

            if is_illegal_access(node.left) or any(is_illegal_access(comparator) for comparator in node.comparators):
                # Check if comparing against a literal number (likely a regime code)
                # But basically ANY direct comparison is suspicious outside FilterStack
                self.illegal_regime_compare = True
                self.illegal_nodes.append(node)
            
            # Detect alias usage in comparison
            for side in [node.left] + node.comparators:
                if isinstance(side, ast.Name):
                    if side.id in self.regime_aliases:
                        self.illegal_regime_compare = True
                        self.illegal_nodes.append(node)
                
            self.generic_visit(node)

    guard = BehavioralGuard()
    guard.visit(tree)

    if not guard.uses_filterstack_import:
        raise ValueError("Architectural Violation: 'from engines.filter_stack import FilterStack' missing.")

    if not guard.initializes_filterstack:
        raise ValueError("Architectural Violation: 'self.filter_stack = FilterStack(...)' missing in __init__.")

    if not guard.calls_allow_trade:
        raise ValueError("Architectural Violation: 'self.filter_stack.allow_trade(...)' not called in check_entry.")

    if guard.illegal_regime_compare:
        raise ValueError(f"Architectural Violation: Hardcoded regime comparison detected. strict usage of FilterStack required. Found {len(guard.illegal_nodes)} instance(s).")

    print("[SEMANTIC] Behavioral Guard: PASSED (FilterStack Enforced)")
    
    # 6. Hollow Strategy Detection (Admission Gate)
    # ------------------------------------------------------------------
    # A hollow strategy is one where check_entry() body is strictly:
    #   - optional docstring (ast.Expr with ast.Constant/ast.Str)
    #   - optional filter_stack guard (if not self.filter_stack.allow_trade: return None)
    #   - return None
    # Anything beyond that pattern = considered implemented.

    class HollowDetector(ast.NodeVisitor):
        def __init__(self):
            self.check_entry_is_hollow = False

        def visit_FunctionDef(self, node):
            if node.name != "check_entry":
                return
            
            remaining = []
            for stmt in node.body:
                # Skip docstrings
                if isinstance(stmt, ast.Expr) and isinstance(
                    getattr(stmt, 'value', None), (ast.Constant, ast.Str)
                ):
                    continue
                # Skip: if not self.filter_stack.allow_trade(ctx): return None
                if isinstance(stmt, ast.If):
                    test = stmt.test
                    is_guard = False
                    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                        call = test.operand
                        if (isinstance(call, ast.Call) and
                            isinstance(call.func, ast.Attribute) and
                            call.func.attr == "allow_trade"):
                            is_guard = True
                    if is_guard:
                        continue
                # Skip: return None
                if isinstance(stmt, ast.Return):
                    val = stmt.value
                    if val is None or (isinstance(val, ast.Constant) and val.value is None):
                        continue
                # Anything else = non-trivial
                remaining.append(stmt)
            
            if len(remaining) == 0:
                self.check_entry_is_hollow = True

    hollow = HollowDetector()
    hollow.visit(tree)

    if hollow.check_entry_is_hollow:
        raise ValueError(
            "PROVISION_REQUIRED: check_entry() contains no execution logic. "
            "Strategy was auto-provisioned but not implemented. "
            "Human must author entry/exit logic before pipeline execution."
        )

    print("[SEMANTIC] Admission Gate: PASSED (Strategy is implemented)")

    return True

# NO STANDALONE ENTRY POINT PERMITTED
