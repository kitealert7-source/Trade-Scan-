# Engine Consolidation — Implementation Plan (single active compute engine)

**Status:** ✅ DESIGN APPROVED 2026-06-29 (operator review — decisions A/C/E resolved, rename-to-disabled gate added). **Execution pending explicit go** (Invariant #6: protected infra — `engine_dev/`, `tools/`, `config/`, `governance/`). No code touched yet.
**Date:** 2026-06-29 · **Author:** agent (Claude) · **Trigger:** operator — "there should be only one version of engine which is active."

> **No code touched.** This is the plan; nothing executes until approved.

---

## 1. Motivation (verified, not asserted)

The multi-version engine archive in the *active* tree (`engine_dev/universal_research_engine/`, 9 versions v1_5_3…v1_5_11) is **evolutionary debt with no remaining functional consumer**, established by three verified facts:

1. **Capability superset.** Engines accumulate capabilities down the lineage; v1.5.11 declares `execution.{entry,exit,partial_exit,intrabar_ur}.v1` — the union of all predecessors. No old engine holds a capability v1.5.11 lacks → the capability-driven resolver never needs an older version.
2. **No live artifact on old engines.** Every live row is **v1.5.10 or v1.5.11**: `master_filter` 1.5.10×22 / 1.5.11×5; `cointegration_sheet` 1.5.10×477; zero artifacts ≤ v1.5.9. The uncharged historical results (computed on old engines) were purged 2026-06-25 (cost-regime → charged-only).
3. **No reproduction intent.** The deleted historical results were *known-wrong* (uncharged cost model) — nothing anyone would byte-reproduce.

→ **v1.5.3–v1.5.9 have no data, no capability, and no replay target.** Their only remaining references are a *dormant code scaffold* (resolver, registry, abi_audit, an emitter fallback, one accidental import, version-specific tests, manifest lineage). The work is to **unwind the scaffold, then remove the dirs** — bounded, because nothing load-bearing is left.

### 1a. The decisive fact — the removal set is *defective*, not just dead (operator, 2026-06-29)

**v1.5.10 introduced the correct cost model** (manifest `adds`: *"Direction-aware execution: SELL fills at bid, BUY fills at ask"* — spread-charging, 2026-06-17). **Every engine ≤ v1.5.9 is UNCHARGED** (v1.5.9's `adds` are pure refactor — no cost change). So the charged/uncharged boundary **is exactly v1.5.10 — identical to the keep/remove line of this plan.** The removal set isn't "dead archive that nobody happens to use"; it is a set of engines with a **known-faulty cost structure that can only ever produce wrong results.** There is therefore **no valid replay or audit target** — reproducing a pre-v1.5.10 run reproduces a *known-wrong number*. This both strengthens the removal rationale and **relaxes the preservation bar** (see §3, P1): you do not carefully archive a defective engine for replay; git history is sufficient forensic record of "the code that had the cost bug."

---

## 2. Target state

`engine_dev/universal_research_engine/` holds **two** compute engines with **explicitly different operational roles** (operator, 2026-06-29) — this is still a **single-runtime architecture**:
- **v1_5_11** — **canonical execution engine.** The one and only engine the runtime ever runs.
- **v1_5_10** — **rollback / reference compute engine.** Byte-identical, swap-safe; stamped the live charged baseline. **Not** a second "active" engine — it is *never chosen* during normal execution.

**Invariant (the heart of the simplification): runtime engine *selection* is forbidden.** Nothing in normal execution chooses *between* the two. The runtime never asks *"which engine?"* — only *"is the active (canonical) engine valid?"*. v1_5_10 is reached **only** by a deliberate operator rollback action, never by an automatic resolver.

Everything older (v1_5_3…v1_5_9) is **removed** from `engine_dev/` (git history is the forensic record — §1a; `vault/engines/` archival optional). The multi-version scaffold is **dismantled**, not merely shrunk.

> **Decision A — RESOLVED (operator, 2026-06-29):** keep v1_5_10, but as the **rollback/reference** role above — *not* a second active engine. Single-runtime preserved: normal execution always uses v1_5_11; v1_5_10 is an operator-only swap target. ✅

### Scope boundary — compute engine vs Signal ABI (do not conflate)
- **IN SCOPE:** `engine_dev/universal_research_engine/v1_5_X/` — the **compute engines**.
- **OUT OF SCOPE (separate decision):** `engine_abi/v1_5_9|v1_5_10|v1_5_11` — the **basket Signal ABI shims** (engine-free contracts, `abi_audit`-gated, imported at `basket_runner.py:38`). `engine_abi.v1_5_9` being named "9" does **not** require the v1.5.9 *compute* engine. Collapsing the ABI shims is a related but distinct refactor — flagged as **Open decision B**, not executed here.

---

## 3. Preconditions (non-negotiable — all must hold before Phase 6 deletion)

- **P1 — Forensic preservation = git history (RELAXED per §1a).** The removal set is *defective* (uncharged) — there is no valid result to replay, so a pristine vault copy is **not** required. The committed engine code in **git history** is sufficient forensic record of the cost-bug era, and is always restorable. The earlier "complete + byte-verify `vault/engines/` (it lacks v1.5.5)" precondition is therefore **downgraded from a hard gate to optional housekeeping** — do it only if you want convenient immutable access to the buggy engines; it is NOT a blocker for deletion. (Contrast: a *correct* engine would warrant the full archive bar — but we are removing only defective ones.)
- **P2 — v1_5_10 retained** in `engine_dev/` (rollback). Never removed by this plan.
- **P3 — `ledger.db` + a full repo snapshot backed up** (timestamped) before Phase 6.
- **P4 — Zero live artifacts on removed versions** — re-verify the §1.2 query at execution time (defensive; the store could change between plan + execute).

---

## 4. Phased plan (atomic commits — design → tighten → atomic-phase → break-test)

Each phase is a standalone reviewable commit that leaves the system GREEN (`pytest` gate + `abi_audit` + `system_preflight`). Order matters: **scaffold first, dirs last.**

### Phase 0 — Confirm git-history preservation *(RELAXED — see §1a / P1)*
- Removal set is defective (uncharged) → **no byte-archive required.** Just confirm the dirs are committed in git history (they are) so deletion is `git revert`-able. Record the current HEAD sha in the deletion commit message as the restore anchor.
- *(Optional housekeeping, not a gate:)* add v1.5.5 + normalize naming in `vault/engines/` only if you want convenient immutable access to the buggy engines. Skippable.
- **Verify:** `git log -- engine_dev/.../v1_5_<n>` shows history for each removal candidate (restorable).

### Phase 1 — Re-point accidental / fallback imports
- `tools/strategy_dryrun_validator.py:29` — `from ...v1_5_6.execution_loop import ContextView` → import from the active engine (`v1_5_11`). Break-test: `ContextView` is version-agnostic; confirm dry-run validator output unchanged.
- `tools/run_stage1.py` — the **v1_5_6 emitter fallback** (`_emit_resolve_emitter_and_capabilities`): remove the fallback branch (it only fires if a pinned emitter is missing — impossible once only v1.5.10/v1.5.11 remain, both of which carry emitters). Replace with a hard error (already the intended behaviour for a real wiring fault).
- **Verify:** full `pytest` + a `run_stage1` smoke on a representative directive.

### Phase 2 — ABI audit scope *(NO-OP CONFIRMATION — decision C resolved)*
- **Already verified (2026-06-29):** all 3 shims bind only kept compute (`v1_5_9→v1_5_10`, `v1_5_10→v1_5_10`, `v1_5_11→v1_5_11`); none binds a removal-set engine. So no shim re-pointing is needed and the shims stay untouched.
- **Verify:** re-run the sanity grep (`engine_abi/` → `v1_5_[3-9]` compute = empty) + `abi_audit` triple-gate PASS. Confirmation only.

### Phase 3 — Registry becomes metadata; resolver becomes a validator *(the conceptual core)*

The point is **not** "registry with two entries" — it is **kill runtime engine selection entirely.** (Operator, 2026-06-29.)

**Invariant to enforce:**
```
Runtime engine selection is FORBIDDEN.
engine_registry exists only to IDENTIFY:
    - canonical engine  (v1_5_11)
    - rollback engine   (v1_5_10)
The registry is METADATA, not a SELECTOR.
```

- `config/engine_registry.json` — reduce to exactly `{canonical: v1_5_11, rollback: v1_5_10}` as **named roles** (not a candidate list). Remove the 7 old entries.
- `tools/engine_resolver.py` — **invert the contract from selection to validation.** Today it answers *"which engine satisfies these capabilities?"* (sorts candidates by semver, picks max). Replace with: *"is the canonical engine valid for this run?"* — a single-engine assertion (canonical satisfies required capabilities/contract → proceed; else hard-fail). It must **never enumerate** engine dirs or choose among versions. The runtime asks *"is the active engine valid?"*, never *"which engine?"*.
- `config/engine_loader.py` / `config/engine_authority.py` — drop hardcoded references to removed versions; ensure `get_active_engine()` resolves canonical directly (no scan/select).
- **Enforcement:** the Phase-7 lint also asserts no code path enumerates `universal_research_engine/` dirs at runtime (selection cannot creep back).
- **Verify:** `pytest` + `system_preflight` REGISTRY GREEN; a grep proving no runtime `iterdir()`/glob over the engine dir.

### Phase 4 — Retire version-specific tests *(quantified delta — known target)*

**Measured 2026-06-29.** The test footprint tied *exclusively* to the removed engines is small — the broader suite is overwhelmingly current-functionality (baskets/cointegration/recycle/governance), which runs on the active engine and is untouched.

**Remove (dedicated to a removed engine):**
| file | collected pytest cases | note |
|---|---|---|
| `test_v157_engine_level.py` | **8** | v1.5.7-specific |
| `test_engine_atr_fallback.py` | **2** | v1.5.4-specific |
| `regression_v154_1h.py` | 0 (standalone script) | file removed; **not** in pytest count |
| `smoke_v154_15m.py` | 0 (standalone script) | file removed; **not** in pytest count |

**Update — re-point version strings, NO case removal** (these reference old versions in *bodies/fixtures*, not as parametrized arms — 0 removable nodes): `test_engine_abi_adversarial`, `test_engine_abi_ts_execution_boot`, `test_engine_identity_convergence`, `test_intent_injector_frozen_path` (re-point v1_5_3/v1_5_8 → kept). Case counts unchanged.

**Keep untouched:** `test_v1510_*` (rollback engine live), `test_engine_health_counters_v1_5_11`, `test_engine_abi_v1_5_9/10/11` (shims — decision B), the 81-case gate suite (none version-specific).

**Expected broader-pytest delta: −10 collected cases → baseline `2232 → 2222` (≈0.4%).** This becomes the **known target** for Phase 5.5 / Phase 6 verification: a *pass* is `2222 passed` (not merely "green"), and the post-refactor broader-pytest baseline must be updated to 2222 via `check_broader_pytest_baseline.py --update-baseline --rationale "engine consolidation: removed v1.5.7/v1.5.4 dedicated tests (-10)"`.

- **Verify:** `pytest` → exactly **2222 passed** (any other count = an unexpected case lost/added — investigate before proceeding); no test imports a removed dir.

### Phase 5 — Manifest lineage + governance contract
- Manifest `predecessor` fields (`v1_5_9←v1_5_8`, `v1_5_10←v1_5_8`, `v1_5_11←v1_5_10`) are **descriptive metadata**, not runtime gates. Leave v1_5_11←v1_5_10 (both retained); the removed dirs' manifests go to the vault with them.
- **Amend `governance/SOP/ENGINE_VAULT_CONTRACT.md`** — this is the *early rule being re-judged*. Add a clause: *active `engine_dev/` holds {canonical, rollback} only; superseded compute engines are removed from the active tree (git history is the forensic record; defective/uncharged engines need no replay archive — §1a); `vault/engines/` archival is optional housekeeping.* This is the governance heart of the change — **needs explicit operator sign-off.**
- **Cross-repo doc cleanup (TS_Execution, decision E residual):** update the stale compute-path references — `TS_Execution/README.md` ("locked to v1_5_3"), `docs/FREEZE_MANIFEST.md` ("v1.5.9 / path …/v1_5_9/"), `harness/fixtures/golden/no_signal_minimal/README.md`, `harness/tests/test_replay.py` comments — to reflect the real binding (`engine_abi.v1_5_9` → `engine_dev/v1_5_10`). Docs only; do in a TS_Execution commit (mind cross-repo git state — [[feedback_cross_repo_preflight]]).

### Phase 5.5 — Rename-to-disabled dependency proof *(operator-required gate; makes Phase 6 a confirmation, not an experiment)*

A cheap, reversible proof that **no hidden runtime resolution path** remains — run *before* the irreversible `git rm`:
```
mv  v1_5_3 … v1_5_9   →   _DISABLED_v1_5_3 … _DISABLED_v1_5_9
```
The dirs still exist on disk but are **unresolvable** (the import path no longer matches). By this point Phase 4 has already removed the version-specific tests, so the renamed-but-unresolvable dirs should perturb nothing. Run the full gate suite **with the dirs renamed**:
- `pytest` → **exactly 2222 passed** (the Phase-4 known target; any import of a renamed engine would surface as a failure here — that's the whole point of the proof)
- `python tools/system_preflight.py` → all structural GREEN
- `python tools/abi_audit.py` (triple-gate)
- a **representative single-asset backtest** (run_pipeline on one directive → completes on v1_5_11)
- a **representative basket run** (exercises `engine_abi` → v1_5_10 path)

**Pass criterion:** everything GREEN while v1_5_3–v1_5_9 are present-but-unresolvable ⇒ proven zero runtime dependence. **Then** rename back (`_DISABLED_* → v1_5_*`) and proceed to Phase 6 — the `git rm` is now a *confirmation* of a proven-safe state, not a test. If anything fails, the rename instantly localizes the hidden dependency and is trivially reverted (`mv` back) with zero data loss.

### Phase 6 — Remove the defective compute dirs *(now a confirmation, per Phase 5.5)*
- **Pre-delete gate:** Phase 5.5 passed; re-run the §1.2 live-artifact query → must be **0** on v1.5.3–v1.5.9 (defensive); confirm git history present (P1); record HEAD sha in the commit message. *(No vault sha256 gate — defective engines, git is the restore path.)*
- `git rm -r engine_dev/universal_research_engine/v1_5_3 v1_5_4 v1_5_5 v1_5_6 v1_5_7 v1_5_8 v1_5_9`.
- **Verify:** full `pytest` → **exactly 2222 passed** (the Phase-4 known target — confirms no unexpected case lost/added) + `abi_audit` + `system_preflight` ALL GREEN; `git grep` finds zero live-code imports of the removed versions; update the broader-pytest baseline to 2222 (rationale per Phase 4).

### Phase 7 — Lock it with an enforcement gate *(prevent regression)*
- Add a **pre-commit + CI lint** (`tools/lint_no_removed_engine_imports.py`): fail on any `import …universal_research_engine.v1_5_{3..9}` outside `vault/`. Per [[feedback_enforceable_mechanisms_only]] — the consolidation must be *enforced*, not just documented, or it decays.
- **Verify:** lint catches a deliberately-introduced bad import in a test fixture.

---

## 5. Risks & open decisions

| # | Item | Disposition |
|---|---|---|
| A | Truly-one vs keep v1_5_10 | ✅ **RESOLVED (operator, 2026-06-29):** keep v1_5_10 as **rollback/reference** (operator-only swap target), v1_5_11 = sole canonical execution engine. Single-runtime; **runtime selection forbidden** (Phase 3). |
| B | Collapse the `engine_abi` Signal shims too (v1_5_9/10/11) | **Separate refactor** — out of scope here; baskets depend on the shim contract |
| C | `engine_abi` shims transitively need a removal-set compute engine? | ✅ **RESOLVED 2026-06-29 — NO.** All 3 shims bind only kept compute: `engine_abi.v1_5_9→v1_5_10`, `v1_5_10→v1_5_10`, `v1_5_11→v1_5_11`. Sanity grep for any shim→`v1_5_[3-9]` compute = empty. The "v1_5_9" shim name is a contract label decoupled from its compute binding. **Phase 2 is now a no-op confirmation.** |
| D | A future bug found in a removed engine's *logic* (audit) | Recoverable from git history (P1) + `vault/engines/` if archived |
| E | TS_Execution (sibling) imports a removal-set engine | ✅ **RESOLVED 2026-06-29 — CLEAR.** TS_Execution's *only* governed dependency is `engine_abi.v1_5_9` (`bridge.py` comment confirms), which binds `engine_dev/v1_5_10` (kept). No direct or transitive import of v1_5_3–v1_5_9 compute. **Removing them does not break TS_Execution.** Residual: stale *docs* in TS_Execution (`README.md` "locked to v1_5_3", `FREEZE_MANIFEST.md` "v1.5.9 path …/v1_5_9/", golden-fixture README, `test_replay.py` comments) reference removal-set compute *paths* — documentation only, not runtime; update as cross-repo doc cleanup (added to Phase 5). |

## 6. Rollback
Each phase is one revertible commit. **Primary restore path = git history** (the removed dirs are committed; the deletion commit records the restore-anchor sha) → any phase is `git revert`-able and any removed engine is restorable via `git checkout <sha> -- <path>`. `vault/engines/` is a secondary (optional) copy. v1_5_10 retained throughout = swap-safe production fallback. (No need for a pristine vault copy of a *defective* engine — §1a.)

## 7. Out of scope
- `engine_abi` Signal-shim consolidation (Open decision B).
- `vault/engines/` deeper history (v1.2.0/v1.2.1/v1.5.2) — already archive-only, untouched.
- Any change to v1.5.11 trade logic (this is removal/wiring only — zero trade-behaviour change; a Phase-6 `system_preflight` + golden-run check confirms byte-neutrality).

## 8. Sequencing / effort
Phases 0→7 sequential, each a reviewable commit. Phase 0 + 5.5 + 6 + 7 (git-check / rename-proof / delete / lint) are mechanical; Phases 1, 3, 4, 5 (re-point + registry-to-metadata + tests + contract) are the substance (Phase 2 is now a no-op confirmation, decision C). Recommend **two sessions**: (1–3) wiring + registry-to-metadata + resolver-to-validator, then (4 → 5 → **5.5 rename-proof** → 6 delete → 7 lint) — with a GREEN checkpoint between. **Phase 5.5 is the operator-required confidence gate that turns the final `git rm` into a confirmation.**
