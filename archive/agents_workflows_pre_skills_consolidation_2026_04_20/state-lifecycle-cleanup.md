---
description: Perform State Lifecycle Lineage-Aware Cleanup
---

This workflow executes the structured Lineage-Aware State Lifecycle sequence to safely identify, map, and prune abandoned pipelines, backtests, and artifacts while maintaining absolute referential integrity.

**Critical Authority Note:** Absolute deletion and preservation authority originates SOLELY from three top-down sources: `Master_Portfolio_Sheet.xlsx`, `Filtered_Strategies_Passed.xlsx`, and `portfolio.yaml` execution shield.
If a run or portfolio identifier is documented in these active spreadsheets or shielded by the execution config, all its corresponding staging footprint directories across `TradeScan_State/runs`, `TradeScan_State/backtests`, `TradeScan_State/sandbox`, `TradeScan_State/strategies`, and `Trade_Scan/strategies` are natively shielded.
Anything absent from these central lists is mathematically defined as "abandoned" and will be formally pruned by Phase 4.

### Phase 1: Hydrate Pre-Flight State

If raw runtime folders exist in the initial staging sandbox but failed to push to the evaluation tracks natively, we must hydrate them safely across native bounds before doing referential queries.

// turbo

```powershell
python tmp/hydrate_sandbox.py
```

### Phase 2: Diagnose & Repair Structural Decay

(Optional) Automatically locate missing strings from active tracking spreadsheets `Master_Portfolio_Sheet.xlsx` and `Filtered_Strategies_Passed.xlsx` against physical files on disk, actively dropping rows/portfolios that contain no live counterparts. This neutralizes structural database decay.

```powershell
python tools/state_lifecycle/repair_integrity.py
```

### Phase 3: Validate Quarantine Sequence (Dry Run)

Evaluate the physical tracking geometries strictly across Master and Filtered lists without running mutations. Will abort immediately if invariants fail (e.g. if a mapped run ID lacks a physical directory). Outputs grouped counts natively.

```powershell
python tools/state_lifecycle/lineage_pruner.py
```

### Phase 4: Execute Formal Lineage Cleanup

Physically sequence all unmapped abandoned elements structurally out of active processing areas (`runs/`, `backtests/`, `directives/`, `strategies/`) directly into an isolated snapshot directory natively under `TradeScan_State/quarantine/`.

```powershell
python tools/state_lifecycle/lineage_pruner.py --execute
```

**Note:** If Phase 3/4 is blocked by a stale TS_Execution PID, verify the process is dead and re-run with `--force-unlock`:
```powershell
python tools/state_lifecycle/lineage_pruner.py --force-unlock
python tools/state_lifecycle/lineage_pruner.py --force-unlock --execute
```

### Phase 5: Aesthetic Validation & Formatting

Finally, execute the native formatting engines over the surviving matrices to physically ensure visual constraints (Data Bars, Ranking, Status Highlighting) are perfectly maintained.

// turbo
```powershell
python tools/format_excel_artifact.py --file "C:\Users\faraw\Documents\TradeScan_State\candidates\Filtered_Strategies_Passed.xlsx" --profile strategy
python tools/format_excel_artifact.py --file "C:\Users\faraw\Documents\TradeScan_State\strategies\Master_Portfolio_Sheet.xlsx" --profile portfolio
```
