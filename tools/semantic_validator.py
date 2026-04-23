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
import re
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

    # 5.6. Engine-Owned Fields Guard
    # ------------------------------------------------------------------
    # From engine v1.5.3 onwards, the regime_state_machine's
    # apply_regime_model() runs AFTER prepare_indicators() and
    # authoritatively writes these columns to the df. Any strategy that
    # re-computes or re-assigns them creates a silent second source of
    # truth: the strategy's column is overwritten by the engine, so the
    # gate reads one value while the trade record stamps another.
    # Strategies must access these fields exclusively via
    # ctx.require('<field>') at runtime -- not ctx.get(), which silently
    # returns a default on missing data instead of failing fast.
    #
    # IMPORT POLICY (refined 2026-04-23):
    #   An engine-owned module MAY be imported at module scope iff:
    #     (a) the imported symbol has ZERO references anywhere outside
    #         its own ImportFrom node -- it exists solely as a classifier
    #         artifact to force SIGNAL-class diff when a new FilterStack
    #         block consuming the field is introduced; AND
    #     (b) STRATEGY_SIGNATURE declares at least one "consumer filter"
    #         block that is behaviorally effective (enabled=True AND
    #         >=1 key beyond "enabled").
    #   Any reference to the imported symbol -- call, alias, attribute,
    #   pass-through, decorator -- FAILS. No whitelist.
    #
    # Central registry. `consumer_filters` lists the FilterStack block
    # names that legitimize the import (i.e. read the field from ctx at
    # runtime).
    from tools.filter_registry import is_behavioral_filter_config

    ENGINE_OWNED_FIELDS = {
        "volatility_regime": {
            "imports": {"indicators.volatility.volatility_regime"},
            "callables": {"volatility_regime"},
            "consumer_filters": {"volatility_filter", "market_regime_filter"},
        },
        "trend_regime": {
            "imports": set(),
            "callables": set(),
            "consumer_filters": set(),
        },
        "trend_score": {
            "imports": set(),
            "callables": set(),
            "consumer_filters": set(),
        },
        "trend_label": {
            "imports": set(),
            "callables": set(),
            "consumer_filters": set(),
        },
    }

    _eof_forbidden_imports = set()
    _eof_forbidden_callables = set()
    _eof_import_to_field = {}
    for _field_name, _field_def in ENGINE_OWNED_FIELDS.items():
        _eof_forbidden_imports |= _field_def["imports"]
        _eof_forbidden_callables |= _field_def["callables"]
        for _mod in _field_def["imports"]:
            _eof_import_to_field[_mod] = _field_name
    _eof_forbidden_columns = set(ENGINE_OWNED_FIELDS.keys())

    class EngineOwnedFieldsGuard(ast.NodeVisitor):
        """
        Strict three-rule guard:
          1. df['<engine_owned_col>'] = ...            -> FAIL
          2. <imported_engine_owned_symbol>(...)       -> FAIL (belt-and-braces)
          3. Any ast.Name reference to a symbol bound
             by a forbidden ImportFrom, anywhere other
             than the ImportFrom node itself           -> FAIL
        """

        def __init__(self, forbidden_imports, forbidden_columns, forbidden_callables):
            self.forbidden_imports_set = forbidden_imports
            self.forbidden_columns_set = forbidden_columns
            self.forbidden_callables_set = forbidden_callables
            self.bound_engine_owned_names = {}  # bound_name -> module_path
            self.imports_declared = []
            self.violations_assignments = []
            self.violations_calls = []
            self.violations_references = []  # list of (name, lineno)

        def visit_ImportFrom(self, node):
            if node.module in self.forbidden_imports_set:
                self.imports_declared.append(node.module)
                for alias in node.names:
                    bound = alias.asname or alias.name
                    self.bound_engine_owned_names[bound] = node.module
            # Intentionally do NOT generic_visit -- the ImportFrom's own
            # alias binding is permitted; visiting children would treat
            # the binding site as a reference.
            return

        def visit_Assign(self, node):
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if not (isinstance(target.value, ast.Name) and target.value.id == "df"):
                    continue
                col = self._extract_subscript_key(target.slice)
                if col in self.forbidden_columns_set:
                    self.violations_assignments.append(col)
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name):
                if node.func.id in self.forbidden_callables_set:
                    self.violations_calls.append(node.func.id)
            self.generic_visit(node)

        def visit_Name(self, node):
            if node.id in self.bound_engine_owned_names:
                self.violations_references.append((node.id, node.lineno))
            self.generic_visit(node)

        @staticmethod
        def _extract_subscript_key(slice_node):
            if isinstance(slice_node, ast.Constant):
                return slice_node.value
            if hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
                if isinstance(slice_node.value, ast.Constant):
                    return slice_node.value.value
            return None

    eof_guard = EngineOwnedFieldsGuard(
        _eof_forbidden_imports, _eof_forbidden_columns, _eof_forbidden_callables
    )
    eof_guard.visit(tree)

    eof_violations = []
    if eof_guard.violations_assignments:
        eof_violations.append(
            f"forbidden df column writes: {sorted(set(eof_guard.violations_assignments))}"
        )
    if eof_guard.violations_calls:
        eof_violations.append(
            f"forbidden function calls: {sorted(set(eof_guard.violations_calls))}"
        )
    if eof_guard.violations_references:
        refs = sorted({
            f"{name}@L{lineno}" for name, lineno in eof_guard.violations_references
        })
        eof_violations.append(
            f"engine-owned symbol referenced after import "
            f"(only ctx.require() permitted): {refs}"
        )

    # Consumer-filter contract.
    declared_imports_by_field = {}
    for mod in eof_guard.imports_declared:
        field = _eof_import_to_field.get(mod)
        if field:
            declared_imports_by_field.setdefault(field, []).append(mod)

    for field, mods in declared_imports_by_field.items():
        consumer_filters = ENGINE_OWNED_FIELDS[field]["consumer_filters"]
        if not consumer_filters:
            eof_violations.append(
                f"engine-owned module(s) {sorted(mods)} imported but field "
                f"'{field}' has no registered consumer filter; import not permitted"
            )
            continue
        sig = visitor.signature_dict or {}
        satisfied_by = None
        for cf_name in consumer_filters:
            block = sig.get(cf_name)
            if is_behavioral_filter_config(block):
                satisfied_by = cf_name
                break
        if satisfied_by is None:
            eof_violations.append(
                f"engine-owned module(s) {sorted(mods)} imported without a "
                f"behavioral consumer filter; required one of "
                f"{sorted(consumer_filters)} with enabled=True and at least "
                f"one non-'enabled' key in STRATEGY_SIGNATURE"
            )

    if eof_violations:
        raise ValueError(
            f"ENGINE_OWNED_FIELDS: Strategy violates engine-owned field boundary. "
            f"These fields are computed by apply_regime_model() after "
            f"prepare_indicators() -- re-implementing them causes silent drift "
            f"between gate logic and trade record labels. "
            f"Access exclusively via ctx.require('<field>'). "
            f"Violations: {'; '.join(eof_violations)}"
        )

    print("[SEMANTIC] Engine-Owned Fields Guard: PASSED")

    # 5.5. Forbidden Terms Guard (Stage-0 Inline Indicator Ban)
    # ------------------------------------------------------------------
    # Detect inline indicator patterns that must live in repository indicators.
    # Runs as source-text scan after stripping comments and docstrings.
    #
    # Layer 1 (Immediate): keyword patterns for common inline computation
    # Layer 2 (Medium):    external data loading detection
    # Layer 3 (Long-term): AST analysis of prepare_indicators() body
    FORBIDDEN_TERMS = [
        # Original terms
        "rolling(",
        "high_low",
        "high_close",
        # Rolling computation bypasses (cumsum trick, numpy equivalents)
        "np.cumsum(",
        "np.cumsum(np",
        "cumsum(",
        # Inline statistical computation
        "np.convolve(",
        "np.correlate(",
        # External data loading (indicators load data, strategies must not)
        "pd.read_csv(",
        "pd.read_excel(",
        "pd.read_parquet(",
        ".read_csv(",
        "open(",
    ]

    _scan_source = re.sub(r'""".*?"""|\'\'\'.*?\'\'\'', '', source, flags=re.DOTALL)
    _scan_source = re.sub(r'#[^\n]*', '', _scan_source)

    found_forbidden = [term for term in FORBIDDEN_TERMS if term in _scan_source]
    if found_forbidden:
        raise ValueError(
            f"FORBIDDEN_TERMS: Strategy contains inline indicator logic or "
            f"external data loading: {found_forbidden}. "
            f"Move computations into a repository indicator under indicators/. "
            f"Strategies must not load external data — use an indicator import."
        )

    print("[SEMANTIC] Forbidden Terms Guard: PASSED")

    # 5.7. External Data Loading Guard (Medium-term — AST-based)
    # ------------------------------------------------------------------
    # Detects pd.read_csv / pd.read_excel / pd.read_parquet / open() calls
    # anywhere in strategy code via AST. More robust than text scan —
    # catches aliased calls like `pandas.read_csv(...)` or `csv_loader(path)`.
    class ExternalDataGuard(ast.NodeVisitor):
        """Detect external file I/O calls in strategy code."""
        FORBIDDEN_ATTRS = {
            "read_csv", "read_excel", "read_parquet", "read_json",
            "read_feather", "read_hdf",
        }

        def __init__(self):
            self.violations = []

        def visit_Call(self, node):
            # pd.read_csv(...) / pandas.read_csv(...)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in self.FORBIDDEN_ATTRS:
                    self.violations.append(
                        f"{node.func.attr}() at line {node.lineno}"
                    )
            # Built-in open(...)
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                self.violations.append(f"open() at line {node.lineno}")
            self.generic_visit(node)

    ext_guard = ExternalDataGuard()
    ext_guard.visit(tree)

    if ext_guard.violations:
        raise ValueError(
            f"EXTERNAL_DATA_LOAD: Strategy loads external data directly. "
            f"Strategies must not perform file I/O — external data loading "
            f"belongs in a repository indicator under indicators/. "
            f"Violations: {'; '.join(ext_guard.violations)}"
        )

    print("[SEMANTIC] External Data Loading Guard: PASSED")

    # 5.8. Inline Indicator Detection (Long-term — AST body analysis)
    # ------------------------------------------------------------------
    # Walks the body of prepare_indicators() and detects patterns that
    # indicate inline indicator computation:
    #   - df column assignments using numpy array math (np.where, np.sqrt, etc.)
    #     beyond simple shift/rename operations
    #   - Creation of intermediate DataFrames or Series from raw OHLCV
    #   - Statistical aggregation functions (mean, std, var, sum, corr, cov)
    #     applied to df columns
    #
    # Allowed in prepare_indicators():
    #   - Importing and calling indicator functions from indicators/
    #   - Simple bar-shift references: df['col'].shift(N)
    #   - Column renames / copies for signal naming
    #
    # This is a heuristic guard — it flags suspicious patterns for review,
    # not a perfect classifier. False positives are acceptable (fail-safe).
    class InlineIndicatorDetector(ast.NodeVisitor):
        """Detect inline indicator computation in prepare_indicators()."""
        # numpy/pandas calls that indicate derived computation
        SUSPICIOUS_NP_CALLS = {
            "where", "cumsum", "cumprod", "diff", "gradient",
            "convolve", "correlate", "sqrt", "log", "exp",
            "maximum", "minimum", "percentile", "quantile",
        }
        SUSPICIOUS_PD_METHODS = {
            "rolling", "expanding", "ewm",
            "cumsum", "cumprod", "cummax", "cummin",
            "pct_change", "corr", "cov",
            "mean", "std", "var", "sum", "median",
            "groupby",
        }
        # Allowed simple operations — not indicators
        ALLOWED_METHODS = {"shift", "fillna", "astype", "copy", "rename", "map"}

        def __init__(self):
            self.violations = []
            self._in_prepare_indicators = False

        def visit_FunctionDef(self, node):
            if node.name == "prepare_indicators":
                self._in_prepare_indicators = True
                self.generic_visit(node)
                self._in_prepare_indicators = False
            else:
                self.generic_visit(node)

        def visit_Call(self, node):
            if not self._in_prepare_indicators:
                self.generic_visit(node)
                return

            # np.where(...), np.cumsum(...), etc.
            if isinstance(node.func, ast.Attribute):
                if (isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "np"
                        and node.func.attr in self.SUSPICIOUS_NP_CALLS):
                    self.violations.append(
                        f"np.{node.func.attr}() at line {node.lineno}"
                    )

                # df['col'].rolling(...), series.mean(), etc.
                if node.func.attr in self.SUSPICIOUS_PD_METHODS:
                    self.violations.append(
                        f".{node.func.attr}() at line {node.lineno}"
                    )

            self.generic_visit(node)

    inline_det = InlineIndicatorDetector()
    inline_det.visit(tree)

    if inline_det.violations:
        raise ValueError(
            f"INLINE_INDICATOR: prepare_indicators() contains inline "
            f"computation that should be in a repository indicator. "
            f"Strategies must import indicator functions from indicators/; "
            f"prepare_indicators() should only call imported indicators and "
            f"perform simple column shifts/renames. "
            f"Suspicious patterns: {'; '.join(inline_det.violations)}"
        )

    print("[SEMANTIC] Inline Indicator Detection: PASSED")

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
