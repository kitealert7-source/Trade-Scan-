# System Maintenance Workflow

This workflow is the **Unified Operational Hub** for TradeScan. It covers system health, workspace hygiene, recovery operations, and vault management. These tasks are non-authoritative over the execution pipeline but essential for stability.

---

### 1. System Health Audit (Preflight)
Run this read-only check to detect integrity violations or filesystem drift.

// turbo
```powershell
python tools/system_preflight.py
```
- **RED**: **HALT**. Resolve integrity issues (Registry/Manifest/Data coverage) before execution.
- **YELLOW**: Inspect `strategies/` for untracked drift files.
- **GREEN**: System is healthy for execution.

---

### 2. State Lifecycle & Artifact Cleanup
**[SUPERSEDED]**: All native repository reconciliation and artifact pruning operations have been mathematically centralized into the strict **State Lifecycle Management** API.

To deterministically dry-run or physically execute a formal purge of abandoned structures across the entire pipeline based on your Master ledgers, trigger the dedicated Lifecycle workflow instead:

**Trigger Cross-Workflow:**
```markdown
/state-lifecycle-cleanup
```

---

### 3. Recovery & State Reset (Authorized Only)
Institutionalized tools for resetting corrupted or experimental states.

| Scenario | Command | Risk |
| :--- | :--- | :--- |
| **Directive Reset** | `python tools/reset_directive.py <ID> --reason "<justification>"` | LOW |
| **Full State Reset** | `python tools/reset_runtime_state.py --confirm` | **HIGH** |

---

### 4. Pipeline Validation (Smoke Tests)
Run regression fixtures to validate the end-to-end pipeline path.

// turbo
```powershell
python tools/tests/run_pipeline_smoke_fixture.py
```
*Expected: Exit code 0 and `[DONE] Pipeline smoke fixture PASSED.`*

---

### 5. Vault & Snapshot Management
Create point-in-time archives per `ENGINE_VAULT_CONTRACT.md`.

**Create Snapshot:**
```powershell
python tools/create_vault_snapshot.py --name "DR_BASELINE_$(Get-Date -f yyyy_MM_dd)"
```

**Verify Manifest:**
Confirm `vault/snapshots/<NAME>/vault_manifest.json` is valid and total files match.

---

### 6. Artifact Aesthetics (Formatting)
Stylize Excel ledgers for research presentation.

// turbo
```powershell
python tools/format_excel_artifact.py --file "backtests/Strategy_Master_Filter.xlsx" --profile strategy
python tools/format_excel_artifact.py --file "strategies/Filtered_Strategies_Passed.xlsx" --profile strategy
python tools/format_excel_artifact.py --file "strategies/Master_Portfolio_Sheet.xlsx" --profile portfolio
```

---

### 7. Legacy & Migration Utilities
*Use these only during transition periods.*

**Namespace Migration:**
```powershell
python tools/convert_promoted_directives.py --source-dir backtest_directives/INBOX --rename-strategies
```

---

### Maintenance Rules & Constraints
- **Idempotence**: Cleanup should converge to zero actions.
- **Independence**: Strategy and Portfolio layers must remain strictly independent.
- **No Manual Deletion**: Use reconcile/reset tools to maintain ledger integrity.
- **Protected Paths**: Never delete `vault/`, `governance/`, or `deployable/` folders.

### Reference: System Contract
The system is: **Deterministic, Ledger-authoritative, Append-only, Fail-fast, Non-mutating.**
Maintenance must never alter the `tier` or `status` of a registered run without a justification log.
