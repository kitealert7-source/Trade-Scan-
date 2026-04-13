# ADDENDUM_A_Timeframe_Filename_Governance.md

## Status: ACTIVE
## Parent SOPs:
- ANTI_GRAVITY_SOP_v17
- SOP_DATA_TIMEFRAMES_v1

---

# ADDENDUM A — Canonical Filename Migration & SOURCE→FEED Mapping Governance

## A1. Purpose

This addendum formalizes and permanently governs:

1. The canonical dataset filename contract
2. Migration from all legacy naming formats
3. Deterministic and auditable SOURCE → FEED translation
4. Mandatory migration audit and rollback artifacts
5. Validator-level enforcement of all filename identity rules

Its objective is the permanent elimination of dataset identity ambiguity
and the preservation of long-term reproducibility across the Anti-Gravity system.

This addendum is authoritative and non-optional.

---

## A2. Canonical Filename Contract (Authoritative)

All dataset files under `MASTER_DATA` **MUST** follow the canonical format:

```
[ASSET]_[FEED]_[TIMEFRAME]_[YEAR]_[TYPE].csv
```

Where:
- `ASSET`      → Uppercase (e.g. BTC, ETH, XAUUSD)
- `FEED`       → Uppercase, canonical feed identifier
- `TIMEFRAME`  → Lowercase (e.g. 1m, 3m, 5m, 15m)
- `YEAR`       → Four-digit year
- `TYPE`       → RAW | CLEAN | RESEARCH

### Forbidden Legacy Formats

The following formats are **FORBIDDEN** and must not exist after migration:

```
[ASSET]_[TIMEFRAME]_[YEAR]_[SOURCE]_[TYPE].csv
[ASSET]_[SOURCE]_[TIMEFRAME]_[YEAR]_[TYPE].csv
```

The dataset validator **MUST** reject any non-canonical filename.

---

## A3. SOURCE → FEED Mapping (Deterministic)

The following mapping is **authoritative and exclusive**:

| SOURCE | FEED   |
|------:|--------|
| MT5   | OCTAFX |
| DELTA | DELTA  |

### Enforcement Rules

- Unknown SOURCE → **CRITICAL FAIL**
- Ambiguous SOURCE → **CRITICAL FAIL**
- New ingestion sources require an explicit governance update
- No implicit or heuristic mapping is permitted

---

## A4. Migration Protocol (One-Time Operation)

This protocol applies **once only** during the transition from legacy naming.

### A4.1 DRY-RUN (Mandatory)

A dry-run migration script **MUST** generate:

```
migration_plan.json
```

For each file:
- original filename
- target canonical filename
- SOURCE and FEED
- ASSET, TIMEFRAME, YEAR, TYPE
- SHA256 (pre-rename)
- timestamp

Migration **MUST ABORT** if:
- SOURCE is unknown
- target filename collision occurs
- FEED–TIMEFRAME combination is invalid

---

### A4.2 Destructive Rename Execution

After explicit approval:

- Rename files in place
- Remove all legacy filenames
- Do not duplicate or preserve legacy copies

Archive the migration plan at:

```
GOVERNANCE/MIGRATIONS/
    TIMEFRAME_FILENAME_MIGRATION_YYYYMMDD.json
```

---

### A4.3 Post-Migration Validation

The following commands **MUST** succeed:

```
dataset_validator_sop17.py --audit-all
rebuild_research_sop17.py --dry-run
```

Validator **MUST CONFIRM**:
- No legacy filenames remain
- All canonical filenames are valid
- No mixed naming epochs exist
- FEED–TIMEFRAME integrity holds

If validation fails, **ROLLBACK IS REQUIRED**.

---

## A5. Validator Extended Enforcement Duties

The dataset validator **MUST** enforce:

1. Canonical filename format only
2. Valid FEED values only
3. Valid SOURCE → FEED mapping
4. Unique identity for (asset, feed, timeframe, year, type)
5. Immediate failure if legacy and canonical files coexist

No downstream component may override validator decisions.

---

## A6. Pipeline Expectations After Migration

After migration completion:

- Ingestion logic emits canonical filenames only
- Analyzer and Tuner drop all legacy handling
- Timeframe detection relies exclusively on filenames
- FEED must always be explicitly declared

---

## A7. Governance Recording Requirement

The migration decision **MUST** be recorded as:

```
DEC-YYYY-MM-DD-XXX
Adoption of Addendum A — Canonical Filename Migration &
SOURCE→FEED Mapping Governance
```

This record is permanent.

---

## A8. Status & Permanence

This addendum is **ACTIVE and PERMANENT**.

Any modification requires:
1. Explicit human approval
2. Versioned governance change record
3. Written declaration of execution impact

No silent or implicit change is permitted.
