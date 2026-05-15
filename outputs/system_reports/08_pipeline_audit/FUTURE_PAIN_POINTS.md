Honest assessment, no padding.

## Headline

The system is **~60% of the way to a defensible research pipeline endpoint** (Phases 0a-9 of the locked plan). Phase 10 LIVE is a separate question with different gates and isn't realistic on the current timeline. The remaining 40% splits roughly half engineering work, half calendar discipline you can't compress.

## Strengths (real, not generic)

1. **Governance is enforced, not aspirational.** Triple-gate ABI checks, append-only ledger invariants, indicator registry sync, frozen corpus immutability, junction prohibition — I watched pre-commit hooks fire and block bad commits today. That's rare. Most research codebases have governance documents nobody runs.

2. **Audit trails actually connect.** strategy.py → SIGNATURE_HASH → run_id → vault → MPS row → corpus manifest. You can trace any result back to its inputs. This is what survives a year of sessions.

3. **Real data is your moat.** Anti_Gravity_DATA_ROOT + DATA_INGRESS + lineage tracking + RESEARCH dataset versioning. Most retail-grade backtest systems use scraped data of unknown provenance. You have curated OctaFx 5m back to 2016 with hashes.

4. **The plan-lock pattern saved the H2 mechanic gap.** Without it, the wrong rule from Phase 3 would have aged into "the way it's always been." The locked-then-revised-at-v11 protocol let us catch it cheaply.

5. **Self-observing infrastructure** (SYSTEM_STATE auto-regen, MEMORY chain, INTENT_INDEX, post-merge watch). The system reports on itself, which is how it survived the multi-window drift this session.

## Weaknesses (specific, with evidence)

1. **Plan vs. execution gap.** The H2 plan is excellent on paper. In practice, parallel-session execution almost broke it twice today: (a) dual ABI collapsed to single without plan update — forced mid-execution v10→v11; (b) Phase 3 shipped a fundamentally wrong rule because nobody verified the mechanic against the validated reference. The structure is only as good as serial discipline.

2. **Artifact discoverability is the worst current architectural problem** — you named it yourself. Phase 5b's basket runs hide in `research/basket_runs.csv`. The 19 LIVE strategies are findable in MPS but per-trade audit paths vary by family. Every new artifact type adds a new location. This is *already* costing future-session productivity; it's not a future risk.

3. **Research-stage code lives in `tmp/`.** `tmp/eurjpy_recycle_v2_validation.py` is the canonical spec of H2 — discovered today by grep, not by directory structure. Strategy specifications shouldn't live where I delete scratch files at session-close. This is "research will be lost slowly" at the architecture level.

4. **Test depth ≠ test coverage.** 70 gate tests pass. But the pre-existing adversarial-test sys.modules bug is documented and unfixed, and none of today's tests actually run the pipeline against historical windows to verify research-stage parity. New tests get written well; cross-test interactions and end-to-end parity tests don't.

5. **TS_Execution is undertested post-ABI-migration.** It got migrated to v1_5_9 in a parallel session and we never validated the actual broker connection works against the post-migration ABI. The 9 LIVE strategies are at 0.01 fixed lot per Invariant 27 — that's fine — but the validator→executor handoff (Phases 7a→7b→8) is entirely unbuilt and untested. Plan defers this; the gap is just wider than it looks on paper.

6. **14-day observation windows are unimplemented operational dependencies.** Plan calls for ≥14 days clean observation between Phase 7a→7b→8. There's no calendar tooling. Validator emits heartbeats; nothing aggregates them into "clean for N days." That's runbook work but it's load-bearing for promotion safety.

7. **Strategy diversity within FX is narrow.** 19 strategies cluster around continuation/mean-reversion at 15M-1H FX + XAU 1H + index 1D. No baskets LIVE. H2 is the first multi-leg entering — if it works, basket templates multiply, and the rule registry (currently 2 entries, 1 deprecated) will need to scale.

## Time-to-complete by scenario

| Definition of "complete" | Engineering effort | Calendar |
|---|---|---|
| H2 runs through pipeline with discoverable artifacts + 10-window research parity | Path B + Phase 5d.1 | **1-2 focused sessions** (~6-12 hrs serial) |
| H2 on Phase 7a clean-observation clock with validator actively gating | + observation tooling | **2-3 weeks calendar / 3-5 build sessions** |
| H2 actually gates TS_Execution decisions (Phase 8 done) | + 7b shadow-read + flag wiring | **4-6 weeks calendar / 5-8 build sessions** |
| Plan fully executed through Phase 9 (multi-basket matrix) | + N-leg rule scaling work | **6-10 weeks calendar** |
| Phase 10 LIVE | TS_Execution multi-symbol overhaul (out of current plan scope) | **3+ months if pursued** |

## The honest risk

**The biggest risk to the timeline isn't engineering complexity — it's the multi-window parallel session pattern.** If you stay disciplined to single-window execution, the numbers above hold. If you split work across parallel sessions for "efficiency," add 30-50% rework overhead for drift reconciliation. Today proved the cost is real; tomorrow's Path B work is a good test case for the new discipline.

Get some rest. Pipeline's clean.