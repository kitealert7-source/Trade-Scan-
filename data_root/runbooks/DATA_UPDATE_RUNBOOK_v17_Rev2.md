# DATA UPDATE RUNBOOK v17 (Rev2)
**(Incremental RAW Update Protocol)**

**Version:** 1.1 (Rev3)
**Date:** 2025-12-13
**Status:** DRAFT (Awaiting Engine Updates)

## 1. Overview
This runbook replaces all prior data update procedures. It strictly enforces the **Incremental RAW Update Protocol** defined in AG Engine Update Requirements v17.
**Objective:** Append new market data to existing RAW files without overwriting history.

---

## 2. Pre-Requisites
- **Python Environment:** Active
- **MT5 Terminal:** Open and connected (for XAUUSD/OctaFX)
- **Internet:** Active (for Delta API)
- **Repo State:** Clean git status (recommended)

---

## 3. Workflow A: Standard Daily Update (Append Only)
**Frequency:** Once Daily (after 00:00 UTC)

### Step 3.1: RAW Ingest (Incremental - All Assets)
This step fetches *only* new bars since the last recorded timestamp. Run both commands to cover all feeds.

**Command 1 (XAUUSD + Delta):**
```powershell
python raw_update_sop17.py --incremental
```

**Command 2 (OctaFX Crypto - BTC/ETH):**
```powershell
python process_octafx.py --incremental
```

**Verification:**
- Check logs for "Appended X bars" for *each* asset.
- Ensure no "Overwriting" message appears.
- Verify `MASTER_DATA/.../RAW/` file modification times.

### Step 3.2: CLEAN Rebuild (Processing)
Rebuilds the CLEAN dataset from the updated RAW files. This is a full-pass operation to ensure global consistency.
**Command:**
```powershell
python clean_rebuild_sop17.py
```
**Verification:**
- "Duplicate bars removed" count should be near 0 (if RAW is healthy).
- "Missing bars" count should be stable.
- Check `MASTER_DATA/.../CLEAN/` timestamps.

### Step 3.3: RESEARCH Rebuild (Execution Modeling)
Applies the Execution Model (Fees/Spread) to the fresh CLEAN data.
**Command:**
```powershell
python rebuild_research_sop17.py
```
**Verification:**
- SOP v17 Headers present in new CSVs.
- `dataset_version` updated to current date.

---

## 4. Workflow B: Historical Reset (Migration Only)
**Context:** Use this ONLY if RAW data is corrupted or lost (as happened previously). This resets lineage.

1. **Backup:**
   ```powershell
   mkdir ARCHIVE\RAW_BACKUP_<DATE>
   move MASTER_DATA\*\RAW\*.csv ARCHIVE\RAW_BACKUP_<DATE>\
   ```

2. **Full Download (Base Image):**
   ```powershell
   python raw_update_sop17.py --full-reset
   ```
   *Fetches maximum available history (e.g. 99,999 bars).*

3. **Lock:**
   These files become the new anchor for incremental updates.

---

## 5. Audit & Validation
After update, run the integrity check:
**Command:**
```powershell
python dataset_validator_sop17.py --audit-all
```
**Checks:**
- Monotonic timestamps?
- No future data?
- JSON Manifest matches file stats?

See Section 5A for mandatory RAW validation rules executed during audit.

---

## 5A. RAW DATA VALIDATION — SOP17 MANDATORY RULES
This section defines the strict logic enforced by `dataset_validator_sop17.py`.

### 1. Integrity Rules (HARD FAIL)
The validation engine must throw a **Critical Exception** and block downstream processing if:
1.  **Duplicate Timestamps**: Two or more rows share the same `time` value.
2.  **Non-Monotonicity**: Time sequence is not strictly increasing ($t_{i} \le t_{i-1}$).

### 2. Gap Detection & Continuity
- **Gap Class**: A "gap" is defined as $\Delta t > Interval$.
- **Asset-Aware Thresholds**:
    - **Crypto (BTC, ETH)**: 24/7 Trading.
        - *Rule*: **Zero Tolerance**. ANY gap > 1 bar = **HARD FAIL**.
    - **Forex/CFD (XAU)**: Session-based.
        - *Rule*: Any intra-week gap > 1 bar = **HARD FAIL**.
        - *Exception*: Weekend gaps (~48h) and market holidays are IGNORED.

### 3. Metric Computation
For every ingestion run, the following metrics must be computed per file:
- **bars_expected**: All timestamps between First & Last excluding closed-market windows (Session/Holiday aware).
- **missing_pct**: $1 - (\frac{bars\_actual}{bars\_expected})$

### 4. Validation Output Schema
The validator emits a status object:
```json
{
    "file": "BTC_5m_2024_DELTA_RAW.csv",
    "status": "PASS|FAIL",
    "metrics": {
        "bars_total": 5000,
        "duplicates": 0,
        "monotonic_errors": 0,
        "max_gap_bars": 0
    }
}
```
**Constraint**: Validator is a pure logic module and must not write logs.

---

---

## 6. Troubleshooting
- **"Gap Detected in RAW"**: If `raw_update` reports a gap between file-end and API-start, you missed a window.
  - *Mitigation:* Manually patch or accept gap (document in `data_update_log.txt`).
- **"Hash Mismatch"**: If binding implies old hash, generate new binding for new data version.
- **MT5 Disconnect**: Restart Terminal and retry Step 3.1.

---

## 7. Operational Log
Maintain `SOP/logs/data_update_log.txt`:
```text
[YYYY-MM-DD HH:MM]
- RAW Append: BTC (+1440 bars), XAU (+1440 bars)
- Metrics: 0 Dupes, 0 Gaps
- Version: v17.20251211
- Operator: Agent
```

---

## CHANGELOG
- **Rev3 (2025-12-13)**: Added Section 5A defining mandatory dataset validation rules (SOP17). Corrected spec: Zero tolerance for Crypto gaps, strict intra-week validaton for FX, removed unauthorized OHLC rule, and enforced pure validator logic.
