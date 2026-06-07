# Basket Promotion — Implementation Plan (READ-ONLY, awaiting approval)

**Date:** 2026-06-07
**Status:** Plan only. No code written. Protected infrastructure (`tools/`) — requires explicit approval before any phase executes (Invariant #6).
**Narrow objective:** Promote **one** existing basket artifact — run_id `74d26f18407d` (`90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312`, CADJPY long / USDCHF short, GP/ZCROSS, Ret/DD 2.05, 197 cycles, current span 2026‑03‑12→06‑04) — into the **demo** deployment path, **with parity protection**.
**Explicitly NOT in scope:** a general basket-promotion system, a combined-PnL research quality gate, the TS_Execution live-loop wiring, multi-basket/portfolio, capital/correlation models. (The live-loop wiring is named in §5 as the gating dependency for the *subsequent* operational-validation phase.)

---

## 0. Revised sequence (simpler + strictly more robust — adopted 2026-06-07)

Rather than promote the stale `74d26f18407d` with a pin-today's-spec workaround, **re-run first so the artifact carries full provenance**, then promote. Ordered:

1. **Provenance fix (prerequisite — the chip task `task_5d2692d4`).** Add `broker_spec_sha256` to basket-run `input_provenance` (`tools/basket_pipeline.py` / `basket_provenance.py`). Protected infra → its own small plan + approval. ~1 additive field, no behavior change.
2. **Produce the fresh run INSIDE the promotion tool via a direct `basket_pipeline` call** — NOT a standalone `run_pipeline` re-run. *(Discovered 2026-06-07: a standalone re-run of an existing cointegration directive is blocked at three points — the run_registry uniqueness guard, the append-only `cointegration_sheet` writer with no auto-supersede, and `basket_reset` being H2-only/operator-gated/destructive. A direct `basket_pipeline` invocation sidesteps the uniqueness guard and is the same call Phase 1's parity replay uses.)* The run records bars AND `broker_spec_sha256` (provenance fix landed `8ee1b87e`).
3. **The promotion tool owns `cointegration_sheet` supersession** the append-only writer doesn't do: after the fresh run lands `is_current=1`, mark the prior `74d26f18407d` row `is_current=0` (superseded_by = new run_id). This keeps `74d26f18407d` as a retained prior-reference tombstone (no purge needed — non-destructive).
4. **Promote the fresh run** through Phases 0–4 below.

**Why this is better, not just easier:**
- The fresh run records its spec → the parity replay pins from the **recorded** hash → **Tier-2 (sizing) is a true bit-exact backtest-vs-replay match**, not "exact under an unrelated pinned spec." The §3a workaround and its honest-limit caveat **no longer apply**.
- "Deployed == backtested" becomes bit-exact on **both** decisions and sizing.
- The window is the **current** cointegrated span (most live-relevant), still pinned to that fresh run's own recorded window per window-match discipline.
- `74d26f18407d` is demoted to a **prior-reference cross-check** (optional sanity), not the promotion target.

The §3a / Phase-1-Tier-2 / Phase-2 broker-spec **pinning** machinery below is now the **fallback only** (if ever promoting a pre-provenance-fix artifact directly); under this revised sequence the spec is recorded and the gate is a straight match.

---

## 1. Reuse / Adapt / Skip (every piece classified)

### Parity disambiguation (three distinct concepts — this plan builds #3)
The codebase has **three** different "parity" gates; only #3 is what "parity protection" means here:
1. **Streaming-vs-batch parity** — `tests/test_basket_runner_streaming_parity.py`. Proves a growing-prefix stream == batch bit-for-bit (indicators, per-bar `active_legs`, recycle events). **Built, passes.** Reused here as the *comparison engine*.
2. **Pipeline-vs-research parity** — `tools/h2_parity_run.py`. Proves pipeline outcome distribution == research-sim baseline across windows. **Built, used for H2.** Reused here as the *replay-producer invocation pattern* (`_try_basket_dispatch`).
3. **Promotion parity gate** — replay the *promoted* code+params on the *exact same backtest bars*, **trade-level exact-match, hard-stop on any single trade**. **NOT YET BUILT.** This is the deployment proposal's parity gate and the **main new code in this plan**. `basket_reproducibility_check` is only a manifest-hash *pre-filter* for it, not the gate.

### REUSE as-is (no changes)
| Piece | File | Role here |
|---|---|---|
| Basket vault writer | `tools/basket_vault.py` (`write_basket_vault`, `BasketVaultPayload`, `read_basket_vault`) | Full basket snapshot (basket.yaml + meta + recycle_events + legs/). Round-trip tested. |
| Parity **comparison engine** (#1) | `tests/test_basket_runner_streaming_parity.py` — `_run_mechanic` + bit-for-bit diff of indicators / per-bar `active_legs` / recycle events @ atol 1e-9 | The trade/state/event exact-match machinery to lift into the #3 gate. |
| Parity **replay producer** (#2) | a **single** `_try_basket_dispatch` call (the invocation *pattern* from `tools/h2_parity_run.py`) → `tools/basket_pipeline.run_basket_pipeline` | Re-run the vaulted directive **once** on its own recorded window. **Reuse the single-dispatch call ONLY — NOT h2_parity_run's 10-window sweep / distribution bucketing** (that is pipeline parity #2, a different question). |
| Manifest **pre-filter** (complementary) | `tools/basket_reproducibility_check.py` + `basket_provenance.compare_basket_runs` | Cheap hash-level drift check (leg_data_sha256 + code hashes). **Necessary-not-sufficient** — gates nothing on its own. |
| portfolio.yaml authority | `tools/promote/yaml_writer.py` (`_load_portfolio_yaml`, `_write_portfolio_yaml`, atomic tmp+rename, `_build_comment_block`, vault_id format `DRY_RUN_YYYY_MM_DD__{run_id[:8]}`) | Atomic descriptor write + comment block + integrity/consistency check pattern. |
| Bridge + shim (DRY) | `tools/live_basket/bridge.py`, `tools/live_basket/shim.py:run_once`, `tools/live_basket/driver.py:StreamingBasketRunner` | Phase-4 dry validation: prove the descriptor flows runner→target.jsonl→shim→`WOULD_OPEN`. No orders. |
| Demo gate (validation only) | `TS_Execution/config/demo_allowlist.json`, `src/basket_live_broker.py:assert_demo_allowed`, `src/basket_readiness.py` | Used at the later operational phase, not the promotion. Confirms 213872531/OctaFX-Demo. |
| Audit/integrity | `tools/promote/audit.py:_write_audit_log`, `tools/validate_portfolio_integrity.py` | Promotion audit trail + post-write integrity. |

### ADAPT (new thin code, mostly wiring reused parts)
| Piece | From | Adaptation |
|---|---|---|
| Promotion orchestrator | `tools/promote_to_live.py:promote()` (the *shape*) | New `tools/promote_basket_to_live.py`: basket-shaped flow. **Takes the run_id directly** (bypasses `find_run_id_for_directive`/`runs/*` single-symbol lookup). Reads legs/rule/params from the **basket directive + `cointegration_sheet` row**, not `backtests/{ID}_*` symbol folders. |
| Leg/lot/beta extraction | `_detect_symbols` (replaced) | Read `basket.legs` (symbol/direction/lot) + `recycle_rule{name,version,params}` from the frozen directive; record the screener `hedge_ratio` for the leg-ratio note. |
| Vault call | `tools/promote/strategy_files.py:_snapshot_to_vault` (replaced) | Build `BasketVaultPayload` from the run artifacts → `write_basket_vault(vault_id_dir, payload)` → assert round-trip + deterministic `vault_id`. |
| Deployment descriptor | `_build_yaml_entry` (single-symbol) → basket entry | Write a **basket descriptor** (legs, per-leg direction+lot, rule+params, run_id, vault_id, parity_status, data_vintage, lifecycle). **Design decision in §4: a dedicated `baskets:` block / `baskets.yaml`, NOT a single-symbol strategies[] row**, to avoid a TS_Execution `portfolio_loader` schema change inside this narrow scope. |
| **Promotion parity gate (#3) — BUILD (main new code)** | combines the reused replay (#2) + comparison engine (#1) | New `tools/basket_promotion_parity.py`: replay the **vaulted** directive on its recorded window/vintage → **trade-level exact-match** (per-leg trade log + recycle events) vs the recorded `74d26f18407d` artifacts. `leg_data_sha256` match is the pre-filter; the trade diff is the gate. **ABORT on any single-trade mismatch — "hard stop, no close-enough."** Catches code/param drift, vault serialization error, and live-vs-backtest preprocessing difference that the manifest hash alone can miss. |

### SKIP entirely (do not run against a basket)
- `tools/promote/strategy_files.py:_validate_strategy_files` — a basket has no `strategy.py` / `deployable/<profile>/` / `portfolio_evaluation/`.
- The **6-metric single-instrument quality gate** + **per-symbol all-or-nothing expectancy gate** (`tools/promote/quality_gate.py`, `pre_promote_validator` layers) — wrong shape for a 2-leg combined-PnL spread, **and** the edge is already research-settled; a single-symbol governance gate run against a basket would FAIL on shape, not signal (cf. `feedback_screening_rules_for_research`). A combined-PnL basket gate is a *future general* need, not required to promote this one validated artifact.
- Composite (`PF_*`) decomposition, `--batch`/`--batch-all`, multi-profile `deployable/` logic, `Control_Panel`/`portfolio_interpreter` CLI gate.
- **TS_Execution `portfolio_loader` schema extension + `main.py` basket orchestration loop** — the live-loop *wiring* (see §5). Out of scope for promotion; it is the prerequisite for the *operational-validation* phase, not for producing a parity-protected deployable descriptor.

---

## 2. Atomic phases (each independently verifiable; stop-after-any; parity is fail-fast FIRST)

**Phase 0 — Preconditions (read-only).**
Verify: `TradeScan_State/runs/74d26…/` exists with `run_state.json` + `manifest.json` (execution_mode=basket) + `input_provenance.leg_data_sha256`; the frozen directive resolves legs=[CADJPY long, USDCHF short], rule=`pine_ratio_zrev_v1_zcross`, GP params; `cointegration_sheet` row is `is_current=1`; basket not already in the descriptor. → **Exit:** a precondition report; ABORT on any miss. *(No writes.)*

**Phase 1 — Build + run the Promotion parity gate #3 (fail-fast, BEFORE any vault/descriptor write).**
**Scope: ONE artifact reproducing itself — nothing wider.** Replay *only* `74d26f18407d`'s own (bars, params, vaulted directive) and compare to *its own* recorded output. Build `basket_promotion_parity.py` (reusing #1's bit-for-bit comparison engine + a **single** `_try_basket_dispatch` call), then run it:
- (a) **pre-filter** — `compare_basket_runs` manifest match incl. `leg_data_sha256` (same substrate/code).
- (b) **gate** — replay the **vaulted** directive on the artifact's **frozen recorded window** (`test_start=2026-03-12`, `test_end=2026-06-04`) + recorded vintage — *the run's OWN window, never re-derived from the current screener* (which has since advanced to 06-05; regenerating would change the window and fail parity for the wrong reason — window-match discipline). Compare in **two tiers** (broker_specs YAML self-updates daily and was NOT recorded — see §3a):
  - **Tier 1 — DECISIONS (spec-independent → EXACT, hard-fail):** recycle-event sequence · per-leg trade entry/exit bars · open/close decisions · leg directions. *(For this config — zcross exit, harvest off — decisions are z-/price-driven, so spec drift cannot move them; a Tier-1 diff is a real code/param/serialization fault.)*
  - **Tier 2 — SIZING (spec-dependent → EXACT *under the vault-pinned spec*):** per-leg lots + realized-PnL stream reproduce against the spec snapshotted in Phase 2 (GP sizing reads `load_broker_spec`: `usd_per_pu`/`lot_step`/`min_lot`).
→ **Exit:** `PARITY=EXACT` (both tiers, under pinned spec) required; **hard-stop + report the FIRST differing record** on mismatch. A Tier-1 diff is always fatal; a Tier-2 diff under the pinned spec is also fatal (it means the sizing *logic*, not the spec input, drifted).
**Out of bounds (do NOT do):** no universe / family / FX-FX-class replay, no other-baskets regression — that is research + infra validation, already complete (#1, #2, 2249 runs). **Cost = exactly one replay.** *(Writes only a throwaway run folder; nothing promoted.)* This phase IS the deliverable's core — #3 did not exist before this plan.

**Phase 2 — Vault snapshot (incl. broker-spec PIN).**
Build `BasketVaultPayload` from the run artifacts → `write_basket_vault(DRY_RUN_VAULT/{vault_id}/, payload)` where `vault_id=DRY_RUN_2026_06_07__74d26f18` → assert `read_basket_vault` round-trips and `is_basket_vault` true. **Also snapshot the CURRENT `broker_specs/OctaFx/{CADJPY,USDCHF}.yaml` into the vault (`broker_specs_snapshot/`) + record their sha256** — this PINS the sizing substrate that the daily-self-updating YAML otherwise loses (the run's manifest recorded only `leg_data_sha256`). Phase 1's Tier-2 replays against THIS pinned spec. → **Exit:** immutable vault dir (legs + recycle events + **pinned broker specs**) + verified round-trip.

**Phase 3 — Deployment descriptor (atomic write).**
Write the basket descriptor (legs/dir/lot, rule+params, run_id, vault_id, `parity_status=REPRODUCIBLE`, data_vintage, `lifecycle: LIVE`, `target: demo`) to the chosen `baskets:` descriptor via the reused atomic tmp+rename writer; run the integrity/consistency checks (adapted to require run_id+vault_id+parity_status per basket). → **Exit:** one parity-stamped basket entry; integrity PASS.

**Phase 4 — Dry-path validation (no orders).**
Instantiate `StreamingBasketRunner` + `shim.run_once` in **DRY mode** from the descriptor against a short live-bar replay of the two legs → assert a target is emitted to `target.jsonl` and the shim classifies `WOULD_OPEN(CADJPY long, USDCHF short)` with correct per-leg magic/comment. → **Exit:** proof the promoted descriptor is consumable end-to-end through the existing bridge. **STOP — promotion complete.**

> Rollback: Phases 2–4 are additive (vault dir, one descriptor entry, dry logs). Reverting = remove the descriptor entry + vault dir. No ledger mutation; no execution side-effects.

---

## 3. Parity protection (what "protected" means, concretely)
This is the **Promotion parity gate (#3)** from the deployment proposal — distinct from the already-built streaming (#1) and pipeline (#2) gates. It is the one-shot, promotion-time confirmation that *deployed == promoted*.
- **Single-artifact scope — cost proportional to the question.** The question is *not* "does the cointegration framework still work" (proven: #1, #2, 2249 runs, the artifact itself) — it is **only** "does `74d26f18407d` reproduce itself." So it replays exactly that one run's bars/params/vaulted artifact and nothing else: **no universe, family, FX-FX-class, or other-basket replay.** One artifact in, one replay, one verdict.
- **Trade-level, not hash-level:** the gate is an **exact-match of the replayed trade + recycle-event sequence** vs the recorded run — `basket_reproducibility_check`'s manifest hash is only the pre-filter (it can match while a serialization/preprocessing drift still changes trades).
- **Gate, not afterthought:** Phase 1 runs *before* any promotion write; a non-exact artifact never reaches the descriptor.
- **Hard-stop, no "close-enough":** a single differing trade rejects promotion and must be investigated.
- **Substrate-pinned:** keyed on the recorded `leg_data_sha256` + window, so it is *same bars → same trades*, not "re-ran and got a number."
- **Stamped + re-checkable:** `parity_status=EXACT` + `data_vintage` + `run_id` ride in the descriptor and vault `basket_meta.json`; the gate re-runs on demand.
- **Leans on #1:** because streaming-vs-batch parity already guarantees the mechanic is deterministic, #3's job is specifically to catch *promotion-time drift* (vault snapshot code/params/data vs the original backtest) — not non-determinism.

### 3a. Broker-spec drift (the one input that legitimately moves) — *FALLBACK ONLY under §0*
> Under the revised §0 sequence (re-run after the provenance fix), the spec is **recorded** and Tier-2 is a true bit-exact match — the pinning workaround below is unnecessary. This section applies only if promoting a pre-provenance-fix artifact directly.

GP sizing reads `load_broker_spec` (`pine_ratio_zrev_v1.py:53/667`) for `usd_per_pu`/`lot_step`/`min_lot`; `usd_per_pu` for JPY/CHF legs floats with the daily FX rate and the `broker_specs/OctaFx/*.yaml` **self-updates daily**. So sizing is **not** bit-reproducible across days, and the original run recorded **only** `leg_data_sha256` — the 06-04 spec is gone.
- **Why it doesn't break decisions:** for this artifact (zcross exit, harvest threshold off), entries/exits/recycle events are z-/price-driven → spec-independent → Tier-1 reproduces exactly regardless of spec drift.
- **Why Tier-2 is pinned, not tolerant:** rather than allow a fuzzy lot/PnL tolerance (which would erode "hard-stop, no close-enough"), Phase 2 **pins** today's spec into the vault and Phase 1 Tier-2 replays against it — restoring an exact gate whose only spec input is frozen + auditable.
- **Honest limit:** "deployed == backtested" is bit-exact on **decisions**; on **sizing** it is "deployed == backtested *under the pinned spec*," because the true 06-04 spec is unrecoverable. Practical delta is small — `usd_per_pu` moves ~%/day and `lot_step` rounding usually absorbs it — but it is acknowledged, not hidden.
- **Live-sizing is a separate question:** whether the *live runner* sizes off the pinned vault spec (deterministic) or the live spec at each entry (current notional parity) is a deployment-layer choice for the operational phase — the gate only proves the sizing *logic* + decisions reproduce.

---

## 4. The one design decision to ratify before Phase 3
**Where does the basket descriptor live?** Two options:
- **(A) Dedicated `baskets.yaml` / `baskets:` block** *(recommended for this narrow scope)* — self-contained in the bridge/promotion world; **no TS_Execution `portfolio_loader` change**; keeps the single-symbol portfolio.yaml schema untouched. The future live loop reads baskets from here.
- (B) Extend `TS_Execution/portfolio.yaml` with a top-level `basket:` block + `portfolio_loader` parser — cleaner long-term unification, but pulls a cross-repo schema change into a narrow promotion and couples it to the loop wiring.

→ **Recommendation: (A).** It keeps promotion atomic and Trade_Scan-local; (B) folds naturally into §5's wiring phase if/when desired.

---

## 5. Out of scope — the gating dependency for *operational validation*
Promotion (Phases 0–4) lands a **vaulted, parity-protected, dry-validated descriptor**. It does **not** make the basket trade on the demo, because the live loop is unwired:
- `TS_Execution/src/main.py` has **no** basket runner instantiation, bridge polling, or `dispatch_group` call (single-symbol bar loop only).
- No process ties `StreamingBasketRunner` (data in) → `target.jsonl` → `shim` (LIVE mode) → `basket_exec.dispatch_group` (demo-gated) into a running service.

**Next phase (separate plan, separate approval):** "Live-basket loop wiring" — a TS_Execution sidecar (or `main.py` hook) that reads the §4 descriptor, runs the runner on the live `mt5_feed` bars for both legs, polls the bridge, and calls the P2-proven `dispatch_group`/`close_group` behind `assert_demo_allowed` + a both-legs-fresh tick gate. **That** is what enables the operator's "onboard → trade → break → offboard" demo lifecycle. Naming it here so promotion is not mistaken for dispatch-readiness.

---

## 6. Risks / notes
- **Data drift on re-run:** historical bars 03‑12→06‑04 are frozen, so Phase 1 Tier-1 should reproduce; if `leg_data_sha256` differs (substrate refreshed), that is a *flag to re-anchor*, not a silent pass.
- **Broker-spec provenance gap (found 2026-06-07):** the basket run records only `leg_data_sha256`, not a broker-spec hash, and `broker_specs/OctaFx/*.yaml` self-update daily → the exact backtest-time spec is unrecoverable. *Mitigation (this plan):* pin today's spec into the vault (Phase 2) + tier the gate so decisions stay bit-exact. **Forward fix (1-line provenance hardening, separate change):** add `broker_spec_sha256` to basket `input_provenance` at run time so future artifacts are fully spec-pinnable and Tier-2 becomes a true 06-04-vs-replay match.
- **Min-lot leg ratio:** GP sizing at 0.01 default; the descriptor records per-leg lots — verify they honor the research beta (hedge_ratio) at min-lot rounding before the operational phase.
- **`breaking`/removal feed** and the 5-state screener view are the parallel operational track (separate); not required for promotion.
- **No engine/ledger mutation** anywhere in Phases 0–4 — append-only invariants intact.

---
*Read-only plan. Approve to execute Phase 0; each phase gated on the prior. Parity (Phase 1) is the hard precondition.*
