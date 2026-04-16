# CLAUDE.md — Agent Session Brief

## What This System Is

Six-repo research-to-execution pipeline:
- **Trade_Scan** (this repo) — research pipeline: directive → backtest → deployable strategy
- **TradeScan_State** (`../TradeScan_State`) — all pipeline output; shared artifact store
- **TS_Execution** (`../TS_Execution`) — MT5 live execution bridge
- **DATA_INGRESS** (`../DATA_INGRESS`) — 5-phase data pipeline: RAW → CLEAN → RESEARCH
- **Anti_Gravity_DATA_ROOT** (`../Anti_Gravity_DATA_ROOT`) — master data store
- **DRY_RUN_VAULT** (`../DRY_RUN_VAULT`) — dry run archive

**No execution authority here. No live trading. No automation.**

---

## Before Acting — Read Protocol

**Always (every session start):**
- `AGENT.md` — invariants, lifecycle, engine standards, pre-directive gate
- `SYSTEM_STATE.md` — check SESSION STATUS (OK/WARNING/BROKEN), acknowledge system condition before acting

**Task-conditional:**
- `.agents/workflows/execute-directives.md` — before any `run_pipeline.py` call
- `RESEARCH_MEMORY.md` — before strategy design or directive creation
- `FAILURE_PLAYBOOK.md` — when any failure or anomaly occurs

---

## Critical Invariants (key 9 — full list of 29 in AGENT.md)

1. **Fail-Fast** — any failure aborts the pipeline; never silently continue
2. **Append-Only Ledgers** — `Strategy_Master_Filter.xlsx` and `Master_Portfolio_Sheet.xlsx` are append-only; no deletion, no overwrite
3. **Artifact Authority** — all gating decisions derive from physical artifact existence, not memory or assumptions
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` is write-once after creation
5. **Human Gating** — no strategy enters TS_Execution without explicit human approval (PORTFOLIO_COMPLETE)
6. **Protected Infrastructure** — `tools/`, `engines/`, `engine_dev/`, `governance/`, `.agents/workflows/` require implementation plan + explicit human approval before modification
7. **Sequential Execution Only** — one directive at a time; batch submission prohibited; minimum 15s cooldown between runs
8. **Scratch Script Placement** — all ad-hoc/diagnostic scripts go to `/tmp/` exclusively; no transient scripts in the repo root
9. **Indicator Separation** — all indicator logic must live in `indicators/` as importable modules; inline computation and external data loading in strategy.py is prohibited (enforced at Stage-0.5)

---

## Topic Index — "If you are doing X, read this first"

| Task | Document |
|---|---|
| Pipeline run or directive work | `AGENT.md` + `.agents/workflows/execute-directives.md` |
| Pipeline failure or FSM repair | `FAILURE_PLAYBOOK.md` |
| Pipeline stage flow | `outputs/system_reports/01_system_architecture/pipeline_flow.md` |
| Entrypoints | `outputs/system_reports/01_system_architecture/SYSTEM_ENTRYPOINTS.md` |
| System boundaries + invariants | `outputs/system_reports/01_system_architecture/SYSTEM_SURFACE_MAP.md` |
| Engine code (`engine_dev/`) | `outputs/system_reports/02_engine_core/ENGINE_EXECUTION_AUDIT_v1_5_3.md` |
| Governance, naming, registry | `outputs/system_reports/04_governance_and_guardrails/GUARDRAILS_WALKTHROUGH.md` |
| Capital model, lot sizing, risk | `outputs/system_reports/05_capital_and_risk_models/CAPITAL_SIZING_AUDIT.md` |
| Research infrastructure or filters | `outputs/system_reports/06_strategy_research/RESEARCH_INFRASTRUCTURE_AUDIT.md` |
| Backtest dates, warm-up, regime | `outputs/system_reports/06_strategy_research/BACKTEST_DATE_POLICY_AND_DATA_FLOW.md` |
| Artifact provenance or storage | `outputs/system_reports/08_pipeline_audit/ARTIFACT_STORAGE_AUDIT_2026_03_24.md` |
| Directive state, lifecycle, cleanup | `outputs/system_reports/10_State Lifecycle Management/Workflow_Design.md` |
| Promoting a strategy to burn-in | `.agents/workflows/promote.md` |
| Burn-in → waiting transition | `.agents/workflows/to-waiting.md` |
| Waiting → live transition | `tools/transition_to_live.py` |
| Deployment, burn-in, go-live | `outputs/system_reports/11_deployment_and_burnin/README.md` (index) |
| Directory/file authority | `outputs/system_reports/01_system_architecture/REPOSITORY_AUTHORITY_MAP.md` |
| System audit or review | Browse `outputs/system_reports/` folder READMEs first — each subfolder has an index |
| Ending a work session | `.agents/workflows/session-close.md` — commit, push, document, clean up |

---

## Path & Encoding Rules (ENFORCED BY PRE-COMMIT HOOK)

`config/state_paths.py` — defines every output path to TradeScan_State. Never hardcode.

- **NEVER hardcode** absolute user paths (`C:\Users\faraw\...`). Hook: `tools/lint_no_hardcoded_paths.py`
- **ALWAYS** `encoding="utf-8"` on every `.read_text()` and `open()`. Hook: `tools/lint_encoding.py`
- **Exempt:** `vault/`, `tmp/`, `archive/`

**Path derivation** using `Path(__file__).resolve()`:
- `tools/*.py` → `.parent.parent`; `tools/subdir/*.py` → `.parents[2]`
- `tests/*.py` / `config/*.py` → `.parent.parent`
- Sibling repos: `PROJECT_ROOT.parent / "RepoName"`

---

## Key Operational Commands

```bash
python tools/run_pipeline.py <DIRECTIVE_ID>   # run a single directive
python tools/system_preflight.py              # system preflight check
cd ../TS_Execution && python src/main.py --phase 0  # phase 0 validation
```

---

## Architecture Docs

Full index: `outputs/system_reports/01_system_architecture/README.md`
