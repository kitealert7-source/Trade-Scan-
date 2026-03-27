# AGENT.md — System Invariants & Operational Contract

**Authority:** Governance-First Pipeline Architecture  
**Status:** DIAGNOSTIC ONLY — No mutation authority  
**Scope:** All failures encountered in `run_pipeline.py` orchestrated execution

> [!CAUTION]
> This playbook is NOT an autonomous repair system.  
> It MUST NEVER authorize automatic mutation of strategy code, directives, artifacts, `run_state.json`, or Master Ledgers.  
> It is a diagnostic and remediation guide only.


### Pre-Directive Creation Gate (MANDATORY — Zero-Cost Failure Point)

Before creating ANY file (directive, strategy.py, sweep_registry entry, idea_registry entry):

**Step 0: Token Validation**

1. Read `governance/namespace/token_dictionary.yaml`
2. Confirm the proposed MODEL token exists in the `model:` list
3. If not found — check `aliases.model` for a canonical mapping
4. If still not found — STOP. Do not create any files. Resolve the token first:
   - Select the closest existing token, OR
   - Propose adding a new token/alias to the dictionary and await human approval
5. Only proceed to file creation once the token is confirmed valid

**Why this is the zero-cost failure point:**
Stage -0.30 (Namespace Governance Gate) runs BEFORE Stage-0 (strategy.py provisioning).
The pipeline will catch token errors before touching strategy.py.
But the agent creates files manually before INBOX submission — so a wrong token at that
point requires renaming the directive, strategy directory, strategy.py internals,
sweep_registry entry, and idea_registry entry before re-running.
Catching it at Step 0 costs nothing. Catching it at pipeline runtime costs a full reset.

**Valid MODEL tokens (reference — source of truth is token_dictionary.yaml):**
RSIAVG, ZREV, VOLEXP, ATRBRK, BOS, CHOCH, SFP, IBREAK, PINBAR, ENGULF,
LIQGRAB, PORT, ULTC, DAYOC, SMI, LORB, RSIPULL, SPKFADE, GAPFILL,
BBSQZ, ATRSQZ, ASRANGE, FAKEBREAK, LIQSWEEP, CMR, MICROREV, IMPULSE

**New pass creation tool (eliminates EXPERIMENT_DISCIPLINE 2-pass cycle):**
For any `_PXX` variation, use `tools/new_pass.py` instead of manually writing files:
```bash
python tools/new_pass.py <source_pass> <new_pass>   # scaffold
# Edit directive + strategy.py
python tools/new_pass.py --rehash <new_pass>         # pre-inject canonical hash → no mtime change → no EXPERIMENT_DISCIPLINE
```
GENESIS_MODE (brand new family, _P00): use legacy `python tools/run_pipeline.py --all --provision-only` path.

---

## SYSTEM INVARIANTS

These are non-negotiable. The agent must never violate any of these.

1. **Ledger Supremacy** — `Master_Portfolio_Sheet.xlsx` and `Strategy_Master_Filter.xlsx` are append-only. No deletion. No overwrite. *(→ Recovery: FAILURE_PLAYBOOK.md §STAGE_4_LEDGER_MISMATCH)*
2. **Fail-Fast** — Any failure at any stage aborts the entire pipeline. No partial progression. No continuation after error. *(→ Recovery: FAILURE_PLAYBOOK.md §EXECUTION_ERROR)*
3. **Artifact Authority** — All gating decisions derive from physical artifact existence and content, not memory or cache.
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` and `STRATEGY_SNAPSHOT.manifest.json` are write-once. No mutation after creation. *(→ Recovery: FAILURE_PLAYBOOK.md §SNAPSHOT_INTEGRITY_MISMATCH)*
5. **State Machine Integrity** — `run_state.json` transitions are strictly forward. FAILED is terminal. Re-provisioning is the only recovery. *(→ Recovery: FAILURE_PLAYBOOK.md §STATE_TRANSITION_INVALID)*
6. **Directive Integrity** — Directives in `backtest_directives/INBOX/` are not modified by the pipeline. Only moved to `completed/` on success.
7. **Deterministic Execution** — Same directive + same data = same output. No randomness. No inference. No implicit defaults.
8. **Single Authority** — Only `run_pipeline.py` may mutate `run_state.json`. No other tool, script, or agent may modify state files.
9. **Append-Only Audit** — `directive_audit.log` and run audit logs are append-only. No truncation. No retroactive edits.
10. **Human Gating** — No new `strategy.py` may enter execution without explicit human approval (Admission Gate — SOP_TESTING §4A).
11. **Protected Infrastructure** — Files under `tools/`, `engines/`, `engine_dev/`, `governance/`, and `.agents/workflows/` are Protected Infrastructure. Agent MUST NOT modify without presenting an implementation plan and receiving explicit human approval.
12. **Single Signature Authority** — Signature construction is owned exclusively by `tools/directive_schema.py:normalize_signature()`. No other file may construct or compare signatures independently.
13. **Genesis/Clone Classification** — New strategies (no existing `strategy.py`) use GENESIS_MODE: directive-only implementation, no cross-family behavioral borrowing. Existing strategies use CLONE_MODE.
14. **No Workspace Mode** — All pipeline executions run in strict integrity mode. Engine hash verification and tools manifest verification are mandatory. There is no development bypass.
15. **Governance-Authorized Reset Only** — `--force` is removed from the pipeline. Failed directives may only be reset via `tools/reset_directive.py --reason "<justification>"`, which logs to `governance/reset_audit_log.csv`. Full resets (→ INITIALIZED) archive associated per-symbol `run_state.json` files **and delete the directive-level run folder (`TradeScan_State/runs/<DIRECTIVE_ID>/`) including `run_registry.json`** — preventing phantom completion states from corrupting subsequent pipeline runs. `--to-stage4` preserves run states and does not clear the directive-level folder. The agent MUST NOT invoke this tool autonomously. `--to-stage4` is only valid from PORTFOLIO_COMPLETE. FAILED directives cannot resume mid-pipeline because Stage-4 relies on consistent artifacts from Stages 0-3. A FAILED directive must be fully reset before re-execution to guarantee artifact integrity. *(→ Recovery: FAILURE_PLAYBOOK.md §STATE_TRANSITION_INVALID)*
16. **Guard-Layer Manifest** — All Critical Guard Set files (`tools/tools_manifest.json`) are SHA-256 bound. `tools/generate_guard_manifest.py` is human-only; the agent MUST NOT invoke it or modify the manifest.
17. **Root-of-Trust Vault Binding** — `verify_engine_integrity.py` is hash-bound via `vault/root_of_trust.json`. `preflight.py` verifies this hash before invoking the integrity checker. Vault updates require explicit human action. The agent MUST NOT modify `vault/root_of_trust.json`.
18. **Engine Manifest Generator** — `tools/generate_engine_manifest.py` is human-only; the agent MUST NOT invoke it. It auto-detects the active engine version and writes `engine_manifest.json`.
19. **Directive Schema Freeze** — The canonical directive schema is defined in `tools/canonical_schema.py` (FREEZE policy). All directives must conform to this schema. `tools/canonicalizer.py` validates structure at Stage -0.25. Unknown keys, misplaced blocks, type mismatches, and missing required sub-blocks cause HARD FAIL. The canonicalizer moves, renames, or reorders keys only via explicit tables — never via inference or leaf scanning.
20. **Capital Model Invariant** — Per-symbol reference capital is `$1,000` (defined in `data_access/broker_specs/*/<SYMBOL>.yaml` as `reference_capital_usd: 1000`). Total portfolio capital is `$10,000` (defined in `portfolio_evaluator.py` as `TOTAL_PORTFOLIO_CAPITAL = 10000` and in `capital_wrapper.py` PROFILES). Self-imposed leverage cap is 5× (effective buying power: $5,000 per symbol). These values must remain synchronized across all three systems.
21. **Namespace Governance** — Directive identity must satisfy `filename == test.name == test.strategy` and pass `tools/namespace_gate.py` (pattern, token dictionaries, alias policy, idea-family registry match) at Stage -0.30.
22. **Sweep Registry Integrity** — Sweeps are reserved through `tools/sweep_registry_gate.py` at Stage -0.35. Existing sweep reuse is allowed only for exact idempotent matches (same directive + same signature hash); all other reuse is blocked as collision.
23. **Symbol Universe Admission** — Preflight must confirm each symbol exists in broker specs and has RESEARCH data for the declared broker/timeframe before Stage-1 execution.
24. **Clean Repository Rule** — The Trade_Scan repository is immutable during pipeline execution. All runtime artifacts (runs, registries, backtests, reports, sandbox outputs) must be written exclusively to `TradeScan_State/`. Any tool or workflow attempting to write runtime artifacts inside the repository constitutes a governance violation.
25. **Scratch Script Placement** — All ad-hoc, one-off, diagnostic, or batch utility scripts created during agent sessions must be written to `/tmp/` exclusively. The `Trade_Scan/` repository root must remain free of transient scripts. Any script placed in the repository root without being part of the governed toolset is a governance violation.

### On Failure: Use the Playbook

If any invariant is violated, pipeline state is inconsistent,
or execution deviates from expected lifecycle:

→ STOP immediately  
→ Do NOT attempt ad-hoc fixes  
→ Open FAILURE_PLAYBOOK.md and locate the matching failure class  
→ Follow the deterministic recovery path exactly

---


---

## LIFECYCLE OVERVIEW

> Before running the pipeline: verify `SYSTEM_STATE.md` shows no blocking issues.

```
Directive (YAML in active/)
    │
    ▼
Stage -0.25: Structural Canonicalization
    ├── Envelope Guard (test: must be identity-only)
    ├── Tree Rebuild (parse → canonical blocks → type check)
    ├── Conflict-Safe Relocation (misplaced keys)
    ├── Leftover Rejection (unknown keys = HALT)
    ├── Depth-2 Nested Key Validation
    └── Deterministic Diff + Approval Gate
    │
    ▼
Stage -0.30: Namespace Governance Gate
    ├── Name pattern enforcement
    ├── FAMILY/MODEL/FILTER/TF token dictionary enforcement
    ├── Alias policy enforcement (canonical tokens only)
    └── Idea registry family binding check
    │
    ▼
Stage -0.35: Sweep Registry Gate
    ├── Sweep reservation (append-only)
    ├── Idempotent reuse check (same directive + same signature hash)
    └── Collision rejection on conflicting reuse
    │
    ▼
Stage-0: Preflight
    ├── Strategy Provisioning (create/update strategy.py shell)
    ├── Dependency Validation (indicators, engine, broker specs)
    ├── Symbol Universe Validation (broker spec + RESEARCH data presence)
    └── Governance Compliance Check
    │
    ▼
Stage-0.5: Semantic Validation
    ├── Identity Verification (name, timeframe)
    ├── Signature Schema Enforcement (version, deep equality)
    ├── Indicator Set Verification (exact import matching)
    ├── Behavioral Guard (FilterStack enforcement, no hardcoded regime access)
    └── Admission Gate (hollow strategy detection → PROVISION_REQUIRED)
    │
    ▼
Stage-0.55: Semantic Coverage Gate
    └── All declared behavioral parameters referenced in strategy code
    │
    ▼
Stage-0.75: Dry-Run Validation
    ├── Strategy Instantiation Test
    ├── prepare_indicators() Crash Detection
    └── check_entry() Crash Detection
    │
    ▼
Stage-1: Run-Registry Worker Execution (per planned run)
    ├── Plan run set to `TradeScan_State/registry/run_registry.json`
    ├── Claim `PLANNED` run -> mark `RUNNING`
    ├── Data Load (RESEARCH only)
    ├── Engine Execution Loop
    ├── Artifact Emission (results_tradelevel.csv, results_standard.csv)
    ├── Artifact Gate (physical file existence check)
    └── Finalize run -> `COMPLETE` or `FAILED` in registry
    │
    ▼
Stage-2: Compilation (per symbol)
    ├── Stage-1 Artifact Ingestion
    ├── Metric Computation (SOP_OUTPUT compliant)
    └── AK_Trade_Report Excel Generation
    │
    ▼
Stage-3: Aggregation
    ├── Strategy_Master_Filter.xlsx Update
    ├── Cardinality Gate (row count == symbol count)
    ├── Strategy Snapshot Copy + Hash Verification
    └── STRATEGY_SNAPSHOT.manifest.json Binding
    │
    ▼
Pre-Stage-4: Manifest Integrity Verification
    ├── Manifest Existence Check (all runs)
    ├── Manifest Key Set Verification
    └── Artifact Hash Re-Computation + Comparison
    │
    ▼
Stage-4: Portfolio Evaluation
    ├── Portfolio Metrics Computation
    ├── Chart Generation
    ├── Master_Portfolio_Sheet.xlsx Append
    ├── Ledger Row Count Verification
    └── Constituent Run ID Cardinality Gate
    │
    ▼
PORTFOLIO_COMPLETE → Directive moved to completed/
    │
    ▼
Step 7: Deterministic Report Generation (non-authoritative)
    ├── REPORT_SUMMARY.md from raw results CSVs
    └── Read-only — does NOT affect directive state
    │
    ▼
Step 8: Capital Wrapper (deployable artifact emission)
    ├── CONSERVATIVE_V1 + AGGRESSIVE_V1 profiles
    ├── equity_curve.csv + equity_curve.png
    ├── deployable_trade_log.csv
    ├── summary_metrics.json
    └── profile_comparison.json
    │
    ▼
Step 9: Deployable Artifact Verification
    ├── Equity math invariant (final_equity = starting + pnl)
    ├── Non-negative equity check
    ├── Trade log count match
    └── PNG existence + non-zero size
    │
    ▼
Step 10: Robustness Suite (observational research)
    ├── 14-section analysis per profile
    ├── Monte Carlo, Bootstrap, Friction Stress
    └── Reports to strategies/ + outputs/reports/
```

### Step 11: Research Insight Extraction (Optional, Manual)

Review the generated report:
`TradeScan_State/backtests/<DIRECTIVE>/REPORT_SUMMARY.md`

If meaningful strategic insight is discovered, propose appending a structured entry to `RESEARCH_MEMORY.md` including:

- Tags
- Finding
- Evidence
- Conclusion
- Implication

Rules:
- Append only
- Do not modify previous entries
- Do not record raw experiment logs
- Only record distilled findings

Important: do not auto-generate insights. The agent should suggest, and human approval is required before append.

---

---

## ENGINE ARCHITECTURE STANDARDS (MANDATORY)

Purpose: Prevent structural drift, shadow routing, and split execution authority.

These rules are non-negotiable.

------------------------------------------------------------

### 1. Version Namespace Validity

Engine version folders inside:

engine_dev/universal_research_engine/

MUST follow this exact pattern:

v<major>_<minor>_<patch>

Example:

- v1_4_0  ✅
- 1.4.0   ❌
- 1_4_0   ❌
- version1_4_0 ❌

If a version folder cannot be imported via native Python syntax,
the architecture is invalid.

------------------------------------------------------------

### 2. No Engine Core Import Bypass

The following is strictly forbidden for engine core modules:

importlib.util.spec_from_file_location

Dynamic filesystem injection is permitted ONLY for strategy plugins.

All engine execution components MUST be imported using standard syntax:

from engine_dev.universal_research_engine.vX_Y_Z.<module> import ...

If dynamic loading is detected for engine core → HARD FAIL.

------------------------------------------------------------

### 3. Single Execution Authority

At runtime, the following modules MUST resolve inside the active version folder:

- execution_loop
- execution_emitter_stage1
- stage2_compiler

If any resolve outside the active version directory → HARD FAIL.

Split execution authority is prohibited.

------------------------------------------------------------

### 4. Engine Self-Containment Doctrine

An engine version folder MUST be fully self-contained for:

- Stage-1 execution loop
- Stage-1 artifact emission
- Stage-2 compilation

No execution lifecycle component may depend on unversioned global modules.

------------------------------------------------------------

### 5. Shadow Core Prohibition

Core execution files MUST NOT exist in multiple active locations
in a way that allows silent fallback.

If duplicate filenames exist across:

- engine_dev/
- tools/

Runtime must explicitly bind to the version folder.

Implicit fallback to global modules is prohibited.

------------------------------------------------------------

### 6. Manifest Localization & Strict Integrity

engine_manifest.json MUST reside inside the active version folder.

verify_engine_integrity.py MUST:

- Hash only files inside the active version directory
- Fail strictly if manifest is missing
- Fail strictly on any SHA-256 mismatch
- Never downgrade to WARN

------------------------------------------------------------

### 7. Vault Non-Authority Doctrine

Vault snapshots are non-authoritative for execution.
They are recovery artifacts only.

---


---

> For failure classification and the escalation matrix,
> see **FAILURE_PLAYBOOK.md**.

---

**End of AGENT.md — System Invariants & Operational Contract**
