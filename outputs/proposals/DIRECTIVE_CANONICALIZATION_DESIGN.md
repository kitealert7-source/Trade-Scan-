# Stage -0.25 Directive Canonicalization — Design Document v2.2 (Hardened)

> **Schema Policy: FREEZE (Option B)**
> This system enforces a single strict directive format.
> Legacy patterns are handled via an explicit, finite migration table — not a growing compatibility layer.

---

## 1. High-Level Architecture

```
Parse YAML → Build Canonical Tree → Type Check → Relocate → Leftovers → Sub-block Check → Serialize → Diff → Approval Gate
```

| Component | Role |
|---|---|
| `tools/canonical_schema.py` | Frozen schema definition + explicit migration table |
| `tools/canonicalizer.py` | Tree Rebuild engine + diff generator (~150 LOC) |
| `run_pipeline.py` | 10-line hook before Stage-0 |

---

## 2. Pipeline Insertion Point

```
Directive YAML loaded
    │
    ▼
★ Stage -0.25: Structural Canonicalization ★
    │
    ▼
Stage-0: Preflight (engine + tools integrity)
```

Inside `run_single_directive()`, immediately after `parse_directive(d_path)`.

---

## 3. Algorithm — Tree Rebuild Strategy

### Phase 1: Parse + Snapshot

```
original = yaml.safe_load(directive_file)
```

If `yaml.YAMLError` → **HARD FAIL** with line/column.

```
original_snapshot = deepcopy(original)  # BEFORE any mutation
```

> **Invariant:** `original_snapshot` is a frozen deep copy taken immediately after parse — before any `pop()`, relocation, or migration. All subsequent phases mutate `original` freely. Phase 7 serializes `original_snapshot` for diff comparison. If this deepcopy is omitted, diff correctness collapses.

### Phase 2: Unwrap Envelope (Identity-Only Guard)

> **Rule: `test:` block may ONLY contain identity keys.**
> If `test:` contains any canonical structural block (`indicators`, `execution_rules`, etc.), this is a **HARD FAIL** — not a migration.

```
if "test" in original and isinstance(original["test"], dict):
    envelope = original["test"]

    # Guard: test: must not contain structural blocks
    structural_leak = set(envelope.keys()) & STRUCTURAL_BLOCKS
    if structural_leak:
        HARD_FAIL(f"test: block contains structural keys: {structural_leak}. "
                  f"Move them to top-level. Do NOT nest structural blocks in test:.")

    # Extract identity keys, rebuild original with test: as identity-only
    canonical["test"] = envelope
    original = {k: v for k, v in original.items() if k != "test"}
```

Where:

```python
STRUCTURAL_BLOCKS = {"symbols", "indicators", "execution_rules",
                     "order_placement", "trade_management",
                     "range_definition", "exit_rules"}
```

This prevents the ambiguity of:

```yaml
test:
  indicators:     # ← HARD FAIL: structural block inside identity envelope
    - ...
indicators:       # ← which one wins?
  - ...
```

### Phase 3: Build Canonical Tree

Build a new empty `canonical = {}`. For each block defined in the frozen schema:

```
for block_name in CANONICAL_BLOCKS:
    if block_name in original:
        canonical[block_name] = original.pop(block_name)
    elif block_name in MIGRATION_TABLE:
        legacy_name = MIGRATION_TABLE[block_name]
        if legacy_name in original:
            canonical[block_name] = original.pop(legacy_name)
            log(f"MIGRATED: '{legacy_name}' → '{block_name}'")
    elif block_name in REQUIRED_BLOCKS:
        HARD_FAIL(f"Missing required block: '{block_name}'")
```

### Phase 3.5: Block Type Validation

Enforce expected types for each block. Prevents structural corruption (e.g., `symbols: {foo: bar}` instead of a list).

```
BLOCK_TYPES = {
    "test":             dict,
    "symbols":          list,
    "indicators":       list,
    "execution_rules":  dict,
    "trade_management": dict,
    "order_placement":  dict,
}

for block_name, block_data in canonical.items():
    expected_type = BLOCK_TYPES.get(block_name)
    if expected_type and not isinstance(block_data, expected_type):
        HARD_FAIL(f"INVALID_BLOCK_TYPE: '{block_name}' must be {expected_type.__name__}, "
                  f"got {type(block_data).__name__}")
```

### Phase 4: Relocate Known Misplacements (with Conflict Detection)

For each entry in the explicit `MISPLACEMENT_TABLE`:

```
MISPLACEMENT_TABLE = {
    "direction": ("root", "trade_management"),
    "entry_logic": ("root", "execution_rules"),
    "exit_logic": ("root", "execution_rules"),
}

for key, (illegal_parent, correct_parent) in MISPLACEMENT_TABLE.items():
    if key in original:  # still in leftovers = was at root
        # Conflict check: destination must not already contain this key
        if correct_parent in canonical and key in canonical[correct_parent]:
            HARD_FAIL(f"CONFLICTING_DEFINITION: '{key}' exists both at root "
                      f"and inside '{correct_parent}'. Cannot relocate. "
                      f"Human must resolve which definition is authoritative.")
        # Safe to relocate
        if correct_parent not in canonical:
            canonical[correct_parent] = {}
        canonical[correct_parent][key] = original.pop(key)
        log(f"RELOCATED: '{key}' from {illegal_parent} → {correct_parent}")
```

> **No silent overwrites.** If a key exists at both the illegal and correct positions, the system does not pick one — it HALTs.

### Phase 5: Leftover Check

```
if original has remaining keys (after all pops):
    HALT — "Unknown top-level keys detected: {remaining_keys}"
    Do NOT proceed. Do NOT guess.
```

### Phase 6: Nested Key Validation (Depth-2)

Validation runs at **two levels**: block children AND sub-block children.

**Level 1 — Block children:**

```
for block_name, block_data in canonical.items():
    if block_name in ALLOWED_NESTED_KEYS and isinstance(block_data, dict):
        unknown = set(block_data.keys()) - ALLOWED_NESTED_KEYS[block_name]
        if unknown:
            HALT — "Unknown keys in '{block_name}': {unknown}"
```

**Level 2 — Sub-block children:**

```
for block_name, block_data in canonical.items():
    if not isinstance(block_data, dict):
        continue
    for sub_key, sub_data in block_data.items():
        if isinstance(sub_data, dict) and sub_key in ALLOWED_SUB_KEYS:
            unknown = set(sub_data.keys()) - ALLOWED_SUB_KEYS[sub_key]
            if unknown:
                HALT — "Unknown keys in '{block_name}.{sub_key}': {unknown}"
```

### Phase 6.5: Required Sub-Block Enforcement

Enforce minimal structural completeness within required blocks. This is presence-only — no semantic validation.

```
REQUIRED_SUB_BLOCKS = {
    "execution_rules": {"entry_logic"},
}

for block_name, required_children in REQUIRED_SUB_BLOCKS.items():
    if block_name in canonical:
        missing = required_children - set(canonical[block_name].keys())
        if missing:
            HARD_FAIL(f"STRUCTURALLY_INCOMPLETE: '{block_name}' is missing "
                      f"required sub-block(s): {missing}")
```

> This does NOT enforce semantic correctness (e.g., does not check that `entry_logic.type` has a valid value). Only structural presence.

### Phase 7: Deterministic Serialize + Diff

Serialization uses **explicit block ordering**, not `sort_keys=True`. This ensures the canonical output is always in the same structural order regardless of how the original was written.

```
def serialize_canonical(canonical):
    """Deterministic serialization using CANONICAL_BLOCKS order."""
    ordered = {}
    for block_name in CANONICAL_BLOCKS:
        if block_name in canonical:
            block = canonical[block_name]
            if isinstance(block, dict) and block_name in CANONICAL_KEY_ORDER:
                block = order_dict(block, CANONICAL_KEY_ORDER[block_name])
            ordered[block_name] = block
    return yaml.dump(ordered, default_flow_style=False, sort_keys=False)
```

Where `CANONICAL_KEY_ORDER` defines the serialization order for nested keys:

```python
CANONICAL_KEY_ORDER = {
    "test": ["name", "family", "strategy", "version", "broker",
             "timeframe", "session_time_reference", "start_date", "end_date",
             "research_mode", "tuning_allowed", "parameter_mutation"],
    "execution_rules": ["pyramiding", "entry_when_flat_only", "reset_on_exit",
                        "cancel_opposite_on_fill", "entry_logic", "exit_logic",
                        "stop_loss", "trailing_stop", "take_profit"],
    "trade_management": ["direction", "direction_restriction", "mode",
                         "max_positions", "max_trades_per_session",
                         "trade_counting_mode", "reentry",
                         "no_reentry_after_second_trade"],
    "order_placement": ["type", "execution_timing", "trigger",
                        "execution_timeframe", "price_validation", "orders"],
}
```

Comparison:

```
canonical_yaml = serialize_canonical(canonical)
original_yaml  = serialize_canonical(original_snapshot)  # re-serialize original in same order
diff = unified_diff(original_yaml, canonical_yaml)
```

If diff is empty → **PASS** (no changes needed).
If diff is non-empty → display and **HALT for approval**.

---

## 4. Frozen Schema Definition

```python
# === CANONICAL BLOCKS (ordered) ===
CANONICAL_BLOCKS = [
    "test",               # Identity envelope
    "symbols",            # Symbol list
    "indicators",         # Indicator imports
    "execution_rules",    # Entry/exit/stop logic
    "order_placement",    # Order type and timing
    "trade_management",   # Direction, reentry, position rules
]

REQUIRED_BLOCKS = {"test", "symbols", "indicators", "execution_rules"}
OPTIONAL_BLOCKS = {"order_placement", "trade_management"}

# === BLOCK TYPE ENFORCEMENT ===
BLOCK_TYPES = {
    "test":             dict,
    "symbols":          list,
    "indicators":       list,
    "execution_rules":  dict,
    "trade_management": dict,
    "order_placement":  dict,
}

# === REQUIRED SUB-BLOCKS (structural presence only) ===
REQUIRED_SUB_BLOCKS = {
    "execution_rules": {"entry_logic"},
}

# === LEGACY KEY MIGRATIONS (finite, not extensible) ===
MIGRATION_TABLE = {
    "execution_rules": "execution",  # AK30 used "execution:"
}

# === MISPLACEMENT TABLE (explicit only) ===
MISPLACEMENT_TABLE = {
    "direction":   ("root", "trade_management"),
    "entry_logic": ("root", "execution_rules"),
    "exit_logic":  ("root", "execution_rules"),
}

# === ALLOWED NESTED KEYS — Level 1 (per block) ===
ALLOWED_NESTED_KEYS = {
    "test": {"name", "family", "strategy", "version", "broker",
             "timeframe", "session_time_reference", "start_date",
             "end_date", "research_mode", "tuning_allowed",
             "parameter_mutation", "description", "notes"},
    "execution_rules": {"entry_logic", "exit_logic", "stop_loss",
                        "trailing_stop", "take_profit", "pyramiding",
                        "entry_when_flat_only", "reset_on_exit",
                        "cancel_opposite_on_fill"},
    "trade_management": {"direction", "direction_restriction",
                         "reentry", "max_trades_per_session",
                         "trade_counting_mode", "max_positions",
                         "mode", "no_reentry_after_second_trade"},
    "order_placement": {"type", "execution_timing", "trigger",
                        "execution_timeframe", "price_validation",
                        "orders"},
}

# === ALLOWED SUB-KEYS — Level 2 (per sub-block) ===
ALLOWED_SUB_KEYS = {
    "entry_logic": {"type", "lookback_bars", "atr_length",
                    "atr_multiplier", "condition"},
    "exit_logic":  {"type", "price_exit", "time_exit_bars",
                    "time_exit"},
    "stop_loss":   {"type", "atr_multiplier", "fixed_points"},
    "trailing_stop": {"enabled", "type", "atr_multiplier",
                      "activation_threshold"},
    "take_profit": {"enabled", "type", "atr_multiplier",
                    "fixed_points"},
    "reentry":     {"allowed", "reuse_original_range",
                    "place_both_orders_on_reentry",
                    "allowed_until_trade_count"},
    "price_validation": {"ignore_pre_breakouts"},
}
```

---

## 5. Approval Interaction Model

```
┌─────────────────────────────────────────┐
│  STRUCTURAL DRIFT DETECTED              │
│                                         │
│  Violations:                            │
│    • RELOCATED: 'direction' → trade_mgt │
│    • MIGRATED: 'execution' → exec_rules │
│                                         │
│  --- Unified Diff ---                   │
│  - direction: both                      │
│  + trade_management:                    │
│  +   direction: both                    │
│                                         │
│  Corrected YAML written to:             │
│    /tmp/<DIRECTIVE_ID>_canonical.yaml    │
│                                         │
│  Type APPROVED to overwrite original.   │
│  Any other response = ABORT.            │
└─────────────────────────────────────────┘
```

- Corrected file is written to `/tmp/` (never overwrites in-place without approval).
- Agent MUST NOT auto-approve.
- Agent MUST NOT continue pipeline after structural mismatch without explicit `APPROVED`.

---

## 6. Failure Modes

| Failure | Classification | Phase | Recovery |
|---|---|---|---|
| Unparsable YAML | `YAML_PARSE_ERROR` | 1 | Human fixes syntax |
| Structural block inside `test:` | `ENVELOPE_CONTAMINATION` | 2 | Human moves block to top-level |
| Missing required block | `STRUCTURALLY_INCOMPLETE` | 3 | Human adds block |
| Block has wrong type | `INVALID_BLOCK_TYPE` | 3.5 | Human fixes structure |
| Key exists at both root and destination | `CONFLICTING_DEFINITION` | 4 | Human resolves which is authoritative |
| Unknown top-level key | `UNKNOWN_STRUCTURE` | 5 | Human resolves |
| Unknown L1 nested key | `UNKNOWN_NESTED_KEY` | 6 | Human resolves |
| Unknown L2 sub-key | `UNKNOWN_SUB_KEY` | 6 | Human resolves |
| Required sub-block missing | `STRUCTURALLY_INCOMPLETE` | 6.5 | Human adds sub-block |
| Value modification detected | `INTEGRITY_VIOLATION` | 7 | Design bug — escalate |
| Approval denied | `CANONICALIZATION_REJECTED` | 7 | Pipeline stops |

---

## 7. Structural Guarantees

| Guarantee | Mechanism |
|---|---|
| No leaf guessing | No global key scanning. Only explicit table lookups. |
| No cross-depth inference | Keys recognized only at their declared illegal position. |
| No silent swallowing | Leftover check catches everything not explicitly handled. |
| No silent overwrites | Relocation conflict detection prevents duplicate key resolution. |
| No value modification | Diff comparison catches any accidental value changes. |
| Deterministic output | Explicit `CANONICAL_KEY_ORDER` serialization — not `sort_keys`. |
| Schema freeze | `CANONICAL_BLOCKS`, `ALLOWED_NESTED_KEYS`, `ALLOWED_SUB_KEYS`, `BLOCK_TYPES`, and `REQUIRED_SUB_BLOCKS` are the single source of truth. |
| Envelope purity | `test:` may only contain identity keys. Structural blocks in envelope = HARD FAIL. |
| Depth-2 coverage | Sub-block keys (`entry_logic`, `stop_loss`, etc.) are also frozen. |
| Type safety | Each block enforces its expected type (`dict` vs `list`). |
| Structural completeness | Required sub-blocks (e.g., `entry_logic`) must be present — not just parent blocks. |

---

## 8. Implementation Impact

| Area | Change |
|---|---|
| New: `tools/canonical_schema.py` | ~80 LOC (frozen schema + types + ordering) |
| New: `tools/canonicalizer.py` | ~200 LOC (tree rebuild + conflict detection + diff + CLI) |
| Modify: `run_pipeline.py` | ~10 LOC (hook before Stage-0) |
| Modify: `execute-directives.md` | Add Step 1.25 for canonicalization |
| Modify: `AGENT.md` | Add invariant #19 for schema freeze |
| **Total** | **~280 LOC new + ~20 LOC modified** |
