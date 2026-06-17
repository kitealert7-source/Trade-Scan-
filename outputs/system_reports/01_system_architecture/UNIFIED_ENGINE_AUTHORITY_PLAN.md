# Unified Engine Authority — Design & Implementation Plan

> **Goal:** establish a **single, compute-binding engine authority shared across all execution
> paths**, so "which engine runs" has exactly one answer that can never silently diverge or
> mislabel — across single-asset *and* basket backtests.
>
> **Status: DESIGN — protected-infra (Invariant #6), STOP-level.** Every change here touches
> `config/`, `tools/`, `engine_dev/`, `governance/` — implementation plan + explicit human approval
> before any edit. **Lands INERT** (no engine activation, no charging) unless separately approved.
>
> **Authored** 2026-06-17 from a multi-agent design study (4 investigators mapping the selection
> surface + a 3-architecture judge panel). Companion to
> [`V1_5_10_CANONICAL_FLIP_DESIGN.md`](V1_5_10_CANONICAL_FLIP_DESIGN.md): **that** doc is the
> *compute/charge* layer (how the basket engine actually charges spread); **this** doc is the
> *selection* layer (how every path names the one canonical engine). They compose.
> Related memory: `[[engine_identity_is_compute_not_stamp]]`, `[[project-v1_5_10-canonical-readiness]]`.

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

**Cross-repo boundary (hard):** TS_Execution stays pinned **v1_5_9** (its own allow-list
`phase0_validation _SUPPORTED_ABIS=('v1_5_3','v1_5_9')` doesn't even permit v1_5_10). The authority
is **Trade_Scan-internal** and must never drive the live ABI. Research(v1.5.10)/live(v1.5.9)
divergence is intended and must be documented.

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
- **CI gates only v1_5_9** (`.github/workflows/abi_audit.yml`), not v1_5_10 — the local pre-commit
  hook covers both (`_SUPPORTED_ABIS:53`), but **extend the CI matrix to v1_5_10 before** it becomes
  canonical, else the new canonical has weaker enforcement than the retired one.
- **v1_5_9 vault liability:** the manifest claims `vaulted:true` but **no `vault/.../v1_5_9` dir
  exists** (and v1_5_10 is unvaulted too). Disaster-recovery (`ENGINE_VAULT_CONTRACT §8`) would fail
  to find it. Correct the claim or create the snapshot before formalizing v1_5_9's frozen/retired
  status — and vault v1_5_10 before the active_engine flip (Phase C).
- **`strategy_dryrun_validator.py:29`** v1_5_6 ContextView is outside the authority — graft (g)
  forces an explicit waiver-or-inclusion so it can't silently desync.
- **Single-asset mixed-regime** (Phase C) is the single-asset analogue of the basket hazard — do not
  flip `active_engine` to v1_5_10 before `master_filter` has the cost-regime column + the
  `spread_model` fix, or deployment rankings blend regimes.
- **Authority centralizes a chokepoint:** a bug in `engine_authority.py` (stdlib-only, tiny) or its
  unimportability aborts basket runs (fail-closed-correct, but a new coupling).

---

## 7. Open decisions for the operator

1. **"Compute-binding" interpretation:** accept **C** (static import + gate-bound name authority —
   recommended, doctrine-faithful), or prefer **B** (a real module that *returns* the engine, at the
   cost of an `abi_audit` re-point + AST-guard extension)? C is my strong recommendation.
2. **Convergence depth & sequence:** land the authority inert (Phase A) now; then basket (Phase B,
   gated on the flip doc) then single-asset (Phase C) — confirm baskets-first.
3. **Single-asset re-baseline scope:** which shortlist of the 353 is_current master_filter rows gets
   re-priced charged (re-pricing all is wasteful and risks reviving retired strategies)?
4. **Pre-existing gaps to fix now or waive:** v1_5_9/v1_5_10 vault gap; CI v1_5_10 matrix; the
   no-allow-list-teeth for selectability.

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
