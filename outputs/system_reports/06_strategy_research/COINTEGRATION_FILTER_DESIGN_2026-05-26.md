# Cointegration Filter Design — Notes for 2026-05-27 Continuity

**Author session:** 2026-05-26 (post `/session-close` continuity note)
**Decision pending:** How to use the cointegration screener as a pair-selection filter for `pine_ratio_zrev_v1` (15m × N=30) tomorrow.
**Status:** Strategy plan was firmed up to *dual-TF cointegration confirmation* as a pair filter; two ADF-math issues then surfaced that meaningfully change the threshold semantics and the resulting cohort sizes.

---

## TL;DR

1. **The screener's ADF math has two known biases** that systematically *over-identify* cointegration. Standard ADF p-values applied to OLS residuals (Issue 1) and raw prices instead of log prices (Issue 2). Both push reported p-values **4-5× smaller than the true Engle-Granger p**.
2. **Practical translation:** current `p < 0.05` is roughly **true p < 0.20** under correct math. Current `p < 0.01` is roughly **true p < 0.05**. Use `p < 0.01` as the effective filter cutoff without rewriting the screener.
3. **The dual-TF filter (1d × 252 AND 4h × 1500) shrinks the cohort drastically.** At `p < 0.01` dual-TF: **3 pairs** in the current data. At `p < 0.05` dual-TF: 7 pairs. At `p < 0.001`: zero.
4. **Recommended re-frame for tomorrow:**
   - **Thread A (cohort-statistical):** 1d-only filter at `p < 0.05` → ~30-40 of the 87 Pine pairs, enough sample for "filtered vs baseline" comparison.
   - **Thread B (per-pair high-conviction):** dual-TF at `p < 0.01` → 3-7 pairs, treated as individual deep-dive candidates.
   - **Do NOT do "dual-TF p<0.01 as cohort claim"** — sample size is too small for statistical inference.

---

## 1. Original plan that triggered this analysis

The 2026-05-26 highlighted Pine reports in `outputs/system_reports/06_strategy_research/`:

- `PHASE2_PINE_PORT_CONSOLIDATED_2026-05-26.md` — Priority 1 next step
- `PINE_N30_FAMILY_DENSITY_2026-05-26.md` — 62% FX-FX positive, 67% IDX-IDX positive on 87-pair broad cohort
- `PINE_N30_ALIGNMENT_WINDOW_TEST_2026-05-26.md` — methodology test

Plan (decided 2026-05-26 evening):
- Use 4h cointegration backfill data (completes ~2026-05-27 morning) as a **pair-selection filter**, not for entry timing.
- Require cointegration at BOTH `1d × 252-bar` AND `4h × 1500-bar` (both ≈ 1-year calendar windows).
- Strategy execution unchanged: `pine_ratio_zrev_v1` at 15m × N=30.
- Rationale: dual-TF confirmation reduces false positives from single-TF cointegration flukes. Backfill coverage will be ~17 months by morning — sufficient for 1500-bar (~1y) lookback.

Then while pre-committing the threshold, the question "is the screener's ADF math doing what we think it's doing?" surfaced two issues.

---

## 2. Two ADF math issues in `tools/cointegration_screen.py`

### Issue 1 — Standard ADF p-values applied to OLS residuals (high severity)

Around line 203-216:

```python
# --- OLS hedge ratio: B = α + β·A + ε
X = sm.add_constant(a_vals)
ols = sm.OLS(b_vals, X).fit()
spread = b_vals - beta * a_vals

# --- ADF test on the spread
adf_result = adfuller(spread, autolag="AIC")     # <-- standard ADF critical values
```

This is the **Engle-Granger 2-step procedure** but uses **standard ADF critical values**. OLS pre-estimation makes residuals more stationary-looking than randomly-observed series → standard ADF rejects too often.

**Correct fix:** use `statsmodels.tsa.stattools.coint(a_vals, b_vals, autolag="AIC")` which applies MacKinnon (1996) Engle-Granger critical values.

### Issue 2 — Raw prices, not log prices (high severity for cross-scale pairs)

Same function uses RAW closes:

```python
ols = sm.OLS(b_vals, X).fit()       # b_vals, a_vals = raw closes
```

For pairs with similar scales (FX/FX, IDX/IDX) the numerical effect is small. For different-scale pairs (BTC ≈ 76,000 vs NZDJPY ≈ 93) the β degenerates to ~−0.0001, making the "spread" essentially one leg with a trivial correction — the ADF test reduces to single-asset stationarity testing.

**Diagnostic evidence within the same module:** `compute_single_series_adf` at line 290 already uses log prices for single-asset stationarity (`log_close = np.log(series.values)`). The pair function is inconsistent with the single-asset function in the same file.

**Correct fix:** transform to log prices before OLS:

```python
a_vals = np.log(aligned["a"].values)
b_vals = np.log(aligned["b"].values)
```

### Bias direction (both issues)

Both biases push toward **over-identifying** cointegration. Combined, the reported `adf_pvalue` is systematically smaller than the true Engle-Granger p-value.

---

## 3. Quantitative bias estimate (Issue 1 only; Issue 2 is pair-specific)

Based on MacKinnon (1996) critical values vs standard ADF tables, the t-statistic gap is roughly **constant at ~0.5σ** between the two distributions. Translation:

| Current screener reports | True Engle-Granger p-value | Multiplier |
|---|---|---|
| p = 0.05 | ~0.15-0.20 | **3-4×** |
| p = 0.01 | ~0.04-0.05 | **4-5×** |
| p = 0.001 | ~0.008-0.012 | **8-10×** |
| p = 0.0001 | ~0.0015-0.002 | **15-20×** |

The multiplier grows in the tail because the critical-value gap is fixed in t-stat units but p-values are exponentially sensitive there.

**Effective threshold remap (use without rewriting the screener):**

| Current threshold | ≈ Equivalent under correct math |
|---|---|
| p < 0.05 | p < 0.20 (loose) |
| p < 0.01 | p < 0.05 (conventional) |
| p < 0.005 | p < 0.02 (tight) |
| p < 0.001 | p < 0.01 (very tight) |

**Practical recommendation:** treat `p < 0.01` on the current screener as the effective "conventional cointegration" threshold. `p < 0.05` is approximately "interesting candidate" not "cointegrated."

Issue 2 (log vs raw) adds pair-specific bias on top of this — small for FX-FX (mostly similar scales), large for cross-asset pairs (BTC, ETH, gold vs FX).

---

## 4. Empirical cohort sizes at each threshold (queried 2026-05-26 evening)

Source: `Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db`. 1d × 252 as_of 2026-05-26 (full universe). 4h × 1500 as_of 2025-04-18 (most-recent fully-populated; backfill incomplete).

### 1d × 252 (as_of 2026-05-26, 406 pair-pairs)

| Threshold | Pairs | % of universe |
|---|---:|---:|
| p < 0.001 | 5 | 1.2% |
| p < 0.005 | 39 | 9.6% |
| **p < 0.01** | **64** | **15.8%** |
| p < 0.05 | 127 | 31.3% |
| p < 0.10 | 171 | 42.1% |

### 4h × 1500 (as_of 2025-04-18, 190 pair-pairs available)

| Threshold | Pairs | % of universe |
|---|---:|---:|
| p < 0.001 | 0 | 0.0% |
| p < 0.005 | 2 | 1.1% |
| **p < 0.01** | **5** | **2.6%** |
| p < 0.05 | 9 | 4.7% |
| p < 0.10 | 14 | 7.4% |

**Note:** the 4h universe will grow toward ~435 once the backfill completes overnight; linear extrapolation suggests ~12 pairs at p < 0.01 and ~21 at p < 0.05 in the final 4h-complete universe.

### Dual-TF intersection (as_of 2025-04-18, the binding 4h-completion date)

| Threshold | Intersection |
|---|---:|
| p < 0.001 BOTH | **0** |
| p < 0.005 BOTH | 2 |
| **p < 0.01 BOTH** | **3** |
| p < 0.05 BOTH | 7 |
| p < 0.10 BOTH | 12 |

**Linear extrapolation to post-backfill universe (4h ~435 pairs):** ~7 at p<0.01 dual-TF; ~16 at p<0.05 dual-TF.

---

## 5. Two-thread re-frame for tomorrow

The cohort-size data forces a split because a single filter can't serve both "statistical inference" and "deployment shortlist":

### Thread A — Cohort-statistical comparison

**Purpose:** answer "does cointegration filtering add edge to `pine_ratio_zrev_v1`?"

- **Filter:** 1d × 252 only, `p < 0.05`.
- **Expected cohort:** ~30-40 of the 87 Pine pairs.
- **Sample size:** enough for "filtered cohort vs broad-cohort baseline" comparison (mean Ret/DD, positive-rate, top-pair Ret/DD).
- **Pre-committed eval criterion:**
  > Filter is valid IFF filtered-cohort mean Ret/DD > broad-cohort mean Ret/DD by ≥ 1.0 (Ret/DD units). Equal or worse → cointegration is the wrong screen, defer dual-TF work.

### Thread B — Per-pair deep-dive

**Purpose:** identify a small set of high-conviction candidates for deployment-quality backtesting.

- **Filter:** dual-TF (1d × 252 AND 4h × 1500), `p < 0.01` on both.
- **Expected cohort:** ~3-7 pairs post-backfill-completion.
- **No cohort-level metric.** Each pair is analyzed individually: full Pine N=30 backtest, walk-forward, multi-window. Treated as a deployment shortlist, not a statistical claim.
- **Risk:** these pairs were never proven independently from the broad-cohort discovery. Per-pair edge may be coincidental.

### What NOT to do

- **Dual-TF + p<0.01 + cohort-mean Ret/DD claim.** With 3-7 pairs, confidence intervals dominate any cohort metric. The result is non-actionable either way.
- **Dual-TF + p<0.001.** Zero pairs survive (per current data). Empty cohort.
- **Cite p<0.001 as "exceptional" evidence.** Under correct math that's only ~p=0.01 — strong but not exceptional.

---

## 6. Open questions / next-session checklist

In priority order for 2026-05-27:

| # | Task | Why it matters |
|---|---|---|
| 1 | Verify 4h backfill completion (PID 32516 done; coverage reaches 2026-05-26) | Both threads depend on full universe (~435 pair-pairs). |
| 2 | Spot-check 20 representative pairs with corrected math (`statsmodels.coint()` + log prices). Compare verdicts vs current numbers. | Validates the 4-5× bias estimate empirically. ~30 min cost. |
| 3 | Decide: Thread A only, Thread B only, or both? | Drives the work plan. |
| 4 | If Thread A: re-query 1d × 252 p<0.05 cohort on full universe. Cross-reference with the 87 Pine pairs (need to confirm which 87). | Get the actual filtered cohort. |
| 5 | If Thread B: pull the actual pair names that pass dual-TF p<0.01. | Concrete shortlist for backtesting. |
| 6 | Document the chosen threshold + filter design in RESEARCH_MEMORY as a single new entry. | Continuity for the next session. |

**Open infra question (low priority):** is the screener math worth fixing? See §7.

---

## 7. Screener math fix — scope + cost

**Cost to fix:** ~10-line code change in `tools/cointegration_screen.py` (use `statsmodels.coint()` + log prices). Trivial.

**Cost to re-run:** **same as current backfill — ~14 hours on 4h, ~1-2 hours on 1d.** Every existing row's `adf_pvalue`, `adf_statistic`, `hedge_ratio`, `regime` becomes invalid.

**Cost to migrate research records:** the 2026-05-21 COINTREV v1 retirement basis + the 2026-05-24 v1.2 retirement basis + the BTC/NZDJPY surprise finding + the yen-cross/XAU cluster all sit on current (biased) numbers. Each needs re-evaluation under new math.

**Recommendation:** **don't fix yet.** Tomorrow's plan can proceed on the effective-threshold remap (use `p<0.01` as the actual cutoff). The full math fix + re-compute + research-record migration is its own dedicated session, not folded into tomorrow's strategy work.

**Trigger for prioritizing the fix:** if the spot-check (task #2 above) shows >25% verdict flips at the p<0.01 threshold, escalate to "fix before further cointegration-based research."

---

## 8. References

- Screener source: `tools/cointegration_screen.py` (Issues 1+2 at lines 203-216)
- DB: `Anti_Gravity_DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db`
- Pine N=30 broad cohort findings: `PINE_N30_FAMILY_DENSITY_2026-05-26.md` (same folder)
- USDCHF-hedge sub-family: `RESEARCH_MEMORY.md` 2026-05-26 entries (pre-compaction; some moved to archive)
- COINTREV retirement lineage (for the screener-strategy mismatch lesson): `RESEARCH_MEMORY_ARCHIVE.md` 2026-05-21 + 2026-05-24 entries
- MacKinnon (1996) critical values: `statsmodels.tsa.stattools.coint` source

---

## 9. Closing thought

The most important thing this analysis surfaced is **not the math bias** — it's that the dual-TF filter at sensible thresholds yields a tiny cohort. Even if the math were perfect, dual-TF + reasonable significance produces 3-15 pairs, not the 87-pair cohort the broad-test work was based on. This means the original plan ("use cointegration to confirm the Pine pair selection") was always going to encounter this — the math issues just made it visible sooner. Tomorrow's design must reckon with the cohort-size reality regardless of which p-value table we use.
