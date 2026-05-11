# FAMILY_REPORT_DESIGN — Implementation Plan for a New Family Analysis Report

**Scope:** Design for a NEW family-level markdown report — separate from per-strategy `REPORT_<directive>.md`, not replacing it. Answers questions today's reporting cannot: lineage across passes, parent→child mutation attribution, cross-variant comparative metrics, per-variant deployment verdict.

**Companion:** [REPORT_AUDIT.md](REPORT_AUDIT.md) for the gap analysis. [REPORT_UPGRADE_PLAN.md](REPORT_UPGRADE_PLAN.md) for the per-strategy report upgrade (separate workstream, but shares helpers with this report).

**Recommendation in one paragraph:** Build it as `tools/family_report.py <directive-prefix>` — on-demand, manually invoked. Reads `Strategy_Master_Filter.xlsx` for headline metrics, `results_tradelevel.csv` per variant for tail/concentration/session analysis, and `governance/namespace/sweep_registry.yaml` for lineage. Writes a single markdown to `outputs/family_reports/<prefix>_<timestamp>.md`. No state mutation, no engine touch, no schema change. Estimated build: 1-2 days for the core (lineage table + comparative metrics + tail concentration + per-variant verdict); add 1-2 more days for mutation attribution and the visual lineage tree. The blocker for auto-triggering is that families form at variable cadence (researcher decision), not at a deterministic pipeline boundary. Manual invocation matches how `family_psbrk_24m_report.md` was actually used.

---

## 0. Goals and Non-goals

### Goals
1. Answer the four questions today's reporting cannot:
   - **Lineage**: P00 → ... → P(n) chain visible at a glance.
   - **Comparative metrics**: side-by-side metric table for every variant in the family.
   - **Structural attribution**: concentration / tail / session / direction / regime / yearwise stability per variant.
   - **Per-variant verdict**: Reject / Investigate / Watch / Candidate / Promote with explicit rationale.
2. Absorb the recurring `tmp/` scripts (pain point #10 in audit). After this lands, `tmp/psbrk_24m_analysis.py`, `convexity_P04_analyze.py`, `concurrency_sweep.py` and similar one-off attribution scripts become obsolete.
3. Provide a stable, regeneratable artifact that researchers cite in `RESEARCH_MEMORY.md` (replaces ad-hoc memory entries pointing at hand-built files).

### Non-goals
1. Do not replace `REPORT_<directive>.md`. The per-strategy report stays.
2. Do not write into Master Filter / MPS / sweep_registry.
3. Do not modify `TradeScan_State/runs/<run_id>/strategy.py` snapshots — read-only.
4. Do not auto-trigger from the pipeline (see §3 trigger decision).
5. Do not build duplicate analytics — every structural metric must reuse an existing primitive from `tools/utils/research/` or `tools/robustness/`. New code is limited to: **session derivation**, **lineage aggregation**, and the **variant comparison renderer** (per post-audit Rule 2).
6. Do not invoke expensive robustness components from the family report. **Allowed primitives** (cheap, deterministic, milliseconds per variant): `tail_contribution`, `tail_removal`, `directional_removal`, `early_late_split`, `rolling_window` / `classify_stability`, `identify_dd_clusters`, `streaks` helper, `analyze_monthly` / `analyze_weekday`. **Forbidden** (hundreds of iterations per variant, family-iteration too slow): `run_regime_block_mc`, `run_block_bootstrap`, `run_friction_scenarios`, `run_reverse_path_test`, `simulate_percent_path` (full Monte Carlo). The forbidden set remains in the per-strategy robustness report invoked separately via `python -m tools.robustness.cli`.

---

## 1. Question A — Lineage

### What to render

A markdown lineage table for the family. Each row is one variant, columns capture the diff against the previous variant.

```markdown
## Lineage

| Pass | Strategy ID | Entry Logic | Exit Logic | Filters | Window | Engine | Δ vs parent |
|------|-------------|-------------|------------|---------|--------|--------|-------------|
| P00 | 65_BRK_..._S01_V4_P00 | session-break | utc_day_close | none | 24m | 1.5.8 | initial |
| P09 | 65_BRK_..._S01_V4_P09 | session-break | utc_day_close + lock@+1R | none | 24m | 1.5.8 | +lock |
| P14 | 65_BRK_..._S01_V4_P14 | session-break | utc_day_close + lock@+1R | armed-once-per-session | 24m | 1.5.8 | +session-arm-once |
| P15 | 65_BRK_..._S01_V4_P15 | session-break | BE@+2R | armed-once-per-session | 24m | 1.5.8 | lock→BE |
```

Plus optional ASCII lineage tree:

```
P00 (root)
 ├─ P09 (+lock@+1R)
 │   ├─ P14 (+armed-once-per-session)  ← current leader
 │   └─ P15 (lock@+1R → BE@+2R)
 └─ ... (S02, S03 are siblings on a different sweep base)
```

### Where the data comes from

| Field | Source |
|---|---|
| Pass number, sweep, variant | parsed from directive name via `tools/generate_strategy_card.py:49` `_parse_name` |
| Entry Logic / Exit Logic / Filters / Window | `STRATEGY_SIGNATURE` in `Trade_Scan/strategies/<id>/strategy.py` or `TradeScan_State/runs/<run_id>/strategy.py` (snapshot, read-only) — same logic that `generate_strategy_card.py:_logic_lines` already uses |
| Δ vs parent | textual diff over flattened signature, same approach as `generate_strategy_card.py:_diff` |
| Engine version | `metadata/run_metadata.json` (per-run) — sanity-check all variants on same engine version |
| `sweep_registry.yaml` | for the official parent chain (P00→P02→P03→...) |

### Effort: S (~1 hour)
Refactor the existing `generate_strategy_card.py` `_flatten` and `_diff` helpers into a shared module `tools/report/strategy_signature_utils.py` and reuse from both the family report and the strategy card.

### Risk
Low. The signature parsing is already battle-tested in `generate_strategy_card.py`.

---

## 2. Question B — Comparative Metrics

### What to render

```markdown
## Core Metrics (24m standardized window)

| Variant | Trades | Net PnL | PF | SQN | Sharpe | DD% | R/DD | Expectancy | Avg Bars |
|---------|--------|---------|----|-----|--------|-----|------|-----------|----------|
| P09 | 1,251 | $2,226.95 | 1.25 | 2.34 | 1.05 | 0.38% | 5.84 | $1.78 | 72.6 |
| P14 | 1,078 | $2,830.45 | 1.35 | **2.87** | **1.39** | 0.40% | **7.07** | $2.63 | 65.5 |
| P15 | 1,013 | $2,262.97 | 1.30 | 2.50 | 1.25 | **0.36%** | 6.26 | $2.23 | 75.1 |
| S02 P01 | 1,054 | $1,997.31 | 1.25 | 2.03 | 0.99 | 0.58% | 3.47 | $1.89 | 66.8 |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

## Δ vs parent (per metric)
| Variant | Δ Trades | Δ PnL | Δ PF | Δ SQN | Δ DD% |
|---------|----------|-------|------|-------|-------|
| P14 (vs P09) | -173 | +$603 | +0.10 | +0.53 | +0.02 |
| P15 (vs P09) | -238 | +$36 | +0.05 | +0.16 | -0.02 |
| ... | ... | ... | ... | ... | ... |
```

Bold = best in column. Rank arrow `↑/↓` against parent for SQN, PF, DD%.

### Where the data comes from

| Field | Source |
|---|---|
| Trades, Net PnL, PF, SQN, Sharpe, DD%, R/DD, Expectancy | `Strategy_Master_Filter.xlsx` row, filtered by `strategy` startswith family prefix |
| Avg Bars | Master Filter column `avg_bars_in_trade` |
| Δ vs parent | join on parent pass number — parent inferred from sweep_registry or pass-number heuristic (`P14 → P13 → ... → P09 → P00`) |

### Effort: S (~1 hour)
Read Master Filter via `tools/ledger_db.py` `read_master_filter()` (already a helper for read-only access).

### Cross-window guard
**Required.** Before rendering, check every row's `test_start` and `test_end`. If a row's window differs from the family median by > 5 days at either end, flag with a warning:

```
> WARNING: 2 of 6 variants ran on a different test window. Marked with ⚠ below.
> Rows ⚠ are not comparable to the rest.
```

This is the cross-window comparability fix surfaced from REPORT_AUDIT §2.7. Implementation: ~10 LOC in a new `tools/window_compat.py`.

### Risk
- Master Filter row staleness — if a row reflects a pre-recovery window, the family report inherits that staleness. Mitigate via the cross-window guard (above) + a `--refresh` flag that triggers `python tools/stage3_compiler.py <prefix>` first.
- Master Filter cardinality — `_assert_pipeline_idle` may interrupt — read-only path is fine, no append.

---

## 3. Question C — Structural Attribution

This is where the report becomes unique — these computations live nowhere today.

### 3.1 Concentration risk

```markdown
## Concentration

| Variant | Top-5% | Top-10% | Top-20% | Body PnL (after Top-20) | Worst-5% | Longest Loss Streak |
|---------|--------|---------|---------|------------------------|----------|---------------------|
| P09 | 39.9% | 71.7% | 120.4% | -$453 | 4.4% | 10 |
| P14 | 36.5% | 62.6% | 104.8% | -$136 | 5.7% | 16 |
| ... | ... | ... | ... | ... | ... | ... |
```

**Compute:** Read `results_tradelevel.csv` per variant. Call existing primitive [`tools/utils/research/robustness.py:10`](tools/utils/research/robustness.py:10) `tail_contribution(tr_df)` → returns `{top_1, top_5, top_1pct, top_5pct, total_pnl, ...}`. Wrap to also emit Top-10% / Top-20% / body-after-Top-N (one extra groupby; ~10 LOC in the renderer, not a new primitive).

**Effort:** XS (~15 minutes — pure orchestration, primitive already battle-tested).

### 3.2 Tail dependence

```markdown
## Tail Dependence

| Variant | Top-5% | Top-10% | Top-20% | Body PnL | Verdict |
|---------|--------|---------|---------|----------|---------|
| P09 | 39.9% | 71.7% | 120.4% | -$453 | TAIL-DEPENDENT |
| P14 | 36.5% | 62.6% | 104.8% | -$136 | TAIL-DEPENDENT (mildest) |
```

**Verdict logic:**
- Top-20% ≥ 100% → TAIL-DEPENDENT
- Top-5% > 50% AND Top-20% > 130% → SEVERELY TAIL-DEPENDENT
- Otherwise → BODY-DRIVEN

**CAGR-degradation evidence (advisory):** reuse [`tools/utils/research/robustness.py:33`](tools/utils/research/robustness.py:33) `tail_removal(tr_df, pct_cutoff=0.01)` and `pct_cutoff=0.05` to show "remove top 1% → CAGR drops from X% to Y%". Already deterministic, milliseconds per variant. No new code.

Same verdict thresholds as `family_psbrk_24m_report.md` §5.

### 3.3 Session dependence

```markdown
## Session Contribution

| Variant | Asia | London | NY | Max session % |
|---------|------|--------|----|--------------:|
| P09 | 45.1% | 39.9% | 15.0% | 45.1% |
| P14 | 43.8% | 27.4% | 28.9% | 43.8% (most balanced) |
| S02 P01 | 52.0% | 13.4% | 34.6% | 52.0% ⚠ London weak |
```

**Compute:** From `results_tradelevel.csv`, classify each row's `entry_timestamp` via `tools/report/report_sessions.py:_classify_session`, sum PnL per session, divide by total net.

**Flag threshold:** Max session > 70% → warn.

### 3.4 Direction dependence

```markdown
## Direction Concentration

| Variant | Long share | Short share | Imbalance |
|---------|-----------|-------------|-----------|
| P09 | 92.4% | 7.6% | Extreme long bias |
| P14 | 62.1% | 37.9% | Balanced |
| ... | ... | ... | ... |
```

**Compute:** Two pieces:
1. **Share table** above — simple groupby on `direction`, sum positive `pnl_usd`, divide by total positive. ~5 LOC in the renderer.
2. **Direction-removal stress** — call existing primitive [`tools/utils/research/robustness.py:66`](tools/utils/research/robustness.py:66) `directional_removal(tr_df)` to report `baseline_pf`, `no_long20_pf`, `no_short20_pf`, `no_both_pf`. Identifies whether top-20 longs/shorts carry the edge.

Flag "Extreme bias" when one side carries > 85% of positive PnL; "Balanced" when neither side < 30%.

### 3.5 Regime winners / bleed cells

```markdown
## Regime Cell Matrix (cross-variant)

### Direction × Volatility
| Variant | Best cell | Best PnL | Worst cell | Worst PnL |
|---------|-----------|----------|------------|-----------|
| P14 | Short × High | +$1,301 | Short × Normal | -$144 |
| P15 | Long × Low | +$792 | Short × Low | -$124 |
| ... | ... | ... | ... | ... |

### Direction × Trend  
(similar layout)
```

**Compute:** Reuse the Dir × Vol and Dir × Trend cross-tabs from `tools/report/report_sections/risk.py:166`; per variant, identify best and worst cell by PnL with N ≥ 30.

### 3.6 Yearwise stability

```markdown
## Yearwise Stability

| Variant | 2024 PnL | 2025 PnL | 2026 (partial) PnL | Max year share | Flag |
|---------|----------|----------|---------------------|----------------|------|
| P09 | $339 (15%) | $945 (42%) | $943 (42%) | 42% | balanced |
| P14 | $229 (8%) | $1,161 (41%) | $1,440 (51%) | 51% | 2026 carries half |
| ... | ... | ... | ... | ... | ... |
```

**Compute:** Two options, equivalent results:
1. Read `results_yearwise.csv` per variant (already written by Stage-1).
2. Or extract the yearwise/monthly logic currently inline at [`tools/robustness/runner.py:159-183`](tools/robustness/runner.py:159) into a shared helper `tools/utils/research/calendar.py` and call from both robustness runner and family report. **Recommended.** Removes duplication; both reports stay in sync.

Flag any year > 60% as dominant.

### 3.7 Streak diagnostics

```markdown
## Loss / Win Streaks

| Variant | Max Win Streak | Max Loss Streak | Avg Loss Streak |
|---------|----------------|-----------------|-----------------|
| P14 | 12 | 16 | 3.2 |
| P09 | 9 | 10 | 2.8 |
| ... | ... | ... | ... |
```

**Compute:** Currently inline at [`tools/robustness/runner.py:203-237`](tools/robustness/runner.py:203). Extract into `tools/utils/research/streaks.py` (same `_max_streak` / `_avg_streak` body); call from both robustness suite and family report.

**Effort:** S (~20 min — refactor existing inline code).

### 3.8 Rolling-window stability

```markdown
## Rolling Stability (365d window, 30d step)

| Variant | Windows | Neg. Windows | DD>20% Windows | Worst Return | Worst DD | Clustering |
|---------|---------|--------------|----------------|--------------|----------|------------|
| P14 | 7 | 1 | 0 | -2.1% | 18.2% | ISOLATED |
| P09 | 7 | 0 | 1 | +1.4% | 21.3% | N/A |
| ... | ... | ... | ... | ... | ... | ... |
```

**Compute:** Call [`tools/utils/research/rolling.py:10`](tools/utils/research/rolling.py:10) `rolling_window(eq_df, tr_df, window_days=365, step_days=30)` then `classify_stability(...)`. Pure reuse, ~3 LOC per variant in the renderer.

### 3.9 Early/late split

```markdown
## Stability — Early vs Late Half

| Variant | First Half PnL | Second Half PnL | First WR | Second WR | Δ Win Rate |
|---------|----------------|------------------|----------|-----------|-----------|
| P14 | $1,094 | $1,736 | 36.1% | 38.4% | +2.3pp |
| ... | ... | ... | ... | ... | ... |
```

**Compute:** Call [`tools/utils/research/robustness.py:118`](tools/utils/research/robustness.py:118) `early_late_split(tr_df, start_cap)`. Already returns `{first_half: {…}, second_half: {…}}`. Renderer reads two keys.

### 3.10 Drawdown clusters

```markdown
## Worst Drawdown Episode

| Variant | Start | Trough | Recovery | Max DD% | Duration | Clustering |
|---------|-------|--------|----------|---------|----------|------------|
| P14 | 2025-03-12 | 2025-04-08 | 2025-05-21 | 18.2% | 27 / 70d | ISOLATED |
| ... | ... | ... | ... | ... | ... | ... |
```

**Compute:** Call [`tools/utils/research/drawdown.py:10`](tools/utils/research/drawdown.py:10) `identify_dd_clusters(eq_df, top_n=1)` per variant (top-1 only for family compactness — robustness suite shows top-3). Renderer reads `start_date`, `trough_date`, `recovery_date`, `max_dd_pct`, `duration_days`.

### Effort for §3 total (concentration + tail + session + direction + regime + yearwise + streaks + rolling + early/late + drawdown): **M (~2 hours combined)** — most of which is rendering. Compute is reuse.

---

## 4. Question D — Promotion Logic

### What to render

```markdown
## Verdict

| Variant | Verdict | Rationale |
|---------|---------|-----------|
| **P14** | **CORE** | SQN 2.87 ≥ 2.5, PnL $2,830 > 1,000, trades 1,078 ≥ 200, Top-5 36.5% < 70%. Body-after-Top-20 = -$136 (mildest in family). |
| P15 | WATCH | SQN 2.50 meets exactly, tightest DD 0.36%, body-after-Top-20 = -$386. Conservative classification given borderline SQN. |
| P09 | WATCH | SQN 2.34, prior V4 winner, now demoted by P14. |
| S03 P02 | WATCH | SQN 2.32 < 2.5; structurally distinct (momentum filter) — diversifier candidate. |
| S02 P03 | WATCH | SQN 2.22, Top-5 54.9%, filter correctly targeted but on wrong base. |
| S02 P01 | **FAIL** (effective) | Meets WATCH gates technically but 277-day flat period + 59.8% Top-5 = deployment-unfit per spirit of `feedback_promote_quality_gate`. |
```

### Verdict logic

Reuse the gate hierarchy already encoded in `tools/filter_strategies.py:_compute_candidate_status` (the Notes-sheet logic). Plus the supplementary "spirit of the gate" overrides from `feedback_promote_quality_gate.md` memory:

- **FAIL hard gates** (unchanged): `realized_pnl ≤ 0` OR `trades < 50` OR `expectancy < asset-class gate`.
- **FAIL soft gates** (new — surfaced as advisory in family report): `Top-5 concentration > 70%` OR `body-after-Top-20 < -$500` OR `longest_flat_days > 250`.
- **CORE**: same as `filter_strategies` — for single-asset, `SQN ≥ 2.5` AND `realized > 1000` AND `accepted ≥ 200`.
- **WATCH**: passes FAIL but doesn't clear CORE. SQN ≥ 2.0 floor for WATCH (per MEMORY.md single-asset gate).
- **CANDIDATE**: WATCH with one clear improvement direction left (e.g. "DD ≥ 30% — propose DD-reduction variant").
- **PROMOTE**: CORE + structurally diverse from existing portfolio (correlation check) — beyond scope of family report; defer to `promote` skill.

### Effort: M (~2 hours) — mostly logic from existing modules.

### Risk
The "spirit of the gate" overrides are advisory, not authoritative. The family report should make this clear: a row marked FAIL (effective) is NOT auto-demoted in `Filtered_Strategies_Passed.xlsx` — the family report is a research artifact only.

---

## 5. Pipeline Integration

### How it integrates with the existing pipeline

**Recommendation: ON-DEMAND COMMAND.** New tool:

```bash
python tools/family_report.py <directive-prefix> \
    [--window 2024-05-11:2026-05-11] \
    [--variants 65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09,P14,P15] \
    [--out outputs/family_reports/<prefix>_<timestamp>.md]
```

**Reasoning** (vs per-pass auto-trigger or end-of-family auto-trigger):

### Trigger decision: per-pass vs end-of-family vs on-demand

| Trigger | Pros | Cons | Picked? |
|---|---|---|---|
| **Per-pass** (every directive auto-regenerates the family report) | Always fresh; family report mirrors pipeline state | Noisy partial-family snapshots get committed to repo; family report regenerates on every pass even when only 2 variants exist; can mask the variant being run (sweeps trigger 5-10 reports) | No |
| **End-of-family** (auto-trigger when all S(n) passes are completed) | Single canonical artifact per sweep | "End of family" is not detectable — the researcher decides when a family is "done"; auto-trigger would either fire at every PORTFOLIO_COMPLETE (= per-pass) or never | No |
| **On-demand** (manual `python tools/family_report.py <prefix>`) | Fires when the researcher wants the synthesis; doesn't pollute repo with throwaway snapshots; mirrors how `family_psbrk_24m_report.md` was actually used | Researcher has to remember to invoke | **Yes (recommended)** |

**Justification (one sentence per user spec):** Family analyses are research events at variable cadence — they happen when the researcher decides multiple variants warrant comparison — so the report should be manually invoked rather than auto-fired by a pipeline boundary that doesn't correspond to the research decision.

### Cross-references back into existing artifacts

Each variant row in the family report links to:
- `[REPORT_*.md](../../TradeScan_State/backtests/<dir>_<sym>/REPORT_*.md)` — full per-strategy report
- `[STRATEGY_CARD.md](../../TradeScan_State/backtests/<dir>_<sym>/STRATEGY_CARD.md)` — config
- `[AK_Trade_Report_*.xlsx](../../TradeScan_State/backtests/<dir>_<sym>/AK_Trade_Report_*.xlsx)` — Excel

The per-strategy report (after [REPORT_UPGRADE_PLAN.md](REPORT_UPGRADE_PLAN.md) Step B) links back to the family report when it exists at the expected path.

### Sections that could be slimmed in per-strategy report once Family Report exists

After the Family Report lands, the per-strategy `REPORT_*.md` could optionally:
- Drop the standalone "Yearwise" detail (move full table to family report; keep just a one-line summary).
- Drop the Edge Decomposition cross-tabs entirely (family report carries the matrix per variant).

Recommendation: **don't slim**. Keeping both reports self-sufficient is cheap (no compute saved by removing tables; just text). The per-strategy report should remain readable in isolation.

---

## 6. Data Lineage

Inputs and where each metric in the family report comes from:

| Section | Primary source | Helper |
|---|---|---|
| Lineage | `Trade_Scan/strategies/<id>/strategy.py` (signature flatten) + `sweep_registry.yaml` | `tools/report/strategy_signature_utils.py` (**new** — extracted from `generate_strategy_card.py`) |
| Core metrics + Δ vs parent | `Strategy_Master_Filter.xlsx` (read via `tools/ledger_db.py:read_master_filter()`) | none |
| Cross-window guard | Master Filter `test_start`/`test_end` columns | `tools/window_compat.py` (**new** — ~30 LOC) |
| Concentration / tail | `results_tradelevel.csv` | reuse `tools.utils.research.robustness.tail_contribution` + `tail_removal` — **no new module** |
| Streaks | `results_tradelevel.csv` | extract inline streak code from `tools/robustness/runner.py:203` → `tools/utils/research/streaks.py` (refactor, ~30 LOC moved not new) |
| Yearwise / Monthly | `results_tradelevel.csv` | extract inline year/month logic from `tools/robustness/runner.py:159` → `tools/utils/research/calendar.py` (refactor) |
| Rolling stability | `equity_curve.csv` + `results_tradelevel.csv` | reuse `tools.utils.research.rolling.rolling_window` + `classify_stability` — **no new module** |
| Drawdown clusters | `equity_curve.csv` | reuse `tools.utils.research.drawdown.identify_dd_clusters` — **no new module** |
| Early/late split | `results_tradelevel.csv` | reuse `tools.utils.research.robustness.early_late_split` — **no new module** |
| Session × Direction matrix | `results_tradelevel.csv` `entry_timestamp` (no `session` column written) | `tools/report/family_session_xtab.py` (**new** — ~40 LOC: hour→session derivation + 3 cross-tabs Dir×Session, Dir×Trend, Dir×Vol) |
| Verdict | `tools/filter_strategies.py:_compute_candidate_status` (reused) + soft-gate overrides | `tools/report/family_verdicts.py` (**new** — ~60 LOC, orchestration only) |

**Inventory of allowed new code** (per Rule 2 + Rule 4 wrapper-first):
- `tools/family_report.py` — orchestrator + CLI (~150 LOC, NEW)
- `tools/report/strategy_signature_utils.py` — lineage aggregation (~80 LOC, NEW, duplicates `_flatten`/`_diff` from `generate_strategy_card.py` per Rule 4 — original untouched)
- `tools/report/family_session_xtab.py` — session derivation + 3 cross-tabs (~40 LOC NEW)
- `tools/report/family_verdicts.py` — verdict orchestration over existing gates (~60 LOC NEW)
- `tools/report/family_renderer.py` — markdown variant comparison renderer (~150 LOC NEW)
- `tools/window_compat.py` — cross-window guard (~30 LOC NEW)
- `tools/utils/research/streaks.py` — `compute_streaks()` helper (~30 LOC NEW, duplicates inline logic from `runner.py:203` per Rule 4 — original untouched)
- `tools/utils/research/calendar.py` — `yearwise_pnl()`/`monthly_heatmap()` helpers (~40 LOC NEW, duplicates inline logic from `runner.py:159` per Rule 4 — original untouched)

**Net new code:** ~580 LOC across 8 new modules. ~150 LOC is intentional duplication (Rule 4) to keep `tools/robustness/runner.py` and `tools/generate_strategy_card.py` untouched in first release.

**Zero new analytics.** Every metric comes from an existing primitive or its inline duplicate.

**No new state, no new ledger, no new schema.** Read-only against existing artifacts.

---

## 7. Module-Level Design

### Proposed structure (wrapper-first per Rule 4)

```
tools/
├── family_report.py                    (~150 LOC, NEW) — top-level orchestrator + CLI
├── report/
│   ├── strategy_signature_utils.py     (~80 LOC, NEW; duplicates _flatten/_diff from generate_strategy_card.py)
│   ├── family_session_xtab.py          (~40 LOC, NEW) — session derivation + Dir×{Session,Trend,Vol} cross-tabs
│   ├── family_verdicts.py              (~60 LOC, NEW) — verdict orchestration over existing gates
│   └── family_renderer.py              (~150 LOC, NEW) — markdown variant comparison renderer
├── window_compat.py                    (~30 LOC, NEW) — cross-window comparability guard
└── utils/research/
    ├── streaks.py                      (~30 LOC, NEW; duplicates streak logic from robustness/runner.py:203)
    └── calendar.py                     (~40 LOC, NEW; duplicates yearwise/monthly logic from runner.py:159)
```

**Untouched in first release (Rule 4):**
- `tools/robustness/runner.py` — keeps its inline streak/calendar logic.
- `tools/generate_strategy_card.py` — keeps its inline `_flatten`/`_diff`.

**Removed from earlier draft:**
- ~~`tools/report/family_tail.py`~~ — `tail_contribution` and `tail_removal` already exist in `tools.utils.research.robustness`.
- ~~`tools/report/family_attribution.py`~~ — folded into `family_renderer.py`; Δ-vs-parent is rendering not computation.

### Public surface

```python
# tools/family_report.py
def generate_family_report(
    prefix: str,
    variants: list[str] | None = None,
    window: tuple[str, str] | None = None,
    out_path: Path | None = None,
) -> Path:
    """Generate a family analysis report. Returns path written."""

# tools/report/strategy_signature_utils.py (extracted from generate_strategy_card.py)
def flatten_signature(strategy_py_path: Path) -> dict[str, Any]: ...
def diff_signatures(prev: dict, curr: dict) -> list[tuple[str, str, str]]: ...

# tools/report/family_session_xtab.py (only genuinely new analytics)
def classify_session(ts: pd.Timestamp) -> str: ...           # asia / london / ny / dead
def crosstab_direction_session(tr_df: pd.DataFrame) -> pd.DataFrame: ...
def crosstab_direction_trend(tr_df: pd.DataFrame) -> pd.DataFrame: ...
def crosstab_direction_volatility(tr_df: pd.DataFrame) -> pd.DataFrame: ...

# tools/utils/research/streaks.py (refactored from inline)
def compute_streaks(pnls: np.ndarray) -> dict: ...           # max/avg win/loss streak

# tools/utils/research/calendar.py (refactored from inline)
def yearwise_pnl(tr_df: pd.DataFrame) -> dict: ...
def monthly_heatmap(tr_df: pd.DataFrame) -> dict: ...
```

### What the orchestrator calls per variant (illustrative)

```python
from tools.utils.research.robustness import (
    tail_contribution, tail_removal, directional_removal, early_late_split,
)
from tools.utils.research.rolling import rolling_window, classify_stability
from tools.utils.research.drawdown import identify_dd_clusters
from tools.utils.research.streaks import compute_streaks           # refactored
from tools.utils.research.calendar import yearwise_pnl              # refactored
from tools.report.family_session_xtab import (
    crosstab_direction_session, crosstab_direction_trend, crosstab_direction_volatility,
)
# ~9 imports, all primitives; orchestrator just dispatches over the variant list.
```

### Consumption pattern (Stage-1 outputs vs Master Filter vs MPS)

- **Headline numerics** — from Master Filter (one round trip, ~0.1s).
- **Concentration / session / direction / regime** — from per-variant `results_tradelevel.csv` (one CSV read per variant, ~30 KB each; 6 variants ~ 0.5s total).
- **Lineage diff** — from each variant's `strategy.py` (~10 KB each; <0.2s).
- **MPS not read directly.** Family report is for single-asset variant comparison primarily; multi-asset composites are different beasts that go through `tools/portfolio_evaluator.py`.

**Total runtime estimate: 1-3 seconds per family of up to 10 variants.**

---

## 8. Artifact Naming and Storage

| Aspect | Decision |
|---|---|
| Output location | `outputs/family_reports/<prefix>_<YYYYMMDD>_<HHMMSS>.md` |
| Naming | `<prefix>` = first three components of directive name (e.g. `65_BRK_XAUUSD_5M_PSBRK`); timestamp prevents overwrite |
| Retention | Keep all (git-tracked); they are inexpensive (~30 KB each) and document research history |
| Indexing | Add `outputs/family_reports/INDEX.md` (auto-regenerated each invocation) listing every family report with date, prefix, and one-line summary. Same pattern as `outputs/system_reports/` already uses |
| Linking | The per-strategy report's `_build_header_section` (after [REPORT_UPGRADE_PLAN.md](REPORT_UPGRADE_PLAN.md) Step B) auto-detects the latest matching family report and links to it |

---

## 9. Integration Points

### With existing per-strategy report
- One-line cross-link in header (added by REPORT_UPGRADE_PLAN.md Step B): `[Family Report — <prefix>](../../outputs/family_reports/<prefix>_<latest>.md)` when one exists.

### With RESEARCH_MEMORY.md
- After running, the family report's verdict block is suitable copy-paste material for a `memory/project_<family>_summary.md` entry. The report file itself is the durable artifact; memory just points to it.

### With sweep_registry.yaml
- Read-only — used to determine the parent of each pass for the Δ-vs-parent column. Never written.

### With Master Filter
- Read-only — provides headline metrics. The report explicitly notes when row `test_start` differs from family median (cross-window guard from §2.4 of REPORT_AUDIT). Never written.

### With Promote skill
- The "PROMOTE" verdict in the family report is **advisory only** — actual promotion requires running the `promote` skill. The family report's CORE verdict for one variant is necessary but not sufficient for promotion.

---

## 10. Risks

### Snapshot-immutability invariant (#4)
**Status:** PRESERVED. The family report reads `TradeScan_State/runs/<RUN_ID>/strategy.py` and `Trade_Scan/strategies/<id>/strategy.py` but does not write to either. Read-only against snapshots. The strategy.py-signature parsing uses `ast.literal_eval` — same as `generate_strategy_card.py`.

### Cross-window false comparisons
**Mitigation:** The cross-window comparability guard (§2.4, helper `tools/window_compat.py`) is built before the comparative metrics table is rendered. Rows with mismatched windows are marked ⚠ and explicitly called out as not comparable.

### Master Filter staleness
**Mitigation:** Family report optionally accepts `--refresh` to trigger `python tools/stage3_compiler.py <prefix>` first, ensuring Master Filter rows match the latest backtest artifacts. Default is no-refresh (researcher controls).

### Append-only ledger invariant (#2)
**Status:** PRESERVED. No writes to Master Filter, MPS, FSP, run_summary.csv, hypothesis_log.json. Reads only.

### Engine freeze (Invariant #6)
**Status:** PRESERVED. No engine module touched. No `engine_dev/`, `engines/`, `governance/` modification.

### Performance
**Status:** Acceptable. 6 variants × ~50 KB tradelevel csv = ~300 KB total I/O. < 1 second compute (all primitives are O(N) or O(N log N) over the trade log; no MC iterations, no bootstrap, no friction sweeps).

### Shared-primitive coupling (NEW — introduced by Rule 1)
**Status:** Acknowledged. The two refactors (`streaks.py`, `calendar.py`) lift code currently inline in `tools/robustness/runner.py` into `tools/utils/research/`. Both runner and family report will import from the new location. **Risk:** a change to `compute_streaks` semantics affects both the per-strategy robustness report AND the family report. **Mitigation:** (a) the extraction is mechanical — byte-equivalent function bodies, just relocated; (b) unit tests pin the streak/year/month outputs against the current Stage-2 reports' numbers via golden snapshots; (c) `tools/robustness/runner.py` is updated in the same commit to import from the new path — atomic refactor, no transitional state.

### Forbidden primitive leakage
**Status:** Tested. A unit test in `tools/tests/test_family_report.py` will import `tools.family_report` and assert it does NOT import any of: `simulators`, `block_bootstrap`, `friction`, `monte_carlo`, `bootstrap`. Prevents future drift from Rule 3.

### Test coverage
Add `tools/tests/test_family_report.py` with:
- Unit tests for each new helper (`compute_tail_concentration`, signature diff, verdict logic).
- Integration test: run `generate_family_report("65_BRK_XAUUSD_5M_PSBRK")` against the 6 existing PSBRK runs in `backtests/`. Snapshot-match the output to a checked-in golden file (`tools/tests/fixtures/family_psbrk_golden.md`). Update the golden when intentional changes are made.

---

## 11. Effort Estimate

**Revised after robustness audit + Rules 1-3:**

| Phase | Scope | Effort |
|---|---|---|
| 0 | Refactor: extract `streaks.py` and `calendar.py` from `robustness/runner.py`; update runner imports; golden-snapshot tests | S (1h) |
| 1 | Lineage (extract signature_utils from generate_strategy_card) + cross-window guard + comparative-metrics table from Master Filter | S (1.5h) |
| 2 | Structural attribution — orchestrate `tail_contribution`, `tail_removal`, `directional_removal`, `early_late_split`, `rolling_window`, `identify_dd_clusters`, refactored streaks/calendar, plus `family_session_xtab.py` (the only genuinely new analytics) | S (1.5h) |
| 3 | Verdict orchestration (call `_compute_candidate_status` + apply family soft-gate overrides) | S (1h) |
| 4 | Markdown renderer + Δ-vs-parent table + cross-links to per-strategy reports | S (1.5h) |
| 5 | Tests (unit for new pieces, golden snapshot against existing `family_psbrk_24m_report.md`, forbidden-import guard) | S (1.5h) |
| **Total** | — | **~8 hours / 1 day** |

### Build sequence
- **AM**: Phase 0 (extract refactors) + Phase 1 (lineage + comparative + window guard).
- **PM**: Phases 2-3 (structural attribution + verdict).
- **End of day**: Phases 4-5 (renderer + tests). Acceptance: generated report matches `family_psbrk_24m_report.md` within rounding tolerance.

The cost reduction (from ~16h to ~8h) is entirely from Rule 1 — the analytics already exist. The remaining hours are orchestration, refactor, rendering, and tests. There is no longer a "Day 3 optional" because mutation attribution Δ is just rendering existing diffs, not new analysis.

---

## 12. Testing Strategy

### Unit tests
- `test_compute_tail_concentration` — given a known trades DataFrame, assert top-N percentages.
- `test_diff_signatures` — given two known signatures, assert the diff list.
- `test_verdict_with_soft_gates` — variants matching the family report's §7 verdicts should reproduce them exactly.
- `test_window_comparability` — given rows with intentional date mismatches, assert the warning fires.

### Integration test
- Golden snapshot: run against the 6 existing PSBRK runs (already in `backtests/`) and snapshot-match against `tools/tests/fixtures/family_psbrk_golden.md`.
- Re-run when intentional changes are made; commit golden update with the same PR.

### Manual acceptance
- After Phase 3 lands, run `python tools/family_report.py 65_BRK_XAUUSD_5M_PSBRK` and visually compare against the existing `outputs/family_psbrk_24m_report.md`. The new generated report should reproduce every metric in the existing one within rounding tolerance.

---

## 13. One-Paragraph Rationale (per user spec, revised post-audit)

> The Family Report is the structural fix for two of the highest-cost pain points in the audit: fragmented family comparisons (#1) and ephemeral `tmp/` scripts (#10). After the robustness audit, the build collapses from "design new analytics" to "orchestrate existing primitives" — `tail_contribution`, `tail_removal`, `directional_removal`, `early_late_split`, `rolling_window`, `identify_dd_clusters` already exist in `tools/utils/research/` and `tools/robustness/`, all cheap and deterministic. The only genuinely new analytics is session derivation + 3 cross-tabs (Dir×Session, Dir×Trend, Dir×Vol) — ~40 LOC. Net new code lands around 280 LOC, almost entirely renderer + orchestrator. Built as a manual `python tools/family_report.py <prefix>` to match how families actually form (researcher discretion, variable cadence). Reads existing artifacts only — no engine touch, no ledger writes, no schema change. Total effort: ~1 day. After it lands, the `tmp/` script pattern is replaceable and the `family_psbrk_24m_report.md` style of analysis becomes a one-command operation.