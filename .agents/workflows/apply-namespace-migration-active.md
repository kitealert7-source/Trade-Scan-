---
description: Convert legacy directives in backtest_directives/active to governed namespace format
---

## Apply Namespace Migration (Active)

Use this workflow to migrate legacy directives in `backtest_directives/active/`
to namespace-governed IDs while reserving sweeps only via the sweep gate.

### Preconditions

- `governance/namespace/idea_registry.yaml` is up to date.
- `governance/namespace/token_dictionary.yaml` is up to date.
- `governance/namespace/sweep_registry.yaml` is available.
- Close spreadsheets/editors that may lock directive files.

### Step 1: Run Migration Tool

```bash
python tools/convert_promoted_directives.py --source-dir backtest_directives/active --rename-strategies
```

Behavior:

- Creates backup folder automatically: `backtest_directives/active_backup/`
- Classifies FAMILY/MODEL/FILTER/SYMBOL/TF
- Resolves idea ID from registry
- Reserves sweep via `tools/sweep_registry_gate.py`
- Validates candidate directive via `tools/namespace_gate.py`
- Updates `test.name` and `test.strategy`
- Renames directive filename
- Optionally renames strategy folder and `Strategy.name` (`--rename-strategies`)

### Step 2: Review Conversion Summary

Check final counters:

- files scanned
- files converted
- files skipped
- namespace errors
- sweep collisions

If `sweep collisions > 0`, stop and resolve before running pipeline.

### Step 3: Run Provision-Only Validation

```bash
python tools/run_pipeline.py --all --provision-only
```

This validates canonicalization, namespace gate, sweep gate, preflight, and semantic checks
without executing backtests.

### Step 4: Proceed to Normal Execution

After human review/approval of strategy code:

```bash
python tools/run_pipeline.py --all
```
