# FAMILY_REPORT_IMPLEMENTATION_PLAN — Post-Audit Build Plan

**Authority:** Post-Robustness-Audit Rules (Rule 1: reuse primitives, Rule 2: orchestration-only new code, Rule 3: cheap deterministic primitives only) + **Post-Approval Rule 4: wrapper-first, no refactors of stable surfaces in first release.**

**Rule 4 (added 2026-05-11 per user approval):**
- Family report may directly call existing primitives and use thin adapters.
- Family report MUST NOT modify `tools/robustness/runner.py` or `tools/generate_strategy_card.py` in the first release.
- Streak / calendar / signature-flatten logic may be duplicated inline in new modules under `tools/utils/research/` and `tools/report/` for the first release. The original inline implementations stay untouched in their current homes.
- Post-validation, a separate proposal may extract the duplicated logic into shared helpers (deferred work).
- Rationale: minimize blast radius and preserve stable reporting surfaces during first deployment.

**Companion docs:**
- [FAMILY_REPORT_DESIGN.md](FAMILY_REPORT_DESIGN.md) — design and rationale
- [REPORT_UPGRADE_PLAN.md](REPORT_UPGRADE_PLAN.md) — Phase A scope (per-strategy report upgrade)
- [REPORT_AUDIT.md](REPORT_AUDIT.md) — gap analysis

**Status:** Plan only. **No code changes until user reviews this doc and approves.**

---

## 0. Two-phase workstream

The reporting work has two independent phases that can land in either order:

| Phase | Scope | Trigger | Target file |
|-------|-------|---------|-------------|
| **A** | Upgrade existing per-strategy report (verdict block lift, risk surfacing, parent Δ, delete dupes) | Per-pass (every `python tools/run_pipeline.py <id>`) | `REPORT_<directive>.md` + `STRATEGY_CARD.md` |
| **B** | New family analysis report (orchestrate existing robustness primitives across N variants) | Manual `python tools/family_report.py <prefix>` | `outputs/family_reports/<prefix>_<ts>.md` |

**Build order recommendation:** Phase A first, because Phase B's "cross-link to per-strategy report" works better when the per-strategy report already carries the verdict block. But the two phases are otherwise decoupled — they touch different files and either can land independently.

---

## 1. Phase A — Existing report upgrade

### 1.1 Goals (verbatim from user)
1. **Verdict block** — lift CORE/WATCH/FAIL classification from Excel Notes sheet (row ~270) to the top of `REPORT_*.md`.
2. **Risk surfacing** — bring tail-concentration / direction-bias / longest-flat-period flags to the top, ahead of raw metrics.
3. **Parent Δ** — one-row "vs parent" delta in the header (PnL Δ, SQN Δ, DD Δ).
4. **Remove duplicate sections** — drop the 4 near-identical concentration tables flagged in REPORT_AUDIT §4.1.

### 1.2 Touched files

| File | Change | Effort |
|---|---|---|
| `engine_dev/universal_research_engine/v1_5_8/stage2_compiler.py` | **READ-ONLY** — must not modify (engine frozen). Verdict/risk inject happens in a wrapper, not the compiler. | 0 |
| `tools/report/report_sections/*.py` | Reorder sections; delete duplicate concentration tables. Sections module is in `tools/`, not engine — additive change OK. | M (3-4h) |
| `tools/report/_build_header_section` (or new wrapper module if not present) | Inject verdict + risk + parent Δ block at top of markdown report. Reads from existing primitives (`filter_strategies._compute_candidate_status`, `tail_contribution`, `directional_removal`). | M (2-3h) |
| `tools/filter_strategies.py` | NO CHANGE. Verdict logic already lives here at `_compute_candidate_status` — import from header builder. | 0 |
| `tools/tests/test_report_header_section.py` (new) | Unit tests: verdict block, risk flags, parent Δ extraction. | S (1.5h) |
| `tools/tests/fixtures/golden_report_<strategy>.md` (new) | Golden-snapshot acceptance test against a known directive (e.g. PSBRK V4 P14). | S (1h) |

**Out of scope for Phase A:**
- Engine module changes (frozen).
- Master Filter schema changes (append-only ledger).
- Excel `Notes` sheet content — the verdict already lives there; Phase A just surfaces it earlier in the markdown view.
- Stage 3 compiler — Excel structure unchanged.

### 1.3 Effort: ~1 day
- AM: refactor `report_sections` ordering + delete duplicates.
- PM: build header injector + tests.

### 1.4 Risk

| Risk | Severity | Mitigation |
|---|---|---|
| Header injection runs after stage2_compiler completes; if it raises, REPORT_*.md is missing the new block but the rest is intact | Low | Try/except around header injection; on failure log warning and skip injector. Pipeline continues. |
| Existing reports (already on disk) don't get retroactively upgraded | Low | Acceptable. New behavior takes effect on next pipeline run per directive. Historical reports stay as-is. |
| Section reordering changes downstream tooling expectations (Excel formatter, hyperlink restorer) | Medium | Audit `tools/excel_format/`, `tools/add_strategy_hyperlinks.py` for hard-coded section references before reorder. Inspect-only first. |
| Verdict block computation pulls trades CSV per-report, adds ~50ms per directive | Negligible | Acceptable — already happens elsewhere in stage 4. |

---

## 2. Phase B — New family report

### 2.1 Goals (verbatim from user)
1. **Manual invocation only** — `python tools/family_report.py <family_prefix>`.
2. **Allowed new code**: session derivation, lineage aggregation, variant comparison renderer.
3. **Reuse all analytics** from `tools/utils/research/` and `tools/robustness/`.

### 2.2 Touched files

#### 2.2.1 New files (orchestration + rendering + new analytics)

| File | Purpose | LOC | Status |
|---|---|---|---|
| `tools/family_report.py` | CLI entry + orchestrator | ~150 | NEW |
| `tools/report/strategy_signature_utils.py` | `flatten_signature` + `diff_signatures` | ~80 | NEW (extracted from `tools/generate_strategy_card.py`) |
| `tools/report/family_session_xtab.py` | Session derivation (hour→asia/london/ny) + 3 cross-tabs (Dir×Session, Dir×Trend, Dir×Vol) | ~40 | NEW (only genuinely new analytics) |
| `tools/report/family_verdicts.py` | Verdict orchestration: call `_compute_candidate_status` + apply family soft-gate overrides (Top-5 > 70%, body-after-Top-20 < -$500, longest_flat > 250d) | ~60 | NEW (orchestration) |
| `tools/report/family_renderer.py` | Markdown renderer: lineage table, comparative metrics, Δ-vs-parent, structural attribution tables, verdict | ~150 | NEW (rendering) |
| `tools/window_compat.py` | Cross-window comparability guard | ~30 | NEW |
| `tools/tests/test_family_report.py` | Unit tests + golden snapshot + forbidden-import guard | ~150 | NEW |
| `tools/tests/fixtures/family_psbrk_golden.md` | Golden snapshot for PSBRK family | data | NEW |

#### 2.2.2 Wrapper-first duplication (per Rule 4 — no refactors in first release)

| File | Source | Status |
|---|---|---|
| `tools/utils/research/streaks.py` | NEW module containing `compute_streaks()` — semantically equivalent to `_max_streak` / `_avg_streak` in `tools/robustness/runner.py:203-237`. **Duplicated inline body, NOT extracted.** | NEW (~30 LOC duplicated) |
| `tools/utils/research/calendar.py` | NEW module containing `yearwise_pnl()` / `monthly_heatmap()` — semantically equivalent to logic in `tools/robustness/runner.py:159-183`. **Duplicated inline body, NOT extracted.** | NEW (~40 LOC duplicated) |
| `tools/report/strategy_signature_utils.py` | NEW module containing `flatten_signature()` / `diff_signatures()` — semantically equivalent to `_flatten` / `_diff` in `tools/generate_strategy_card.py`. **Duplicated inline body, NOT extracted.** | NEW (~80 LOC duplicated) |
| `tools/robustness/runner.py` | **NO CHANGE.** Stays exactly as-is. | READ-ONLY |
| `tools/generate_strategy_card.py` | **NO CHANGE.** Stays exactly as-is. | READ-ONLY |

**Tradeoff:** ~150 LOC temporarily duplicated. Mitigated by:
1. Inline copies are byte-equivalent to source (no semantic drift risk on day 1).
2. Golden-snapshot tests pin the new copies' outputs to the existing reports' outputs.
3. Future extraction is a separate proposal once both consumers are validated independently.

#### 2.2.3 Read-only consumers (no change)

| File | Why touched | Status |
|---|---|---|
| `tools/utils/research/robustness.py` | Family report imports `tail_contribution`, `tail_removal`, `directional_removal`, `early_late_split`, `symbol_isolation` | READ-ONLY |
| `tools/utils/research/rolling.py` | Family report imports `rolling_window`, `classify_stability` | READ-ONLY |
| `tools/utils/research/drawdown.py` | Family report imports `identify_dd_clusters` | READ-ONLY |
| `tools/filter_strategies.py` | Family report calls `_compute_candidate_status` | READ-ONLY |
| `tools/ledger_db.py` | Family report calls `read_master_filter()` | READ-ONLY |
| `governance/namespace/sweep_registry.yaml` | Family report reads for parent-chain inference | READ-ONLY |
| `Strategy_Master_Filter.xlsx` | Headline metrics source | READ-ONLY |
| `TradeScan_State/backtests/<dir>_<sym>/raw/results_tradelevel.csv` | Per-variant trade log | READ-ONLY |
| `TradeScan_State/backtests/<dir>_<sym>/raw/equity_curve.csv` | For rolling/DD analysis | READ-ONLY |

#### 2.2.4 Forbidden imports (Rule 3 enforcement)

The family report MUST NOT import (test asserts this):

- `tools.utils.research.simulators` (Monte Carlo)
- `tools.utils.research.block_bootstrap`
- `tools.robustness.monte_carlo`
- `tools.robustness.bootstrap`
- `tools.robustness.friction`
- `tools.utils.research.friction`

Rationale: hundreds of iterations per variant, not appropriate for family-iteration cadence. These remain in the standalone robustness suite invoked via `python -m tools.robustness.cli`.

### 2.3 Implementation sequence (single working day, wrapper-first)

| Step | Time | Deliverable |
|------|------|-------------|
| 1 | 45min | Create `tools/utils/research/streaks.py` + `tools/utils/research/calendar.py` (duplicated inline copies of runner.py logic, NEW modules). Pin outputs via unit tests against known DataFrames. `runner.py` unchanged. |
| 2 | 45min | Create `tools/report/strategy_signature_utils.py` (duplicated `_flatten` / `_diff` from generate_strategy_card.py). Pin via unit tests. `generate_strategy_card.py` unchanged. |
| 3 | 60min | Build `window_compat.py` + Master Filter reader wrapper. Test cross-window detection on the 6 PSBRK rows. |
| 4 | 60min | Build `family_session_xtab.py`. Test session derivation against known timestamps; cross-tabs against known trade DataFrames. |
| 5 | 60min | Build `family_verdicts.py`. Test verdict outputs against the 6 PSBRK rows — expect to reproduce the family report's §7 verdicts. |
| 6 | 90min | Build `family_renderer.py`: lineage table, comparative-metrics table, attribution sections, verdict block. Render against the 6 PSBRK rows. |
| 7 | 60min | Build `family_report.py` CLI: argparse, orchestrate steps 3-6, write output. Smoke-test: `python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK`. |
| 8 | 60min | Tests: golden-snapshot acceptance against `outputs/family_psbrk_24m_report.md`, forbidden-import guard, **byte-equivalence guard on `robustness/runner.py` and `generate_strategy_card.py` outputs** (asserts existing reports unaffected). |
| **Total** | **~8h / 1 day** | |

### 2.4 Acceptance criteria

1. **Functional**: `python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK` runs without error, writes `outputs/family_reports/65_BRK_XAUUSD_5M_PSBRK_<ts>.md`.
2. **Reproduction**: The generated report's metrics match `outputs/family_psbrk_24m_report.md` (the hand-authored reference) within rounding tolerance.
3. **Refactor invariance**: existing robustness reports and strategy cards byte-equivalent (or differ only in whitespace) after the refactors land.
4. **Forbidden-import test passes**: `pytest tools/tests/test_family_report.py::test_no_forbidden_imports` succeeds.
5. **Golden snapshot test passes**: `pytest tools/tests/test_family_report.py::test_psbrk_golden` succeeds.
6. **Performance**: Family of 10 variants completes in < 3 seconds wall-clock.

### 2.5 Risk analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Inline-duplicated logic in `streaks.py` / `calendar.py` / `strategy_signature_utils.py` drifts from its source over time | MEDIUM | Acknowledged tradeoff for first release (Rule 4). Unit tests pin both implementations against the same inputs. Followup extraction proposal will eliminate the duplication once family report is stable. **Tracking item:** when next touching `tools/robustness/runner.py`, propose extraction as part of that PR. |
| Existing reports affected by Phase B work | HIGH (must not happen) | Byte-equivalence test in Step 8 explicitly verifies `tools/robustness/runner.py` and `tools/generate_strategy_card.py` outputs are unchanged after Phase B lands. CI gate. |
| Session derivation incorrect (boundary off by one hour) | MEDIUM | Unit tests with hand-chosen timestamps at session boundaries (00:00, 07:00, 13:00, 21:00 UTC and 1 minute either side). Use the same hour mapping as `indicators/structure/session_clock.py` (XAU-tuned) AND `indicators/structure/session_clock_universal.py` — family report should derive session from the variant's own indicator import, not assume one. |
| Cross-window guard misclassifies legitimate near-edge variants (e.g., differ by exactly 5 days) | LOW | Make the threshold tunable via CLI flag `--window-tolerance-days N`; default 5d but configurable. |
| Verdict orchestrator's "spirit of gate" overrides disagree with `filter_strategies._compute_candidate_status` (the canonical authority) | LOW | The family report's verdict is **advisory** — clearly marked. Canonical promotion still goes through `filter_strategies.py` write to `candidates/Filtered_Strategies_Passed.xlsx`. |
| Future drift: someone adds an expensive primitive to the family report ignoring Rule 3 | LOW | Forbidden-import guard test prevents this. CI enforces it. |
| Family report runs against a directive whose `results_tradelevel.csv` is malformed or missing | LOW | Per-variant try/except; report a `⚠ missing data` row rather than crashing the whole family report. |

### 2.6 Snapshot & invariant compliance

- **Engine freeze (Invariant 6)**: PRESERVED. No `engines/`, `engine_dev/`, `governance/` modification.
- **Append-only ledgers (Invariant 2)**: PRESERVED. Read-only against Master Filter, MPS, FSP, run_summary.csv, hypothesis_log.json.
- **Snapshot immutability (Invariant 4)**: PRESERVED. Reads `TradeScan_State/runs/<run_id>/strategy.py` but never writes.
- **Indicator separation (Invariant 9)**: PRESERVED. New code is in `tools/`, not `indicators/`.
- **Scratch-script placement (Invariant 8)**: IMPROVED. Replaces the `tmp/` family-analysis-script pattern with a permanent tool.

---

## 3. What's NOT in this plan (intentionally deferred)

The user's prompt explicitly carved these out — they are noted here so the deferred status is visible:

| Deferred | Where it would live |
|---|---|
| Monte Carlo per-variant | Per-strategy robustness report (`python -m tools.robustness.cli <prefix>`) — already exists, unchanged |
| Block bootstrap per-variant | Per-strategy robustness report — already exists, unchanged |
| Friction sensitivity per-variant | Per-strategy robustness report — already exists, unchanged |
| Reverse path test | Per-strategy robustness report — already exists, unchanged |
| Auto-trigger from pipeline | Out of scope. Manual invocation only. |
| Multi-family / portfolio-of-families report | Out of scope. Separate workstream if ever needed. |
| Excel output | Out of scope. Markdown only. |

---

## 4. Review checklist (for user before approving patch)

Before approving Phase B implementation, confirm:

- [ ] Module layout in §2.2 is acceptable (`tools/family_report.py` as CLI; `tools/report/` for renderer/verdicts/session-xtab/signature-utils; `tools/utils/research/streaks.py` and `calendar.py` as new refactored homes).
- [ ] The refactor of `robustness/runner.py` and `generate_strategy_card.py` to import from new locations is acceptable (it touches both files in the same commit; byte-equivalent function bodies).
- [ ] Forbidden-import list (§2.2.4) is correct and complete.
- [ ] Effort estimate (~1 day) is acceptable.
- [ ] Test strategy (§2.4 acceptance criteria) is sufficient.
- [ ] Build order (Phase A before Phase B) is acceptable, OR explicit OK to build Phase B first.

Once approved, the patch sequence is mechanical and matches the 7-step implementation sequence in §2.3.
