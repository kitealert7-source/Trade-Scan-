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
