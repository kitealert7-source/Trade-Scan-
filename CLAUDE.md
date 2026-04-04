# CLAUDE.md — Agent Session Brief

## What This System Is

Six-repo research-to-execution pipeline:
- **Trade_Scan** (this repo) — research pipeline: directive → backtest → deployable strategy
- **TradeScan_State** (`../TradeScan_State`) — all pipeline output; shared artifact store
- **TS_Execution** (`../TS_Execution`) — MT5 live execution bridge; reads strategies from here
- **DATA_INGRESS** (`../DATA_INGRESS`) — 5-phase data pipeline: RAW → CLEAN → RESEARCH
- **Anti_Gravity_DATA_ROOT** (`../Anti_Gravity_DATA_ROOT`) — master data store
- **DRY_RUN_VAULT** (`../DRY_RUN_VAULT`) — dry run archive

**No execution authority here. No live trading. No automation.**

---

## Before Acting — Read Protocol

**Always:**
1. `AGENT.md` — invariants, lifecycle, engine standards, pre-directive gate

**Task-conditional:**
2. `SYSTEM_STATE.md` — before any pipeline run
3. `.agents/workflows/execute-directives.md` — before any `run_pipeline.py` call (including when the agent wrote the directive itself)
4. `RESEARCH_MEMORY.md` — before strategy design or directive creation
5. `FAILURE_PLAYBOOK.md` — when any failure or anomaly occurs

---

## Critical Invariants (top 5 — full list in AGENT.md)

1. **Fail-Fast** — any failure aborts the pipeline; never silently continue
2. **Append-Only Ledgers** — `Strategy_Master_Filter.xlsx` and `Master_Portfolio_Sheet.xlsx` are append-only
3. **Artifact Authority** — decisions derive from physical artifact existence, not memory or assumptions
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` is write-once
5. **Human Gating** — no strategy enters TS_Execution without explicit human approval (PORTFOLIO_COMPLETE)

---

## Topic Index — "If you are doing X, read this first"

| Task | Document |
|---|---|
| Any pipeline run or directive work | `AGENT.md` (invariants, lifecycle, pre-directive gate) + `.agents/workflows/execute-directives.md` — **read the workflow before every `run_pipeline.py` call, even when the agent authored the directive** |
| Pipeline failure or FSM repair | `FAILURE_PLAYBOOK.md` |
| Understanding pipeline stage flow | `outputs/system_reports/01_system_architecture/pipeline_flow.md` |
| Checking what entrypoints exist | `outputs/system_reports/01_system_architecture/SYSTEM_ENTRYPOINTS.md` |
| Understanding system boundaries + invariants | `outputs/system_reports/01_system_architecture/SYSTEM_SURFACE_MAP.md` |
| Touching engine code (`engine_dev/`) | `outputs/system_reports/02_engine_core/ENGINE_EXECUTION_AUDIT_v1_5_3.md` |
| Governance, naming, registry, or guardrails | `outputs/system_reports/04_governance_and_guardrails/GUARDRAILS_WALKTHROUGH.md` |
| Capital model, lot sizing, or risk | `outputs/system_reports/05_capital_and_risk_models/CAPITAL_AUDIT_REPORT.md` |
| Strategy research infrastructure or filters | `outputs/system_reports/06_strategy_research/RESEARCH_INFRASTRUCTURE_AUDIT.md` |
| Backtest dates, warm-up, regime data flow | `outputs/system_reports/06_strategy_research/BACKTEST_DATE_POLICY_AND_DATA_FLOW.md` |
| Artifact provenance or storage layout | `outputs/system_reports/08_pipeline_audit/ARTIFACT_STORAGE_AUDIT_2026_03_24.md` |
| Directive state, lifecycle, or cleanup | `outputs/system_reports/10_State Lifecycle Management/Workflow_Design.md` |
| Promoting a strategy to burn-in | `.agents/workflows/promote.md` |
| Transitioning from burn-in to waiting | `.agents/workflows/to-waiting.md` |
| Transitioning from waiting to live | `tools/transition_to_live.py` |
| Deployment, burn-in, go-live, or dry-run vault | `outputs/system_reports/11_deployment_and_burnin/GOLIVE_PACKAGE_COMPATIBILITY_AUDIT.md` |
| Directory/file authority questions | `outputs/system_reports/01_system_architecture/REPOSITORY_AUTHORITY_MAP.md` |

---

## Path Authority

`config/state_paths.py` — defines every output path to TradeScan_State. Never hardcode.

### Path & Encoding Rules (ENFORCED BY PRE-COMMIT HOOK)

**NEVER hardcode absolute user paths** like `C:\Users\faraw\...` or `/home/user/...`. The pre-commit hook (`tools/lint_no_hardcoded_paths.py`) will block any commit that contains them.

**ALWAYS use `encoding="utf-8"`** on every `.read_text()` and `open()` call. Windows defaults to cp1252 — bare `.read_text()` will silently corrupt or crash on any file containing em-dashes, arrows, or smart quotes. The pre-commit hook (`tools/lint_encoding.py`) blocks bare `.read_text()` calls.

**How to derive paths:**
```python
from pathlib import Path

# Repo root (adjust parents[N] based on file depth)
PROJECT_ROOT = Path(__file__).resolve().parent.parent      # tools/*.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]          # tools/subdir/*.py
STATE_ROOT   = PROJECT_ROOT.parent / "TradeScan_State"      # sibling repo
```

**Depth rules for this repo:**
| File location | To get Trade_Scan root | Example |
|---|---|---|
| `tools/*.py` | `.parent.parent` | `tools/run_pipeline.py` |
| `tools/subdir/*.py` | `.parents[2]` | `tools/state_lifecycle/lineage_pruner.py` |
| `tests/*.py` | `.parent.parent` (= `.parents[1]`) | `tests/test_registry_integrity.py` |
| `config/*.py` | `.parent.parent` (= `.parents[1]`) | `config/state_paths.py` |

**For sibling repos:** Always derive from this repo's root: `PROJECT_ROOT.parent / "RepoName"`

**Lint checks (both enforced by pre-commit hook):**
- `python tools/lint_no_hardcoded_paths.py` — blocks hardcoded user paths
- `python tools/lint_encoding.py` — blocks bare `.read_text()` without `encoding="utf-8"` (Windows defaults to cp1252, causing intermittent UnicodeDecodeError on files with em-dashes/arrows)

**Exempt directories:** `vault/`, `tmp/`, `archive/` — frozen snapshots and throwaway scripts are not scanned.

---

## Key Operational Commands

```bash
# Run a single directive
python tools/run_pipeline.py <DIRECTIVE_ID>

# Phase 0 validation (TS_Execution)
cd ../TS_Execution && python src/main.py --phase 0

# System preflight check
python tools/system_preflight.py
```

---

## Architecture Docs

Full document index: `outputs/system_reports/01_system_architecture/README.md`
All system reports: `outputs/system_reports/`
