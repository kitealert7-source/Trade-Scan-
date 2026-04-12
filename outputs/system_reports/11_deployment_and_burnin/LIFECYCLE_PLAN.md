# STRATEGY LIFECYCLE PLAN — PROMOTE / BURN_IN / WAITING / LIVE

> **Created:** 2026-04-03
> **Updated:** 2026-04-12
> **Status:** FULLY IMPLEMENTED (Phase 1-6 lifecycle tools + Deployment Unification Phase 2-5 runtime guards). Phase 3.3 (`burnin_monitor.py --json`) deferred — burn-in metrics entered manually via `transition_to_waiting.py` CLI args. Promotion pipeline fully hardened (Waves 1-5 + R6-R10). Runtime safety guards wired into TS_Execution (signal integrity + kill-switch).
> **Scope:** Artifact movement, storage, and lifecycle determinism from PIPELINE_COMPLETE to LIVE

---

## Objective

Make artifact movement, storage, and lifecycle (PROMOTE -> BURN_IN -> WAITING -> LIVE) deterministic, auditable, and zero-loss.

---

## Current State Audit

### Vault Coverage (per strategy — updated 2026-04-10, ~100+ files)

> All gaps from 2026-04-03 audit have been resolved. `promote_to_burnin.py` now creates full vault snapshots.

| Artifact | In Vault | In TradeScan_State | Status |
|----------|----------|-------------------|--------|
| `strategy.py` | YES | YES (strategies/) | OK |
| `directive.txt` | YES | NO (consumed -> .admitted marker) | Vault is only copy |
| `meta.json` (git, hash, run_id, vault_id, profile) | YES | NO | Vault is only copy |
| `selected_profile.json` | YES | NO | **FIXED** (was missing) |
| `portfolio_evaluation/` (11 files) | YES | YES (strategies/{ID}/) | OK |
| `deployable/` (ALL 7 profiles, full artifacts) | YES | YES | **FIXED** (was 1 profile) |
| `broker_specs_snapshot/` (per-symbol YAML) | YES | NO | **FIXED** (was missing) |
| `backtests/{ID}_{SYM}/raw/*.csv` (3 files) | YES | YES (backtests/) | OK |
| `backtests/{ID}_{SYM}/metadata/run_metadata.json` | YES | YES | OK |
| `run_snapshot/run_state.json` (FSM history) | YES | YES (runs/{RUN_ID}/) | **FIXED** (was missing) |
| `run_snapshot/manifest.json` (artifact hashes) | YES | YES (runs/{RUN_ID}/) | **FIXED** (was missing) |
| `run_snapshot/audit.log` (pipeline log) | YES | YES (runs/{RUN_ID}/) | **FIXED** (was missing) |
| `run_snapshot/data/` (all stage outputs) | YES | YES (runs/{RUN_ID}/) | **FIXED** (was missing) |

**Additional traceability artifact (2026-04-10):**
| Artifact | Location | Purpose |
|----------|----------|---------|
| `strategy_ref.json` | `TradeScan_State/strategies/{ID}/` | Pointer to authority `Trade_Scan/strategies/{ID}/strategy.py` with `code_hash: "sha256:..."` for version integrity detection |

### Run Context (13 files per run in `TradeScan_State/runs/{RUN_ID}/`)

```
runs/{RUN_ID}/
  audit.log                        <- pipeline stage execution log
  manifest.json                    <- strategy hash + artifact SHA-256 hashes
  run_state.json                   <- FSM state history (IDLE -> COMPLETE)
  strategy.py                      <- write-once snapshot
  data/
    bar_geometry.json              <- candle structure metadata
    batch_summary.csv              <- aggregated batch results
    equity_curve.csv               <- raw equity curve
    metrics_glossary.csv           <- metric definitions
    results_risk.csv               <- risk metrics
    results_standard.csv           <- performance metrics
    results_tradelevel.csv         <- per-trade detail
    results_yearwise.csv           <- annual breakdown
    run_metadata.json              <- engine version, dates, symbol, broker
```

### Deployable Artifacts (per profile, 7 profiles x ~5 files = ~35 files)

```
strategies/{ID}/deployable/
  profile_comparison.json          <- cross-profile comparison
  CONSERVATIVE_V1/
    deployable_trade_log.csv       <- capital-adjusted trades
    equity_curve.csv               <- profile-specific equity
    equity_curve.png               <- chart
    rejection_log.csv              <- lot-floor rejections
    summary_metrics.json           <- profile PF, DD, acceptance%
  DYNAMIC_V1/...
  FIXED_USD_V1/...
  BOUNDED_MIN_LOT_V1/...
  MIN_LOT_FALLBACK_V1/...
  MIN_LOT_FALLBACK_UNCAPPED_V1/...
  RAW_MIN_LOT_V1/...
```

### Portfolio YAML Schema (as of 2026-04-10)

**BURN_IN entries (current standard):**
```yaml
- id: "22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P03_AUDJPY"
  path: "strategies/22_CONT.../strategy.py"
  symbol: AUDJPY
  timeframe: M30
  enabled: true
  vault_id: DRY_RUN_2026_04_09__1b21c414
  profile: CONSERVATIVE_V1
  lifecycle: BURN_IN
```

**LEGACY entries (pre-vault, 11 entries):**
```yaml
- id: "27_MR_XAUUSD_1H_PINBAR_S01_V1_P05"
  path: "strategies/27_MR.../strategy.py"
  symbol: XAUUSD
  timeframe: H1
  enabled: true
  # vault_id, profile, lifecycle -> NOT present (pre-2026-04-06)
```

TS_Execution `portfolio_loader.py` uses `REQUIRED_FIELDS = {"id", "path", "symbol", "timeframe"}` and **silently ignores** unknown fields. Current portfolio: 19 entries (11 LEGACY, 8 BURN_IN across 4 strategies).

**Execution config fields (2026-04-12):**
```yaml
execution:
  vault_root: ../DRY_RUN_VAULT       # resolved relative to portfolio.yaml
  require_vault: false                # false = warn-only; true = abort if vault missing
```

`vault_root` and `require_vault` are consumed by `guard_bridge.py` at startup. `require_vault: false` is for the transition period; switch to `true` after confirming clean guard construction.

### Artifact Protection (Phase 4 pre-check + 2026-04-12 hardening)

- `cleanup_reconciler.py` -- has explicit `"vault"` in forbidden paths
- `lineage_pruner.py` -- scoped to TradeScan_State only; checks `protected: true` flag + PORTFOLIO_COMPLETE status (dual-signal)
- `reset_repo_artifacts.py` -- `"vault"` in PROTECTED_PATHS
- `backup_dryrun_strategies.py` -- write-only, never deletes
- `strategy_provisioner.py` -- only creates/updates strategy.py, never deletes folders
- No TS_Execution script references vault paths
- **Protection flag:** `directive_state.json` gets `protected: true` automatically at PORTFOLIO_COMPLETE transition
- **Verification gate:** `_verify_completion_artifacts()` runs non-blocking at PORTFOLIO_COMPLETE — checks run folders, strategy.py snapshots, data/ folders, authority copy, deployable existence. Warnings logged to directive_audit.log.
- **Runtime guards:** `strategy_guard.py` (`from_vault()`) constructs `StrategyGuard` per slot at TS_Execution startup; `guard_bridge.py` resolves vault paths, verifies profile integrity, builds signal index from `deployable_trade_log.csv`. Two-tier `validate_signal()` (exact hash + tolerant match) blocks HARD_FAIL signals pre-dispatch. Kill-switch `record_trade()` halts strategy on loss streak / WR / DD breach.
- **Verdict: Zero deletion paths to vault. Explicit protection flag + artifact verification at transition. Runtime signal + kill-switch guards active.**

---

## Phase 1 -- Vault Completeness (Upgrade DRY_RUN_VAULT)

**Goal:** Vault becomes FULL snapshot of strategy state (not partial).

### Actions

1. For each promoted strategy, copy ENTIRE run context:

   **Source:** `TradeScan_State/runs/{RUN_ID}/` (13 files)

   **Destination:** `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/run_snapshot/`

   **Include:**
   - `directive_state.json` / `run_state.json` (FSM history)
   - `manifest.json` (strategy hash + artifact hashes)
   - `audit.log` (pipeline stage execution log)
   - All stage outputs (`data/` folder: results, equity, metadata)
   - `strategy.py` (write-once snapshot from pipeline)

2. Copy ALL deployable profiles (not just selected):

   **Source:** `TradeScan_State/strategies/{ID}/deployable/` (all 7 profiles)

   **Destination:** `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/deployable/`

   **Include per profile:**
   - `deployable_trade_log.csv`
   - `equity_curve.csv`
   - `equity_curve.png`
   - `rejection_log.csv`
   - `summary_metrics.json`

3. Create `selected_profile.json` (new artifact):

   ```json
   {
     "strategy_id": "...",
     "selected_profile": "CONSERVATIVE_V1",
     "selected_by": "human",
     "selected_at": "2026-04-03T...",
     "vault_id": "DRY_RUN_2026_04_03"
   }
   ```

4. Copy broker spec YAML:

   **Source:** `Trade_Scan/data_access/broker_specs/{BROKER}_specs.yaml`
   (broker determined from `run_metadata.json -> broker` field)

   **Destination:** `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/broker_specs_snapshot/`

5. Add `run_id` to vault `meta.json`:

   ```json
   {
     "run_id": "7f030aac9bcfe612e141a32f",
     "strategy_id": "...",
     ...existing fields...
   }
   ```

   Without this, recovering the run_snapshot from vault requires scanning all runs.

6. Keep existing vault structure intact (additive only).

### Final Vault Layout Per Strategy

```
{vault_id}/{STRATEGY_ID}/
  strategy.py                          <- frozen code
  directive.txt                        <- execution spec (only copy after admission)
  meta.json                            <- git, hash, execution model, run_id
  selected_profile.json                <- NEW: profile selection record
  portfolio_evaluation/                <- full copy (11 files)
  deployable/                          <- ALL profiles (not just selected)
    profile_comparison.json
    CONSERVATIVE_V1/
      deployable_trade_log.csv
      equity_curve.csv
      equity_curve.png
      rejection_log.csv
      summary_metrics.json
    DYNAMIC_V1/...
    FIXED_USD_V1/...
    ... (all 7 profiles)
  broker_specs_snapshot/               <- NEW: broker YAML copy
    {BROKER}_specs.yaml
  backtests/{ID}_{SYMBOL}/             <- per-symbol raw results
    metadata/run_metadata.json
    raw/results_standard.csv
    raw/results_risk.csv
    raw/results_yearwise.csv
  run_snapshot/                        <- NEW: full pipeline state
    audit.log
    manifest.json
    run_state.json
    strategy.py
    data/
      bar_geometry.json
      batch_summary.csv
      equity_curve.csv
      metrics_glossary.csv
      results_risk.csv
      results_standard.csv
      results_tradelevel.csv
      results_yearwise.csv
      run_metadata.json
```

### Reject If

- Any artifact is recomputed instead of copied
- Any dependency on external state remains
- Storage is deduplicated (redundancy is intentional)

---

## Phase 2 -- Explicit Artifact Linkage

**Goal:** Every deployed strategy maps to exact snapshot.

### Actions

1. Modify `promote_to_burnin.py` to add structured fields:

   ```yaml
   - id: "27_MR_XAUUSD_1H_PINBAR_S01_V1_P05"
     path: "strategies/27_MR.../strategy.py"
     symbol: XAUUSD
     timeframe: H1
     enabled: true
     vault_id: DRY_RUN_2026_04_03
     profile: CONSERVATIVE_V1
     lifecycle: BURN_IN
   ```

2. Lifecycle field values (enumerated):

   | Value | Meaning |
   |-------|---------|
   | `BURN_IN` | Active execution, observation only |
   | `WAITING` | Passed burn-in, not yet allocated capital |
   | `LIVE` | Full capital allocation |
   | `DISABLED` | Manually stopped |

3. `enabled` vs `lifecycle` -- separate concerns:

   - `enabled` controls TS_Execution loading (it reads this field)
   - `lifecycle` controls governance (TS_Execution ignores it)
   - Keep both. Don't merge them.

4. Add `read_strategy_metadata()` utility to `promote_to_burnin.py`:

   ```python
   def read_strategy_metadata(strategy_id: str) -> dict:
       """Read vault_id, profile, lifecycle from portfolio.yaml for a strategy."""
   ```

   Needed by `/to_waiting` and `/to_live` workflows.

5. Remove all implicit assumptions:

   - No "latest vault" inference
   - No profile inference from comments
   - vault_id and profile are MANDATORY structured fields

### Reject If

- Execution can run without vault_id in portfolio.yaml
- Profile is only stored in comments

---

## Phase 3 -- WAITING State (Post Burn-In)

**Goal:** Define lifecycle after burn-in before live capital.

### State Definitions

| State | Meaning | portfolio.yaml |
|-------|---------|---------------|
| `BURN_IN` | Active execution, observation | `enabled: true, lifecycle: BURN_IN` |
| `WAITING` | Passed burn-in, not yet scaled | `enabled: false, lifecycle: WAITING` |
| `LIVE` | Allocated capital | `enabled: true, lifecycle: LIVE` |

### Actions

#### 3.1 Transition: BURN_IN -> WAITING

**Trigger:** Pass gates satisfied (manual human decision)

**Process:**

1. Disable strategy in portfolio.yaml:
   ```yaml
   enabled: false
   lifecycle: WAITING
   ```

2. Preserve vault_id (unchanged)

#### 3.2 Freeze Artifacts

**Source:** `DRY_RUN_VAULT/{vault_id}/{STRATEGY_ID}/`

**Destination:**
```
DRY_RUN_VAULT/WAITING/{STRATEGY_ID}_{date}/
  baseline/                    <- copy from promotion vault
  burnin_summary.json          <- NEW: burn-in execution results
  decision.json                <- NEW: PASS/FAIL/HOLD + rationale
```

#### 3.3 `burnin_summary.json` Schema

Data source: TS_Execution logs (`SignalJournal.jsonl`, `ExecutedSignals.jsonl`, MT5 deal history). Computed by `burnin_monitor.py --json`.

```json
{
  "strategy_id": "...",
  "burnin_start": "2026-04-03",
  "burnin_end": "2026-05-15",
  "duration_days": 42,
  "total_trades": 92,
  "profit_factor": 1.35,
  "win_rate": 0.58,
  "max_drawdown_pct": 4.2,
  "fill_rate": 0.97,
  "avg_pnl_per_trade": 3.45,
  "consecutive_losing_weeks": 0,
  "symbols": ["XAUUSD"]
}
```

#### 3.4 `decision.json` Schema

```json
{
  "strategy_id": "...",
  "decision": "PASS",
  "decided_by": "human",
  "decided_at": "2026-05-15T...",
  "burnin_start": "2026-04-03",
  "burnin_end": "2026-05-15",
  "trades_observed": 92,
  "pass_gates_met": ["PF>=1.20", "WR>=50%", "MaxDD<=10%", "fill_rate>=85%"],
  "abort_gates_triggered": [],
  "notes": "..."
}
```

### Reject If

- Strategy leaves burn-in without snapshot
- WAITING state has no artifact freeze

---

## Phase 4 -- Artifact Protection Policy

**Goal:** Prevent accidental loss or mutation.

### Current State: ALREADY SATISFIED

All cleanup scripts have explicit vault exclusions. Zero deletion paths to vault exist.

### Rules

1. `DRY_RUN_VAULT/` is immutable, append-only
2. `WAITING/` folder is immutable after creation, versioned per transition
3. No cleanup process can touch vault or waiting snapshots
4. Execution must NOT write into vault

### Additional Changes Required

- Add `"WAITING"` to `cleanup_reconciler.py` forbidden paths (1 line)
- Add `"WAITING"` to `reset_repo_artifacts.py` PROTECTED_PATHS (1 line)

### Reject If

- Any script modifies existing vault contents
- Cleanup touches vault paths

---

## Phase 5 -- Lifecycle Workflows

### /promote (existing, updated)

Creates vault snapshot, writes portfolio.yaml with vault_id + profile + lifecycle.

```
/promote <STRATEGY_ID> --profile <PROFILE>
  |
  Step 1: Validate PIPELINE_COMPLETE, artifacts exist, not in portfolio.yaml
  Step 2: Lookup run_id from directive_id (scan run_state.json files)
  Step 3: Vault snapshot (full: run_snapshot + all profiles + broker specs)
  Step 4: Create selected_profile.json
  Step 5: Verify vault (index.json, meta.json, git commit)
  Step 6: Edit portfolio.yaml (vault_id, profile, lifecycle: BURN_IN)
  Step 7: Sync IN_PORTFOLIO flag
  Step 8: Report (vault_id, entries added, symbols)
```

### /to_waiting (NEW)

**Input:** strategy_id

```
/to_waiting <STRATEGY_ID>
  |
  Step 1: Validate burn-in complete
    - Read portfolio.yaml -> confirm lifecycle: BURN_IN
    - Read burnin_monitor.py output -> confirm pass gates
  |
  Step 2: Generate burnin_summary.json
    - python tools/burnin_monitor.py --json <STRATEGY_ID>
    - Or: manually provide if burnin_monitor not available
  |
  Step 3: Create decision.json (human provides decision + notes)
  |
  Step 4: Copy vault -> WAITING snapshot
    - cp DRY_RUN_VAULT/{vault_id}/{ID}/ -> WAITING/{ID}_{date}/baseline/
    - Write burnin_summary.json + decision.json
  |
  Step 5: Update portfolio.yaml
    - enabled: false
    - lifecycle: WAITING
  |
  Step 6: Report waiting_snapshot_id
```

**Output:** waiting_snapshot_id

### /to_live (future, minimal now)

**Input:** strategy_id

```
/to_live <STRATEGY_ID>
  |
  Step 1: Validate WAITING exists (WAITING/{ID}_* in vault)
  Step 2: Enable in portfolio.yaml
    - enabled: true
    - lifecycle: LIVE
  Step 3: Report
```

No artifact mutation. Just a portfolio.yaml state change.

---

## Phase 6 -- Consistency Guarantees

System must ensure:

1. `strategy -> vault_id -> exact snapshot` (1:1 mapping)
2. `burn-in -> waiting snapshot` preserved
3. No artifact recomputation at execution
4. Full reproducibility from vault alone

### Linkage Status (updated 2026-04-10)

| Linkage | Status | Resolved By |
|---------|--------|-------------|
| `strategy -> vault_id` | **RESOLVED** — vault_id in portfolio.yaml | Phase 2 (promote_to_burnin.py) |
| `vault_id -> run_id` | **RESOLVED** — run_id in meta.json | Phase 1 (backup_dryrun_strategies.py) |
| `strategy -> code_hash` | **RESOLVED** — strategy_ref.json pointer | 2026-04-10 (strategy_ref.json) |
| `burn-in -> waiting snapshot` | **READY** — transition_to_waiting.py built | Phase 3 (not yet exercised) |

---

## Improvements Over Original Spec

| # | Improvement | Phase | Effort | Impact |
|---|-------------|-------|--------|--------|
| 1 | Add `run_id` to vault `meta.json` | P1 | 15 min | Run_snapshot -> vault traceability |
| 2 | Copy ALL 7 profiles (not just 1 equity_curve.csv) | P1 | 30 min | Full capital model audit trail |
| 3 | Create `selected_profile.json` in promote workflow | P1 | 20 min | Records profile selection decision |
| 4 | Copy broker spec YAML to vault | P1 | 15 min | Broker config reproducibility |
| 5 | Add `read_strategy_metadata()` utility | P2 | 20 min | Enables /to_waiting and /to_live |
| 6 | Enumerate lifecycle values | P2 | 5 min | Prevents ad-hoc values |
| 7 | Keep `enabled` + `lifecycle` as separate concerns | P2 | 0 min | Document only |
| 8 | Use `WAITING/` subfolder in vault | P3 | 10 min | Cleaner vault structure |
| 9 | Add `--json` to `burnin_monitor.py` | P3 | 45 min | Automated burnin_summary.json |
| 10 | Define `decision.json` schema now | P3 | 10 min | Prevents schema drift |
| 11 | Add WAITING to cleanup exclusion lists | P4 | 5 min | Protects WAITING folder |
| 12 | Run_id reverse lookup in promote workflow | P1 | 20 min | Automates run -> vault mapping |
| 13 | `promote_readiness.py` dashboard | R6 | 3h | Single-command readiness overview for all CORE/WATCH |
| 14 | `protected: true` flag at PORTFOLIO_COMPLETE | R7 | 1h | Explicit artifact protection, pruner dual-signal |
| 15 | `_verify_completion_artifacts()` at PORTFOLIO_COMPLETE | R8 | 2h | Non-blocking artifact verification with audit log |
| 16 | `--batch` / `--batch-all` promote mode | R10 | 2h | Batch promote all ready strategies |
| 17 | `--composite` promote for PF_* portfolios | W4 | 3h | Decompose + per-constituent quality gate |
| 18 | All-or-nothing per-symbol expectancy gate | Fix | 30 min | No silent symbol dropping in multi-symbol |
| 19 | `decompose_portfolio()` run folder fallback | Fix | 30 min | Recovers constituents missing from Master Filter |
| 20 | `from_vault()` factory in strategy_guard.py | DU-P2 | 1h | Guard construction from vault layout (not golive/) |
| 21 | Two-tier `validate_signal()` + `SignalResult` | DU-P2.1 | 2h | Exact hash + tolerant match; HARD_FAIL blocks trade |
| 22 | `guard_bridge.py` in TS_Execution | DU-P2 | 2h | Vault path resolution, guard construction, MismatchTracker |
| 23 | 3 hooks in TS_Execution main.py | DU-P2 | 1h | construct_guards, validate_signal, record_trade |
| 24 | Archive `generate_golive_package.py` | DU-P4 | 15 min | Moved to archive/tools/ (functionally orphaned) |
| 25 | Rewrite `validate_safety_layers.py` | DU-P4+P5 | 2h | 6 vault-based tests (artifact, hash, signal, kill-switch x2, two-tier) |

**Total additional effort: ~3.5h (original) + ~12h (Waves 4-5 + R6-R10) + ~8h (Deployment Unification P2-P5)**

---

## Files Modified (Implementation Record)

| File | Change | Status |
|------|--------|--------|
| `tools/backup_dryrun_strategies.py` | Full rewrite: `--run-id`/`--profile` args, run_snapshot/ copy, all deployable profiles, broker specs, selected_profile.json, run_id in meta.json, unique vault_id format | DONE |
| `tools/promote_to_burnin.py` | Full rewrite: run_id lookup, vault snapshot call, vault_id/profile/lifecycle in YAML entries, `--profile` mandatory, `read_strategy_metadata()` utility | DONE |
| `tools/transition_to_waiting.py` | **NEW**: BURN_IN->WAITING transition, vault_ref.json (no data copy), decision.json, burnin_summary.json, portfolio.yaml update, `validate_waiting_strategies()` invariant check | DONE |
| `.agents/workflows/promote.md` | Full rewrite: single-command promote, vault_id format, full vault contents, lifecycle fields | DONE |
| `.agents/workflows/to-waiting.md` | **NEW**: /to-waiting workflow spec | DONE |
| `TS_Execution/portfolio.yaml` | Schema extension (vault_id, profile, lifecycle) -- no loader changes needed | READY |
| `tools/cleanup_reconciler.py` | Added "waiting" to forbidden paths | DONE |
| `tools/reset_repo_artifacts.py` | Added "WAITING" to PROTECTED_PATHS | DONE |
| `CLAUDE.md` | Added topic index entries for /promote and /to-waiting | DONE |
| `TS_Execution/tools/burnin_monitor.py` | Add `--json` output mode; relocated output to `TS_Execution/outputs/burnin/` (no backward writes to TradeScan_State) | DEFERRED (--json); OUTPUT RELOCATED (2026-04-12) |
| `tools/promote_readiness.py` | **NEW**: Readiness dashboard scanning FSP + MPS for CORE/WATCH candidates, checks strategy.py/run_id/deployable/quality_gate/portfolio_yaml | DONE (2026-04-12) |
| `tools/pipeline_utils.py` | Added `protected: true` flag at PORTFOLIO_COMPLETE + `_verify_completion_artifacts()` non-blocking verification gate | DONE (2026-04-12) |
| `tools/state_lifecycle/lineage_pruner.py` | Dual-signal protection: checks `protected` flag + PORTFOLIO_COMPLETE status | DONE (2026-04-12) |
| `.agents/workflows/promote.md` | Full rewrite: added --composite/--batch/--batch-all/--skip-quality-gate, readiness dashboard, all-or-nothing gate | DONE (2026-04-12) |
| `outputs/system_reports/11_deployment_and_burnin/CLASSIFICATION_REFERENCE.md` | **NEW**: CORE/WATCH/FAIL gate reference across filter_strategies, portfolio_evaluator, promote quality gate | DONE (2026-04-12) |
| `execution_engine/strategy_guard.py` | Added `from_vault()`, `validate_signal()`, `SignalResult`, `_signal_details`, `_load_baseline_from_vault()`, `_timestamp_diff_seconds()` | DONE (2026-04-12) |
| `tools/validate_safety_layers.py` | **REWRITTEN**: 6 vault-based tests (was: broken golive-based 5 tests) | DONE (2026-04-12) |
| `tools/generate_golive_package.py` | **ARCHIVED** to `archive/tools/` (functionally orphaned since vault became deployment path) | DONE (2026-04-12) |
| `tests/test_generate_golive_package_helpers.py` | **ARCHIVED** to `archive/tests/` | DONE (2026-04-12) |
| `TS_Execution/src/guard_bridge.py` | **NEW**: `construct_guards()`, `resolve_vault_path()`, `MismatchTracker` | DONE (2026-04-12) |
| `TS_Execution/src/main.py` | 3 guard hooks: construct at startup, validate pre-dispatch, record on shadow/reconcile exit | DONE (2026-04-12) |
| `TS_Execution/portfolio.yaml` | Added `vault_root`, `require_vault` to execution config | DONE (2026-04-12) |

---

## Constraints

- No architecture redesign
- No new databases
- No runtime performance impact
- Minimal code changes only
- TS_Execution portfolio_loader.py: zero changes (extra fields silently ignored)

---

## Addendum: Pipeline Authority & Quality Gates (2026-04-10)

### Profile Selection Authority

Step 7 (`_resolve_deployed_profile` in `portfolio_evaluator.py`) is the **sole authority** for `deployed_profile` selection. Step 8.5 (`profile_selector.py`) is a **validator/enricher only** — reads Step 7's choice from the ledger, enriches metrics, never selects. `select_deployed_profile()` raises `RuntimeError` as a dead code guard.

### Portfolio Status Quality Gates

Classification in `_compute_portfolio_status()` uses layered gates (all additive):

**FAIL gates (any one triggers FAIL):**
- `realized_pnl <= 0`
- `trades_accepted < 50`
- `trade_density < 50` (per-symbol average — catches inflated portfolio totals)
- `expectancy < asset_class_gate` (FX: $0.15, XAU/BTC/INDEX: $0.50)

**Quality gates (on top of ALL FAIL gates — below floor = FAIL):**
- **Portfolios tab:** `edge_quality >= 0.12` for CORE, `>= 0.08` for WATCH
- **Single-Asset tab:** `SQN >= 2.5` for CORE, `>= 2.0` for WATCH

**CORE also requires:** `realized > $1,000` AND `accepted >= 200` AND `rejection <= 30%`

These gates determine which strategies are eligible for promotion via `promote_to_burnin.py`.

### Strategy Traceability

Each `TradeScan_State/strategies/{ID}/` has a `strategy_ref.json` pointer:
```json
{
  "source": "Trade_Scan/strategies/{ID}/strategy.py",
  "code_hash": "sha256:...",
  "created_at": "..."
}
```
Authority chain: `strategy_ref.json` -> `Trade_Scan/strategies/{ID}/strategy.py` (source of truth) -> vault snapshot (immutable copy at promote time).
