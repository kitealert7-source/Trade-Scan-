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
        self.filter_counts = {}  # per-filter-type rejection counter

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
                    self.filter_counts["market_regime_filter"] = self.filter_counts.get("market_regime_filter", 0) + 1
                    self.filtered_bars += 1
                    return False

        # Regime age exclusion gate: blocks trades entering during excluded
        # regime age range. Supports two modes:
        #   1. allowed_values: allowlist (takes priority if present)
        #   2. exclude_min / exclude_max: contiguous exclusion range (legacy)
        raf = self.signature.get("regime_age_filter", {})
        if raf.get("enabled", False):
            # One-shot telemetry: log mode on first activation of the filter.
            if not getattr(self, "_raf_logged", False):
                print(f"[REGIME_FILTER] active | mode={raf.get('mode', 'signal')} | "
                      f"allowed={raf.get('allowed_values')} | "
                      f"exclude=[{raf.get('exclude_min')},{raf.get('exclude_max')}]")
                self._raf_logged = True
            # v1.5.5: mode selects which regime_age view the filter operates on.
            #   "signal" (default): current bar's regime_age — the state the
            #     strategy saw at decision time. Backward-compatible behavior.
            #   "fill": next-bar regime_age (signal-row-anchored, from
            #     regime_age.shift(-1)) — the state at which the trade will
            #     actually fill under next_bar_open.
            # Absence defaults to "signal". No inference; anything else is a
            # governance abort — callers must be explicit.
            raf_mode = raf.get("mode", "signal")
            if raf_mode not in ("signal", "fill"):
                raise RuntimeError(
                    f"ABORT_GOVERNANCE: regime_age_filter.mode must be "
                    f"'signal' or 'fill', got '{raf_mode}'."
                )
            age_key = "regime_age_signal" if raf_mode == "signal" else "regime_age_fill"
            # Prefer .get() over .require(): NaN at this bar is a legitimate
            # data state (last bar of dataset has regime_age_fill == NaN since
            # it's shift(-1) — the signal there could not possibly fill under
            # next_bar_open). Distinguish "column not in ctx at all" (hard
            # error, v1.5.5+ contract violation) from "value is NaN at this
            # bar" (graceful rejection under fill-mode, fall-through under
            # signal-mode for legacy compat).
            actual_age = ctx.get(age_key)
            col_present = hasattr(ctx, "_ns") and (
                age_key in ("regime_age_signal", "regime_age_fill")
            )
            if actual_age is None:
                # Check whether the underlying dataframe even carries the column.
                row_obj = getattr(getattr(ctx, "_ns", None), "row", None)
                has_col = hasattr(row_obj, "index") and age_key in row_obj.index
                if not has_col:
                    if raf_mode == "signal":
                        # Legacy pre-v1.5.5: fall through to flat regime_age.
                        actual_age = ctx.get("regime_age")
                    else:
                        raise RuntimeError(
                            "regime_age_filter.mode='fill' requires engine "
                            "v1.5.5+ (regime_age_fill column missing from ctx)."
                        )
                # else: column present but value is NaN at this bar.
                # Under fill-mode, NaN means unknowable fill age → reject
                # (signal cannot be validated against the fill-age gate).
                # Under signal-mode, NaN preserves legacy behavior (pass).
                elif raf_mode == "fill":
                    self.filter_counts["regime_age_filter"] = self.filter_counts.get("regime_age_filter", 0) + 1
                    self.filtered_bars += 1
                    return False

            allowed = raf.get("allowed_values")
            if allowed is not None and (raf.get("exclude_min") is not None or raf.get("exclude_max") is not None):
                raise RuntimeError(
                    "ABORT_GOVERNANCE: regime_age_filter has both 'allowed_values' and "
                    "'exclude_min'/'exclude_max'. Use one mode, not both."
                )
            if allowed is not None:
                if actual_age is None or actual_age not in allowed:
                    self.filter_counts["regime_age_filter"] = self.filter_counts.get("regime_age_filter", 0) + 1
                    self.filtered_bars += 1
                    return False
            else:
                exclude_min = raf.get("exclude_min")
                exclude_max = raf.get("exclude_max")
                if exclude_min is not None and exclude_max is not None:
                    if actual_age is not None and exclude_min <= actual_age <= exclude_max:
                        self.filter_counts["regime_age_filter"] = self.filter_counts.get("regime_age_filter", 0) + 1
                        self.filtered_bars += 1
                        return False

        # Session exclusion gate: blocks trades during excluded UTC hours.
        # bar_hour is derived from (in order): ctx.bar_hour column → ctx.row.name.hour
        # (DatetimeIndex fallback). The fallback eliminates the INFRA-NEWS-001 silent-
        # zero-trades trap where a strategy with session_filter enabled but no
        # df["bar_hour"] populated in prepare_indicators() would reject every bar.
        sf = self.signature.get("session_filter", {})
        if sf.get("enabled", False):
            exclude_hours = sf.get("exclude_hours_utc", [])
            if exclude_hours:
                try:
                    bar_hour = ctx.require("bar_hour")
                except Exception:
                    bar_hour = None
                # Fallback: derive from row index timestamp when column absent.
                if bar_hour is None:
                    try:
                        row = getattr(ctx, "row", None)
                        if row is not None and hasattr(row, "name") and hasattr(row.name, "hour"):
                            bar_hour = int(row.name.hour)
                    except Exception:
                        bar_hour = None
                if bar_hour is None:
                    self.filter_counts["session_filter"] = self.filter_counts.get("session_filter", 0) + 1
                    self.filtered_bars += 1
                    return False
                if bar_hour in exclude_hours:
                    self.filter_counts["session_filter"] = self.filter_counts.get("session_filter", 0) + 1
                    self.filtered_bars += 1
                    return False

        for filter_name, cfg in self.signature.items():
            if not isinstance(cfg, dict):
                continue

            if filter_name in ("market_regime_filter", "regime_age_filter", "session_filter"):
                continue  # Already handled above — skip in generic loop

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
                            self.filter_counts["trend_filter"] = self.filter_counts.get("trend_filter", 0) + 1
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
                self.filter_counts[filter_name] = self.filter_counts.get(filter_name, 0) + 1
                self.filtered_bars += 1
                return False

            if expected is not None and not self._evaluate_condition(actual, expected, operator):
                self.filter_counts[filter_name] = self.filter_counts.get(filter_name, 0) + 1
                self.filtered_bars += 1
                return False

            # Secondary: exclude_regime — explicitly reject a specific regime value.
            # Supported on trend_filter only. Evaluated only if primary condition passes.
            # Note: exclude_regime also fires when required_regime is absent (expected=None),
            # acting as a standalone exclusion gate.
            if filter_name == "trend_filter":
                exclude_val = cfg.get("exclude_regime")
                if exclude_val is not None and actual == exclude_val:
                    self.filter_counts["trend_filter"] = self.filter_counts.get("trend_filter", 0) + 1
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

