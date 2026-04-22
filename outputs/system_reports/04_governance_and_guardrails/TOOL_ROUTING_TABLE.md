# TOOL_ROUTING_TABLE.md — Pipeline Execution & Recovery

**Authority:** `AGENT.md` (Invariant 30) + `FAILURE_PLAYBOOK.md`
**Scope:** Pipeline execution (Stage -0.35 → PORTFOLIO_COMPLETE) + failure recovery only
**Enforcement:** MANDATORY consultation. Tool selection without classification = invariant violation.

---

## FAST PATH OVERRIDE (Reflex Layer)

The FAST PATH is split into two types. **Do not conflate them.**

### FAST PATH — DIRECT (execute immediately on symptom match)

> Execute the listed sequence. No classification step required — the symptom IS the classification.

```
[F03]  [FATAL] Stage-3 cardinality mismatch (found > expected)
       python tools/cleanup_ledger.py --strategy-id <ID> --dry-run
       python tools/cleanup_ledger.py --strategy-id <ID> --confirm
       python tools/reset_directive.py <ID> --reason "stale ledger rows cleared"

[F04]  [FATAL] Attempted modification of existing portfolio entry
       python tools/cleanup_mps.py --portfolio-id <ID> --dry-run
       python tools/cleanup_mps.py --portfolio-id <ID> --confirm
       python tools/reset_directive.py <ID> --reason "stale portfolio entry cleared" --to-stage4
```

### FAST PATH — CONDITIONAL (requires classification step BEFORE any tool execution)

> **DO NOT execute a tool until the prerequisite step completes.** Treating these like DIRECT = invariant violation.

```
[F02]  [FATAL] Illegal state transition  OR  directive refuses to re-run
       PREREQUISITE: IDENTIFY root cause (which F-class drove FAILED). Reset alone is NOT a fix.
       THEN: python tools/reset_directive.py <ID> --reason "<root-cause + fix>"

[F10]  Non-zero exit + traceback from Stage-1
       PREREQUISITE: HARD STOP — read full traceback, classify via F10 subclass table.
       NO tool may be selected before subclassification.

[F16]  Stage -0.30 NAMESPACE_TOKEN_INVALID / IDENTITY_MISMATCH / IDEA_ID_UNREGISTERED
       PREREQUISITE: Consult governance/namespace/token_dictionary.yaml + idea_registry.yaml.
       Classify subtype (TOKEN / IDENTITY / PATTERN / IDEA_ID) — then escalate to human for fix.
       Most common cause: MODEL token typo (e.g. VOLEXPAND vs VOLEXP).
```

---

## Recovery Tiers

| Tier | Meaning | Execution Rule |
|:---:|:---|:---|
| **1** | SAFE AUTO — fully deterministic, reversible, zero ambiguity | Execute directly **only when symptom match is unambiguous**. Any doubt → treat as Tier 3. |
| **2** | GUARDED AUTO — requires dry-run preview + `--confirm` before mutation | Execute only after validation passes |
| **3** | CONDITIONAL FLOW — classification required before action | NO tool execution until scenario identified |
| **4** | HUMAN REQUIRED — ambiguous authority, non-reversible, or strategy authoring | Escalate to human |

> **Tier 1 caveat:** "SAFE AUTO" assumes the symptom matches exactly. If the symptom overlaps with another scenario (e.g. `ModuleNotFoundError` could be F11 OR a stale import in F07), fall through to classification. No execution under ambiguity.

**Tier assignment (all 19 scenarios):**

| Tier | Scenarios |
|:---:|:---|
| **1** | F01, F11, F14 |
| **2** | F03, F04 |
| **3** | F02, F07, F10, F12, F17, F18 |
| **4** | F05, F06, F08, F09, F13, F15, F16, F19 |

---

## Section 1 — Failure Scenario Inventory

| ID | Tier | Freq | Scenario | Observable Symptom |
|:---|:---:|:---:|:---|:---|
| F01 | 1 | MED | TOOLS_MANIFEST_STALE | `[ORCHESTRATOR] Tool modified after manifest generation: <file>.py` |
| F02 | 3 | **HIGH** | STATE_TRANSITION_INVALID | `[FATAL] Illegal state transition` or pipeline refuses to re-enter FAILED directive |
| F03 | 2 | **HIGH** | ORPHANED_LEDGER_STAGE3 | `[FATAL] Stage-3 cardinality mismatch: expected X, found Y` (Y > X) |
| F04 | 2 | **HIGH** | IDEMPOTENT_OVERWRITE_LOCK | `[FATAL] Attempted modification of existing portfolio entry '<ID>'` |
| F05 | 4 | MED | PROVISION_REQUIRED | `[HollowDetector] check_entry() body is empty` at Stage-0.5 |
| F06 | 4 | MED | SCHEMA_VIOLATION | `[FATAL] Signature mismatch` or `signature_version mismatch` at Stage-0.5 |
| F07 | 3 | MED | INDICATOR_IMPORT_MISMATCH | `Missing Indicator Import(s)` or `Undeclared Indicator Import(s)` |
| F08 | 4 | MED | FILTERSTACK_VIOLATION | `[BehavioralGuard] FilterStack not found` or hardcoded regime pattern |
| F09 | 4 | MED | DRYRUN_CRASH | Exception in `prepare_indicators` / `check_entry` at Stage-0.75 |
| F10 | 3 | **HIGH** | EXECUTION_ERROR | Non-zero exit + traceback from Stage-1 subprocess |
| F11 | 1 | RARE | MISSING_INDICATOR_MODULE | `ModuleNotFoundError: No module named 'indicators.X.Y'` |
| F12 | 3 | RARE | PREFLIGHT_FAILURE | `Preflight REJECTED` at Stage-0 |
| F13 | 4 | RARE | INTEGRITY_VIOLATION | Hash mismatch in `STRATEGY_SNAPSHOT.manifest.json` or snapshot vs source |
| F14 | 1 | RARE | DATA_LOAD_FAILURE | `No RESEARCH CSV found for <SYMBOL>/<BROKER>/<TF>` |
| F15 | 4 | RARE | MISSING_BROKER_SPEC | `FileNotFoundError: Broker spec not found: broker_specs/<BROKER>/<SYMBOL>.yaml` |
| F16 | 4 | **HIGH** | NAMESPACE_GATE_FAIL | Stage -0.30: `NAMESPACE_TOKEN_INVALID` / `_IDENTITY_MISMATCH` / `_PATTERN_INVALID` / `IDEA_ID_UNREGISTERED` |
| F17 | 3 | MED | SWEEP_GATE_FAIL | Stage -0.35: `SWEEP_IDEMPOTENCY_MISMATCH` or `Invalid signature_hash 'placeholder'` |
| F18 | 3 | LOW | AK_TRADE_REPORT_MISSING | SCHEMA_VALIDATION: Stage-2 did not produce `AK_Trade_Report` for a symbol (NOT signature mismatch) |
| F19 | 4 | LOW | NO_TRADES_EXPLICIT | Stage-1 artifact missing + `Probable NO_TRADES`; `results_tradelevel.csv` absent or empty |

---

## Global Rule — Classification Before Action

```
HARD RULE:
No tool execution is allowed without:
  1. matched failure scenario (F01–F19)
  2. satisfied preconditions
  3. tier-appropriate validation (dry-run for Tier 2, classification for Tier 3)

For EXECUTION_ERROR (F10):
  → DO NOT SELECT ANY TOOL
  → FIRST read full traceback
  → classify using F10 subclass table
  → THEN proceed to mapped scenario

TOOL EXCLUSIVITY (meta-rule):
  → Only ONE primary tool may be executed per failure resolution step.
  → Chaining tools without re-classification is PROHIBITED.
  → After each tool run: re-observe symptom state. If a new failure appears,
    restart at classification — do NOT assume continuity with the prior scenario.
  → Rationale: cascading fixes mask root causes and silently corrupt state.
```

---

## Research Override Layer (Supervised Posture)

Backtests run under close human supervision. Default posture for the flexible scopes
is **ANNOUNCE + PROCEED**, not STOP. STRICT STOP is preserved only where the concern
is correctness of the run itself, not permission to run.

### Override Scope (exhaustive — do not extend)

| Scope | Default posture | Marker required |
|:---|:---|:---|
| F02 exploratory reset (root cause unclear) | ANNOUNCE + PROCEED | `reason` begins with `EXPLORATORY:` + probe statement |
| F19 NO_TRADES re-run | ANNOUNCE + PROCEED | Param delta stated (delta softens warning; absence = loud warn) |
| Tool exclusivity (sequential use) | ANNOUNCE + PROCEED | One-line re-observation note between tools |
| Tier 1 ambiguity (≥2 scenarios match) | ANNOUNCE + PROCEED | Primary choice + runner-up both named |

### ANNOUNCE Format (MANDATORY — 1 line, no free-form)

    [ANNOUNCE] <SCENARIO> | risk: <what may go wrong> | action: <what is being done>

**Examples:**

    [ANNOUNCE] F02 EXPLORATORY | risk: root cause unknown | action: resetting directive
    [ANNOUNCE] F19 RE-RUN | risk: no parameter change, result likely identical | action: re-running directive
    [ANNOUNCE] TIER1 AMBIGUITY | risk: F10 vs F18 overlap | action: proceeding with F10 classification
    [ANNOUNCE] TOOL SEQUENCE | risk: prior fix may have masked second failure | action: running cleanup_ledger after reset_directive
    [ANNOUNCE] F02 REPEAT (3rd) | risk: same directive reset 3 times this session | action: resetting again

**Rules:**
- One line. No multi-line expansion. No bullet lists inside fields.
- All three fields present. Missing field = invalid announce, counts as silent violation.
- `<SCENARIO>` must be one of: `F02`, `F19`, `F02 REPEAT`, `TIER1 AMBIGUITY`, `TOOL SEQUENCE`. No free-form scenario tags allowed.
- `risk:` states the actual concrete risk in ≤12 words.
- `action:` states the immediate next tool invocation in ≤12 words.

### Decision Rules

    ANNOUNCE + PROCEED (default under supervision):
      - F02 EXPLORATORY reset         (marker: EXPLORATORY: prefix + probe)
      - F19 re-run with delta         (marker: delta named in announce)
      - Sequential tool use           (marker: one-line re-observation note)
      - Tier 1 with clear primary     (marker: primary + runner-up named)

    WARN LOUDLY + PROCEED (visible to supervisor, still no block):
      - F19 re-run with NO param change   → [ANNOUNCE] includes "no parameter change"
      - >=3rd reset on same directive      → [ANNOUNCE] includes "REPEAT (Nth)"
      - Tier 1 with genuine >=2-way tie    → [ANNOUNCE] names both candidates
      - Tool run with no re-observation    → [ANNOUNCE] flags "no re-observation"

    STRICT STOP (correctness — NEVER overridable, even under supervision):
      - F10 before traceback read + subclassified
      - F03/F04 cleanup without --dry-run → verify → --confirm sequence
      - Governance scopes: F05, F06, F08, F13, F15, F16 (human authoring authority)
      - System invariants: snapshot immutability, append-only ledgers, sequential execution

### Edge Case Handling

    Repeated resets (awareness, not block)
      → Track count in session. Announce each reset with REPEAT (Nth) tag from #2 onwards.
      → Supervisor intercepts visually; no automatic escalation.

    Re-running identical directive (deterministic no-op)
      → Announce "no parameter change, result likely identical". Supervisor decides.
      → Do NOT silently re-run without the announce.

    Ambiguous classification (F10 / F17 / F18)
      → Announce tie. Pick upstream scenario as primary.
      → Rule of thumb: traceback mentions sweep → F17; mentions AK_Trade_Report → F18; else → F10.

    Partial fix → new failure
      → Announce with TOOL SEQUENCE tag + re-observation line.
      → Treat the new failure as fresh classification. Do NOT assume continuity.

### Audit trail

Every `[ANNOUNCE]` line is the audit record. Supervisors can grep `[ANNOUNCE]` across
session transcripts to reconstruct the override history. No separate log file.

---

## Section 2 — Deterministic Tool Mapping

---

### F01 — TOOLS_MANIFEST_STALE  [TIER 1 · MED]

| | |
|:---|:---|
| ✅ **Primary** | `python tools/generate_guard_manifest.py` |
| ❌ **Wrong** | Manually editing `tools_manifest.json`; `--no-verify` |
| **Precondition** | Tool change was intentional and approved. Human-only (Invariant 16). |
| **Post-check** | `python tools/run_pipeline.py <ID>` passes startup guardrails |

---

### F02 — STATE_TRANSITION_INVALID  [TIER 3 · HIGH]

> **Reset is NOT a diagnostic tool.** MUST identify root cause BEFORE reset.
> MUST confirm failure class (F05–F15) that drove the directive to FAILED.

| | |
|:---|:---|
| ✅ **Primary** | (1) Identify failure class → (2) fix root cause → (3) `python tools/reset_directive.py <ID> --reason "<failure-class + fix>"` |
| ⚠️ **Variant** | `--to-stage4` ONLY when: (a) state is PORTFOLIO_COMPLETE, (b) only Stage-4 needs rerun, (c) >3 symbols. ≤3 symbols → full reset. |
| ❌ **Wrong** | Resetting before classifying; manually editing `run_state.json`/`directive_state.json`; deleting state files; `--force` (removed) |
| **Precondition** | Failure class identified. Reason string names the failure class (e.g. `"F09 DRYRUN_CRASH fix"`). |
| **Post-check** | Pipeline accepts directive at Stage -0.35 |

---

### F03 — ORPHANED_LEDGER_STAGE3  [TIER 2 · HIGH]

**Three-step protocol:**
```
Step 1: python tools/cleanup_ledger.py --strategy-id <ID> --dry-run
Step 2: VERIFY row count + sample preview match expectation
Step 3: python tools/cleanup_ledger.py --strategy-id <ID> --confirm
Step 4: python tools/reset_directive.py <ID> --reason "stale ledger rows cleared"
```

| | |
|:---|:---|
| ✅ **Primary** | `cleanup_ledger.py` (dry-run → verify → confirm) then `reset_directive.py` |
| ⚠️ **Variant** | `purge_run_id.py` — only when cleanup is by exact `run_id`, not `strategy_id` prefix |
| ❌ **Wrong** | Running `--confirm` without first running `--dry-run`; deleting entire Master Filter; Excel GUI edits; running `stage3_compiler.py` directly |
| **Precondition** | Confirm Y > X (duplicates). If Y < X → different failure (missing run → F10). |
| **Post-check** | Row count for `strategy_id` == expected symbol count |

---

### F04 — IDEMPOTENT_OVERWRITE_LOCK  [TIER 2 · HIGH]

**Three-step protocol:**
```
Step 1: python tools/cleanup_mps.py --portfolio-id <ID> --dry-run
Step 2: VERIFY row count + sample preview match expectation
Step 3: python tools/cleanup_mps.py --portfolio-id <ID> --confirm
Step 4: python tools/reset_directive.py <ID> --reason "stale portfolio entry cleared" --to-stage4
```

| | |
|:---|:---|
| ✅ **Primary** | `cleanup_mps.py` (dry-run → verify → confirm) then `reset_directive.py --to-stage4` |
| ❌ **Wrong** | Running `--confirm` without `--dry-run` first; bypassing the overwrite lock in `portfolio_evaluator.py`; deleting entire MPS |
| **Precondition** | Existing entry is from a failed/incomplete run, not a valid historical record. |
| **Post-check** | MPS contains exactly 1 row for this `portfolio_id` after re-run |

---

### F05 — PROVISION_REQUIRED  [TIER 4 · MED]

| | |
|:---|:---|
| ✅ **Primary** | Human authors `check_entry()`, `check_exit()`, `prepare_indicators()` → Admission Gate approval → `reset_directive.py --reason "strategy authored"` → re-run |
| ❌ **Wrong** | Auto-generating strategy logic; bypassing HollowDetector |
| **Escalation** | Agent MUST escalate to human. No autonomous recovery. |
| **Post-check** | Stage-0.5 passes |

---

### F06 — SCHEMA_VIOLATION  [TIER 4 · MED]

| | |
|:---|:---|
| **Default rule** | If unclear which side is authoritative → **the DIRECTIVE wins.** Never edit the directive to match the strategy. |
| ✅ **Directive changed** | `reset_directive.py --reason "re-provision after directive change"` → re-run |
| ✅ **Strategy edited** | Human restores `STRATEGY_SIGNATURE` in strategy.py from directive → re-run |
| ❌ **Wrong** | Patching signature manually; downgrading `signature_version`; editing directive to match strategy |
| **Escalation** | Non-reversible authority decision. Human confirms which side is authoritative before action. |
| **Post-check** | Stage-0.5 passes signature check |

---

### F07 — INDICATOR_IMPORT_MISMATCH  [TIER 3 · MED]

**Classification required:**
```
Read directive `indicators:` block vs strategy.py `from indicators.*` imports.
Default rule: DIRECTIVE wins. Align strategy to directive unless directive was demonstrably miscopied.
```

| | |
|:---|:---|
| ✅ **Strategy imports wrong** | Edit strategy.py imports → re-run (no reset) |
| ✅ **Directive wrong** | Fix directive → `reset_directive.py --reason "directive indicator list corrected"` → re-run |
| ❌ **Wrong** | Auto-adding imports; removing undeclared imports without understanding |
| **Precondition** | Side identified via default rule. |
| **Post-check** | Stage-0.5 passes import equality check |

---

### F08 — FILTERSTACK_VIOLATION  [TIER 4 · MED]

| | |
|:---|:---|
| ✅ **Primary** | Human edits strategy.py to route regime gating through `FilterStack`; remove hardcoded `row["regime"] == X`; Admission Gate approval → re-run |
| ❌ **Wrong** | Auto-patching; removing BehavioralGuard; proceeding to execution |
| **Escalation** | Architectural correction requires human. |
| **Post-check** | Stage-0.5 BehavioralGuard passes |

---

### F09 — DRYRUN_CRASH  [TIER 4 · MED]

| | |
|:---|:---|
| ✅ **Primary** | Read exception + traceback → human fixes strategy bug → Admission Gate approval → re-run. If already FAILED: `reset_directive.py` first. |
| ❌ **Wrong** | Bypassing dry-run; proceeding to Stage-1; auto-patching without approval |
| **Escalation** | Strategy bug = human authoring domain. |
| **Post-check** | Stage-0.75 completes without exception |

---

### F10 — EXECUTION_ERROR  [TIER 3 · HIGH] — HARD STOP

> **HARD RULE — ENFORCED:**
> IF Stage-1 exits non-zero → **DO NOT SELECT ANY TOOL.**
> FIRST read full traceback.
> THEN classify using subclass table below.
> ONLY THEN select the routed tool. Skipping this = invariant violation.

**Subclass table — consult BEFORE selecting tool:**

| Traceback pattern | Subclass | Route to |
|:---|:---|:---|
| Strategy/indicator logic crash | Strategy Authoring (Tier 4) | Fix strategy → `reset_directive.py` → re-run |
| `No RESEARCH CSV found` | Data missing | → **F14** |
| `ModuleNotFoundError: indicators.*` | Missing module | → **F11** |
| `Broker spec not found` | Missing spec | → **F15** |
| `KeyError: 'close'` / `'volatility_regime'` | Payload/dataframe bug (Tier 4) | Human fixes `prepare_indicators` → `reset_directive.py` → re-run |
| Process crash (env, OS, memory) | Environmental | Fix environment → re-run (no reset if not FAILED) |

| | |
|:---|:---|
| ✅ **Primary** | After subclassification ONLY: fix root cause → `reset_directive.py --reason "<subclass + fix>"` → re-run |
| ❌ **Wrong** | **Retrying before reading traceback**; suppressing exception; modifying execution engine |
| **Post-check** | Stage-1 exits 0 + `results_tradelevel.csv` exists |

---

### F11 — MISSING_INDICATOR_MODULE  [TIER 1 · RARE]

| | |
|:---|:---|
| ✅ **Primary** | `git show HEAD:indicators/path/file.py > indicators/path/file.py` |
| ⚠️ **If not in git** | Escalate to Tier 4: re-implement from `.pyc` semantics (human judgment). Do NOT use `.pyc` as runtime substitute. |
| ❌ **Wrong** | Proceeding with only `.pyc`; importing from `__pycache__` directly |
| **Pre-check** | `python -c "from indicators.X.Y import Z"` confirms absence |
| **Post-check** | Same command exits 0 |

---

### F12 — PREFLIGHT_FAILURE  [TIER 3 · RARE]

**Classification required** — route by which preflight check failed:

| Failed check | Route to |
|:---|:---|
| Engine hash mismatch | `python tools/verify_engine_integrity.py` → investigate (Tier 4) |
| Missing indicator module | → **F11** (Tier 1) |
| Broker spec missing | → **F15** (Tier 4) |
| Directive malformed | Re-read `tools/canonical_schema.py`, fix directive (Tier 4) |

| | |
|:---|:---|
| ✅ **Primary** | `python tools/system_preflight.py` → read failed check → route per table |
| ❌ **Wrong** | Skipping preflight; force-passing |
| **Precondition** | Specific failed check identified. |
| **Post-check** | `system_preflight.py` returns all PASS |

---

### F13 — INTEGRITY_VIOLATION  [TIER 4 · RARE]

| | |
|:---|:---|
| ✅ **Primary** | `reset_directive.py --reason "artifact integrity violation"` → re-run from Stage-0 |
| ❌ **Wrong** | Re-binding manifest; modifying artifacts to restore hash; `--to-stage4`; any partial re-run |
| **Escalation** | Potential tamper event. Human confirms before full re-provision. |
| **Note** | NOT recoverable by partial rerun. All stages must re-execute. |
| **Post-check** | Fresh run completes Stage-3A with newly bound manifest |

---

### F14 — DATA_LOAD_FAILURE  [TIER 1 · RARE]

| | |
|:---|:---|
| ✅ **Primary** | `../DATA_INGRESS` → run `build_freshness_index` / data pipeline for missing symbol/TF → re-run pipeline (no reset unless FAILED) |
| ❌ **Wrong** | Fabricating data; using CLEAN tier as fallback (RESEARCH only); downloading during execution |
| **Post-check** | `data_root/freshness_index.json` contains symbol/TF entry |

---

### F15 — MISSING_BROKER_SPEC  [TIER 4 · RARE]

| | |
|:---|:---|
| ✅ **Primary** | Human creates `data_access/broker_specs/<BROKER>/<SYMBOL>.yaml` with ALL mandatory fields → `reset_directive.py --reason "broker spec added"` → re-run |
| **Mandatory fields** | `min_lot`, `lot_step`, `max_lot`, `cost_model`, `precision`, `tick_size`, `pip_size`, `margin_currency`, `profit_currency`, `calibration` |
| ❌ **Wrong** | Hardcoding defaults in engine; copying another symbol's spec without adjusting values |
| **Escalation** | Broker-specific values require human research. |
| **Post-check** | Stage-0 broker spec check passes |

---

### F16 — NAMESPACE_GATE_FAIL  [TIER 4 · HIGH]

> Stage -0.30 rejects directive before any pipeline work begins. Governance authority is human.

**Subtype table:**

| Subtype | Root cause | Route |
|:---|:---|:---|
| `NAMESPACE_TOKEN_INVALID` (e.g. `MODEL='LORB' not in allowed set`) | Typo or unregistered token in directive `test.name` | Human fixes directive token. Consult `governance/namespace/token_dictionary.yaml`. Common: `VOLEXPAND` → `VOLEXP`. |
| `NAMESPACE_IDENTITY_MISMATCH` | Directive filename stem ≠ `test.name` parsed identity | Human aligns filename + `test.name`. |
| `NAMESPACE_PATTERN_INVALID` | `test.name` doesn't match canonical pattern | Human re-authors per canonical format. |
| `IDEA_ID_UNREGISTERED` | `idea_id` in directive not present in `idea_registry.yaml` | Human registers idea via governance flow before re-run. |

| | |
|:---|:---|
| ✅ **Primary** | (1) Read error → match subtype → (2) fix directive OR register token/idea in governance (human) → (3) `reset_directive.py --reason "F16 <subtype> fix"` → re-run |
| ❌ **Wrong** | Editing `token_dictionary.yaml` to "match" a typo; bypassing namespace gate; guessing MODEL tokens. Token lookup is MANDATORY (see CLAUDE.md namespace rule). |
| **Precondition** | Token dictionary + idea registry consulted. Root cause classified to specific subtype. |
| **Post-check** | Stage -0.30 passes on re-run |

---

### F17 — SWEEP_GATE_FAIL  [TIER 3 · MED]

> Stage -0.35 sweep registry check. Requires classification: re-run hash drift vs genuine identity conflict.

**Subtype table:**

| Subtype | Root cause | Route |
|:---|:---|:---|
| `SWEEP_IDEMPOTENCY_MISMATCH` after editing an existing pass | Pass hash drifted from registry | `python tools/new_pass.py --rehash <NAME>` — does NOT touch directive state |
| `SWEEP_IDEMPOTENCY_MISMATCH` on a re-run of completed pass | Identity already allocated at different SNN | Human confirms whether to rehash or allocate new SNN |
| `Invalid signature_hash 'placeholder'` | Registry entry never finalized | Human finalizes pass in registry → re-run |

| | |
|:---|:---|
| ✅ **Primary** | Classify subtype → `new_pass.py --rehash <NAME>` (hash drift) OR human resolves identity conflict in `governance/namespace/sweep_registry.yaml` → re-run |
| ⚠️ **Variant** | After `--rehash`, a `reset_directive.py` is ALSO required if the directive is already in FAILED state (see Known Gotcha #11). |
| ❌ **Wrong** | Manually editing sweep registry hash (Known Gotcha #8); using `reset_directive.py` alone for hash drift (doesn't rehash); running `--rehash` on an unchanged pass |
| **Precondition (hash drift path)** | ALL must hold before `--rehash`: (1) pass was **intentionally edited** since last admission, (2) registry hash **differs from computed hash** (inspect both), (3) no other directive shares this identity at a different SNN. Failing ANY → escalate to Tier 4. |
| **Precondition (identity conflict path)** | Human has reviewed both registry entries and decided whether to rehash or allocate new SNN. Not an agent decision. |
| **Post-check** | Stage -0.35 passes on re-run |

---

### F18 — AK_TRADE_REPORT_MISSING  [TIER 3 · LOW]

> SCHEMA_VALIDATION stage fails because Stage-2 compiler did not emit `AK_Trade_Report` for a symbol. Distinct from F06 (signature mismatch).

**Classification required — route by upstream cause:**

| Upstream cause | Route |
|:---|:---|
| Stage-1 produced no trades (empty `results_tradelevel.csv`) | → **F19** (NO_TRADES_EXPLICIT) |
| Stage-1 crashed silently for one symbol | → **F10** (read traceback for that symbol) |
| Data gap for a specific symbol/TF | → **F14** (DATA_LOAD_FAILURE) |
| Stage-2 compiler bug | Tier 4 — human investigates compiler output |

| | |
|:---|:---|
| ✅ **Primary** | After subclassification ONLY: route to mapped scenario. Fix upstream → `reset_directive.py --reason "<subclass + fix>"` → re-run |
| ❌ **Wrong** | Fabricating an empty AK_Trade_Report; bypassing SCHEMA_VALIDATION; re-running Stage-2 in isolation |
| **Precondition** | Per-symbol Stage-1 outputs inspected. Upstream cause identified. |
| **Post-check** | `AK_Trade_Report` exists for every symbol in directive |

---

### F19 — NO_TRADES_EXPLICIT  [TIER 4 · LOW]

> Strategy produced zero trades. This is a **research verdict, not a recovery**.

| | |
|:---|:---|
| ✅ **Primary** | Human research decision: (a) accept NO_TRADES as kill signal → decommission, OR (b) loosen filters via **new directive** (new `__SUFFIX` or `new_pass.py`) |
| ❌ **Wrong** | Re-running the same directive hoping for different output (deterministic — it will not); editing strategy.py to force trades; retro-fitting directive to "hide" the verdict |
| **Escalation** | Strategy design domain. Agent MUST NOT author replacement logic autonomously. |
| **Note** | Not a failure of the pipeline — the pipeline correctly reports zero edge. |
| ✅ **Post-action (MANDATORY)** | (1) Append entry to `RESEARCH_MEMORY.md` with: directive ID, strategy + symbol + TF, failure reason = `NO_TRADES`, filter/regime config snapshot, date. (2) This entry is the **re-test guard** — before authoring any new directive, the Pre-Research Checklist (CLAUDE.md) requires scanning RESEARCH_MEMORY.md for identical configurations. |
| ❌ **Re-test prevention** | Do NOT re-submit a directive whose identity + filter config matches a logged NO_TRADES entry. Only submit if ≥1 material parameter differs AND the delta is documented in the new directive's rationale. |
| **Post-check** | Either (a) directive marked decommissioned + logged in RESEARCH_MEMORY.md, OR (b) new directive authored with documented parameter delta + admitted |

---

## Section 3 — Decision Table (Executable)

```
IF  [ORCHESTRATOR] Tool modified after manifest generation: <file>.py     [F01 · TIER 1]
→   python tools/generate_guard_manifest.py   (human-only)

IF  [FATAL] Illegal state transition  OR  directive refuses to re-run    [F02 · TIER 3]
→   CLASSIFY root cause (which F-class drove FAILED state)
→   python tools/reset_directive.py <ID> --reason "<class + fix>"

IF  [FATAL] Stage-3 cardinality mismatch (found > expected)              [F03 · TIER 2]
→   python tools/cleanup_ledger.py --strategy-id <ID> --dry-run
→   VERIFY output
→   python tools/cleanup_ledger.py --strategy-id <ID> --confirm
→   python tools/reset_directive.py <ID> --reason "stale ledger rows cleared"

IF  [FATAL] Attempted modification of existing portfolio entry           [F04 · TIER 2]
→   python tools/cleanup_mps.py --portfolio-id <ID> --dry-run
→   VERIFY output
→   python tools/cleanup_mps.py --portfolio-id <ID> --confirm
→   python tools/reset_directive.py <ID> --reason "stale portfolio entry cleared" --to-stage4

IF  [HollowDetector] check_entry() body is empty                         [F05 · TIER 4]
→   ESCALATE to human. Strategy logic must be authored.

IF  Signature mismatch  OR  signature_version mismatch                   [F06 · TIER 4]
→   ESCALATE to human. DEFAULT: directive is authoritative.

IF  Missing Indicator Import(s)  OR  Undeclared Indicator Import(s)      [F07 · TIER 3]
→   CLASSIFY which side is wrong (DEFAULT: directive wins)
→   fix strategy.py imports  OR  fix directive + reset_directive.py

IF  [BehavioralGuard] FilterStack not found  OR  hardcoded regime        [F08 · TIER 4]
→   ESCALATE to human. Architectural correction required.

IF  Exception in prepare_indicators / check_entry at Stage-0.75          [F09 · TIER 4]
→   ESCALATE to human. Strategy bug must be fixed by author.

IF  Non-zero exit + traceback from Stage-1                               [F10 · TIER 3]
→   HARD STOP: DO NOT SELECT TOOL. Read traceback FIRST.
→   CLASSIFY via F10 subclass table
→   THEN proceed per subclass routing

IF  ModuleNotFoundError: No module named 'indicators.X.Y'                [F11 · TIER 1]
→   git show HEAD:indicators/X/Y.py > indicators/X/Y.py

IF  Preflight REJECTED at Stage-0                                        [F12 · TIER 3]
→   python tools/system_preflight.py
→   CLASSIFY which check failed, route per F12 sub-table

IF  Hash mismatch (manifest or snapshot)                                 [F13 · TIER 4]
→   ESCALATE to human. Full re-provision only.

IF  No RESEARCH CSV found for <SYMBOL>/<BROKER>/<TF>                     [F14 · TIER 1]
→   ../DATA_INGRESS pipeline → ingest symbol/TF → re-run

IF  Broker spec not found: broker_specs/<BROKER>/<SYMBOL>.yaml           [F15 · TIER 4]
→   ESCALATE to human. Broker YAML must be authored.

IF  Stage -0.30 NAMESPACE_TOKEN_INVALID / IDENTITY_MISMATCH / etc.       [F16 · TIER 4]
→   CONSULT governance/namespace/token_dictionary.yaml + idea_registry.yaml
→   CLASSIFY subtype (TOKEN / IDENTITY / PATTERN / IDEA_ID)
→   Human fixes directive OR registers token/idea
→   python tools/reset_directive.py <ID> --reason "F16 <subtype> fix"

IF  Stage -0.35 SWEEP_IDEMPOTENCY_MISMATCH  OR  signature_hash placeholder [F17 · TIER 3]
→   CLASSIFY: hash drift (re-run after pass edit) vs identity conflict
→   IF hash drift:  python tools/new_pass.py --rehash <NAME>
→   IF identity conflict: human resolves in sweep_registry.yaml
→   Re-run (+ reset_directive.py if already FAILED)

IF  SCHEMA_VALIDATION: AK_Trade_Report not found for <SYMBOL>            [F18 · TIER 3]
→   CLASSIFY upstream: NO_TRADES (→F19), Stage-1 crash (→F10), data gap (→F14), compiler bug (Tier 4)
→   Route per subclassification

IF  Stage-1 artifact missing / Probable NO_TRADES (zero-trade run)       [F19 · TIER 4]
→   ESCALATE to human. Research verdict — not a recovery.
→   Either decommission directive OR author new directive with loosened filters.
```

---

## Section 4 — Gaps & Ambiguities

| # | Gap | Status |
|:---|:---|:---|
| G1 | No CLI for stale ledger cleanup by strategy prefix | **CLOSED** — `cleanup_ledger.py` + `cleanup_mps.py` shipped with `--confirm` safety |
| G2 | EXECUTION_ERROR requires human subclassification | **CLOSED** — HARD STOP + Tier 3 enforcement |
| G3 | DATA_INGRESS recovery cross-repo | **CLOSED** — CLAUDE.md topic row added |
| G4 | `reset_directive.py` vs `new_pass.py --rehash` disambiguation | **CLOSED** — see table below |
| G5 | `reconcile_portfolio_master_sheet.py` misuse risk | **CLOSED** — explicit note below |
| G6 | F02 used as diagnostic shortcut | **CLOSED** — "Reset is NOT a diagnostic tool" + root-cause classification required |

### G4 — `reset_directive` vs `new_pass --rehash`

| Tool | When valid |
|:---|:---|
| `reset_directive.py` | Clear FAILED / PORTFOLIO_COMPLETE state before re-run. Changes directive lifecycle state. |
| `new_pass.py --rehash` | Update sweep registry hash after editing an existing pass. Does NOT touch directive lifecycle. |

**Never** substitute one for the other. Different subsystems.

### G5 — `reconcile_portfolio_master_sheet.py`

Patches ledger rows from `deployed_profile`. Does NOT delete rows, clear overwrite locks, or reset state. **Never invoke during F04 recovery.**

---

## Section 5 — Enforcement & Integration

**File:** `outputs/system_reports/04_governance_and_guardrails/TOOL_ROUTING_TABLE.md`

**Enforcement (Invariant 30 — see AGENT.md):**
- On ANY pipeline failure → agent MUST consult FAST PATH OVERRIDE first, then Section 2 if no match.
- Tool selection without scenario classification + satisfied preconditions = invariant violation.
- Tier 2 mutations require `--dry-run` → verify → `--confirm` sequence.
- Tier 3 scenarios require classification before any tool selection.
- Tier 4 scenarios require human escalation. Agent MUST NOT attempt autonomous recovery.

**Referenced from:**
- `CLAUDE.md` (Topic Index row)
- `FAILURE_PLAYBOOK.md` (header reference)
- `AGENT.md` (Invariant 30)

**Updates:** Static document. Update only when a new failure class is confirmed in `FAILURE_PLAYBOOK.md`.
