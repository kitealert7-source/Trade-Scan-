# RESEARCH MEMORY

FORMAT POLICY:
- Entries may be compacted for token efficiency; content is semantically identical
- Compaction does not violate the append-only rule
- Archive split enforced at 600 lines / 40 KB -> RESEARCH_MEMORY_ARCHIVE.md
- Tier A (3-line inline): simple findings, all sections ≤ 3 non-blank lines, no sub-lists
- Tier B (label-free paragraphs): complex entries, labels removed, paragraph structure kept
- Pre-2026-04-07 entries live in RESEARCH_MEMORY_ARCHIVE.md (compacted)

THIS FILE IS APPEND-ONLY. Corrections are new entries, not edits.
Post-contract entries must conform to the NEW ENTRY CONTRACT template.

---
2026-04-07 | Tags: burn_in_live_validation, fx_mean_reversion_friction, strategy_selection_criteria | Strategy: 22_CONT_FX / 15_MR_FX (portfolio-level finding) | Run IDs: 20260406T170841Z_41372, 20260406T095611Z_14752

FX mean-reversion and short-hold continuation strategies (M15, max_bars=3) show near-zero
or negative expected value under real spreads in burn-in. Backtest expectancy of $0.04-0.09
per trade is too thin to survive real-world friction. High win rates (79-82%) mask
unfavorable reward/risk ratios (0.09-0.19).
22_CONT_FX archive: 88 exits, 82% WR, avg win $0.0097, avg loss $0.0510, R:R 0.19, EV -$0.0013/trade.
XAU/BTC strategies: expectancy $2.18-5.30/trade, R:R ~1.0+, friction-resilient by construction.
FX M15 mean-reversion with 3-bar holds produces wins smaller than typical spread costs.
The strategies are structurally friction-fragile — the edge exists in backtest but is
consumed by bid-ask spread in live markets. Strategies with expectancy below ~$0.50/trade
on FX are unlikely to survive real execution.
1. FX research should pivot toward breakout/momentum strategies with wider stops and
   larger per-trade expectancy ($1+) that can absorb spread + slippage.
2. The 22_CONT_FX 30M variants (expectancy $0.10-0.23) are marginal — monitor but
   do not expect positive live performance.
3. XAU, BTC, and index strategies are inherently more friction-resilient due to higher
   tick values and larger price movements. Prioritize these asset classes for new research.
4. Minimum viable expectancy threshold for FX should be established (~$0.50/trade)
   as a pre-promotion gate to avoid wasting burn-in slots on friction-fragile strategies.
---
---
---

---
2026-04-07 | Tags: pipeline_gate_expectancy, candidate_filtration, capital_allocation_limits | Strategy: (portfolio-level — pipeline design) | Run IDs: 20260406T170841Z_41372, 20260406T095611Z_14752

Capital allocation (burn-in lot sizing at 1% risk on $10K notional) cannot compensate
for a strategy with insufficient per-trade expectancy. Backtest uses real spreads, yet
22_CONT_FX passed candidates with $0.04-0.07 expectancy — spreads were modeled but the
filter pipeline did not gate on absolute expectancy, only on PF/Sharpe/RetDD ratios.
22_CONT_FX M15 GBPUSD: backtest PF 1.19, 2858 trades, expectancy $0.06. Live burn-in: 0/4 WR, -$204.85 net.
15_MR_FX M15 AUDNZD: backtest PF 1.54, 437 trades, expectancy $0.09. Live burn-in: 2/4 WR, -$240.49 net.
Ratio-based filters (PF, Sharpe, Return/DD) pass strategies where the absolute dollar
edge per trade is too small to survive execution. A strategy can have PF 1.19 across
2858 trades and still be unviable — the edge is real but too thin. Capital allocation
scales position size, not the underlying edge quality.
1. Add a minimum absolute expectancy gate to the candidates filtration pipeline.
   Proposed thresholds: FX pairs >= $0.50/trade, XAU/BTC/Index >= $1.00/trade.
   This filters before burn-in, saving observation slots for viable strategies.
2. Existing ratio gates (PF >= 1.20, Sharpe, RetDD) remain necessary but are
   insufficient alone — they must be paired with the expectancy floor.
3. Strategies currently in BURN_IN with expectancy below threshold should complete
   their 90-trade cycle for data, but expectations should be set accordingly.
---
---
---

---
2026-04-07 | Tags: expectancy_threshold_calibration, candidate_gate_design, burn_in_evidence | Strategy: (portfolio-level — pipeline gate calibration) | Run IDs: 20260406T170841Z_41372, 20260406T095611Z_14752

Burn-in data across 12 strategies with live exits shows a clear dividing line: every FX
strategy with backtest expectancy below $0.10/trade is negative in live (7/8, the one
exception is likely noise at n=7). XAU strategies with $2-5 expectancy show negative on
n=1-2 trades each — too small to judge. No live data yet in the $0.10-$1.00 range.
BT exp <$0.10: 8 strategies with live data, 7 negative. 22_CONT USDCHF: BT $0.06, live -$5.06/trade (n=28).
BT exp >$1.00: 4 strategies with live data, 1 positive (17_REV $1.33/trade n=2), 3 negative (n=1 each).
The failure zone for FX is definitively below $0.10/trade — spread costs alone consume the
edge. The viable zone boundary is somewhere between $0.10 and $1.00 but burn-in has no data
there yet. Sample sizes for XAU/BTC/Index are too small (n=1-2) to calibrate their threshold.
1. Implement minimum expectancy gate in candidates filtration pipeline NOW:
   - FX pairs: >= $0.25/trade (see 2026-04-07 threshold revision below)
   - XAU/BTC/Index: >= $1.50/trade (provisional, refine after 90-trade burn-in cycles)
2. These are first-pass thresholds. Refine as more burn-in data fills the $0.10-$1.00 gap.
3. Do NOT remove sub-threshold strategies from active burn-in — let them complete 90 trades
   to build the calibration dataset, but do not promote new sub-threshold strategies.
---
---
---

---
2026-04-07 | Tags: expectancy_threshold_revision, fx_strategy_viability, honest_research_gates | Strategy: (portfolio-level — pipeline gate revision) | Run IDs: 20260406T170841Z_41372, 20260406T095611Z_14752

Distribution analysis of all 124 FX strategies in Filtered_Strategies_Passed.xlsx shows
the maximum FX expectancy in the entire pool is $0.23 (22_CONT_FX_30M AUDJPY). Zero
strategies pass at $0.25. The $0.15-$0.23 range (18 strategies, 14.5%) represents the
best current FX research output — but burn-in evidence shows even $0.10 strategies fail
in live. Lowering the threshold to keep strategies alive would defeat the purpose.
124 FX strategies: 0 pass $0.25, 4 pass $0.20, 18 pass $0.15, 43 pass $0.10, 109 pass $0.05.
Best FX family: 22_CONT_FX_30M avg_exp=$0.14, max=$0.23. All tested <$0.10 strategies negative live.
The $0.25 threshold is correct and should not be lowered to accommodate existing strategies.
If current FX archetypes cannot meet the bar, that is an honest signal that the research
direction must change — not that the bar should be bent. The gate exists to prevent
wasting burn-in slots and capital on friction-fragile strategies.
1. FX expectancy gate stays at $0.25/trade. This currently eliminates all 124 FX strategies.
   That is the intended outcome — it forces research toward higher-expectancy FX archetypes
   (breakout, momentum, structure) with wider risk distances and larger per-trade targets.
2. Current FX burn-ins complete their 90-trade cycle for calibration data only.
   No new FX strategies below $0.25 enter burn-in.
3. XAU/BTC/Index gate remains $1.50/trade (provisional). These asset classes have
   demonstrated viable expectancy ranges ($2-5+/trade) in existing research.
---
---
---

---
2026-04-07 | Tags: candidate_status_gates, expectancy_tiered_pipeline, fx_status_criteria | Strategy: (portfolio-level — pipeline status gates) | Run IDs: 20260406T170841Z_41372, 20260406T095611Z_14752

Tiered FX expectancy gates defined for the candidate pipeline, mapping each status level
to a minimum expectancy threshold. Gates are calibrated from burn-in evidence: all FX
strategies below $0.10 are confirmed negative in live, the $0.10-$0.25 range is marginal
with no positive evidence, and no existing FX strategy reaches $0.25.
124 FX strategies: 0 pass $0.25, 18 pass $0.15, 109 pass $0.05. All 8 tested below $0.10 negative live.
Current max FX expectancy: $0.23 (22_CONT_FX_30M AUDJPY). 100% of pool would be FAIL or WATCH.
FX candidate status gates (per-trade expectancy):
  FAIL:     < $0.15  — cull, doesn't survive friction
  WATCH:    $0.15 - $0.24  — worth monitoring, not ready for live test
  BURN_IN:  >= $0.25  — approved for live shadow observation
  CORE:     >= $0.25 + passed 90-trade burn-in gates (PF, WR, MaxDD, fill_rate)
XAU/BTC/Index gates (logic-driven, finalized 2026-04-07):
  Derivation: spread_cost_at_min_lot(class) / spread_cost_at_min_lot(FX) = ~3.3x multiplier.
    FX (EURUSD): 0.6 pips * $1000/PU @ 0.01 lot = $0.06
    XAU: $0.20 spread * $1.00/PU @ 0.01 lot = $0.20 (3.3x)
    BTC: $20 spread * $0.01/PU @ 0.01 lot = $0.20 (3.3x)
    INDEX (GER40): 2 pts * $0.115/PU @ 0.01 lot = $0.23 (3.8x)
  Slippage proportional to spread (microstructure principle). Conservative 3.0x applied.
  FAIL: XAU < $0.50, BTC < $0.50, INDEX < $0.50
  BURN_IN: XAU >= $0.80, BTC >= $0.80, INDEX >= $0.80
1. Apply these gates in filter_strategies.py as automatic candidate_status assignment.
2. Current FX pipeline output: 106 FAIL, 18 WATCH, 0 BURN_IN. This is correct —
   forces research pivot toward higher-expectancy FX archetypes before any reach burn-in.
3. Existing sub-threshold BURN_IN strategies complete their 90-trade cycle for data
   but are not replaced when done. New BURN_IN slots reserved for qualifying strategies.
---
---
---

---
2026-04-07 | Tags: regime_gate, pipeline_staging, OOS_validation, overfit, capital_wrapper | Run IDs: experiments/regime_gate_validation.py, experiments/results/regime_gate_validation.json
Regime gating (blocking trades in unprofitable regime cells) improves in-sample metrics but fails OOS stability — 0/5 active-gated portfolios survived 60/40 split. Direction reversal in all cases: blocked trades were losers in training but winners in OOS. In-sample: 5/9 improved, +$9525 total dPnL, avg PF +0.11, avg DD -0.45pp. OOS: 0/5 active stable; PF_7FCF1D2EB158 reversed from +$6420 IS to -$7360 OOS. Blocked OOS PnL was positive in all 5 cases ($1427, $455, $160, $52, $1143). REJECT for pipeline integration. Regime labels lack forward-predictive signal at current sample sizes (min_trades=10). Ordering confirmed: if ever used, gating must precede capital allocation (B != C in 5/5 active cases). Profile selection unaffected (0/9 changed). Stage 4 Regime Audit stays diagnostic/reporting only — never auto-block. If revisited: require min_trades >= 50, walk-forward validation, regime-cluster stability checks. Strategy Activation System remains valid as monitoring layer, not gating layer. --- ---.
---

---
2026-04-07 | Tags: regime_gate, activation, exposure_control, concurrency, pipeline_staging | Run IDs: experiments/regime_gate_validation.py, experiments/activation_vs_filtering.py, experiments/exposure_control_vs_activation.py, experiments/concurrency_diagnostics.py
Portfolio-level regime filtering, activation, and exposure control do not provide material improvement with current regime definitions. Regime buckets (vol, trend) are too coarse to partition trades into stable, behaviorally distinct populations. 3 experiments, 9 portfolios. Post-trade filtering: +$1058 avg IS but 0/5 OOS stable. Binary activation: -$3332 avg but 9/9 OOS stable (returns to baseline). Exposure control: +$11 avg (noise). REV max_concurrent=2, cap fires 6-9 trades. TREND low-vol signal ~$130 avg. Do not implement regime-based gating, activation, or exposure control in pipeline. REV×TREND overlap is beneficial diversification. Only valid signal (TREND in low-vol) is too small for system-level rules. Revisit only if regime classification becomes granular and aligned with strategy entry logic. No Stage 4 Regime Audit in pipeline. Current regime labels (vol bucket, trend label) lack forward-predictive power for trade-level decisions. Future work requires feature-level regime alignment, not coarse state labels. --- ---.
---

---
2026-04-08 | Tags: macro_filter, USD_SYNTH, z_score, mean_reversion, multi_timeframe, FX, indicator_extraction | Strategy: 41_REV_FX_*_FAKEBREAK (S04-S07 across 15M/1H/4H) | Run IDs: 04742f79173eccac300312ec, e3c57271ef8d6b6249b25903, 4e2a79a7d89e4dfe567a1260, f055d75f6561415a0615efa5, db8f5b719e8dad44bd96ad12, ebe145710b977951a2e247dc, 4fbe103f3bb47daf7a1d33d2, 883737e69e9af09908663027

USD_SYNTH Z-score mean-reversion filter is a confirmed edge enhancer for FX two-bar reversal strategies across all tested timeframes (15M, 1H, 4H). Trading only when USD is at statistical extremes (|Z| >= threshold on rolling 100-day window) and fading the extreme consistently improves profit factor. Stricter thresholds monotonically improve quality — the signature of a real signal. By contrast, SMA(100) trend-following filters on both USD_SYNTH and SPX500 destroyed value at every timeframe tested (PF < 1.0 in all cases).
SMA filters (1H): USD_SYNTH SMA PF 0.985, SPX500 SMA PF 0.945 — both worse than naked pattern. Z-score filters: 15M Z>=1.5 PF 1.120 (3611T), Z>=2.0 PF 1.131 (1621T); 1H Z>=1.5 PF 1.077 (905T), Z>=2.0 PF 1.231 Sharpe 2.07 (401T); 4H Z>=1.5 PF 0.916 (233T), Z>=2.0 PF 1.655 Sharpe 4.17 (104T).
Daily USD trend direction contains no usable information for intraday FX entries (SMA filters dead). However, USD extremity (how far from mean) is a valid macro context — when USD is statistically overbought/oversold, the reversion creates a directional tailwind for FX pairs. The filter auto-detects pair type via correlation (quote vs base pair) and maps Z-score extremes to allowed trade direction. Extracted to repository indicator at `indicators/macro/usd_synth_zscore.py` for reuse.
1. For FX macro filters, prefer mean-reversion (Z-score extremes) over trend-following (SMA direction). Daily trend is noise at intraday scale; daily extremity is signal.
2. Stricter Z thresholds trade density for quality. 4H Z>=2.0 (104T, PF 1.65) is too thin for standalone deployment but validates the signal. 1H Z>=2.0 (401T, PF 1.23) is the best balance. 15M provides density but thin edge per trade.
3. The indicator `indicators/macro/usd_synth_zscore.py` is available for all future FX strategies. Call: `usd_synth_zscore(df, lookback=100, threshold=2.0)` — outputs `macro_allowed` (+1/-1/0) and `usd_z_score`.
4. Existing 6 strategy files retain inline cumsum computation (PORTFOLIO_COMPLETE, snapshot immutable). Only future strategies should import the indicator.
---
---
---

---
2026-04-09 | Tags: USD_SYNTH, z_score, curve_fit_experiment, regime_filter, non_USD_crosses, indicator_validation, pipeline_validation | Strategy: 22_CONT_FX_30M_RSIAVG_TRENDFILT_S08_V1_P02 (experiment) vs P00 (control)

USD_SYNTH Z-score indicator has a dual mechanism depending on pair type, confirmed by blind-pair experiment on 5 never-tested FX crosses (EURJPY, EURGBP, CADJPY, GBPAUD, CHFJPY). The indicator computes correlation between pair returns and USD_SYNTH returns to determine pair_sign. On USD pairs (corr 0.70-0.85) it functions as a directional filter. On non-USD crosses (corr 0.05-0.24) the directional signal is near-random but it still works as a macro volatility regime gate — extreme USD moves correlate with elevated cross-market volatility where mean-reversion setups are stronger.
Experiment design: S08 P00 config (30M, Z>=1.5, max_bars=3) run identically on 5 pairs that never appeared in any RSIAVG directive. Compared against P00's 7 original USD-paired symbols. Zero parameter changes.
Results — per-symbol expectancy: Blind median $0.204 vs Selected median $0.203 (100.7% ratio). All 5 blind pairs profitable (PF 1.27-1.58). Mean expectancy 78% of selected. Aggregate expectancy blind $0.175 vs selected $0.247 (71%).
Robustness comparison (capital-wrapped): P02 blind CAGR 9.28% vs P00 selected 19.14%. MC 5th pctl CAGR 4.64% vs 9.54%. Both have 0/14 negative rolling years. P02 breaks under extreme slippage (1 pip) while P00 barely survives (+$483). Tail removal: P02 loses 39% CAGR at top-1% removal vs P00's 16% — blind crosses more tail-dependent.
Key finding: The ~2x performance gap (P00 vs P02) is NOT curve-fitting — it reflects the Z-score filter operating via different mechanisms. On USD pairs the filter provides genuine directional edge (strong correlation). On crosses it provides regime-timing value (trade only during macro dislocations). The value on non-USD crosses comes precisely from the indicator being uncorrelated to the traded instrument — it cannot overfit to the pair's specific patterns.
1. USD_SYNTH Z-score is a structural FX indicator, not a curve-fit artifact. Edge exists on 12/12 tested FX pairs (7 original + 5 blind).
2. For USD pairs: directional filter (corr 0.7-0.85). For non-USD crosses: volatility regime gate (corr 0.05-0.24). Both profitable, USD pairs ~2x stronger.
3. Pipeline pair selection process validated — selects pairs where the filter mechanism is strongest, does not manufacture false edge. Median expectancy identical between blind and selected groups.
4. Non-USD crosses have thinner edge ($2.31/trade vs $6.27) and higher tail dependence — viable in portfolio but not as standalone deployment.
5. The independence of the filter from the traded instrument on crosses is an anti-curve-fit property: an exogenous gate that cannot be mined from the pair's own price history.
---
---
---

---
2026-04-09 | Tags: pipeline_validation, curve_fit, portfolio_selection, median_test, composite_portfolio | Strategy: PF_04C5F80CB1E3 (median control) vs PF_71C9872F6F7E (top-picked)

Pipeline selection process validated via median-pick control portfolio. Same 4 symbols (EURUSD, GBPUSD, USDJPY, AUDJPY) — instead of best entries, picked the median-expectancy entry per symbol from CORE/BURN_IN strategies only. Ran full composite portfolio workflow (evaluator + capital wrapper + robustness).
Median portfolio PF_04C5F80CB1E3 composition: EURUSD S02 P03 30M ($0.17 exp, 247T), GBPUSD S07 P01 15M ($0.31, 127T), USDJPY S01 P06 15M ($0.09, 1275T), AUDJPY S02 P03 30M ($0.23, 134T).
Results: Median portfolio CAGR 33.97% vs top-picked 39.55% (86% ratio). PF 1.53 vs 1.55 (99%). Expectancy $5.01 vs $6.06 (83%). Max DD 3.09% vs 3.77% (median actually tighter). Recovery factor 39.92 vs 29.61 (median better). MC 5th pctl CAGR 23.48% vs 29.58% (79%). Zero negative rolling years for both. Baseline slippage PF 1.40 vs 1.42 (99%). Both break under extreme 1-pip slippage.
Combined with the blind-pair experiment (same session): the RSIAVG + trend filter edge is structural across FX. The pipeline selection process adds ~15-20% CAGR uplift over median picks — legitimate optimization, not curve-fitting. Even random/median entry selection produces a strong portfolio (34% CAGR, PF 1.53, 0 negative years).
1. Pipeline selection adds ~15% CAGR uplift, not 2-3x inflation. Base-rate edge is real regardless of entry selection.
2. PF is nearly identical (1.53 vs 1.55) — the quality of trades is similar; selection mainly improves per-trade expectancy slightly.
3. Median portfolio has tighter DD (3.09% vs 3.77%) and better recovery factor — less concentrated risk.
4. USDJPY median entry (S01 P06, 1275 trades at $0.09) compensates for low expectancy with massive trade volume — 57% of PnL.
5. Two-experiment validation (blind pairs + median picks) confirms: the RSIAVG FX edge is structural, and the pipeline filtering process is legitimate optimization.
---
---
---

---
2026-04-10 | Tags: uk100_15m, session_filter, pullback, trade_quality, regime_gating | Strategy: 40_CONT_UK100_15M_RSIPULL_SESSFILT_S08–S11_V2_P00
Three independent session filters applied to UK100 London-open short pullback (S08 baseline PF 1.24, 133 trades) all improved PF by blocking low-quality entry conditions. S09 (Wednesday exclusion) → PF 1.43/112 trades; S10 (weak_down regime block) → PF 1.56/68 trades; S11 (range_low_vol block) → PF 1.39/101 trades. S10 weak_down block delivers best PF lift (+0.32) but halves trade count to 68 — single-symbol statistical floor concern. S09 Wednesday block achieves +0.19 PF with only 16% trade reduction, best efficiency ratio. UK100 London-open shorts have a measurable regime dependency — weak downtrends and low-volatility ranges produce negative-expectancy entries that dilute the edge. Wednesday exclusion likely proxies for a mid-week liquidity/volatility trough specific to FTSE. The filters are additive in mechanism (day-of-week vs trend vs volatility) suggesting combinatorial stacking may compound gains, but trade count erosion per filter must be monitored. For UK100 London-open pullback variants, test combinatorial filter stacking (S09+S10 or S09+S11) only if the combined trade count stays above 80. Treat weak_down regime gating as a universal pre-filter candidate for any index session strategy — the PF lift is too large to be noise at 68 trades. ---.
---

---
2026-04-13 | Tags: F42, LIQSWEEP, SESSION_FILTER, FX_15M, CROSS_SYMBOL | Strategy: 42_REV_EURJPY/GBPUSD_15M_LIQSWEEP | Run IDs: S13_P04, S05_P03
Asia session exclusion [0-7 UTC] is the dominant filter for JPY crosses and GBP pairs on LIQSWEEP 15M. Regime age adds marginal lift only. EURJPY: base PF 1.20 → session only PF 1.40 SQN 2.40 (331T) vs regime_age_only PF 1.24 SQN 1.72 (455T). GBPUSD best: age[6-10] + excl. WeakUp → PF 1.88 SQN 2.81 97T. Asia session noise systematically degrades LIQSWEEP signal on JPY crosses. Regime age responds differently per symbol — GBPUSD: mature bars (6-10); EURJPY: session filter dominates. The two filters are not additive. For future LIQSWEEP FX passes, test session filter as primary gate first. Regime age is secondary exploration only on symbols that survive session filtering.
---

---
2026-04-14 | Tags: CHOCH_V2, pivot-based, signal-density, cross-asset, structural-edge | Run IDs: ff42d3d84bca6ce5d4782adc, 275b01020a669403f5bf808c, a096448a26b6008133374477

Strategies: 46_STR_XAU_1H_CHOCH_S01_V2_P00, 47_STR_FX_1H_CHOCH_S01_V2_P00, 48_STR_BTC_1H_CHOCH_S01_V2_P00
Transition from rolling-max proxy (V1) to pivot-based CHOCH (V2) increased signal density ~10-12x and fundamentally altered system behavior, converting a high-variance, misleading signal into a statistically stable one.

- XAU: 47->572 trades, PF 0.84->1.15
- BTC: 74->746 trades, PF 0.99->1.09
- USDJPY: 50->586 trades, PF 0.75->0.84 (remains negative)

Signal density is a first-order determinant of reliability. The V1 implementation failed due to undersampling, not necessarily signal invalidity. V2 reveals CHOCH as a weak but real structural edge on certain assets (XAU, BTC), and a non-viable signal on others (USDJPY).
Edge Characteristics:
- Directional asymmetry persists (XAU longs dominate)
- Strong session dependency (XAU: London/NY, BTC: Asia)
- Regime/timing sensitivity (early + late structure phases outperform mid-cycle)

- CHOCH_PIVOT_V2 is the only valid baseline
- CHOCH is not a standalone universal signal
- Edge emerges only when conditioned by context (direction, session, regime)
Next Hypothesis:
Test minimal conditioning:
1) Directional split (XAU long-only, BTC short/long split)
2) Session filter (XAU: exclude Asia, BTC: exclude London)
3) Regime-age gating (exclude mid-cycle zones)
Constraint:
Do not revisit CHOCH_PROXY_V1. Mark as invalid due to sampling error.
---

---
2026-04-14 | Tags: CHOCH_V2_vs_V3, structure-filter, signal-degradation, cross-asset | Run IDs: ff42d3d84bca6ce5d4782adc, 275b01020a669403f5bf808c, a096448a26b6008133374477, 4ebdb9c2ead03c9ee03a6229, 9299e9daf503e2e4388ef24a, d3a63a3f30af6c8c88ef7d24

Strategies: 46/47/48 (V2), 49/50/51 (V3)
Adding structure validation (HH+HL / LL+LH) to pivot-based CHOCH (V3) reduces trade count ~40-45% but consistently compresses PF toward 1.0 across all assets.

- XAU: PF 1.15 -> 1.02, trades 572 -> 325
- BTC: PF 1.09 -> 1.03, trades 746 -> 504
- USDJPY: PF 0.84 -> 0.95, trades 586 -> 362

Structure-aware CHOCH (V3) removes both profitable and unprofitable signals proportionally, indicating that confirmed HH/HL-based reversals do not carry edge. The edge observed in V2 originates from earlier pivot-break events, not from validated structural trend changes.

- "True CHOCH" (structure-confirmed) is not a profitable entry primitive
- Pivot-break (V2) captures earlier market transitions where edge exists
- Structure filtering acts as a neutralizer, not an enhancer
Next Hypothesis:
Focus on V2 (pivot-break) and apply:
1) Directional conditioning (asset-specific bias)
2) Session filters (strong divergence observed)
3) Regime-age gating (early vs mid-cycle behavior)
Constraint:
CHOCH_V3 should not be extended further. Mark as CHOCH_STRUCTURE_FILTER_FAILED.
---

---
2026-04-14 | Tags: CHOCH_v2, direction-asymmetry, XAU, BTC, 1H | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P01 | Run IDs: ff42d3d84bca6ce5d4782adc, dda4eef019b3252ba211e96c, 69b70372bc2604b73596dd12
CHOCH_v2 shows clear directional asymmetry on XAU 1H (long-only PF 1.15 -> 1.33 at 373 trades); asymmetry is weak on BTC 1H (long PF 1.09 vs short 1.02). - XAU: long arm PF 1.33 (n=373) vs blended PF 1.15 (n=572); short arm ~1.0 - BTC: long arm PF 1.09 (n=384) vs short arm PF 1.02 (n=365); blended 1.054. Short-side trades dilute edge on XAU where long-side carries the signal. On BTC the asymmetry is marginal and both directions cluster near break-even. The behavior is consistent with a pivot-breakout (not true CHOCH) interacting with asset-specific trend regimes (XAU uptrend vs BTC mixed). Future CHOCH work on XAU should be long-biased or direction-gated. BTC CHOCH_v2 requires an orthogonal filter (session, regime) rather than direction restriction alone. ---.
---

---
2026-04-14 | Tags: CHOCH_v2, regime_age, signal_fill_alignment, XAU, 1H, engine_v1_5_5 | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P02

With correct signal-fill alignment (engine v1.5.5, regime_age_filter mode: fill), excluding fill-bar Age 0 trades (regime transitions) does not improve CHOCH_v2 long-only performance on XAU 1H.

- mode=signal (legacy): 363 trades, PF 1.355, win 41.0%, avg_R +0.215, Max DD 14.04 R
- mode=fill (corrected): 362 trades, PF 1.346, win 40.9%, avg_R +0.210, Max DD 15.04 R
- age0_at_fill survivors under mode=fill: 0 (filter wired correctly)
- Delta: -1 trade, PF -0.009, DD +1.00 R
- The 8 removed transition-fill trades carried net +2R — they were not noise.

The previously observed "Age 0 is noise" effect was an artifact of signal/fill misalignment under next_bar_open. After correction, fill-bar transition trades are statistically similar to mid-regime trades for this strategy.

Regime-transition filtering is not a valid edge for CHOCH_v2 long XAU 1H. Alignment fix is necessary for correctness but does not by itself produce alpha. Strategic search should pivot away from regime_age toward breakout strength, volatility expansion, and entry timing. Adopt regime_age_filter.mode: fill as the default for NEW directives going forward (filter default remains "signal" for backward compat).
---

---
2026-04-14 | Tags: regime_age, HTF_quantization, dual_time_model, measurement_layer, engine_v1_5_5 | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P02 (v1.5.5 governed run) | Run ID: d87a73ea7beedd1d91a1f701

The v1.5.5 dual-time regime_age fields are measuring an HTF-granular clock, not a bar-level clock. regime_age on exec TF is broadcast from the HTF grid (4H for 1H exec, per config/regime_timeframe_map.yaml). Signal and fill bars within the same HTF bar share the same age value. Delta = fill_age - signal_age therefore measures HTF transitions, not next-bar-open progression.

Observed distribution on 363 trades (46_P02, XAU 1H, 4H regime):
- Delta 0 (same HTF bar): 267 trades / 73.6% — PF 1.456, WR 40.4%, avg +$4.00
- Delta 1 (fill crosses into next HTF bar): 88 trades / 24.2% — PF 0.864, WR 42.0%, avg -$1.51
- Delta <=-2 (regime flip between signal and fill): 8 trades / 2.2% — PF 1.876, WR 50.0%, avg +$6.27
- Delta -1 and Delta >=2: 0 trades (structurally impossible under HTF broadcast).

The 3:1:rare distribution matches the 4H:1H ratio exactly. This is not a bug; it is the correct interpretation of an HTF-broadcast age variable. The original "delta 1 should dominate under next_bar_open" expectation was wrong — it assumed an exec-TF clock that does not exist in the current pipeline.

Root cause structural: run_stage1.py computes regime_age on HTF then merges (broadcasts) onto exec TF. execution_loop.py reads df['regime_age'] at signal and fill bars, producing HTF-quantized signal/fill ages. Pipeline code comment at tools/run_stage1.py:945-949 explicitly documents that regime_age_signal/fill are NOT merged from HTF for this reason, but does not (yet) provide an exec-TF counterpart.

Action taken: report headers and metrics_core docstring relabeled as HTF-granularity; no computation changes. Edge-candidate observation — Delta <=-2 (regime flip between signal and fill) at PF 1.876 across 8 trades is noteworthy but under-sampled; tag for future exploration if that bucket grows.

Pending: add regime_age_exec, regime_age_exec_signal, regime_age_exec_fill derived from an exec-TF state-machine pass so the "bar-level timing" question can actually be asked. Two orthogonal clocks (HTF macro + exec-TF micro) enable cross-interaction analysis (e.g. early entry in new HTF regime vs late entry in mature regime).
---
2026-04-14 | Tags: regime_age_exec, dual_time_model, engine_v1_5_6, probe_validation | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P02 | Run ID: 47ec676b31654d49e187721a
Engine bumped v1.5.5 -> v1.5.6. Added exec-TF regime-age clock as a second, orthogonal probe (separate from HTF clock). run_stage1 derives df['regime_age_exec'] on exec TF via groupby((regime_id != regime_id.shift()).cumsum()).cumcount(); engine reads at signal + fill bars; emitter + RawTradeRecord now carry regime_age_exec_signal / _fill.

Exec-TF distribution on 46_P02 re-run (363 trades):
- Exec Delta +1: 355 trades (97.8%) — dominant, as expected under next_bar_open (exec clock ticks exactly one bar between signal and fill).
- Exec Delta  0: 0 trades.
- Exec Delta <=-1: 8 trades — same 8 "regime flip" trades visible on HTF as Delta <=-2. Consistency check passed.

Conclusion on HTF anomaly: the Delta=0 dominance observed on the HTF clock (267/363 = 73.6%) was 100% an HTF-quantization artifact. Those same trades are Delta +1 on exec TF. Both clocks now coexist; neither is "the truth" on its own. HTF clock = macro (regime-age at HTF granularity); exec clock = micro (bars-since-regime-change at exec granularity). regime_alignment_guard.py has warn rules for both clocks (HTF: delta -1 / >=2 non-empty; exec: delta=+1 dominance drop below 80%). v1.5.6 vault close deferred until probe-driven analysis yields an actionable finding.
---

2026-04-17 | Tags: exit_timing, mean_reversion, h4, cmr, signal_persistence, reentry_frequency | Strategy: 53_MR_EURUSD_4H_CMR_S01_V1_P00..P05
Run IDs: P00, P01, P02, P03, P05 (EURUSD, 2024-01-02 -> 2026-04-15)

Finding:
For the 3-consecutive-close MR signal on EURUSD H4, a 3-bar time-exit (P01) dominates all tested alternatives (day-close, 6-bar, PnL-gated 1-2 bars, signal-only).

Evidence:
P01 PF=1.17 / SQN=1.09 / DD=4.83%. P02 PF=1.14 with higher DD (11.48%). P05 PF=1.11 with avg_bars=11.63 and ~50% lower trade count. P03 PF=1.01, showing edge collapse under early profit-taking.

Conclusion:
Edge is concentrated in a short 2-3 bar window. Exiting too early truncates the positive tail, while holding beyond this window leads to edge decay. Signal persistence is not the dominant driver; re-entry cadence and capital recycling are key contributors to total PnL.

Implication:
For consecutive-close MR signals on H4 FX: default exit = ~3 bars; avoid PnL-gated early exits; avoid relying solely on signal reversal; re-entry frequency is additive to performance even when per-trade expectancy is lower.
2026-04-17
Tags:
timeframe_scaling
mean_reversion
cmr
signal_quality
daily_tf

Strategy: 53_MR_EURUSD_1D_CMR_S02_V1_P00
Run IDs: 423cb6c67747cc63ca063922 (EURUSD, 2024-01-01 -> 2026-04-14)

Finding:
3-consecutive-close MR signal shows materially higher PF and stability on Daily (PF 1.65, SQN 1.47) vs H4 variants (best PF 1.17).

Evidence:
1D: 63 trades, PF 1.65, SQN 1.47, DD 0.034%, long PF 1.74 / short PF 1.52. H4 P01: 359 trades, PF 1.17, SQN 1.09, DD 4.83%.

Conclusion:
Edge persists across timeframe scaling and improves under noise reduction. Signal structure is consistent, but lower-frequency sampling increases signal quality at the cost of trade count.

Implication:
Daily timeframe is a higher-quality representation of the same signal. Next step is to increase sample size via multi-pair expansion before modifying thresholds or rules.

---

2026-04-17 | Tags: macro-filter, dispersion-gate, consecutive-close, daily, fx-basket, usd-synth, jpy-synth
Strategy: 53_MR_EURUSD_1D_CMR_S02_V1 (P01/P02/P03)
Run IDs: P01_<18 pairs>, P02_<18 pairs>, P03_<18 pairs>

Finding:
USD_SYNTH |z|>=0.5 entry gate improves aggregate FX-basket PF (1.10->1.16) and specifically repairs the weak SHORT leg (PF 0.97->1.06) and the losing 2024 year (PF 0.83->0.99), while removing 26% of trades.

Evidence:
P02 vs P01: trades 1067->792, PnL +$337->+$387, PF 1.10->1.16, SHORT PF 0.97->1.06.
P03 (USD or JPY union): trades 1067->1040 (−2.5%), PF 1.10->1.15 — minimal filtering effect due to high JPY coverage.

Conclusion:
USD dispersion provides meaningful regime discrimination, while JPY dispersion at this threshold has near-universal coverage and therefore no effective filtering power. Macro factors differ in base-rate coverage and are not interchangeable as filters.

Implication:
Macro filters must be evaluated by coverage before use. For this signal family:
- prefer USD-only dispersion gating
- avoid union-based filters with high-coverage factors
- next step: test stricter USD thresholds (|z|>=1.0) or intersection logic (USD AND JPY)
2026-04-17
Tags:
53_MR
CMR
ASSET_SELECTION

Strategy: 53_MR_EURUSD_1D_CMR_S02_V1
Run IDs: P07 vs P06

Finding:
Removing persistently negative-expectancy pairs (NZDUSD PF 0.37, GBPUSD PF 0.73) materially improves system performance (PF 1.30→1.64, MAR 1.84→2.31).

Evidence:
P06→P07: 363→322 trades; MaxDD 11.2%→10.0%; CAGR 20.6%→23.1%; net PnL +$544→+$616.

Conclusion:
The CMR signal is asset-sensitive. Performance depends on structural compatibility between the signal and the underlying pair behavior. Pairs with persistent directional regimes support the signal; balanced or mean-reverting pairs degrade it.

Implication:
Asset selection must be empirical and driven by compatibility, not predefined currency categories. Default approach: exclude structurally negative pairs and validate inclusion individually.

---

2026-04-18 | Tags: burn-in-observation, regime-incoherence, mean-reversion, rsiavg, gbpjpy, double-entry, trend-filter, regime-lag
Strategy: 22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05 (GBPJPY)
Run IDs: N/A — burn-in live observation 2026-04-17

Finding:
GBPJPY double-entry on 2026-04-17 was NOT a clean regime miss — it was a regime incoherence event. The entry gate passed correctly by its own rules, but `market_regime` and `trend_regime` produced contradictory classifications on the second signal bar, masking an impending directional reversal.

Evidence:
Trade 1 (bar 01:30 SVR): entry SHORT @ 215.328, exit @ 215.304, net +0.024 pips (+small win).
  regime: volatility_regime=-1, trend_regime=-2 (strong_down), market_regime="unstable_trend"

Trade 2 (bar 02:30 SVR — immediate re-entry same session):
  entry SHORT @ 215.34, exit @ 215.46 (stopped out), net -0.12 pips (−0.59R approx).
  regime: volatility_regime=-1, trend_regime=-2 (strong_down), market_regime="range_low_vol"

The entry gate for Trade 2 passed because: vol_regime=-1 ✓, trend_regime<=-2 ✓ (direction gate), trend_score<=-2 ✓, rsi_avg>75 ✓.
Price moved UP from 215.294→215.324→215.46 — the "strong_down" trend_regime label was lagging.

Key observation: `market_regime` flipped from "unstable_trend" → "range_low_vol" in a SINGLE bar while `trend_regime` held at -2. These two labels are internally contradictory: a strong directional trend (trend_regime=-2) cannot simultaneously be a low-volatility range (market_regime=range_low_vol). The composite regime label (`market_regime`) had already signaled regime breakdown; the scalar label (`trend_regime`) had not yet updated.

Conclusion:
Point A is CONFIRMED but nuanced. The regime detector did not fail to fire — it fired correctly within its rules. The failure mode is regime label incoherence: `market_regime` leading a regime shift that `trend_regime` lagged by ≥1 bar. The strategy gates on `trend_regime` only (via FilterStack direction_gate), making it blind to `market_regime` divergence as an early warning. The `market_regime="range_low_vol"` + `trend_regime=-2` combination is a structural contradiction that, in this instance, preceded a trend reversal. It may be a reliable precursor signal — but this is a single event and not yet validated.

Implication:
1. A re-entry cooldown (min_bars_between_trades) would have prevented Trade 2 mechanically — simplest fix, no regime logic required. Requires replay validation before deployment.
2. A `market_regime` consistency gate — block entry when `market_regime` contradicts `trend_regime` (e.g., `range_low_vol` when trend_regime is ±2) — would be a more principled fix but requires backtesting to quantify the coverage/edge tradeoff.
3. Flag for future hypothesis: test whether `market_regime != trend-consistent label` is a reliable early-warning of regime breakdown across the RSIAVG family (not just GBPJPY P05).
4. Do NOT patch mid-burn-in. Log observation, continue monitoring; design fix as new directive with full replay validation.

---

2026-04-19 | Tags: 54_STR, MACD, CONVERGENCE, XAUUSD, 5M, FILTER_STACKING, REGIME_INTERSECTION
Strategy family: 54_STR_XAUUSD_5M_MACD*
Run IDs: S01=019c8b6c (MACDB_S05), S02=12df81c6 (MACDX_S06), S03=84ea51f3 (MACDX_S13, renamed from S07 due to registry slot collision)

Finding:
On XAUUSD 5M, MACD + regime filters combine MULTIPLICATIVELY, not additively. Triple-convergence (event + bias + EMA trend) is the only configuration that crosses the quality gate; each single-filter variant fails.

Evidence:
Test window 2024-07-19 → 2026-04-17, SL=2xATR, TP=6xATR, no time/session filters, direction long_and_short.

  S01 MACDB  (event + bias)           : 1759 trades, PF 1.23, SQN 2.61, MaxDD 41.3%, Sharpe 0.99 → FAIL
  S02 MACDXE (crossover_trans + EMA)  : 2099 trades, PF 1.17, SQN 2.23, MaxDD 40.6%, Sharpe 0.77 → FAIL
  S03 MACDXC (event + bias + EMA)     : 1301 trades, PF 1.34, SQN 3.10, MaxDD 23.5%, Sharpe 1.36, Sortino 2.82, Ret/DD 9.91 → WATCH

Baseline reference: prior unfiltered MACDX_S06 collapsed at PF 0.97 (2164 trades) under flat-dedup.

Year-wise for S03: 2024 -$18, 2025 +$1153, 2026 +$1196 (near-flat 2024, consistent 2025/2026).

Conclusion:
Filter stacking on momentum signals exhibits multiplicative edge recovery: two single filters each raise PF from 0.97 to ~1.2 (still failing), but their intersection lifts PF to 1.34 and DOUBLES SQN (2.23 → 3.10) while COMPRESSING DD by 42%. Neither filter is sufficient alone; both are load-bearing. S02's EMA-only filter is actively worse than S01's bias-only — EMA regime without event-timing discipline keeps too many false transitions.

Implication:
1. For momentum-family entries on XAU 5M, regime filters must intersect, not union — at least event-timing + bias + trend alignment combined.
2. Do NOT evaluate convergence candidates by PF/trade-count alone; SQN and DD-compression are where intersection logic actually earns its cost.
3. S03 MACDXC is the only promote-worthy candidate of the family on XAU 5M. Candidate_status=WATCH; needs pre-promote quality gate (tail concentration, flat periods, edge ratio on individual trades) before advancing.
4. Next probe hypothesis (advisory): test whether this multiplicative pattern generalizes to FX 5M/15M and BTC 5M, or whether it is XAU-specific. If generalizable, triple-convergence becomes a default scaffold; if XAU-specific, it localizes the XAU regime-alignment prior.
2026-04-19
Tags:
54_STR
MACDX
XAUUSD
5M
VOLATILITY_FILTER
DIRECTION_CONDITIONAL

Strategy: 54_STR_XAUUSD_5M_MACDX_S13/S20/S21_V1_P00
Run IDs: S20=58ccdb5b/S21=a6c1814e — see TradeScan_State/backtests/54_STR_XAUUSD_5M_MACDX_S{20, 21}_V1_P00_XAUUSD

Finding:
Volatility-regime filter (exclude low) on S13 triple-convergence MACDX improves all risk-adjusted metrics; effect is overwhelmingly short-side.

Evidence:
S13 N=1301 PF=1.34 SQN=2.64 DD=$235 top10=58%; S20 (both dirs vol!=low) N=817 PF=1.55 SQN=3.88 DD=$172; S21 (shorts only vol!=low) N=1134 PF=1.48 SQN=3.58 DD=$195. Short PF 1.385 -> 1.820 in both variants; longs identical S13 vs S21.

Conclusion:
Low-vol shorts were the contaminated cluster in S13; direction-conditional vol gate (short-only) recovers most of the benefit while keeping all long-side trades. S20 maximises PF/SQN/DD; S21 maximises PnL and reduces tail concentration to 48%.

Implication:
Prefer S21-style direction-conditional filters when one side's edge is already clean: cheaper in trade count lost, stronger on PnL. Use engine-owned volatility_regime via ctx.require inside try/except for dry-run safety; never import indicators.volatility.volatility_regime in strategy (engine-owned-fields guard).

2026-04-19 | Tags: infra, partial_exits, capital_wrapper, engine_v157, scope_decision | Strategy: 54_STR_XAUUSD_5M_MACDX_S23_V1_P00

Partial-exit infra integrated; exits rejected as edge lever after full accounting validation.
