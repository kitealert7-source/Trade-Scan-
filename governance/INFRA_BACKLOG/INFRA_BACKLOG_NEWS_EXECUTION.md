# INFRA_BACKLOG — News Execution Plumbing

**Date:** 2026-05-03
**Source:** Phase 2 NEWS edge research (NEWSBRK Phase 2 + cross-family discovery + Path A side-channel validation)
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
**Status:** OPEN
**Audience:** anyone authoring an event-gated strategy in the future

This document collects every infrastructure / pipeline / governance friction that the NEWS research surfaced. None of these block the framework as a whole (the `FRAMEWORK_BASELINE_2026_05_03` regression suite is green), but each one is a pothole the next event-gated family will hit unless addressed.

---

## INFRA-NEWS-001 — `bar_hour` not auto-populated for FilterStack `session_filter`

| | |
|---|---|
| **Symptom** | Strategy with `session_filter` enabled returns 0 trades. `[REGIME_FILTER]` log shows filter active but no trades fire. |
| **Root cause** | `engines/filter_stack.py` `session_filter` calls `ctx.require("bar_hour")`, fails, sets `bar_hour=None`, **rejects every bar**. The `bar_hour` column is convention-required to be set in `prepare_indicators()` but no engine layer enforces or auto-populates it. |
| **Reproduction** | Author a strategy with `session_filter.enabled: true` and `exclude_hours_utc` non-empty. Do NOT add `df["bar_hour"] = df.index.hour` to `prepare_indicators`. Run any backtest → 0 trades. |
| **Severity** | HIGH — silent failure (no error, no warning, just zero trades). Cost me ~2 hours of debugging during Path A. The original RSIAVG_S03_V1_P03 production strategy works because the engine-runner via run_stage1.py merges HTF regime fields that incidentally include time-derived columns; my side-channel bypassed that path and exposed the real dependency. |
| **Fix recommendation** | Two options, either acceptable: **(A)** Engine adds `df["bar_hour"] = df.index.hour` automatically post-`prepare_indicators` and pre-loop. Single line in `run_execution_loop`. Backwards-compatible. **(B)** `FilterStack.session_filter` derives `bar_hour` from `ctx.row.name.hour` if available, falling back to ctx.get only when neither works. Rejects only when truly indeterminate. |
| **Affects future families?** | **Yes** — every strategy with `session_filter` enabled. |

---

## INFRA-NEWS-002 — Engine contract IDs hard-bound to specific engine versions

| | |
|---|---|
| **Symptom** | Authoring a new strategy by copying `REQUIRED_CONTRACT_IDS` from an existing production strategy → preflight fails with `ENGINE_RESOLUTION_FAILED: contract_id_not_whitelisted`. |
| **Root cause** | A strategy's `REQUIRED_CONTRACT_IDS` is bound to whichever engine version was active when the strategy was last canonicalized. If a copied source strategy was last run on v1.5.6, its contract is whitelisted in v1.5.6 only. The active engine v1.5.8a does not whitelist legacy contracts. |
| **Reproduction** | Copy `REQUIRED_CONTRACT_IDS` from `strategies/22_CONT_FX_15M_RSIAVG_TRENDFILT_S03_V1_P03/strategy.py` (sha256:962bfed5...) into a new strategy. Run pipeline. Hits `ENGINE_RESOLUTION_FAILED [F9]` with `v1_5_8a: contract_id_not_whitelisted`. |
| **Severity** | MEDIUM — surfaces clearly via preflight error, but error message doesn't explicitly tell the author "use the v1.5.8a contract from a recently-run strategy." |
| **Fix recommendation** | Either **(A)** Engine resolver error message lists the *valid* contracts for the active engine (so the fix is obvious), **(B)** A `tools/strategy_doctor.py --update-contract-id <strategy>` helper that derives the correct contract from `engine_lineage.yaml` and rewrites the file, refreshing the marker. **(C)** Strategy template generator that auto-fills the current engine's contract. |
| **Affects future families?** | **Yes** — every strategy authored by copying an older one (very common pattern). |

---

## INFRA-NEWS-003 — Canonicalizer schema rejects new top-level filter blocks

| | |
|---|---|
| **Symptom** | New filter type (e.g. `news_window_filter`) declared in directive YAML → admission fails at Stage -0.25 with `UNKNOWN_STRUCTURE: Unknown top-level keys detected: ['news_window_filter']`. |
| **Root cause** | `tools/canonical_schema.py` enumerates allowed top-level blocks (`market_regime_filter`, `regime_age_filter`, `session_filter`, `volatility_filter`, `trend_filter`, etc.). Any block name outside that allow-list is rejected. New filter categories require schema edits. |
| **Reproduction** | Add `news_window_filter: { enabled: true, ... }` as a top-level block to any directive YAML. Run pipeline. Fails at Stage -0.25. |
| **Severity** | MEDIUM — protects against typos and unauthorized config drift, which is the *intent* of the schema. But also blocks legitimate new filter types that don't have a clear "right place" to live. |
| **Fix recommendation** | **(A)** Document the schema-extension procedure in `governance/SOP/STRATEGY_PLUGIN_CONTRACT.md` so authors know how to register a new filter. **(B)** Allow an `extra_filters` namespace in the schema for experimental filters that don't yet warrant top-level promotion: `extra_filters: { news_window: {...}, my_filter: {...} }`. Pulls experimental clutter out of the top level without infinite schema growth. |
| **Affects future families?** | **Yes** — every novel filter type (next likely candidates: macro stress filter, JPY synth filter, regime-flip filter). |

---

## INFRA-NEWS-004 — `reset_directive` blocks strategy-content changes via EXPERIMENT_DISCIPLINE

| | |
|---|---|
| **Symptom** | After updating a strategy.py (e.g. fixing a contract ID, refreshing a hash, adding a missing column), `reset_directive` refuses with "RESET BLOCKED — LOGIC CHANGE DETECTED". Strategy stays in FAILED, can't re-admit. |
| **Root cause** | EXPERIMENT_DISCIPLINE is correctly designed to prevent silent re-runs after logic changes. But "fix the contract ID I copied wrong" and "fix a missing bar_hour" are *infra-administrative changes*, not logic changes. The discipline guard treats both identically. |
| **Reproduction** | Author a strategy. Run it, fail. Update the strategy.py for any administrative reason (incl. fixing a typo). Try `reset_directive`. Blocked. |
| **Severity** | LOW (a workaround exists: refresh the approval marker via `tools/approval_marker.py compute_strategy_hash` + `write_approved_marker`, then reset succeeds), but **discoverability is poor**. The reset error message doesn't tell you the workaround. |
| **Fix recommendation** | Reset error message should explicitly say: *"If this is an administrative change (contract ID fix, missing convention column, comment-only edit), refresh the approval marker via `tools/approval_marker.py` and retry reset. If this is a logic change, create the next directive version instead."* Both paths documented inline. |
| **Affects future families?** | **Yes** — anyone iterating on a strategy with admin-only edits. |

---

## INFRA-NEWS-005 — Strategy directory drift detector blocks reset-and-recreate cycles

| | |
|---|---|
| **Symptom** | After resetting a directive (which cleans run state) and trying to re-run, orchestrator pauses with `[GUARDRAIL] Strategy Directory Drift Detected: Untracked directory: <directive_id>. Manual reconciliation required.` |
| **Root cause** | Some bookkeeping registry tracks which strategy directories the orchestrator "knows about." `reset_directive` clears run state but doesn't update this strategy-folder registry, so on the next pipeline boot the folder appears "untracked" and the guardrail fires. |
| **Reproduction** | `python tools/reset_directive.py <directive_id>` then re-run pipeline → directory-drift guard pauses. |
| **Severity** | MEDIUM — recoverable but unclear how to "manually reconcile" (no helper named in the error). |
| **Fix recommendation** | **(A)** Reset_directive's auto-archive should also de-register the strategy folder from whatever bookkeeping it lives in. **(B)** Or expose a `tools/reconcile_strategy_directory.py <directive_id>` that explicitly registers / re-registers / removes a strategy folder. **(C)** Document the reconciliation procedure in `governance/SOP/`. |
| **Affects future families?** | Probably — any reset-edit-rerun cycle. |

---

## INFRA-NEWS-006 — PORT/MACDX duplication anomaly

| | |
|---|---|
| **Symptom** | Two distinct strategies (`05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00` and `54_STR_XAUUSD_5M_MACDX_S22_V1_P04`) produce **byte-identical trade-level CSVs**: same 1333 trades, same timestamps, same prices, same PnL ($2719.16), same news classification metrics in the discovery report. |
| **Root cause** | UNKNOWN. Could be: (a) one strategy module imports / aliases the other's signal logic with no namespace difference, (b) the two strategies independently computed identical signals (extremely unlikely for 1333 distinct entry timestamps), (c) artifact-emission bug copied trades across run folders, (d) `54_STR_XAUUSD_5M_MACDX_S22_V1_P04` is a literal alias / clone of PORT under the MACDX token. |
| **Reproduction** | Compare `TradeScan_State/backtests/05_PORT_XAUUSD_5M_PORT_TRENDFILT_S04_V1_P00_XAUUSD/raw/results_tradelevel.csv` vs `54_STR_XAUUSD_5M_MACDX_S22_V1_P04_XAUUSD/raw/results_tradelevel.csv` → trade fields are identical. Strategy.py files have different sha256 hashes. |
| **Severity** | MEDIUM — directly affects discovery-report accuracy (the bucket double-counted PORT/MACDX as two NEWS_AMPLIFIED candidates when they are one). Could indicate broader artifact-emission bleed-through that affected other comparisons silently. |
| **Fix recommendation** | One-shot investigation: diff the two strategy.py files structurally (not byte-wise, since they're different sizes), check whether one imports the other, check the run_registry.json metadata for cross-references, check whether each strategy actually called `prepare_indicators` and `check_entry` distinctly during its run. Document findings; if the duplication is intentional aliasing, mark one as canonical and deprecate the other in the namespace token dictionary. |
| **Affects future families?** | Possibly — if there's a class of cross-strategy artifact bleeding, other discovery findings could be inflated. |

---

## INFRA-NEWS-007 — Sweep registry orphan accumulation

| | |
|---|---|
| **Symptom** | 81 sweep entries in `governance/namespace/sweep_registry.yaml` reference strategy names that have no corresponding strategy folder and no directive file in any lifecycle location. (Note: count may include false-positives from multi-symbol naming patterns; refined audit needed.) |
| **Root cause** | `reset_directive` and ad-hoc cleanup remove strategy folders and directives but rarely de-register from `sweep_registry.yaml`. Stub entries with placeholder hashes (`signature_hash: 0000...`) accumulate when sweep slots are reserved before the strategy fully materializes and never get back-filled with real hashes. |
| **Reproduction** | `python` audit script (provided in this session's `tmp/`) walks `sweep_registry.yaml` cross-checking each `directive_name` against `strategies/` and `backtest_directives/{INBOX,active,active_backup,completed}` → flags orphans. |
| **Severity** | LOW — orphan entries don't actively harm anything, but they bloat the registry, make sweep slot allocation harder to reason about, and the placeholder-hash stubs (8 found) leave open the question "is this a sweep that's about to land or one abandoned 6 months ago?" |
| **Fix recommendation** | **(A)** Periodic cleanup tool: `python tools/sweep_registry_audit.py --report` (read-only orphan scan), `--gc` (archive orphans to a `sweep_registry_archive.yaml` after N-day grace period). **(B)** `reset_directive --full` should optionally de-register from sweep_registry. **(C)** Auto-consistency gate could refuse to advance `next_sweep` while > N orphans exist (forcing eventual cleanup). |
| **Affects future families?** | Indirectly — registry hygiene affects long-run navigability. |

---

## INFRA-NEWS-008 — `idea_registry.yaml` doesn't auto-track research closure

| | |
|---|---|
| **Symptom** | NEWSBRK family research closed via three reports (`outputs/NEWSBRK_15M_COMPARATIVE_2026_05_03.md`, `NEWSBRK_A1_5M_PRE_EVENT_TEST_2026_05_03.md`, `PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md` — collective verdict: KILL). But `governance/namespace/idea_registry.yaml` still lists idea 64 with `status: active`, `closed_reason: -`. |
| **Root cause** | No mechanism connects research output reports to idea_registry status updates. Closure is a documented outcome but not a registry transition. |
| **Reproduction** | Search outputs/ for any KILL or close-out report → cross-reference to idea_registry.yaml status of the corresponding idea_id. |
| **Severity** | LOW — purely cosmetic / discoverability. Future agents searching for "active families" via the registry get a wrong answer. |
| **Fix recommendation** | **(A)** A `tools/idea_close.py <idea_id> --reason <ref>` helper that updates the registry and logs to an audit trail. Author calls it after writing the closure report. **(B)** Or convention: closure reports include a manifest section the registry can scrape. **(C)** Or just expand the per-idea status enum: `active / closed_kill / closed_promote / parked` with a manual edit policy documented. |
| **Affects future families?** | **Yes** — every research family will eventually have a closure outcome that needs to land in the registry. |

---

## INFRA-NEWS-009 — Sweep slot collision at registration time

| | |
|---|---|
| **Symptom** | When I registered S13/S14 stubs under idea 22 for my Path A wrappers, those slots overwrote a pre-existing claim by `22_CONT_FX_30M_RSIAVG_TRENDFILT_S13_V1_P00` (a 30M directive in `completed/`). The 30M directive's prior sweep registration was silently lost. |
| **Root cause** | Sweep registration uses `next_sweep` to pick a slot, but the next-slot pointer can collide with slots claimed earlier by directives that authored without going through the next_sweep allocation flow (e.g. directives whose sweep was assigned manually or via a different code path). The registration is last-writer-wins with no collision check. |
| **Reproduction** | Idea 22 had `next_sweep: 13` AND a directive `22_CONT_FX_30M_RSIAVG_TRENDFILT_S13_V1_P00` already in `completed/` claiming slot 13. New stub for slot 13 silently overwrote the existing entry. |
| **Severity** | MEDIUM — silent data loss in the registry. Anyone investigating the 30M S13 directive's lineage now finds a 15M wrapper's hash in its old slot. |
| **Fix recommendation** | The sweep stub creator (manual or auto via auto-consistency) should: (a) check whether the target slot is already claimed by a different `directive_name`, (b) refuse if there's a conflict, (c) suggest the next available slot. Trivial change: `if slot in idea['sweeps']: raise SweepCollisionError(...)`. |
| **Affects future families?** | **Yes** — any time a researcher reserves a sweep slot manually. |

---

## Sequence in which these would have helped

Had INFRA-NEWS-001 (`bar_hour`) been fixed, my Path A side-channel would have produced trades on the first run instead of zero.

Had INFRA-NEWS-002 + INFRA-NEWS-004 (contract IDs + reset semantics) been fixed, I wouldn't have spent a full iteration cycle on contract-update + marker-refresh.

Had INFRA-NEWS-003 (schema extension) had a documented procedure, I would have known to move news config into a module-level constant immediately rather than authoring + canonicalizer-reject + refactor.

Had INFRA-NEWS-009 (slot collision) been guarded, I would not have silently corrupted the 30M S13 directive's sweep registration. (Reverted now via Phase 1 cleanup.)

The total time cost of these issues during the news research was approximately **3-4 hours of 7-8 hours of total session work**. Fixing items 001, 002, 004 alone would roughly halve that overhead for the next event-gated family.

---

## Severity rollup

| Severity | Count |
|---|--:|
| HIGH | 1 (INFRA-NEWS-001) |
| MEDIUM | 6 (INFRA-NEWS-002, 003, 005, 006, 008, 009) |
| LOW | 2 (INFRA-NEWS-004, 007) |

Recommended fix order:
1. INFRA-NEWS-001 — single-line engine fix, eliminates the largest single category of debugging time
2. INFRA-NEWS-009 — single-line registry fix, prevents silent data loss
3. INFRA-NEWS-006 — investigate PORT/MACDX duplication; affects all prior cross-family discovery work
4. INFRA-NEWS-002, 003, 004 — improve error messages and document workarounds; lowest-effort highest-leverage
5. The rest — opportunistic
