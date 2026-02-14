# Enforcement Proposals for SOP_CLEANUP.md

## 1. Pre-Run Enforcement (Gatekeeper)

**Enforcement Surface:** `tools/run_stage1.py` (Execution Harness) & `governance/preflight.py`

**Mechanism:**
1.  **Read-Before-Write:** The harness MUST read `backtests/Strategy_Master_Filter.xlsx` before initializing the engine.
2.  **Invariant Check:** Check if `Directive.Strategy` matches any `Strategy` column in the Master Sheet.
3.  **Blocking Logic:**
    *   **If Row Exists:** Return `HARD_STOP`. Error message: *"Strategy '{Name}' already exists in Master Sheet (Row {N}). Verification Failed: 1-Strategy-1-Row Invariant. Action: Remove row from Master Sheet to proceed."*
    *   **If Row Missing but Folder Exists (`backtests/<strategy>`):** Return `HARD_STOP`. Error message: *"Zombie Artifact detected. Strategy folder exists but is unindexed. Action: Run cleanup tool or manually delete folder."*

**Failure Handling:**
*   Execution aborts immediately (Exit Code 1).
*   No artifacts are created.
*   User must perform manual (or tool-assisted) cleanup to clear the block.

**Pros/Cons:**
*   *Pros:* Guarantees strictly no collisions; enforces "Master Sheet as Source of Truth" by forcing user to interact with it to "free up" the slot.
*   *Cons:* Requires user intervention for re-runs (feature, not bug per SOP).

## 2. Post-Run Enforcement (Commitment)

**Enforcement Surface:** `tools/stage3_compiler.py` (The Indexer)

**Mechanism:**
1.  **Atomic Materialization:** The runner executes execution logic and writes `backtests/<strategy>/` output.
2.  **Conditional Indexing:** `stage3_compiler.py` is invoked immediately after run completion.
3.  **Validation Gate:**
    *   Verify `run_metadata.json` exists and `run_id` is unique.
    *   Verify `runs/<run_id>` exists (Persistence).
4.  **Transaction:**
    *   Append Row to Master Sheet.
    *   *If Write Fails (e.g., file lock):* The run is now "Unindexed/Zombie".
    *   **Auto-Rollback (Proposed):** If the Sheet update fails, the script should rename `backtests/<strategy>` to `backtests/<strategy>_FAILED_<timestamp>` or delete it immediately to prevent "Zombie" accumulation.

**Failure Handling:**
*   If Master Sheet is locked: Retry 3x -> Fail -> Trigger Auto-Rollback (Delete Artifacts).
*   Alert User: *"Run passed but Indexing failed. Artifacts scrubbed to maintain consistency."*

**Pros/Cons:**
*   *Pros:* Prevents "Ghost Runs" (files exist, no index).
*   *Cons:* Valid run data might be lost if Excel is open (File Lock).

## 3. Periodic / Recovery Enforcement (The Janitor)

**Enforcement Surface:** New Tool `tools/maintenance/integrity_sweep.py`

**Mechanism:**
1.  **Load Truth:** Read `backtests/Strategy_Master_Filter.xlsx` into `Set<RunID>` and `Set<StrategyName>`.
2.  **Scan Artifacts:** List `backtests/*` and `runs/*`.
3.  **Logic Matrix:**
    *   **Orphaned Row:** Row exists, but `backtests/<Strategy>` OR `strategies/<RunID>` missing.
        *   *Action:* **Remove Row**. (The reality of the filesystem overrides the claim of the sheet if data is gone).
    *   **Zombie Folder:** `backtests/<Strategy>` exists, but `<Strategy>` not in Sheet.
        *   *Action:* **Delete Folder**. (Unindexed data is trash).
    *   **Zombie Run Snapshot:** `runs/<RunID>` exists, but `<RunID>` not in Sheet.
        *   *Action:* **Delete Folder**.
    *   **Identity Mismatch:** `backtests/<Strategy>/metadata` says `RunID=A`, Sheet says `RunID=B`.
        *   *Action:* **Trust Sheet**. Warn user. If Sheet points to non-existent B, it's an Orphaned Row (Delete Row). Then `backtests/<Strategy>` becomes a Zombie (Delete Folder).

**Operational Mode:**
*   **Default:** `Dry-Run` (Report only).
*   **Enforce:** `--fix` flag (Automatic deletion/modification).
*   *Notification:* Summary report generated in `outputs/logs/integrity_report.md`.

**Pros/Cons:**
*   *Pros:* Self-healing system; strict adherence to SOP.
*   *Cons:* Destructive. "Delete First" policy assumes unindexed data is worthless (aligned with SOP).
