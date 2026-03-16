
import yaml
import re
import os
import ast
import operator as op
from pathlib import Path
from typing import List, Dict, Union, Any, cast

# Authoritative path to the registry
REGISTRY_PATH = Path(__file__).parent.parent / "indicators" / "INDICATOR_REGISTRY.yaml"

class RegistryFormulaError(Exception):
    """Raised when a registry formula is invalid or contains unknown variables."""
    pass

# Supported operators for safe evaluation
BINARY_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
}

UNARY_OPERATORS = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}

# Global cache to avoid repeated file reads
_REGISTRY_CACHE = None

def resolve_strategy_warmup(strategy_indicators: List[Dict[str, Union[str, dict]]]) -> int:
    """
    Resolve the maximum required warm-up bars for a set of strategy indicators.
    """
    global _REGISTRY_CACHE
    debug_mode = os.environ.get("ENGINE_DEBUG_WARMUP") == "1"
    
    if _REGISTRY_CACHE is None:
        if not REGISTRY_PATH.exists():
            if debug_mode: print(f"[DEBUG] Registry missing at {REGISTRY_PATH}, falling back to 250")
            return 250
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            _REGISTRY_CACHE = yaml.safe_load(f)

    registry = cast(dict, _REGISTRY_CACHE)
    if not isinstance(registry, dict):
        return 250

    indicator_map = registry.get("indicators", {})
    max_warmup = 0
    
    for item in strategy_indicators:
        name = str(item.get("name", "Unknown"))
        params = item.get("params", {})
        if not isinstance(params, dict):
            params = {}
        
        entry = indicator_map.get(name)
        if not entry or not isinstance(entry, dict):
            if debug_mode: print(f"[DEBUG] Indicator '{name}' not found in registry")
            continue
            
        # 1. Merge default parameters
        defaults = entry.get("default_parameters", {})
        if not isinstance(defaults, dict):
            defaults = {}
            
        resolved_params = {**defaults, **params}
        
        warmup_formula = entry.get("warmup", 0)
        
        # 2. Resolve formula
        try:
            resolved_val = _safe_eval_formula(warmup_formula, resolved_params, name)
            if debug_mode:
                # Filter to only show parameters actually used in the formula for cleaner logs
                param_str = " ".join([f"{k}={v}" for k, v in resolved_params.items()])
                print(f"[{name}] {param_str} → warmup={int(resolved_val)}")
            max_warmup = max(max_warmup, resolved_val)
        except RegistryFormulaError as e:
            if debug_mode: print(f"[DEBUG] ERROR resolving '{name}': {str(e)}")
            raise

    return int(max_warmup)

def _safe_eval_formula(formula: Union[str, int, float], params: dict, indicator_name: str) -> float:
    """
    Safe evaluation of arithmetic formulas using AST.
    Only allows basic operators and parameters.
    """
    if isinstance(formula, (int, float)):
        return float(formula)
        
    if not isinstance(formula, str):
        return 0.0

    try:
        node = ast.parse(formula, mode='eval').body
        return _eval_node(node, params, formula, indicator_name)
    except Exception as e:
        if isinstance(e, RegistryFormulaError):
            raise
        raise RegistryFormulaError(f"Invalid formula syntax in '{indicator_name}': {formula}")

def _eval_node(node: ast.AST, params: dict, original_formula: str, indicator_name: str) -> float:
    if isinstance(node, ast.Constant): # <3.8 used ast.Num
        return float(node.value)
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in BINARY_OPERATORS:
            raise RegistryFormulaError(f"Binary operator {op_type} not allowed in formula: {original_formula}")
        # Use cast to satisfy linter type checking for dynamic operator lookup
        binary_op = cast(Any, BINARY_OPERATORS)[op_type] 
        return float(binary_op(
            _eval_node(node.left, params, original_formula, indicator_name),
            _eval_node(node.right, params, original_formula, indicator_name)
        ))
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in UNARY_OPERATORS:
            raise RegistryFormulaError(f"Unary operator {op_type} not allowed in formula: {original_formula}")
        unary_op = cast(Any, UNARY_OPERATORS)[op_type]
        return float(unary_op(
            _eval_node(node.operand, params, original_formula, indicator_name)
        ))
    elif isinstance(node, ast.Name):
        if node.id in params:
            val = params[node.id]
            if not isinstance(val, (int, float)):
                raise RegistryFormulaError(f"Parameter '{node.id}' must be numeric in {indicator_name}")
            return float(val)
        else:
            raise RegistryFormulaError(f"Formula variable '{node.id}' not present in resolved_params for {indicator_name}")
    else:
        raise RegistryFormulaError(f"Unsupported node type {type(node)} in formula: {original_formula}")

def extract_indicators_from_strategy(strategy) -> List[dict]:
    """
    Helper to extract indicator list and params from a Strategy instance.
    Prefers strategy.indicator_config() hook if available.
    """
    if hasattr(strategy, "indicator_config") and callable(strategy.indicator_config):
        return strategy.indicator_config()

    indicators = []
    sig = getattr(strategy, "STRATEGY_SIGNATURE", {})
    
    # 1. Generic indicator list
    raw_list = sig.get("indicators", [])
    for item in raw_list:
        if isinstance(item, str):
            name = item.split(".")[-1]
            indicators.append({"name": name, "params": {}})
            
    # 2. Extract specific filter parameters (if logic-defined)
    for filter_key in ["trend_filter", "volatility_filter"]:
        cfg = sig.get(filter_key, {})
        if cfg.get("enabled", False):
            if filter_key == "volatility_filter":
                # The engine currently uses 'atr_period' for its internal filters
                p = cfg.get("atr_period")
                if p:
                    indicators.append({"name": "atr_percentile", "params": {"window": p}})
                    indicators.append({"name": "volatility_regime", "params": {"window": p}})
                
    return indicators
