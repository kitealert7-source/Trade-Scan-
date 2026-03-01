# Directive YAML Structure Gap — Analysis Report

## The Problem

During the SPX02_MR pipeline run, the directive had `entry_logic` and `direction` at the **wrong nesting level** (flat instead of under `execution_rules` / `trade_management`). The pipeline accepted it through preflight and semantic validation, then **crashed mid-execution** with a `KeyError` deep inside `strategy.py`.

This means the YAML structure is **not validated before code is generated**, so a misplaced key silently produces broken strategy code.

---

## What the Pipeline Currently Validates

| Gate | What It Checks | What It Misses |
|---|---|---|
| `directive_schema.py` | `indicators` and `execution_rules` exist as keys | Does NOT check internal nesting or sub-key structure |
| `semantic_validator.py` | Signature hash match, indicator imports, FilterStack usage, hollow detection | Does NOT validate directive YAML structure itself |
| `strategy_provisioner.py` | Generates `strategy.py` from directive | Silently generates broken code if keys are at wrong level |
| `strategy_dryrun_validator.py` | Runs strategy with mock data | Catches the crash — but only AFTER code generation |

**The gap:** There is no check between "parse YAML" and "generate strategy code" that verifies the YAML's **internal tree structure** is correct.

---

## Structural Variations Found Across Directives

### SPX02_MR (v2 — corrected)

```yaml
test:
  name: SPX02_MR
execution_rules:
  entry_logic:        # ← nested correctly under execution_rules
    type: volatility_pullback
trade_management:
  direction: long_only  # ← nested correctly under trade_management
```

### AK30_FX_PORTABILITY_4H (legacy — flat)

```yaml
test:
  name: AK30_FX_PORTABILITY_4H
direction: both           # ← FLAT (no parent block)
execution:                # ← "execution" not "execution_rules"
  entry_timing: next_bar_open
```

### ORB_FX_01 (mixed nesting)

```yaml
test:
  name: ORB_FX_01
  indicators:            # ← INSIDE test: block
    - indicators.structure.highest_high
execution_rules:         # ← Top-level
  cancel_opposite_on_fill: true
trade_management:        # ← Top-level (correct)
  direction_restriction: none
```

### Key Inconsistencies

| Key | SPX02_MR | AK30 | ORB_FX_01 |
|---|---|---|---|
| `indicators` | top-level | top-level | **inside `test:`** |
| `entry_logic` | under `execution_rules` | absent | absent |
| `direction` | under `trade_management` | **flat** | under `trade_management` |
| `execution_rules` | present | **`execution:` instead** | present |

---

## Where a Structural Check Should Be Inserted

The ideal insertion point is **Step 0 — immediately after YAML parse, before any code generation**.

```
Current flow:
  Parse YAML → Preflight → Semantic Validation → Strategy Provisioning → ...

Proposed flow:
  Parse YAML → ★ STRUCTURAL VALIDATION ★ → Preflight → Semantic Validation → ...
```

This check would be a **hard-fail gate** that runs before Stage-0. It would:

1. Verify the required top-level blocks exist (`indicators`, `execution_rules`)
2. Verify critical sub-keys are at the correct nesting depth (e.g., `entry_logic` must be under `execution_rules`, not flat)
3. Detect legacy key names (e.g., `execution` → should be `execution_rules`)
4. Report all violations at once (not fail on the first one)

---

## Risk Assessment

| Risk | Severity | Current Mitigation |
|---|---|---|
| Flat `direction` key | **HIGH** — causes runtime `KeyError` | None — only caught by dry-run crash |
| `indicators` inside `test:` | **MEDIUM** — may or may not be parsed correctly depending on loader | `parse_directive()` may handle this |
| `execution` vs `execution_rules` | **HIGH** — schema check for `execution_rules` would fail, but legacy directives used `execution` | `REQUIRED_SIGNATURE_KEYS` catches this, but error message is opaque |
| Missing `trade_management` | **LOW** — some strategies don't use it | Not currently required |

---

## Recommendation

> [!IMPORTANT]
> This is a **report only** per user request.
> Implementation should be planned separately after the current hardening round stabilizes.

The structural validator should be a lightweight Python script (`tools/validate_directive_structure.py`) that:

- Takes a directive path
- Parses the YAML
- Validates against a schema definition (expected keys, nesting, types)
- Returns PASS/FAIL with human-readable diagnostics
- Is called as the **first gate** in the execute-directives workflow (before `--provision-only`)
