# Go-Live Package Compatibility Audit

**Date:** 2026-04-03 | **Updated:** 2026-04-12
**Status:** ARCHIVED — All gaps identified in this audit have been resolved. See resolution summary below.
**Scope:** `tools/generate_golive_package.py`, `execution_engine/strategy_guard.py`, `tools/validate_safety_layers.py`, and their integration with the current promotion/burn-in pipeline.

---

## Resolution Summary (2026-04-12)

Option B (Merge Go-Live Into Dry-Run Vault) was **fully implemented** via the Deployment Unification Plan:

| Gap (from Section 7) | Resolution | Date |
|---|---|---|
| No signal integrity verification | `strategy_guard.py` wired into TS_Execution via `guard_bridge.py`; two-tier `validate_signal()` | 2026-04-12 |
| No kill-switch in live execution | `record_trade()` hooked into shadow exit + reconcile close; 3-rule kill-switch active | 2026-04-12 |
| No profile hash verification | `_verify_profile_hash()` called by `from_vault()` at startup (when extended vault format present) | 2026-04-12 |
| Stale conversion artifacts | `generate_golive_package.py` archived to `archive/tools/` | 2026-04-12 |
| Validation script broken | `validate_safety_layers.py` rewritten: 6 vault-based tests, all pass | 2026-04-12 |
| Broker specs not in vault | Added by `promote_to_burnin.py` Phase 1 | 2026-04-09 |
| `selected_profile.json` not in vault | Added by `promote_to_burnin.py` Phase 1 | 2026-04-09 |

**Current file status:**

| Component | Location | Status |
|-----------|----------|--------|
| `generate_golive_package.py` | `archive/tools/` | ARCHIVED — dead code |
| `test_generate_golive_package_helpers.py` | `archive/tests/` | ARCHIVED |
| `strategy_guard.py` | `execution_engine/` | ACTIVE — extended with `from_vault()`, `validate_signal()`, `SignalResult` |
| `validate_safety_layers.py` | `tools/` | REWRITTEN — 6 vault-based tests |
| `guard_bridge.py` | `TS_Execution/src/` | NEW — vault-based guard construction |

**This audit is retained for historical reference. No further action required.**

---

## 1. Executive Summary

The go-live package generator (`generate_golive_package.py`) and its companion safety layer (`strategy_guard.py`) were built on 2026-03-11 during the v1.5.3 era. Since then, the capital system underwent a major overhaul (2026-04-03): dynamic FX conversion was replaced with MT5 static valuation, and a new burn-in promotion pipeline was added. Leverage cap is **5x** (Invariant 20: $1,000/symbol, $10,000 total portfolio, 5x cap).

> **2026-04-12 Update:** Option B **fully implemented**. `generate_golive_package.py` archived. `strategy_guard.py` extended with `from_vault()` and wired into TS_Execution. `validate_safety_layers.py` rewritten with 6 vault-based tests. All deployment safety gaps closed.

**Current status:**

| Component | Importable? | Executable? | Aligned with current system? |
|-----------|-------------|-------------|------------------------------|
| `generate_golive_package.py` | ARCHIVED | ARCHIVED | N/A — retired |
| `strategy_guard.py` | YES | YES | YES — extended with `from_vault()`, wired into TS_Execution |
| `validate_safety_layers.py` | YES | YES — all 6 tests pass | YES — rewritten for vault layout |
| `guard_bridge.py` (NEW) | YES | YES | YES — vault path resolution + guard construction |

**Key finding:** ~~The go-live package generator is functionally orphaned.~~ **Resolved:** go-live package archived; all safety capabilities merged into vault-based guard system.

---

## 2. Current Pipeline Topology: Research to Execution

```
AUTOMATED PIPELINE (tools/run_pipeline.py)
  Directive in INBOX/
    |
    v
  Stage 0: Preflight (namespace, token, semantic validation)
  Stage 1: Backtest (engine per-symbol, trade-level results)
  Stage 2: Compile (per-symbol result compilation)
  Stage 3: Aggregate (Strategy_Master_Filter.xlsx + cardinality gate)
  Stage 3a: Manifest Binding (artifact hashing, run close)
  Stage 4: Portfolio Evaluation
    |-- Step 4: portfolio_evaluator.py -> Master_Portfolio_Sheet.xlsx
    |-- Step 7: portfolio_evaluator.py -> deployed_profile selection (SOLE AUTHORITY)
    |-- Step 8: capital_wrapper.py -> deployable/ artifacts (7 profiles)
    |-- Step 8.5: profile_selector.py -> validator/enricher only (reads Step 7 choice)
    |-- Step 9: artifact verification
    v
  PORTFOLIO_COMPLETE (terminal success state)
    |
    v
  Post-pipeline: filter_strategies.py -> Filtered_Strategies_Passed.xlsx
    (candidate_status: CORE / WATCH / FAIL / BURN_IN)
    |
    v
  Directive archived to completed/

MANUAL PROMOTION (human decision via promote_to_burnin.py)
    |
    v
  promote_to_burnin.py: vault snapshot + portfolio.yaml append (atomic)
    |
    v
  filter_strategies.py auto-detects -> sets BURN_IN status in candidate ledger
    |
    v
  cleanup_reconciler.py protects BURN_IN runs from cleanup
  lineage_pruner.py builds execution shield from portfolio.yaml

LIVE EXECUTION (TS_Execution)
    |
    v
  startup_launcher.py -> MT5 + watchdog + src/main.py --phase 2
  watchdog_daemon.py -> heartbeat polling, auto-restart
  stop_execution.py -> clean shutdown on market close
```

### Where the Go-Live Package Fits (and Doesn't)

The go-live package generator was designed as **Stage 10** -- a manual, post-pipeline step to assemble deployment artifacts. However:

1. It is **not registered** in the StageRunner (`tools/orchestration/runner.py`)
2. It is **not called** by `run_pipeline.py` at any point
3. The promotion flow (`filter_strategies.py` -> `portfolio.yaml` -> BURN_IN) **bypasses it entirely**
4. `strategy_guard.py` consumes go-live artifacts but is only used by TS_Execution -- no reference from Trade_Scan pipeline code

**The current deployment path is (2026-04-10):**
```
PORTFOLIO_COMPLETE -> Step 7 (deployed_profile selection) -> Step 8 (capital_wrapper)
  -> Step 8.5 (profile enrichment) -> promote_to_burnin.py (vault + portfolio.yaml)
  -> TS_Execution reads portfolio.yaml directly
```

**The designed deployment path was:**
```
PORTFOLIO_COMPLETE -> Stage 10 (generate_golive_package) -> golive/ artifacts
  -> strategy_guard verifies signals -> TS_Execution executes
```

These two paths have **diverged**. The current system operates without go-live packages.

### What Replaced the Go-Live Package in Practice

Three workflows and tools were built to fill the deployment gap, each covering a subset of what the go-live package was designed to provide:

**1. Dry-Run Vault Workflow (`.agents/workflows/dry-run-vault.md` + `tools/backup_dryrun_strategies.py`)**

Captures a point-in-time snapshot of all backtest artifacts for the burn-in cohort into `DRY_RUN_VAULT/` (outside all repos, immutable, append-only). Per strategy:
```
DRY_RUN_VAULT/DRY_RUN_{DATE}/{STRATEGY_ID}/
  directive.txt, strategy.py, meta.json (git commit + config_hash),
  portfolio_evaluation/ (full), deployable/profile_comparison.json,
  backtests/{ID}_{SYMBOL}/ (metadata + raw CSVs)
```
**Overlap with go-live:** Captures directive, strategy.py, deployable artifacts, broker-adjacent metadata. Does NOT embed broker spec snapshots, conversion data, profile hash, enriched trade log, or execution spec. Does NOT construct a strategy guard.

**2. Portfolio Selection Workflows (`.agents/workflows/portfolio-selection-add.md`, `portfolio-selection-remove.md`)**

Manages `IN_PORTFOLIO` flag flow:
```
Filtered_Strategies_Passed.xlsx -> --save -> in_portfolio_selections.json -> --apply -> Strategy_Master_Filter.xlsx
```
Operator adds/removes strategies from the live selection. `filter_strategies.py` then auto-detects entries in `TS_Execution/portfolio.yaml` and sets `candidate_status = BURN_IN`.

**Overlap with go-live:** Manages which strategies enter live execution. Go-live package was designed to be the gate between "selected" and "deployed" -- this flow bypasses that gate.

**3. Execution Shield (cleanup_reconciler.py + lineage_pruner.py)**

BURN_IN strategies are protected from cleanup and quarantine. `lineage_pruner.py` reads `portfolio.yaml` directly to build an execution shield -- any strategy in the deployed set is blocked from deletion.

**Overlap with go-live:** Protects deployed artifacts. Go-live package's profile hash verification and signal integrity serve the same "protect deployed state" goal, but at runtime rather than cleanup time.

### Coverage Comparison

| Capability | Go-Live Package | Current System | Gap? |
|------------|----------------|----------------|------|
| Freeze directive + strategy.py | YES (golive/) | YES (DRY_RUN_VAULT) | No |
| Freeze broker specs | YES (broker_specs_snapshot/) | YES (vault/broker_specs_snapshot/) | **CLOSED** (2026-04-09) |
| Profile param hash (tamper detection) | YES (SHA-256) | YES (`_verify_profile_hash()` in `from_vault()`) | **CLOSED** (2026-04-12) |
| Signal hash fingerprints (integrity) | YES (enriched_trade_log.csv) | YES (`validate_signal()` two-tier) | **CLOSED** (2026-04-12) |
| Kill-switch (loss streak/WR/DD) | YES (strategy_guard.py) | YES (wired into TS_Execution via `guard_bridge.py`) | **CLOSED** (2026-04-12) |
| Execution spec (human-readable) | YES (execution_spec.md) | NO | Accepted — burnin_monitor.md serves this role |
| Deployment selection tracking | NO | YES (IN_PORTFOLIO + portfolio.yaml) | No |
| BURN_IN status automation | NO | YES (filter_strategies.py) | No |
| Cleanup protection | NO | YES (execution shield) | No |
| Artifact immutability guarantee | NO | YES (vault invariants) | No |

**Summary (2026-04-12):** All runtime safety gaps have been closed. Signal verification, kill-switch, profile tamper detection, and broker spec freezing are all active. The only remaining difference is the human-readable `execution_spec.md` which is adequately replaced by burn-in monitoring docs.

---

## 3. Go-Live Package Generator: Detailed Assessment

### 3.1 What It Produces

```
strategies/<PREFIX>/golive/
  run_manifest.json            -- engine metadata, symbols, data window, seed
  symbols_manifest.json        -- symbol-broker mapping
  selected_profile.json        -- capital profile params + integrity hash
  directive_snapshot.yaml       -- frozen directive copy
  enriched_trade_log.csv       -- deployable trades + Stage-1 fields
  broker_specs_snapshot/       -- frozen broker YAMLs per symbol
  conversion_data_manifest.json -- FX conversion pair metadata
  conversion_data_snapshot/    -- daily close CSVs for conversion pairs
  execution_spec.md            -- human-readable execution parameters
  golive_checklist.md          -- sign-off checklist
```

### 3.2 Stale Components

| Component | Status | Detail |
|-----------|--------|--------|
| `CONVERSION_MAP` import | STALE | Still exists in capital_wrapper.py but references the old dynamic FX conversion model. The current system uses MT5 static valuation. Go-live package would embed conversion pair data that the simulation no longer uses. |
| `_parse_fx_currencies` import | STALE | Same -- still exists but serves the old conversion model. |
| `conversion_data_manifest.json` | UNNECESSARY | Conversion pair data is no longer consumed by the capital simulation. Embedding it in the package adds dead weight. |
| `conversion_data_snapshot/` | UNNECESSARY | Daily close CSVs for conversion pairs -- not used by MT5 static valuation. |
| `ENGINE_VERSION = "1.6"` | STALE | Self-assigned version label. Research engine is v1.5.4. |
| `selected_profile.json: max_leverage` | OK | Generator reads from PROFILES dict. Current leverage cap is 5x (Invariant 20). |

### 3.3 What Still Works

| Component | Status |
|-----------|--------|
| `run_manifest.json` generation | OK -- engine metadata, seed, data window |
| `symbols_manifest.json` generation | OK -- symbol list from directive |
| `selected_profile.json` generation | OK -- reads current PROFILES dict, hash is correct |
| `directive_snapshot.yaml` | OK -- copies directive verbatim |
| `enriched_trade_log.csv` | OK -- joins deployable trade log with Stage-1 fields |
| `broker_specs_snapshot/` | OK -- copies current YAMLs (now MT5-verified) |
| `execution_spec.md` | OK -- human-readable summary |
| `golive_checklist.md` | OK -- sign-off template |
| Profile hash integrity | OK -- SHA-256 of enforcement+sizing, deterministic |

### 3.4 Import and Execution Status

- **Imports:** All resolve. `CONVERSION_MAP`, `_parse_fx_currencies`, `PROFILES`, `SIMULATION_SEED` are all present in `capital_wrapper.py`.
- **Execution:** Would run without crash. Would produce all artifacts. The conversion_data artifacts are unnecessary but not harmful.

---

## 4. Strategy Guard: Detailed Assessment

### 4.1 Architecture

Fully self-contained module with zero project imports. Uses only stdlib (`csv`, `hashlib`, `json`, `logging`, `dataclasses`, `pathlib`, `typing`).

Two mechanisms:
1. **Signal Integrity Guard** -- compares live signal hashes against `deployable_trade_log.csv` fingerprints. Blocks on mismatch.
2. **Statistical Deviation Guard** -- 3 kill-switch rules:
   - Loss streak > historical max x 1.5
   - Rolling win rate (50 trades) < historical WR x 0.65
   - Equity drawdown > 2x historical max DD

### 4.2 Compatibility

| Aspect | Status |
|--------|--------|
| Import | OK -- no project dependencies |
| Hash formula | OK -- `sha256(symbol|ts|dir|price|dist)[:16]`, matches `capital_wrapper.compute_signal_hash()` |
| Profile hash verification | OK -- recomputes from `selected_profile.json` |
| Baseline stats derivation | OK -- reads `deployable_trade_log.csv` + `selected_profile.json` |
| Kill-switch thresholds | OK -- configurable via `GuardConfig` dataclass |

### 4.3 Integration Gap

`strategy_guard.py` expects to be constructed from a go-live package:
```python
guard = StrategyGuard.from_golive_package(golive_dir=..., profile=...)
```

**Current TS_Execution does not use this.** It reads `portfolio.yaml` directly and manages its own trade execution. The strategy guard is available but not wired into the execution loop.

---

## 5. Validation Script: Broken

### `tools/validate_safety_layers.py`

| Issue | Line(s) | Severity |
|-------|---------|----------|
| `emit_profile_artifacts(state, tmp)` called with 2 args; function requires 4 (`total_runs`, `total_assets`) | 77, 118, 119 | CRASH (TypeError) |
| `PROJECT_ROOT / "strategies"` should be `TradeScan_State/strategies/` | 30 | CRASH (FileNotFoundError) |

This script has not been maintained since 2026-03-11 and cannot run in its current state.

---

## 6. Compatibility Matrix

| Current System Component | Go-Live Package | Strategy Guard | Notes |
|--------------------------|----------------|----------------|-------|
| MT5 static valuation | PARTIAL -- embeds stale conversion artifacts | N/A | Broker spec snapshots are correct; conversion data is dead weight |
| FIXED_USD_V1 (leverage 5x) | OK -- reads current PROFILES dict | OK -- reads selected_profile.json | Profile params are current if package is regenerated |
| Capital wrapper Step 8 output | OVERLAPS -- go-live enriches the same trade log | CONSUMES | Go-live reads Step 8 output and enriches it |
| Profile selector Step 8.5 | NOT INTEGRATED -- go-live has own profile param embedding | N/A | Two parallel profile-embedding paths exist |
| filter_strategies.py promotion | BYPASSED -- promotion doesn't trigger go-live | N/A | BURN_IN status set without go-live package |
| portfolio.yaml deployment | BYPASSED -- TS_Execution reads yaml directly | NOT WIRED | Guard expects go-live dir, execution uses yaml |
| Candidate ledger (BURN_IN) | NOT AWARE | NOT AWARE | Go-live package doesn't check or update BURN_IN status |

---

## 7. Gap Analysis

### 7.1 Gaps That Block Deployment Safety

1. **No signal integrity verification in live execution.** The strategy guard exists and works, but TS_Execution does not call it. Live trades execute without hash verification against research fingerprints.

2. **No kill-switch in live execution.** The 3-rule statistical deviation guard exists but is not wired into the execution loop. A live strategy can enter an unbounded loss streak without automated halt.

3. **No profile hash verification at startup.** The go-live package embeds a SHA-256 profile hash, and the guard verifies it at construction. But since the guard is not constructed, the hash is never checked. If someone manually edits portfolio.yaml sizing params, there is no automated detection.

### 7.2 Gaps That Are Non-Blocking but Create Debt

4. **Stale conversion artifacts.** The go-live package embeds FX conversion pair data that the simulation no longer uses. Not harmful but misleading.

5. **Validation script broken.** `validate_safety_layers.py` cannot run. The 5-test acceptance suite (signal hash, reproducibility, mismatch blocking, kill-switch) has no automated coverage.

6. **Two parallel profile-embedding paths.** Step 7 (portfolio_evaluator) selects `deployed_profile` and writes to the Master Portfolio Sheet (sole authority). Step 8.5 (profile_selector) is a read-only enricher. Go-live writes `selected_profile.json` independently. These could diverge if package is regenerated from stale state.

7. **ENGINE_VERSION label stale.** Go-live package writes `1.6` while research engine is `1.5.4`. Cosmetic but confusing.

---

## 8. Remediation Options

### Option A: Retire Go-Live Package (Minimal)

Archive `generate_golive_package.py` and `strategy_guard.py`. Document that deployment uses the `portfolio.yaml` direct path + DRY_RUN_VAULT for baseline snapshots. Accept that runtime safety (signal verification, kill-switch) is not active.

**What you keep:** DRY_RUN_VAULT snapshots (directive, strategy.py, metrics, trade logs), IN_PORTFOLIO selection flow, BURN_IN automation, execution shield.

**What you lose:** Signal hash verification, kill-switch (loss streak/WR/DD), profile tamper detection, broker spec freezing.

**Effort:** 1 hour (archive files, update reports)
**Risk:** No runtime safety layer. A corrupted strategy.py or modified portfolio.yaml sizing params would not be detected until manual review.

### Option B: Merge Go-Live Into Dry-Run Vault (Targeted)

Keep the dry-run vault as the deployment snapshot mechanism but extend it with the go-live package's unique safety artifacts:

1. Add broker spec snapshot to `backup_dryrun_strategies.py` (copy `OctaFx/*.yaml` per symbol)
2. Add `selected_profile.json` with SHA-256 hash to vault per strategy
3. Add signal hash column to the vaulted trade log (already in `deployable_trade_log.csv`)
4. Wire `strategy_guard.py` into TS_Execution startup -- construct from vault path instead of `golive/` dir
5. Remove stale conversion artifacts from `generate_golive_package.py` or retire it entirely

**What you get:** Single deployment snapshot path (vault), with runtime verification (guard reads from vault).

**Effort:** 1-2 days
**Risk:** Low -- extends existing working infrastructure rather than introducing new paths.

### Option C: Integrate Go-Live as Pipeline Stage (Full)

Register go-live as an automated post-Step-9 stage:
1. Auto-generate go-live package after profile selection
2. Dry-run vault snapshot triggers automatically at the same time
3. Strategy guard constructs from go-live artifacts at TS_Execution startup
4. Signal hash verification on every live trade
5. Kill-switch monitoring active
6. Profile hash drift detection at startup

**Effort:** 2-3 days
**Risk:** Highest value but creates a second snapshot path alongside DRY_RUN_VAULT. Need clear ownership: vault = human-readable baseline, golive = machine-readable runtime contract.

### Recommendation

**Option B was fully implemented (2026-04-12).** Items 1-3 (broker specs, selected_profile.json, signal hashes in trade logs) were implemented 2026-04-09 via `promote_to_burnin.py` vault extension. Items 4-5 (guard wiring into TS_Execution, go-live retirement) were implemented 2026-04-12 via Deployment Unification Plan Phase 2-5. Go-live package archived to `archive/tools/`.

---

## 9. File Index

### Go-Live Package (2026-03-11, ARCHIVED 2026-04-12)

| File | Location | Status |
|------|----------|--------|
| `generate_golive_package.py` | `archive/tools/` | ARCHIVED — superseded by vault-based deployment |
| `strategy_guard.py` | `execution_engine/` | ACTIVE — extended with `from_vault()`, `validate_signal()`, wired into TS_Execution |
| `validate_safety_layers.py` | `tools/` | REWRITTEN — 6 vault-based tests, all pass |
| `test_generate_golive_package_helpers.py` | `archive/tests/` | ARCHIVED |
| `guard_bridge.py` | `TS_Execution/src/` | NEW — vault path resolution, guard construction, MismatchTracker |

### Current Deployment Path (active, maintained)

| File | Location | Role |
|------|----------|------|
| `backup_dryrun_strategies.py` | `tools/` | Dry-run vault snapshot script |
| `filter_strategies.py` | `tools/` | Candidate promotion, BURN_IN status from portfolio.yaml |
| `portfolio_evaluator.py` | `tools/` | Stage-4 portfolio analysis, ledger write |
| `profile_selector.py` | `tools/` | Step 8.5, best profile selection, ledger enrichment |
| `capital_wrapper.py` | `tools/` | Step 8, multi-profile capital simulation |
| `sync_portfolio_flags.py` | `tools/` | IN_PORTFOLIO flag persistence (--save/--apply/--clear) |
| `cleanup_reconciler.py` | `tools/` | BURN_IN protection during cleanup |
| `lineage_pruner.py` | `tools/state_lifecycle/` | Execution shield from portfolio.yaml |

### Workflows (`.agents/workflows/`)

| Workflow | Purpose |
|----------|---------|
| `dry-run-vault.md` | Snapshot backtest artifacts before burn-in into DRY_RUN_VAULT/ |
| `portfolio-selection-add.md` | Add strategy to live portfolio (IN_PORTFOLIO flag) |
| `portfolio-selection-remove.md` | Remove strategy from live portfolio |
| `update-vault.md` | Full workspace snapshot into vault/snapshots/ |
| `execute-directives.md` | Pipeline execution workflow |

### Orchestration (`tools/orchestration/`)

| File | Role |
|------|------|
| `startup_launcher.py` | MT5 + watchdog + TS_Execution launch |
| `watchdog_daemon.py` | Heartbeat monitor, auto-restart |
| `stop_execution.py` | Clean shutdown at market close |
| `pre_execution.py` | Directive identity, consistency gate |

---

*Generated: 2026-04-03 | Updated: 2026-04-12 | Status: ARCHIVED — all gaps resolved. Audit covers: research pipeline stages 0-4, promotion flow, dry-run vault, go-live package (archived), strategy guard (active + wired), orchestration layer*
