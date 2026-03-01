import hashlib
import json

class FilterStack:
    """
    Operator-Aware Filter Stack (Phase 1 Hardened).
    
    Supports operators: eq (default), gte, lte, gt, lt, in
    Backward compatible — signatures without 'operator' key default to 'eq'.
    """
    
    SUPPORTED_OPERATORS = {"eq", "gte", "lte", "gt", "lt", "in"}
    AUTHORITATIVE_FIELDS = {
        "volatility_regime",
        "trend_regime",
        "trend_label",
        "trend_score",
        "atr"
    }
    
    def __init__(self, signature: dict):
        self.signature = signature or {}
        self.filtered_bars = 0
        
        # Phase 1: Signature Fingerprinting
        self._initial_sig_str = json.dumps(self.signature, sort_keys=True)
        self.signature_hash = hashlib.sha256(self._initial_sig_str.encode('utf-8')).hexdigest()

    def allow_trade(self, ctx) -> bool:
        # Phase 1: Engine Protocol Enforcement
        if not getattr(ctx, '_ENGINE_PROTOCOL', False):
            raise TypeError(
                "ABORT_GOVERNANCE: FilterStack.allow_trade() requires a ContextView object. "
                "Raw dicts or SimpleNamespace objects are no longer permitted."
            )
            
        # Runtime mutation check
        current_sig_str = json.dumps(self.signature, sort_keys=True)
        if current_sig_str != self._initial_sig_str:
            raise RuntimeError("ABORT_GOVERNANCE: Strategy signature mutated during runtime.")
            
        for filter_name, cfg in self.signature.items():
            if not isinstance(cfg, dict):
                continue

            if not cfg.get("enabled", False):
                continue
                
            if filter_name == "trend_filter":
                field = "trend_regime"
                expected = cfg.get("required_regime")
                operator = cfg.get("operator", "eq")
                
            elif filter_name == "volatility_filter":
                field = "volatility_regime"
                expected = cfg.get("required_regime")
                operator = cfg.get("operator", "eq")
                
            else:
                field = cfg.get("field")
                if not field:
                    raise RuntimeError(f"ABORT_GOVERNANCE: Generic filter '{filter_name}' missing required 'field'.")
                    
                if field in self.AUTHORITATIVE_FIELDS:
                    raise RuntimeError(f"ABORT_GOVERNANCE: Generic filter '{filter_name}' cannot reference authoritative field '{field}'.")
                    
                if "value" not in cfg:
                    raise RuntimeError(f"ABORT_GOVERNANCE: Generic filter '{filter_name}' missing required 'value'.")
                expected = cfg.get("value")
                operator = cfg.get("operator", "eq")

            if operator not in self.SUPPORTED_OPERATORS:
                raise RuntimeError(
                    f"ABORT_GOVERNANCE: Unknown filter operator '{operator}'. "
                    f"Supported: {self.SUPPORTED_OPERATORS}"
                )

            actual = ctx.require(field)
            
            if not self._evaluate_condition(actual, expected, operator):
                self.filtered_bars += 1
                return False

        return True

    def allow_direction(self, intended_direction: int) -> bool:
        """
        Phase 2: Directional Gating.
        Verifies if the intended trade direction is permitted by the filters.
        Assumes `allow_trade(ctx)` has already permitted the bar itself.
        """
        for filter_key in ["volatility_filter", "trend_filter"]:
            cfg = self.signature.get(filter_key, {})
            if cfg.get("enabled", False):
                allowed = cfg.get("allowed_directions")
                # If specified, direction must be in the list
                if allowed is not None and intended_direction not in allowed:
                    return False
        return True

    def _evaluate_condition(self, actual_value, required_value, operator: str = "eq") -> bool:
        """
        Evaluate a filter condition using the specified operator.
        
        Args:
            actual_value: The value from the data row (e.g. trend_regime)
            required_value: The threshold/target from the signature config
            operator: One of eq, gte, lte, gt, lt, in
            
        Returns:
            True if condition is met, False otherwise.
        """
        if actual_value is None:
            return False
            
        if operator == "eq":
            return actual_value == required_value
        elif operator == "gte":
            return actual_value >= required_value
        elif operator == "lte":
            return actual_value <= required_value
        elif operator == "gt":
            return actual_value > required_value
        elif operator == "lt":
            return actual_value < required_value
        elif operator == "in":
            if isinstance(required_value, (list, tuple, set)):
                return actual_value in required_value
            return actual_value == required_value
        else:
            raise RuntimeError(
                f"ABORT_GOVERNANCE: Unknown filter operator '{operator}'. "
                f"Supported: {self.SUPPORTED_OPERATORS}"
            )

