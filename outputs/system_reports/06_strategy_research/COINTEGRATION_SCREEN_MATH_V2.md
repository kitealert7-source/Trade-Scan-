# Cointegration Screener — Math Correction (v1 → v2)

**Date:** 2026-05-30
**Status:** Design — pending operator ack before C2 lands
**Scope:** `tools/cointegration_screen.py`, `tools/cointegration_db.py`, `tools/cointegration_excel.py`, `tests/test_cointegration_screen.py`
**Operator decisions locked this session:** math = log + EG only (no FDR), corpus = legacy-tag (no rebuild), hysteresis = regime reset for ≥5 v2 rows
**Authority:** addresses the math half of the 2026-05-29 audit; the durability/edge half (cointegration-as-screen weak at 1d×252) remains a separate PROVISIONAL conclusion under AGENT.md Invariant #31

---

## 1. Current implementation (v1 — `v1_raw_adf`)

| Aspect | Current code | Location |
|---|---|---|
| Spread construction | `spread = b − β·a` on **raw closes**; OLS α dropped (adfuller `regression='c'` re-adds) | `cointegration_screen.py:204-210` |
| Beta estimation | OLS static, `B = α + β·A` | line 207 |
| ADF invocation | `adfuller(spread, autolag="AIC")` — **standard unit-root criticals** | line 216 |
| Criticals validity | Wrong for pre-estimated OLS residuals → systematically over-rejects | — |
| Multiple-testing | None | `run()` loop |
| Inconsistency | `compute_single_series_adf` (line 290) uses `np.log` — pair-spread path doesn't | line 290 |
| Identity markers | `BETA_METHOD="ols_static"`, `TEST_METHOD="adf"` | constants |

**Universe-scale impact (per 2026-05-29 audit, 1d × 252, 465 pairs):**

| Stage | Qualified | % |
|---|---|---|
| v1 baseline | 163 | 35.1% |
| + log prices | 158 | 34.0% |
| + EG/MacKinnon criticals (= v2 endpoint) | **84** | 18.1% |
| + BH-FDR (deferred from this session) | 0 | 0.0% |

EG criticals are the dominant correction. Log alone is small at scale but fixes a real inconsistency.

---

## 2. Target implementation (v2 — `v2_log_eg`)

| Aspect | Target code | Notes |
|---|---|---|
| Spread construction | OLS on **log prices**: `lb = log(b)`, `la = log(a)`, fit `lb = α + β·la` | β stored, unused by strategy |
| Cointegration test | `statsmodels.tsa.stattools.coint(lb, la, trend='c', autolag='AIC')` | MacKinnon (1996) EG critical values |
| Regime classifier thresholds | Unchanged: `<0.05` cointegrated, `<0.10` breaking, else broken | Same buckets, harder-to-hit gate |
| Multiple-testing | **NONE this session.** FDR is a future v3 decision | See §6 |
| Identity markers | `BETA_METHOD="ols_static"` (β on log, but still OLS); `TEST_METHOD="eg_mackinnon"` | |
| Version label | `methodology_version="v2_log_eg"` | New column, see §3 |

**Why log + EG together, not separable:**
- Log alone leaves the EG-criticals bug intact (158 still over-qualified vs ~84 truth).
- EG alone on raw-price spreads is technically defensible but inconsistent with the existing log-space single-series path.
- Together they are the textbook clean methodology — matches what `compute_synthetic_log_ratio` already does for synthetic pairs.

**FDR explicitly deferred** — see §6.

---

## 3. Methodology versioning (schema change)

### 3.1 New column

Add `methodology_version TEXT NOT NULL` to:
- `PARQUET_COLUMNS` in `cointegration_screen.py` (appended at end — schema-order preserved for `pair_a, …, regime, data_version, generated_at, methodology_version`)
- `SINGLES_PARQUET_COLUMNS` (same)
- DB pair-table `coint_pairs_history` (or whatever the table name resolves to — `cointegration_db.py:156` block)
- DB singles table `coint_singles_history`
- DB triggers table if it persists this dimension (likely no — triggers reference pair_a/pair_b, not methodology)

### 3.2 Values

- Existing rows: `"v1_raw_adf"` (one-time SQL UPDATE during C2 migration)
- New rows from v2 code: `"v2_log_eg"`
- Future v3 (if FDR ever ships): `"v3_log_eg_fdr"` etc.

### 3.3 Frozen-schema test guard

`tests/test_cointegration_screen.py:163-173` `test_parquet_columns_canonical_order` must be updated in the **same commit** as the schema change. The test's "Schema is FROZEN" intent is preserved — additions go at the canonical end of the list.

### 3.4 Rendering

`cointegration_excel.py` human-view tab: add `methodology_version` as a visible column. Tab header gets a one-line note:

> Rows tagged `v1_raw_adf` were qualified under pre-correction math (raw-price ADF without EG criticals); see `COINTEGRATION_SCREEN_MATH_V2.md`. Rows tagged `v2_log_eg` use log-price + Engle-Granger/MacKinnon criticals. Methodologies are NOT comparable head-to-head.

---

## 4. Regime hysteresis transition

**Locked decision:** **Regime reset until 5 v2 rows exist per pair.**

The current regime classifier (`cointegration_db.py:414`, callsite of `classify_regime`) reads a 5-day rolling median of `adf_pvalue` from the DB. After C3 lands, that median will mix v1 and v2 p-values — and EG p-values are systematically larger than raw-ADF p-values for the same data, so pairs would show spurious regime flips driven by methodology, not signal.

**Implementation:**
- In `_pair_pvalue_history` (line 257ish) and the singles equivalent (line 582ish): add a `methodology_version` filter. Only return p-values matching the calling row's methodology.
- In the classifier callsite: if fewer than 5 same-methodology rows are available, classify from the current row's `adf_pvalue` alone (skip hysteresis). Once history reaches 5+, hysteresis resumes naturally.
- Test: new `test_hysteresis_resets_at_methodology_cutover` — given a sequence of v1 rows and a single v2 row, the v2 regime is classified from current pvalue only.

This is a clean transition state, not a hack — `classify_regime`'s existing fallback for empty history is already "use current p-value." We're just extending that fallback to "use current p-value when same-methodology history < 5."

---

## 5. Atomic commit sequence

Each commit ships independently green (preflight + targeted pytest).

### C1 — design doc (this file)
- File: `outputs/system_reports/06_strategy_research/COINTEGRATION_SCREEN_MATH_V2.md`
- Operator review gate. No code touched.

### C2 — schema extension + backfill
- Code: add `methodology_version` to PARQUET_COLUMNS, SINGLES_PARQUET_COLUMNS, DB schemas, and the `_pair_pvalue_history` / `_singles_pvalue_history` queries.
- Backfill script: one-time `UPDATE … SET methodology_version = 'v1_raw_adf' WHERE methodology_version IS NULL`. Self-contained migration helper (deletable after run).
- Tests: extend `test_parquet_columns_canonical_order` + `test_singles_parquet_columns_canonical_order` with the new field; add `test_methodology_version_required_not_null` on DB schema.
- Math unchanged — v1 rows still written as `'v1_raw_adf'` until C3 lands.
- Verify: round-trip read/write of an existing v1 row is byte-equivalent modulo the new column.

### C3 — math correction
- Code: rewrite `compute_pair_stats` body:
  - `la = np.log(aligned["a"].values)`, `lb = np.log(aligned["b"].values)`
  - OLS on `(la, lb)` (still stored as `hedge_ratio` — log-space β now)
  - `from statsmodels.tsa.stattools import coint`
  - `coint_t, coint_p, _ = coint(lb, la, trend='c', autolag='AIC')` → use `coint_p` and `coint_t`
  - `TEST_METHOD = "eg_mackinnon"`
  - Output dict: `"methodology_version": "v2_log_eg"`
- Tests update:
  - `test_required_constants` → `TEST_METHOD == "eg_mackinnon"`
  - `test_cointegrated_pair_passes_adf`: rewrite synthetic to log-cointegrated (`b = a * exp(noise)` instead of `b = 2*a + noise`); assert `hedge_ratio ≈ 1.0`; assert p < 0.01.
  - `test_random_walk_pair_fails_adf` — should still pass; EG p-values for two independent log-RWs are still high.
  - Add `test_hysteresis_resets_at_methodology_cutover` per §4.
  - Add `test_v2_pvalue_higher_than_v1_on_real_data` (optional sanity check using a fixed real-data fixture).
- Break-test (see §7) runs as part of this commit.

### C4 — rendering + memory
- `cointegration_excel.py`: surface `methodology_version` column + tab header note (§3.4).
- RESEARCH_MEMORY entry: methodology correction, pipeline-grade now (via the next screener run from C3).
- Auto-memory: replace the PROVISIONAL `cointegration_methodology_audit` entry with the v2-grounded version once the first v2 run completes.

---

## 6. What this session does NOT do

| Concern | Why deferred |
|---|---|
| **FDR (BH or Bonferroni)** | Yesterday's audit showed FDR α=0.05 zeroes the universe. That's a policy decision distinct from the math correction. Operator chose to land math-correctness without the policy bundled. FDR can ship later behind a `--methodology v3_log_eg_fdr` flag once the policy is settled. |
| **Corpus rebuild** | Operator decision: keep 339 legacy episodes, tag them, no re-screen. Yesterday's verdict ("rebuild not justified for info-gain") still holds. |
| **Strategy/episode/window/β edits** | Out of scope. β is stored unused. Strategy is 1:1 lot ratio. |
| **Repromoting the "weak concept" conclusion** | Yesterday's `cointegration-as-screen is weak at 1d×252` is still PROVISIONAL until the v2 screener writes pipeline-grade rows. Pipeline-Authoritative Conclusions (#31). |
| **Aggregator / episode builder / backtester** | They read `adf_pvalue` and `methodology_version` (after C2); no other dependency on the math change. |
| **Half-life** | Computed off the OU fit of the spread. Spread is now log-spread instead of price-spread — half-life is in *log-return half-life* units, not price half-life. Numerically different but semantically the same "speed of mean reversion." Document the unit change in code comment. |

---

## 7. Break-test plan (runs in C3)

Before declaring C3 done, exercise:

1. **Random-walk pair** (independent log-RWs): v2 p > 0.10, regime ∈ {breaking, broken}.
2. **Strongly log-cointegrated pair** (`b = a * exp(stationary_noise)`): v2 p < 0.01, regime = cointegrated, hedge_ratio ≈ 1.0.
3. **Level-cointegrated but NOT log-cointegrated** (`b = 100 + 2*a + noise`): v1 would pass at p<0.05; v2 may or may not (this is the math-difference probe). Document the outcome — establishes that v2 is a strictly different test, not just rescaled.
4. **Extreme-scale pair** (XAU ~3500 vs EURUSD ~1.05): log normalization should make β meaningful. Smoke-test on real data.
5. **NaN / empty-alignment handling** unchanged: `< lookback//2` rejects to None.
6. **Sanity-check against the audit:** run the v2 screener on the full 1d×252 universe; the audit reported ~84 qualified pairs at p<0.05. The new count should land in roughly the same neighborhood. This is an investigation trigger, not a hard contract — autolag selection and any data shift since the audit can move the number, so small deviations (single-digit, low-teens) are informational. A *wildly* different result (order-of-magnitude off — e.g. 0, <30, or >150) is a signal that something is wrong; pause and investigate before C4.

---

## 8. Future v3 placeholders (NOT in scope, but the column makes them cheap)

| Variant | methodology_version | Trigger |
|---|---|---|
| v3 EG + BH-FDR α=0.05 | `v3_log_eg_fdr_05` | Operator decision to operationalize family-wide correction |
| v3 EG + half-life gate | `v3_log_eg_hl_gate` | If we want to filter on mean-reversion speed |
| v4 Johansen | `v4_johansen` | If we revisit cointegration as a primary signal class |

These exist only as label conventions — no code, no plan, no implication. The `methodology_version` column makes adding any of them a clean tagged-cohort question rather than a corpus-rebuild question.

---

## 9. Open question for the next session (not blocking C1-C4)

After C3 lands and the first v2 screener run completes, the **PROVISIONAL** memory entry `project_cointegration_methodology_audit.md` should be reproduced through the pipeline (Invariant #31). The expected output: ~84 v2-qualified pairs at 1d×252, audit's class-wise decomposition reproducible. If reproduced, the "cointegration-as-screen at 1d×252 is genuinely weak" conclusion is promoted from PROVISIONAL → confirmed. If not reproduced, investigate before promoting.

This is a separate work item — flag at session-close, don't bundle into C4.
