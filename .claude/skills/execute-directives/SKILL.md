---
name: execute-directives
description: Execute all active directives through the governed pipeline with Admission Gate enforcement
---

## Core Execution Workflow (The Golden Path)

This workflow executes directives in `backtest_directives/INBOX/` to produce authoritative **Candidates**.

> **MANDATORY READ RULE**: This workflow MUST be read in full before calling `run_pipeline.py` — regardless of whether the directive was provided by the user or authored by the agent. When the agent writes the directive itself, this step is most easily skipped and most likely to cause regressions. There are no exceptions.

### Prerequisites
- Directive YAML file(s) in `backtest_directives/INBOX/`
- AGENT.md (Failure Playbook) exists at project root

> **Supervised posture:** On failure, consult `outputs/system_reports/04_governance_and_guardrails/TOOL_ROUTING_TABLE.md`. Flexible scopes (F02 exploratory, F19 re-run, tool sequencing, Tier 1 ambiguity) use `[ANNOUNCE] <SCENARIO> | risk: ... | action: ...` and PROCEED. STRICT STOP preserved for F10 pre-traceback, F03/F04 cleanup without `--dry-run`, governance scopes (F05/F06/F08/F13/F15/F16), and system invariants.

---

### Step 0: Directive Admission Gate

Before provisioning, you MUST verify data coverage and administrative alignment.

1.  **Temporal Coverage**: Verify `MASTER_DATA` timestamps cover the directive range (`avail_start <= req_start` AND `avail_end >= req_end`).
2.  **Optional Admission Pre-checks**: The following tools run automatically inside `run_pipeline.py`, but can be used for manual pre-validation:
    ```bash
    python tools/canonicalizer.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    python tools/namespace_gate.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    python tools/sweep_registry_gate.py backtest_directives/INBOX/<DIRECTIVE_ID>.txt
    ```

3.  **Optional Maintenance Check**: If workspace drift is suspected, run the reconciler from the **System Maintenance Workflow** to ensure the `runs/` directory is aligned with `run_registry.json`.

4.  **New Sweep Pre-registration** (required only when `idea_id` or `sweep` slot is new):
    Before running the pipeline, add the idea and sweep stub to `governance/namespace/sweep_registry.yaml`.
    Use `'0000000000000000'` as the placeholder `signature_hash` — NOT the word `placeholder`.
    The word `placeholder` is not valid hex and will fail the sweep gate immediately.
    ```yaml
    # Correct stub format for a new sweep slot (S02, S03, etc.)
    S02:
      directive_name: <DIRECTIVE_ID>
      signature_hash: '0000000000000000'
      signature_hash_full: '0000000000000000000000000000000000000000000000000000000000000000'
      reserved_at_utc: '<UTC_TIMESTAMP>'
      patches: {}
    ```
    The real hash is written by `new_pass.py --rehash` after strategy implementation.

### Step 1: New Pass Creation (use `new_pass.py` — eliminates EXPERIMENT_DISCIPLINE)

For any new pass (_PXX), use the creation tool instead of manually writing files:

```bash
# Scaffold directive + strategy.py from source pass
python tools/new_pass.py <source_pass> <new_pass>

# After editing directive and strategy.py with your changes:
python tools/new_pass.py --rehash <new_pass>
```

`--rehash` pre-injects the provisioner-canonical hash into strategy.py and touches
`strategy.py.approved` so the provisioner finds nothing to change on first pipeline run.
**EXPERIMENT_DISCIPLINE will not fire.**

Skip to Step 5 after `--rehash` completes.

> **Legacy path (GENESIS_MODE only — brand new family):**
> Use `python tools/run_pipeline.py --all --provision-only` to generate the skeleton,
> implement check_entry/check_exit, then follow the EXPERIMENT_DISCIPLINE cycle.

### Step 2: Strategy Admission Gate

Classify the implementation mode based on the directive and existing code:
- **GENESIS_MODE**: New strategy (new family, _P00). Implement exclusively from directive parameters. Use legacy path above.
- **PATCH_MODE**: Variation of parent (`_PXX` where XX > 00). Use `new_pass.py` workflow.
- **CLONE_MODE (same sweep, new patch)**: Logic comparison within the same sweep (e.g., S01_P00 → S01_P01). Use `new_pass.py` workflow.
- **CLONE_MODE (new sweep)**: Clone into a different timeframe or structural variant (e.g., S01 → S02). `new_pass.py` cannot create new sweep slots — it only handles patches. Use the GENESIS_MODE path: pre-register the S0X stub in `sweep_registry.yaml` (Step 0.4), write the directive to INBOX, run `run_pipeline.py`, implement the strategy, then `--rehash`.

### Step 3: Human Strategy Review & Approval

1. Present `strategies/<NAME>/strategy.py` to the user for review.
2. **Approval Required**: The agent MUST NOT proceed without an explicit `APPROVED` response.
3. Verify the `# --- STRATEGY SIGNATURE ---` markers are present in the code.

### Step 4: Warmup Verification Test

Perform a regression test to ensure indicators are correctly initialized.

// turbo

```bash
python tools/tests/test_warmup_extension.py
```

*Do NOT proceed if any test fails.*

### Step 5: Full Pipeline Execution

After human approval, launch the multi-stage backtest.

// turbo

```bash
python tools/run_pipeline.py --all
```

*Monitor Stages 1-4. On failure, refer to **Step 5: Failure Handling** below.*

### Step 6: Capital Wrapper Execution

Simulate equity paths across the three active capital profiles:

| Profile | Role | Summary |
|---|---|---|
| `RAW_MIN_LOT_V1` | Diagnostic baseline | Every signal fires at 0.01 lot unconditionally. No risk/heat/leverage gates. "Is the directional edge real?" probe. |
| `FIXED_USD_V1` | Retail conservative | $1k seed, risk = max(2% of equity, $20 floor). No heat/leverage caps. Sub-min_lot trades SKIP honestly (no fallback). |
| `REAL_MODEL_V1` | Retail aggressive | $1k seed, tier-ramp risk (2% base → +1% each 2× equity doubling, capped at 5%). `retail_max_lot=10`. Symmetric on retracement. |

> [!IMPORTANT]
> **DATA GUARD**: The wrapper MUST run after Stage-4 completes.
> Verify `backtests/<RUN_ID>/raw/results_tradelevel.csv` exists before execution.

The old institutional profiles (`DYNAMIC_V1`, `CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`,
`MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1`) have been **retired** — they
modelled desk-style portfolio heat / leverage caps that do not apply to a single
retail OctaFx account. Do not re-introduce them without Protected Infrastructure
approval (Invariant #6).

// turbo

```bash
python tools/capital_wrapper.py <DIRECTIVE_NAME>
```

### Step 7: Candidate Promotion

Perform the final quality filter and migrate passing runs to `candidates/`.

// turbo

```bash
python tools/filter_strategies.py
```

**Immediately report results:**

```text
=== CANDIDATE PROMOTION REPORT ===
Total strategies evaluated : <N>
Passed criteria            : <N>
Newly promoted this run    : <N>
Physically migrated        : <N>
===================================
```

### Step 8: Research Suggestion Layer

Acting as the Research Suggestion Layer, analyze the newly completed runs in `TradeScan_State/research/index.csv`.
Generate **EXACTLY 0 OR 1** candidate research entry matching the `RESEARCH_MEMORY.md` contract.
If no structural/decisive insight exists, output: "No high-signal research insight identified from this batch."

If a candidate is identified, it must adhere to the severe constraint template:
- **Tags, Strategy, Run IDs** (no padded spacing)
- **Finding:** Pure observation of what changed.
- **Evidence:** MAX 2 lines. MAX 2 key metrics. Must show dominant delta clearly.
- **Conclusion:** Mechanism (why it happened), not repetitive of the finding.
- **Implication:** Clear actionable future constraint.

Present the single candidate to the human and ask: "Append this entry? (yes/no or suggest modification)".
**DO NOT use research_memory_append.py without explicit human approval.**

> **File size check:** After appending, if `RESEARCH_MEMORY.md` exceeds 600 lines or 40 KB, flag it:
> "RESEARCH_MEMORY.md is over the compaction threshold — run system-health-maintenance workflow, Section 8."

**STOP — Mission Complete.**

> **Discoverability note:** Each completed Stage-1 run is automatically appended to
> `TradeScan_State/research/index.csv`. To query across all runs without folder scanning:
> ```python
> import csv
> rows = list(csv.DictReader(open(r'TradeScan_State\research\index.csv')))
> hits = [r for r in rows if float(r['profit_factor'] or 0) > 1.5
>         and float(r['max_drawdown_pct'] or 99) < 10]
> ```
> Filter by `schema_version='legacy'` to exclude pre-patch runs from provenance-sensitive queries.
> Filter by `schema_version='1.3.0'` for runs with full provenance (content_hash + git_commit + execution_model).

---

## Appendix A: Failure Handling & Playbook
On ANY failure:
1.  Classify per `AGENT.md` failure playbook.
2.  Report exact failure class (e.g., `SCHEMA_VIOLATION`, `EXECUTION_ERROR`).
3.  Do NOT attempt silent repairs. Report to user immediately.

## Appendix B: Protected Infrastructure Policy
The agent MUST NOT modify the following without an **implementation plan** and **user approval**:
- `tools/*.py`, `engines/*.py`, `governance/*.py`, `vault/**`, `.agents/workflows/*.md`.

## Appendix C: System Contract
- Deterministic, Ledger-authoritative, Append-only, Fail-fast.
- Post-pipeline analysis (Robustness, Portfolios) is conducted via `portfolio-research.md`.
- System hygiene (Cleanup, Formatting) is conducted via `system-health-maintenance.md`.

