# REPORT_UPGRADE_PLAN — Minimal-Change Upgrade Path for Existing Reports

**This is Phase A of the two-phase reporting workstream.** Phase B (new family report) is in [FAMILY_REPORT_DESIGN.md](FAMILY_REPORT_DESIGN.md) + [FAMILY_REPORT_IMPLEMENTATION_PLAN.md](FAMILY_REPORT_IMPLEMENTATION_PLAN.md).

**Scope:** Implementation plan for upgrading the **per-strategy** report (`REPORT_<directive>.md`) and the surrounding markdown surface (STRATEGY_CARD.md, PORTFOLIO_<id>.md). No grand refactors. No engine touch.

**Phase A specific goals (per user post-audit instructions):**
- Verdict block lift (CORE/WATCH/FAIL to top of report)
- Risk surfacing (tail / direction / flat-period flags above raw metrics)
- Parent Δ row (one-line `vs parent: PnL Δ, SQN Δ, DD Δ` in header)
- Remove duplicate sections (the 4 near-identical concentration tables flagged in REPORT_AUDIT §4.1)

**Companion:** [REPORT_AUDIT.md](REPORT_AUDIT.md) for the gap analysis that drives this plan. [FAMILY_REPORT_DESIGN.md](FAMILY_REPORT_DESIGN.md) for Phase B.

**Recommendation in one paragraph:** Do the eight reordering/deletion changes first (Tier 1, all in `tools/report/`), then add the four new computations (Tier 2). Skip every Excel-side change — the engine is frozen at v1.5.8 (Invariant 6). When v1.5.9 ships, fold the Excel deletions into the engine upgrade so they ride a single freeze cycle. The markdown report is the natural home for decision-guidance content because it is unconstrained by engine governance and the natural top-of-funnel artifact the researcher reads first.

---

## 0. What Is Out of Scope

- **Engine modules** (`engine_dev/`, `engines/`) — frozen v1.5.8.
- **Master Filter / Master Portfolio Sheet schemas** — Invariant 2 (append-only ledgers).
- **Stage-1 emitter / `results_*.csv` columns** — engine-owned.
- **Tooling infrastructure** (`tools/run_pipeline.py`, `tools/orchestration/*`, `governance/`) — protected per Invariant 6.
- **Anything proposing rewrites of working code** — we surface, reorder, and delete only.

In scope: `tools/report/*` (markdown section builders) and `tools/generate_strategy_card.py`.

---

## 1. Change Categories

### 1.1 (Tier 1) Reordering — No new compute

| # | What changes | File / line | After-state | Effort | Risk |
|---|---|---|---|---|---|
| 1 | Move "Verdict" to top of report | `tools/report/report_sections/summary.py` `_build_header_section` (after line 33); orchestrator order in `tools/report_generator.py:146` | Header → Verdict block (CORE / WATCH / FAIL / LIVE with rule eval) → Key Metrics. Call `tools/filter_strategies.py:_compute_candidate_status` over a single-row DataFrame built from `risk_data_list[0]` + `standard_metrics`. | S | Low — `_compute_candidate_status` is already a pure function; pass it a one-row DataFrame |
| 2 | Reorder full section list in `report_generator.py:146` | `tools/report_generator.py:146-180` | New order: Header → Verdict → Key Metrics → Direction Split → Symbol Summary → **Risk Characteristics (was 14)** → **Edge Decomposition (was 13)** → **Trade Path Geometry (was 12)** → Exit Analysis → Yearwise → Sessions → Regime-age (collapsed) → Insights → News. Pull the three "structural" sections from positions 12-14 to positions 6-8. | S | Low — pure reorder of `md.extend(...)` calls |
| 3 | Drop K-Ratio from markdown `_build_key_metrics_section` | `tools/report/report_sections/summary.py:51` | Remove one row. Excel Performance Summary K-Ratio row stays. | S | None |
| 4 | Suppress regime-age duplicates | `tools/report/report_sections/session.py` (`_build_fill_age_section`, `_build_exec_delta_section`) | If `fill_age_data == age_data`, suppress fill-age section. If 95%+ of trades share a single exec-delta bucket, suppress exec-delta. | S | Low — both already optional sections; just early-return |
| 5 | Delete standalone Volatility Edge + Trend Edge | `tools/report/report_sections/summary.py:152-169` + `report_generator.py:157-158` | Remove `_build_volatility_edge_section` and `_build_trend_edge_section` calls + functions. The same info lives in Edge Decomposition A and B (Dir × Vol, Dir × Trend) which are richer. | S | Low — verify no tests assert on these two specific tables |
| 6 | Delete `PORTFOLIO_<id>.md` on single-asset | `tools/orchestration/stage_portfolio.py:173` (`generate_strategy_portfolio_report`) + `tools/report/report_strategy_portfolio.py:14` (early return) | Add the same `is_multi_asset` gate already used at `stage_portfolio.py:97`. | S | Low — strategy-portfolio report is non-authoritative; tests should ignore |
| 7 | Delete legacy R-bucket fallback in Exit Analysis | `tools/report/report_sections/risk.py:93-161` (the `else` branch) | Replace ~70-line fallback with a single line: `md.append("> Exit Analysis unavailable: legacy run without exit_source column.")`. | S | Low — `exit_source` has been Stage-1-emitted for all post-v1.5.5 runs; verify no `~old/` archived runs are routinely re-rendered |
| 8 | Hyperlink Strategy Card from REPORT.md header | `tools/report/report_sections/summary.py:14` (header lines) | Add a line: `[Strategy Card](STRATEGY_CARD.md)` in the header block. Crosslink the existing artifact. | S | None |

**Tier 1 total:** ~80-120 LOC removed, ~30-40 LOC added. Zero new external calls. All changes live under `tools/report/` except #6.

### 1.2 (Tier 2) Deletions — Lower-value content removal

| # | What changes | File / line | After-state | Effort | Risk |
|---|---|---|---|---|---|
| 9 | Drop `_DIRECTIVE_SUBDIRS` `INBOX` lookup latency in Strategy Card | `tools/generate_strategy_card.py:199` | Already small; keep — flag only if profiling shows it as hotspot. | S | None |
| 10 | Compact MFE Giveback / Immediate Adverse to a single "Capture Quality" subsection | `tools/report/report_sections/risk.py:65-79` | Move both lines under a `### Capture Quality` heading, alongside the values already shown in `_build_path_geometry_section`. Avoids same metric appearing twice in the rendered report. | S | None |

### 1.3 (Deferred — engine-frozen) AK_Trade_Report Excel deletions

These four are in `engine_dev/.../v1_5_8/stage2_compiler.py` and **cannot** be edited under Invariant 6 / freeze. Document them as v1.5.9 candidates:

| # | What changes (eventual) | Owner | Defer until |
|---|---|---|---|
| D1 | Delete `Settings` sheet (`stage2_compiler.py:347`) | engine | v1.5.9 |
| D2 | Delete `Benchmark Analysis` sheet (`stage2_compiler.py:494`) | engine | v1.5.9 |
| D3 | Delete "Avg Bars in Winning/Losing" rows in Performance Summary (`stage2_compiler.py:457-459`) | engine | v1.5.9 |
| D4 | Delete K-Ratio row in Excel Performance Summary | engine | v1.5.9 (only after Tier 1.3 lands) |

For now: nothing changes in AK Excel.

### 1.4 (Tier 3) Cross-references between existing artifacts

| # | What changes | File | After-state | Effort | Risk |
|---|---|---|---|---|---|
| 11 | Link `REPORT.md` → `STRATEGY_CARD.md` → `AK_Trade_Report_*.xlsx` | `tools/report/report_sections/summary.py:14`, `tools/generate_strategy_card.py:496` | Each artifact's header carries a one-line "Other artifacts" section linking to its siblings. Researcher reading any one finds the others in one click. | S | None |
| 12 | When a directive sits in a `sweep_registry.yaml` chain, render a "Lineage" link to `[Family Report — 65_BRK_XAUUSD_5M_PSBRK](../FAMILY_*.md)` if the family report exists at the expected path | `tools/report/report_sections/summary.py:14` | Header gets one extra line when applicable. If the family file doesn't exist yet, no link. | S | None |

### 1.5 (Tier 4) New computation in existing files

| # | What changes | File | After-state | Effort | Risk |
|---|---|---|---|---|---|
| 13 | Add `[carries]` / `[leaks]` cell flags to Edge Decomposition | `tools/report/report_sections/risk.py:166` (`_build_edge_decomposition_section`) + `tools/report/report_sessions.py` (`_build_cross_tab`) | Each cell rendered as `N=171 PnL=$1,301 WR=41% PF=1.74 [carries]` when PnL ≥ $400 and N ≥ 50; `[leaks]` when PnL ≤ −$50 and N ≥ 30. Thresholds configurable; defaults match what the family report used. | M | Low — `_build_cross_tab` returns lines; modify formatter only |
| 14 | Add Tail Concentration mini-block (Top-5/10/20 + body-after-Top-20) | `tools/report/report_sections/risk.py:192` (extend `_build_risk_characteristics_section`) | Three new rows: `Top-10 / Top-20 Trade Concentration / Body PnL after Top-20 Removal`. ~15 LOC over the existing risk df. | M | Low |
| 15 | Add Yearwise inline flags | `tools/report/report_sections/summary.py:117` (`_build_yearwise_section`) | After each year row, append `(<60%)` / `(>60%)` / `(partial year — Jan-MM)` / `(negative)`. Tag "partial year" when row's year matches `datetime.today().year` and trade range doesn't span Jan-Dec. | M | None |
| 16 | Add "Δ vs previous pass" subsection in Key Metrics | `tools/report/report_sections/summary.py:36` (`_build_key_metrics_section`) | After the main metric table, append a subsection showing Δ for PF, SQN, Sharpe, DD%, Net PnL, Top-5%, Direction balance vs the previous pass (parsed via `_parse_name` in `generate_strategy_card.py`). Reads prior pass's `results_standard.csv`/`results_risk.csv` from `BACKTESTS_DIR` (same source the existing report uses). If no previous pass exists, render nothing. | M | Low — read-only; gate behind `prior_run_folder.exists()` |

**Tier 4 total:** ~100-150 LOC across 4 functions; one new helper for tail-concentration; one new helper for delta read.

---

## 2. Implementation Sequence

Strict order — each step is independently shippable:

### Step A (one PR): Tier 1.1 changes #1–8 — pure reorder/delete
- Acceptance: every existing `REPORT_*.md` in `TradeScan_State/backtests/` can be regenerated with `python tools/rebuild_all_reports.py` (already exists) and the diff is purely additive (verdict block added at top) + deletions of the deleted sections.
- Verification: regenerate one report (e.g. P14), eyeball, compare against the existing one. No new sections appear that don't have a builder.
- Tests: existing `tests/test_*report*.py` should keep passing. Update test assertions for `_build_volatility_edge_section`/`_build_trend_edge_section` to expect them removed.

### Step B (one PR): Tier 1.4 cross-references #11–12 — link wiring
- Acceptance: a regenerated report has a Lineage block when the parent family file exists; no-op when it doesn't.
- Tests: trivial — one assertion per builder.

### Step C (one PR): Tier 4 new computation #13 — `[carries]/[leaks]` flags
- Acceptance: P14 report's Edge Decomposition reads as in the family report's §4.1: `Long | N=167 PnL=$1,155 WR=49.7% PF=1.45 [carries]`.
- Tests: add a unit test for `_build_cross_tab` with a known-input dataframe and assert flag presence.

### Step D (one PR): Tier 4 #14 — Tail Concentration block
- Acceptance: Risk Characteristics now shows 4 lines (Top-5 / Top-10 / Top-20 / Body-PnL-after-Top-20). P14: Top-5=36.5%, Top-10=62.6%, Top-20=104.8%, Body=-$136.
- Tests: unit test against a known csv fixture.

### Step E (one PR): Tier 4 #15 — Yearwise flags + Tier 1.2 #10 Capture-Quality
- Acceptance: yearwise table flags partial-year correctly; MFE giveback shown only once.

### Step F (one PR): Tier 4 #16 — Δ vs previous pass
- Acceptance: P14 report shows a Δ block referencing P13's prior metrics (and a "no prior pass" notice if P00).
- Risk: If the previous pass folder is missing or has incompatible date range, silently skip — never raise.

After F lands, the per-strategy report carries every section the family report does (per strategy), the Family Report becomes a pure aggregation rather than a re-implementation, and `tmp/` scripts can be deleted.

---

## 3. Risk Per Tier

### State-machine impact
None. The markdown report is non-authoritative — `stage_portfolio.py:176-181` already swallows report-generation exceptions with `print(f"[ERROR] REPORT_GENERATION_FAILURE: {rep_err}")` and a `WARN` log; directive state is unaffected on report failure. All Tier 1-4 changes inherit this safety.

### Engine impact
None. Tier 1.3 (the four AK Excel deletions) would touch engine code and is explicitly deferred to v1.5.9. Nothing in Tiers 1.1, 1.2, 1.4, 2, 3, 4 modifies engine code, `engines/`, `engine_dev/`, or anything Stage-2 generates.

### Snapshot-immutability impact
None. `TradeScan_State/runs/<RUN_ID>/strategy.py` is unread by this plan. The markdown report builders read Stage-1 `raw/*.csv` (immutable engine output) and metadata only.

### Master Filter / MPS schema impact
Zero. The plan does not write to either ledger.

### Append-only ledger impact
Zero — same reason.

### State-folder writes
- Each rebuild overwrites `REPORT_<directive>.md` and `STRATEGY_CARD.md` in `TradeScan_State/backtests/<dir>_<sym>/`. This is already the behaviour today.

### Forward-compat
All new fields/sections are additive. Removing PORTFOLIO_<id>.md on single-asset (#6) is the only behavioural removal. Downstream consumers of that file: search `grep -r "PORTFOLIO_.*\.md" tools/ tests/` showed no programmatic consumer. Safe to delete on single-asset.

---

## 4. Test Coverage Strategy

### Per-builder unit tests (Step C-F)
Each new function (`_compute_tail_concentration`, `_format_carries_leaks`, `_read_prior_pass_metrics`, `_yearwise_flag`) gets a dedicated unit test under `tools/tests/test_report_sections.py`. Inputs are small DataFrame fixtures (10-30 rows). Use existing test data from `tools/tests/fixtures/` if present; otherwise inline 5-10 row fixtures.

### Integration tests
Existing report-generator tests (`tests/test_report_generator.py` if present, `tools/tests/test_*.py` otherwise) re-run on the P14 sample. Snapshot the new report; check for:
- Verdict block present at top
- `[carries]/[leaks]` flags appear at the expected thresholds
- Tail Concentration row count
- Yearwise flags match the regenerated row

### Smoke check
After Step A: regenerate every existing report with `python tools/regenerate_all_reports.py`. Spot-check 3 disparate strategies (one XAU 5M, one FX 1H, one IDX 1D). The reorder is correct iff the verdict appears in the first 20 lines.

### Pre-commit hooks
- `tools/lint_encoding.py` already enforces utf-8. New files inherit.
- `tools/lint_no_hardcoded_paths.py` should be re-run after Tier 4 (which reads `BACKTESTS_DIR` — already comes from `config.state_paths`).

### Regression bake
Run the existing pre-promote validator and dry-run validator on P14 after Step A. Both should pass byte-equivalent on Stage-1 / Stage-2 / Stage-3 / Stage-4 outputs — those are engine-side; this plan only touches the report layer.

---

## 5. Effort & Sequencing Summary

| Step | Tier | Items | LOC | Effort | Independent shippable? |
|---|---|---|---|---|---|
| A | 1.1 | #1-8 | ~−100 / +35 | S | Yes |
| B | 1.4 | #11-12 | +20 | S | Yes |
| C | 4 | #13 | +30 | M | Yes |
| D | 4 | #14 | +25 | M | Yes |
| E | 4 + 1.2 | #15, #10 | +40 | M | Yes |
| F | 4 | #16 | +50 | M | Yes |
| Total | — | — | ~+200 / −100 | — | — |

Effort scale: S = ≤2h, M = 2-6h, L = 6h+. Total: 5-7 hours work distributed across 6 small PRs.

---

## 6. What This Plan Does Not Solve

- **Family comparisons** — covered by FAMILY_REPORT_DESIGN.md.
- **Excel-side cleanup (Settings, Benchmark, Avg-Bars-Win/Loss, R-bucket fallback in Stage-1 alternate path)** — deferred to engine v1.5.9.
- **Cross-window comparability** — needs a new helper consumed by both the Family Report and `filter_strategies`. Cleanest home: a new `tools/window_compat.py` module called from both. Out of scope for this plan; flagged for the Family Report PR (where it is needed first).
- **Robustness preview in per-strategy report** — deferred. Either auto-invoke `robustness/cli --suite quick` (5-15s/run cost) or lift the two highest-value sections (Tail Removal, Block-MC) into the per-strategy report. Decision deferred until the Tier-4 tail block is in place; that block already covers ~50% of what Robustness reports show.

---

## 7. One-Paragraph Rationale (per user spec)

> The minimal-change path is to make the markdown report carry the verdict and the structural interpretation that already exist elsewhere (Excel Notes sheet, family report, candidate filter) — not to add more compute. Six small PRs (A-F above) deliver decision-grade reports without touching the frozen engine, without modifying append-only ledgers, and without introducing a new pipeline phase. The Family Report (separate design) handles cross-strategy aggregation; the per-strategy report should be optimised for "is this one deployable, and what changed?" — which is exactly what these eight changes target.