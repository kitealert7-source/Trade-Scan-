from __future__ import annotations

import hashlib
import json

from engines.protocols import ContextViewProtocol

__all__ = ["FilterStack"]


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
        import copy
        self.signature = copy.deepcopy(signature) if signature else {}
        self.filtered_bars = 0

        # Phase 1: Signature Fingerprinting
        self._initial_sig_str = json.dumps(self.signature, sort_keys=True)
        self.signature_hash = hashlib.sha256(self._initial_sig_str.encode('utf-8')).hexdigest()

        # Direction-gate cache: stores regime values from the most recent
        # allow_trade(ctx) call. Used by allow_direction() when direction_gate is
        # enabled. The engine always calls allow_trade() before allow_direction()
        # for any given signal, so the cached value is always from the signal bar.
        self._cached_vol_regime   = None
        self._cached_trend_regime = None

    def allow_trade(self, ctx: ContextViewProtocol) -> bool:
        # Phase 1: Engine Protocol Enforcement (type-system backed)
        if not isinstance(ctx, ContextViewProtocol):
            raise TypeError(
                "ABORT_GOVERNANCE: FilterStack.allow_trade() requires a ContextViewProtocol-"
                "compatible object (must implement get() and require()). "
                "Raw dicts or SimpleNamespace objects are not permitted."
            )
            
        # Runtime mutation check
        current_sig_str = json.dumps(self.signature, sort_keys=True)
        if current_sig_str != self._initial_sig_str:
            raise RuntimeError("ABORT_GOVERNANCE: Strategy signature mutated during runtime.")

        # Cache regime values for direction_gate mode. Runs before the filter loop so
        # values are always available in allow_direction() even if allow_trade()
        # returns False early. try/except handles strategies with no regime indicators.
        try:
            self._cached_vol_regime = ctx.require('volatility_regime')
        except Exception:
            self._cached_vol_regime = None
        try:
            self._cached_trend_regime = ctx.require('trend_regime')
        except Exception:
            self._cached_trend_regime = None

        # Hard pre-entry gate: market_regime_filter
        # Blocks trade if current bar's market_regime is in the exclude list.
        # No fallback — rejection is absolute.
        mrf = self.signature.get("market_regime_filter", {})
        if mrf.get("enabled", False):
            exclude_list = mrf.get("exclude", [])
            if exclude_list:
                try:
                    actual_regime = ctx.require("market_regime")
                except Exception:
                    actual_regime = None
                if actual_regime in exclude_list:
                    self.filtered_bars += 1
                    return False

        # Regime age exclusion gate: blocks trades entering during excluded
        # regime age range. Uses exclude_min / exclude_max (inclusive bounds).
        raf = self.signature.get("regime_age_filter", {})
        if raf.get("enabled", False):
            exclude_min = raf.get("exclude_min")
            exclude_max = raf.get("exclude_max")
            if exclude_min is not None and exclude_max is not None:
                try:
                    actual_age = ctx.require("regime_age")
                except Exception:
                    actual_age = None
                if actual_age is not None and exclude_min <= actual_age <= exclude_max:
                    self.filtered_bars += 1
                    return False

        for filter_name, cfg in self.signature.items():
            if not isinstance(cfg, dict):
                continue

            if filter_name in ("market_regime_filter", "regime_age_filter", "session_filter"):
                continue  # Already handled above or in strategy.check_entry() — skip in generic loop

            if not cfg.get("enabled", False):
                continue

            if filter_name == "trend_filter":
                # direction_gate mode: per-direction gating handled in allow_direction().
                # Bypass standard field check to avoid double-blocking.
                # But exclude_regime is a hard pre-entry gate — must still fire.
                if cfg.get("direction_gate"):
                    exclude_val = cfg.get("exclude_regime")
                    if exclude_val is not None:
                        try:
                            actual_trend = ctx.require("trend_regime")
                        except Exception:
                            actual_trend = None
                        if actual_trend is not None and actual_trend == exclude_val:
                            self.filtered_bars += 1
                            return False
                    continue
                field = "trend_regime"
                expected = cfg.get("required_regime")
                operator = cfg.get("operator", "eq")
                
            elif filter_name == "volatility_filter":
                # direction_gate mode: bar-level vol gating is bypassed entirely.
                # allow_direction() handles conditional direction blocking using the
                # cached vol_regime. Skipping here prevents double-blocking.
                if cfg.get("direction_gate"):
                    continue
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

            try:
                actual = ctx.require(field)
            except Exception:
                # Field unavailable (e.g. regime fields during dry-run validation
                # where HTF computation is skipped). Block the trade safely —
                # during real execution, authoritative fields are always populated.
                self.filtered_bars += 1
                return False

            if not self._evaluate_condition(actual, expected, operator):
                self.filtered_bars += 1
                return False

            # Secondary: exclude_regime — explicitly reject a specific regime value.
            # Supported on trend_filter only. Evaluated only if primary condition passes.
            if filter_name == "trend_filter":
                exclude_val = cfg.get("exclude_regime")
                if exclude_val is not None and actual == exclude_val:
                    self.filtered_bars += 1
                    return False

        return True

    def allow_direction(self, intended_direction: int) -> bool:
        """
        Phase 2: Directional Gating.
        Verifies if the intended trade direction is permitted by the filters.
        Assumes `allow_trade(ctx)` has already been called for the signal bar.

        direction_gate mode: when volatility_filter has direction_gate=True, the
        allowed direction is determined by the vol_regime cached during allow_trade().
        long_when / short_when sub-blocks define the vol condition per direction.
        """
        # --- Direction-conditional vol gating (direction_gate mode) ---
        vol_cfg = self.signature.get("volatility_filter", {})
        if vol_cfg.get("enabled") and vol_cfg.get("direction_gate"):
            vol = self._cached_vol_regime
            if vol is None:
                return False  # Safety: no cached regime → block
            gate_key = "long_when" if intended_direction > 0 else "short_when"
            gate = vol_cfg.get(gate_key)
            if not gate:
                return False  # No gate defined for this direction → block
            req = gate.get("required_regime")
            op = gate.get("operator", "eq")
            if not self._evaluate_condition(vol, req, op):
                return False

        # --- Direction-conditional trend gating (direction_gate mode) ---
        trend_cfg = self.signature.get("trend_filter", {})
        if trend_cfg.get("enabled") and trend_cfg.get("direction_gate"):
            trend = self._cached_trend_regime
            if trend is None:
                return False  # Safety: no cached regime → block
            gate_key = "long_when" if intended_direction > 0 else "short_when"
            gate = trend_cfg.get(gate_key)
            if not gate:
                return False  # No gate defined for this direction → block
            req = gate.get("required_regime")
            op = gate.get("operator", "eq")
            if not self._evaluate_condition(trend, req, op):
                return False

        # --- Static allowed_directions check (existing behaviour) ---
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

