---
name: update-vault
description: Create a vault snapshot of the current workspace state
---

# /update-vault — Vault Snapshot Workflow

This workflow creates a point-in-time archive of the full workspace into
`vault/snapshots/`. It follows the ENGINE_VAULT_CONTRACT.md (§4A, §11).

> **IMPORTANT**: This workflow captures the workspace — it is NOT an engine-only
> promotion (see §4 of ENGINE_VAULT_CONTRACT.md for that process).

---

## Pre-Conditions

Before creating a snapshot, confirm:

1. All governance changes are committed and tested.
2. Preflight passes cleanly.
3. No temp files in `tools/` (run `/cleanup-directive` if needed).
4. No pending directive work in progress.

---

## Step 1: Read the Engine Vault Contract

// turbo

Read `governance/SOP/ENGINE_VAULT_CONTRACT.md` — specifically §4A and §11.
Confirm you understand the separation between engine vault and workspace snapshots.

---

## Step 2: Verify Clean State

// turbo

Run the cleanup reconciler in dry-run mode to confirm no orphaned artifacts:

```bash
python tools/cleanup_reconciler.py
```

Expected: **0 actions remaining**.

If actions exist, run `/cleanup-directive` first.

---

## Step 3: Verify Preflight

// turbo

```bash
python governance/preflight.py
```

All checks must PASS. Do NOT proceed with a failing preflight.

---

## Step 4: Create Workspace Snapshot

// turbo

```bash
python tools/create_vault_snapshot.py
```

This auto-generates the snapshot name as `DR_BASELINE_<YYYY_MM_DD>_v<version>`.

To use a custom name:

```bash
python tools/create_vault_snapshot.py --name CUSTOM_SNAPSHOT_NAME
```

---

## Step 5: Verify Snapshot

// turbo

Confirm the snapshot was created and the manifest is valid:

```bash
python -c "import json; m = json.load(open('vault/snapshots/DR_BASELINE_%DATE%/vault_manifest.json')); print(f'Snapshot: {m[\"snapshot_name\"]}'); print(f'Files: {m[\"total_files\"]}'); print(f'Timestamp: {m[\"timestamp_utc\"]}')"
```

Replace `%DATE%` with today's snapshot directory name (listed in the Step 4 output).

---

## Step 6: Report

Report the following to the human:

- Snapshot name
- Total files captured
- Manifest path
- Any files that were skipped

---

## Step 7: Update System State

// turbo

Generate a final snapshot of the system state to log the new engine version into the top-level repo log.

```bash
python tools/system_introspection.py
```

---

## Optional: Engine-Only Promotion (§4)

If the engine version has changed and needs vault promotion:

1. Confirm engine passes preflight + full pipeline.
2. Copy the validated engine:

```bash
xcopy /E /I engine_dev\universal_research_engine\<version> vault\engines\Universal_Research_Engine\<version>
```

1. Verify the copy matches the source (hash comparison).
2. The engine vault directory is now **immutable** — never modify it.

This step is separate from the workspace snapshot and is only needed when promoting
a new engine version.
