# v1.5.10 Canonical Flip — Implementation Design (Phase 2)

> **Status: DESIGN — NOT APPROVED FOR EXECUTION.** This document specifies *how* to make
> `engine_abi.v1_5_10` (direction-aware spread charging) the canonical basket compute. Every
> code change it describes touches **protected infrastructure** (`tools/`, `engines/`,
> `engine_dev/`, `governance/`) and is a **STOP-level gate** under AGENT.md Invariant #6 —
> implementation plan + explicit human approval before any edit. This doc *is* that plan; it
> does not authorize itself.
>
> **Authored:** 2026-06-17, from a multi-agent investigation (8 code-grounded facets) + a
> 5-lens adversarial review (14 blocker / 15 major / 8 minor objections). Phase 1 (R9 self-ID)
> is DONE and committed (`289c9c76`, branch `feat/r9-spread-self-id`). Related memory:
> `[[project-v1_5_10-canonical-readiness]]`, `[[engine_identity_is_compute_not_stamp]]`,
> `[[data-provenance-hardening]]`, `[[reference_octafx_uniform_ask_spread_uncharged]]`.

---

## 0. The cardinal finding — the flip is NOT a two-line re-point

The mechanical re-point is two lines (`basket_runner.py:38` import + `:60` `ENGINE_ABI`), and the
entire stamp chain follows automatically through the SSOT block added by `4f5ac8fb`
(`_basket_compute_engine_version()`/`_basket_engine_abi()` → cointegration row, manifest,
STRATEGY_CARD, `execution_cost_model`, live heartbeat — all verified to derive from those two
lines, no second hardcode anywhere).

**But the production-default fast path for the 5 kept corpus arms does not route through the
engine, so the re-point alone STAMPS them `spread_charged` while COMPUTING them uncharged.**
This is the exact stamp≠compute divergence the entire R9 arc exists to prevent, and it would
*pass the Phase-1 certification filter* (which checks the stamp + data presence, not whether the
engine actually charged). Five independent adversarial lenses converged on this as the #1 risk.

The PineZRev fast path (`basket_runner._run_fast_path`, the production default —
`ContinuousHoldStrategy._basket_fast_path=True`) skips `evaluate_bar` entirely
(`basket_runner.py:489`) and has **four distinct fill sites that the re-point charges
inconsistently**:

| Fill site | Where | On re-point alone | Required |
|---|---|---|---|
| **Entry** (fast path) | `basket_runner.py:472-477` — `entry_price = entry_open` (raw) | **uncharged** | charge via `exec_fill` |
| **Rule cycle exit** (EQUILIBRIUM / TIMESTOP / break — the *dominant* exit) | `pine_ratio_zrev_v1.py:825` `exit_price=bar_closes[sym]` raw; PnL from `cointegration_meanrev_v1_2.py:106-126` raw `current_price` | **uncharged** | charge direction-aware in `_liquidate` |
| **DATA_END exit** (`finalize_force_close`, only for legs the rule never closed) | `basket_runner.py:509` → v1_5_10 `_exec_fill` | **auto-charges** | (already correct) |
| **Single-strategy path** | `config/engine_registry.json` `active_engine` (currently `v1_5_8`) | unchanged | **out of scope — keep decoupled** |

> **Facet contradiction, resolved.** The `r10_fastpath` facet asserted "the exits are already
> engine/rule-sided and would be charged correctly." This is **FALSE** and the `pine_exit`,
> `half_charged`, `test_gap`, and `merge_regression` lenses all refuted it on disk: the rule's
> `_liquidate` exit records a **raw** close and the PnL helper has **no** spread term. **Authoritative
> scope:** the entry charge AND the rule-side `_liquidate` exit charge must both land, atomically,
> in the same commit as the import re-point. A re-point shipped alone is a defect, not a milestone.

> **Second facet correction.** The `pine_exit` facet pointed at `_liquidate_at_prices` /
> `exit_fill_timing` / `next_open` machinery. The `half_charged` lens verified that machinery
> **does not exist on main or `feat/r9-spread-self-id`** — it lives only on the stale
> `feat/cointegration-onboarding` fork. **Scope the rule-exit charge to the bar_close `_liquidate`
> at `pine_ratio_zrev_v1.py:818-836` only.** Do not author against the branch-only path.

---

## 1. Decision frame — what "the flip" means

"Flip `active_engine` to v1_5_10" is ambiguous. There are **two independent compute paths**:

- **Baskets** (cointegration research — the subject of this arc) compute via
  `basket_runner.py`'s hardcoded `from engine_abi.v1_5_9 import` (line 38). They **never read**
  `active_engine`. Flipping baskets = the `basket_runner` edit + the charge wiring.
- **Single-strategy** (per-symbol) runs read `active_engine` via `get_engine_version()`. Flipping
  that charges per-symbol fills too — a *separate* behavioral change.

**Recommendation: decouple.** This flip is **basket-compute only**. Leave
`config/engine_registry.json active_engine` at `v1_5_8` (the registry's own note at line 25
self-defers it to "basket parity (Phase 2) + RESEARCH embed (Phase 3)"). A single-strategy flip
is a future, separately-gated decision. The basket path does not read the registry, so this is
clean (verified).

---

## 2. Prerequisites — gates BEFORE any flip code

These are ordered. Each is a hard gate; do not start the flip commit until all are satisfied.

### P0 — Human approval (Invariant #6, STOP)
`basket_runner.py`, `pine_ratio_zrev_v1.py`, `cointegration_meanrev_v1_2.py`,
`basket_pipeline.py`, `run_pipeline.py`, `engines/execution_fill.py`, `governance/recycle_rules/`,
`governance/engine_abi_v1_5_10_manifest.yaml`, `config/engine_registry.json` are all protected.
This document is the implementation plan; execution needs an explicit go.

### P1 — Phase-1 self-ID must be on the integration branch
**Verified: `289c9c76` is NOT an ancestor of `main`** (`git merge-base --is-ancestor 289c9c76
main` = FALSE; the `spread_coverage_pct` / `execution_cost_model` columns and the
`run_pipeline.py` write block exist *only* on `feat/r9-spread-self-id`). If the flip lands on bare
`main`, every charged row writes a NULL cost-model and the flip is uncertifiable — silently
nullifying Phase 1's only deliverable.

**Action:** fast-forward `feat/r9-spread-self-id` → `main` (1 commit, 0 conflicts) FIRST, then branch
the flip off the updated `main`. Add a hard precondition to the flip commit:
`git merge-base --is-ancestor 289c9c76 HEAD` must return 0 before any `basket_runner` edit.

### P2 — Cherry-pick the LM/HF rules (independent; can precede the flip)
LM20/HF55 are 2 of the 5 kept arms but their rules (`pine_ratio_zrev_v1_zcross_lm` / `_hf`) live
only on `feat/cointegration-onboarding`. **`git cherry-pick 28a80cc8 0082b0bb` (HF then LM).
NEVER merge/squash/whole-file-checkout the fork** — it predates `32bfc85d` and a merge **deletes
`comparison_schema.py` + `comparison_writer.py`** (verified `deleted file mode` in
`git diff main..onboarding`). The per-commit cherry-pick was empirically verified safe (neither
commit touches those paths; `pine_ratio_zrev_v1.py` 3-way merges cleanly and **retains main's
BB-adaptive-width feature** — 12 refs preserved). See §6 for the full conflict-resolution recipe,
including the **`max_bars_in_trade=` / `exit_fill_timing=` TypeError trap**.

### P3 — The DATA long-pole (the REAL Phase-3 gate)
**The "XAU spread gap" framing was wrong.** On-disk measurement (completeness lens) found a
**systemic 2024 FX spread hole: ~34% nonzero-spread coverage across *every* FX pair checked**
(EURUSD/USDJPY/GBPUSD/AUDUSD/USDCHF/USDCAD), vs ~100% for 2016-2023 and 2025-2026. Cross-referenced
to the live ledger: **~565 of 2377 `is_current=1` rows (~24%) fall in or overlap 2024 → cannot
reach `spread_coverage_pct >= 99` no matter how perfectly the charge is wired.**

A flip on spread=0 data charges **$0** and is byte-identical to v1.5.8 (engine manifest invariant:
spread=0 → byte-equivalent) — **cosmetically "done," actually inert.** This is the binding
constraint, not the code.

**Decision required (operator):** for the selected re-run universe's windows, either
**(a)** re-ingest/backfill the 2024 spread column via DATA_INGRESS CLEAN→RESEARCH regen, or
**(b)** exclude 2024 windows from the re-run scope and document the uncertifiable population.
Per `[[feedback-mr-corpus-screening-universe]]` the requirement is uniform spread across the
**selected ~20 pairs' windows**, not the whole corpus — audit those windows specifically.

### P4 — spread>0 parity fixtures (the charge's proof-of-life)
`exec_fill`/`bar_spread` are no-ops at spread=0, so **every existing parity test passes whether or
not the charge is wired** on 0-spread data. The kept-corpus parity window (2024-09→2024-12
EURUSD/USDJPY) *was* empirically confirmed to carry nonzero spread (USDJPY median 0.019, max
0.050) — but it exercises the wrong rule class. Author **synthetic-spread (spread>0) fixtures**
that drive the actual PineZRev fast path **before** the flip is accepted. A green parity test on
0-spread data is **no evidence**.

---

## 3. The atomic flip commit

All of the following land in **one commit** (the pre-commit convergence gate makes a partial flip
unlandable, and any one-sided charge produces a half-charged corpus):

### 3a. Re-point (the stamp)
- `basket_runner.py:38` — `from engine_abi.v1_5_9 import (...)` → `engine_abi.v1_5_10` (8 symbols
  unchanged; v1_5_10 `__all__` is a verified superset).
- `basket_runner.py:60` — `ENGINE_ABI = "engine_abi.v1_5_9"` → `"engine_abi.v1_5_10"`.
- **Preserve** the SSOT re-export block (`:49-64`, commit `4f5ac8fb`) and `__all__` — only the
  version token changes. Update the doc/comment strings for accuracy.

### 3b. Entry charge (the compute)
- Add `from engines.execution_fill import exec_fill, bar_spread` (leaf-safe — `execution_fill.py`
  imports only pandas; use the **shared** module, NOT the ABI's private `_exec_fill`, which isn't
  on the `__all__` surface).
- `basket_runner.py:472-477` — `leg.state.entry_price = exec_fill(entry_open,
  is_sell=(leg.direction == -1), spread=bar_spread(entry_row))`. **`is_sell` keyed on
  `leg.direction`** (the base/initial sign stored once at fill — correct per the engine path).
- **Seed `trade_high`/`trade_low` (`:478-479`) and `initial_stop_price` (`:484`) from the charged
  `fill_price`, not raw `entry_open`** — else MFE/MAE enrichment fields are a secondary half-charge
  that desyncs fast-vs-engine.

### 3c. Rule-exit charge (the dominant exit — the half-charge fix)
- `cointegration_meanrev_v1_2.py:106-126` (`_leg_pnl_usd_universal`) and
  `pine_ratio_zrev_v1.py:818-836` (`_liquidate`, **bar_close mode only**) — charge the embedded
  per-bar spread against the exit price *before* PnL: long-leg exit at bid (close − spread),
  short-leg at ask, mirroring `_exec_fill` semantics. The recorded `exit_price` (`:825`) and the
  realized `pnl_usd` (`:830`) must both reflect the charged fill.
- **`is_sell` keyed on `leg.effective_direction`** (cycle-aware), exit side inverted from entry.
  This is the **2026-05-24 `leg_direction_flip_bug` re-entry point**: PineZRev legs flip sign per
  cycle (SHORT_SPREAD vs LONG_SPREAD); using `leg.direction` charges the wrong side.
- Strict **no-op at spread absent/0** (mirror `_bar_spread`'s guard) — preserves the
  byte-identity-to-v1.5.9 parity claim.
- Do **not** disturb the `LIQUIDATE_<reason>` string contract (`canonical_metrics` depends on it).

> **Round-trip invariant:** entry + rule-exit together must pay **exactly one spread per leg**
> (matching the engine-level invariant in `test_v1510_basket_parity.py:119-126`). Charging only one
> end is wrong by half a spread.

### 3d. Convergence-test co-edit (same commit — it's in the pre-commit gate)
`tests/test_engine_identity_convergence.py` (gated at `tools/hooks/pre-commit:137` +
`system_introspection._GATE_TEST_SUITE:676`) fail-closes the instant baskets re-point:
- Line 34 import → `engine_abi.v1_5_10`; line 48 → `== "engine_abi.v1_5_10"`.
- **Re-target ALL override sentinels** (lines 62, 65, 76, 79, 99) from `"1.5.10"` → `"9.9.9"`
  (matching the already-fixed line 192). Once 1.5.10 is the *real* compute, asserting `compute !=
  "1.5.10"` is `value != itself` → the override-inertness proof goes **vacuous** (passes for the
  wrong reason). One spot was fixed; five were left — fix all.
- **Add a positive lock:** `ENGINE_VERSION == "1.5.10"` and `ENGINE_ABI == "engine_abi.v1_5_10"`
  literally, so an accidental revert to v1_5_9 fails loud.

### 3e. abi_audit (governance — resolve empirically)
Facets disagreed whether `basket_runner` must be added to the v1_5_10 manifest `consumed_by`.
**Run `python tools/abi_audit.py --pre-commit` with the re-point staged** to settle it. If required:
add `Trade_Scan.tools.basket_runner` to `consumed_by` for the 8 imported symbols + bump
`consumer_count` + `abi_audit.py --rehash --abi-version v1_5_10`, **in the same commit**
(`governance/` is protected — folds into the P0 approval).

---

## 4. Test plan — lock the CHARGED compute, not just the stamp

The existing tests lock the *stamp*; **nothing currently asserts the kept arms' charged
*compute*** (all v1510 parity tests drive `run_execution_loop` directly or use the H2 rule, never
the PineZRev fast path). New tests are **flip prerequisites, not fast-follows**:

1. **End-to-end `basket_runner` parity** (the test `test_v1510_basket_parity.py:12-14` explicitly
   defers "to the canonical flip"): drive a real `basket_runner.run()` (fast AND engine path) on a
   **spread>0** fixture; assert round-trip pays exactly one spread/leg, fast==engine, and
   byte-identical at spread=0.
2. **PineZRev rule-level charged-exit** through `_run_fast_path` on spread>0: long-leg `_liquidate`
   prices at bid, short at ask; **must FAIL on the pre-fix raw-close exit** (so it genuinely locks
   the charge).
3. **Cycle-flip charge-side**: open a SHORT_SPREAD cycle (`effective_direction != direction`) and
   assert the spread is charged on the side dictated by `effective_direction` — the only test that
   distinguishes the correct fix from the `leg_direction_flip_bug` reintroduction.
4. **Strengthen `test_spread_self_id.py:122-135`** post-flip: assert the live basket ABI maps to
   `startswith("spread_charged")` (today it only asserts `not unspecified:`, which passes for
   uncharged too).
5. **Gate-roster additions:** add the new end-to-end + the strengthened self-ID lock to BOTH
   `tools/hooks/pre-commit` and `system_introspection._GATE_TEST_SUITE` (keep in sync). Today the
   *only* gated charging assertion is the stamp test — a half-charge surfaces only in a manual full
   suite.
6. **Audit `test_basket_runner_phase2.py`** byte-identity fixtures (`NoOpStrategy`/`_df`) for
   spread values BEFORE the flip — if spread>0 and the strategy opens a position, the charged
   `basket_runner` diverges from its v1_5_9 reference and the assertion breaks silently. (Likely
   spread=0/no-trade and safe, but **verify, don't assume**.)
7. Rename/retarget the cosmetic stale strings (`test_basket_runner_phase2`'s AST-guard test name +
   message) — non-breaking, accuracy only.

---

## 5. Promotion mechanics (vault / registry / status)

- **Vault** (`governance/SOP/ENGINE_VAULT_CONTRACT.md §4`): after preflight + full pipeline +
  governance PASS + clean git tree, copy `engine_dev/.../v1_5_10/` → `vault/engines/.../v1_5_10/`,
  then commit + tag, then set `engine_manifest.json` `vaulted:true` (order matters).
  **Pre-existing gap:** `v1_5_9` was *never* vaulted (`vault/engines/` jumps `v1_5_8` → nothing) —
  flag for a conscious waive-or-resolve decision; it is not introduced by this flip.
- **Status:** `engine_dev/.../v1_5_10/execution_loop.py` declares `ENGINE_STATUS="EXPERIMENTAL"`.
  Moving the canonical basket compute onto an EXPERIMENTAL engine needs an explicit
  EXPERIMENTAL→FROZEN decision (`engine_manifest.json` + freeze_date).
- **Registry:** **do NOT** touch `active_engine` (stays `v1_5_8`; baskets don't read it — §1).
- `_SUPPORTED_ABIS` already includes both v1_5_9 and v1_5_10; v1_5_9 stays consumed by TS_Execution
  + tests, so no retirement is forced.

---

## 6. LM/HF cherry-pick recipe (P2 detail)

`git cherry-pick 28a80cc8 0082b0bb` (HF then LM). HF produces 6 conflicts (registry.yaml,
rule_code_hashes.yaml, basket_pipeline.py, recycle_rules/__init__.py, run_pipeline.py,
tools_manifest.json); LM adds INDICATOR_REGISTRY.yaml. **All are context-drift** (the fork carries
a whole sibling-rule family main lacks), not competing edits. Resolution:

- `recycle_rules/__init__.py` / `run_pipeline.py LEG_STRATEGY_DISPATCH` / `basket_pipeline.py`:
  keep main's content, **add only the HF + LM** import/registration/dispatch entries. **Prune the
  sibling-rule lines** (hl/zavg/zstop/hflm/session_window) the conflict context drags in —
  registering a rule whose `.py` wasn't picked fails at import.
- `basket_pipeline.py _instantiate_rule` (HF + LM blocks): **DROP the `max_bars_in_trade=` and
  `exit_fill_timing=` kwargs** — those fields exist only on the fork's `+234`-line base (not
  pulled) and raise **TypeError at instantiation** on main's base. The HF/LM rule classes don't
  reference them internally (they add only `hurst_*` / `lm_*` fields). Keep
  `coint_break_exit`/`granular_parity_max_k`/`coint_regime_column` (those exist on main's base).
  Add a smoke instantiation to `test_hurst_entry_gate`/`test_lm_entry_gate`.
- `pine_ratio_zrev_v1.py`: **accept the auto-merge** (status M) — do NOT `git checkout --theirs`
  (would wipe main's BB-adaptive-width feature). Confirm post-merge that `adaptive_width`/`bb_k`/
  `bb_m` (12 refs) AND the new `pine_zrev_ratio` line both survive.
- `indicators/stats/normalized_net_move.py` (LM dep) applies clean as an add; `hurst_rs` (HF dep)
  is already on main.
- `rule_code_hashes.yaml` + `tools_manifest.json`: take main's, then **regenerate** (rule hashes
  via `generate_recycle_rule_hashes.py` — a HUMAN-ONLY blessing op, run LAST after registry+rules
  are staged; manifest via its auto-regen).
- **Post-cherry-pick assertion:** `git ls-files tools/portfolio/comparison_schema.py
  tools/portfolio/comparison_writer.py` must return both.

---

## 7. Post-flip corpus re-run (Phase 3 — gated on the flip being PROVEN green + DATA)

Charged research is the *point*, but it is **the point of no easy rollback**: charged rows in the
append-only `cointegration_sheet` (Invariant #2) coexist with uncharged twins and cannot be
un-written. **Do not re-price the corpus until the flip is proven green** (spread>0 parity +
convergence + abi_audit) AND the P3 data decision is made.

- **Scope:** the operator-selected **~20 pairs** × the (≤5) kept arms — *not* the whole 2377-row
  corpus. Driver pattern: `tmp/rerun_affected_xau.py` (identity-preserving `--refresh`, recovers
  `DIRECTIVE_SOURCE.txt`, supersedes the prior `is_current=1` row). Use the **recorded** window
  (not `--window-mode current`, which changes window+engine together).
- **Supersession is the only contamination guard:** each charged rerun must supersede its uncharged
  twin (match by pair+span). **Verify the key match is exact** before trusting it.
- **MPS / operator surface (BLOCKER — currently uninvestigated by any prior plan):**
  `trade_candidates_view.py:113` groups by pair only with **no cost-regime split** — a pair holding
  both a charged and an uncharged `is_current` row blends two incomparable regimes into one median
  Ret/DD the operator reads to pick deployments. **Add `execution_cost_model` (or a charged/
  uncharged badge) to `TRADE_CANDIDATES_COLUMNS` + the MPS export**, and/or hard-guarantee
  supersession prevents mixed-regime `is_current` per pair. Then `ledger_db --export-mps` →
  `format_excel_artifact --profile portfolio`.

---

## 8. Cross-cutting hazards & guards

- **Certification filter is comment-only.** The two-clause contract
  (`execution_cost_model LIKE 'spread_charged%' AND spread_coverage_pct >= 99`) lives only as a
  schema comment + one test. **Add a canonical helper / SQL VIEW** (`decision_grade_charged_clause()`)
  so a consumer cannot drop the coverage clause and mis-certify a thin-coverage charged run.
  Coverage attests **presence**, not correctness, of the spread (a present-but-mispriced spread
  still reads 100).
- **Liquidation floor (R7/R8) — no code change, but it's read-time-only.** The floor's
  `maxDD>100 ⟺ trough<0` discriminant is regime-agnostic and correct for the peak-relative
  `canonical_max_dd_pct` the ledger stores; charging only changes *how often* it fires. But the
  floor runs only in `cointegration_aggregator` at read time — a charged blowup is **stored with
  raw optimistic metrics**, and "genuinely charged AND solvent" isn't answerable in one query.
  Update the stale `cointegration_aggregator.py:74-82` docstring (floor now also catches
  ordinary-spread-cost blowups, not just leveraged-sizing cohorts).
- **Live execution is SAFE and must be documented.** Live basket targets are **signal-derived**
  (`driver.py:37-59` — Target from position state; triggers on `zcross`/`coint_regime` *signals*,
  not PnL/equity), so the v1.5.10 charge is **provably invariant to the live target sequence**. The
  live heartbeat will stamp `1.5.10` (label-only; bridge consumers ignore the key). **TS_Execution
  stays `v1_5_9`** — `portfolio.yaml:6` pins `abi_version: v1_5_9`, `phase0_validation.py:30`
  `_SUPPORTED_ABIS=('v1_5_3','v1_5_9')` (v1_5_10 isn't even allowed), `strategy_loader.py:154`
  hardcodes v1_5_9. **Document the intended research(v1.5.10)/live(v1.5.9) ABI divergence** so a
  future operator doesn't "complete" the flip by bumping the live pin.
- **Load-bearing doc updates (in the flip change-set):** `SYSTEM_STATE.md:77` (asserts baskets are
  v1.5.9 override-inert "behaviour unchanged" — becomes FALSE) and `:71` (floor scope); a
  RESEARCH_MEMORY/MEMORY entry recording baskets→charged v1.5.10 + the ~24% uncertifiable-window
  consequence.
- **Comparison ledger is an empty, manually-driven table** (0 rows; `comparison_writer` not invoked
  in any run path). Do **not** present it as the live comparability guard unless a step actually
  populates it. Either wire `comparison_writer` into the rerun driver to emit (uncharged-twin,
  charged-rerun)→`comparable=NULL` rows, or rely on supersession + the MPS cost-regime column (§7).
- **Rollback asymmetry:** code reverts cleanly; **data does not.** This is why the corpus re-run is
  gated behind a proven-green flip.

---

## 9. Open decisions for the operator

1. **DATA (P3) — the gate:** backfill 2024 FX spread via DATA_INGRESS regen, or exclude 2024
   windows + accept the ~24% uncertifiable population? (Determines whether the flip charges anything
   real.)
2. **Scope of "the flip":** basket-compute only (recommended), or also flip `active_engine` for the
   single-strategy path?
3. **v1_5_10 status:** promote EXPERIMENTAL→FROZEN as part of this, or flip the basket compute onto
   an EXPERIMENTAL engine and FROZEN-promote separately?
4. **Selected ~20-pair universe:** is it documented or operator-held? Which of the ≤5 arms re-run
   (BBK20 was REJECTED in Exp1)?
5. **Pre-existing gaps to waive or fix now:** v1_5_9 never vaulted; comparison ledger never
   populated.

---

## 10. Execution order (checklist — each gated)

```
P0  Human approval (Invariant #6)                                    [STOP]
P1  FF feat/r9-spread-self-id → main; assert 289c9c76 ∈ main         [gate: merge-base]
P2  Cherry-pick 28a80cc8 + 0082b0bb (§6); assert comparison files survive
P3  DATA decision: backfill 2024 FX spread OR scope-exclude (§2 P3)  [the real gate]
P4  Author spread>0 parity fixtures + the 3 new tests (§4)           [must FAIL pre-fix]
─── ATOMIC FLIP COMMIT (§3) ──────────────────────────────────────
    3a re-point  + 3b entry charge + 3c rule-exit charge
    + 3d convergence-test co-edit (sentinels→9.9.9 + positive lock)
    + 3e abi_audit (empirical)  + new tests green on spread>0
    local pre-commit GREEN before commit
─── PROMOTION (§5) ───────────────────────────────────────────────
    vault per §4 · EXPERIMENTAL→FROZEN · (active_engine untouched)
─── PROVE GREEN, THEN PHASE 3 (§7) ───────────────────────────────
    ≥1 charged run reaches coverage≥99 & self-stamps spread_charged
    → MPS cost-regime column → selected-universe re-run → supersede → export-mps
─── DOCS (§8) ────────────────────────────────────────────────────
    SYSTEM_STATE.md:71/77 · RESEARCH_MEMORY · doctrine notes
```

---

## 11. Evidence index (key citations)

- Re-point sites: `basket_runner.py:38,60`; SSOT block `:49-64` (commit `4f5ac8fb`); stamp helpers
  `run_pipeline.py:869-901`.
- Fast-path fills: `basket_runner.py:472-477` (raw entry), `:478-479,484` (tracker seeds), `:489`
  (engine skipped), `:509` (DATA_END auto-charges).
- Rule exit (raw): `pine_ratio_zrev_v1.py:818-836` (`_liquidate`, `:825` raw exit_price);
  `cointegration_meanrev_v1_2.py:106-126` (raw PnL, no spread term).
- Charged fill helpers: `engines/execution_fill.py:26-39` (shared `exec_fill`/`bar_spread`);
  `engine_dev/.../v1_5_10/evaluate_bar.py:116-132,320-325` (engine `_exec_fill`).
- Gate: `tests/test_engine_identity_convergence.py:34,48,62-65,76-79,99,192`;
  `tools/hooks/pre-commit:97,131-138`; `system_introspection._GATE_TEST_SUITE:670-677`.
- abi_audit: `tools/abi_audit.py:53,222-254,278-312`; `governance/engine_abi_v1_5_10_manifest.yaml`.
- Cherry-pick: HF=`28a80cc8`, LM=`0082b0bb`; deletion danger `git diff main..onboarding`
  (comparison_schema/writer `deleted file mode`); TypeError trap `basket_pipeline.py _instantiate_rule`.
- DATA: 2024 FX RESEARCH ~34% coverage; ~565/2377 `is_current=1` rows in/overlap 2024.
- Live safety: `tools/live_basket/driver.py:37-59,143`; TS_Execution `portfolio.yaml:6`,
  `phase0_validation.py:30`, `strategy_loader.py:154`.
- Operator surface: `trade_candidates_view.py:58,113`.
- Floor: `leverage_liquidation_adjust.py:58-91`; `cointegration_aggregator.py:74-93`;
  `canonical_metrics.py:356` (peak-relative DD).
- Registry self-defer: `config/engine_registry.json:25`. Vault gap:
  `vault/engines/Universal_Research_Engine/` (v1_5_8 only). Phase-1: `289c9c76` on
  `feat/r9-spread-self-id`.
```
