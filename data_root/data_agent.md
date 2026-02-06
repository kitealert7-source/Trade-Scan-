# DATA ENGINEERING STANDARD (ANTI-GRAVITY CANONICAL)

This document governs ALL data ingestion, storage, and handling.
Authoritative for agents and humans.

---

## 0. BOOTSTRAP REQUIREMENT (MANDATORY)

Before any data work begins, the agent MUST:

1. Load and explicitly acknowledge ALL Anti‑Gravity data governance.
2. Confirm read/write access to ANTI_GRAVITY_DATA_ROOT for ingestion and rebuild operations.
3. Treat all SOPs and addenda as binding constraints.

Minimum required documents (explicit acknowledgment required):

- ANTI_GRAVITY_SOP_v17.md (Primary Canon)
- ANTI_GRAVITY_DATA_LIFECYCLE_SOP_v17_Revised.md
- DATASET_GOVERNANCE_SOP_v17-DV1.md
- SOP_DATA_TIMEFRAMES_v1.md
- ADDENDUM_A_Timeframe_Filename_Governance.md
- ADDENDUM_EXECUTION_PRICE_SEMANTICS_OCTAFX.md
- DATA_RESOLUTION_ENGINE_CONTRACT_v1.md
- RECOVERY.md (Data Recovery & Integrity Protocol)


If any conflict exists:
ANTI_GRAVITY_SOP_v17 prevails.

No ingestion or modification may proceed until these are reviewed and explicitly acknowledged.

The agent is AUTHORIZED to access ANTI_GRAVITY_DATA_ROOT for:

- RAW ingestion (append-only)
- CLEAN rebuilds
- RESEARCH rebuilds
- governance-compliant dataset updates

The agent must NOT request this permission again unless explicitly revoked.

---

## 1. Anti Gravity Data Root (MANDATORY)

All market data MUST live under:

ANTI_GRAVITY_DATA_ROOT/

This is the only authoritative data location.

Forbidden:
- ad-hoc local CSVs
- duplicate datasets outside root
- strategy folders holding raw market data

Strategies may only CONSUME data from the root.

---

## 2. Immutable Raw Data Rule

Raw ingested data is IMMUTABLE.

Once written:
- never edited
- never overwritten
- never filtered in-place

Any transformation creates a NEW derived dataset.

Append-only semantics apply.

---

## 3. Dataset Identity

Every dataset must be uniquely identified by:

- asset
- feed
- timeframe
- year
- dataset stage (RAW / CLEAN / RESEARCH)

Canonical filename required:

[ASSET]_[FEED]_[TIMEFRAME]_[YEAR]_[TYPE].csv

Legacy formats are forbidden.

---

## 4. Ingestion Pipeline

Standard flow:

1. Fetch RAW (incremental only)
2. Store under ANTI_GRAVITY_DATA_ROOT/MASTER_DATA/<ASSET>_<FEED>_MASTER/RAW
3. Validate schema + continuity
4. Produce CLEAN
5. Produce RESEARCH
6. Emit lineage + manifests

Never bypass steps.

---

## 5. Timeframe Governance

All bars must comply with SOP_DATA_TIMEFRAMES_v1.

Native sourcing only.
NO RESAMPLING.

Unsupported feed–timeframe pairs must hard-fail.

---

## 6. Validation Requirements

Each ingestion must verify:

- monotonic timestamps
- no duplicates
- no gaps (or gaps explicitly logged)
- numeric columns finite
- timezone consistency
- canonical filenames
- SOURCE→FEED mapping

Failures STOP the pipeline.

---

## 7. Provenance Tracking

Every derived dataset must record:

- source dataset id
- dataset_version
- research_sha256
- transformation applied
- execution timestamp

No orphan data.

---

## 8. Scope Discipline

Do NOT:

- normalize data inside strategy code
- resample inside strategy code
- patch missing bars silently
- mix brokers without explicit labeling
- write directly to RESEARCH outside rebuild pipeline

Data preparation is separate from strategy execution.

---

## 9. Versioning

Any change to ingestion behavior requires:

- new version
- old version preserved
- explicit changelog

Never overwrite historical data.

---

## 10. Execution Price Semantics (OctaFX)

For OctaFX RESEARCH datasets:

- prices MUST already be execution prices (ASK embedded)
- spread MUST be zero
- engines must NOT apply spread again

Violation is CRITICAL.

---

## 11. Performance Philosophy

Correctness > Reproducibility > Speed.

Optimization is allowed ONLY after data integrity is guaranteed.

---

## 12. Data Folders

Please remember permanently:
Anti-Gravity SOPs and all market datasets always live under ANTI_GRAVITY_DATA_ROOT.
Never search alternate folders for governance or data.
If something is not found there, stop and ask.

End of document.
