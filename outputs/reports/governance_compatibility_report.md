# Governance Compatibility Verification: Directive-Declared Indicators

## Executive Summary

**Compliance Status**: **SAFE / COMPLIANT**
**Requires SOP Revision**: **NO**

Adding an optional `Indicators:` block to directive files for the sole purpose of Preflight existence requirements **does not violate** existing governance protocols. In fact, it **better aligns** the system with `SOP_INDICATOR` §10 requirements.

---

## 1. Compliance Analysis

| Governance Clause | Potential Conflict | Verdict | Justification |
| :--- | :--- | :--- | :--- |
| **SOP_INDICATOR §10**<br>"Dependency validation MUST occur BEFORE: Strategy import, Engine execution" | Moving validation to Preflight satisfies "BEFORE". Currently, implicit validation happens *during* execution (Strategy import). | **ENHANCED COMPLIANCE** | The proposed change explicitly satisfies the requirement to validate *before* import/execution. |
| **SOP_INDICATOR §10**<br>"Strategy plugins MUST declare indicator dependencies exclusively through: `import`" | Does "exclusively" forbid listing them in directives? | **NO CONFLICT** | "Exclusively through import" refers to **code binding** (i.e., you cannot use inline logic or other mechanisms to *invoke* indicators). The directive list is a **metadata declaration** for environmental validation, not a strategy implementation mechanism. The Strategy still imports them. |
| **STRATEGY_PLUGIN_CONTRACT §2**<br>"Indicator invocation and parameter selection belong to the strategy" | Does listing them in directive remove this ownership? | **NO CONFLICT** | The directive only lists *what files must be present*. It does not instantiate, invoke, or parameterize them. The Strategy retains full control over invocation logic. |
| **SOP_TESTING §3.2**<br>"Execution is directive-explicit" | Is expanding directive schema allowed? | **COMPLIANT** | Directives are the authoritative source of execution scope. Listing dependencies aligns with the principle that the Directive defines the "Execution Context". |
| **SOP_INDICATOR §5**<br>"Inline indicator implementations... PROHIBITED" | Does this allow inline logic? | **NO** | The proposed change only allows listing *filenames* of existing repository indicators. It remains strictly declarative. |

---

## 2. Detailed Justification

### Why "Exclusively through import" is not violated

The clause in `SOP_INDICATOR` §10 is designed to prevent **Hidden Dependencies** or **Inline Re-implementations**. It ensures that if a strategy uses an indicator, it must be via a standard Python import of a governed file.

Adding a header in the directive:

```yaml
Indicators:
  - indicators/volatility/atr.py
  - indicators/trend/sma.py
```

...is a **Preconditions Check**. It says "Verify these files exist before starting". It does not replace the import. If the strategy fails to import them, execution will still fail (at a later stage). If the strategy imports something *not* in this list, execution proceeds (unless we enable strict policing, which is optional).

Therefore, the Strategy still "declares" usage via import. The Directive simply "declares" requisite environment state.

### Why Preflight is the Correct Layer

`SOP_INDICATOR` specifically mandates validation **BEFORE** execution.
Currently, `run_stage1.py` validates dependencies *inside* `load_strategy()`.
Technically, validation happens *at the moment of* Strategy Import.
By moving this check to Preflight (via Directive declaration), we achieve strict adherence to the **"BEFORE Strategy Import"** requirement.

---

## 3. Recommendation

**Proceed with Implementation.**

No governance documents need to be updated because:

1. **SOP_TESTING**: Already permits directive-driven execution and Preflight validation.
2. **SOP_INDICATOR**: The change facilitates better compliance with Section 10 ("Validation BEFORE execution").
3. **STRATEGY_PLUGIN_CONTRACT**: Remains invariant as the Strategy logic is untouched.

**Action Item**:

- Implement `Indicators:` block parsing in `governance/preflight.py`.
- Treat the list as a **Mandatory Existence Check** (If listed, MUST exist).
- (Optional) Future Governance: Update `SOP_TESTING` to explicitly *recommend* declaring indicators in directives for faster fail-fast behavior, but do not make it mandatory yet to preserve backward compatibility.
