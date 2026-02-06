# ADDENDUM_EXECUTION_PRICE_SEMANTICS_OCTAFX.md

## Status
**ACTIVE — GOVERNANCE ADDENDUM**  
**Scope:** Anti-Gravity v17 Data Layer  
**Applies To:** OctaFX feed ONLY

This addendum is authoritative and binding.  
It introduces **execution price semantics** for OctaFX-derived datasets and resolves BID/ASK ambiguity permanently.

---

## 1. Motivation

OctaFX (MT4/MT5) provides OHLC prices in **BID terms** with an explicit `spread` column.
Execution, however, occurs at **ASK for BUY** and **BID for SELL**.

Prior to this addendum, RESEARCH datasets embedded execution *models* but not execution *prices*, resulting in an invalid hybrid:
- BID OHLC
- spread = 0
- execution_model_version declared

This addendum corrects that ambiguity at the **data layer**, not the strategy or engine layer.

---

## 2. Scope (Strict)

This addendum applies **ONLY** when **ALL** of the following are true:

- `feed == OCTAFX`
- `dataset_stage == RESEARCH`
- `execution_model_version` starts with `octafx_exec`

If any condition is false, this addendum does **NOT** apply.

Delta and all non-OctaFX feeds are explicitly excluded.

---

## 3. Canonical Rule — Execution Prices for OctaFX

For OctaFX EXECUTION datasets:

- RAW prices are BID
- CLEAN prices are BID
- RESEARCH prices **MUST** be execution prices

Execution prices are defined as **ASK-based bars**, constructed by embedding spread into OHLC.

### 3.1 Price Transformation Rule

Let:

- `price_bid` be any OHLC value from CLEAN
- `spread_points` be the RAW spread (in points)
- `point_size` be the instrument point value

Then:

```
price_exec = price_bid + (spread_points × point_size)
```

This transformation MUST be applied to:
- open
- high
- low
- close

This rule is deterministic, strategy-agnostic, and conservative.

---

## 4. Post-Transformation Constraints

After execution-price embedding:

| Field | Required Value |
|------|----------------|
| spread | 0 |
| slippage | 0 |
| commission | execution-model constant |
| execution_model_version | octafx_exec_vX.Y |

Implications:
- Spread is embedded into prices
- Engines MUST NOT apply spread again
- Prices are final execution prices

---

## 5. Forbidden States (CRITICAL VIOLATION)

The following states are **INVALID** for OctaFX RESEARCH datasets:

- BID OHLC + spread = 0
- EXECUTION model declared without price transformation
- CLEAN OHLC identical to RESEARCH OHLC when spread = 0

Any of the above MUST trigger a hard pipeline failure.

---

## 6. Engine Contract

Engines consuming RESEARCH datasets MUST assume:

- Prices are execution-realistic
- No BID/ASK reasoning is required
- No spread logic is applied internally

Violating this contract is an SOP breach.

---

## 7. Governance Authority

- This addendum extends:
  - ANTI_GRAVITY_SOP_v17
  - DATASET_GOVERNANCE_SOP_v17-DV1
- It does NOT modify Delta execution semantics
- It does NOT alter commission, position sizing, or strategy logic

---

## 8. Versioning & Change Control

- Any change to this addendum requires:
  1. Explicit human approval
  2. Versioned changelog entry
  3. Written execution-impact declaration

Absent these, the rules herein remain permanent.

---

## 9. Effective Date

Effective immediately upon adoption.
All OctaFX RESEARCH datasets generated thereafter MUST comply.

Historical datasets MAY be regenerated under this rule for correctness.

---

END OF ADDENDUM
