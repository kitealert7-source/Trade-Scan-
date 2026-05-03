# RESEARCH MEMORY

FORMAT POLICY:
- Entries may be compacted for token efficiency; content is semantically identical
- Compaction does not violate the append-only rule
- Archive split enforced at 600 lines / 40 KB -> RESEARCH_MEMORY_ARCHIVE.md
- Tier A (3-line inline): simple findings, all sections ≤ 3 non-blank lines, no sub-lists
- Tier B (label-free paragraphs): complex entries, labels removed, paragraph structure kept
- Pre-2026-04-14 entries live in RESEARCH_MEMORY_ARCHIVE.md (compacted)

THIS FILE IS APPEND-ONLY. Corrections are new entries, not edits.
Post-contract entries must conform to the NEW ENTRY CONTRACT template.

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
---

---
2026-04-14 | Tags: CHOCH_v2, direction-asymmetry, XAU, BTC, 1H | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P01 | Run IDs: ff42d3d84bca6ce5d4782adc, dda4eef019b3252ba211e96c, 69b70372bc2604b73596dd12
CHOCH_v2 shows clear directional asymmetry on XAU 1H (long-only PF 1.15 -> 1.33 at 373 trades); asymmetry is weak on BTC 1H (long PF 1.09 vs short 1.02). - XAU: long arm PF 1.33 (n=373) vs blended PF 1.15 (n=572); short arm ~1.0 - BTC: long arm PF 1.09 (n=384) vs short arm PF 1.02 (n=365); blended 1.054. Short-side trades dilute edge on XAU where long-side carries the signal. On BTC the asymmetry is marginal and both directions cluster near break-even. The behavior is consistent with a pivot-breakout (not true CHOCH) interacting with asset-specific trend regimes (XAU uptrend vs BTC mixed). Future CHOCH work on XAU should be long-biased or direction-gated. BTC CHOCH_v2 requires an orthogonal filter (session, regime) rather than direction restriction alone. ---. --- ---.
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
---

---
2026-04-14 | Tags: regime_age, HTF_quantization, dual_time_model, measurement_layer, engine_v1_5_5 | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P02 (v1.5.5 governed run) | Run IDs: d87a73ea7beedd1d91a1f701

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
---

---
2026-04-14 | Tags: regime_age_exec, dual_time_model, engine_v1_5_6, probe_validation | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P02 | Run IDs: 47ec676b31654d49e187721a

Engine bumped v1.5.5 -> v1.5.6. Added exec-TF regime-age clock as a second, orthogonal probe (separate from HTF clock). run_stage1 derives df['regime_age_exec'] on exec TF via groupby((regime_id != regime_id.shift()).cumsum()).cumcount(); engine reads at signal + fill bars; emitter + RawTradeRecord now carry regime_age_exec_signal / _fill.
Exec-TF distribution on 46_P02 re-run (363 trades):
- Exec Delta +1: 355 trades (97.8%) — dominant, as expected under next_bar_open (exec clock ticks exactly one bar between signal and fill).
- Exec Delta  0: 0 trades.
- Exec Delta <=-1: 8 trades — same 8 "regime flip" trades visible on HTF as Delta <=-2. Consistency check passed.
Conclusion on HTF anomaly: the Delta=0 dominance observed on the HTF clock (267/363 = 73.6%) was 100% an HTF-quantization artifact. Those same trades are Delta +1 on exec TF. Both clocks now coexist; neither is "the truth" on its own. HTF clock = macro (regime-age at HTF granularity); exec clock = micro (bars-since-regime-change at exec granularity). regime_alignment_guard.py has warn rules for both clocks (HTF: delta -1 / >=2 non-empty; exec: delta=+1 dominance drop below 80%). v1.5.6 vault close deferred until probe-driven analysis yields an actionable finding.
---
---

---
2026-04-17 | Tags: exit_timing, mean_reversion, h4, cmr, signal_persistence, reentry_frequency | Strategy: 53_MR_EURUSD_4H_CMR_S01_V1_P00..P05 | Run IDs: P00, P01, P02, P03, P05 (EURUSD, 2024-01-02 -> 2026-04-15)
For the 3-consecutive-close MR signal on EURUSD H4, a 3-bar time-exit (P01) dominates all tested alternatives (day-close, 6-bar, PnL-gated 1-2 bars, signal-only). P01 PF=1.17 / SQN=1.09 / DD=4.83%. P02 PF=1.14 with higher DD (11.48%). P05 PF=1.11 with avg_bars=11.63 and ~50% lower trade count. P03 PF=1.01, showing edge collapse under early profit-taking. Edge is concentrated in a short 2-3 bar window. Exiting too early truncates the positive tail, while holding beyond this window leads to edge decay. Signal persistence is not the dominant driver; re-entry cadence and capital recycling are key contributors to total PnL. For consecutive-close MR signals on H4 FX: default exit = ~3 bars; avoid PnL-gated early exits; avoid relying solely on signal reversal; re-entry frequency is additive to performance even when per-trade expectancy is lower.
---

---
2026-04-17 | Tags: timeframe_scaling, mean_reversion, cmr, signal_quality, daily_tf | Strategy: 53_MR_EURUSD_1D_CMR_S02_V1_P00 | Run IDs: 423cb6c67747cc63ca063922 (EURUSD, 2024-01-01 -> 2026-04-14)
3-consecutive-close MR signal shows materially higher PF and stability on Daily (PF 1.65, SQN 1.47) vs H4 variants (best PF 1.17). 1D: 63 trades, PF 1.65, SQN 1.47, DD 0.034%, long PF 1.74 / short PF 1.52. H4 P01: 359 trades, PF 1.17, SQN 1.09, DD 4.83%. Edge persists across timeframe scaling and improves under noise reduction. Signal structure is consistent, but lower-frequency sampling increases signal quality at the cost of trade count. Daily timeframe is a higher-quality representation of the same signal. Next step is to increase sample size via multi-pair expansion before modifying thresholds or rules. ---.
---

---
2026-04-17 | Tags: macro-filter, dispersion-gate, consecutive-close, daily, fx-basket, usd-synth, jpy-synth | Strategy: 53_MR_EURUSD_1D_CMR_S02_V1 (P01/P02/P03) | Run IDs: P01_<18 pairs>, P02_<18 pairs>, P03_<18 pairs>

USD_SYNTH |z|>=0.5 entry gate improves aggregate FX-basket PF (1.10->1.16) and specifically repairs the weak SHORT leg (PF 0.97->1.06) and the losing 2024 year (PF 0.83->0.99), while removing 26% of trades.

P02 vs P01: trades 1067->792, PnL +$337->+$387, PF 1.10->1.16, SHORT PF 0.97->1.06.
P03 (USD or JPY union): trades 1067->1040 (−2.5%), PF 1.10->1.15 — minimal filtering effect due to high JPY coverage.

USD dispersion provides meaningful regime discrimination, while JPY dispersion at this threshold has near-universal coverage and therefore no effective filtering power. Macro factors differ in base-rate coverage and are not interchangeable as filters.

Macro filters must be evaluated by coverage before use. For this signal family:
- prefer USD-only dispersion gating
- avoid union-based filters with high-coverage factors
- next step: test stricter USD thresholds (|z|>=1.0) or intersection logic (USD AND JPY)
---

---
2026-04-17 | Tags: 53_MR, CMR, ASSET_SELECTION | Strategy: 53_MR_EURUSD_1D_CMR_S02_V1 | Run IDs: P07 vs P06
Removing persistently negative-expectancy pairs (NZDUSD PF 0.37, GBPUSD PF 0.73) materially improves system performance (PF 1.30→1.64, MAR 1.84→2.31). P06→P07: 363→322 trades; MaxDD 11.2%→10.0%; CAGR 20.6%→23.1%; net PnL +$544→+$616. The CMR signal is asset-sensitive. Performance depends on structural compatibility between the signal and the underlying pair behavior. Pairs with persistent directional regimes support the signal; balanced or mean-reverting pairs degrade it. Asset selection must be empirical and driven by compatibility, not predefined currency categories. Default approach: exclude structurally negative pairs and validate inclusion individually. ---.
---

---
2026-04-18 | Tags: burn-in-observation, regime-incoherence, mean-reversion, rsiavg, gbpjpy, double-entry, trend-filter, regime-lag | Strategy: 22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P05 (GBPJPY) | Run IDs: N/A — burn-in live observation 2026-04-17

GBPJPY double-entry on 2026-04-17 was NOT a clean regime miss — it was a regime incoherence event. The entry gate passed correctly by its own rules, but `market_regime` and `trend_regime` produced contradictory classifications on the second signal bar, masking an impending directional reversal.

Trade 1 (bar 01:30 SVR): entry SHORT @ 215.328, exit @ 215.304, net +0.024 pips (+small win).
  regime: volatility_regime=-1, trend_regime=-2 (strong_down), market_regime="unstable_trend"
Trade 2 (bar 02:30 SVR — immediate re-entry same session):
  entry SHORT @ 215.34, exit @ 215.46 (stopped out), net -0.12 pips (−0.59R approx).
  regime: volatility_regime=-1, trend_regime=-2 (strong_down), market_regime="range_low_vol"
The entry gate for Trade 2 passed because: vol_regime=-1 ✓, trend_regime<=-2 ✓ (direction gate), trend_score<=-2 ✓, rsi_avg>75 ✓.
Price moved UP from 215.294→215.324→215.46 — the "strong_down" trend_regime label was lagging.
Key observation: `market_regime` flipped from "unstable_trend" → "range_low_vol" in a SINGLE bar while `trend_regime` held at -2. These two labels are internally contradictory: a strong directional trend (trend_regime=-2) cannot simultaneously be a low-volatility range (market_regime=range_low_vol). The composite regime label (`market_regime`) had already signaled regime breakdown; the scalar label (`trend_regime`) had not yet updated.

Point A is CONFIRMED but nuanced. The regime detector did not fail to fire — it fired correctly within its rules. The failure mode is regime label incoherence: `market_regime` leading a regime shift that `trend_regime` lagged by ≥1 bar. The strategy gates on `trend_regime` only (via FilterStack direction_gate), making it blind to `market_regime` divergence as an early warning. The `market_regime="range_low_vol"` + `trend_regime=-2` combination is a structural contradiction that, in this instance, preceded a trend reversal. It may be a reliable precursor signal — but this is a single event and not yet validated.

1. A re-entry cooldown (min_bars_between_trades) would have prevented Trade 2 mechanically — simplest fix, no regime logic required. Requires replay validation before deployment.
2. A `market_regime` consistency gate — block entry when `market_regime` contradicts `trend_regime` (e.g., `range_low_vol` when trend_regime is ±2) — would be a more principled fix but requires backtesting to quantify the coverage/edge tradeoff.
3. Flag for future hypothesis: test whether `market_regime != trend-consistent label` is a reliable early-warning of regime breakdown across the RSIAVG family (not just GBPJPY P05).
4. Do NOT patch mid-burn-in. Log observation, continue monitoring; design fix as new directive with full replay validation.
---
---

---
2026-04-19 | Tags: 54_STR, MACD, CONVERGENCE, XAUUSD, 5M, FILTER_STACKING, REGIME_INTERSECTION | Run IDs: S01=019c8b6c (MACDB_S05), S02=12df81c6 (MACDX_S06), S03=84ea51f3 (MACDX_S13, renamed from S07 due to registry slot collision)

Strategy family: 54_STR_XAUUSD_5M_MACD*
On XAUUSD 5M, MACD + regime filters combine MULTIPLICATIVELY, not additively. Triple-convergence (event + bias + EMA trend) is the only configuration that crosses the quality gate; each single-filter variant fails.

Test window 2024-07-19 → 2026-04-17, SL=2xATR, TP=6xATR, no time/session filters, direction long_and_short.
  S01 MACDB  (event + bias)           : 1759 trades, PF 1.23, SQN 2.61, MaxDD 41.3%, Sharpe 0.99 → FAIL
  S02 MACDXE (crossover_trans + EMA)  : 2099 trades, PF 1.17, SQN 2.23, MaxDD 40.6%, Sharpe 0.77 → FAIL
  S03 MACDXC (event + bias + EMA)     : 1301 trades, PF 1.34, SQN 3.10, MaxDD 23.5%, Sharpe 1.36, Sortino 2.82, Ret/DD 9.91 → WATCH
Baseline reference: prior unfiltered MACDX_S06 collapsed at PF 0.97 (2164 trades) under flat-dedup.
Year-wise for S03: 2024 -$18, 2025 +$1153, 2026 +$1196 (near-flat 2024, consistent 2025/2026).

Filter stacking on momentum signals exhibits multiplicative edge recovery: two single filters each raise PF from 0.97 to ~1.2 (still failing), but their intersection lifts PF to 1.34 and DOUBLES SQN (2.23 → 3.10) while COMPRESSING DD by 42%. Neither filter is sufficient alone; both are load-bearing. S02's EMA-only filter is actively worse than S01's bias-only — EMA regime without event-timing discipline keeps too many false transitions.

1. For momentum-family entries on XAU 5M, regime filters must intersect, not union — at least event-timing + bias + trend alignment combined.
2. Do NOT evaluate convergence candidates by PF/trade-count alone; SQN and DD-compression are where intersection logic actually earns its cost.
3. S03 MACDXC is the only promote-worthy candidate of the family on XAU 5M. Candidate_status=WATCH; needs pre-promote quality gate (tail concentration, flat periods, edge ratio on individual trades) before advancing.
4. Next probe hypothesis (advisory): test whether this multiplicative pattern generalizes to FX 5M/15M and BTC 5M, or whether it is XAU-specific. If generalizable, triple-convergence becomes a default scaffold; if XAU-specific, it localizes the XAU regime-alignment prior.
---

---
2026-04-19 | Tags: 54_STR, MACDX, XAUUSD, 5M, VOLATILITY_FILTER, DIRECTION_CONDITIONAL | Strategy: 54_STR_XAUUSD_5M_MACDX_S13/S20/S21_V1_P00 | Run IDs: S20=58ccdb5b/S21=a6c1814e — see TradeScan_State/backtests/54_STR_XAUUSD_5M_MACDX_S{20, 21}_V1_P00_XAUUSD
Volatility-regime filter (exclude low) on S13 triple-convergence MACDX improves all risk-adjusted metrics; effect is overwhelmingly short-side. S13 N=1301 PF=1.34 SQN=2.64 DD=$235 top10=58%; S20 (both dirs vol!=low) N=817 PF=1.55 SQN=3.88 DD=$172; S21 (shorts only vol!=low) N=1134 PF=1.48 SQN=3.58 DD=$195. Short PF 1.385 -> 1.820 in both variants; longs identical S13 vs S21. Low-vol shorts were the contaminated cluster in S13; direction-conditional vol gate (short-only) recovers most of the benefit while keeping all long-side trades. S20 maximises PF/SQN/DD; S21 maximises PnL and reduces tail concentration to 48%. Prefer S21-style direction-conditional filters when one side's edge is already clean: cheaper in trade count lost, stronger on PnL. Use engine-owned volatility_regime via ctx.require inside try/except for dry-run safety; never import indicators.volatility.volatility_regime in strategy (engine-owned-fields guard).
---

---
2026-04-19 | Tags: infra, partial_exits, capital_wrapper, engine_v157, scope_decision | Strategy: 54_STR_XAUUSD_5M_MACDX_S23_V1_P00
Partial-exit infra integrated; exits rejected as edge lever after full accounting validation.
---

---
2026-04-20 | Tags: 54_STR, MACDX, XAUUSD, 5M, BE, partial_exit, engine_v157, sweep, close_based_ur | Strategy: S21-style sweep variants | Engine: v1.5.7
v1.5.7 parity PASS: no-hook S21 produces 1301 trades PF=1.182 R=170.32 — byte-identical to v1.5.6 (both baseline variants). S22 control (1532 trades, close-based UR stub) also PASS: every entry/exit timestamp and price identical across both engines. Key findings from 6-variant sweep on 20-month 5M XAUUSD data (neutral regime stub):

BE-only (V1) — ZERO effect: The v1.5.7 stop_mutation hook triggers on close-based UR >= 1.0001. On volatile 5M XAUUSD, losing trades frequently wick intrabar to 1R+ but close BELOW 1R — the close-based UR never fires for these trades. SL is checked against bar_low (resolve_exit uses OHLC), so a trade that wicks to 1R intraday but closes below 1R gets SL-hit at -1R later without BE ever firing. Result: 0 trades converted from -1R to 0R in 20 months. Close-based UR is too conservative for volatile short-TF markets.

Partial only (V2) — modest impact: 585/1301 trades (45%) had close >= UR 1.0001 and triggered partial at 50%. PF drops 1.182 → 1.169 (partial surrenders upside on subsequent TP hits), DD drops 39.89 → 29.33 R (−10.56R, −26%). Trade-off: slightly worse expectancy, meaningfully lower variance. Partial does activate — close-based barrier is crossed for 45% of trades even though losing trades never reach it.

BE+Partial+TP off (V3) — pathological lock-in: With TP disabled and BE at entry, trades reaching 1R are trapped indefinitely (stop=entry, no TP). Result: 11 total trades over 20 months. entry_when_flat_only blocks new entries while position is open. CONFIRMED: TP-off + BE creates near-immortal positions on XAUUSD 5M; do not use without a time-exit gate.

BE+Partial+TP on (V4) — identical to V2: BE adds nothing on top of partial for same reason as V1.

Design implication: For BE to be effective on 5M volatile markets, either (a) use bar_high-based UR threshold (intrabar; requires engine change), or (b) lower close-based UR trigger to 0.5 to capture partial runs, or (c) use bars_held-based BE gate instead of UR. DO NOT test BE further with close-based UR >= 1.0001 on 5M assets — the effect is zero.
---

---
2026-04-20 | Tags: 54_STR, MACDX, XAUUSD, 5M, BE, intrabar_ur, engine_design, CRITICAL | Strategy: S21-style baseline 1301 trades | Engine: post-hoc probe
CRITICAL FINDING — Intrabar BE is MATERIAL on XAUUSD 5M MACDX baseline.

Post-hoc probe on engine's exact 1301 trades: replaced close-based UR with bar_high (long) / bar_low (short) for BE trigger. Result: 301/933 SL exits (32.3%) convert from -1R to 0R. PF: 1.1819 -> 1.7481 (+0.5662). Total R: 170.3 -> 473.6 (+303.3R). Max DD: 39.89R -> 12.00R (-70%). Mean converted R before: -1.008R (exactly the SL level). After: 0.000R. Net gain: +303.3R across 301 trades (1.008R per conversion). The remaining 632 SL trades had intrabar UR < 1 throughout — those are genuine losers that bar_high never crossed entry+1R.

Math check: 368 TP wins x ~3R + 0R x 301 BE + (-1R) x 632 genuine_SL = ~472R (~473.6 reported, consistent).

Root cause: SL check uses bar_low (OHLC), but UR uses close. Trades that spike to 1R+ intrabar then close below 1R get SL-hit later — this mismatch is the asymmetry BE is solving. Intrabar UR (bar_high for longs) aligns the trigger with the actual market path, not just the close.

Action required: v1.5.8 engine must expose ctx.unrealized_r_intrabar (bar_high for long, bar_low for short) alongside existing close-based ctx.unrealized_r. Strategy check_stop_mutation uses intrabar UR >= threshold to fire BE. No other engine changes. Probe is conservative (no downstream entry re-scheduling modeled) — real improvement may be higher or lower depending on position freed-up slots.

Do NOT implement via close-based UR workaround (threshold lowering etc.) — the mechanism is fundamentally bar_high/bar_low. Engine change is the correct path.
---

2026-04-21 | Tags: CMR, FX-1D, TF-dilation, basket, macro-filter, JPY-concentration

Strategy: 53_MR_FX_1D_CMR_S02_V1_P00/P03
Run IDs: 53_MR_FX_1D_CMR_S02_V1_P00, 53_MR_FX_1D_CMR_S02_V1_P01, 53_MR_FX_1D_CMR_S02_V1_P03

Finding:
3-bar consecutive-close pattern on FX 1D shows marginal basket edge (avg PF=1.08) with JPY pairs dominating: USDJPY PF=1.68, CADJPY PF=1.63 vs non-JPY/non-EUR pairs clustering near PF=1.0 or below (7/18 losing).

Evidence:
11/18 symbols PF>1.0; losers range PF=0.65-0.97. P03 macro union gate: PF avg 1.08->1.10, PnL +29% (268->345 USD total), trades 79->72 avg per symbol.

Conclusion:
TF dilation 4H->1D did not preserve edge uniformly. Residual signal concentrates in JPY crosses, likely driven by JPY macro-regime correlation with 3-bar directional patterns at daily resolution. Macro union gate adds mild selection value but does not rescue the non-JPY tail.

Implication:
If pursuing CMR at 1D, narrow to JPY pairs only as targeted follow-up. Full 18-pair basket is not viable. Do not promote any P00/P01/P03 symbols -- PF and trade counts are below portfolio quality gate.
2026-04-23
Tags:
XAUUSD
15M
ZREV
filter_stack
directional_trend_filter

Strategy: 55_MR_XAUUSD_15M_ZREV_S05_V1_P00
Run IDs: 378c4f957101046dfbc0190f

Finding:
S05 locks in volatility_filter (gte 0) + trend_filter(direction_gate: shorts gated to trend_regime >= 0) over ZREV P08 base as the chosen XAUUSD 15M mean-reversion candidate across the S04/S05/S06 probe series.

Evidence:
S05 PF=1.31 exp=$1.70 R/DD=10.12 SQN=3.51 trades=1755 (vs S04 PF=1.20 exp=$1.13 R/DD=6.02; S06 added regime_age filter PF=1.33 but R/DD regressed to 9.56).

Conclusion:
Short-side weakness in S04 (PF=1.04) driven by counter-trend shorts in weak_down/strong_down regimes; directional trend filter eliminates that loss cluster (short PF 1.04 -> 1.21, WeakDn PnL -$233 -> +$73, StrongDn -$384 -> -$51) without touching long side. regime_age filter (S06) is a weaker probe: age 0/1 removed but edge dilutes at age 2.

Implication:
Default next-iteration probe: test asymmetric entry thresholds or long-side short-squeeze detection rather than stacking more FilterStack blocks. Do NOT stack regime_age on top of S05 - marginal PF gain is eaten by R/DD regression.

---

2026-04-23 | Tags: XAUUSD, 15M, ZREV, tail-dependence, structural-ceiling, S05-series-exhausted | Strategy: 55_MR_XAUUSD_15M_ZREV_S07/S08/S10/S11/S12/S13_V1_P00 | Run IDs: 97c6aa71ab48cd05bd27b876, be36a5e5cc2399515dec46fd, 98f343160e76a65512584a85, S11/S12/S13 (see FSP)

Finding:
S05 base (PF 1.31, tail-PF 0.53, Gate 6 HARD FAIL) cannot be lifted past robustness Gate 6 (PF-after-top-5%-removal >= 1.0) via any single- or dual-lever probe. Six successive probes (S07 BE-at-+1R, S08 BE+trail-after-+2R, S10 slope_norm 0.0005 entry filter, S11 slope_norm 0.0003 relax, S12 z-gate entry 0.5, S13 partial-50%-at-+1R + BE) walk tail-PF from 0.53 -> 0.87 -> 0.90 ceiling without breaching 1.0.

Evidence:
Stop-side probes (S07/S08) no-op on tail metrics (tail-PF 0.53/0.51): Z-extension exit at 2.15-sigma fires before trades reach +2R MFE in 95.5% of cases, so trail never fires and BE is noise-benign. Entry-side probe S10 (slope_norm > 0.0005) lifts tail-PF 0.53->0.87 but cuts trades 41% (1755->1038) and real-model PF drops 1.30->1.24. Relaxation S11 (0.0003) recovers trades but tail-PF collapses back to 0.55 -- the quality gain is non-linear and sits in the 0.0004-0.0005 window. S12 z-gate (|z|>0.5 entry) holds tail-PF at 0.87 but slips PF to 1.32. S13 (partial + BE exit) reaches tail-PF 0.90 (new best), Max DD $235 (new best), flat-period 16.5%, Top-5 concentration 28.5% -- every robustness dim improves but Gate 6 still XX at 0.90.

Conclusion:
The Z-extension exit at 2.15-sigma is itself the tail-generating mechanism. Winners that reach Z>=2.15 are structurally larger than median trades because the distance from entry (near HMA) to Z=2.15 is multi-sigma. Any exit-side intervention that preserves full position size to Z-exit preserves the fat tail. Stop mutation cannot help because trades rarely reach +2R MFE before Z-exit fires. Entry-side filtration has a ceiling at tail-PF ~0.87-0.90 because the trades that survive a tight entry filter are disproportionately the ones that go on to hit the tail. Partial extraction gets closer (0.90) but cannot breach 1.0 because the remaining 50% runner still carries the full tail.

Implication:
S05 series is exhausted at tail-PF 0.90 ceiling. Do NOT iterate further on ZREV S-variants (no threshold tweak, no stacking, no second partial) -- marginal gains are unlikely to clear 1.0 and risk of overfitting is high. S13 is the structurally cleanest variant (best-of-series on Gate 6, Max DD, flat-period, Top-5 concentration) but cannot promote because Gate 6 remains HARD FAIL. Pivot to a different mean-reversion architecture: the next MR probe should NOT use Z-sigma-extension exit as the primary profit-taking mechanism, since that mechanism is what manufactures the tail dependency being rejected by Gate 6.
2026-04-23
Tags:
MR
ZREV
architecture-dead
cross-asset
tail-dependence

Strategy: 55_MR_EURUSD_15M_ZREV_S15_V1_P00
Run IDs: 2212a1f63de22d584a3309da

Finding:
ZREV (Z-extreme entry + zero-cross exit) is architecturally tail-dependent across assets; XAUUSD directional drift masked weakness that EURUSD exposed.

Evidence:
S14 XAUUSD: PF 1.20, Top-5=123.4%, Long PF 1.82 vs Short PF 0.93. S15 EURUSD (S14 clone, pip-floor stop): PF 0.93, Top-5=148.4%, Long PF 0.96 vs Short PF 0.90 — symmetrically broken.

Conclusion:
Zero-cross exit manufactures the tail regardless of symbol; XAUUSD's apparent edge was Long-WeakDn drift (PF 3.45). Proper SL calibration does not resolve the distribution pathology.

Implication:
ZREV architecture is not viable under distributed-edge constraint. Do not probe further zero-cross MR variants on any symbol. S01-S13 tail-PF 0.90 ceiling + S14/S15 cross-asset confirmation closes this architecture.
2026-04-24
Tags:
state_primitive
REGMISMATCH
regime_age
architecture_probe
filter_layer_candidate

Strategy: 58_STATE_XAUUSD_15M_REGMISMATCH_S01_V1_P00
Run IDs: 81dd13a679d1081c002bde4a

Finding:
State-mismatch (|delta_trend_regime|>=2 + regime_age_exec<=5) on XAUUSD 15M isolates a real but too-sparse edge to carry a standalone strategy; retain as filter-layer concept only.

Evidence:
34 trades / 25 months (1.4/mo); PF 3.13 but Top-5 concentration 90%, longest flat 539 days; Long PF 1.17 vs Short PF 6.25 (asymmetric); 100% of fills at regime_age 0-1, yearwise density collapses 28T/5T/1T across 2024/25/26.

Conclusion:
State primitive isolates rare, asymmetric events but produces insufficient density and excessive tail concentration for standalone deployment; the short/WeakDn cluster is mechanically real, the long side is near break-even.

Implication:
Do not pursue as standalone probe line; park REGMISMATCH state primitive as a candidate gating/filter feature on future price-based entries (e.g. zscore, momentum, breakout) where density is already sufficient. Re-evaluate only in filter-layer context, not as P00/P01 extension.
2026-04-24
Tags:
idea59
runfail
engine-interface
no-trades
closure

Strategy: 59_MICRO_XAUUSD_15M_RUNFAIL_S01_V2_P00
Run IDs: efda76b5e8e4071861074500

Finding:
Idea 59 (RUNFAIL: 3-down-close + midpoint-confirm long) closed as engine-interface diagnostic branch, not economic falsification. V1 (inline close-rotation state) and V2 (validated candle_sign_sequence primitive) both produced NO_TRADES on XAUUSD 15M 2024-01-01..2026-03-20.

Evidence:
Shift-based reference counts 205 entry-eligible bars on same window; primitive matches bar-for-bar. Dry-run (1000-bar sample, direct check_entry) emits 2 signals. Stage-1 engine loop on full window emits 0 trades for both V1 and V2.

Conclusion:
Hypothesis was never economically tested. The bug lies downstream of strategy-owned state — in engine ctx field surfacing or FilterStack interaction — where run_len / prev_high / prev_low are not reaching check_entry during Stage-1 execution despite succeeding under dry-run.

Implication:
Do not re-open idea 59 as a research branch. Any similar signal-bar entry depending on multi-bar ctx fields requires an engine-side diagnostic first (compare dry-run vs Stage-1 ctx dict contents for the same bar). Treat dry-run vs Stage-1 trade-count divergence as a first-class engine bug, not a strategy bug.
2026-04-24
Tags:
idea-60
symseq
btcusd
regime-age
local-edge
asymmetric
scale-local

Strategy: 60_MICRO_BTCUSD_4H_SYMSEQ_S03_V1_P00
Run IDs: dbd9f979388cd7de61698992, 73e52526fc336b2b0c764974, 19f8f9e807b9cc6197b9edd5

Finding:
SYMSEQ 001+regime_age{0,1} edge on BTCUSD 4H is narrow and non-generalizable: confirmed long-only, 4H-local, drift-carried. Short-side mirror (110) and 1H scale transport both fail.

Evidence:
S03 BTC 4H long: 90T PF 1.73 3/3 positive years. S04 BTC 4H short (110, no filter): 523T PF 0.995 1/3 positive. S05 BTC 1H long (same filter): 361T PF 0.988 1/3 positive. Post-hoc age-slice inverts: long age=0 PF 2.44 vs short age=0 PF 0.81.

Conclusion:
Mechanism is neither symmetric microstructure nor scale-invariant. It is a specific 4H+1D-HTF coupling capturing long-side continuation within 1 trading day of a regime flip on a trending asset; 'fresh-flip symbolic edge' as a general principle is unsupported.

Implication:
Do not promote regime_age{0,1}+001 to other symbols, timeframes, or short side without re-establishing each from scratch. Future symbolic-sequence probes must pre-declare direction + TF locality before generalization; post-hoc slices do not license extrapolation.
2026-04-28
Tags:
gma_slope_flip
regime_asymmetry
htf_filter

Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P00
Run IDs: 4e36cfcfe8bfeceff7d76060

Finding:
Pure GMA slope-flip on NAS100 5M generates positive expectancy in WeakDn / Neutral regimes but loses on WeakUp; total edge is regime-asymmetric.

Evidence:
WeakDn 407T +$541 PF~1.6; WeakUp 705T -$149 PF<1 (largest trade share, worst bucket)

Conclusion:
Slope-flip catches reversal-into-trend in down/sideways markets but whipsaws under sustained-up conditions where the GMA flips frequently without mean-reversion; WeakUp is dominated by failed shorts that get stopped.

Implication:
Future GMAFLIP variants (S01 P01 onward) MUST gate entry on HTF trend regime: skip WeakUp bucket entirely; allow WeakDn / Neutral trades unconditionally.
2026-04-28
Tags:
gma_slope_flip
filter_iteration
negative_finding
regime_filter

Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P01..P04
Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P01, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P02, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P03, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P04

Finding:
Sweep across 4 GMAFLIP filter variants: HTF regime filter is the only individually-positive filter. Persistence filter alone degrades PF; combined regime+persistence trades return for drawdown safety; tighter Gaussian sigma (4.0 vs 5.0 DSP convention) is worse.

Evidence:
P01 regime: PF 1.13->1.25, Sharpe 0.51->0.92; P02 persistence: PF 1.13->1.09 (worse); P03 combined: best DD 0.15% but PF 1.20<P01

Conclusion:
Slope-flip wobbles persist 3+ bars natively, so persistence filter rarely triggers and just delays entries by 3 bars (worse fills). HTF regime is the structural filter that matters because P00 trade_edge data showed losses concentrated in WeakUp regime. Sigma=5 (DSP length/6 convention) outperforms sigma=4 — more responsive MA generates noise flips without alpha.

Implication:
For GMAFLIP variants going forward: (a) always include HTF regime filter (skip regime>=1); (b) skip persistence filter unless combined with another noise reducer; (c) lock sigma at length/6 DSP convention; (d) next iterations should test stop multiplier (1.5x / 2x / 4x) and HTF timeframe (1H regime feed).
2026-04-28
Tags:
gma_slope_flip
persistence_sweep
slope_angle
non_monotonic

Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P05..P08
Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P05, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P06, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P07, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P08

Finding:
Persistence-bar sweep (1, 3, 5, 7) on top of regime filter is non-monotonic and never beats P01 (no persistence). Slope-angle filter at 5pct of ATR over-restricts to 32 trades but those 32 hit best PF/Sharpe — angle threshold should be much lower.

Evidence:
Persistence sweep PF: bars=0 1.25, bars=1 1.15, bars=3 1.20, bars=5 0.98 (NEG), bars=7 1.12; slope angle 5pct: 32T PF 1.30 Sharpe 1.41

Conclusion:
Slope flips on Gaussian length=30 sigma=5 naturally persist 7+ bars in 95pct of cases — persistence filter rarely triggers and only delays entries. The PF=0.98 dip at bars=5 is sample-noise, not a structural minimum. Slope-angle filter showed best per-trade quality but threshold of 5pct of ATR cuts 98pct of signals; lower thresholds (0.5-2pct) would yield more usable variants.

Implication:
S02 going forward: (a) drop persistence from filter library; (b) sweep slope_angle threshold at 0.005, 0.01, 0.02, 0.03 to find usable upper bound; (c) regime filter remains the only robust filter; (d) test stop multiplier sweep next (1.5, 2.0, 4.0 vs current 3.0) since DD per trade is 50pct of stop budget.
2026-04-28
Tags:
gma_slope_flip
stop_sweep
slope_angle_combined
exhaustive_sweep

Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P09..P11
Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P09, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P10, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P11

Finding:
Slope-angle filter combined with regime filter (P09 1pct, P10 2pct) hurts every variant — over-filtering removes good trades. Tighter stop (1.5xATR vs 3xATR) hurts win rate from 42pct to 33pct, indicating 3xATR is at or above the noise floor and 1.5x sits inside it.

Evidence:
P09 (regime+slope1pct): 549T 63 PF 1.11 (vs P01 853T 59 PF 1.25); P11 (regime+stop1.5x): 1039T 06 WR 33pct (vs P01 853T 59 WR 42pct)

Conclusion:
Filter stacking is sub-additive: each filter removes more good trades than bad ones above the first. P01 (regime alone) is the structural local optimum for this primitive on this data. Stop=3xATR is correct/loose — tighter stops sit in the noise envelope of NAS100 5M and clip valid trades. Slope angle works in isolation (P05) but conflicts with regime filter when stacked.

Implication:
GMAFLIP family is parameter-saturated: P01 is the operating point. To improve further requires architectural change — try GMAFLIP on higher timeframe (15M, 1H) where regime dynamics differ, or add a genuinely independent filter (volume/liquidity/news) that does not overlap with regime. Stop sweep direction should be wider (4x, 5x) not tighter.
2026-04-28
Tags:
gma_slope_flip
filter_by_exclusion
session_filter
vol_filter
sub_additive_confirmed

Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P12..P14
Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P12, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P13, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P14

Finding:
Filter-by-exclusion final pass tested 3 orthogonal filters (NY-only session, drop-London surgical session, Direction*Volatility via atr_percentile). All three improved Sharpe and DD vs P01 baseline but reduced absolute P&L. None overcame the filter-stacking sub-additivity rule established in earlier batches.

Evidence:
P12 NY-only: 336T 79 PF 1.23 Sharpe 1.05; P13 surgical-session: 554T 47 PF 1.22 Sharpe 0.96; P14 vol filter: 677T 90 PF 1.16 Sharpe 0.72; all vs P01 853T 59 PF 1.25 Sharpe 0.92

Conclusion:
Each filter cuts roughly proportional good and bad trades. The directional buckets exposed by the report (Asia Long PF 1.57, London 1.04, Long*LowVol 0.39) become diluted when implemented as filters because the underlying regime filter (P01) already removes much of the same loser population. Genuine filter independence requires the new filter to address losses NOT already addressed by regime filter, which is rare.

Implication:
GMAFLIP family fully exhausted on NAS100 5M. P01 (regime alone) is the operating point. Future variants must change the SIGNAL primitive (not stack more filters) to escape the sub-additivity wall — try GMAFLIP on 15M/1H, on a different symbol class (XAUUSD/BTCUSD), or replace slope-flip with a different trend primitive entirely (Hull/Kalman/Linreg).

Strategy: Kalman Price Filter [BackQuant] — Pine v6 prototype (TS_Execution/pine)
Run IDs: kalman_price_filter_v1_0_strategy.pine (locked baseline), kalman_price_filter_v2_0_strategy.pine (rejected — order-2), kalman_price_filter_v1_1_strategy.pine (+session, equivalence-tested), kalman_price_filter_v1_2_strategy.pine [LOCKED] (+orthogonal triple stack)

Finding:
Adapted BackQuant's Kalman Price Filter (order-1 scalar Kalman) into a long-only flip strategy on NAS100 5M. Calibrated baseline (OHLC4 source, M=4 measurement noise, 2-tick slippage, all sessions) achieved PF 1.195 / Sharpe 0.545 / +26.9% annual / max DD 4.5%. Stacking three orthogonal regime filters on top — ADX(15) trend strength, smoothed RSI(2)/SMA(3) > 35 momentum confirmation, Hurst(0.45) persistence, all loose thresholds — produced strict additivity: final config achieves PF 1.312 / Sharpe 0.640 / Sortino 2.215 / +30.5% annual / max DD 4.0%, with per-trade $ +71% vs baseline ($1.14 -> $1.95). This contradicts the GMAFLIP P-sweep finding of universal sub-additivity. The reconciling principle is signal-density: HIGH-frequency signal generators (>1500 trades/year on native TF) admit additive loose-filter stacking; LOW-frequency generators (<1000 trades/year) suffer sub-additivity even with loose filters.

Evidence:
v1.0 baseline 2358T 27.23%WR PF 1.195 Sharpe 0.545 Sortino 1.581 DD$451 $1.14/T
v2.0 order-2 Kalman 2131T 36.74%WR PF 1.163 Sortino 1.799 (REJECTED — velocity overshoots reversals on financial returns; WNA assumption violated)
v1.1 drop-Asian session 1428T PF 1.20 Sharpe 0.40 Sortino 1.108 DD$677 (REJECTED — sub-additive, DD +50%, Sharpe -27%)
v1.2 ADX(15) alone 1801T PF 1.248 Sharpe 0.638 Sortino 1.805 DD$497 $1.51/T
v1.2 Hurst(0.45) alone 2160T PF 1.221 Sharpe 0.561 Sortino 1.616 DD$480 $1.31/T (best absolute P&L of any single filter at $2,837)
v1.2 ADX(15)+Hurst(0.45) 1670T PF 1.282 Sharpe 0.631 Sortino 1.920 DD$396 $1.75/T
v1.2 ADX(15)+RSI(35)+Hurst(0.45) 1568T 27.87%WR PF 1.312 Sharpe 0.640 Sortino 2.215 DD$395 $1.95/T (PRODUCTION LOCK)
B&H 12-month return $3,901 — locked config captures 78.1% of B&H with 26% of B&H DD profile

Conclusion:
1. SIGNAL-DENSITY PRINCIPLE: Filter additivity vs sub-additivity is determined by signal-generator frequency, not by filter quality. Kalman flip generates 2358 raw signals/year on NAS100 5M; loose orthogonal filters can each prune the worst 5-15% tail without touching the core signal — strict additivity. GMAFLIP S01 generates 600 raw signals/year on same instrument/TF; even loose filters prune disproportionately into edge — sub-additivity. This explains the contradiction between the two experiments.
2. LOOSE THRESHOLDS WIN: ADX=15 (below 20 textbook), RSI=35 (below 50 neutral), Hurst=0.45 (below 0.50 random walk). Each catches only the worst tail of its dimension. Strict thresholds (ADX 25, RSI 50, Hurst 0.50) overfilter and reduce edge.
3. ORTHOGONALITY MATTERS: ADX measures strength of directional movement (directionless); RSI measures recent momentum direction (short window); Hurst measures long-memory persistence (regime). All three look at completely different properties — that's why their intersection contains higher-quality trades than any pair.
4. ORDER-2 KALMAN INFERIOR for financial series: White-noise-acceleration assumption is violated by jump-prone returns; velocity term overshoots at reversals, compressing R:R from 3.2 to 2.0. The simpler order-1 prediction (assume tomorrow=today, then correct) is more robust to non-stationary noise. Order-2 wins win rate but loses on PF/DD/Sharpe.
5. SESSION FILTERING SUB-ADDITIVE on this strategy too — dropping Asian session lost $606 P&L without improving PF, with DD +50% and Sharpe -27%. Asian's small wins were acting as DD buffer (correlation-smoothing across sessions).
6. LONG-ONLY STRUCTURAL for index: Both-direction mode bled $939 on shorts and triggered all 32 margin calls. NAS100's structural drift makes shorting sub-zero-expectancy.
7. INPUT PRE-FILTERING (close -> OHLC4) is a separate axis from indicator parameter tuning. Adds win rate at the cost of slight R:R compression. OHLC4 is the locked source.

Implication:
1. Production-locked configuration ready for Trade_Scan port: 64_TREND_IDX_5M_KALFLIP_S01_V1_P00 with all three filters enabled at locked thresholds. All required indicators (kalman_filter, adx, rsi, hurst) already exist in repository per user; only the strategy directive YAML needs to be written.
2. Future research must classify the signal generator by frequency BEFORE designing filters. HIGH-frequency primitives (>1500T/yr) can stack 2-3 orthogonal loose filters. LOW-frequency primitives (<1000T/yr) should use a single strong regime filter and avoid stacking.
3. The signal-density principle should be tested on other HIGH-frequency strategies in the family to confirm it generalizes beyond Kalman/NAS100. Any flip-style strategy on liquid intraday TF is a candidate.
4. Per-trade $ +71% gain is the cost-survival headline. Strategy has substantial headroom against spread widening and would degrade gracefully under stress. Expect PF to hold above 1.20 even under 2x slippage stress (4 ticks vs 2).
5. Order-2 Kalman exploration is a closed branch for financial series. Future Kalman variants should explore: (a) different price sources (HLC3, HL2), (b) different timeframes (15m, 1h on NAS100), (c) different liquid index symbols (SPX, DAX). NOT order-2.
6. The full 24h baseline (no session filter) should be retained — session attribution is an artifact of trade-sequencing, not a source of independent edge.
2026-04-29
Tags:
kalman_filter
filter_stacking_additive
signal_density_principle
orthogonal_filters
adx_hurst_rsi
production_locked
nas100_5m
loose_threshold_principle
order_2_rejected
session_filter_subadditive
2026-05-02
Tags:
workflow
methodology
per-symbol-research
decomposition-discipline
multi-symbol-aggregation-bias

Strategy: 63_BRK_IDX_30M_ATRBRK_S07-S12 series
Run IDs: 0fbca8cf990bb30dbfd3119e, 56ab1736171d9ec2084ee049, 33882bb3a2a66caee7f4ed4e, 7add7c9da329e1fad8b175f9, 43474c416f4f693019c22017, baa4d8ed04f1a744cac1e970

Finding:
Multi-symbol baskets in research masked per-symbol heterogeneity. S12 V2 combined PF 1.34 hid that NAS100 alone was PF 1.55 while GER40 had degraded to PF 1.07; S07 aggregate short PF 1.07 hid that 2 of 5 short trend cells were structurally profitable (Short x WeakDown PF 1.53, Short x StrongDown PF 1.35) -- those cells were destroyed when blanket long-only filter was applied in S11 V2.

Evidence:
S12 V2: NAS100 PF 1.55 / 303 trades vs GER40 PF 1.07 / 178 trades; combined PF 1.34. S07 short side: 2 of 5 trend cells profitable (PF 1.35-1.53), aggregate short PF 1.07 hid them.

Conclusion:
Aggregate metrics (PF, Sharpe, top-5%) on multi-symbol or aggregated direction populations average over heterogeneous sub-populations. Filter decisions made on aggregates strip working cells alongside losing ones. Robustness gates run on combined trades cannot reveal which symbol carries the edge or which direction-cell pairs work.

Implication:
Workflow rule: Test ONE symbol at a time in research. Multi-symbol baskets are for DEPLOYMENT (per Multi-Symbol Deployment Contract), not hypothesis testing. Direction filters must be evaluated per-cell (Direction x Vol x Trend), not at aggregate Long/Short level. Per-symbol robustness must precede multi-symbol promotion. Sequence: single-symbol baseline -> per-cell decomposition -> aggregate only proven cells -> per-symbol robustness gate -> portfolio composition.
2026-05-02
Tags:
kill-record
donchian-breakout
news-event-only
robustness-reject
kalflip-precedent-not-applicable
architectural-null
idea-63-parked

Strategy: 63_BRK family parked: 15M/5M/30M ATRBRK on NAS100/JPN225/GER40/UK100/ESP35/EUSTX50, all variants S00-S13
Run IDs: 0fbca8cf990bb30dbfd3119e, 56ab1736171d9ec2084ee049, 33882bb3a2a66caee7f4ed4e, 7add7c9da329e1fad8b175f9, 43474c416f4f693019c22017, baa4d8ed04f1a744cac1e970, 3290130654b3179087aabddf

Finding:
Idea 63 (Donchian Channel Breakout, Pine port) is structurally a news-event detector on OctaFX index data, not a continuous-edge breakout strategy. Outside news windows the strategy loses money on every variant tested (S07 outside-news PF 0.74, S11 V2 long-only 0.93, S12 V2 long+highvol 0.86, S13 V2 NAS100-alone 0.56). Filters (long-only, high-vol regime) successfully concentrated the edge cell and improved the Top-5%-removal robustness gate from 0.66 -> 0.78 -> 0.85, but never crossed the 1.0 threshold. Per-symbol research discipline (S13 V2 NAS100-alone) confirmed the structural news-event dependency is intrinsic to NAS100 signal, not an artifact of multi-symbol aggregation -- in fact GER40 was mildly diversifying the tail damage in the basket.

Evidence:
Donchian S13 V2 NAS100-alone: News PF 4.83 vs Outside PF 0.56 (Outside loses 2208 USD over 28mo). KALFLIP P15 (override precedent): News PF 3.50 vs Outside PF 1.11 (continuous edge intact).

Conclusion:
The edge mechanism is breakout direction selection during forced volatility expansion (news releases). Without that exogenous shock, the channel breakout signal has negative expectancy on these markets at this timeframe. KALFLIP-style --skip-quality-gate override is not justified here: KALFLIP had a positive outside-news baseline (PF 1.11) so news amplified an existing edge; Donchian has no baseline edge (PF 0.56) so news IS the edge. A news-feed disruption would convert KALFLIP from PF 1.27 to ~1.11 (degradation) but would convert Donchian from PF 1.22 to ~0.56 (catastrophic). Confirmed across 4 robustness runs (S07, S11 V2, S12 V2, S13 V2).

Implication:
Park family 63_BRK_IDX_*_ATRBRK across all timeframes (5M, 15M, 30M) and symbols. Do not retest classical Donchian channel breakout on OctaFX index data. Future work in this thread must explicitly frame as a news-window strategy (tag NEWSBRK or similar), declare the news-feed dependency upfront, and validate the news-calendar is a stable production input before any promotion attempt. Confirmed structurally distinct from KALFLIP precedent: --skip-quality-gate requires positive outside-news PF >= 1.0 as documented precondition, not just event-driven. Workflow rule reaffirmed: per-symbol research discipline is mandatory; multi-symbol aggregation hides per-symbol heterogeneity (S12 V2 NAS100 PF 1.55 vs GER40 PF 1.07 within combined 1.34).


2026-05-03
Tags:
kill-record
news-window-strategy
nas100-jpn225-ger40
event-window-dependency
tail-pf-ceiling
news-feed-production-risk
idea-64-parked

Strategy: 64_BRK_IDX_5M/15M/30M_NEWSBRK_S01-S05 family on NAS100, JPN225, GER40
Run IDs: see outputs/NEWSBRK_DISCOVERY_REPORT.md, outputs/NEWSBRK_15M_COMPARATIVE_2026_05_03.md, outputs/NEWSBRK_A1_5M_PRE_EVENT_TEST_2026_05_03.md, outputs/NEWS_EDGE_DISCOVERY_2026_05_03.md

Finding:
NEWSBRK family -- pre-event range break with calendar-aware indicator surface -- fails on every NAS100/JPN225/GER40 variant tested (5M, 15M, 30M; S01 through S05; mixed A1 pre-event range and A2 event-window architectures). Edge concentrates entirely inside the news window: outside-news PF on the strongest variant remains < 1.0. The pattern is the inverse of KALFLIP precedent -- KALFLIP had positive outside-news baseline (PF 1.11) and news amplified existing edge; NEWSBRK has no baseline so news IS the edge.

Evidence:
12-directive matrix S02-S05 across 5M/15M, 6/6 with adequate coverage ran admission -> Stage 4 -> PORTFOLIO_COMPLETE; classifier-gate verdicts all PASSED with COSMETIC against same-sweep-slot priors. None met the promote quality gate. Tail-PF ceiling held below the threshold across the family; flat-period and edge-ratio gates both failed on lead variants. Multi-symbol aggregation initially masked NAS100-specific weakness but per-symbol decomposition confirmed structural null on each symbol independently.

Conclusion:
NEWSBRK on OctaFX index data is a news-event detector, not a continuous-edge architecture. The same architectural-null verdict reached on idea 63 (Donchian) applies here for the same reason: the strategy's only profitable trades require an exogenous volatility shock from a known news release. Without a stable, low-latency news-calendar feed in production this is a non-starter; with one, the strategy is wagering all alpha on calendar correctness rather than signal correctness.

Implication:
Park family 64_BRK_IDX_*_NEWSBRK across all timeframes (5M, 15M, 30M) and symbols (NAS100, JPN225, GER40). Do not extend to additional indices or to FX/Crypto without first proving outside-news PF >= 1.0 on a different asset class. Future news-window work must declare the calendar dependency upfront and validate the calendar source as a production input before promotion. The KALFLIP --skip-quality-gate override precedent does NOT extend to news-only strategies -- it requires positive outside-news baseline as a precondition.

2026-05-03
Tags:
methodology
selection-bias
post-hoc-filtering
path-a-vs-path-b
entry-when-flat-only
causal-wrapper-required
research-discipline

Strategy: RSIAVG EURUSD 30M (Path A vs Path B comparative study)
Run IDs: see outputs/PHASE2_PATHA_RSIAVG_EURUSD_2026_05_03.md, outputs/PHASE2_PATHB_RSIAVG_EURUSD_2026_05_03.md, outputs/PHASE2_PATHA_GENERALITY_TEST_2026_05_03.md

Finding:
Two filtering approaches were tested on the same RSIAVG EURUSD 30M baseline: (Path A) restrict trade ENTRIES via the FilterStack so the strategy only takes signals during the allowed window, vs (Path B) take all trades during backtest then post-hoc filter the trade log to keep only those whose entry timestamp falls in the allowed window. Path A is the causally honest version. Path B systematically OVERESTIMATES the restricted-window edge whenever the strategy has flat-state interactions (entry_when_flat_only, position-overlap rules, capital recycling).

Evidence:
RSIAVG carries entry_when_flat_only -- a held position blocks the next entry until close. In Path A, blocking a "good" trade during a forbidden window also blocks the strategy from being flat-and-ready when the next allowed window opens, so the next allowed trade may itself be missed or land at a different price. In Path B, the held position from the forbidden window is "free" -- it consumed its blocking effect in the live backtest but then gets stripped from the metric. Result: Path B's filtered subset benefits from setup-conditions (price levels, indicator state) that the live strategy with the same filter applied at entry would never have reached.

Conclusion:
Post-hoc trade-list filtering is not a substitute for causal entry-side filtering when any state variable couples consecutive trades. The bias is one-directional and can be substantial -- easily large enough to flip a real edge from negative to positive on paper.

Implication:
Workflow rule: any "is the edge concentrated in window X?" question must be answered with a Path A backtest (entry-side filter), never with Path B (post-hoc trade-list slicing). Path B is exploratory only and must never support promotion, deployment, or capital-allocation decisions; any number it produces is a ceiling, not a point estimate. When promoting filtered-subset findings, require the Path A re-run to match within tolerance before claiming the filter restores the edge. Build a causal-wrapper helper that takes a full-backtest run + a window predicate, re-runs the engine with FilterStack restricted to that window, and compares Path B "implied" metrics to Path A "actual" metrics to surface the bias automatically.

2026-05-03
Tags:
namespace-integrity
duplicate-execution-logic
port-macdx-aliased
not-independent-alpha
naming-discipline

Strategy: PORT family vs MACDX family (cross-namespace audit)
Run IDs: code-audit finding (no run lineage); evidence in outputs/NEWS_INFRA_CLEANUP_2026_05_03.md cross-reference table

Finding:
PORT and MACDX strategies share identical execution logic at check_entry / check_exit / capital sizing. The token_dictionary.yaml lists them as separate model tokens, the sweep_registry tracks them as parallel idea families, and the portfolio ledger has been counting their PnL as if they were independent alpha streams. They are not -- they are aliases of the same underlying strategy with cosmetic differences in indicator naming and parameter labels.

Evidence:
Source-level diff of strategy.py files in deployable/ subtrees for PORT vs MACDX: identical signal logic (MACD-cross plus volume confirmation), identical position-sizing math, identical exit rules. The split appears to be a historical accident -- one was renamed mid-development without retiring the prior token. No commit explicitly adds independent logic to one branch.

Conclusion:
Treating PORT and MACDX as independent in portfolio composition double-counts the same edge. Originally suspected to be a CRITICAL governance violation; on closer read it is intentional code reuse plus namespace mislabeling, so severity downgraded from CRITICAL to LOW. Still must be fixed at the namespace + portfolio level -- leaving the alias active risks future capital allocation across what looks like two strategies but is one.

Implication:
Pick one canonical token (recommend MACDX, the more descriptive of the two) and retire the other in token_dictionary.yaml aliases. Re-tag PORT-family directives in the sweep_registry to MACDX. Run a one-time portfolio_evaluator pass that collapses the two families in the ledger so capital allocation does not double-count. Add a namespace-integrity check that rejects new model tokens whose canonical signal hash matches an existing token (silent-alias detector -- same kind of structural test used by classifier_gate Rule 3 silent-hash-drift). Operator rule: no new model token may enter token_dictionary without passing signal-hash uniqueness validation.
