# Directive Schema Unification — Implementation Plan

Eliminate the provisioner/validator architectural inconsistency with a single source of truth for signature construction.

## Proposed Changes

### Step 1 — Unify Signature Authority

**Goal**: Validator mirrors provisioner logic. Single exclusion list. No hardcoded key names.

#### [MODIFY] [semantic_validator.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/semantic_validator.py)

Replace lines 82–97 (hardcoded signature extraction):

```diff
     # BUILD EXPECTED SIGNATURE (Must match provisioner exactly)
-    vol_filter = get_key_ci(d_conf, "volatility_filter") or get_key_ci(test_block, "volatility_filter") or {}
-    range_def = get_key_ci(d_conf, "range_definition") or get_key_ci(test_block, "range_definition") or {}
-    trade_mgmt = get_key_ci(d_conf, "trade_management") or get_key_ci(test_block, "trade_management") or {}
-    exec_rules = get_key_ci(d_conf, "execution_rules") or get_key_ci(test_block, "execution_rules") or {}
-    order_placement = get_key_ci(d_conf, "order_placement") or get_key_ci(test_block, "order_placement") or {}
-
-    expected_signature = {
-        "signature_version": SIGNATURE_SCHEMA_VERSION,
-        "indicators": declared_indicators,
-        "volatility_filter": vol_filter,
-        "range_definition": range_def,
-        "trade_management": trade_mgmt,
-        "execution_rules": exec_rules,
-        "order_placement": order_placement
-    }
+    # UNIFIED: Use same exclusion-based logic as strategy_provisioner.py
+    from tools.directive_schema import NON_SIGNATURE_KEYS
+    expected_signature = {"signature_version": SIGNATURE_SCHEMA_VERSION}
+    for key, value in d_conf.items():
+        if key.lower() not in NON_SIGNATURE_KEYS:
+            expected_signature[key] = value
```

#### [NEW] [directive_schema.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/directive_schema.py)

Single source of truth shared by provisioner and validator:

```python
"""
directive_schema.py — Single Source of Truth for Directive YAML Contract
Authority: SOP_TESTING (Stage-0 Governance)

NO DUPLICATE DEFINITIONS. Import this everywhere.
"""

# Keys excluded from signature construction.
# Everything NOT in this set becomes part of the strategy signature.
NON_SIGNATURE_KEYS = frozenset({
    "test", "backtest", "description", "notes", "symbols",
    "name", "family", "strategy", "broker", "timeframe",
    "session_time_reference", "start_date", "end_date",
    "research_mode", "tuning_allowed", "parameter_mutation",
})

# Minimal required signature keys (hard abort if missing)
REQUIRED_SIGNATURE_KEYS = frozenset({"indicators", "execution_rules"})

# Default-injected blocks (injected into signature if absent from directive)
SIGNATURE_DEFAULTS = {
    "order_placement": {"type": "market", "execution_timing": "next_bar_open"},
}

SIGNATURE_SCHEMA_VERSION = 1
```

#### [MODIFY] [strategy_provisioner.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/strategy_provisioner.py)

Replace inline `NON_SIGNATURE_KEYS` and `REQUIRED_KEYS` with shared import:

```diff
-SIGNATURE_SCHEMA_VERSION = 1
+from tools.directive_schema import NON_SIGNATURE_KEYS, REQUIRED_SIGNATURE_KEYS, SIGNATURE_DEFAULTS, SIGNATURE_SCHEMA_VERSION

 def provision_strategy(directive_path: str) -> bool:
     ...
-        NON_SIGNATURE_KEYS = {k.lower() for k in {
-            "test", "backtest", "description", "notes", "symbols",
-            "name", "family", "strategy", "broker", "timeframe",
-            "session_time_reference", "start_date", "end_date",
-            "research_mode", "tuning_allowed", "parameter_mutation",
-        }}
         signature = {}
         for key, value in d_conf.items():
             if key.lower() not in NON_SIGNATURE_KEYS:
                 signature[key] = value
         signature["signature_version"] = SIGNATURE_SCHEMA_VERSION
+
+        # Default-inject missing optional blocks
+        for key, default_val in SIGNATURE_DEFAULTS.items():
+            if key not in signature:
+                signature[key] = default_val
+
-        REQUIRED_KEYS = {"indicators", "execution_rules", "order_placement"}
-        missing = REQUIRED_KEYS - set(signature.keys())
+        missing = REQUIRED_SIGNATURE_KEYS - set(signature.keys())
```

---

### Step 2 — Remove Hardcoded Key Expectations

Handled by Step 1. The validator no longer hardcodes `volatility_filter`, `range_definition`, or `trade_management`. If absent from the directive, they simply won't be in the signature — both provisioner and validator will agree.

---

### Step 3 — Define Minimal Stable YAML Contract

#### [NEW] [DIRECTIVE_CONTRACT.md](file:///c:/Users/faraw/Documents/Trade_Scan/governance/SOP/DIRECTIVE_CONTRACT.md)

Formal documentation of the YAML contract. This is the human-readable reference for directive authors.

Contents:

- Required `test:` envelope with identity fields
- Required root-level keys: `symbols`, `indicators`, `execution_rules`
- Optional root-level keys: `order_placement`, `volatility_filter`, `range_definition`, `trade_management`
- Rule: anything not in `NON_SIGNATURE_KEYS` enters the signature — no exceptions

---

### Step 4 — Remove Flat YAML Compatibility

#### [MODIFY] [pipeline_utils.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/pipeline_utils.py)

Add enforcement in `parse_directive()` after line 102:

```diff
     data = _stringify_dates(data)

+    # STRICT: test: wrapper is mandatory
+    if "test" not in data:
+        raise ValueError(
+            "INVALID DIRECTIVE STRUCTURE: 'test:' wrapper block is required. "
+            "Flat directives are no longer supported."
+        )
+
     # Mirror test: sub-keys into root for backward-compatible downstream access.
```

> [!WARNING]
> **Migration impact**: `SPX02_MR.txt` (now in `completed/`) used flat YAML.
> No currently active directives are affected. Any future directives must use `test:` wrapper.

---

### Step 5 — Make `order_placement` Default-Injectable

Handled by Step 1 via `SIGNATURE_DEFAULTS` in `directive_schema.py`. If `order_placement` is missing from the directive, it is injected as `{type: market, execution_timing: next_bar_open}` into the signature by both provisioner and validator.

`REQUIRED_SIGNATURE_KEYS` is reduced from `{indicators, execution_rules, order_placement}` to `{indicators, execution_rules}`.

---

### Step 6 — Symbol Parsing Refactor (Separate Track)

#### [MODIFY] [run_stage1.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/run_stage1.py)

Replace heuristic-based `parse_symbol_properties()` with broker-spec-driven lookup:

```diff
 def parse_symbol_properties(symbol: str):
-    s = symbol.upper()
-    if len(s) == 6:
-        return s[:3], s[3:]
-    elif s.endswith("USD"):
-        return s[:-3], "USD"
-    else:
-        return s, None
+    """
+    Parse symbol into base and quote currencies using broker spec metadata.
+    Falls back to heuristic only for symbols without a broker spec.
+    """
+    s = symbol.upper()
+    # Try broker spec first (authoritative)
+    broker_spec_path = PROJECT_ROOT / "data_access" / "broker_specs" / BROKER / f"{s}.yaml"
+    if broker_spec_path.exists():
+        import yaml
+        with open(broker_spec_path, "r") as f:
+            spec = yaml.safe_load(f)
+        price_unit = spec.get("calibration", {}).get("price_unit", "")
+        if price_unit == "INDEX_POINT":
+            return s, None  # Non-FX: PnL is already in USD
+    # Heuristic fallback
+    if len(s) == 6 and s.isalpha():
+        return s[:3], s[3:]
+    elif s.endswith("USD"):
+        return s[:-3], "USD"
+    else:
+        return s, None
```

This uses the existing `price_unit: INDEX_POINT` field already present in broker specs like `SPX500.yaml`, `NAS100.yaml`, `GER40.yaml` etc. No new metadata files needed.

---

## Verification Plan

### Automated Tests

After all changes:

1. **Signature Parity**: Run provisioner + validator on every directive in `completed/` and verify no signature mismatch:

   ```
   python -c "from tools.semantic_validator import validate_semantic_signature; ..."
   ```

2. **Flat YAML Rejection**: Confirm `parse_directive()` raises on flat YAML format.

3. **Default Injection**: Confirm a directive without `order_placement` still provisions and validates.

4. **Symbol Parsing**: Confirm `SPX500`, `NAS100`, `GER40` return `(symbol, None)` and `EURUSD`, `XAUUSD` return correct FX pairs.

### Manual Verification

- Re-run `python tools/run_pipeline.py --all --provision-only` with a test directive (no `order_placement`, no `volatility_filter`) to confirm clean pass.
