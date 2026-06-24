# Engine Dispatch Convergence (`CURRENT` / `LIVE_ABI`) — Design & Decision Doc

> **Status: DESIGN — NOT APPROVED FOR EXECUTION.** Read-only planning artifact (no code changed).
> Every change it describes touches protected dispatch infrastructure (`config/`, `tools/`,
> `engine_abi/`, `governance/`, `.github/`) and the **identity-doctrine enforcement layer** —
> STOP-level under Invariant #6. This doc does **not** authorize itself.
>
> **Provenance:** motivated by the v1.5.11 Patch A promotion (2026-06-24), whose ~13-surface
> *zero-trade-change* flip made the "identity plumbing tax" (Tax C) concrete. Companion + successor
> to [`UNIFIED_ENGINE_AUTHORITY_PLAN.md`](UNIFIED_ENGINE_AUTHORITY_PLAN.md) (which executed the
> *authority* layer, Phases A–D) and [`V1_5_10_CANONICAL_FLIP_DESIGN.md`](V1_5_10_CANONICAL_FLIP_DESIGN.md)
> (the *charge* layer). Related memory: `[[project_v1_5_11_patch_a_canonical]]`,
> `[[engine_identity_is_compute_not_stamp]]`.

---

## 0. Crux — read this first (the design is NOT what the slogan suggests)

The motivating pitch was: *"`run_stage1 → CURRENT`, never `v1_5_10 / v1_5_11 / …`; dispatch never
sees a version."* **That exact design was already authored, adversarially scored, and REJECTED.** It
is **Architecture A** (dynamic registry resolver) / **B** (handle-returning importer) in
`UNIFIED_ENGINE_AUTHORITY_PLAN.md §0`. The decisive rejection reason is load-bearing and still holds:

> A dynamic/aliased import **defeats the AST-static-provability** the identity doctrine depends on.
> `abi_audit`'s `consumed_by` check and the basket AST guard can only prove *which real engine is
> imported* if the import target is a **static, AST-visible version literal**. Hide the version behind
> a resolver and the proof goes dark — the exact "stamp can drift from compute" failure the whole
> arc exists to prevent.

So the honest finding: **the identity doctrine requires the engine version to exist as a static,
AST-resolvable literal *somewhere*.** `CURRENT` cannot make that literal *vanish* — it can only
**relocate it to one indirection-of-record** and make every other surface *derive* from it.

**What that buys (real, bounded):** the per-promotion **dispatch flip** collapses from ~9 hand-edited
surfaces to **~1 version-literal edit** + the (irreducible) freeze/vault mechanics. **What it does
NOT buy:** "no version anywhere." The version still lives in `CURRENT` — behind one door. Freeze +
vault + an archived per-version package still accrue per canonical. If the bounded win isn't worth
reworking the provability machinery (§7-Q1), the correct answer is *do nothing* — the tax is real but
finite, and the authority already gives a single logical switch.

This doc designs the doctrine-**compatible** version of the idea and is explicit about the ceiling.

---

## 1. What already exists (convergence is NOT greenfield)

`UNIFIED_ENGINE_AUTHORITY_PLAN.md` executed **Architecture C**: static engine imports + a stdlib-only
name authority + a fail-closed convergence gate. Today:

- `config/engine_authority.py` — the **single logical switch**: `CANONICAL_ENGINE_ABI` +
  `CANONICAL_SINGLE_ASSET_ENGINE` (now both `v1_5_11`). Imports no engine. "Compute-binding by
  **verification, not dispatch**."
- `tests/test_engine_identity_convergence.py` — fail-closed gate proving every selection surface
  names the authority **and** that the authority resolves to the imported module's own
  `ENGINE_VERSION`. (It caught my mid-edit partial flip during the v1.5.11 promotion.)
- Static imports preserved: basket `tools/basket_runner.py:40 from engine_abi.v1_5_11 import (…)`;
  single-asset `run_stage1.run_engine_logic` dynamically imports `engine_dev/.../v{ver}/main` from
  the `get_engine_version()` string and **fail-closes on folder-vs-module skew** (`:410-420`).

**Convergence's logical layer is done.** What remains is the *mechanical* per-promotion cost, below.

---

## 2. The real tax, decomposed (from the v1.5.11 promotion, firsthand)

A promotion that moves **zero trades** touched these. Grouped by reducibility under the doctrine:

**Tax C — per-promotion DISPATCH flip (~9 surfaces; the target of this doc):**
| Surface | Reducible? |
|---|---|
| `basket_runner.py:40` static import literal | relocate → `CURRENT` (one-hop static) |
| `basket_runner.py:70` load-time `ENGINE_ABI == "engine_abi.vN"` self-check literal | derive from `CURRENT` |
| `config/engine_authority.py` ×2 (`CANONICAL_ENGINE_ABI`, `CANONICAL_SINGLE_ASSET_ENGINE`) | derive from `CURRENT` |
| `config/engine_registry.json` `active_engine` + `engines{}` map | `active_engine` derives; map = freeze record |
| `test_engine_identity_convergence.py` version literals (`"1.5.11"`, EXPECT map) | derive from `CURRENT` |
| `execution_loop.py` `ENGINE_STATUS`/`ENGINE_FREEZE_DATE` | freeze mechanics (irreducible) |
| `engine_manifest.json` freeze + LF-normalized `file_hashes` + note | freeze mechanics (irreducible) |
| `vault/…/vN/` snapshot | DR snapshot (irreducible) |

**Tax A — per-promotion ABI CEREMONY (~5 surfaces):** new `engine_abi/vN/` package +
`governance/engine_abi_vN_manifest.yaml` + `tests/test_engine_abi_vN.py` + `_SUPPORTED_ABIS` entry +
`.github/workflows/abi_audit.yml` path/test wiring. *Live drift exhibit:* CI `abi_audit.yml:80`
runs `test_engine_abi_v1_5_9.py test_engine_abi_v1_5_10.py` — **`v1_5_11` is missing**; the engine I
just promoted has no CI ABI test. This is precisely the "easy to forget a per-version surface" tax.

**Tax B — per-FEATURE output threading** (engine→main→wrapper→`emit_result`→`_emit_enrich_metadata_files`).
**Orthogonal — convergence does NOT touch it.** Named here only so the experiment (Patch A.1) is graded
correctly: convergence success = Tax A/C shrink; any residual feature-add pain is Tax B (its own arc).

---

## 3. Target design — single indirection-of-record (`CURRENT`), doctrine-compatible

### 3a. `engine_abi/CURRENT/__init__.py` — the one indirection-of-record
A package whose body is a **single static re-export** of the canonical versioned ABI:
```python
# THE one place the canonical research engine version is named. Promotion edits THIS line only.
from engine_abi.v1_5_11 import *          # noqa: F401,F403  (static, AST-resolvable one-hop)
from engine_abi.v1_5_11 import __all__    # re-export the surface verbatim
```
The version literal still exists and is still a **static, AST-visible literal** — it just lives in
exactly one file. Everything else imports `from engine_abi.CURRENT import (…)`.

### 3b. Make the provability machinery follow the one hop (the load-bearing rework)
This is the part that earns the doctrine's trust and is the real engineering:
- **AST guard / `abi_audit consumed_by`:** today they assert a *direct* `from engine_abi.vN import`.
  Teach them to resolve `engine_abi.CURRENT` → its single re-export target (one static hop, parse
  `CURRENT/__init__.py`) and prove against *that*. Provability preserved, not abandoned.
- **Convergence gate (graft-e):** `import_module("engine_abi.CURRENT").ENGINE_VERSION` must still
  equal the resolved versioned module's `ENGINE_VERSION` (unchanged in spirit; now via the hop).

### 3c. Derive the dispatch surfaces from `CURRENT`
- `basket_runner.py:40` → `from engine_abi.CURRENT import (…)`; the `:70` self-check asserts against
  the resolved target, not a literal.
- `config/engine_authority.CANONICAL_ENGINE_ABI` → resolved from `CURRENT` (or `CURRENT` *is* the
  authority's single source).
- `test_engine_identity_convergence` version literals + `EXPECT` map → derived from `CURRENT`'s
  resolved `ENGINE_VERSION`, so a promotion never edits the gate.
- **Single-asset** (`get_engine_version()` → `engine_dev/.../v{ver}/`): point the registry
  `active_engine` resolution at `CURRENT`'s version (the folder-path dispatch stays static per the
  skew-guard; only the *source* of the version string converges). Open question §7-Q3.

### 3d. `LIVE_ABI` — name the existing research/live split (mostly documentation)
TS_Execution is intentionally pinned `v1_5_9` (`_SUPPORTED_ABIS=('v1_5_3','v1_5_9')`, fail-closed,
v1_5_10/11 not even permitted). Introduce `LIVE_ABI` as the *named* constant for that pin so the
research/live divergence is explicit and a future reader can't "helpfully complete" the flip by
bumping the live side. `CURRENT` ≠ `LIVE_ABI` **by design** — the Phase-D end-state already says so.
Low-risk: naming + a gate assertion that they are *allowed* to differ.

### 3e. Parameterize the Tax-A ceremony where safe
- `_SUPPORTED_ABIS` and the CI `abi_audit.yml` per-version test list → glob/derive (`test_engine_abi_*.py`
  already globs in `paths:`; extend to the *invocation*). Fixes the live `v1_5_11`-missing-from-CI gap.
- The per-version `tests/test_engine_abi_vN.py` could become one parameterized "current ABI" test +
  an archived-versions sweep. (Optional; assess separately.)

---

## 4. Fold in H6 (deferred here from Patch A — it IS an identity-resolution problem)

`stage2_compiler.get_runtime_engine_version()` is **permanently broken** (returns `UNKNOWN` always:
no `VALIDATED_ENGINE.manifest.json` exists + it builds a dotted `1.5.10` path that never matches the
underscored `v1_5_10` dir), so the "strict version validation" is dead and literal fail-closed would
raise on every Stage-2 compile. The correct fix is a **reliable runtime-identity source** — exactly
what `CURRENT`/the authority provides:
- Rewrite `get_runtime_engine_version()` to read the **active engine module's own `ENGINE_VERSION`**
  (`engine_abi.CURRENT.ENGINE_VERSION`, the doctrine source), not a nonexistent manifest file.
- Then make the Stage-2 check **fail-closed**: unresolved runtime identity → raise; `meta != runtime`
  → raise. Byte-identical for normal runs (meta `1.5.11` == module `1.5.11` → passes today and after);
  only a *genuine* mismatch newly raises. Locked by a test (absent/forged identity raises).

---

## 5. Migration — INERT-first, gated, byte-identical (mirrors the Phase-A discipline)

1. **STOP / approval** (Invariant #6). Lands INERT: `CURRENT` re-exports the *current* canonical
   (`v1_5_11`), so every resolved identity is byte-identical before/after.
2. Add `engine_abi/CURRENT/` (§3a) + the AST/abi_audit one-hop resolution (§3b) + `LIVE_ABI` (§3d).
3. Migrate the dispatch surfaces (§3c) to derive from `CURRENT` — **one atomic commit** with the gate
   extension (else a moved literal trips the gate, as it did mid-promotion).
4. Fold in H6 (§4) — separable, can be its own commit (it's `stage2_compiler.py` + one test).
5. Parameterize Tax-A/CI (§3e).
6. **Gate green INERT:** convergence gate + `abi_audit --pre-commit` (all ABIs, consumed-by now via
   the hop) + a basket run + a single-asset run byte-identical to pre-migration + `system_preflight`.
7. **The proof:** the *next* promotion (and Patch A.1's event log) runs the collapsed flow — flip
   `CURRENT` (1 line) + freeze/vault. If the dispatch flip is ~1 edit, convergence worked; if a
   feature-add still hurts, that residual is Tax B (diagnosis, not failure — §2).

**Rollback:** INERT + atomic → `git revert`; `CURRENT` removed, surfaces restored to direct version
literals, no data unwind. Same shape as the Phase-A rollback (`UNIFIED_…§7.1.4`).

---

## 6. Honest cost / benefit + non-goals

**Benefit:** per-promotion dispatch flip ~9 surfaces → **~1 `CURRENT` edit + freeze/vault**;
convergence-gate + authority + basket import stop being hand-edited per version; Tax-A CI/allowlist
parameterized (closes the live `v1_5_11`-missing-from-CI gap); **H6 fixed correctly** as a byproduct.

**NOT a benefit (the ceiling — state plainly):** the version literal does **not** vanish (it
relocates to `CURRENT/__init__.py`); freeze + vault + an archived `engine_abi/vN` package still accrue
per canonical (you *want* a frozen, DR-snapshotted, separately-testable record of each shipped
engine); Tax B is untouched.

**Non-goals (rejected, out of charter):** ❌ a dynamic dispatch resolver / handle-returner
(Architecture A/B — defeats AST-provability); ❌ removing the static import model; ❌ touching the
TS_Execution live ABI; ❌ deleting archived versioned engines (retire ≠ delete — reproduction +
TS_Execution + byte-equivalence anchors consume them).

---

## 7. Open decisions for the operator

- **Q1 (the gating call):** the win is *relocate + collapse to ~1 edit*, **not** *eliminate*, and it
  costs a rework of the AST-guard / `abi_audit` provability machinery (the safety-critical doctrine
  enforcement). Is that worth it now, vs. accepting the finite per-promotion tax (the authority is
  already one logical switch)? **Reasonable to defer** if promotions are infrequent.
- **Q2:** indirection-of-record = a new `engine_abi/CURRENT/` package (§3a), **or** keep
  `config/engine_authority.py`'s constant as the single source and only collapse the *derive-from-it*
  surfaces (no `CURRENT` package, smaller blast radius, no AST rework — but basket's `:40` literal
  still edits per flip)? Q2 trades blast-radius against how much of the flip collapses.
- **Q3:** single-asset dispatch is folder-path (`engine_dev/.../v{ver}/`), not an `engine_abi` import.
  Does it derive its version from `CURRENT` (one source) but keep the static folder dispatch + skew
  guard, or is that path left as-is (registry `active_engine` is already a single string)?
- **Q4:** do H6 (§4) **independently and now** (it's small, correct, and unblocks PSBRK P17's
  invalid-fill work), even if Q1 defers the larger convergence?

## 8. Risks

- **Blast radius is the enforcement layer.** §3b reworks the AST guard + `abi_audit` — the machinery
  that *proves* stamp==compute. A bug there weakens the doctrine silently. Mitigation: INERT landing
  (identity byte-identical), the existing convergence gate as the net, and a forged-`CURRENT`-target
  test that must fail closed.
- **One-hop indirection is still indirection.** It must be exactly one static, parseable hop — if
  `CURRENT` ever becomes conditional/computed, it regresses to the rejected Architecture A. Lock
  `CURRENT/__init__.py` to a single `from engine_abi.vN import *` shape via a gate.
- **Touches live single-asset dispatch** (every run resolves through it). Same class of risk as the
  v1.5.10 active_engine flip — gated, reversible, byte-identical.
- **Q1-deferral is a legitimate outcome.** If the rework's risk exceeds the bounded win, recording
  "tax accepted, authority is the single switch" is a valid decision, not a failure.

---

*Design doc — read-only. No code modified. Execution requires explicit operator approval per
Invariant #6; each migration step (and H6) is separately gated. The honest ceiling (§0/§6) is the
point: convergence collapses and relocates the identity tax; the doctrine forbids eliminating it.*
