# RESEARCH MEMORY

FORMAT POLICY:
- Entries may be compacted for token efficiency; content is semantically identical
- Compaction does not violate the append-only rule
- Archive split enforced at 600 lines / 40 KB -> RESEARCH_MEMORY_ARCHIVE.md
- Tier A (3-line inline): simple findings, all sections ≤ 3 non-blank lines, no sub-lists
- Tier B (label-free paragraphs): complex entries, labels removed, paragraph structure kept
- Pre-2026-06-16 entries live in RESEARCH_MEMORY_ARCHIVE.md (compacted)

THIS FILE IS APPEND-ONLY. Corrections are new entries, not edits.
Post-contract entries must conform to the NEW ENTRY CONTRACT template.

---
2026-06-19 | Tags: minimum_viable_spread, cost_floor, entry_filter, z_score_normalization, filter_inert, vault_concept_tested | Strategy: pine_ratio_zrev_v1_zcross cointegration baskets (COINTREV_V3, N30/15M/absolute/GP) | Run IDs: AD-HOC data query (no pipeline run_id; PROVISIONAL per Invariant #31): 60 FXD25 is_current=1 runs, 12,166 cycles, v1.5.9 uncharged engine
The minimum viable spread filter (abs(raw_spread_at_entry) > cost_floor, per Thorp/Saleh 2025) has no predictive power on top of the z=2.5 threshold in Trade_Scan's cointegration architecture. The z-score normalization already implements the filter implicitly. Per-cycle gross P&L distribution (FXD25 FX-FX pairs, uncharged v1.5.9): mean=+0.0001%, median=+0.055%, 56% positive. Cost floor estimated at 0.0279% per cycle (2.54pp aggregate v1.5.10 drag / 91 median cycles per run). Survival rate at cost floor: 53.1% of trades -- virtually identical to raw win rate. ATR quartile as proxy for absolute spread magnitude at entry (high ATR ≈ high spread_std ≈ high absolute spread): Q1(low)=51.5% clearing floor, Q2=51.8%, Q3=54.4%, Q4(high)=54.5% -- a 3pp gradient across the full ATR range. Survivors average +0.71% gross, rejects -0.81% gross -- a real gap, but the filter cannot predict which trades fall into which group. Thorp's 1.5% raw-spread filter had bite because his strategy used a fixed ±1.2 z-score threshold, so the raw-spread value varied across entries. At z=2.5, Trade_Scan's rolling-std normalization ensures every entry has roughly the same z-relative divergence; the absolute spread at entry only varies because spread_std varies, and ATR (the available proxy for spread_std) barely predicts post-entry gross quality. Adding an absolute cost floor on top of z=2.5 would cut ~47% of trades with no material improvement in the survivor pool quality. Filter inert; do not test as a directive variant. The vault concept (cost-floor-minimum-viable-spread) is correctly filed as Class A library knowledge, not a testable hypothesis. One narrow version could have value: a PAIR-LEVEL selection gate (upstream of z-score) rejecting pairs where mean(gross_per_cycle) < cost_floor over historical sample. But that is functionally equivalent to the Ret/DD ranking already applied in corpus screening. No new mechanism needed. --- ---.
---

---
2026-06-16 | Tags: bb_adaptive_width, cointegration_basket, fat_tail_blowup_constraint, adaptive_entry_band, level_matched_k25_accept, generic_k20_rejected, exp1_settled | Strategy: pine_ratio_zrev_v1_zcross cointegration baskets (COINTREV_V3, N30/15M/absolute/GP) -- 3 arms x 497-pair cohort | Run IDs: cohort 475-476 is_current/arm in cointegration_sheet; examples FXD25=9f77f28947b6f6382fd5394c BBK20=67f856d04d7290194fdde0cd BBK25=dbfc12ea6d22f87574704abc; corpus commit fc30f0c4
An adaptive sigma-band entry trigger on the z-series (|z| > k*sigma_M(z), mid fixed 0, absolute) cuts cointegration-basket fat-tail blowups ONLY when level-matched to the existing fixed threshold (k=2.5); the generic textbook band (k=2.0) over-trades and worsens blowups. 3 arms x 497-pair cohort, uncharged engine_abi.v1_5_9 (within-batch deltas valid). Cohort medians + blowups (max-DD >= 50% stake): FXD25 fixed |z|>2.5 control Ret/DD 0.000 / 32 trades / 20 blowups; BBK20 k=2.0 +0.116 / 62 trades (1.94x) / 30 blowups; BBK25 k=2.5 +0.064 / 42 trades (1.3x) / 17 blowups. Generic k=2.0 REJECTED (fails pre-registered acceptance: blowups 30 > baseline 20; ~1.94x over-trade -- looser ~2.0 average fires into the breakdowns it was meant to avoid = trade-count-inflation failure). Level-matched k=2.5 CONDITIONAL ACCEPT (blowups 20->17, +0.064 Ret/DD uplift, no DD penalty) -- confirms the adaptive-band concept but only with the average level held fixed. For cointegration-basket entry timing, an adaptive band is worth pursuing only level-matched (k tuned to the old fixed threshold), never generic k=2.0. Carry-forward = Exp2 calibration (normalized thr = 2.5*sigma_M(z)/mean(sigma_M(z)) or tuned k/M), OPEN/optional. Verdict is blowup-REDUCTION not net-of-cost profitability (uncharged engine; charged v1.5.10 edge is inside the spread); nothing promoted (patch additive/default-off). --- ---.
---

---
2026-06-20 | Tags: cointegration, regime-conditionality, basket, ratio-reversion | Strategy: 90_PORT_BTCUSDEUSTX50_15M_ZREV_L30_GP_ZCRS_FXD25 | Run IDs: 6e3d51f4fea07b7cbe2061ae, 8208d26caa396595aafcdb19
FXD25 BTCUSD/EUSTX50 ratio-reversion is strongly regime-conditional. The strategy is profitable during cointegrated/breaking periods but catastrophically unprofitable during broken periods. Regime realized PnL (USD): cointegrated +235, breaking +196, broken -3892. Edge is confined to cointegrated/breaking regimes; unconditioned exposure to broken periods dominates and is net-destructive. Cointegration-span conditioning is a required component of the strategy definition rather than an optional optimization. --- ---.
---

---
2026-06-20 | Tags: mean-reversion, equity-index, rsi-power-zone, stage1-probe | Strategy: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00 | Run IDs: aa2a6d553fda6c87af0f075d
SPX500 daily RSI(4)<30 mean-reversion (EMA200-gated, long-only) shows a strong short-term mean-reversion signal -- Stage-1 probe of vault spx500-rsi-mean-reversion-cfd (Connors RSI Power Zone), EMA(200) proxy for SMA(200). 27 trades, 88.9% win, PF 4.99, SQN 3.39, mean R +0.18 (charged v1.5.10, OctaFX swap-free, 2024-26). Verdict FAIL = trades 27<50 (administrative), not edge. Evidence supports the existence of a positive mean-reversion edge, pending validation on the full 2016-2026 sample; the deployment FAIL is trade-count, not edge quality. Stage-2 = full 2016-2026 history (sample size + COVID + 2022 bear + EMA-gate stress); do NOT optimize parameters yet. OctaFX swap-free so no financing overlay needed. --- ---.
---

---
2026-06-20 | Tags: mean-reversion, equity-index, rsi-power-zone, regime-conditionality | Strategy: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00 | Run IDs: 51d49c9b2d927e4029a17662, aa2a6d553fda6c87af0f075d
Stage-2 full 2017-2026 history confirms the SPX500 RSI(4) mean-reversion edge (EMA200-gated, long-only) is durable but regime-conditional; supersedes the sample-limited Stage-1, verdict FAIL->WATCH. Net +180, PF 1.74, 73.3% win, SQN 2.31 (WATCH), 86 trades. EMA(200) gate contained COVID (2020 -11); weakest in 2022 bear (-34, 25% win); full-cycle mean R +0.057 vs bull-window +0.18. Edge survives a decade incl. two crashes net-positive and the EMA gate works in fast crashes, but it is bull-biased -- money is made in bull/recovery years and partly given back in down/choppy years (esp. sustained bears). Deploy-eligible as a bull-biased equity-index portfolio complement, NOT a CORE standalone. Next P01 targets the largest weak cell (down-year dip-buys, esp. 2022 bear) via an EMA(200)-rising/slope gate, not parameter tuning. --- ---.
---

---
2026-06-20 | Tags: mean-reversion, equity-index, generalization, rsi-power-zone | Strategy: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00 | Run IDs: 51d49c9b2d927e4029a17662, 7196ef4df3b5e9a125e4af27, 32fb644813e30ecc21a089a6, 1ffd340d97951a7d032d635f, 9d4367b73ef8ac35bd8c1235, f50d2446623582a13dced753, db83ffa33af1999c849f7495, d804eab41230d4a7a68683cd, f3dfe4a9ac0120d8ccb85f60, b1bfe8178bb7bf7c5a145a48
The SPX500 RSI Power Zone mean-reversion edge generalizes BROADLY but UNEVENLY across 10 equity-index CFDs (1d) -- net-positive on 9/10 but strong on only 2; instrument-specific, not a generic 'equity index' edge. Run separately per instrument (not a portfolio). PF across 10 indices: SPX500 1.74 / NAS100 1.72 (strong) > AUS200 1.49 / EUSTX50 1.48 / GER40 1.40 / UK100 1.30 / JPN225 1.25 (moderate) > ESP35 1.15 / US30 1.04 / FRA40 0.87 (NEGATIVE). Win 63-77% all; density ~7-10 trades/yr on EVERY index. Short-term mean-reversion is a broad equity-index property but strength tracks index CHARACTER (broad-cap/tech deepest); FRA40 is a genuine non-generaliser (PF<1). Density is structural to the strategy (~8/yr for daily RSI(4)<30), NOT the instrument -- no index choice clears the 50/yr gate. Core complements SPX500 + NAS100; secondary AUS200/EUSTX50/UK100/JPN225; drop ESP35/US30/FRA40. The ONLY density-clearing path is multi-instrument aggregation (separate runs SELECT instruments; a pooled deployment CLEARS density) -- a single daily index can never pass the 50/yr gate. ---.
---

---
2026-06-21 | Tags: octafx, swap-free, cost-model, financing-zero, spread-only, broker-terms, equity-index-mr, cointegration, settled-decision | Strategy: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00 | Run IDs: 51d49c9b2d927e4029a17662, aa2a6d553fda6c87af0f075d
Finding: OctaFX/Octa is swap-free: it charges NO overnight swap/financing on any account or instrument (FX, indices, metals, crypto, stocks), with no holding-time limit and no admin fee (Sharia-compliant default, all countries, since 2022-06). The complete OctaFX backtest cost model is therefore spread (+ slippage); the financing term is structurally zero.
Evidence: Source vault sources/octafx-swap-free-cost-model.md (Financial IT 2022-06-21 + broker reviews + owner confirmation 2026-06-21); cost layer carries NO swap term, verified spread-only across engines/execution_fill.py, tools/basket_runner.py, tools/recycle_rules/pine_ratio_zrev_v1.py, frozen single-asset v1_5_10; spx500-rsi E001 run 51d49c9b after-spread verdict PF 1.74.
Conclusion: RESOLVES all prior overnight-financing-is-the-open-gate / hypothesis-killer conclusions for the equity-index mean-reversion family and the cointegration line: financing was never charged because it does not exist on OctaFX, the gate was always spread. spx500-rsi E001 cost side now CLOSED (only the sample-density / SQN deployment gate remains). Multi-day-hold strategies (Double 7, cointegration baskets) pay no carry, a structural advantage not a drag.
Implication: Do NOT add a swap / carry / financing term to any OctaFX backtest, cost model, or P&L path (scope: all instruments, any holding duration); cost = spread (+ slippage) only. The no-financing omission is correct by design, documented as OVERNIGHT_FINANCING = 0 in engines/execution_fill.py and locked by INVAR-003 (INVARIANT_PROPOSALS.md).
---

---
2026-06-21 | Tags: internal-bar-strength, threshold-shape-probe, equity-index, edge-concentration | Strategy: 70_MR_IDX_1D_IBS_S01_V1_P00 | Run IDs: 3344c46617c134ef5a513a7d, fb181760863ae5800f33558d, 328eb0cfcf4c1f4e37a3f38b
Finding: SPX500 IBS edge is sharpest at IBS<0.20 and dilutes as the entry threshold widens (shape-probe 0.20/0.25/0.30, not optimization).
Evidence: P00/P01/P02: PF 1.45/1.39/1.29, SQN 2.33/2.22/1.83, maxDD 5.87/8.54/8.29%, flat 811/952/952d, top5 41/42/48% net, trades 323/360/410.
Conclusion: Within (0.20,0.25,0.30) IBS<0.20 dominates; further loosening not justified -- marginal 0.20-0.30 trades are a lower-quality population (Pagonidis non-linearity) and widening kills the normal-vol regime (+42->-5).
Implication: Keep IBS<0.20 (champion); threshold-shape arc CLOSED. More density -> multi-instrument pooling, not a looser threshold.
---

---
2026-06-21 | Tags: signal-union, internal-bar-strength, rsi-pullback, equity-index, composite-additive, watch | Strategy: 71_MR_IDX_1D_UNION_S01_V1_P00 | Run IDs: 894fa6ff5b96261059b2acfc
Finding: RSI-IBS union (RSI OR IBS) on SPX500 improves quality AND distribution vs either component alone -- signal diversification, not threshold loosening.
Evidence: 314 trades (~33/yr), PF 1.62, SQN 2.93, net +$405, top-5 conc 29.6% (vs IBS 41%), flat ~769d, positive in all vol+trend regimes; IBS-only=volume, RSI-involved=higher per-trade (~$2.7-3.1), both=strongest.
Conclusion: Signal diversification succeeds where threshold-loosening (idea-70 P01/P02) failed; composite edge is additive and less tail-dependent than either standalone.
Implication: CONFIRMED WATCH (governed run 894fa6ff, Stages 1-4 + promotion; net $405 <$1000 caps at WATCH, else CORE-grade: SQN 2.92, ret/DD 4.45, maxDD 9.11%). Earlier governed NO_TRADES was a stuck deterministic run_id + first-exec guard (cleared crash debris), NOT a worker bug; anti-masking fix landed regardless. Multi-index expansion now unblocked (operator call).
---

---
2026-06-23 | Tags: directional-regime-interaction, trade-record-decomposition, market_regime, single-asset-filter, methodology-validation, dma-gold | Strategy: 72_MR_XAUUSD_5M_DMA_S02_V1_P01 | Run IDs: ca606d818a7ad24937083cfd, f184e8668a952c4fba267c3b
Finding: Two transferable lessons from a DMA-gold-5m P01 test (the DMA result itself is NOT deployable): (1) a directional x entry-observable-regime poison cell (LONG x market_regime=unstable_trend) is isolable from trade records and removable via a one-line direction-conditional check_entry gate WITHOUT destroying density; (2) a trade-record decomposition's prediction survives a full governed pipeline rerun.
Evidence: S02->P01: net -375->+309, PF 0.93->1.10, 739->488 trades (66% kept); LONG -562/PF0.86->+122/PF1.10, SHORT byte-identical (301tr/+187). Ad-hoc decomposition predicted +355/485tr; pipeline produced +309/488tr (under 5% off on both net and count).
Conclusion: Direction-conditional gating on an engine-owned signal-bar regime field surgically removes the toxic leg while preserving the profitable opposite direction (per-bucket exit R unchanged at stop -1.01 / MR +0.53; only the stop/MR mix shifts, ratio 0.93->1.10). The PROVISIONAL ad-hoc slice reproduced through the pipeline to within 5pct -> trade-record decomposition is PREDICTIVE of governed reruns, not merely suggestive (Invariant #31 reproduction satisfied).
Implication: Reusable beyond DMA gold: (a) decompose by direction x entry-observable-regime to surface isolable poison cells; (b) a clean trade-record prediction justifies committing exactly one confirming pipeline run, then conclude there. P01 itself NOT deployable (SQN -0.08 < 2.0, net 149pct from 2024-26, ~4.7yr flat) -- durability is an orthogonal gate the regime fix does not touch.
---

---
2026-06-23 | Tags: dma-gold, regime-filter, session-filter, mean-reversion, arc-conclusion, single-asset-filter | Strategy: 72_MR_XAUUSD_5M_DMA_S02_V1_P02 | Run IDs: 9c409d63dfc7c77f123e8763, ca606d818a7ad24937083cfd, f184e8668a952c4fba267c3b
Finding: DMA-gold-5m arc reached a regime-conditional WATCH via two stacked entry-observable filters (no-LONG-in-unstable_trend + exclude-London), after which BOTH simplification paths were tested and rejected -- the filters earn their place. Stop-refining ('don't overoperate') decision; pivot to a complementary breakout module.
Evidence: S02 FAIL -375/PF0.94 -> P01 +309/PF1.10/SQN0.74 -> P02 +707/PF1.35/SQN2.13; all 7 dir x regime cells positive (PF 1.12-3.30, Long x unstable empty/gated); top-2 cells = 57pct of net.
Conclusion: Depth-threshold simplification rejected -- depth NON-monotonic (marginal: only >=2.50 stretch profitable, 16tr/~2yr density-dead; thr>=1.50 = +221/SQN0.53, sub-P02 + tail-dependent on 16 trades). Regime-removal rejected -- every market_regime net-positive (only droppable is trend_compression, +6). The filters extract regime/session selectivity a single threshold or regime-cut cannot; P02 is ~3 diversified profitable sub-modules (short-MR-unstable +248, long-MR-trend_expansion +158/PF3.3, range-MR +281), not propped on one.
Implication: P02 deployable as a regime-conditional WATCH (SQN 2.13; net <1000 caps WATCH; 2024-26-concentrated = durability is the residual gate, NOT quality). Add no more filters: the lone remaining leak (SHORT x strong_up x unstable -159) sits INSIDE the +248 short-unstable cell, so cutting it shaves a profitable module. Next = breakout module (structurally uncorrelated to the MR book). Infra: indicators.structure.session_clock realigned to the report canon (London 8-16, report_sessions.py) so strategy gating uses identical hours to report bucketing.
---

---
2026-06-24 | Tags: gold-breakout, one-per-day-selectivity, multi-session-reentry-churn, charged-full-history, single-asset | Strategy: 65_BRK_XAUUSD_5M_PSBRK_S01_V4_P09 | Run IDs: 8faf348a (one-per-day P16), 02bb9ab4 (multi-entry baseline E003), e60c5997 (multi-entry full-window)
Finding: PSBRK gold-5m prior-session breakout is dead on charged full-history (PF 1.01), but capping to ONE entry per UTC day (first breakout only, no re-entry) is a large structural improvement -- multi-session re-entry was net-destructive churn.
Evidence: Same window 2016-02..2026-05-26 charged v1.5.10: multi-entry -$96/PF1.00/SQN-0.08/maxDD165.7%/6048tr vs one-per-day +$464/PF1.04/SQN0.56/maxDD67.7%/2650tr; pre-2025 bleed -1319 -> -388.
Conclusion: First-of-day selectivity removes the 62%-stop-out re-entry churn driving the blowup; flips net sign + kills the >100% no-liquidation DD, but PF~1.04/SQN0.56 still sub-deployable -- the signal is the ceiling, not the sizing.
Implication: For multi-session intraday breakout families, test a one-entry-per-day cap before concluding dead. Long-only P17 (next probe) blocked pending the v1.5.11 invalid-fill SKIP engine fix (gap-fill stop-contract crash; design parked).
---
