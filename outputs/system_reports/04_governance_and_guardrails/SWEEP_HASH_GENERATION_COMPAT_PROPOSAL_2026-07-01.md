# Version-Aware Sweep-Hash Compatibility — Design Proposal (REPORT-ONLY)

> **Status:** DESIGN ONLY — nothing implemented. No registry entry edited (P04 deliberately left
> stale as the live acceptance fixture). Author session 2026-07-01. Requires Protected-Infrastructure
> approval (Invariant #6) before any code or `governance/namespace/sweep_registry.yaml` change.
>
> **Scope:** the entire pre-May "stale-hash era" of `sweep_registry.yaml`, not idea 22 and not P04.
> Idea 22 is the *evidence*, not the target.

---

## 1. Problem statement — an unstated version assumption

The sweep gate (`tools/sweep_registry_gate.py`) admits or rejects a directive by comparing a freshly
computed hash against the value stored in the registry:

```
incoming  = _hash_signature(directive)          # f_current(directive)
stored    = registry[idea][sweep][patch].hash   # written when the entry was created
admit  ⇔  _hashes_match(stored, incoming)
```

This encodes a silent assumption:

> **`stored == f_current(directive)`** — i.e. the hash function has not changed since the entry
> was written.

That assumption is **false for 72–82 % of the registry.** The stored hash was correct for the hash
function *of its era*. `_hash_signature` has since changed shape (details in §3), so for any entry
written before those changes, `f_current(directive) ≠ stored` **even when the directive is byte-faithful
to the original.** The gate then reports `PATCH_COLLISION` — "a different strategy is trying to claim
this slot" — when the truth is "the same strategy, hashed by a newer function."

The correct framing is **not** "fix the sweep gate." It is **version-aware governance compatibility**:
the registry holds hashes from multiple *generations* of the hash function, and the gate must reason
about generation before it can compare.

```
        Historical registry entry
                  │
                  ▼
        Recognize registry generation G
                  │
                  ▼
        Compute historical-equivalent hash  f_G(directive)
                  │
          ┌───────┴────────┐
          ▼                ▼
   f_G(directive)==stored   else
          │                 │
          ▼                 ▼
   EQUIVALENT → admit     genuine COLLISION
   (+ governed migrate     (reject)
    stored → f_current)
```

---

## 2. Evidence — idea 22, three hash generations in one sweep

Reconstructing the idea-22 flagship (`22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P04`) from its vault
`strategy.py` and running it through the gate surfaced **three distinct hash values for the same
logical sweep**, each from a different era of `_hash_signature`:

| Slot | Stored hash (registry) | `reserved_at_utc` | Reproduced by today's gate as… |
|---|---|---|---|
| S01 / P00–P04 | `10c26e362c7af710` | 2026-03-07 … 03-10 | **not reproducible** from directive (oldest generation) |
| S01 / P05 | `d0fd79582f7f6321` | 2026-03-31 (refreshed 04-15) | `normalize_signature` **without** `__sweep_tf__` |
| my faithful rebuild | `68ee0d2b8b3c4ccb` | — | `normalize_signature` **with** `__sweep_tf__` (current) |

**The decisive proof the reconstruction is faithful, not a mistake:** the current normalizer applied to
my rebuilt directive, *with the `__sweep_tf__` term removed*, produces **`d0fd79582f7f6321`** —
byte-identical to what the registry already stores for the sibling P05 slot. So my directive content is
provably correct; the ONLY thing that differs is which generation of the hash function is applied.
Excluding the version-metadata keys (`signal_version`, `signature_version`, `version`) in every
combination does **not** recover `10c26e362c7af710`, confirming the P00–P04 value predates an even
earlier normalizer shape — a genuinely older generation, not merely "before the tf term."

This is exactly the **version-drift frontier** SYSTEM_STATE flagged (2026-06-30) as the next obstacle
for resurrecting genuinely-old strategies.

---

## 3. Generation archaeology — where the hash function moved

Value-changing commits to the sweep-hash computation (`git log`, dates are author-date):

| Commit | Date | Change | Effect on hash **value** |
|---|---|---|---|
| `a3629a0c` | (early) | original `normalize_signature` | Gen-0 baseline |
| `13d12821` | — | introduce `signal_version` into identity | **changes value** (new key in signature) |
| `3367d658` | — | stop-contract normalization for `next_bar_open` | **may change value** |
| `2fb041f6` | 2026-05-06 | include `timeframe` (`__sweep_tf__`) in `_hash_signature` | **changes value** (adds a key) |
| `2d62b475` | 2026-05-08 | rename field `signature_hash` → `directive_hash` | **storage only — value unchanged** |
| `c68cf12e` | 2026-06-24 | attribute `REGISTRY_DRIFT` vs `COLLISION` + human-gated repair tool | orthogonal (name-misfiling; see §5) |

Two facts matter for the design:

1. **Marker generations ≠ value generations.** The field rename (`2d62b475`) is a *storage marker*
   that changes nothing about the hash value; the `__sweep_tf__` and `normalize_signature`-body commits
   *do* change the value. So the number of distinct **recipes** needed (§6) is small — bounded by the
   value-changing commits, roughly **3–4**, not one per commit.
2. **`reserved_at_utc` is a usable (soft) generation signal** — every one of the 606 entries carries
   it (0 missing). It disambiguates when the stored hash alone is insufficient.

---

## 4. Blast radius — this is an era, not an entry

Full scan of `sweep_registry.yaml` (606 entries carrying a `directive_name`, sweep-level + patch-level):

| Signal | Count | Share | Reading |
|---|---|---|---|
| Total entries | 606 | — | |
| Old field only (`signature_hash*`, pre-rename) | **496** | 82 % | stale-era candidates |
| New field only (`directive_hash*`) | 0 | 0 % | — |
| Dual-written (both fields) | 110 | 18 % | touched post-rename; likely current-gen |
| Reserved **pre-2026-05-06** (oldest, no-tf) | **437** | 72 % | hard core of the stale era |
| Reserved 2026-05-06 … 05-08 (tf-transition) | 13 | 2 % | |
| Reserved **post-2026-05-08** | 156 | 26 % | current-ish |
| **16-char short hash only** (no 64-char full) | **40** | 7 % | cannot prefix-verify a recomputed full hash — hard case (§8) |

Old-field ("stale-era") entries are spread across **60+ ideas** — top contributors: idea 91 (45),
idea 22 (36), idea 42 (30), idea 01 (25), idea 55 (24), idea 41 (22), idea 06 (19)… down a long tail
to 20 ideas with a single entry each. **Every genuine pre-May strategy resurrected from the vault walks
into this.** The reasoning I just did for P04 — recognize the hash is era-stale, prove the directive is
faithful, decide admit-vs-collide — will recur once per resurrected old sweep. That crosses the
"recurring friction → build the mechanism" threshold: the mechanism should remove the *reasoning*, and
fix the *class*, not the instance.

---

## 5. Why the existing `REGISTRY_DRIFT` does not cover this

Commit `c68cf12e` already added a drift-vs-collision distinction — but it solves an **orthogonal**
problem. `_slot_drift()` (sweep_registry_gate.py:425-440) flags an entry as `REGISTRY_DRIFT` only when
the directive_name's **intrinsic coordinates contradict the slot it occupies** — e.g. an
`..._S03_..._P02` directive mis-filed in the S02/P02 slot. It is about **filing location vs name.**

In the idea-22 case the name and slot are **correct** (`22_…_S01_…_P04` is filed under idea 22 / S01 /
P04). Only the *hash* is stale-era. So `_slot_drift` returns `drifted=False`, control falls through to
`_hashes_match`, the hashes differ, and the gate emits **`PATCH_COLLISION`** (line 621).

There are therefore **three** situations, of which only two are currently modelled:

| Situation | name↔slot | hash | Current verdict | Correct verdict |
|---|---|---|---|---|
| Genuine collision | consistent | differs, same generation | `PATCH_COLLISION` ✓ | COLLISION |
| Mis-filed entry | **contradicts** | any | `REGISTRY_DRIFT` ✓ | (name) DRIFT |
| **Stale-era hash** | consistent | differs, **older generation** | `PATCH_COLLISION` ✗ | **HASH_GENERATION_DRIFT** (new) |

The design adds the missing third verdict. It does **not** weaken the first: a same-generation hash
mismatch remains a hard collision.

---

## 6. Design — the compatibility layer

Three cooperating pieces. All are additive; none changes the happy path (current-gen entry, current
directive → unchanged behaviour).

### 6.1 Generation recognition

Given a registry payload, classify its hash generation `G` from signals already present, in priority
order:

1. **Explicit stamp** (new, forward-only): a `hash_generation: <N>` field written on every *new*
   registration from now on. Current entries lack it → fall through to inference.
2. **Field-name marker:** `directive_hash*` present ⇒ post-rename (Gen ≥ 3); `signature_hash*` only ⇒
   pre-rename.
3. **`reserved_at_utc` vs the §3 boundaries** (2026-05-06, and the normalize-body commit dates) to pick
   among pre-rename recipes.
4. **Fail-safe:** unresolved ⇒ treat as "unknown generation" and fall through to COLLISION (never admit
   on ambiguity — same conservative bias as `_intrinsic_coords` returning `None`).

### 6.2 Historical-equivalent hash — a small registry of pure "recipes"

The heart of the durable fix. Rather than resurrecting arbitrary old module code (which drags in
`directive_schema` dependency drift), capture each **value-generation** as a small, pinned, pure
function `f_G(directive) -> hash`, living in one new module (e.g. `governance/sweep_hash_recipes.py`):

```
RECIPES = {
    "gen1_pre_tf_pre_signalver": f_gen1,   # oldest normalize, no tf, no signal_version
    "gen2_pre_tf":               f_gen2,   # + signal_version, still no tf
    "gen3_with_tf":              f_gen3,   # + __sweep_tf__  (== current f_current)
}
```

Each recipe is **anchored by a golden test**: it must reproduce a set of *known* stored hashes from real
registry entries of that generation (e.g. `f_gen2("…P05 directive") == d0fd79582f7f6321`; the current
`f_gen3` == `_hash_signature`). Recipes are frozen — a recipe is added only when a new value-generation
is introduced, and its golden anchors lock it forever. This is what makes the layer *durable* rather
than a moving target: the current hash function is free to evolve; each evolution just appends a recipe
and its anchors.

Verification for an incoming rerun of an existing slot:

```
for G in candidate_generations(payload):     # from §6.1, most-likely first
    if _hashes_match(stored, RECIPES[G](directive)):
        return EQUIVALENT(G)                  # same logic, older hash → admit
return COLLISION                              # no generation reproduces stored → genuinely different
```

This **verifies** equivalence (recomputes the stored value from the candidate directive under the old
recipe) rather than trusting timestamps or field names — the strong form of the user's
"compute historical-equivalent hash" branch.

### 6.3 Migrate-on-read (governed, once, lazy)

When 6.2 returns `EQUIVALENT(G)`, the entry is provably the same strategy under an old recipe. At that
point, upgrade the stored hash **once**, under governance:

- Rewrite `stored → f_current(directive)`, set `hash_generation: current`, and record provenance
  (`migrated_from_hash`, `migrated_from_generation`, `migrated_at`, `migrated_reason: HASH_GEN_MIGRATION`,
  and the run/session that triggered it).
- Direct payload edit (per `reference/sweep_hash.md`: **never** `new_pass.py --rehash` for an existing
  patch — it appends a duplicate key). Append-only spirit preserved: the old value is retained in
  `migrated_from_hash`, not destroyed.

Lazy migration means the 437-entry stale core is upgraded **as strategies are actually resurrected** —
no big-bang rewrite of entries nobody is touching. A **governed batch mode** (§7, opt-in) exists for
operators who prefer to migrate a whole idea or the whole era in one audited pass.

---

## 7. Two delivery modes (operator choice)

| Mode | What | When to prefer |
|---|---|---|
| **A — Lazy compat (recommended)** | §6 layer active in the gate; each old sweep migrates on first faithful rerun. Zero-touch for un-resurrected entries. | Default. Matches "build the mechanism, let it remove the reasoning as work arrives." |
| **B — Governed batch migration** | A one-shot, human-approved tool walks all stale-era entries that have a recoverable directive (vault `strategy.py` / reconstruction), verifies via §6.2 recipes, and migrates. Reports the residue it could **not** verify. | When an operator wants the registry uniformly current, or to quantify the unverifiable residue up front. |

Both use the **same** recipe + verification core; B is A run eagerly in a batch with a report. Neither
blind-rewrites: an entry migrates only when a recipe reproduces its stored hash from a real directive.

---

## 8. Hard cases the design must state honestly

1. **40 entries with 16-char-only hashes.** `_hashes_match` already prefix-matches a 16-char stored
   value against a 64-char recompute, so verification still works; but the migrated full hash cannot be
   *audited* against the original beyond 16 hex chars. Acceptable (16 hex = 64 bits, collision-negligible
   at this scale) but must be logged as reduced-provenance.
2. **Lost directives.** Most stale entries have **no** recoverable source (idea 22's had to be rebuilt
   from `strategy.py`). Such an entry can be migrated only when someone reconstructs its directive to
   rerun it — which is exactly Mode A's trigger. Entries never resurrected simply stay stale forever,
   harmlessly (they only ever block *their own* rerun, which never comes).
3. **Unreproducible generations.** If a stored value (e.g. `10c26e362c7af710`) is not reproduced by *any*
   recipe from the faithful directive, the layer must **refuse to admit** and surface
   `HASH_GENERATION_UNRESOLVED` — a human decision, never a silent pass. This is the failure mode that
   protects against smuggling a genuinely-changed strategy in under "it's just old." (Idea-22 P04 is
   currently in exactly this state until a `gen1` recipe is authored and anchored — see §10.)
4. **Recipe authorship cost.** Each pre-current recipe must be reconstructed from git history and locked
   with golden anchors. `gen3` is free (it is today's function). `gen2` is anchored by P05
   (`d0fd79582f7f6321`) already in hand. `gen1` requires reproducing the pre-`signal_version`/pre-tf
   normalizer — the one genuine archaeology task.

---

## 9. Enforcement mechanism (so it cannot decay)

Per [[feedback_enforceable_mechanisms_only]] — a proposal without an enforcement mechanism is a
decaying doc. This design is enforced by:

- **Golden-anchor tests** (`tests/test_sweep_hash_recipes.py`): every recipe must reproduce its pinned
  anchor hashes; CI fails if a recipe drifts. This is what freezes each generation.
- **A gate assertion**: `f_current` must equal `RECIPES["gen_current"]` (the current recipe is not a
  copy that can skew from the live function) — a test that binds the compat layer to the real gate.
- **Forward stamp**: new registrations write `hash_generation`, so the inference burden shrinks over
  time and future drift is self-labelling.
- **Migration provenance**: every migrate-on-read writes `migrated_from_*` fields; a periodic check
  (session-close / `audit_intent_index` sibling) counts un-migrated stale-era entries so the residue is
  visible, never silently "done."

---

## 10. Idea-22 as the built-in acceptance test

P04 is deliberately left stale (`10c26e362c7af710`). The design is "done" when:

1. A `gen1` recipe reproduces `10c26e362c7af710` from the reconstructed P04 directive (anchors the
   oldest generation), **or** the layer cleanly emits `HASH_GENERATION_UNRESOLVED` for it if gen1 proves
   unreconstructable — either is a correct, non-silent outcome.
2. Re-running the staged `…_P04__E001` rerun then admits via `HASH_GENERATION_DRIFT → EQUIVALENT(gen1)`,
   migrates P04 to `68ee0d2b8b3c4ccb` with provenance, and proceeds to Stage 1 — **without** a manual
   registry edit.

The already-staged rerun (`backtest_directives/active_backup/…_P04__E001.txt`, reconstruction source in
`backtest_directives/archive/…P04.txt`) is the live fixture; no synthetic test data needed.

---

## 11. Non-goals — what this is explicitly NOT

- **Not** a P04 registry edit (the instance fix was declined in favour of the class fix).
- **Not** a weakening of collision detection: same-generation hash mismatches stay `PATCH_COLLISION`.
- **Not** an auto-rewrite on *any* mismatch: migration requires a recipe to *reproduce the stored value*
  from a real directive. No reproduction ⇒ no admit.
- **Not** a merge with name-misfiling `REGISTRY_DRIFT` (`c68cf12e`): distinct verdict, distinct cause;
  the two compose but do not overlap.
- **Not** implemented. This document is the design; build is a separate, approval-gated phase.

---

## 12. Open questions for approval

1. **Recipe count** — is reconstructing `gen1` worth the archaeology, or is
   `HASH_GENERATION_UNRESOLVED → human migrate` acceptable for the oldest ~437 entries (i.e. ship gen2+
   verified, treat gen1 as human-gated)? Cheaper, slightly less automatic.
2. **Mode A vs A+B** — ship lazy-only first, add the batch tool later, or both together?
3. **Home** — extend `sweep_registry_gate.py` in place, or a new `governance/sweep_hash_compat.py` the
   gate calls (keeps the gate's happy path tight; matches the Diagnostic-Contract "attach not replace"
   principle [[feedback_diagnostics_attach_not_replace]])?
4. **Relationship to Diagnostic Contract Phase 2** — `HASH_GENERATION_DRIFT` / `…_UNRESOLVED` are
   textbook diagnostic-catalog entries (what + where + remedy). Fold this into that framework's payload
   rather than emitting a bare message?

---

## Appendix — reproduction commands (read-only, used to build this report)

```python
# hash of a directive under the current gate
from tools.sweep_registry_gate import _hash_signature
_hash_signature(Path("…/…_P04__E001.txt"))          # -> 68ee0d2b8b3c4ccb (current gen)

# faithful-reconstruction proof: current normalizer minus __sweep_tf__ == stored P05 hash
from tools.sweep_registry_gate import parse_directive, normalize_signature
sig = normalize_signature(parse_directive(p04_directive)); sig.pop("__sweep_tf__", None)
sha256(json.dumps(sig, sort_keys=True))[:16]          # -> d0fd79582f7f6321 (== registry P05)
```

Blast-radius scan: bucket `sweep_registry.yaml` entries by `signature_hash` vs `directive_hash` field,
by `reserved_at_utc` vs {2026-05-06, 2026-05-08}, and by 16- vs 64-char width (numbers in §4).
