# Unified Engine Authority (Trade_Scan-internal) — Design & Implementation Plan

> **Goal:** establish a **single engine authority for all *Trade_Scan* execution paths** —
> single-asset *and* basket backtests — so "which engine runs *in Trade_Scan*" has exactly one
> answer that can never silently diverge or mislabel. The authority is **compute-binding by
> enforcement** (gate-verified, not a runtime dispatcher — see the *Architectural invariant* below).
>
> **Status: DESIGN APPROVED 2026-06-17 — implementation NOT yet authorized. **[EXECUTION UPDATE 2026-06-17 — superseded: Phases A→B→C ALL EXECUTED and merged to `main` via PR #3 (merge `d98a4770`). `active_engine`=v1_5_10; v1.5.10 is the single canonical charged compute for both paths. Text below is the original plan.]**** The operator approved
> Architecture C, this design, and the phase ordering (A→B→C→D). Implementation stays STOP-level
> protected-infra (Invariant #6) — every change touches `config/`, `tools/`, `engine_dev/`,
> `governance/`. **Phase A is authorizable only when the four-item gate in §7.1 is explicitly
> closed**; Phases B/C/D require *separate* approval gates (they alter compute semantics + research
> baselines). **Lands INERT** (no engine activation, no charging) when authorized.
>
> **Authored** 2026-06-17 from a multi-agent design study (4 investigators mapping the selection
> surface + a 3-architecture judge panel). Companion to
> [`V1_5_10_CANONICAL_FLIP_DESIGN.md`](V1_5_10_CANONICAL_FLIP_DESIGN.md): **that** doc is the
> *compute/charge* layer (how the basket engine actually charges spread); **this** doc is the
> *selection* layer (how every path names the one canonical engine). They compose.
> Related memory: `[[engine_identity_is_compute_not_stamp]]`, `[[project-v1_5_10-canonical-readiness]]`.

---

## Architectural invariant — compute-binding by *verification*, not *dispatch*  (read first)

This is the conceptual core of why Architecture C stays faithful to
`[[engine_identity_is_compute_not_stamp]]`, and the lens for reading the phrase "compute-binding"
everywhere below. The authority does **not** determine compute. It declares the *expected*
identity; a fail-closed gate proves that expectation equals the *real* compute:

```
static import           →  real compute       basket: basket_runner.py:38  from engine_abi.v1_5_9 import (…)
                                               single-asset: module dynamically imported in run_stage1.run_engine_logic
config/engine_authority →  expected identity   name constants only — imports NO engine
convergence gate        →  proves  expected identity == real compute
```

`config/engine_authority.py` is stdlib-only (no engine import). The gate (graft-e, §2d) asserts the
authority constant resolves to the **real imported module's own `ENGINE_VERSION`**
(`importlib.import_module(CANONICAL_ENGINE_ABI).ENGINE_VERSION == basket_runner.ENGINE_VERSION ==
CANONICAL_ENGINE_VERSION_DOTTED`), and the existing `run_stage1.py:410-420` guard already aborts on
stamp-vs-loaded-module skew. The authority **never resolves, dispatches, or returns** an engine —
that is the *rejected* Architecture A/B. So "compute-binding authority" is shorthand for **"a name
authority whose binding to compute is gate-verified."**

*Precise scope of the proof:* the gate verifies against the imported module's declared
`ENGINE_VERSION` attribute — a faithful proxy because `basket_runner.py:38` statically imports that
very module and the byte-equivalence anchor (graft 3) pins the actual compute. It is **not** a
runtime compute introspection, and this doc does not claim one.

## Scope — Trade_Scan-internal, *not* platform-wide

"Unified Engine Authority" governs **Trade_Scan only**. It does **not** govern the **TS_Execution
live ABI**, which is independently pinned to **v1_5_9** (`TS_Execution/portfolio.yaml:6`; allow-list
`_SUPPORTED_ABIS=('v1_5_3','v1_5_9')` at `TS_Execution/src/phase0_validation.py:30` — v1_5_10 is
**not** permitted and appears **zero** times in that repo, fail-closed). The end-state
research(v1.5.10)/live(v1.5.9) split is **intentional**: after convergence there is **one** engine
authority *inside* Trade_Scan but **two** across the ecosystem (research + live), by design. A
future reader must treat that divergence as designed — **not** a bug to reconcile. The Phase-D
end-state assertion (§4) binds only the **two Trade_Scan constants**; it never references
TS_Execution's pin.

---

## 0. Verdict — Architecture C (static-import + fail-closed gate), hardened

Three architectures were designed and adversarially scored:

- **A — registry resolver:** one module dynamically `importlib`-imports the engine for both paths.
  *Rejected:* a dynamic basket import **defeats the AST-static-provability** the doctrine relies on
  and likely breaks `abi_audit`'s consumed-by import check. Maximum unification, but by
  reintroducing the indirection the doctrine forbids.
- **B — engine_authority importer:** one module performs the *only* `from engine_abi import` and
  returns a handle. *Runner-up:* clean single chokepoint, but moves the import **off**
  `basket_runner` (requires re-pointing `abi_audit` consumed-by; the existing AST guard is blind to
  the new module; widens the import graph).
- **C — minimal drift-lock:** both paths keep their **static** engine imports; one tiny authority
  module holds the canonical-engine **name constants** + a normalizer (it imports *no* engine); a
  **fail-closed gate** cross-checks every selection surface against that one authority.

**C wins** on the load-bearing axes (doctrine-preservation, enforceability, migration-safety,
blast-radius) and is adequate on ambiguity-removal. Decisive reason: C is the only design that
keeps the basket import a **static, AST-visible literal** — the exact property the doctrine
hardcoded — while still collapsing "which engine is canonical" to one authority. It is
*compute-binding by enforcement* (gate + module-load assertion), not by replacing the static import
with a resolver.

**Grafts folded in from B/A** (turn C's "name authority" into a *provably* compute-bound one):
1. **Version cross-check** — the gate asserts the authority constant resolves to the **real imported
   module's `ENGINE_VERSION`** (`engine_abi.<const>.ENGINE_VERSION` *and* `basket_runner.ENGINE_VERSION`),
   not just a parsed string. (Closes C's "two constants not proven equivalent to the modules.")
2. **Symbol-superset invariant** — the gate asserts `engine_abi.<CANONICAL_ENGINE_ABI>.__all__` ⊇ the
   8 basket symbols, so a future one-file flip to v1_5_10 cannot break the import surface (enforces
   the flip doc's "verified superset" claim).
3. **Byte-equivalence anchor** — a regression test pins v1_5_8 ≡ v1_5_9 compute and v1_5_10 ≡ v1_5_9
   at spread=0, so retiring both labels keeps the equivalence proven.
4. **Latent-surface governance** — bring `strategy_dryrun_validator.py:29` (hardcoded v1_5_6
   ContextView) under the authority or document an explicit waiver in the gate.

---

## 1. The selection surface today (what the authority must subsume)

There are **four selection mechanisms** plus latent surfaces, none sharing one authority:

| # | Surface | Where | Kind | Path |
|---|---|---|---|---|
| 1 | `active_engine` (`"v1_5_8"`) | `config/engine_registry.json:2` | config string | single-asset |
| 2 | `get_engine_version()` → **dotted** `"1.5.8"` | `tools/pipeline_utils.py:213` | selector (+`ENGINE_VERSION_OVERRIDE`) | single-asset |
| 3 | `get_active_engine()` → **underscored** `"v1_5_8"` | `config/engine_loader.py:8` | duplicate selector (+override) | single-asset |
| 4a | `from engine_abi.v1_5_9 import (…)` | `tools/basket_runner.py:38` | **static compute import** | basket |
| 4b | `ENGINE_ABI = "engine_abi.v1_5_9"` | `tools/basket_runner.py:60` | hardcoded ABI literal | basket |

The single-asset string (#2) is consumed compute-bindingly at **three dynamic-import sites**:
`run_stage1.run_engine_logic:386`, `_emit_resolve_emitter_and_capabilities:468`, and
`stage_symbol_execution.py:226→230`. Each fail-fasts on `ModuleNotFoundError`; `run_engine_logic`
additionally **fail-closes when the loaded module's own `ENGINE_VERSION` ≠ the resolved string**
(`run_stage1.py:410-420` — the live `v1_5_3`-folder-ships-`1.5.4` skew guard).

**Two normalization conventions** (#2 dotted vs #3 underscored) — the authority must normalize at
the boundary, not collapse the source naively (would break whichever consumer expects the other).

**The registry is blind to the basket engine** — `engines{}` lists v1_5_6/7/8/10 but **not v1_5_9**.
And v1_5_8 ≈ v1_5_9 are the *same uncharged compute under two labels* (docstring-only diff).

**Latent surface:** `strategy_dryrun_validator.py:29` hardcodes `v1_5_6` ContextView (a dryrun
structural import, not the run engine) — outside all four mechanisms.

---

## 2. Architecture C (hardened) — the design

### 2a. `config/engine_authority.py` (new — imports NO engine)
Pure string facts + a normalizer, so it can be imported anywhere (config layer) without pulling
`engine_abi`/`engine_dev` into config's dependency graph, and so the basket import stays AST-visible:

```python
CANONICAL_ENGINE_ABI         = "engine_abi.v1_5_9"   # basket compute ABI (today)
CANONICAL_SINGLE_ASSET_ENGINE = "v1_5_8"             # single-asset engine (today)
CANONICAL_ENGINE_VERSION_DOTTED      = "1.5.9"        # derived by parsing the ABI const
CANONICAL_SINGLE_ASSET_VERSION_DOTTED = "1.5.8"
def normalize_engine_token(s) -> ...   # one source for dotted/underscored
```

These are the **only two switches** for the whole system. (Two constants — not one — is correct:
it lets a *staged* convergence run baskets on v1_5_10 while single-asset is still v1_5_8, with the
gate proving neither silently diverges. §4 adds an end-state lock that collapses them.)

### 2b. Basket path — keep the static import, source the label + assert (fail-closed)
`basket_runner.py:38` stays **exactly** `from engine_abi.v1_5_9 import (…)` (AST guard + byte-test
depend on this literal). Change only `:60`:
```python
from config.engine_authority import CANONICAL_ENGINE_ABI as ENGINE_ABI
# immediately after the :38 import block:
assert ENGINE_ABI == "engine_abi.v1_5_9", f"basket import target diverged from authority: {ENGINE_ABI}"
```
The import literal and the re-exported `ENGINE_ABI` can now never silently disagree — a one-sided
edit fails closed at module load (first basket run aborts). `ENGINE_VERSION` is still re-exported
from the imported module (stamp==compute, the `4f5ac8fb` property, untouched).
`run_pipeline._basket_compute_engine_version/_basket_engine_abi` (`:869-901`) and their `from
tools.basket_runner import …` are **unchanged** → the existing AST guard stays green.

### 2c. Single-asset path — registry stays the selector, gains an authority cross-check
`get_engine_version()` (dotted) and `get_active_engine()` (underscored) keep their runtime
contracts and `ENGINE_VERSION_OVERRIDE` semantics (override stays single-asset-only → baskets stay
override-inert). They compute their **non-override** value via the authority normalizer, so the two
conventions draw from one source. No `run_stage1`/`stage_symbol_execution` runtime-logic change.

### 2d. The convergence gate (the load-bearing mechanism)
Extend `tests/test_engine_identity_convergence.py` (already in `tools/hooks/pre-commit:137` +
`system_introspection._GATE_TEST_SUITE:676` — **no roster edit needed**) with
`test_selection_surfaces_converge_on_authority()` asserting:
- (a) `basket_runner.ENGINE_ABI == CANONICAL_ENGINE_ABI`;
- (b) the AST-extracted `basket_runner:38` import target == `CANONICAL_ENGINE_ABI`;
- (c) under no override, `get_active_engine()`/`get_engine_version()` both normalize to
  `CANONICAL_SINGLE_ASSET_ENGINE`;
- (d) `engine_registry.json active_engine == CANONICAL_SINGLE_ASSET_ENGINE`;
- **(e) [graft] version cross-check** — `importlib.import_module(CANONICAL_ENGINE_ABI).ENGINE_VERSION
  == basket_runner.ENGINE_VERSION == CANONICAL_ENGINE_VERSION_DOTTED`, and the single-asset constant
  resolves to its module's own `ENGINE_VERSION`. *This is what makes the authority compute-bound, not
  just a literal.*
- **(f) [graft] symbol superset** — `engine_abi.<CANONICAL_ENGINE_ABI>.__all__` ⊇ the 8 basket symbols;
- **(g) [graft] dryrun waiver** — `strategy_dryrun_validator`'s ContextView source is the authority's
  declared dryrun engine, or an explicit `# WAIVER:` constant is present.

Any future edit that points one surface at a different ABI than the authority **fails the commit**
(and SESSION STATUS → BROKEN). Divergence becomes mechanically impossible.

### 2e. Registry awareness
Add a `v1_5_9` entry to `engines{}` (`canonical:false`, `status:FROZEN`, note: *"Basket compute ABI
+ TS_Execution pin; NOT single-asset selectable; byte-identical compute to v1.5.8"*) so the registry
finally lists every engine. **ADD, not a flag-flip** — `active_engine` stays `v1_5_8`.

---

## 3. Compute-binding proof & doctrine compatibility

`stamp == compute` is preserved **by not changing where compute or stamp come from**, only by adding
fail-closed cross-checks that they *name the same thing*. Three layers:

1. **Runtime** — basket: the static `:38` import + the `:60` module-load assertion (literal ==
   authority); single-asset: `run_stage1:410-420` still binds the stamp to the loaded module's own
   `ENGINE_VERSION` and aborts on folder/module skew. No silent fallback (Invariant #1).
2. **Gate** — `test_selection_surfaces_converge_on_authority` asserts every surface == the one
   authority constant **and** that the constant resolves to the real module's `ENGINE_VERSION`
   (graft e). Commit-blocking + SESSION STATUS.
3. **AST/ABI** — the existing fail-closed `_basket_*` AST guard is **not** widened-and-broken (no new
   dispatch surface, no import moved); `abi_audit` consumed-by is **unchanged** (basket_runner still
   directly imports `engine_abi.v1_5_9`).

**Doctrine `[[engine_identity_is_compute_not_stamp]]`: preserved literally.** The basket identity is
still the static imported module; the authority is a *name* registry that imports no engine, so it
*cannot* become "a stamp that mislabels." Override-inertness for baskets is verbatim. This is the
key advantage over A/B, which both relocate/dynamize the import the doctrine deliberately fixed.

---

## 4. From "one authority" to "one engine" — staged convergence

The authority lands **inert** (Phase A). Convergence then becomes a sequence of **separately-gated**
steps, each a *one-file name flip in the authority* plus the per-path *compute* work:

- **Phase A — land the authority (INERT).** §5. No engine activation. Both paths byte-identical to
  today; the gate proves single-source.
- **Phase B — basket convergence.** Flip `CANONICAL_ENGINE_ABI → engine_abi.v1_5_10` **+** the
  `basket_runner:38` re-point **+ the inline charge surgery** (entry + rule-exit) per
  `V1_5_10_CANONICAL_FLIP_DESIGN.md §3` (the fast path bypasses `evaluate_bar`, so selecting v1_5_10
  is **not** sufficient to charge — the surgery is mandatory, else stamp says charged while compute
  half-charges). Gated on that doc's prerequisites (P1 self-ID on main, parity tests).
- **Phase C — single-asset convergence.** Flip `CANONICAL_SINGLE_ASSET_ENGINE → v1_5_10` **+**
  `active_engine → v1_5_10`. Single-asset charges **natively** via `evaluate_bar` (no surgery), but
  needs: (i) a **cost-regime column on `master_filter`** (mirroring Phase-1 self-ID — today
  `MASTER_FILTER_COLUMNS` has *no* engine identity at all, the mixed-regime hazard 289c9c76 closed
  for cointegration); (ii) fix `run_metadata.spread_model='none_applied'`
  (`run_stage1.py:998,1029`) → derive from compute (else it's a stamp≠compute lie under v1_5_10);
  (iii) supersession re-baseline of the **selected shortlist** (not all 353 is_current rows) — every
  charged re-run supersedes its uncharged twin and re-passes the deployment gates (charging lowers
  PF/expectancy). Requires `verify_engine_integrity` to pass (v1_5_10 vaulted + manifest hashes).
- **Phase D — retirement + end-state lock.** Set v1_5_8 `canonical:false` (documentary — see risk
  on "no allow-list teeth"); keep the v1_5_9 ABI surface alive (TS_Execution + abi_audit + 2 tests
  still consume it — **retire ≠ delete**). Add the **end-state gate assertion**: both authority
  constants resolve to the **same** `ENGINE_VERSION` → true single-engine, anti-ambiguity locked.

**Cross-repo boundary (hard) — see the *Scope* callout at the top of this doc.** TS_Execution stays
pinned **v1_5_9** (its own allow-list `_SUPPORTED_ABIS=('v1_5_3','v1_5_9')`,
`phase0_validation.py:30`, doesn't even permit v1_5_10 — fail-closed). The authority is
**Trade_Scan-internal** and must never drive the live ABI. After convergence there is **one**
authority *inside* Trade_Scan but **two** across the ecosystem (research v1.5.10 + live v1.5.9);
that divergence is **intended, fail-closed on the live side, and must be treated as designed — not
a bug.**

---

## 5. Phase A migration (land INERT) — ordered

```
0. STOP — implementation plan + human approval (Invariant #6). Land INERT (no active_* flip,
   no v1_5_10 re-point). Selection-surface consolidation ONLY.
1. Create config/engine_authority.py: the two constants (matching today: engine_abi.v1_5_9,
   v1_5_8) + derived dotted/underscored + normalize_engine_token(). Imports stdlib only.
2. basket_runner.py:60 → `from config.engine_authority import CANONICAL_ENGINE_ABI as ENGINE_ABI`
   + the post-:38 module-load assertion. Leave :38 literal as-is. Update the SSOT comment (:49-59).
3. engine_registry.json: ADD v1_5_9 entry (canonical:false, FROZEN, basket/TS_Execution-pinned,
   not single-asset-selectable). active_engine STAYS v1_5_8.
4. pipeline_utils.get_engine_version + engine_loader.get_active_engine: source the non-override
   value via the authority normalizer (keep dotted/underscored outputs + override semantics).
5. Extend test_engine_identity_convergence.py with test_selection_surfaces_converge_on_authority
   (assertions a–g, §2d) IN THE SAME COMMIT as steps 2–4 (else the moved literal trips the gate).
   Add the byte-equivalence anchor test (graft 3).
6. Run green INERT: the convergence gate, abi_audit --pre-commit (both ABIs, unchanged consumed-by),
   system_preflight. Confirm a basket run + a single-asset run produce byte-identical stamps/compute
   to pre-migration. Commit atomically.
```

**Blast radius:** 1 new file + 4 small edits (`basket_runner.py:60`, `engine_registry.json`,
`pipeline_utils.py`/`engine_loader.py` string-source, the test). **No** runtime-logic change to
`run_stage1`/`run_pipeline`/`stage_symbol_execution`; **no** dynamic-import surface; **no** abi_audit
consumed-by re-point; **no** corpus becomes mixed-regime (inert). All protected (Invariant #6).

---

## 6. Risks & guards (incl. grafted hardenings)

- **"Compute-binding" is gate-enforced, not a runtime dispatcher.** The basket `:38` literal and the
  `:60`/assertion must be edited together — by design (one coordinated flip). The graft-e version
  cross-check makes the authority constant *provably* the real module's version, not just a string.
- **No allow-list teeth for "non-selectable."** Nothing reads `engines{}.canonical`; `active_engine`
  selectability is enforced only by module existence. Setting v1_5_8 `canonical:false` is
  documentary. *Optional future hardening:* a `selectable-allowlist` gate asserting
  `active_engine == CANONICAL_SINGLE_ASSET_ENGINE`. (Already covered by gate assertion (d).)
- **CI enforcement is v1_5_9-skewed in *wiring*, though `abi_audit` already covers both ABIs**
  (verified 2026-06-17). `tools/abi_audit.py:53` is `_SUPPORTED_ABIS=('v1_5_9','v1_5_10')` and the CI
  audit step runs with no `--abi-version`, so it audits **both** by default. The real gaps are three
  specific wiring issues in `.github/workflows/abi_audit.yml`: (i) the `paths:` triggers list
  `engine_dev/.../v1_5_9/**` but **not** `v1_5_10/**` (a v1_5_10 engine-source edit won't trigger CI;
  the `engine_abi/**` + `engine_abi_*_manifest.yaml` globs are version-agnostic and *do* trigger);
  (ii) the identity-test step runs `test_engine_abi_v1_5_9.py` only — `test_engine_abi_v1_5_10.py`
  **exists but is never invoked**; (iii) the last_verified auto-commit stages only the v1_5_9
  manifest, so v1_5_10's `last_verified` is never committed. **Close all three before v1_5_10 becomes
  canonical** (gate item 2, §7.1), else the new canonical has weaker CI than the retired engine.
- **Vault liability (verified 2026-06-17):** `vault/engines/Universal_Research_Engine/` holds
  v1.2.0…v1_5_8 but **no `v1_5_9` and no `v1_5_10` dir**. v1_5_9 is the **live-pinned** ABI
  (TS_Execution) and v1_5_10 is the canonical successor, so both genuinely need snapshots — "mark it
  unvaulted" is not an option for an engine the live system depends on. (The governance ABI
  manifests carry no `vaulted` field; `engine_registry.json:5 vaulted:true` is scoped to active
  v1_5_8. The v1_5_9 *package* manifest `engine_dev/.../v1_5_9/engine_manifest.json` did claim
  `vaulted:true` while no vault dir existed — **made honest by the 2026-06-17 closure pass**, §7.1.1.)
  Disaster-recovery (`ENGINE_VAULT_CONTRACT`) would otherwise fail to find v1_5_9/v1_5_10. **Vault
  before formalizing v1_5_9 frozen/retired and before the Phase-C active_engine flip** (gate item 1,
  §7.1; v1_5_9 done, v1_5_10 deferred) — via the vault contract, not improvised.
- **`strategy_dryrun_validator.py:29`** v1_5_6 ContextView is outside the authority — graft (g)
  forces an explicit waiver-or-inclusion so it can't silently desync.
- **Single-asset mixed-regime** (Phase C) is the single-asset analogue of the basket hazard — do not
  flip `active_engine` to v1_5_10 before `master_filter` has the cost-regime column + the
  `spread_model` fix, or deployment rankings blend regimes.
- **Authority centralizes a chokepoint:** a bug in `engine_authority.py` (stdlib-only, tiny) or its
  unimportability aborts basket runs (fail-closed-correct, but a new coupling).

---

## 7. Operator decisions — RESOLVED 2026-06-17

The four open decisions were reviewed and decided by the operator (governance review, 2026-06-17).
Recorded here as the authoritative resolution; the design above is **approved as written**.
Resolution **approves the design** but does **not** authorize implementation: Phase A remains
STOP-level protected-infra (Invariant #6), authorizable only when the **§7.1 Phase A Authorization
Gate** (four items) is explicitly closed. Phases B/C/D require *separate* gates.

1. **Architecture — RESOLVED: Architecture C.** Static engine imports + a stdlib-only name
   authority + the fail-closed convergence gate. B (return-a-handle module) and A (dynamic
   resolver) rejected — both relocate/dynamize the import the doctrine deliberately fixed. This
   resolves the "compute-binding interpretation" question: C is compute-binding *by verification,
   not dispatch* — see the **Architectural invariant** at the top.
2. **Phase ordering — RESOLVED: A → B → C → D exactly as written, baskets-first.** Selection
   convergence (**this** doc) and charging convergence (`V1_5_10_CANONICAL_FLIP_DESIGN.md`, the
   compute layer) stay **separate, separately-gated change sets — never one commit.** Phase A
   (authority, INERT) lands and bakes before any charging phase.
3. **Single-asset re-baseline scope — RESOLVED: selected shortlist only.** Re-price **only the
   selected shortlist**, never all 353 is_current rows — re-pricing all is wasteful and risks
   reviving retired strategies, recreating the mixed-regime problem already eliminated elsewhere.
   Provenance is carried concretely by the Phase-C `master_filter` cost-regime column (C-i) +
   supersession of each uncharged twin by pair+span — not a free, untracked re-baseline.
4. **Pre-existing gaps + Phase A gate — RESOLVED: see §7.1.** The operator (2026-06-17) set these
   as the **Phase A authorization gate** — all must be explicitly closed before Phase A is
   authorized — and added a fourth item (a Phase A rollback procedure). Governing principle: no
   "canonical" engine may ship **weaker recovery or CI enforcement than the engine it retires.** The
   four items (vault · CI matrix · selectability gate · Phase A rollback) and their closure status
   are tracked in **§7.1**.

### 7.1 Phase A Authorization Gate (operator-set, 2026-06-17)

Phase A (land the authority INERT, §5) is authorizable **only when all four items below are
explicitly closed.** Phases B/C/D are **not** covered by this gate — each needs its own approval
(they alter compute semantics + research baselines).

> **Item 1 re-scope (operator, 2026-06-17):** Phase A must not be held hostage to a v1_5_10 snapshot
> that does not yet exist in frozen form. Item 1 is split — **Phase A prerequisite:** v1_5_9 vault
> (satisfied); **Phase C prerequisite:** v1_5_10 vault before canonicalization. Item 1 is therefore
> **satisfied for Phase A purposes.**

| # | Gate item | Closure criterion | Status (2026-06-17) |
|---|---|---|---|
| 1 | **Vault** | **Phase A:** v1_5_9 vaulted + hash-verified. **Phase C:** v1_5_10 vaulted before canonicalization. | **SATISFIED for Phase A** — v1_5_9 vaulted + byte-verified (2026-06-17). v1_5_10 re-scoped to a **Phase C prerequisite** (§7.1.1, §4 Phase C), not a Phase A blocker. |
| 2 | **CI matrix** | `abi_audit.yml` `paths:`, identity-test step, and last_verified commit all cover v1_5_10 | **CLOSED** — all 3 wiring fixes applied (closure pass 2026-06-17, §7.1.2). |
| 3 | **Selectability gate** | a commit-blocking assertion makes a non-canonical/absent `active_engine` fail closed | **CLOSED (specified)** — §7.1.3. |
| 4 | **Phase A rollback** | a documented, side-effect-free revert restoring byte-identical pre-Phase-A state | **CLOSED (specified)** — §7.1.4. |

Items 1 & 2 are **execution actions** (they mutate the engine vault + the CI workflow).
**Executed in the Infrastructure Closure Pass, 2026-06-17** (operator-authorized): item 2 fully;
item 1 for **v1_5_9 only** — v1_5_10 vaulting is deliberately deferred (§7.1.1). This pass is **not**
Phase A: the authority itself remains unauthorized (the gate is *closer to* — not yet — met).

#### 7.1.1 Vault remediation (item 1)
Snapshot v1_5_9 and v1_5_10 per `ENGINE_VAULT_CONTRACT` (use the `update-vault` workflow — do not
improvise the layout): materialize `vault/engines/Universal_Research_Engine/v1_5_9/` and
`.../v1_5_10/` from their `engine_dev/universal_research_engine/<ver>/` sources + manifests, then run
`verify_engine_integrity` and confirm the manifest hashes match. **Acceptance:** both dirs present
and hash-verified; DR can locate every retained/canonical engine.

**Status (2026-06-17):** **v1_5_9 DONE** — `vault/engines/Universal_Research_Engine/v1_5_9/` created
from the canonical `engine_dev/.../v1_5_9/` source (8 files; `__pycache__` excluded per §3/§5), every
file sha256 byte-identical to source; the package manifest's pre-existing `vaulted:true` is now
honest. **Item 1 is SATISFIED for Phase A purposes** (operator, 2026-06-17). **v1_5_10 vault =
Phase C prerequisite** (before canonicalization, per §4 Phase C; *not* a Phase A blocker): do **not**
vault v1_5_10 until (i) basket convergence (Phase B) is complete, (ii) v1_5_10 compute is frozen, and
(iii) Phase C is approaching — so the snapshot captures the engine actually intended for recovery,
not a still-mutating experimental build (vaulting now would risk a stale snapshot needing
re-vaulting).

#### 7.1.2 CI remediation (item 2) — `.github/workflows/abi_audit.yml`
(a) add `engine_dev/universal_research_engine/v1_5_10/**` to **both** the `push.paths` and
`pull_request.paths` lists; (b) add `tests/test_engine_abi_v1_5_10.py` to the "Run identity tests"
step; (c) generalize the last_verified commit step to also stage
`governance/engine_abi_v1_5_10_manifest.yaml` (or glob `governance/engine_abi_*_manifest.yaml`). The
audit step itself already covers both ABIs (default = all `_SUPPORTED_ABIS`), so no
audit-invocation change is needed. **Acceptance:** a v1_5_10 source/manifest/test change triggers CI
and runs its identity test, and v1_5_10's `last_verified` is committed on push to main.

**Status (2026-06-17): DONE** — all three applied to `.github/workflows/abi_audit.yml`: (a)
`engine_dev/universal_research_engine/v1_5_10/**` added to **both** `paths:` lists; (b)
`tests/test_engine_abi_v1_5_10.py` added to the "Run identity tests" step; (c) the last_verified
commit step now globs `governance/engine_abi_*_manifest.yaml` (covers the v1_5_10 manifest too).

#### 7.1.3 Selectability gate (item 3 — specification)
Today nothing reads `engine_registry.json engines{}.canonical` (verified — it is documentary), so
"non-selectable" has no teeth. Add a fail-closed assertion to
`tests/test_engine_identity_convergence.py` (the same commit-blocking + SESSION-STATUS suite the
convergence gate already lives in), promoting §6's optional hardening to **required**:
- `engine_registry.active_engine == CANONICAL_SINGLE_ASSET_ENGINE`;
- the `engines{}` entry for `active_engine` exists and has `canonical: true`;
- **exactly one** engine entry has `canonical: true` (no second canonical single-asset engine).

This is *verification, not a runtime dispatcher* (consistent with the Architectural invariant): a
commit that points `active_engine` at a non-canonical or absent engine fails the gate. No runtime
code reads the flag — the gate is the enforcement.

#### 7.1.4 Phase A rollback procedure (item 4)
Phase A lands as **one atomic commit** (§5 step 6) and is **INERT** — no engine activation, no
charging, no corpus/ledger/`master_filter` mutation — so rollback is clean and side-effect-free:
1. **Revert:** `git revert <phase-A-commit>` (single commit → single revert). This removes
   `config/engine_authority.py`, restores `basket_runner.py:60` to its literal `ENGINE_ABI`,
   restores the two single-asset selectors to their pre-authority string source, drops the added
   v1_5_9 `engines{}` entry, and removes `test_selection_surfaces_converge_on_authority` + the
   byte-equivalence anchor test. The `:38` static import never changed, so basket compute is
   identical either way.
2. **Verify byte-identity:** re-run a basket run + a single-asset run and confirm stamps + compute
   are byte-identical to the pre-Phase-A baseline captured in §5 step 6 (the same parity check that
   gated the landing, run in reverse); `abi_audit --pre-commit` (both ABIs) + the convergence gate
   (now without the new assertion) + `system_preflight` all green.
3. **No data unwind:** because Phase A is inert there are **no** charged runs, superseded rows, or
   ledger writes to reverse — rollback touches code only. (This is precisely why B/C/D need separate
   gates and their *own* rollback designs: they are not side-effect-free.)

**Rollback trigger:** any post-merge failure of the convergence gate, `abi_audit`, or a basket/
single-asset parity mismatch.

### 7.2 Phase A Authorization Assessment (2026-06-17)

*Assessment only — Phase A is **not** executed here. The go/no-go decision rests with the operator.*

**1. Current gate status**

| # | Item | Status |
|---|---|---|
| 1 | Vault (Phase A scope) | **SATISFIED** — v1_5_9 vaulted + byte-verified; v1_5_10 re-scoped to a Phase C prerequisite. |
| 2 | CI matrix | **CLOSED** — wiring applied + locally validated (gate suite 79✓, engine-ABI identity tests 48✓ incl. v1_5_10, abi_audit both OK, YAML valid). First GitHub Actions run on next triggering push. |
| 3 | Selectability gate | **SPECIFIED** (§7.1.3) — implemented *as part of* Phase A's atomic commit; not a pre-req. |
| 4 | Phase A rollback | **DOCUMENTED** (§7.1.4). |

All four are at or above the operator-set bar → **the gate is met for Phase A.**

**2. Remaining blockers to Phase A**

None gate-defined. Two implementation *must-includes* (inside the Phase A commit) + one minor residual:
- **Graft-(g) dryrun waiver (required):** `strategy_dryrun_validator.py:29` imports `ContextView` from
  v1_5_6 — outside the authority. Assertion (g) requires authority-inclusion or an explicit
  `# WAIVER:` constant. *Recommended: waiver* — it is a deliberately-pinned structural dry-run import
  (v1_5_6 is the FROZEN reference engine), not the run engine.
- **Atomic landing (required):** the convergence-test extension (assertions a–g + byte-equivalence
  anchor) lands in the **same commit** as the basket_runner:60 / selector edits (§5 step 5).
- **CI-in-GitHub (minor residual):** item 2's wiring is locally validated; its first real GitHub
  Actions execution is on the next triggering push — recommend pushing the closure-pass commit so CI
  exercises the v1_5_10 path before Phase A merges.

**Verified non-blocker (the design's highest-risk assumption):** changing `basket_runner.py:60` from
the `"engine_abi.v1_5_9"` literal to `from config.engine_authority import CANONICAL_ENGINE_ABI as
ENGINE_ABI` does **not** trip the AST guard — `test_basket_dispatch_ast_guard_fail_closed` scans only
`tools.run_pipeline._basket_*` functions (`_basket_dispatch_functions()` parses run_pipeline only),
never basket_runner:60. The one value assertion on `basket_runner.ENGINE_ABI`
(`test_basket_single_source_chain:48`) stays green because the authority constant still equals
`"engine_abi.v1_5_9"`. `abi_audit` consumed-by is unchanged (the :38 import is untouched; the
authority imports no engine).

**3. Exact implementation blast radius**

1 new file + 4 edits + 1 test extension; **one atomic commit; INERT** (byte-identical compute/stamps
before & after):
- **NEW** `config/engine_authority.py` — stdlib-only: `CANONICAL_ENGINE_ABI="engine_abi.v1_5_9"`,
  `CANONICAL_SINGLE_ASSET_ENGINE="v1_5_8"`, two derived dotted constants, `normalize_engine_token()`.
  Imports no engine.
- **EDIT** `tools/basket_runner.py:60` — `ENGINE_ABI` sourced from `CANONICAL_ENGINE_ABI` + a
  post-:38 module-load assertion. Line :38 import literal + `__all__` (:62-64) unchanged; refresh the
  SSOT comment (:49-59).
- **EDIT** `config/engine_registry.json` — ADD a `v1_5_9` entry to `engines{}` (`canonical:false`,
  `FROZEN`, basket/TS_Execution-pinned). `active_engine` STAYS `v1_5_8`.
- **EDIT** `config/engine_loader.py:8` (`get_active_engine`) + `tools/pipeline_utils.py:213`
  (`get_engine_version`) — non-override value sourced via the authority normalizer (underscored /
  dotted respectively); `ENGINE_VERSION_OVERRIDE` semantics unchanged. (pipeline_utils' legacy
  v1.5.6 fallback becomes dead — optional cleanup.)
- **EDIT** `tests/test_engine_identity_convergence.py` — add `test_selection_surfaces_converge_on_authority`
  (assertions a–g, incl. the §7.1.3 selectability checks + graft-g waiver) + the byte-equivalence
  anchor test.
- **Untouched:** `run_stage1` / `run_pipeline` / `stage_symbol_execution` runtime logic; the :38
  static import; `abi_audit` consumed-by; no dynamic-import surface; no corpus/ledger writes.

**4. Rollback procedure** (per §7.1.4)

Single `git revert <phase-A-commit>` (one atomic commit) — removes `engine_authority.py`, restores
basket_runner:60 / the two selectors, drops the v1_5_9 `engines{}` entry, removes the new tests. The
:38 import never moved, so basket compute is identical either way. Verify: a basket + a single-asset
run byte-identical to the §5-step-6 pre-Phase-A baseline (run in reverse); `abi_audit` + convergence
gate + `system_preflight` green. **No data unwind** — INERT, nothing charged/superseded/written.

**5. Recommended decision: GO (conditional)**

Design adversarially studied + approved; doctrine preserved literally (verification-not-dispatch, :38
untouched); INERT landing is byte-identical and reversible by one revert with no data unwind; blast
radius is 1 file + 4 small edits + 1 test; the single highest-risk assumption (AST-guard scope) is
verified a false alarm; all gate prerequisites met. **Conditions on execution:** (a) include the
graft-g dryrun waiver; (b) land atomically with the gate extension; (c) confirm §5-step-6
byte-identical parity; (d) push so CI exercises the v1_5_10 path at/before merge. Phases B/C/D remain
separately gated and are **not** part of this recommendation.

### 7.3 CI Infrastructure — `engine_abi audit` dormant defect (recorded + deferred 2026-06-17)

**Classification (operator-accepted):** pre-existing **dormant CI defect** · **NON-BLOCKING** for Phase B · **NON-BLOCKING** for promotion · **FUTURE hardening item**.

**Finding (root cause):** `.github/workflows/abi_audit.yml` fails-closed at its "Checkout TS_Execution (sibling)" step because `secrets.SIBLING_REPO_TOKEN` was never provisioned (the sibling checkout, `:60-62`, has no `GITHUB_TOKEN` fallback — unlike the Trade_Scan checkout at `:55`). All downstream steps — the v1_5_10 identity test and the audit itself — are then **skipped**.

**Evidence:**
- **Never succeeded — 0 / 5 runs green** since the workflow's creation (2026-05-13, `6210c70f`); the 5th run is PR #3. By contrast `regression` is **28 / 28** → CI infra is otherwise healthy; the defect is isolated to this workflow's sibling dependency.
- **Identical root cause since creation:** the two earliest runs (`6210c70f` 2026-05-13, `fa7f1f8d` 2026-05-14) and PR #3 all fail at the same "Checkout TS_Execution (sibling)" step. The workflow shipped with this dependency from commit one.
- **Local + runtime gates remain functional:** the pre-commit `abi_audit` (layer 1; resolves the real sibling via `path_authority`) and the runtime import assertion (layer 3) DO verify the cross-repo `consumed_by` and pass for **both** v1_5_9 and v1_5_10. The advertised triple-gate is, in practice, a functioning **double-gate** (pre-commit + runtime); only the redundant CI layer (layer 2) is dark.
- `SIBLING_REPO_TOKEN` is referenced **only** inside `abi_audit.yml` — undocumented elsewhere in the repo.

**Disposition: DEFERRED.** Does not affect compute correctness (verified locally). Remediation when convenient (operator/admin only): provision a read-scoped `SIBLING_REPO_TOKEN` for TS_Execution in repo Actions secrets — restores layer 2 without weakening fail-closed. **Do not** weaken the workflow's fail-closed sibling checkout. Re-open only if new evidence shows compute-correctness impact.

---

## 8. Evidence index

- Selectors: `config/engine_registry.json:2,6-27` (no v1_5_9); `tools/pipeline_utils.py:213-249`
  (dotted + override); `config/engine_loader.py:8-34` (underscored + override, sole consumer
  `stage_symbol_execution.py:226`).
- Single-asset import sites: `run_stage1.py:386,410-420` (verify+abort), `:468`, `stage_symbol_execution.py:230`.
- Basket: `basket_runner.py:38` (static import), `:49-64` SSOT (`4f5ac8fb`), `:60` ABI literal;
  `run_pipeline.py:869-901` stamp helpers (unchanged).
- Doctrine/enforcement: `tests/test_engine_identity_convergence.py` (single-source `:42-55`,
  override-inert `:58-65`, AST guard `:121-167` scoped to run_pipeline `_basket_*`, single-strategy
  `:175-206`); `tools/hooks/pre-commit:137`; `system_introspection._GATE_TEST_SUITE:676`;
  `tools/abi_audit.py:53,207-270`.
- Single-asset convergence: native charge `engine_dev/.../v1_5_10/execution_loop.py:363,531,564,618,705`;
  `master_filter` has no engine column (`stage3_compiler.py`); `run_metadata.spread_model='none_applied'`
  `run_stage1.py:998,1029`; 1257 rows / 353 is_current / 31 symbols.
- Retirement consumers: TS_Execution pins v1_5_9 in 8 sites (`portfolio.yaml:6`,
  `phase0_validation.py:30`, `strategy_loader.py:154`, …); `engine_abi_v1_5_9_manifest.yaml`
  consumed_by = TS_Execution + 2 tests; CI gates only v1_5_9.
- Latent: `strategy_dryrun_validator.py:29` (v1_5_6 ContextView). Vault gap:
  `vault/engines/Universal_Research_Engine/` (no v1_5_9/v1_5_10). Symbol superset:
  `engine_abi/v1_5_10/__init__.py:44-61` ⊇ basket's 8 symbols (verified).
```
