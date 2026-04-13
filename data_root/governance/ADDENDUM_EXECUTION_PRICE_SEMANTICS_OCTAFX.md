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
| execution_model_version | octafx_exec_v3.0 |

Implications:

- Spread is embedded into prices
- Engines MUST NOT apply spread again
- Prices are final execution prices

### 4.1 Post-Transformation Cost Column Semantics (EXECv2)

**CRITICAL RULE**: All execution cost columns in RESEARCH datasets MUST be set to `0`:

| Column | Required Value | Rationale |
|--------|----------------|-----------|
| commission_cash | 0 | Spread already in prices; additional costs are broker constants, not dataset properties |
| commission_pct | 0 | Same as above; informational only |
| spread | 0 | Already embedded in OHLC prices |
| slippage | 0 | Not modeled at data layer |

**Purpose**: These columns exist for **future extensibility only**. They are **NOT** execution costs to be applied.

**Contract**:

- RESEARCH prices are **final execution prices**
- Engines MUST NOT read cost columns from RESEARCH datasets
- Execution costs (commission, slippage) are **broker-specific constants** managed at the engine level
- Reading non-zero values from these columns would cause **double-counting** of costs

**Violation**: Any RESEARCH dataset with non-zero cost columns (under EXECv2+) is **invalid** and MUST be rejected.

### 4.2 Zero-Spread Backfill Rule (EXECv3)

**CRITICAL RULE**: If a RAW partition has exactly 100% zero spread for every row, it MUST be dynamically backfilled using the **Forward Median Method** instead of being hard-rejected.

Let:

- `raw_spread_points` be the spread array for the partition
- `zero_spread_partition` = True if `raw_spread_points.max() == 0` else False

**Forward Median Method**:

1. If `zero_spread_partition` is True, locate the nearest subsequent RAW partition for the same symbol and timeframe where `spread_points > 0`.
2. Extract the first 5,000 non-zero rows (or all if fewer).
3. Compute `reference_spread_points = median(nonzero_spread_points)`.
4. If no future partition exists, fallback to the previous partition. If still none, trigger a hard failure.

**Transformation**:

```
if zero_spread_partition:
    effective_spread_points = reference_spread_points
else:
    effective_spread_points = raw_spread_points

price_exec = price_bid + (effective_spread_points * point_size)
```

**Logging**: Any invocation of this rule MUST log a `ZERO_SPREAD_BACKFILL_INJECTION` integrity event tracking the symbol, timeframe, and `reference_spread_points` value.

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

- Prices are execution-realistic (spread-inclusive for OctaFX)
- No BID/ASK reasoning is required
- No spread logic is applied internally

**EXECv2 Critical Addition**:

Engines MUST NOT:

- Read `commission_cash` or `commission_pct` from RESEARCH datasets
- Use cost columns for execution cost calculation
- Assume non-zero cost values are valid execution parameters

Engines MUST:

- Use **broker-specific execution cost constants** defined at the engine level
- Treat RESEARCH prices as **final execution prices**
- Understand that cost columns are metadata/informational only

**Rationale**: Execution costs are **broker properties**, not dataset properties. RESEARCH datasets provide execution-ready prices; costs are applied by execution engines using broker-specific constants.

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
