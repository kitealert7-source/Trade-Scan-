# AGENT.md — System Invariants & Operational Contract

**Authority:** Governance-First Pipeline Architecture
**Status:** DIAGNOSTIC ONLY — No mutation authority

> [!CAUTION]
> This is a diagnostic and remediation guide only. MUST NEVER authorize automatic mutation of strategy code, directives, artifacts, `run_state.json`, or Master Ledgers.

---

### Pre-Directive Creation Gate (MANDATORY — Zero-Cost Failure Point)

Before creating ANY file (directive, strategy.py, sweep_registry, idea_registry):

1. Read `governance/namespace/token_dictionary.yaml`
2. Confirm MODEL token exists in `model:` list
3. Not found → check `aliases.model`. Still not found → STOP. Resolve before creating files.

**Why**: Agent creates files before INBOX submission. Wrong token = full multi-file rename. Catching at Step 0 costs nothing.

**Valid MODEL tokens** (source of truth: `token_dictionary.yaml`):
RSIAVG, ZREV, VOLEXP, ATRBRK, BOS, CHOCH, SFP, IBREAK, PINBAR, ENGULF,
LIQGRAB, PORT, ULTC, DAYOC, SMI, LORB, RSIPULL, SPKFADE, GAPFILL,
BBSQZ, ATRSQZ, ASRANGE, FAKEBREAK, LIQSWEEP, CMR, MICROREV, IMPULSE

**New pass**: `python tools/new_pass.py <source> <new>` → edit → `python tools/new_pass.py --rehash <new>` → `python tools/run_pipeline.py <new>`
**Edit existing**: Just edit strategy.py/directive → `python tools/run_pipeline.py <name>` (Auto-Consistency Gate handles hashes)
**Re-run after PORTFOLIO_COMPLETE**: `python tools/new_pass.py --rehash <name>` → `python tools/run_pipeline.py <name>`
**GENESIS_MODE** (_P00): `python tools/run_pipeline.py --all --provision-only`

NEVER manually edit sweep_registry.yaml hashes or clean run directories.

---

## SYSTEM INVARIANTS

Non-negotiable. The agent must never violate any of these.

1. **Ledger Supremacy** — `Master_Portfolio_Sheet.xlsx` and `Strategy_Master_Filter.xlsx` are append-only. No deletion. No overwrite.
2. **Fail-Fast** — Any failure at any stage aborts the entire pipeline. No partial progression.
3. **Artifact Authority** — All gating decisions derive from physical artifact existence and content, not memory or cache.
4. **Snapshot Immutability** — `TradeScan_State/runs/<RUN_ID>/strategy.py` and `STRATEGY_SNAPSHOT.manifest.json` are write-once.
5. **State Machine Integrity** — `run_state.json` transitions are strictly forward. FAILED is terminal. Re-provisioning is the only recovery.
6. **Directive Integrity** — Directives in `backtest_directives/INBOX/` are not modified by the pipeline. Only moved to `completed/` on success.
7. **Deterministic Execution** — Same directive + same data = same output. No randomness. No inference. No implicit defaults.
8. **Single Authority** — Only `run_pipeline.py` may mutate `run_state.json`.
9. **Append-Only Audit** — `directive_audit.log` and run audit logs are append-only.
10. **Human Gating** — No new `strategy.py` may enter execution without explicit human approval.
11. **Protected Infrastructure** — `tools/`, `engines/`, `engine_dev/`, `governance/`, `.claude/skills/` require implementation plan + explicit human approval before modification.
12. **Single Signature Authority** — Signature construction owned exclusively by `tools/directive_schema.py:normalize_signature()`.
13. **Genesis/Clone Classification** — New strategies use GENESIS_MODE (directive-only, no cross-family borrowing). Existing strategies use CLONE_MODE.
14. **No Workspace Mode** — All pipeline executions run in strict integrity mode. Engine hash + tools manifest verification mandatory.
15. **Governance-Authorized Reset Only** — `--force` removed. Failed directives reset via `tools/reset_directive.py --reason "<justification>"` only (logged to `governance/reset_audit_log.csv`). Full resets delete the directive-level run folder. `--to-stage4` only valid from PORTFOLIO_COMPLETE. Agent MUST NOT invoke reset autonomously.
16. **Guard-Layer Manifest** — `tools/tools_manifest.json` is SHA-256 bound. `generate_guard_manifest.py` is human-only.
17. **Root-of-Trust Vault Binding** — `verify_engine_integrity.py` is hash-bound via `vault/root_of_trust.json`. Agent MUST NOT modify.
18. **Engine Manifest Generator** — `tools/generate_engine_manifest.py` is human-only.
19. **Directive Schema Freeze** — `tools/canonical_schema.py` (FREEZE policy). Unknown keys, misplaced blocks, type mismatches = HARD FAIL.
20. **Capital Model Invariant (v3.0 Retail Amateur — 2026-04-16)** — Seed capital: **$1,000 total** (not per-symbol). Active profiles: `RAW_MIN_LOT_V1` (0.01 lot unconditional), `FIXED_USD_V1` (retail conservative: max(2% equity, $20 floor); heat/leverage caps disabled), `REAL_MODEL_V1` (retail aggressive: tier-ramp 2%→5% per equity doubling; `retail_max_lot=10`). Must be synchronized across `broker_specs/`, `portfolio_evaluator.py`, `capital_wrapper.py`, `tools/capital_engine/`. Retired profiles (`DYNAMIC_V1`, `CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`, `MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1`, institutional `FIXED_USD_V1`/$10k/5x) must not be reintroduced without governance plan.
21. **Namespace Governance** — `filename == test.name == test.strategy`. Must pass `tools/namespace_gate.py` at Stage -0.30.
22. **Sweep Registry Integrity** — Sweeps reserved at Stage -0.35. Reuse only for exact idempotent matches (same directive + same hash).
23. **Symbol Universe Admission** — Each symbol must exist in broker specs + have RESEARCH data before Stage-1.
24. **Clean Repository Rule** — Trade_Scan is immutable during execution. All runtime artifacts written to `TradeScan_State/` exclusively.
25. **Scratch Script Placement** — All ad-hoc/diagnostic scripts go to `/tmp/` exclusively. No transient scripts in the repo root.
26. **Sequential Execution Only** — One directive at a time. 15-second cooldown between runs. Batch submission prohibited.
27. **Multi-Symbol Deployment Contract** — Multi-symbol research strategies MUST be split into per-symbol instances for TS_Execution. `strategy.name == id` invariant enforced by `strategy_loader.py`.
28. **Live Deployment Pre-Gate** — Before adding to `TS_Execution/portfolio.yaml`, ALL must pass: (1) Phase 0 smoke test, (2) signal schema validation (no `stop_price=0.0`), (3) ENGINE_FALLBACK parity (multiplier matches `ENGINE_ATR_MULTIPLIER`), (4) spot-check on live/recent bar.
29. **Indicator Separation** — All indicator logic MUST live in `indicators/` as importable modules. Inline indicator computation in `strategy.py` (rolling windows, statistical aggregation, external data loading) is prohibited. Enforced at Stage-0.5 by three guards: FORBIDDEN_TERMS, ExternalDataGuard, InlineIndicatorDetector.
30. **Mandatory Tool Routing** — On ANY pipeline failure the agent MUST:
    1. Consult `outputs/system_reports/04_governance_and_guardrails/TOOL_ROUTING_TABLE.md` (FAST PATH OVERRIDE first, Section 2 otherwise).
    2. Match the symptom to a defined scenario (F01–F19).
    3. Satisfy ALL preconditions before any tool execution.

    **Violation → STOP tool execution.** Then: attempt classification via the routing table; if scenario is clear → proceed per its tier; if ambiguity remains → escalate to human.

    **Additional rule — no tool execution without classification.**

    **Tool exclusivity:** Only ONE primary tool may be executed per failure resolution step. Chaining tools without re-classifying the post-tool symptom state is prohibited — cascading fixes mask root causes and silently corrupt state.

    **Supervised Research Posture:** Backtests run under close human supervision. Default posture for the four flexible scopes (F02 exploratory reset, F19 re-run, tool sequencing, Tier 1 ambiguity) is ANNOUNCE + PROCEED, not STOP. STRICT STOP is preserved ONLY for correctness-critical cases: F10 pre-traceback, F03/F04 cleanup without `--dry-run`, governance scopes (F05/F06/F08/F13/F15/F16), and system invariants.

    **ANNOUNCE format (mandatory, one line):**
    `[ANNOUNCE] <SCENARIO> | risk: <what may go wrong> | action: <what is being done>`
    All three fields required. Missing any field = silent violation. Full scope table, examples, and decision rules in TOOL_ROUTING_TABLE.md "Research Override Layer".

    For EXECUTION_ERROR (F10): HARD STOP — no tool may be selected before the traceback is read and subclassified.

### Recovery Tiers (brief — see TOOL_ROUTING_TABLE.md for full tier assignment)

| Tier | Meaning | Execution Rule |
|:---:|:---|:---|
| 1 | SAFE AUTO — deterministic, reversible | Execute directly |
| 2 | GUARDED AUTO — requires dry-run + `--confirm` | Execute only after validation |
| 3 | CONDITIONAL FLOW — classification required | NO execution until scenario identified |
| 4 | HUMAN REQUIRED — ambiguous/non-reversible/authoring | Escalate to human |

### On Failure

→ STOP immediately → Do NOT attempt ad-hoc fixes → Consult `TOOL_ROUTING_TABLE.md` FAST PATH OVERRIDE → If no match, Section 2 → Classify scenario + tier → Execute only per tier rule (Tier 4 = escalate)

---

## LIFECYCLE OVERVIEW

> Full pipeline diagram: `outputs/system_reports/01_system_architecture/pipeline_flow.md`

```
Directive → Stage -0.25 (Canonicalization) → Stage -0.30 (Namespace) → Stage -0.35 (Sweep)
  → Stage 0 (Preflight) → Stage 0.5 (Semantic) → Stage 0.55 (Coverage) → Stage 0.75 (Dry-Run)
  → Stage 1 (Engine Execution) → Stage 2 (Compilation) → Stage 3 (Aggregation)
  → Pre-Stage-4 (Manifest Integrity) → Stage 4 (Portfolio Evaluation) → PORTFOLIO_COMPLETE
  → Step 7 (Report) → Step 8 (Capital Wrapper) → Step 9 (Artifact Verify)
  → Step 10 (Robustness Suite) → Step 11 (Research Suggestion)
```

**Key gates**: Stage -0.30 blocks bad tokens. Stage 0.5 blocks hollow/invalid strategies + inline indicators. Stage 3 cardinality gate blocks row mismatches. Stage 4 blocks ledger overwrites.

**Profile selection authority**: Step 7 (`_resolve_deployed_profile` in `portfolio_evaluator.py`) is the **sole** selector for `deployed_profile`. All downstream steps (Step 8.5 profile_selector, reconcile, robustness CLI) treat `deployed_profile` as read-only from the ledger. `select_deployed_profile()` in profile_selector.py raises `RuntimeError` — do not call.

**Portfolio status gates**: FAIL if `realized_pnl <= 0` OR `trades_accepted < 50` OR `trade_density < 50` (per-symbol) OR `expectancy < asset_class_gate`. CORE/WATCH require quality metrics on top of all FAIL gates:
- **Portfolios tab**: CORE requires `edge_quality >= 0.12`; WATCH requires `edge_quality >= 0.08`
- **Single-Asset tab**: CORE requires `SQN >= 2.5`; WATCH requires `SQN >= 2.0`
- Below quality floor after passing FAIL gates → FAIL. Owned by Step 7 only.

**Strategy traceability**: Each `TradeScan_State/strategies/<ID>/` has a `strategy_ref.json` pointer with `code_hash` (sha256) linking to the authority `Trade_Scan/strategies/<ID>/strategy.py`. No strategy.py copies in state folders.

### Step 11: Research Suggestion Layer (Mandatory after Pipeline)

After every completed pipeline execution:
1. Analyze completed runs in `TradeScan_State/research/index.csv`
2. Generate **EXACTLY 0 OR 1** candidate research entry (strict template: Tags, Finding, Evidence (MAX 2 lines), Conclusion, Implication)
3. Present to human → await "yes" before appending via `python -m tools.research_memory_append`
4. NEVER generate multiple entries. NEVER append without human approval.

---

## ENGINE ARCHITECTURE STANDARDS (MANDATORY)

Prevent structural drift, shadow routing, and split execution authority.

1. **Version Namespace** — Folders must match `v<major>_<minor>_<patch>` pattern (e.g., `v1_4_0`). Must be importable via native Python syntax.
2. **No Engine Core Import Bypass** — `importlib.util.spec_from_file_location` forbidden for engine core. Dynamic loading only for strategy plugins. Standard imports: `from engine_dev.universal_research_engine.vX_Y_Z.<module> import ...`
3. **Single Execution Authority** — `execution_loop`, `execution_emitter_stage1`, `stage2_compiler` must ALL resolve inside the active version folder.
4. **Engine Self-Containment** — Version folder must be fully self-contained for Stage-1 execution, artifact emission, and Stage-2 compilation. No unversioned global dependencies.
5. **Shadow Core Prohibition** — Core execution files must not exist in multiple active locations. No implicit fallback to global modules.
6. **Manifest Localization** — `engine_manifest.json` must reside inside the active version folder. `verify_engine_integrity.py` must hash only files inside that directory. Fail strictly on any SHA-256 mismatch.
7. **Vault Non-Authority** — Vault snapshots are recovery artifacts only. Non-authoritative for execution.

---

## STRATEGY CONTRACT — `check_exit()` v1.3 (2026-04-23)

`Strategy.check_exit(ctx) -> bool | str`

- `False` → no exit
- `True` → exit; engine attributes as `STRATEGY_UNSPECIFIED` (lossy — discouraged)
- `"<LABEL>"` → exit with explicit attribution; surfaces as `STRATEGY_<LABEL>` in `results_tradelevel.csv`

**Namespace** — the namespaced `exit_source` column is single-string with these prefixes:

| Prefix | Owner | Examples |
|---|---|---|
| `ENGINE_*` | Engine | `ENGINE_STOP`, `ENGINE_TP`, `ENGINE_SESSION_RESET`, `ENGINE_DATA_END` |
| `STRATEGY_*` | Strategy `check_exit()` | `STRATEGY_TIME_CAP`, `STRATEGY_OPPOSITE_FLIP`, `STRATEGY_Z_EXTENSION` |
| `STRATEGY_UNSPECIFIED` | Bare `True` fallback | tech-debt marker — drives `Unspecified Exit %` metric |

**Precedence** (highest → lowest): `ENGINE_STOP` > `ENGINE_TP` > `ENGINE_TRAIL` > `ENGINE_SESSION_RESET` > `STRATEGY_*`

**Normalization** — `<LABEL>` is stripped + uppercased + auto-prefixed with `STRATEGY_` if it does not already start with `STRATEGY_` or `ENGINE_`. No further forgiveness.

**Stage 2 surfaces** — `Performance Summary` adds `Unspecified Exit %`; `Exit Source Breakdown` sheet shows per-source counts + PnL across All/Long/Short.

**Pre-commit guardrail** — `tools/lint_check_exit_labels.py` warns (does not block) on bare `return True` in `check_exit()`. Migrate to canonical labels when convenient.

---

> For failure classification and escalation matrix, see **FAILURE_PLAYBOOK.md**.

**End of AGENT.md**
