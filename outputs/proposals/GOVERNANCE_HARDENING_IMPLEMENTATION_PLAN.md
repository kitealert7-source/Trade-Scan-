# Governance Hardening — Closed Box Implementation Plan

Three changes create a cryptographically enforced governance box with explicit human override points.

## Proposed Changes

### Phase 1: Remove Workspace Mode

#### [MODIFY] [verify_engine_integrity.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/verify_engine_integrity.py)

- **L42-51**: Remove `if mode == "workspace"` branch from `verify_hashes()`. All calls now execute strict SHA-256 verification.
- **L96-97**: Remove `if mode == "workspace": return True` from `verify_tools_integrity()`. Tools manifest is now always checked.
- **L171**: Remove `"workspace"` from `--mode` choices. Only `"strict"` remains (default). Keep `--mode` argument for forward compatibility but it only accepts `strict`.

#### [MODIFY] [preflight.py](file:///c:/Users/faraw/Documents/Trade_Scan/governance/preflight.py)

- **L30**: Remove `skip_vault_check: bool = False` parameter from `run_preflight()` signature.
- **L67-68**: Remove vault-check skip logic (`if not skip_vault_check and vault_path.exists()`). Vault check always runs if vault exists.
- **L80**: Remove `mode = "workspace" if skip_vault_check else "strict"`. Always pass `"strict"`.

#### [MODIFY] [exec_preflight.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/exec_preflight.py)

- **L67-72**: Remove `skip_vault_check=True` from `run_preflight()` call. Comment updated to reflect mandatory strict mode.

---

### Phase 2: Demote `--force` to Logged Governance Tool

#### [MODIFY] [reset_directive.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/reset_directive.py)

Full rewrite. New behavior:

- **Mandatory `--reason` argument**: Cannot reset without stating why.
- **Audit logging**: Appends reset event to `governance/reset_audit_log.csv` with columns: `timestamp, directive_id, previous_state, new_state, reason`.
- **Console confirmation**: Prints the logged event for human visibility.

#### [MODIFY] [run_pipeline.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/run_pipeline.py)

- **L203-209**: Replace `--force` handling. Instead of silently resetting to `INITIALIZED`, print a message directing the user to `tools/reset_directive.py` and exit with code 1.

```diff
 elif current_dir_state == "FAILED":
-     if "--force" not in sys.argv:
-         print(f"[ORCHESTRATOR] Directive {clean_id} is FAILED. Use --force to retry.")
-         sys.exit(1)
-     else:
-         print(f"[ORCHESTRATOR] Force retry enabled. Resetting to INITIALIZED.")
-         dir_state_mgr.transition_to("INITIALIZED")
+     print(f"[ORCHESTRATOR] Directive {clean_id} is FAILED.")
+     print(f"[ORCHESTRATOR] To reset, run: python tools/reset_directive.py {clean_id} --reason \"<justification>\"")
+     sys.exit(1)
```

---

### Phase 3: Guard-Layer Manifest

#### [MODIFY] [tools_manifest.json](file:///c:/Users/faraw/Documents/Trade_Scan/tools/tools_manifest.json)

Expand the existing manifest to include the **Critical Guard Set** (files that constitute the governance boundary):

| File | Role |
|---|---|
| `run_pipeline.py` | Orchestrator (already present) |
| `run_stage1.py` | Generator (already present) |
| `semantic_validator.py` | Identity + Behavioral Guard |
| `directive_schema.py` | Signature Authority |
| `strategy_provisioner.py` | Provisioning Gate |
| `exec_preflight.py` | Preflight Launcher |
| `strategy_dryrun_validator.py` | Runtime Guard |
| `pipeline_utils.py` | Shared State Logic |

> [!IMPORTANT]
> `verify_engine_integrity.py` is deliberately **excluded** from the manifest it verifies (self-referential hash is a circular dependency). Its integrity is protected by the engine manifest instead.

#### [MODIFY] [verify_engine_integrity.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/verify_engine_integrity.py)

- **L100-101**: Change `verify_tools_integrity()` from `[WARN]` on missing manifest to `[FAIL]` with `return False`. Manifest is now mandatory.

#### [NEW] [generate_guard_manifest.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/generate_guard_manifest.py)

Human-only utility script that:

1. Reads the Critical Guard Set file list.
2. Computes SHA-256 for each.
3. Writes `tools/tools_manifest.json`.
4. Prints summary to console.

> [!CAUTION]
> This script must **never** be called by the agent or by `run_pipeline.py`. It is a human-initiated maintenance tool only. `AGENT.md` will be updated to reflect this.

---

## Verification Plan

### Automated Tests

1. **Workspace Removal**: Run `python tools/verify_engine_integrity.py --mode workspace` → expect argument error (invalid choice).
2. **Force Removal**: Run `python tools/run_pipeline.py TEST_DIR --force` → expect "use reset_directive.py" message, exit code 1.
3. **Guard Manifest**: Temporarily modify a guard-layer file, run preflight → expect `[FAIL] Tools Integrity Failed`.
4. **Reset Audit**: Run `python tools/reset_directive.py TEST_DIR --reason "test"` → verify `governance/reset_audit_log.csv` contains entry.

### Manual Verification

1. Confirm `AGENT.md` references the new reset protocol and manifest policy.
