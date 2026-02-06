# RECOVERY.md
## Anti_Gravity_DATA_ROOT — Data Recovery & Integrity Protocol

**Status:** ACTIVE  
**Authority:** Anti_Gravity_DATA_ROOT (Data-Sovereign Domain)  
**Scope:** DATA ONLY (No engine or strategy logic)

---

## 1. Purpose

This document defines the authoritative recovery, verification, and reconstruction
procedures for **Anti_Gravity_DATA_ROOT**.

It assumes a worst-case scenario:
- AG folder is corrupted, deleted, or untrusted
- Engines, validators, or scripts may be missing or compromised

**DATA_ROOT must remain provable, auditable, and recoverable without AG.**

This document is declarative and non-executable.

---

## 2. Core Principles (Non-Negotiable)

1. DATA_ROOT is the **sole source of market truth**
2. Data files are immutable; regeneration is append-only
3. Governance documents define correctness, not engines
4. Engines are replaceable; data is not
5. Recovery must be possible using:
   - RAW data
   - Governance SOPs
   - Metadata & manifests

---

## 3. Trust Boundaries

Trusted:
- MASTER_DATA/
- governance/
- RUNBOOKS/
- METADATA/

Untrusted:
- AG/
- Any runtime engine
- Any script modifying data without manifest updates

DATA_ROOT assumes all external code is potentially hostile.

---

## 4. Recovery Entry Conditions

Initiate recovery if **any** of the following are true:

- AG repository is missing or corrupted
- Validator behavior is suspected incorrect
- Data integrity is questioned
- Dataset lineage cannot be proven
- Historical reproducibility is required

---

## 5. Integrity Verification (Read-Only)

For each dataset under `MASTER_DATA/<ASSET>_<FEED>_MASTER/`:

### 5.1 RAW Verification
Verify:
- Append-only property
- Monotonic timestamps
- No duplicate bars
- File-level SHA256 matches manifest (if present)

RAW is authoritative and must never be regenerated unless lost.

### 5.2 CLEAN Verification
Verify:
- Derived strictly from RAW
- Duplicate removal only
- No resampling
- Schema matches governance
- SHA256 matches CLEAN manifest

If CLEAN fails verification, it may be **deleted and rebuilt** from RAW.

### 5.3 RESEARCH Verification
Verify:
- CLEAN hash matches lineage
- Execution model version recorded
- Session rules version recorded
- No strategy logic present
- SHA256 matches RESEARCH lineage

If RESEARCH fails verification, it may be **deleted and rebuilt** from CLEAN.

---

## 6. Reconstruction Order (Authoritative)

If regeneration is required, the **only valid order** is:

1. RAW (never regenerated unless missing)
2. CLEAN (rebuildable from RAW)
3. RESEARCH (rebuildable from CLEAN)

Any other order is invalid.

---

## 7. RAW Loss Scenario (Severe)

If RAW data is lost or corrupted:

1. Declare **DATA LOSS EVENT**
2. Record incident in `METADATA/incidents.log`
3. Restore RAW from:
   - Offline backup
   - Archival snapshot
4. If restoration is impossible:
   - Dataset is permanently invalidated
   - Historical continuity is broken
   - New lineage epoch must be declared

RAW loss cannot be silently repaired.

---

## 8. Lineage Reconstruction

Using only DATA_ROOT artifacts:

- CLEAN lineage must reference:
  - RAW filenames
  - RAW hashes
- RESEARCH lineage must reference:
  - CLEAN hashes
  - Execution model version
  - Session filter version

If lineage cannot be reconstructed:
- Dataset is invalid
- Must not be used for research or trading

---

## 9. Validator Independence

Validators are **not authoritative**.

Any validator implementation must:
- Consume governance rules from DATA_ROOT
- Verify against manifests and hashes
- Be replaceable without data changes

A dataset is valid only if it satisfies governance,
not because a specific engine claims it is valid.

---

## 10. Recovery Acceptance Criteria

Recovery is considered complete only when:

- All datasets pass integrity checks
- Lineage is complete and provable
- Governance references are intact
- No silent assumptions are required

Failure to meet all criteria = recovery failure.

---

## 11. Prohibited Actions During Recovery

- Editing RAW data manually
- Recomputing history without declaration
- Modifying governance to "fix" data
- Backfilling without documentation
- Trusting engine output without verification

---

## 12. Final Assertion

Anti_Gravity_DATA_ROOT is designed so that:

> Even if all engines disappear,
> market truth, lineage, and validity remain provable.

Any system consuming this data must comply with these rules.

---

**END OF FILE**
