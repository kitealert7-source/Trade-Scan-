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

**Step 0 — Skill discovery (mandatory before any non-trivial task):**
The system-reminder at session start lists every available skill with its name and description (alphabetical, flat). For grouped picking with **when-to-use / when-NOT / related** annotations, read **`.claude/skills/CATALOG.md`** — the hand-curated index. Before starting work that goes beyond a one-line answer or a single-file read, scan one of those two surfaces and ask: *"Is there a skill for this?"*
- If a skill matches → invoke it (or read its `SKILL.md`) and follow it unless the user explicitly overrides.
- If nothing matches → proceed normally. If the task surfaces durable process knowledge that isn't in any existing skill, name a candidate skill in your end-of-task summary so it can be created next time.

Skills already cover (non-exhaustive): pipeline runs, strategy ports / Pine→Python, hypothesis testing, re-runs of prior strategies, promote-to-LIVE deployment, portfolio add/remove/research, session close, repo cleanup + refactor, pipeline-state cleanup, system health maintenance, supervised Windows task launch, vault snapshots, capital simulation, Excel ledger formatting. **New skills appear in the system-reminder list automatically** — but `CATALOG.md` must be hand-updated when a skill is added / renamed / removed (the catalog file's "Maintenance" section spells out the protocol).

**Always (every session start):**
- `AGENT.md` — invariants, lifecycle, engine standards, pre-directive gate
- `SYSTEM_STATE.md` — check SESSION STATUS (OK/WARNING/BROKEN), acknowledge system condition before acting

**Task-conditional documents (skill-specific reading is implied by Step 0):**
- `RESEARCH_MEMORY.md` — before strategy design or directive creation
- `FAILURE_PLAYBOOK.md` — when any failure or anomaly occurs

---

## Supervised Backtesting Posture

Backtests run under close human supervision. The four flexible scopes (F02 exploratory reset, F19 re-run, tool sequencing, Tier 1 ambiguity) default to **ANNOUNCE + PROCEED**, not STOP.

**ANNOUNCE format (mandatory, one line):**
```
[ANNOUNCE] <SCENARIO> | risk: <what may go wrong> | action: <what is being done>
```

**STRICT STOP preserved for:** F10 pre-traceback, F03/F04 cleanup without `--dry-run`, governance scopes (F05/F06/F08/F13/F15/F16), system invariants.

**F19 re-test guard (before authoring any new directive):** scan `RESEARCH_MEMORY.md` for prior `NO_TRADES` entries with matching strategy + symbol + TF + filter config. If match found → either document a material parameter delta in the new directive's rationale, or do not submit.

Full rules: `outputs/system_reports/04_governance_and_guardrails/TOOL_ROUTING_TABLE.md` "Research Override Layer".

---

## Critical Invariants (key 9 — full list of 29 in AGENT.md)

1. **Fail-Fast** — any failure aborts the pipeline; never silently continue
2. **Append-Only Ledgers** — `Strategy_Master_Filter.xlsx` and `Master_Portfolio_Sheet.xlsx` are append-only; no deletion, no overwrite
3. **Artifact Authority** — all gating decisions derive from physical artifact existence, not memory or assumptions
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` is write-once after creation
5. **Human Gating** — no strategy enters TS_Execution without explicit human approval (PORTFOLIO_COMPLETE)
6. **Protected Infrastructure** — `tools/`, `engines/`, `engine_dev/`, `governance/`, `.claude/skills/` require implementation plan + explicit human approval before modification
7. **Sequential Execution Only** — one directive at a time; batch submission prohibited; minimum 15s cooldown between runs
8. **Scratch Script Placement** — all ad-hoc/diagnostic scripts go to `/tmp/` exclusively; no transient scripts in the repo root
9. **Indicator Separation** — all indicator logic must live in `indicators/` as importable modules; inline computation and external data loading in strategy.py is prohibited (enforced at Stage-0.5)

---

## Topic Index — "If you are doing X, read this first"

| Task | Document |
|---|---|
| Pipeline run or directive work | `AGENT.md` + `.claude/skills/execute-directives/SKILL.md` |
| Pipeline failure or FSM repair | `FAILURE_PLAYBOOK.md` |
| Tool routing (execution + recovery) | `outputs/system_reports/04_governance_and_guardrails/TOOL_ROUTING_TABLE.md` |
| Data ingestion / missing RESEARCH data | `../DATA_INGRESS/README.md` (cross-repo) |
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
| Promoting a strategy to LIVE | `.claude/skills/promote/SKILL.md` |
| Deployment doctrine (historical) | `outputs/system_reports/11_deployment_and_burnin/README.md` (index) |
| Basket directive / RECYCLE family / H2 engine | `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` (LOCKED v11) — `tools/basket_runner.py`, `tools/basket_pipeline.py`, `tools/basket_data_loader.py`, `tools/recycle_strategies.py`, `tools/recycle_rules/`, `governance/recycle_rules/registry.yaml`. Dispatched by `tools/run_pipeline.py:_try_basket_dispatch` |
| ABI manifest / engine_abi versioning | `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` §1l + §5.12 — single ABI on `engine_abi.v1_5_9`; `tools/abi_audit.py` triple-gate enforcer (pre-commit + CI + runtime) |
| Directory/file authority | `outputs/system_reports/01_system_architecture/REPOSITORY_AUTHORITY_MAP.md` |
| System audit or review | Browse `outputs/system_reports/` folder READMEs first — each subfolder has an index |
| Ending a work session | `.claude/skills/session-close/SKILL.md` — commit, push, document, clean up |

---

## Path & Encoding Rules (ENFORCED BY PRE-COMMIT HOOK)

`config/path_authority.py` — single source of truth for repo + sibling resolution. **Always import siblings from here**, never compute inline. `config/state_paths.py` is a compatibility wrapper that delegates to path_authority.

- **NEVER hardcode** absolute user paths (`C:\Users\faraw\...`). Hook: `tools/lint_no_hardcoded_paths.py`
- **NEVER write** `PROJECT_ROOT.parent / "TradeScan_State"` (or TS_Execution / DRY_RUN_VAULT / Anti_Gravity_DATA_ROOT). Lint blocks the pattern; from a worktree it resolves to a stale `.claude/worktrees/<sibling>` leftover instead of the real one.
- **ALWAYS** `encoding="utf-8"` on every `.read_text()` and `open()`. Hook: `tools/lint_encoding.py`
- **Exempt dirs (lint):** `vault/`, `engine_dev/` (frozen engine versions), `tmp/`, `archive/`

**Path derivation** using `Path(__file__).resolve()`:
- `tools/*.py` → `.parent.parent`; `tools/subdir/*.py` → `.parents[2]`
- `tests/*.py` / `config/*.py` → `.parent.parent`
- Sibling repos: `from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT` (or TRADE_SCAN_STATE / DRY_RUN_VAULT / ANTI_GRAVITY_DATA_ROOT / DATA_ROOT). Marker is `.git.is_dir()` — worktrees have `.git` as a *file*, only the real repo has it as a *directory*.

---

## Worktree & Junction Safety (HARD PROHIBITION)

**NEVER create an NTFS directory junction (`mklink /J`) inside a Claude worktree** — and especially never one that targets `Anti_Gravity_DATA_ROOT`, `TradeScan_State`, `TS_Execution`, `DATA_INGRESS`, or `DRY_RUN_VAULT`.

**Why:** worktree teardown (or any `rm -rf` of the worktree directory) follows junctions and recursively deletes the *target's contents*. On 2026-05-07 a junction `worktree/data_root → Anti_Gravity_DATA_ROOT` caused silent loss of 21,043 research files (4.04 GB across 34 `_MASTER` dirs). Recovery required a full NAS robocopy + sha256 reverify; the next mirror-backup would have made the loss permanent had it been allowed to run.

**Allowed alternatives:**
- Read sibling repos through `config.path_authority` (resolves the real repo via `.git.is_dir()`, immune to worktree leftovers).
- If a tool absolutely needs `data_root` inside the worktree, use a *symbolic file link* via Python (`Path.symlink_to`) for individual files only — never `mklink /J` on a directory.
- For temporary cross-repo work, `cd` into the sibling repo directly; do not bridge it into the worktree's tree.

**Pipeline runs from worktrees are supported** as of commit `2c316e3` (2026-05-08) — `governance/preflight.py` resolves `PROJECT_ROOT` via `config.path_authority.REAL_REPO_ROOT`, so DATA_GATE finds `data_root/` on the real repo regardless of where you invoke from. No junction needed. If you find any other tool deriving root from `Path(__file__).parent.parent` and breaking under a worktree, patch it the same way.

**If you find yourself typing `mklink /J` — stop and re-read this section.** No exceptions in scratch scripts, in `/tmp/`, or "just for this session". The cost of the failure mode (silent multi-GB data loss) is asymmetric to any convenience the junction provides.

**Reference:** `outputs/system_reports/09_incident_reports/DATA_RECOVERY_REPORT.md`

---

## Service-Account Migration Safety (HARD PROHIBITION)

**Before changing the run-as identity or LogonType of any scheduled task that touches `MASTER_DATA`, `DATA_INGRESS`, or any other path under a sibling repo, you MUST run `tools/scheduled_task_identity_smoke.ps1` in `validate` mode and observe a clean exit 0.**

```powershell
powershell -File tools\scheduled_task_identity_smoke.ps1 `
    -Mode validate `
    -ExpectedUser   '<new-user>' `
    -RequiredGroup  '<expected-group>'      # e.g., BATCH for Password/S4U logon
    -ForbiddenGroup '<must-not-be-in-group>' # e.g., INTERACTIVE
    -TargetDir      '<dir-the-task-writes-to>' `
    -LogonType      '<Password|S4U|Interactive>' `
    -Credential     (Get-Credential)        # only for LogonType=Password
```

The tool is binary pass/fail with specific non-zero exit codes (101 identity mismatch, 102 required group missing, 103 forbidden group present, 104 file-op failed, 105/106/107 validate-mode parse failures). **No human interpretation, no "looks fine" override.** If the tool exits non-zero, the migration is not approved.

**Why this exists:** the 2026-05-07 incident's follow-up service-account migration was approved on a smoke test that printed the right warning (`INTERACTIVE=True, BATCH=False`) but didn't *fail* on it. The script ran as the wrong identity, the result was logged as PASS, and the architecture broke at the first natural production trigger. Hours of wasted work. The harness now refuses to confuse "the script ran" with "the script ran as the expected user".

**Reference:** `outputs/system_reports/09_incident_reports/DATA_RECOVERY_REPORT.md` §9.6

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
