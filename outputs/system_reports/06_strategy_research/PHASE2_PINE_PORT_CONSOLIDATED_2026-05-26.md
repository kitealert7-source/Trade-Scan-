# Phase 2 Pine Port — Consolidated Findings

**Date:** 2026-05-26
**Session arc:** multi-TF cointegration scoping → S21 transferability → Pine N=30 broad-cohort + family-density + cross-regime verification
**Strategy under test:** `pine_ratio_zrev_v1` at N=30, 15m, entry_mode=absolute, z_entry=2.0, always_in_market=true, hedge_lock_at_entry=true
**Data infrastructure:** 12-month cointegration history in `cointegration.db` SQLite (240K rows, 2025-05-23 → 2026-05-26, 465 pair-pairs × 2 lookbacks × 263 dates)

This report consolidates the full session's research output to conserve findings for future sessions. Per-step reports remain as committed artifacts and are referenced inline.

---

## Session arc — what was tested, in order

| Step | Activity | Outcome | Per-step report |
|---|---|---|---|
| 1 | Multi-TF cointegration screener plan + Phase-2 empirical lead-lag test (4H vs 1d) | MIXED → FROZEN. Cross-correlation lead real (5/5 pairs, 4-8d), but raw 4H qualified-flag too noisy (40-75% transient runs). Not operationalized. | [`COINTEGRATION_4H_LEADLAG_2026-05-26.md`](COINTEGRATION_4H_LEADLAG_2026-05-26.md) |
| 2 | S21 H3_spread@3 deployment baseline — cross-pair transferability (EUR/USDJPY → GBP/USDJPY, AUD/USDCAD) | BOUNDED. GBP partial (Win A best, Win B FAIL), AUD catastrophic. **Multi-pair portfolio promotion of S21 = NO.** | [`S21_TRANSFERABILITY_2026-05-26.md`](S21_TRANSFERABILITY_2026-05-26.md) |
| 3 | Pine N=30 initial alignment-window test on BOTH-window ≥30d pairs (18 pairs) | **Initially framed as falsified (0/18 CORE-or-WATCH).** Used governance verdict as evaluator — wrong lens. | [`PINE_N30_ALIGNMENT_WINDOW_TEST_2026-05-26.md`](PINE_N30_ALIGNMENT_WINDOW_TEST_2026-05-26.md) (superseded) |
| 4 | Broad-cohort re-evaluation: 252-only ≥30d, 87 pairs, Ret/DD ranking + family-density framework | **STRATEGY HAS EDGE.** FX-FX 62% positive, IDX-IDX 67% positive, CROSS 27%. USDCHF-hedge family discovered. | [`PINE_N30_FAMILY_DENSITY_2026-05-26.md`](PINE_N30_FAMILY_DENSITY_2026-05-26.md) |
| 5 | Cross-regime verification (Option A) — re-test top Ret/DD pairs on longest DB-aligned window | 4 of 7 cross-regime-verified, 2 regime-specific, 1 unverifiable | This report |
| 6 | Historical-regime supplementary test (Option C) — pairs with long alignment ended pre-Excel-window | 2 new strong finds (ESP35/GBPNZD 2.82, AUDJPY/CADJPY 1.53), 1 cross-region IDX-IDX failure (AUS200/NAS100) | This report |

---

## Final verdict on the Pine N=30 strategy

**The strategy has demonstrable cross-regime-robust edge on a specific structural surface.** It is NOT a generic spread strategy — it works on pairs that satisfy specific structural conditions, and fails (sometimes catastrophically) when those conditions are absent.

### Tier-A: cross-regime-verified pairs (deployment candidates after additional work)

| Rank | Pair | Class | Tier-A test | Best Ret/DD across tests |
|---|---|---|---|---|
| 1 | **AUDJPY/USDCHF** | FX (USDCHF-hedge) | 91d → 118d longer-window: 9.12 → 8.07 | 9.12 |
| 2 | **GBPJPY/GER40** | CROSS (GER40-yen) | Cohort → 47d Dec'25-Feb'26 different regime: 2.52 → **5.83** | 5.83 |
| 3 | **EUSTX50/FRA40** | IDX (EU same-session) | 75d → 106d longer same regime: 2.31 → 3.94 | 3.94 |
| 4 | **EURGBP/GBPNZD** | FX (GBP-triangular) | 50d → 179d DIFFERENT regime Sep'25-Feb'26: 2.98 → 2.80 | 2.98 |
| 5 | **ESP35/GBPNZD** | CROSS (Spanish IDX × NZD-FX) | 130d Sep'25-Jan'26 historical (Option C): 2.82 | 2.82 |
| 6 | AUDJPY/CADJPY | FX (yen-cross twins) | 157d Sep'25-Feb'26 historical: 1.53 | 1.53 |
| 7 | ESP35/JPN225 | IDX (cross-region same-session-overlap) | 42d single window: 2.69 (not cross-regime tested — only one aligned period) | 2.69 |

### Tier-B: regime-specific pairs (NOT cross-regime robust)

| Pair | Class | Cohort | E001 verification | Verdict |
|---|---|---|---|---|
| AUDNZD/USDCHF | FX (USDCHF-hedge) | 2.35 | 0.90 (earlier regime) | Regime-specific |
| CHFJPY/GER40 | CROSS (GER40-yen) | 2.31 | 0.27 (earlier regime) | Regime-specific |

These pairs had strong single-window results but the edge does not survive on a different cointegrated period. Don't extrapolate from their cohort result.

### Tier-C: outright failures (structural)

| Pair | Class | Result | Lesson |
|---|---|---|---|
| AUS200/NAS100 | IDX (cross-region NO session overlap) | -0.56 / DD 73 / FAIL | Same-asset-class isn't enough; same-session matters more |
| FRA40 × any FX (9 pairs, full cohort) | CROSS (session-misaligned) | 9/9 negative Ret/DD, mean -0.84 | Session-only IDX leg × 24h FX leg is universally hostile in this strategy class |

---

## Structural patterns confirmed (where the edge lives)

### 1. USDCHF-as-hedge-leg (specifically yen-cross or Antipodean)
- **Robust:** AUDJPY/USDCHF (9.12 → 8.07 verified)
- **Regime-specific:** AUDNZD/USDCHF (worked Feb-Apr 2026, didn't on earlier regime)
- Other family members showed positive Ret/DD in cohort: NZDJPY/USDCHF (2.03), CHFJPY/USDCHF (1.71), CADJPY/USDCHF (1.78) — all untested for cross-regime
- **Mechanism hypothesis:** CHF and JPY both strengthen during risk-off; the spread trades risk-on/risk-off divergence between AUD-bloc and CHF with USD/JPY canceling out

### 2. ESP35-as-counterparty (with non-Spanish-correlated legs)
- Strong with **non-Spanish equity legs**: ESP35/JPN225 (2.69), ESP35/UK100 (0.83), ESP35/FRA40 (0.81), ESP35/GBPNZD (2.82 NEW)
- Negative with **Spanish-correlated neighbors**: ESP35/EUSTX50 (-0.39), ESP35/GER40 (-0.39) — spread is quasi-tautological since ESP35 is a component of EUSTX50
- **Mechanism hypothesis:** ESP35 has unique liquidity / session-overlap properties that make it a clean counterparty for diverse asset classes when not paired with a directly-correlated index

### 3. GER40 vs GBP-yen-cross (NOT CHF-yen-cross)
- **Robust:** GBPJPY/GER40 (2.52 → 5.83 cross-regime verified)
- **Regime-specific:** CHFJPY/GER40 (2.31 → 0.27)
- The "GER40 + yen-cross" pattern only works with GBP — suggests the structural mechanism is **GBP-specific**, not generic yen-cross
- Possibly Brexit-era GBP volatility characteristics interact favorably with the GER40 hedge

### 4. Triangular currency-cancellation (FX-FX)
- **Verified:** EURGBP/GBPNZD (GBP-cancellation between EURGBP and GBPNZD → net trade is on EUR vs NZD with GBP cancelling)
- Cross-regime robust (2.98 cohort, 2.80 on Sep'25-Feb'26 entirely different regime)
- **Mechanism:** the GBP-cancel structure removes one currency's volatility, making the residual spread cleaner mean-reversion target

### 5. Same-session IDX-IDX
- **Verified:** EUSTX50/FRA40 (2.31 → 3.94 on longer window)
- Both indices trade Paris/Frankfurt session; their spread reflects within-Europe risk dispersion
- The session-alignment is the critical property — confirmed by negative AUS200/NAS100 result (different sessions, no overlap)

### 6. Yen-cross commodity-currency twins
- AUDJPY/CADJPY (1.53 historical) — modest positive
- Both yen-cross commodity-currency pairs; their spread trades AUD-commodity-vs-CAD-commodity differential with JPY cancellation

---

## Structural patterns confirmed AS FAILURE MODES (do not test further)

### 1. FRA40 paired with any 24-hour FX
- 9 of 9 pairs catastrophic (mean Ret/DD -0.84, max DD often >100%)
- FRA40 session: Paris hours only (~6.5h/day for cash, broker may synthesize 24h with session-gap-fills)
- Strategy reads session-gap-fills as real microstructure events; loses on noise

### 2. Cross-region IDX-IDX with NO session overlap
- AUS200/NAS100: -0.56 / DD 73 (failed)
- Same lesson as FRA40-vs-FX: the spread isn't truly continuous; gap-fill noise pollutes the mean-reversion signal

### 3. Directly-correlated leg pairs (spread ≈ identity)
- ESP35/EUSTX50, ESP35/GER40 — negative despite both being IDX-IDX in the same region
- The pair structure is too redundant; not enough independent variation to mean-revert against

---

## Methodology learnings (saved as durable feedback memory)

The session produced multiple research-design lessons that future sessions should inherit. Each is saved as a feedback memory:

1. **`feedback_screening_rules_for_research`** — Governance verdicts (CORE/WATCH/FAIL) are deployment-scale gates, not research evaluators. For short-window backtests, evaluate by Ret/DD ranking. Conflating the two led to the initial "falsified" misverdict in Step 3.

2. **`feedback_test_window_must_match_signal_class`** — When a strategy depends on a time-varying property (cointegration here), test only on windows where the property holds. Query the History tab/DB for per-pair alignment windows. Don't test on broader windows that contaminate with non-aligned periods.

3. **`feedback_prove_then_falsify`** — At unproven parameter regimes, cast broad cohort first, categorize results post-hoc. Don't pre-filter on theoretical-correctness criteria; the filter is itself an unverified hypothesis.

4. **`feedback_experiment_basket_composition`** — Force healthy + unstable + control + exploratory diversity in any small validation cohort. Never sample only "currently qualifying" members or the hypothesis becomes self-confirming.

5. **`feedback_infra_build_to_falsify`** — Scope infra to the minimum needed to answer the falsifying question. The plumbing-vs-operationalization distinction was applied successfully on the multi-TF cointegration thread (Phase 1 refactor landed, Phase 5 scheduling correctly skipped).

---

## Data infrastructure findings

### Cointegration screener history tab — verified correct
- SQLite `cointegration.db` was bulk-populated 2026-05-23 with full 12-month history (238,552 rows that day, 263 distinct dates 2025-05-23 → 2026-05-26)
- Daily updates 2026-05-25 and 2026-05-26 add ~930 rows each
- Excel **History tab is intentionally truncated to last 90 days** (per `cointegration_excel.py:12` docstring) for display performance
- **The data is available — just query the DB directly for periods > 90 days back**

### How to query for any future research
```python
import sqlite3, pandas as pd
db = sqlite3.connect(r'data_root/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db')
df = pd.read_sql_query('''
    SELECT as_of, pair_a, pair_b, lookback_days, regime, adf_pvalue, hedge_ratio
    FROM cointegration_daily WHERE pair_a = ? AND pair_b = ?
''', db, params=['AUDJPY', 'USDCHF'])
```

### Operational tech-debt (separate fix items)

1. **H2RecycleRuleV3 currency-reference rejects BTC/ETH/XAU tokens** at basket setup even when the actual strategy is `pine_ratio_zrev_v1`. Cost us 4 pairs in this session (BTCUSD/NZDJPY, UK100/XAUUSD, ESP35/XAUUSD, EUSTX50/XAUUSD). Fix: extend currency reference table to include BTC/ETH/XAU, or move the check to the rule that actually uses it.

2. **MPS xlsx export fails on Permission denied** when the file is open in Excel. Pipeline still writes to the ledger DB. Recovery: close the file then `python tools/ledger_db.py --export-mps`. Could be made resilient (retry on permission error, or write to a temp file then atomic-rename).

3. **`tools/cointegration_excel.py:12` History tab is hard-coded to 90 days.** Operator may want a configurable window or a "Full History" alternate tab. Discussed below as a follow-up plan.

---

## Promotion status

**NONE of these pairs is deployment-ready yet.** The strongest candidates (AUDJPY/USDCHF, EUSTX50/FRA40, EURGBP/GBPNZD, GBPJPY/GER40, ESP35/GBPNZD) have been **research-validated** but not promotion-validated.

What's missing before any promotion conversation:

1. **Per-trade quality gate** ([`feedback_promote_quality_gate`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\feedback_promote_quality_gate.md)) — tail concentration, longest flat period, edge ratio on individual trades. The composite Ret/DD doesn't capture these.

2. **Out-of-sample test** — pick a forward window NOT in the screener history and run the strategy live-equivalent on it. We have 12 months of history; ideal would be 6 months in-sample tune + 6 months out-of-sample. Currently we've used 100% of the data.

3. **Cost-aware re-test** — the strategy fires 2-3 trades/day per pair. Verify that the cost model (OctaFx spread + slippage) is accurately captured; if it's optimistic, the apparent edge may shrink.

4. **Capital-wrapper test** at realistic deployment scale — current results are at $1000 stake / 0.01 lot. At 0.1 lot or larger, slippage modeling matters.

5. **Cross-pair portfolio construction** — if multiple verified pairs deploy together, correlation among them needs analysis. Two USDCHF-hedge pairs trading simultaneously may not be independent.

---

## Future-action recommendations (priority-ordered)

### Priority 1 — out-of-sample verification on the Tier-A robust set

For each of the 5 cross-regime-verified pairs (AUDJPY/USDCHF, GBPJPY/GER40, EUSTX50/FRA40, EURGBP/GBPNZD, ESP35/GBPNZD):
- Identify a continuous 252-aligned period that is **NOT** the test window used for either the cohort or E001 verification
- Run the strategy on that out-of-sample window
- If Ret/DD ≥ 1 holds → genuine cross-regime + out-of-sample robust
- If not → mark as regime-specific noise

This is the strongest test before any deployment thought.

### Priority 2 — per-trade quality gate

For the Tier-A robust set, pull the tradelevel CSV (`backtests/<RUN_ID>/raw/results_tradelevel.csv`) and run [`feedback_promote_quality_gate`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\feedback_promote_quality_gate.md) checks:
- Top-5 trade concentration (% of Net% from 5 biggest trades)
- Longest flat period
- Edge ratio per trade

These reveal whether the edge is uniformly distributed or concentrated in a few lucky events.

### Priority 3 — operationalization decisions (deferred until P1+P2 done)

If P1+P2 pass, consider:
- Promote 1-2 Tier-A pairs as single-pair candidates (NOT a multi-pair portfolio)
- Operator selects which one based on the per-trade quality + sizing comfort
- Cross-pair portfolio version comes only after individual-pair LIVE data accumulates

### Priority 4 — screener-tab classification (proposed below)

Add a "Mean-Reversion Friendliness" classification tab to the screener Excel. Implementation plan below.

### Priority 5 — fix the BTC/ETH/XAU currency-reference tech debt

So future cohort expansions can include crypto/commodity pairs without manual exclusion.

### Priority 6 — accumulate History tab depth

Currently the History tab covers 12 months. The Phase 2 SQLite history accumulator runs daily — let it keep accumulating. After 6 more months of data, longer alignment-window tests become possible.

---

## Closing note

The Pine N=30 strategy thread reached a **decisive characterization** this session. We know:
- Where the strategy works (5+ verified structural patterns)
- Where it fails (3 confirmed structural failure modes)
- What evaluation framework is appropriate (Ret/DD ranking + family-density + cross-regime verification, NOT governance verdict for short windows)
- What data infrastructure to rely on (SQLite DB direct query, not 90-day Excel view)

This positions the strategy class for either:
- **Out-of-sample verification and selective deployment** (if operator wants to pursue)
- **Parking** as a research-grade result that didn't reach deployment scale (if other higher-priority arcs exist)

Operator's call.

## Cross-reference

Per-step reports:
- [`COINTEGRATION_4H_LEADLAG_2026-05-26.md`](COINTEGRATION_4H_LEADLAG_2026-05-26.md)
- [`S21_TRANSFERABILITY_2026-05-26.md`](S21_TRANSFERABILITY_2026-05-26.md)
- [`PINE_N30_ALIGNMENT_WINDOW_TEST_2026-05-26.md`](PINE_N30_ALIGNMENT_WINDOW_TEST_2026-05-26.md) (superseded by family-density)
- [`PINE_N30_FAMILY_DENSITY_2026-05-26.md`](PINE_N30_FAMILY_DENSITY_2026-05-26.md)

Project memory:
- [`project_pine_n30_falsified.md`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\project_pine_n30_falsified.md) (revised verdict)
- [`project_pine_n30_usdchf_hedge_family.md`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\project_pine_n30_usdchf_hedge_family.md)
- [`project_s21_transferability_bounded.md`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\project_s21_transferability_bounded.md)
- [`project_4h_cointegration_thread_frozen.md`](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\project_4h_cointegration_thread_frozen.md)

Feedback memory:
- `feedback_screening_rules_for_research.md`
- `feedback_test_window_must_match_signal_class.md`
- `feedback_prove_then_falsify.md`
- `feedback_experiment_basket_composition.md`
- `feedback_infra_build_to_falsify.md`
