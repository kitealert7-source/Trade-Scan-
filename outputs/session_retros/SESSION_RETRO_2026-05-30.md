# Session Retro — 2026-05-30

**Window:** since `ca284e0` (last close)
**Findings:** 9 (target 5–15)
**Disposition:** parked as report; no per-item approval landed (operator deferred)

---

## What the session did

1. **Methodology correction.** Raw-price ADF → log-price Engle-Granger with MacKinnon (1996) criticals. `methodology_version` column added to `cointegration_daily` + `cointegration_sheet`. Legacy rows tagged `v1_raw_adf`; new rows default `v2_log_eg`.
2. **Backfill (BC1–BC4).** Wholesale historical re-classification 2024-01-01 → present, both 1d/252 + 1d/504 + 4h/1500 + 4h/3000 lookbacks, parallel + resumable via `cointegration_backfill_screener.py`. BC4 wall clock 7h 45m.
3. **Generator promoted out of tmp.** `tools/generate_cointrev_v3_directives.py` with N=5 causal confirmation model + 7 contract tests.
4. **v1 corpus retirement.** 330 ledger rows dropped via `repair_integrity.py --action drop`; 330 backtests/ + 323 runs/ + 18 raw-only orphan folders deleted; 366 v1-era completed directives moved to `archive/v1_legacy_corpus/`. 68 superseded `v1_raw_adf` rows retained as audit tombstones. Full audit appendix at `outputs/cointegration_v1_retirement/`.
5. **CR-EXIT-FIX rework.** First v2 corpus (527 directives, exit=break+1) ALL rejected at `window_validity_gate` — two operator-locked rules silently conflicted. Exit rule revised to `last_coint_idx`, generator + tests + docstrings updated, regenerated 488 directives.
6. **v2 baseline corpus run.** 488 directives → 473 cointegration_sheet rows, 258 distinct pairs, 17 min @ `--max-parallel 8`. 246 profitable (52%), median +0.12%, max DD median 3.60%.
7. **488 → 473 audit.** 15 silent skips, all 0–3 day windows, all hit `pine_ratio_zrev_v1`'s `2 * n_window` minimum-bars assertion. Operator's "warm-up bars" hypothesis confirmed.
8. **Warmup-bars mechanism gap identified.** `run_stage1.RESOLVED_WARMUP_BARS` (single-strategy path) was never ported to the basket pipeline. Spawned as a separate task chip.
9. **Batch analysis.** `cointegration_aggregator.py` rolled up the 473 rows by pair-class. FX-FX cleanest (62% pos, 0 blowups), CRYPTO/METAL fat-tailed (15% blowup), FX-IDX largest+weakest (ret/dd 0.28). Snapshot doc updated with §6.

**Canonical snapshot:** [outputs/system_reports/06_strategy_research/COINTEGRATION_V1_TO_V2_TRANSITION.md](../system_reports/06_strategy_research/COINTEGRATION_V1_TO_V2_TRANSITION.md)

---

## Friction (3)

### F1 — CR-EXIT-FIX rework (IMMEDIATE)

- **Issue.** Generated 527 directives with `exit = break_idx + 1` per operator's "exit on day after break" spec. ALL 527 rejected at `window_validity_gate` because the rule (operator-locked 2026-05-28) requires `end_date <= last_coint_date`. Revised generator + regenerated 488.
- **Root cause.** CR-VERIFY phase validated date arithmetic + indexing convention but not admission compatibility. Two operator-locked rules conflicted silently at corpus-write time.
- **Frequency.** First occurrence; will recur whenever two independently-locked rules touch the same artifact.
- **Suggested fix.** Add a "verify-via-gate" assertion to corpus generation: pick one sample directive, call `evaluate_window_validity()`, fail loud on REJECT BEFORE bulk write. ~5 lines.
- **Sink.** Feedback memory entry.

### F2 — Schema migration didn't auto-apply (IMMEDIATE)

- **Issue.** `methodology_version` column was added to schema code (`tools/portfolio/cointegration_schema.py`) in C2, but the live `ledger.db` didn't have the column until I manually invoked `tools.ledger_db.create_tables()`. First query failed cold with `OperationalError: no such column: methodology_version`.
- **Root cause.** Schema migration runs only at first-write path, not at session start or first-read.
- **Frequency.** Will recur every time a column is added.
- **Suggested fix.** Feedback memory note: "after schema additions in `cointegration_schema.py` / `ledger_db.py`, manually invoke `tools.ledger_db.create_tables()` against live DB before relying on the column."
- **Sink.** Feedback memory entry.

### F3 — Monitor terminal-condition unfamiliarity (SHORT)

- **Issue.** Pipeline-progress monitor used `inbox == 0 AND active == 0` as "done" trigger. Fired prematurely at T+30s because the orchestrator moves directives `INBOX/` → `active_backup/` during dispatch (not into `active/`). Restarted with corrected condition (drain of `active_backup`).
- **Root cause.** The directive state-flow `INBOX → active_backup → completed` isn't documented anywhere a monitor-author would find it.
- **Suggested fix.** Feedback memory note documenting the actual flow.
- **Sink.** Feedback memory entry.

---

## Robustness (2)

### R1 — Engine admission rejections leave no ledger trace (STRATEGIC, propose-only)

- **Risk.** 15 short-window directives failed inside the engine (`pine_ratio_zrev_v1.py:215` raises on `len(common_idx) < 2 * n_window`). No `cointegration_sheet` row, no `rejected_runs` row, no clear log signal — operator-prompted audit was the only way to find them.
- **Likelihood.** High — will recur for every short-window or low-data directive.
- **Damage.** Corpus accounting silently incorrect. Operator must manually reconcile completed/ vs ledger.
- **Mitigation.** Write a REJECTED row (with reason) to a sibling table or to `cointegration_sheet` with a `regime_state='rejected_minbars'` marker.
- **Priority.** Protected Infra (`tools/basket_runner.py`, `tools/recycle_rules/*.py`); propose only.

### R2 — Two operator-locked rules can silently conflict (STRATEGIC, propose-only)

- **Risk.** `window_validity_gate` (locked 2026-05-28) and the today-session exit=break+1 rule (locked 2026-05-30) contradicted each other at corpus-write time. No pre-write check.
- **Likelihood.** Medium — each new operator-locked rule expands the conflict surface.
- **Damage.** This session: one full corpus generation cycle wasted (~15 min). Future: could be larger.
- **Mitigation.** When locking a new generator / admission rule, list which existing operator-locked rules it touches or contradicts (governance discipline, not a code change).
- **Priority.** Governance memory entry; propose only.

---

## Resilience (1)

### Res1 — Bulk admission failure has no pre-flight (SHORT, propose-only)

- **Failure scenario.** Bulk-misconfigured corpus run. This session: 488 directives, 488 noisy log lines + 1 actionable line buried near the bottom.
- **Current recovery cost.** ~30 seconds of pipeline run + ~minutes of log grep to find the cause.
- **Improvement.** `run_pipeline.py` could admission-test the first 5 directives BEFORE parallel-dispatching the rest. If all 5 reject at the same gate, halt with a summary error.
- **Priority.** Protected Infra (`tools/run_pipeline.py`); propose only.

---

## Missed Opportunities (2)

### MO1 — Mechanism-port-checking pattern (IMMEDIATE)

- **Observation.** `run_stage1.RESOLVED_WARMUP_BARS` exists in the single-strategy path. Basket pipeline doesn't carry the equivalent. Operator: "we forgot to include it." This is the second time this session a mechanism in one path was absent in a sibling path (the first being the schema-migration gap, F2).
- **Why missed.** Code review at the time of basket-pipeline development presumably focused on what was added, not what was missing. No checklist for "boundary checks travel with the path."
- **Recommended action.** Memory entry: "when a mechanism exists in one execution path (run_stage1, single-strategy), explicitly verify whether sibling paths (basket_pipeline, basket_runner) carry the equivalent. Boundary checks must travel with the path."
- **Sink.** Memory entry (project / feedback).

### MO2 — Snapshot discoverability (IMMEDIATE)

- **Observation.** `COINTEGRATION_V1_TO_V2_TRANSITION.md` is the canonical record of the v2 baseline, the CR-EXIT-FIX revision, and the corpus-aggregate roll-up. Nothing in `RESEARCH_MEMORY.md` points at it. Future sessions asking "what's the cointegration baseline?" will not find it on a `grep`.
- **Recommended action.** Add a one-line pointer to `RESEARCH_MEMORY.md` Active section.
- **Sink.** RESEARCH_MEMORY entry.

---

## Future Pressure

None observed with anchored trend metrics this session.

---

## Monitor watch-list (active 2/10, unchanged this session)

- `[MONITOR]` RESEARCH_MEMORY.md size — 34→35.3 KB this session, 40 KB cap; promote when >38 KB AND still growing (first seen 2026-05-29)
- `[MONITOR]` conclusion-write-path provenance gate — promote to BUILD after ≥1 operational gate-shakeout session (first seen 2026-05-29)

---

## Considered and dropped (IGNORE)

- 68 superseded `v1_raw_adf` rows remain in `cointegration_sheet` (`is_current=0`). Inert tombstones; no operational impact; no forcing deadline. Cost of cleanup ≈ value of the audit trail. Drop.
- First Monitor's premature `[done]` fire — covered by friction F3; no separate Robustness/Resilience finding.

---

## ★ HIGH ROI CANDIDATE

**F1 — gate-verify step in corpus generation.**

If we only landed one thing from this session, it would be a feedback memory entry: *"before bulk-dispatching a generated directive corpus, pick one sample and run it through `evaluate_window_validity` (or the full admission flow); fail loud on REJECT before any bulk write."*

Catches the exact class of bug we hit (two operator-locked rules silently conflicting at corpus-write time) for the cost of ~5 lines of verification. Future operator-locked-rule additions benefit automatically.

---

## Disposition summary

Operator parked all 9 findings as a report (this file) without per-item approval. No friction-log rows, no Deferred Maintenance entries, no new tasks, no memory edits were landed from this retro. The retro is preserved here as a durable record so the findings can be revisited in a future session.
