# ADDENDUM_DATA_INTEGRITY_CHAIN_v1.md

## Status

**ACTIVE --- GOVERNANCE ADDENDUM**\
**Scope:** Anti_Gravity_DATA_ROOT\
**Applies To:** All MASTER_DATA datasets (RAW, CLEAN, RESEARCH)

This addendum formalizes the **Data Integrity Chain** and downstream
staleness doctrine for Anti-Gravity v17+.

This document is authoritative and binding.

------------------------------------------------------------------------

# 1. Purpose

This addendum establishes:

1.  Structural integrity guarantees at the RAW layer\
2.  Manifest-based lineage enforcement\
3.  Downstream staleness detection rules\
4.  Automatic rebuild semantics\
5.  Explicit failure-class coverage

Its objective is to eliminate silent corruption propagation and ensure
deterministic reconstruction at all times.

------------------------------------------------------------------------

# 2. RAW Integrity Guarantees (Mandatory)

All RAW datasets MUST satisfy:

## 2.1 Structural Invariants

-   Strictly monotonic timestamps
-   No duplicate timestamps
-   Append-only mutation model
-   No resampling or timeframe shifting
-   UTC-normalized timestamps

## 2.2 Timeframe Geometry Enforcement

Each RAW dataset MUST conform to expected median delta rules for its
timeframe (e.g., D1, H4, H1).

Abnormal timeframe geometry (e.g., MN1 returned for D1)\
MUST trigger ingestion failure.

## 2.3 Future Timestamp Prohibition

No RAW dataset may contain timestamps greater than:

UTC_NOW + 24 hours

Violation = CRITICAL failure.

## 2.4 RAW Manifest Requirement

Each RAW file MUST generate a manifest containing:

-   schema_version\
-   symbol\
-   feed\
-   timeframe\
-   year\
-   row_count\
-   first_timestamp\
-   last_timestamp\
-   columns\
-   interval_seconds\
-   sha256\
-   generated_utc

RAW manifests are authoritative identity fingerprints.

------------------------------------------------------------------------

# 3. Manifest Chain Model (Authoritative)

Anti-Gravity enforces a deterministic identity chain:

RAW → CLEAN → RESEARCH

Each downstream layer MUST record upstream identity state.

## 3.1 CLEAN Manifest Requirements

CLEAN manifests MUST include:

-   clean_sha256\
-   bar_count\
-   schema_version\
-   raw_sha256\
-   raw_row_count\
-   raw_last_timestamp

## 3.2 RESEARCH Manifest Requirements

RESEARCH lineage MUST include:

-   research_sha256\
-   dataset_version\
-   execution_model_version\
-   clean_sha256\
-   clean_row_count

This forms a cryptographic dependency chain.

------------------------------------------------------------------------

# 4. Downstream Staleness Doctrine

## 4.1 Material Upstream Change

A downstream dataset is considered STALE if any of the following differ
from recorded upstream state:

-   sha256\
-   row_count\
-   last_timestamp

## 4.2 Mandatory Rebuild Rule

If upstream material change is detected:

-   CLEAN MUST rebuild from RAW\
-   RESEARCH MUST rebuild from CLEAN

Skip logic MUST NOT override manifest mismatch.

Staleness detection is authoritative.

------------------------------------------------------------------------

# 5. Recovery Compatibility

This addendum integrates with:

-   RECOVERY.md\
-   ANTI_GRAVITY_SOP_v17\
-   Addendum A (Filename Governance)

Reconstruction order remains:

RAW → CLEAN → RESEARCH

No layer may regenerate upstream data.

------------------------------------------------------------------------

# 6. Failure Class Coverage

The Data Integrity Chain explicitly prevents:

  Failure Class                    Covered
  -------------------------------- ---------
  Broker wrong timeframe return    YES
  Monthly collapse in daily data   YES
  Future timestamps                YES
  Duplicate bar propagation        YES
  Downstream stale persistence     YES
  Manual manifest deletion         YES
  Silent skip logic corruption     YES

------------------------------------------------------------------------

# 7. Non-Goals

This addendum does NOT:

-   Auto-heal RAW corruption\
-   Modify historical data silently\
-   Permit resampling or inference\
-   Replace validator authority\
-   Alter execution models

It enforces identity integrity only.

------------------------------------------------------------------------

# 8. Governance Authority

This addendum extends:

-   ANTI_GRAVITY_SOP_v17\
-   RECOVERY.md

Any modification requires:

1.  Explicit human approval\
2.  Versioned change record\
3.  Written declaration of execution impact

Absent these, the rules herein remain permanent.

------------------------------------------------------------------------

# 9. Effective Date

Effective immediately upon adoption.

All datasets generated thereafter MUST comply.

------------------------------------------------------------------------

END OF ADDENDUM
