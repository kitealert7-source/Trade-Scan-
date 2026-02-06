# DATA RESOLUTION ENGINE CONTRACT
**Run Order (Organizational)**: 10

**Contract ID**: data_resolution_engine_contract_v1  
**Status**: ACTIVE 
**Engine Name** | Data Resolution Engine |
**Abbreviation** | DRE |
**Implementation** | `engines/data_resolution_engine.py` |
**Pipeline Stage** | Stage-2: Data Resolution |
**Execution Phase** | Runtime (pre-execution) |
**Rights**: (READ/WRITE/EXECUTE) 
**Version**: v1  
**Last Updated**: 2025-12-28

## Abbreviations & Terminology

**Contract-Specific Terms**:
- **DRE**: Data Resolution Engine (this engine)
- **Data Resolution Descriptor**: Cryptographically verified dataset reference

**Common AKM Terms** (see [Glossary](../00_akm_terminology_glossary.md)):
- **RESEARCH**: Dataset tier for strategy execution
- **SEL**: Systematic Execution Loop


## Validation Coverage


## Governing SOPs (Reference Only)
**Related SOPs**:
  Name and Path  

**Note**: SOPs provide governance context only.  
They do not define execution order or pipeline control.
## Contract Interpretation Note

This contract is a **descriptive specification/ executable /enforcing artifact.**

  Authority applies **only** where explicitly stated.
  Undefined behavior is **not** implied permission.
  Described failure handling reflects intent, not guaranteed enforcement.
  In case of conflict, implemented system behavior prevails unless formally overridden.

**Upstream Dependencies**:
  Name and Path 
**Downstream Consumers**:
  Name and Path 


## Input/Output Contract

### Required Inputs



### Produced Outputs (Emissions)



---



---

<!--CONTRACT>

---

# DATA RESOLUTION ENGINE CONTRACT — AKM STAGE‑2

**Engine Name:** Data Resolution Engine  
**Pipeline Stage:** Stage‑2  
**Status:** ACTIVE  
**Authority:** AKM Execution Pipeline  
**Data Authority:** Anti‑Gravity Data System (External)

---

## 1. Purpose

The Data Resolution Engine is responsible for **freezing and certifying the exact RESEARCH dataset instance used by a single AKM execution run**.

This engine produces an immutable **Data Resolution Descriptor** that becomes part of the run's permanent execution record.

The engine does **not** ingest, mutate, validate, rebuild, or transform data.

---

## 2. Scope of Authority

### 2.1 What This Engine Controls

The engine has authority to:

- Resolve dataset **identity**, not dataset content
- Select RESEARCH datasets by:
  - Asset
  - Feed
  - Timeframe
  - Date range
- Verify dataset lineage consistency
- Emit a deterministic, immutable descriptor

### 2.2 What This Engine Does NOT Control

The engine has **no authority** over:

- RAW ingestion
- CLEAN normalization
- RESEARCH rebuilds
- Dataset versioning rules
- Execution model logic
- Strategy logic
- Indicator binding

All such responsibilities are governed by existing Anti‑Gravity SOPs.

---

## 3. Authoritative Inputs

The engine accepts **only declarative intent**, never file paths or hashes.

### 3.1 Input Schema

```json
{
  "asset": "XAUUSD",
  "feed": "OCTAFX",
  "timeframe": "3m",
  "start_date": "YYYY‑MM‑DD",
  "end_date": "YYYY‑MM‑DD",
  "dataset_stage": "RESEARCH"
}
```

### 3.2 Forbidden Inputs

- Absolute or relative file paths
- Dataset version overrides
- Hash overrides
- Partial dataset specifications

---

## 4. Resolution Rules (Mandatory)

### 4.1 Data Root Resolution

- Data root must be resolved using the canonical resolver (`GET_DATA_ROOT`).
- The resolved path **must point to Anti‑Gravity DATA ROOT**.
- Any override, shadow path, or redirected root results in **hard failure**.

### 4.2 Dataset Discovery

The engine must search **only** the following canonical location:

```
MASTER_DATA/
  <ASSET>_<FEED>_MASTER/
    RESEARCH/
      <ASSET>_<FEED>_<TIMEFRAME>_<YEAR>_RESEARCH.csv
```

Rules:
- Required years are inferred from `start_date` → `end_date`.
- All required year files must exist.
- Missing any file results in **hard failure**.

### 4.3 Lineage Consistency Enforcement

For every RESEARCH file, the engine must load:

```
<ASSET>_<FEED>_<TIMEFRAME>_<YEAR>_RESEARCH_lineage.json
```

Mandatory fields:
- `dataset_version`
- `research_sha256`

Rules:
- All resolved files must share **identical dataset_version**.
- Any mismatch results in **hard failure**.
- Missing lineage results in **hard failure**.

### 4.4 Time Coverage Verification

The engine must verify:
- First available bar ≤ `start_date`
- Last available bar ≥ `end_date`

Partial coverage is forbidden and results in **hard failure**.

⚠️ The engine must **not** slice or modify datasets.

---

## 5. Output Contract (Authoritative)

The engine must emit a single immutable descriptor.

### 5.1 Descriptor Schema

```json
{
  "asset": "XAUUSD",
  "feed": "OCTAFX",
  "timeframe": "3m",

  "dataset_stage": "RESEARCH",
  "dataset_version": "RESEARCH_vX_EXECvY_SESSIONvZ",

  "files": [
    "XAUUSD_OCTAFX_3m_2024_RESEARCH.csv",
    "XAUUSD_OCTAFX_3m_2025_RESEARCH.csv"
  ],

  "date_range": {
    "start": "YYYY‑MM‑DD",
    "end": "YYYY‑MM‑DD"
  },

  "research_sha256": "<combined_deterministic_hash>",
  "resolution_timestamp_utc": "YYYY‑MM‑DDTHH:MM:SSZ"
}
```

### 5.2 Combined Hash Rule

The `research_sha256` must be computed deterministically from:

1. Ordered filenames
2. Each file's `research_sha256` from lineage

This hash uniquely fingerprints the dataset instance used by the run.

---

## 6. Persistence Rules (Critical)

- Descriptor must be written **only** to:

```
RESULTS/_RUNNING/<run_id>/data_descriptor.json
```

- On successful run promotion, the descriptor may be moved to:

```
RESULTS/<TIMESTAMP>/data_descriptor.json
```

### Forbidden Writes

The engine must **never** write to:

- `MASTER_DATA/`
- `RAW/`, `CLEAN/`, or `RESEARCH/`
- Any lineage or manifest file

---

## 7. Failure Semantics

The engine must fail immediately on:

- Missing RESEARCH dataset files
- Missing lineage metadata
- Dataset version mismatch
- Unsupported feed–timeframe pair
- Data root mismatch
- Partial time coverage

No warnings, fallbacks, or auto‑corrections are permitted.

---

## 8. Concurrency & Determinism Guarantees

- Engine must be **read‑only** and **side‑effect free**.
- Multiple concurrent executions may safely resolve the same dataset.
- Identical inputs must always produce identical descriptors.

---

## 9. Governance Classification

- This document is an **Engine Contract**, not an SOP.
- It does not define system law.
- It enforces execution‑level authority boundaries within AKM.
- All referenced data rules are inherited from existing Anti‑Gravity SOPs.

---

## 10. Change Control

Any change to:
- Output schema
- Resolution rules
- Persistence behavior

requires:
- A new version of this contract
- Explicit pipeline review

---

**End of Contract — Data Resolution Engine (Stage‑2)**
