# REPORT_AUDIT — Trade_Scan Reporting Stack (Part 1)

**Scope:** Inventory + gap-analysis of every reporting artifact the pipeline produces today, mapped against the 10 known pain points. Inspection only — remediation lives in REPORT_UPGRADE_PLAN.md and FAMILY_REPORT_DESIGN.md.

**Method:** Followed orchestration calls outward from `tools/run_pipeline.py` → `tools/orchestration/stage_*.py` → individual section builders. Read the per-strategy report sample at `TradeScan_State/backtests/65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14_XAUUSD/REPORT_*.md`, the matching strategy card, and the one-off `outputs/family_psbrk_24m_report.md`.

---

## 1. Current Reporting Structure

### 1.1 Per-run artifacts (one set per directive × symbol)

| Stage | Artifact | Produced by | Destination |
|---|---|---|---|
| 1 | `raw/results_tradelevel.csv` | `tools/run_stage1.py` (engine) | `TradeScan_State/backtests/<dir>_<sym>/raw/` |
| 1 | `raw/results_standard.csv` | engine | same |
| 1 | `raw/results_risk.csv` | engine | same |
| 1 | `raw/results_yearwise.csv` | engine | same |
| 1 | `raw/results_partial_legs.csv` | engine (partial-capable only) | same |
| 1 | `raw/equity_curve.csv` | engine | same |
| 1 | `raw/bar_geometry.json` | engine | same |
| 1 | `raw/metrics_glossary.csv` | engine | same |
| 1 | `metadata/run_metadata.json` | engine | same |
| 1.x | `STRATEGY_CARD.md` | `tools/generate_strategy_card.py:376` | same |
| 1.x | `REPORT_<directive>.md` | `tools/report_generator.py:107` via `_write_markdown_reports` in `tools/report/report_writer.py:10` | same |
| 2 | `AK_Trade_Report_<strategy>.xlsx` | `engine_dev/.../v1_5_8/stage2_compiler.py:888` | same |

### 1.2 Ledgers (append-only, system-wide)

| Artifact | Produced by | Destination | Schema |
|---|---|---|---|
| `Strategy_Master_Filter.xlsx` | `tools/stage3_compiler.py:34` | `TradeScan_State/sandbox/` | 39 columns: SQN, PF, expectancy, Sharpe, dd_pct, R/DD, vol+session+trend breakdowns |
| `Master_Portfolio_Sheet.xlsx` | `tools/portfolio/portfolio_ledger_writer.py:40` | `Trade_Scan/strategies/` | Two sheets: `Portfolios` (multi-asset) and `Single-Asset Composites` |
| `Filtered_Strategies_Passed.xlsx` | `tools/filter_strategies.py:67` `_compute_candidate_status` | `TradeScan_State/candidates/` | Status (CORE/WATCH/RESERVE/FAIL/LIVE) + asset-class expectancy gates |
| `run_summary.csv` | `tools/generate_run_summary.py` | `TradeScan_State/research/` | One row per run_id |
| `hypothesis_log.json` | `tools/backfill_hypothesis_log.py` + `tools/hypothesis_tester.py` | `TradeScan_State/` | ACCEPT/REJECT verdicts |
| `run_registry.json` | various | `TradeScan_State/registry/` | directive_id, run_id, status, timestamps |

### 1.3 Strategy-folder artifacts (per strategy)

| Artifact | Produced by | Destination |
|---|---|---|
| `portfolio_evaluation/portfolio_summary.json` | `tools/portfolio_evaluator.py` | `TradeScan_State/strategies/<id>/portfolio_evaluation/` |
| `portfolio_evaluation/portfolio_metadata.json` | same | same |
| `portfolio_evaluation/*.png` | `portfolio_charts.py` | same |
| `PORTFOLIO_<id>.md` | `tools/report/report_strategy_portfolio.py:14` | `TradeScan_State/strategies/<id>/` |
| `deployable/<PROFILE>/summary_metrics.json` | `tools/capital_wrapper.py` | `TradeScan_State/strategies/<id>/deployable/<PROFILE>/` |
| `deployable/<PROFILE>/equity_curve.png` | capital_wrapper | same |
| `deployable/<PROFILE>/deployable_trade_log.csv` | capital_wrapper | same |
| `deployable/profile_comparison.json` | `tools/profile_selector.py` | `TradeScan_State/strategies/<id>/deployable/` |
| `ROBUSTNESS_<id>_<profile>.md` | `tools/robustness/cli.py:67` via `tools/robustness/formatter.py` | `TradeScan_State/strategies/<id>/` |

### 1.4 Idea Evaluation Gate (Stage −0.20)

Source: `tools/idea_evaluation_gate.py:89`. Verdicts: `NEW`, `REPEAT_PROMISING`, `REPEAT_FAILED`. Reads `run_summary.csv`, `hypothesis_log.json`, `RESEARCH_MEMORY.md`. Stdout only — no markdown written.

### 1.5 Order of artifact production per directive

```
admission gate (idea-evaluation, namespace, sweep registry)
  → Stage-1   raw/*.csv, metadata/, STRATEGY_CARD.md
  → Stage-2   AK_Trade_Report_<strategy>.xlsx (incl. Notes sheet)
  → Stage-3   append rows to Strategy_Master_Filter.xlsx
  → Stage-4   strategies/<id>/portfolio_evaluation/* + PORTFOLIO_<id>.md
              append row to Master_Portfolio_Sheet.xlsx
              generate_backtest_report → REPORT_<directive>.md
  → Step 8    capital_wrapper → deployable/<PROFILE>/*
  → Step 8.5  profile_selector → deployable/profile_comparison.json
  → Step 9    filter_strategies → Filtered_Strategies_Passed.xlsx + hyperlinks
  → Step 10   generate_run_summary.py → run_summary.csv
```

Robustness is NOT in this chain — only via `promote` skill or manual `python -m tools.robustness.cli <prefix>`.

---

## 2. Pain Points Mapped to Current State

Cost class legend:
- **REPOSITION** = exists; needs surfacing
- **NEW_COMPUTE_CHEAP** = derivable from existing data; small new module
- **NEW_COMPUTE_HEAVY** = needs multi-run aggregation or new state
- **DELETION** = remove noise

### 2.1 Family comparisons fragmented across Excel + reports + memory
**State:** No family-level artifact exists. `family_psbrk_24m_report.md` was hand-built from a `tmp/` script. Per-strategy REPORT_*.md covers a single directive; Master Filter mixes families. Closest primitive is the `idea` token in directive names (`65_BRK_..._S01_V4_P14`).
**Cost:** **NEW_COMPUTE_CHEAP**. All inputs exist (Stage-1 CSVs, Master Filter, sweep_registry). Aggregation layer only.

### 2.2 No simple lineage view (P00 → P01 → ...)
**State:** Partially solved at single-step level: STRATEGY_CARD.md shows P(n) → P(n−1) signature diff (`generate_strategy_card.py:425`). Multi-step lineage absent. `sweep_registry.yaml` carries the chain but is YAML.
**Cost:** **NEW_COMPUTE_CHEAP**. Walk pass numbers + read each pass's strategy.py.

### 2.3 No automatic delta vs previous backtest section
**State:** Strategy Card shows config delta. Performance-metric delta vs prior pass is nowhere in the report.
**Cost:** **NEW_COMPUTE_CHEAP**. Read prior `results_standard.csv`/`results_risk.csv` from BACKTESTS_DIR.

### 2.4 Concentration risk / session / direction / regime bleed cells buried
**State:**
- Top-5 concentration: present at `report_sections/risk.py:233`, near bottom of report.
- Top-10/20 + body-PnL-after-Top-N: NOT computed anywhere; family report did it manually.
- Session %-share (vs raw PnL): missing; family report hand-computed.
- Direction asymmetry rule: in `report_insights.py:67` but only fires when PF ratio ≥1.5 (high threshold).
- Regime bleed cells: Edge Decomposition cross-tab exists at `risk.py:166` but no `[carries]`/`[leaks]` flags.
**Cost:** **REPOSITION** (move Risk Characteristics up, add flags) + **NEW_COMPUTE_CHEAP** (Top-10/20, %-share).

### 2.5 Metrics but no decision guidance
**State:** Notes sheet in AK Excel (`stage2_compiler.py:625` `_add_notes_sheet`) is the ONLY place with CORE/WATCH/FAIL verdict + gate-by-gate evaluation. Markdown report has only "Actionable Insights" (mechanical bullets, no go/no-go).
**Cost:** **REPOSITION**. Lift the verdict logic (already duplicated in `filter_strategies._compute_candidate_status`) into the markdown header.

### 2.6 No "why did this variant improve/regress?" attribution
**State:** Missing. Family report did this manually (Mutation Attribution §6). Per-strategy report ends at Insights with no causal narrative.
**Cost:** **NEW_COMPUTE_CHEAP** (bounded Δ table) + **HEAVY** (free-text causal — leave to researcher).

### 2.7 Cross-window comparisons cause false conclusions
**State:** Master Filter has `test_start`/`test_end` columns; no tool flags mismatched windows. The 2024-05-11 standardization incident was caught by hand.
**Cost:** **NEW_COMPUTE_CHEAP**. 10-line tolerance check.
**Resolution (2026-05-12):** the comparability policy now has two
contexts with deliberately different rules: cross-strategy comparisons
suppress on mismatch (`tools/window_compat.py`) while same-strategy
comparisons show with an inline drift annotation
(`tools/report/prior_run_delta.py`). Full table in
`outputs/FAMILY_REPORT_DESIGN.md §2 → "Comparison-policy by direction"`.

### 2.8 Report ordering favors raw metrics before structural interpretation
**State:** Current order (from `report_generator.py:146`):
1. Header 2. Key Metrics 3. Direction Split 4. Symbol Summary 5. Yearwise 6. Vol Edge 7. Trend Edge 8. **4 sequential regime-age sections** 9. Session 10. Weekday 11. Exit Analysis 12. Trade Path Geometry 13. Edge Decomposition 14. **Risk Characteristics** 15. News 16. **Actionable Insights** (last).
Structural interpretation is at the bottom of a ~270-line file.
**Cost:** **REPOSITION**.

### 2.9 Robustness only at end-of-deployment
**State:** Confirmed — `tools/robustness/cli.py` invoked from `promote` skill or manually. Not in pipeline.
**Cost:** **REPOSITION** (auto-invoke `--suite quick` after Stage-4) or **NEW_COMPUTE_CHEAP** (lift Tail Removal + Block-MC sections into per-strategy REPORT_*.md).

### 2.10 Temporary scripts produce unsurfaced insights
**State:** Direct evidence: `outputs/family_psbrk_24m_report.md` was built from `tmp/psbrk_24m_analysis.py`. `tmp/` currently contains 70+ Python scripts (convexity_P04_analyze.py, news_edge_discovery.py, concurrency_sweep.py, diff_sl_sweep.py, etc.). Insights re-enter only as memory entries.
**Cost:** **STRUCTURAL** — needs a target home (the Family Report).

---

## 3. High-Value Sections (Keep / Surface Better)

1. **Direction Split** (`summary.py:70`) — 3 lines, immediately answers "is there an imbalance?". Keep above the fold.
2. **Symbol Summary with S3 ✔ marker** (`summary.py:97`). Keep.
3. **Yearwise table** (`summary.py:117`) — stability signal. Keep, add flags.
4. **Edge Decomposition cross-tabs** (`risk.py:166`) — A/B/C tables. Keep, add `[carries]/[leaks]`.
5. **Trade Path Geometry archetypes** (`path_geometry.py:25`) — 6 archetypes (Fast-Expand / Recover-Win / Profit-Giveback / Stall-Decay / Immediate-Adverse / Time-Flat). Unique signal not duplicated anywhere. Currently buried — move up.
6. **MFE Giveback + Immediate Adverse %** (`risk.py:65-79`) — highest decision density per character. Keep.
7. **Actionable Insights** (`report_insights.py:268`) — when it fires, only natural-language guidance. Move up.
8. **Notes-sheet verdict in AK Excel** (`stage2_compiler.py:625`) — strongest gate-by-gate surface. Duplicate into markdown header.

---

## 4. Low-Value / Noise Sections — Delete Candidates

### 4.1 Four near-identical regime/age sections
- `Regime Lifecycle (Age)`, `Regime Lifecycle (Fill Age — HTF Granularity)`, `HTF Transition Distribution`, `Exec-TF Age Delta — v1.5.6 Probe`.
- In P14 sample: three of four tables have the same trade-count distribution. Exec-TF reports 99.6% in one bucket.
**Recommendation:** **DELETE** fill-age when ==regime-age (auto-suppress); DELETE exec-TF probe when ≥95% in one bucket.

### 4.2 Yearwise table with no flags
**Recommendation:** KEEP but add `(<60% of net)` / `(partial year)` / `(negative)` flags.

### 4.3 Standalone Volatility Edge / Trend Edge (`summary.py:152-169`)
Fully subsumed by Edge Decomposition A (Dir×Vol) and B (Dir×Trend). Standalone tables show all-direction sums that mislead when direction asymmetry exists.
**Recommendation:** **DELETE**. Cuts ~10 lines per report.

### 4.4 Settings sheet in AK_Trade_Report (`stage2_compiler.py:347`)
13 rows duplicating run_metadata.json and STRATEGY_CARD.md header. Drift surface — has a "STRICT" version check at `:354` that exists *because* drift happened.
**Recommendation:** **DELETE** if engine ever opens; engine is frozen → use Plan A §1.3 (markdown-side handling).

### 4.5 Benchmark Analysis sheet (`stage2_compiler.py:494`)
Buy & Hold first/last price for an intraday breakout strategy. Misleading at best. No memory entry references "buy_hold" or `relative_perf` as a decision criterion.
**Recommendation:** **DELETE** at next engine version; engine is frozen → no action now.

### 4.6 Weekday breakdown — opt-in flag only
**Recommendation:** KEEP behaviour unchanged.

### 4.7 Avg-Bars-Win / Avg-Bars-Loss in Performance Summary (`stage2_compiler.py:457-459`)
Subsumed by Exit Analysis "Avg Bars to Exit" by exit_source.
**Recommendation:** **DELETE** at next engine version; engine is frozen → no action now.

### 4.8 K-Ratio in two places, both unread
Markdown header (`summary.py:51`) and Excel Performance Summary (`stage2_compiler.py:454`). No memory entry uses K-Ratio. Family report didn't cite it.
**Recommendation:** **DEMOTE** — drop from markdown header; keep in Excel (frozen engine).

### 4.9 R-bucket fallback path in Exit Analysis (`risk.py:93-161`, ~70 lines)
Fires only on archived legacy data without `exit_source`. Drift risk.
**Recommendation:** **DELETE** the fallback; print "Exit Analysis unavailable (legacy run)" instead.

### 4.10 PORTFOLIO_<id>.md on single-asset strategies (`report_strategy_portfolio.py:14`)
Generated unconditionally even when `stage_portfolio.py:97` already gates the *evaluator* on `is_multi_asset`. For single-asset strategies the file duplicates per-strategy REPORT.md with no added information.
**Recommendation:** **DELETE** for single-asset; keep for multi-asset/composite.

---

## 5. Family-Report Insights to Promote as Permanent Sections

| Family-report section | Inputs available | Promote to |
|---|---|---|
| §1 Executive Ranking | Master Filter rows | Family Report core |
| §2 Core Metrics Table | Master Filter rows | Family Report core |
| §3.1 Year split %-of-net + dominance flag | `results_yearwise.csv` | Family + per-strategy (flagged) |
| §3.2 Top-5 / Worst-5 / Streak / Flat-period | `results_tradelevel.csv` | Family Report core |
| §3.3 Session %-share | `results_tradelevel.csv` | Family + per-strategy (replace raw-PnL session table) |
| §3.4 Direction concentration % | `results_tradelevel.csv` | Family Report core |
| §4 Edge Decomp with `[carries]/[leaks]` | per-strategy report; add flags | Per-strategy (Plan A) |
| §5 Tail Dependency (Top-5/10/20 %, body-after-Top-20) | `results_tradelevel.csv` | Family + per-strategy (one line) |
| §6 Mutation Attribution Δ table | parent + current strategy.py | Family Report core |
| §7 Deployment Verdict | `_compute_candidate_status` | Family Report core (per-variant) |

---

## 6. Quick Wins (Reordering / Relabelling — No New Compute)

Ordered by impact ÷ effort.

1. **Move Notes-sheet verdict to top of `REPORT_*.md`** — call `filter_strategies._compute_candidate_status` from `_build_header_section`. Biggest decision-speed win.
2. **Reorder sections in `report_generator.py:146`** — Header → Verdict → Key Metrics → Direction Split → Risk Characteristics (concentration, flat period) → Edge Decomposition → Trade Path Geometry → Exit Analysis → Yearwise → Sessions → Regime-age (collapsed) → Insights → News.
3. **Suppress duplicate Regime-Age sections** when fill-age == signal-age or exec-delta ≥95% in one bucket.
4. **Annotate Yearwise rows** with `(<60%)`, `(partial year)`, `(negative)` flags.
5. **Annotate Edge Decomposition cells** with `[carries]` / `[leaks]` (PnL ≥ $400 & N ≥ 50, or PnL ≤ −$50 & N ≥ 30).
6. **Delete `PORTFOLIO_<id>.md` for single-asset** in `stage_portfolio.py:173`.
7. **Delete standalone Volatility Edge + Trend Edge sections**.
8. **Drop K-Ratio from markdown `_build_key_metrics_section`** (keep Excel row).

Excel-side deletions (Settings, Benchmark, Avg-Bars-Win/Loss, R-bucket fallback) require engine change — engine is frozen v1.5.8. Deferred to engine v1.5.9+.

---

## 7. Structural Redesign Opportunities (New Compute)

1. **Family Report module** — separate command, designed in FAMILY_REPORT_DESIGN.md.
2. **Cross-window comparability check** — warn when row's `test_start`/`test_end` deviates from family standard. Consumed by Family Report + `filter_strategies.py`.
3. **Top-10/20 + body-after-Top-N** — ~15 lines over `results_tradelevel.csv`. Per-strategy (one line) + Family (table).
4. **Pass-to-pass metric delta block** — read prior pass's CSVs. Per-strategy subsection + Family lineage column.
5. **Robustness pre-check in per-strategy report** — Tail Removal + Regime-Aware Block Bootstrap MC from `results_tradelevel.csv`. Or auto-invoke `robustness/cli --suite quick`.

---

## 8. Module → Output Glossary

| Output | Module | Function |
|---|---|---|
| `REPORT_<directive>.md` | `tools/report_generator.py:107` | `generate_backtest_report` |
| Section builders | `tools/report/report_sections/*` | `_build_*_section` |
| `STRATEGY_CARD.md` | `tools/generate_strategy_card.py:376` | `generate_strategy_card` |
| `AK_Trade_Report_*.xlsx` | `engine_dev/.../v1_5_8/stage2_compiler.py:841` | `generate_excel_report` |
| `Strategy_Master_Filter.xlsx` | `tools/stage3_compiler.py:34` | top-level |
| `Master_Portfolio_Sheet.xlsx` | `tools/portfolio/portfolio_ledger_writer.py:399` | `_serialize_ledger_row` + `_append_ledger_row` |
| `Filtered_Strategies_Passed.xlsx` | `tools/filter_strategies.py:67` | `_compute_candidate_status` |
| `run_summary.csv` | `tools/generate_run_summary.py` | top-level |
| `hypothesis_log.json` | `tools/backfill_hypothesis_log.py` + `tools/hypothesis_tester.py` | top-level |
| `ROBUSTNESS_*.md` | `tools/robustness/cli.py:31` | `main` |
| `PORTFOLIO_<id>.md` | `tools/report/report_strategy_portfolio.py:14` | `generate_strategy_portfolio_report` |
| Notes sheet (verdict) | `engine_dev/.../v1_5_8/stage2_compiler.py:625` | `_add_notes_sheet` |
| Idea Evaluation Gate | `tools/idea_evaluation_gate.py:89` | `evaluate_idea` |

---

## 9. Summary

- **No fully-missing primitive.** All inputs exist in `results_tradelevel.csv`, `Strategy_Master_Filter.xlsx`, `STRATEGY_CARD.md`, `sweep_registry.yaml`. Deficit is **aggregation + ordering + decision-guidance**.
- **Cheap wins are large.** Five of eight quick wins are pure reordering / `if`-guards. Removes ~50 lines per report; brings verdict from row 270 to row 5.
- **Family Report is the structural fix** for pain points #1 and #10 simultaneously.
- **One blind spot: cross-window comparability.** Needs a comparator function — small but new.
- **Engine is frozen.** AK_Trade_Report deletions (Settings, Benchmark, Avg-Bars-Win/Loss, R-bucket) are deferred. Markdown-layer improvements are not blocked.