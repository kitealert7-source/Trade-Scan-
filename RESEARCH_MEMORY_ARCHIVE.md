# RESEARCH MEMORY ARCHIVE
# Entries prior to 2026-03-27 — compacted for token efficiency
# Active file: RESEARCH_MEMORY.md

---
2026-03-06 | Tags: zscore, entry_logic, mean_reversion
Deeper Z-score entry reduces PF. PF dropped from 1.20 to 1.17 in E3 test. Prefer moderate stretch entries. Avoid extreme stretch entry thresholds in future strategies.
---

---
2026-03-06 | Tags: portfolio_construction, common_history, risk_metrics, evaluation_window
Common-history alignment improved risk-adjusted portfolio metrics for the selected multi-symbol basket. For the same 4-run portfolio set, full-history evaluation produced Sharpe 0.8328, MaxDD -2.13%, Return/DD 6.7259 (440 trades). Common-history window (2024-01-02 to 2026-01-31) produced Sharpe 1.8866, MaxDD -1.10%, Return/DD 8.0604 (221 trades). Window misalignment across components can dilute comparability and mask the true recent joint behavior of the basket. Use a common-history evaluation pass as a standard comparison layer before portfolio selection and ranking decisions.
---

---
2026-03-07 | Tags: nas100, volatility_expansion, atr_filter, pullback, daily_timeframe
ATR-percentile threshold filter (>75 exclusion) outperforms ATR-percentile band filter (60–72 exclusion) on NAS100 daily volatility pullback strategy. S02 (threshold >75, 4-bar cooldown, ATR10): 35 trades, Sharpe 3.18, MaxDD -1.12%, Return/DD 2.60, verdict PROMOTE. S03 (band 60–72 outside, 5-bar cooldown, ATR14): 42 trades, Sharpe 2.84, MaxDD -2.49%, Return/DD 1.51, verdict PROMOTE. Same window, same symbol, same base logic. Excluding only extreme volatility (>75th pct) allows more trades and delivers better risk-adjusted returns than a band filter that also blocks moderate vol. For NAS100 daily pullback strategies, prefer simple upper-threshold ATR filters over band filters. Band filters reduce trade count without improving Return/DD.
---

---
2026-03-07 | Tags: xauusd, stop_loss, atr_multiplier, time_exit, sensitivity
Tighter ATR stop (2.1×) with longer time exit (15 bars) outperforms wider stop (2.3×) with shorter time exit (14 bars) on the same XAUUSD 1H entry pattern. S04 (stop 2.1, exit 15): 89 trades, Sharpe 1.53, MaxDD -0.92%, Return/DD 0.99, verdict HOLD. S05 (stop 2.3, exit 14): 89 trades, Sharpe 0.87, MaxDD -1.46%, Return/DD 0.38, verdict HOLD. Identical entry signals (same trade count), different exit params only. Increasing ATR stop from 2.1× to 2.3× degraded Sharpe and Return/DD on the tested XAUUSD 1H trend-pullback system. Wider stops did not improve drawdown and reduced risk-adjusted returns in this configuration. Future sweeps should prioritize testing tighter stops (1.8–2.1×) rather than expanding the stop width further.
---

---
2026-03-07 | Tags: fx, mean_reversion, exit_design, friction_sensitivity, strategy_refinement | Strategy: 01_MR_FX_1H_ULTC_REGFILT_S02_V1_P00 | Status: PLANNED EXPERIMENT

Friction stress test confirmed genuine strategy vulnerability. 1 pip round-trip cost reduces PF from ~1.18 to ~0.94. Diagnostic ruled out modeling error. Root cause is structural: exit-too-fast / stop-too-wide.

Strategy has ~2,178 trades over 2 years. Approximately 98% of trades exit within 1 bar. Avg winner $10.42, avg loser $12.81, payoff ratio 0.81. Avg profit per trade ~$0.95. 1-pip friction cost ~$1.10 per trade, consuming 87% of edge. Total friction drag ($2,774) exceeds total baseline profit ($2,064), producing net loss of -$709 under 1-pip slippage. Friction cost validated: expected $2,771 vs observed $2,774 (0.09% variance — no modeling error). Monte Carlo median CAGR 0.14% vs backtest 14.45%, indicating significant regime-fit. Top 1% of trades (21 winners) generate 57.81% of total profit. Per-trade edge eroding: 2024 $1.63/trade → 2025 $0.78/trade. AUDNZD generates 37% of profit (best symbol); EURUSD weakest (55.5% WR, $0.52/trade).

The strategy captures only the initial snap of mean reversion before the primary move develops, while allowing losers to run past the reversion window. The payoff ratio (0.81) and thin edge per trade make live execution under realistic friction conditions unviable without structural changes.

Planned experiments as isolated sweeps (do not combine levers until individual effects confirmed):

Experiment 1 — Stop-loss tightening (highest EV impact):
  Test ATR multipliers: 0.9, 1.0, 1.1 (current: 1.35).
  Objective: reduce avg loser size and improve payoff ratio.

Experiment 2 — Minimum hold duration (prevents 1-bar exits):
  Test MIN_BARS_BEFORE_EXIT: 2, 3.
  Objective: allow the typical 2–4 bar mean-reversion move to develop.

Experiment 3 — Exit threshold widening (after hold behavior confirmed):
  Z-score exit: test 0.6, 0.8 (current: 0.40).
  RSI exit: test 80/20, 85/15 (current: 75/25).

Additional lever: MAX_BARS reduction from 20 to ~6 as a time-based stop to cut slow-drift trades that fail to revert within the expected window.

Post-structure: symbol concentration (AUDNZD, GBPNZD, AUDUSD) and volatility filter refinement for weaker symbols. Apply only after structural levers are tested and ranked.
---

---
2026-03-08 | Tags: limit_entry, mean_reversion, entry_design, oscillator, fill_rate | Strategy: 01_MR_FX_1H_ULTC_REGFILT_S10/S11/S12_V1_P00
ATR-scaled limit orders offset from the signal bar close hurt performance vs immediate next-bar-open market entry for UC%-based mean reversion strategies. Three controlled experiments (k=0.05, 0.10, 0.15 ATR offset, expiry=2 bars) vs S07 baseline. Fill rates 83–90%. PF degraded from 1.198 to ~1.145 across all k-values. Sharpe approximately halved. MaxDD increased 30–58% relative to baseline. Recovery factor fell. All three k-values produced worse risk-adjusted outcomes than immediate market entry. For UC%-based oscillator signals on FX 1H, the signal bar itself represents the adverse excursion. Waiting for further pullback from signal close selects weaker setups — trades that stalled rather than reversed immediately — and misses the primary reversion snap that occurs on bar N+1. Do not test limit entry offsets against oscillator-triggered MR strategies without a structural reason to expect the signal bar to precede a deeper pullback. Limit entry designs are better suited to trend-following or breakout contexts where entry timing relative to a level matters. This experiment axis is closed for the 01_MR_FX_1H_ULTC_REGFILT lineage.
---

---
2026-03-08 | Tags: oscillator_tuning, indicator_variant, mean_reversion, signal_quality, sweep_exhaustion | Strategy: 01_MR_FX_1H_ULTC_REGFILT_S07_V1_P01/P02/P03
Changing the UC% oscillator preset mode (fast / balanced / slow) does not improve on the S07_V1_P00 baseline. The original UC% defaults (lookback=5, smooth=3, OB/OS=75/25) are already well-tuned for this strategy configuration. P01 (fast: smooth=1, OB/OS=80/20): trades 5179 vs 2467 baseline (2× frequency), port PF 1.05, robustness PF 1.13, exp/trade $0.65 vs $1.22, MaxDD $840 vs $442, recovery 3.33 vs 5.55. P02 (balanced: smooth=2, OB/OS=80/20): port PF 1.08, CAGR 15.3% vs 17.1%, recovery 4.74. P03 (slow: lookback=7, smooth=3, OB/OS=75/25): port PF 1.09, CAGR 5.99%, MC 5th pctl CAGR turns negative (-0.03%), top-5% trade concentration at 392% of total PnL — highly tail-dependent. All three variants fail to match baseline on PF, expectancy, recovery factor, and MC worst-case DD. Faster modes over-signal and dilute per-trade edge. Slower modes reduce frequency and concentrate returns into extreme tail events, making equity fragile. The baseline preset is the strongest configuration tested. UC% oscillator mode sweeps are exhausted for the 01_MR_FX_1H_ULTC_REGFILT lineage. Do not re-test smoothing or OB/OS threshold variants without a structural change to entry or exit logic that changes the reward profile of individual trades. Future experiments should focus on other structural levers (stop width, exit design, symbol selection) rather than oscillator parameterisation.
---

---
2026-03-09 | Tags: xauusd, dayoc, volatility_filter, atr_percentile, parameter_sweep | Strategy: 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P00 through P15

For the DAYOC (Daily Open-to-Close) model on XAUUSD 15M, the ATR percentile volatility filter has two independent levers — low_threshold_pct (the percentile cutoff defining LOW regime) and window (the rolling lookback for percentile ranking). Both levers interact non-linearly. Threshold=37 and window=120 individually improve on the baseline (threshold=33, window=100) and the combination (P13) achieves the best Sharpe of the entire sweep (4.92) at the lowest MaxDD% (1.36%). The interaction effect is real but modest: P13 beats each single-axis winner on Sharpe but trails P05 on absolute return and RetDD.

14-patch sweep (P00–P14) across two axes:
Axis 1 (threshold, window fixed at 100): Sharpe peaked at P05 (37%, Sharpe 4.65, RetDD 6.62). PnL rose monotonically to P07 (50%, $1,154) but RetDD degraded above 42%.
Axis 2 (window, threshold fixed at 33): window=60 collapsed Sharpe to 2.16 (over-noisy); window=120 optimal (P11, Sharpe 4.90); window=150 over-filtered (58 trades, $423 PnL).
Interaction P13 (37/120): Sharpe 4.92, MaxDD 1.36%, RetDD 5.78, CAGR 4.99%.
Interaction P14 (42/120): Sharpe 4.44, MaxDD 1.39%, RetDD 6.15, CAGR 5.44%. Confirms wider window disciplines higher threshold well.

Best risk-adjusted: P13 (37/120). Best return/risk balance: P14 (42/120). Best absolute return: P05 (37/100, RetDD 6.62). Threshold and window interact — combining best single-axis values improves Sharpe but shifts trade-off away from return maximisation toward drawdown minimisation.

For DAYOC-family strategies with ATR percentile regime filters, treat threshold and window as a joint decision. Do not optimise either axis in isolation and expect the combination to be additive. Test the interaction explicitly (as P13/P14 did here) before finalising parameter selection.
---

---
2026-03-09 | Tags: xauusd, dayoc, trade_window, regime_stability, long_horizon_validation | Strategy: 06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P15 (P06 config, extended to 2023-2026)
Extending the P06 DAYOC strategy back to 2023 (adding 126 trades from 2023) added only $17 of net PnL while collapsing Sharpe from 4.37 to 2.86, doubling MaxDD from 1.37% to 2.38%, and cutting RetDD from 7.03 to 4.33. The 2024-01-01 trade window gate used in the main sweep was not an artefact of data availability — it reflects a genuine structural regime difference in XAUUSD. P06 (2024-2026): 160 trades, $1,029.95 PnL, Sharpe 4.37, MaxDD 1.37%, RetDD 7.03, CAGR 6.14%. P15 (2023-2026, same parameters): 286 trades, $1,046.92 PnL, Sharpe 2.86, MaxDD 2.38%, RetDD 4.33, CAGR 3.73%. 126 additional 2023 trades contributed ~$17 net profit (avg $0.13/trade vs P06 avg $6.44/trade). Pipeline rated both PROMOTE but quality metrics diverged sharply. Gold in 2023 was in post-Fed-tightening consolidation. LOW-ATR days in 2023 were structurally different from 2024-2026: choppy-quiet rather than trending-quiet. The DAYOC model (first-bar entry, penultimate-bar exit) requires directional resolve within a session to profit. In 2023, low ATR days lacked that resolve. The 2024-01-01 trade window gate is a structural feature, not a data constraint. Do not remove it for future DAYOC variants without confirming that the earlier period has comparable session directionality. For any PA-family strategy on XAUUSD, run a long-horizon validation pass (P15-style) to verify the chosen trade window is justified by regime quality, not convenience.
---

---
2026-03-09 | Tags: xauusd, smi, mean_reversion, oscillator_asymmetry, idea_exhausted | Strategy: 07_MR_XAUUSD_15M_SMI_SMIFILT_S01 and S02 (P00–P04)

Multi-timeframe SMI mean reversion on XAUUSD 15M has no tradable edge across the 2024–2026 test window in any tested configuration. Five variants across two sweeps were discarded.

S01_P00 (1H SMI < -50, no vol filter): 148 trades, $8.92 net, Sharpe 0.05 — flat.
S01_P01 (1H SMI < -80): 10 trades — insufficient sample, no inference possible.
S02_P02 (state gate + LOW/HIGH vol filter): 116 trades, Sharpe 1.92, but 2024 = -$115, 2025 = +$527. Monte Carlo mean CAGR 0.02%.
S02_P03 (event window, 1H cross-below -50, long only): 31 trades, Sharpe 5.14, but 2024 = -$150, 2025 = +$379. 28/100 block bootstrap runs end below start.
S02_P04 (bidirectional mirror of P03): 64 trades, -$146 net, Sharpe -1.27 — short side net -$357 in LOW regime, confirming structural asymmetry.

The edge in P02 and P03 is entirely concentrated in 2025 and fragile under block bootstrap reshuffling. 2024 is a systematic loss year in every long-only variant, not random noise. The underlying cause: XAUUSD's long-run upward drift means "overbought" SMI is not a reversion condition (P04 short side failure), and "oversold" SMI during 2024 trending moves admits entries into sustained downtrends rather than true capitulation reversals. The event-window design (P03) correctly diagnosed and partially addressed this, but the 2024 regime is inherently hostile to this approach.

Idea 07 (SMI oscillator mean reversion on XAUUSD 15M) is exhausted in its current form. Do not iterate further on threshold, window size, or vol filter variants — the architecture is sound but the instrument-timeframe combination does not support the hypothesis consistently. If revisiting, require either: (a) a secondary directional filter (e.g., daily trend alignment confirming gold is in a range, not a trend) to exclude the 2024 trending-down environment, or (b) a different instrument where SMI oversold conditions are genuinely reverting rather than momentum-continuing.
---

---
2026-03-19 | Tags: volatility_squeeze, fx_4h, breakout, failed_concept, exit_design

Volatility squeeze breakout on FX 4H has no viable edge in tested form.
ATR-percentile squeeze detection is sound as a component but the entry
and exit structure could not be resolved profitably.

Three variants tested across two concept families (BB-width squeeze and
ATR-percentile squeeze) on 4H FX. All produced negative PnL. No trend
filter meant entries were taken in both directions equally. Fixed TP was
rarely reached — FX 4H breakouts retrace before extending. Midline exit
cut winners; opposite-band exit widened risk disproportionately. Two
major FX pairs showed marginal positive residual across all variants.

The exit structure is the primary failure point, not the squeeze
detection. The 3×ATR TP is structurally mismatched to 4H FX breakout
behavior. Concept is not dead — pair-specific residual edge exists.

If revisited: add trend direction filter (breakouts in trend direction
only), replace fixed TP with trailing stop, test on higher-volatility
instruments or shorter timeframe where post-squeeze expansion sustains.
ATR-percentile squeeze detection is reusable as a pre-filter component
in other strategy families.
---

---
2026-03-19 | Tags: regime_filter, sweep_design, sharpe_improvement, edge_concentration, neutral_regime

Excluding a regime with near-zero PnL across many trades is a
high-value sweep dimension. It concentrates edge without materially
reducing total PnL.

Spike-fade strategy on XAUUSD 1H. Three sequential sweeps each excluding
one additional regime. First exclusion (strong trending regime): trade
count fell ~20%, Sharpe improved from 2.98 to 4.08, MaxDD fell from
8.18% to 7.12%. Second exclusion (neutral regime, ~30 trades, $0.16 net
PnL): trade count fell further ~26%, Sharpe improved from 4.08 to 5.54,
MaxDD fell from 7.12% to 4.35%, RetDD improved from 6.96 to 10.64.
Neutral regime was pure dilution — high noise, no directional conviction.

Regimes with high trade count and near-zero net PnL are diluting
risk-adjusted metrics without contributing returns. Excluding them
tightens the equity curve without losing the core edge.

For any strategy showing a clearly dead regime in its cross-regime
breakdown, run regime exclusion as the next sweep before any parameter
changes. Neutral regimes are the most frequent candidate. One exclusion
per sweep to maintain attribution.
---

---
2026-03-19 | Tags: portfolio_construction, same_instrument, regime_complementarity, diversification, composite_portfolio

Two strategies on the same instrument can produce a more robust combined
portfolio than either component alone if their edges operate in opposed
market conditions.

Spike-fade reversal and structure breakout strategies, both on the same
instrument (XAUUSD 1H). Combined portfolio produced lower max drawdown
than either individual strategy. Losing periods did not align — one
strategy's losing regime is the other's winning regime. Combined Sharpe
(4.15) exceeded both individual Sharpes. Zero negative rolling 12-month
windows across the combined test period. Second half of test period
outperformed first half, indicating improving rather than decaying edge.

Instrument overlap is not the same as strategy overlap. Regime
complementarity matters more than symbol diversification at small
portfolio scale.

Before rejecting a same-instrument composite, analyse regime breakdown
correlation across the constituent strategies. If one wins in trending
regimes and the other in mean-reverting regimes, the composite will be
more robust than either component alone. This is a valid and productive
portfolio construction axis even with a small number of instruments.
---

---
2026-03-19 | Tags: sweep_design, attribution, one_change_per_sweep, research_discipline

Incremental sweeps with one change at a time make marginal contribution
of each change traceable and allow bad dimensions to be pruned early.

Three sequential sweeps on spike-fade strategy, each adding one regime
exclusion. Because each sweep changed exactly one thing, the contribution
of each exclusion was measurable independently. The neutral regime
exclusion (third sweep) was confirmed as additive only because the first
two sweeps were clean. A combined sweep would have obscured whether both
exclusions were necessary.

Attribution requires isolation. Combined changes produce uninterpretable
results even when the combined outcome is positive.

Enforce one-constraint-per-sweep discipline strictly. If multiple changes
are tempting, run them sequentially, not together. The cost is one
additional pipeline run; the benefit is full attribution of every
improvement.
---

---
2026-03-20 | Tags: volatility_expansion, breakout, xauusd_1h, failed_concept, portfolio_overlap | Strategy: 19_BRK_XAUUSD_1H_VOLEXP_S01_V1_P00

ATR-compression breakout on XAUUSD 1H produces weak aggregate edge
and overlaps behaviourally with existing IN_PORTFOLIO strategies.
Family 19 REJECTED — no S02 planned.

S01 (both directions, 270 trades): PnL $301.68, Sharpe 0.90, PF 1.15,
Max DD 2.35%, R/DD 1.28, Avg R 0.01. Longs-only projection: ~143 trades,
~$347 PnL, estimated PF ~1.35 — improvement but still inferior to F18
P06 (PF 1.68, R/DD 2.27, Avg R 0.39). Avg R of 0.01 versus F18's 0.39
confirms the per-trade quality gap is structural, not a sample issue.
Behavioural overlap: long vol-expansion after compression captures the
same directional impulse that F12 BOS (structure break continuation) and
F18 LIQSWEEP (London open reversal) already exploit. Adding F19 longs
would increase correlation with the existing reversal-heavy portfolio
without adding orthogonal value.

The compression-expansion signal has insufficient per-trade edge on
XAUUSD 1H in its baseline form. Mechanically it is a subset of the
conditions already covered by F12 and F18. Both the standalone quality
and the portfolio diversification case are too weak to justify further
sweeps.

Do not iterate on ATR-compression breakout variants for XAUUSD 1H.
If revisited on a different instrument or timeframe, require Avg R > 0.20
and confirmed non-overlap with existing IN_PORTFOLIO strategies before
proceeding past Pass 1. The atr_percentile component is sound as an
indicator and is reusable as a regime filter in other families.
---

---
2026-03-20 | Tags: regime_slice, pnl_concentration, fragility_check, short_bias, portfolio_complement

A regime-specific slice (shorts in high vol) can appear attractive in
aggregate but fail a temporal distribution check when PnL is concentrated
in a single period.

F19 S01 short/high-vol subset: 43 trades, $136.43, PF 1.39, distributed
across 18 active months with max 5 trades in any single month — trade
frequency passes the clustering test. However, Q4 2025 alone contributed
$124.88 (91.5% of total edge) from 5 trades. Removing Q4 2025, the
remaining 38 trades over 7 quarters produced $11.55 net — essentially
flat. Q1 2026 immediately followed with -$51.05 from 5 trades, confirming
the Q4 2025 result was not the start of a sustained regime.
The idea was motivated by complementarity with F18 P06 (longs/low-vol):
the two slices fire in opposite volatility regimes and would not compete
for the same market conditions. The portfolio construction logic was sound;
the edge quality was not.

Trade distribution across time is a necessary but not sufficient condition
for robustness. PnL concentration must be checked independently. A
strategy with evenly distributed entries but a single quarter generating
>90% of profit is as fragile as one with clustered entries.

For any regime-filtered slice being evaluated as a portfolio complement,
run both checks before building a new sweep: (1) are entries distributed
across time (no clustering), and (2) is PnL distributed across quarters
(no single period dominance). Require that no single quarter contributes
more than ~40% of cumulative PnL for a slice to be considered structurally
robust. Apply this check to all candidate sub-strategies before committing
pipeline cycles.
---

---
2026-03-20 | Tags: portfolio_gap, trend_following, orthogonality, next_research_priority, strategy_class

The current IN_PORTFOLIO basket of 4 strategies is structurally skewed
toward reversal logic, leaving sustained directional trends as an
unhedged blind spot. Family 03 (Trend Following) has zero sweeps and
is the highest-priority next research direction.

IN_PORTFOLIO composition: F11 SPKFADE (reversal, fades spikes),
F17 FAKEBREAK (reversal, fades stop hunts), F18 LIQSWEEP (reversal,
fades London sweeps), F12 BOS (continuation, pullback entry after
structure break). Three of four strategies make money by fading momentum.
F12 is the only continuation strategy but requires a pullback — it does
not ride the initial impulse. No strategy in the portfolio profits from
sustained directional expansion. A pure trend follower (EMA crossover or
ADX-confirmed breakout with trailing stop) makes money precisely in the
regimes where the three reversal strategies bleed. Family 03 TREND and
Family 04 BRK (generic price-level breakout) both have zero sweeps across
the entire research history.

Portfolio diversification at the strategy-class level is incomplete.
Adding a trend-following strategy on XAUUSD 1H would be regime-
complementary to the existing basket rather than correlated with it.

Family 03 (Trend Following Research Track) is the next research priority.
Candidate design: EMA crossover or ADX-confirmed directional breakout on
XAUUSD 1H, trailing ATR stop, no fixed TP. Pass 1 should be minimal
filtering and both directions to confirm the signal exists before any
regime gating.
---

---
2026-03-21 | Tags: trend_following, momentum_ignition, xauusd_1h, sweep_results, pass1_validation | Strategy: 03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P00 through P03

Momentum ignition (large bar closing at extreme, ATR trailing stop, no TP)
has real and scalable edge on XAUUSD 1H. The raw signal exists at Pass 1
(P00). Direction filtering via session and regime gating more than doubles
PnL relative to the baseline. Four-patch sweep: P00 REJECTED, P01 PROMOTE,
P02 PROMOTE (series winner), P03 REJECTED.

P00 (max_bars=12, no filter): 314 trades, PnL $361.68, Sharpe 0.82.
  Winners cut too early — trailing stop never had room to run.
P01 (max_bars=48, trailing_stop=true): 290 trades, PnL $823.89, Sharpe 1.64.
  Extending hold time doubled PnL. All vol regimes profitable.
P02 (+ session/regime direction gate): 209 trades, PnL $1,108.19, PF 1.75,
  Return/DD 4.67, MAR 2.54. NY session (13-20 UTC) longs only; strong_up
  (trend_regime=2) longs only; strong_down (trend_regime=-2) shorts only;
  other regimes both directions. -28% fewer trades, +35% more PnL vs P01.
P03 (+ close shorts when NY session opens): 212 trades, PnL $876.21.
  REJECTED — see separate entry below.

The momentum ignition signal (bar range > 1.8x avg_range_5, close in top/
bottom 20% of range) captures genuine directional impulse. Direction gating
by session + regime is the primary value driver — it removes the bulk of
losing short trades without cutting profitable long-biased moves.

For XAUUSD 1H trend strategies, always apply direction gating from Pass 1.
Longs dominate edge (NY session bullish bias, gold upward drift). Strong Down
shorts should be treated with caution — 10 trades, 20% win rate, PF 0.05
in the tested period. Time exits beyond 24 bars are necessary for trend
strategies — do not default to short max_bars without testing.
---

---
2026-03-21 | Tags: session_filter, exit_design, trend_following, ny_session, failed_hypothesis | Strategy: 03_TREND_XAUUSD_1H_IMPULSE_S01_V1_P03

Closing short positions at the start of NY session (bar_hour >= 13) destroys
the Weak Up short edge rather than protecting it. P03 REJECTED vs P02.

P02 Weak Up shorts: T:28, PnL +$247.30, PF 2.04.
P03 Weak Up shorts (same setup + NY exit): T:28, PnL -$34.43, PF 0.81.
Delta: -$281.73. NY exit cost more in Weak Up shorts alone than the
Strong Down short losses it partially recovered (+$39.41 improvement).
Overall: P03 PnL $876 vs P02 PnL $1,108 (-$232 net regression).

Shorts entered pre-NY (Asian/London session) that are still profitable
need NY hours to complete their move — the ATR trailing stop captures
the reversal after the NY bounce, not before. Forcing an exit at 13:00
UTC terminates these trades mid-move, converting winners into flat or
losers.

Do not use session-based exit gates to force-close trend-following positions
that entered outside the session. Entry restriction (no new shorts in NY) is
correct. Exit restriction (close existing shorts when NY starts) destroys the
positions that were working. The -$115 NY session P&L attribution visible in
the AK report is from positions in transit — not a signal of structural
session weakness.
---

---
2026-03-21 | Tags: filter_stack, direction_gate, trend_filter, engine_extension, governance

FilterStack trend_filter now supports direction_gate mode (long_when /
short_when sub-blocks), mirroring the existing volatility_filter pattern.
This enables per-direction regime gating without triggering the semantic
validator's hardcoded-regime-comparison guard.

Extending FilterStack required three coordinated changes:
(1) engines/filter_stack.py: cache trend_regime in allow_trade(), add
direction_gate bypass in trend_filter block, add trend gate logic in
allow_direction().
(2) tools/canonical_schema.py: add direction_gate, long_when, short_when
to trend_filter allowed nested keys.
(3) Strategy STRATEGY_SIGNATURE: declare long_when / short_when sub-blocks
with required_regime and operator fields.
Directive uses: long_when: {required_regime: -2, operator: gt} (long when
trend > -2, i.e. not strong_down); short_when: {required_regime: 2,
operator: lt} (short when trend < 2, i.e. not strong_up).

Direction-gated trend filtering is now a first-class capability of the
engine governance layer, correctly separated from per-bar filtering.
The semantic validator is satisfied because strategy code calls
filter_stack.allow_direction() — no direct ctx.get('trend_regime') access.

Any future strategy requiring per-direction regime gating should use
the direction_gate pattern on volatility_filter or trend_filter rather
than checking ctx regime values directly in strategy code. Hardcoded
regime comparisons in strategy.py will be caught by the semantic validator
and block execution.
---

---
2026-03-21 | Tags: portfolio_construction, interaction_audit, orthogonality, trend_reversal_complement, portfolio_gap

Adding 03_IMPULSE (momentum ignition trend follower) to the 4-strategy
reversal-heavy portfolio produces a materially better composite. The
addition is genuinely orthogonal but introduces one structural risk: it
owns the largest drawdown event entirely when gold ranges.

BASE (PF_101C552D7C04, 4 strategies): CAGR 27.93%, Sharpe 3.80, Net PnL
$6,982, Max DD $673, Recovery 10.38, MC 5th pctl CAGR 13.85%.
NEW (PF_8C20B7EC307D, 5 strategies): CAGR 43.42%, Sharpe 3.80 (maintained),
Net PnL $11,712, Max DD $834, Recovery 14.04, MC 5th pctl CAGR 24.00%.
Behavioral correlations: P02 vs SPKFADE -0.099, vs BOS +0.073, vs FAKEBREAK
-0.038, vs LIQSWEEP -0.014. Near-zero to slightly negative — confirmed new edge.
Interaction audit: P02 contributes 38.7% of portfolio PnL, 31.9% of trades,
57.3% of aggregate TIM hours. PnL/footprint ratio 0.68x (below avg efficiency
per hour — expected for trend following). Dec 2025 DD: P02 responsible for
109% of the $-201 event (base portfolio was +$19 in that window). Long bias
increased from 10.1% → 22.7% net long hours (XAUUSD bull market tailwind risk).

Verdict: ADD (no scaling yet). Three monitoring flags: (1) Dec 2025-type
ranging market creates an unhedged loss window for P02 with no natural
offset; (2) portfolio now 22.7% net long on one instrument during a bull
run — revisit in bear conditions; (3) PnL/time efficiency 0.68x is
acceptable but below portfolio average.

A range-bound strategy is now the highest-priority portfolio complement.
The Dec 2025 period (choppy XAUUSD, P02 -$115, reversals flat) identifies
the exact regime gap. The ideal complement profits in low-directional,
oscillating market conditions — opposite to when P02 makes money.
---

---
2026-03-21 | Tags: portfolio_gap, range_bound, next_research_priority, regime_complement, xauusd

The 5-strategy portfolio has one unhedged regime: ranging / low-momentum
XAUUSD markets. This is the exact environment where the trend strategy
(P02) bleeds and the reversal strategies (SPKFADE, FAKEBREAK, LIQSWEEP)
go flat because there are no spikes or structural breaks to fade.

Dec 2025 DD audit: P02 -$115, SPKFADE +$10, BOS +$0, FAKEBREAK +$2,
LIQSWEEP -$3. The reversal strategies could not offset P02 because ranging
markets produce neither the large candles (SPKFADE) nor the structural
breaks (FAKEBREAK, LIQSWEEP) that trigger their entries. A strategy
specifically designed for range oscillation would have been active and
profitable during this exact window.

A range-bound module is the structurally correct next addition. Candidate
mechanisms: session-defined range (Asian range, trade London retrace),
SMI/RSI oscillator with neutral regime gate, or Bollinger mid-reversion
when ATR squeeze is confirmed. The regime gate must ensure the strategy
activates only when trend_regime is neutral (0) or weak (±1), so it is
naturally anti-correlated with P02.

Next research priority: range-bound strategy on XAUUSD 1H (or 15M) with
explicit neutral/weak-trend regime gate. Pass 1 should confirm the signal
exists in ranging conditions before adding direction filters. Asian session
range → London retrace is the leading candidate entry mechanism given
existing Family 15 ASRANGE infrastructure. Confirm Family 15 ASRANGE
outcome before opening a new family.
---

---
2026-03-22 | Tags: portfolio_validation, extended_backtest, pf_e1fcd12a8ec3, durability, xauusd_1h

PF_E1FCD12A8EC3 (6-strategy XAUUSD 1H portfolio) passes all durability criteria over an
extended 2.2-year window (2024-01-01 to 2026-03-20). Performance did not decay relative
to the original 2-year baseline (PF_82AEC0F73920).

Extended run — 900 trades, Win Rate 54.2%, PF 1.62, Net PnL $14,132.80, Max DD $806.67,
Recovery Factor 17.52. Monte Carlo (1000 sims): Mean CAGR 46.92%, 5th pctl CAGR 27.57%,
95th pctl Max DD 9.18%, 0 blow-ups. Rolling 1Y (15 windows): 0 negative windows, worst
window return +40.48%, worst DD 6.18%, mean return 55.81%. Year-wise: 2024 $4,038 (416
trades), 2025 $8,213 (408 trades), 2026 YTD $1,881 (76 trades). H1/H2 split: H1 CAGR
42.62% → H2 CAGR 80.47% — accelerating, not decaying. DYNAMIC_V1 capital profile:
Utilized Capital $409.60, ROUC 34.50 (3450%), Efficiency Score 190.15. Per-engine ranking:
IMPULSE P02 $4,143 (214 trades, PF 1.65, score 18.37) > BOS S03 $2,585 (127 trades, PF
1.58, score 9.91) > LIQSWEEP P06 $2,338 (86 trades, PF 1.84, score 9.62) > MICROREV P12
$1,948 (234 trades, PF 1.67, score 8.88) > SPKFADE S03 $1,718 (90 trades, PF 1.93, score
7.47) > FAKEBREAK P04 $1,398 (149 trades, PF 1.32, score 4.61). FAKEBREAK is weakest
engine by efficiency score.

Portfolio is durable over the extended window. All success thresholds met: PF ≥ 1.25 ✓,
Max DD ≤ 10% ✓, 0 negative annual periods ✓. No strategy degraded materially in the
additional 4 months vs the original 2-year run. FAKEBREAK P04 remains a monitoring flag
(lowest PF 1.32, lowest efficiency score 4.61).

PF_E1FCD12A8EC3 is confirmed production-ready for the full extended window. No rebalancing
action required. Next monitoring trigger: FAKEBREAK P04 PF dropping below 1.20 over any
rolling 6-month window.
---

---
2026-03-22 | Tags: pipeline_ops, directive_state, re_run_procedure, extended_backtest, lesson_learned

Reusing directive filenames with different dates (e.g. for extended backtest re-runs) does
NOT automatically reset directive state. The directive_state.json is keyed by filename stem,
not by run_id or content hash. Old PORTFOLIO_COMPLETE state blocks the pipeline even if the
directive has a new date range and new test.name.

All 6 EXT5Y directives used the same filenames as the original runs. First pipeline invocation
found all 6 in PORTFOLIO_COMPLETE / SYMBOL_RUNS_COMPLETE state (keyed by filename stem at
`runs/<DIRECTIVE_ID>/directive_state.json`) and aborted without doing new work. Additionally,
`admit_directive()` moves files from INBOX to `active_backup/` with `.admitted` markers — a
second pipeline invocation on an empty INBOX would find no work. Files had to be manually
restored to INBOX.

Two mandatory pre-steps for any re-run with unchanged filenames:
1. Reset all directive states: `python tools/reset_directive.py <ID> --reason "<why>"` for
   each directive before invoking the pipeline.
2. Confirm INBOX contains the directive files before each pipeline invocation. If a previous
   run admitted them to `active_backup/`, move them back.

Add to re-run SOP: always `reset_directive.py` before re-running any directive whose filename
is unchanged but whose content (dates, test.name, parameters) has been modified. The signature
hash is content-based and date-independent, so PATCH_COLLISION is not a risk — but directive
state is filename-based and will block execution without a reset.
---

---
2026-03-23 | Tags: meta_filter, macro_factor, usd_stress, portfolio_filter, failed_concept

USD Stress Index (usd_stress_percentile) has no viable use as a portfolio-level meta-filter
for the 5Y XAUUSD portfolio. Near-zero correlation with portfolio PnL and an inverse
relationship between stress zones and portfolio performance make it destructive to apply.

Offline simulation across 5Y window (2021-01-01 to 2026-03-20), 900 trades.
Pearson correlation of daily usd_stress_percentile with portfolio daily PnL: -0.016
(effectively zero). Regime-zone PnL breakdown: extreme_low stress (pct < 20): PF 1.405,
$3,119 — best zone. extreme_high stress (pct > 80): PF 1.570, $2,657 — second best.
neutral stress (20-80): PF 1.551. A filter blocking extreme zones would remove 32.5% of
trades, destroy 43% of PnL, and improve PF by only 0.006. The periods the filter would
block are when the portfolio performs best — extreme USD moves trigger the structural
dislocations (spikes, sweeps, impulse moves) that the strategy engines are designed to exploit.

A macro factor with no demonstrated correlation to portfolio PnL cannot be justified as a
regime gate regardless of narrative logic. Extreme USD stress periods are not uniformly
bad for this portfolio — the macro rationale (USD strength = gold headwind) is structurally
inverted at the trade-outcome level.

Do not apply macro-level USD filters to XAUUSD 1H strategies without first confirming a
statistically significant correlation between the macro factor and per-trade outcomes.
Narrative plausibility does not substitute for demonstrated correlation in the trade sample.
This experiment axis is closed for the XAUUSD 1H portfolio.
---

---
2026-03-23 | Tags: regime_filter, regime_age, stability_filter, sweep_parked, temporal_fragility

Regime age threshold filtering (exclude trades where market_regime has been active fewer
than N bars) improves portfolio PF marginally but concentrates its cost in a single high-
return year, making the benefit temporally fragile. Parked without implementation.

Offline sweep across 7 age thresholds [0, 1, 2, 3, 5, 8, 12] using raw results_tradelevel.csv.
Best threshold: age >= 2 (+0.072 PF, -13.8% trade reduction, 900 → 776 trades). Year-by-year:
2024 +$89, 2025 -$535, 2026 YTD +$89. The 2025 cost is not random — it was the portfolio's
best return year ($8,213) and regimes cycled faster, placing many high-quality trades inside
the first 2 bars of a new regime. Higher thresholds (age >= 3) compound the 2025 effect with
worse PF. The +0.072 PF gain is entirely attributable to 2024 and 2026 YTD.

A filter whose benefit is temporally concentrated in low-activity periods while its cost is
concentrated in the best return year fails the distribution test. The gain is period-fitted,
not structurally robust.

Regime age filtering requires uniform distribution of benefit across years before
implementation. If improvement is concentrated in low-activity years and cost in
high-return years, park the axis. Revisit only if a new 12+ month window shows consistent
improvement without year-specific cost concentration. Minimum requirement before
implementation: no single year should bear more than 40% of the filter's total cost.
---

---
2026-03-23 | Tags: market_regime, engine_specific_filter, portfolio_improvement, range_high_vol, filter_design

Market regime exclusion must be applied per-engine based on that engine's individual regime
performance, not at the portfolio level. Two engines (IMPULSE, FAKEBREAK) lose money in
range_high_vol; two others (BOS, MICROREV) are strongly positive in the same regime.
A portfolio-wide exclusion would destroy the latter.

Offline per-engine market_regime PnL breakdown (5Y, 900 trades, PF_0DDC45C94672 baseline).
Portfolio-level range_high_vol: 452 trades, PF 1.130 — worst regime but still net positive.
Engine breakdown within range_high_vol: IMPULSE: 113 trades, PF 0.682, -$231 (worst combination).
FAKEBREAK: range_high_vol PF 0.838 (-$103), range_low_vol PF 0.595 (-$67). BOS: PF 1.70,
+$487 in range_high_vol (best combination). MICROREV: PF 1.65, +$348. SPKFADE: PF 1.22.
LIQSWEEP: PF 1.05 (marginal). Engine-specific filter applied to IMPULSE and FAKEBREAK only:
projected +0.093 PF at portfolio level, -45.8% max drawdown reduction, only 7.5% trade
reduction. Implemented as P04 (IMPULSE) and P05 (FAKEBREAK) with market_regime_filter block.

The correct application of market regime filtering is engine-specific, not portfolio-wide.
Aggregating regime PnL at the portfolio level masks per-engine heterogeneity. An engine
losing money in a regime should exclude it; an engine profiting in that same regime must not
be affected. The FilterStack market_regime_filter block (added to filter_stack.py and
canonical_schema.py) is the correct implementation vehicle — per-strategy, declared in
STRATEGY_SIGNATURE, hard pre-entry gate with no fallback.

For any future portfolio optimization using market_regime exclusion: (1) always run
per-engine regime breakdown first — never work from portfolio aggregate alone; (2) only
apply exclusion where engine PF < 1.0 in a regime with at least ~50 trades; (3) confirm
no other engine is strongly positive in that regime before considering a portfolio-wide gate;
(4) implement via market_regime_filter in STRATEGY_SIGNATURE — never via shared pipeline
    logic or portfolio-level gating.
---

---
2026-03-30 | Tags: fx_15m, mean_reversion, rsi_pullback, trend_filter, multi_symbol | Strategy: 22_CONT_FX_15M_RSIAVG_TRENDFILT_S01_V1_P00 through P04

RSI(2) averaged over two bars (rsi_2_avg) combined with a trend score gate
(|trend_score| >= 2) produces a genuine, scalable edge on FX 15M across
7 major pairs. Four-pass sweep: P00 concept validated (EURUSD only),
P01 5-pair expansion, P02 7-pair hardened, P03 time-exit tightened,
P04 friction-resilient 5-pair deployment subset. P04 entered burn-in.
P00 (EURUSD only): 2,345 trades, Sharpe 2.77, PROMOTE — signal confirmed.
P01 (5 pairs): 11,510 trades, Sharpe 4.62, PROMOTE — scales cleanly.
P02 (7 pairs, hardened): 11,239 CONSERVATIVE trades, PF 1.18, CAGR 99.87%,
  Max DD 3.39%, break-even slippage 0.31 pip — signal genuine, friction thin.
P03 (7 pairs, max_bars 12->3): 14,224 trades, PF 1.19, CAGR 107%, break-even
  0.52 pip. Tighter exit freed positions faster, INCREASING trade count vs
  expected reduction (entry_when_flat_only creates re-entry opportunities
  when holding time drops). Win rate fell 63%->55% but payoff improved
  0.68->0.96.
P04 (5 pairs, drop NZDUSD+EURUSD): 11,216 trades, PF 1.23, CAGR 93.6%,
  Max DD 5.47%, MC 95th pctl DD 7.42%, break-even 0.65 pip. All 5 symbols
  survive +0.2 pip friction. Recovery factor 13.87. 0 negative years.
The rsi_2_avg signal captures genuine mean reversion in trend-aligned
conditions. The primary edge lies in the first 3 bars post-entry — bars
4-12 are structurally net-negative across all pairs and regimes.
NZDUSD and EURUSD are friction-fragile and dilute the portfolio; removing
them improves PF, Max DD, and friction resilience simultaneously.
1. For FX 15M pullback strategies, always decompose by bars_held before
   assuming max_bars is well-calibrated. The decomposition may reveal a
   hard cutoff (bar 3-4 in this case) where edge transitions from positive
   to negative. Tightening max_bars to that cutoff is a clean, attributable
   lever that does not require a new signal.
2. Reducing max_bars on an entry_when_flat_only strategy does NOT reduce
   trade count — it creates more entries by freeing positions faster.
   Expected: fewer trades, higher quality. Actual: more trades, different
   quality profile (lower WR, better payoff ratio). Account for re-entry
   dynamics before forecasting trade count impact.
3. Symbol pruning based on friction stress test is a valid deployment filter
   even when all symbols are profitable in backtest. A symbol that flips
   negative at +0.2 pip slippage has insufficient edge buffer for live
   execution and should be excluded from deployment regardless of raw PnL.
4. Burn-in gate for high-frequency 15M strategies should include a $/trade
   floor (warn < $2.00, abort < $1.20) in addition to PF and WR — PF can
   stay above 1.0 while per-trade expectancy quietly compresses toward zero
   under friction, spread widening, or execution slippage. The $/trade metric
   catches edge erosion before it is visible in PF or WR.
---
---
---

---
2026-03-30 | Tags: engine_fallback, stop_price, live_deployment, signal_schema, fx_15m

Strategies using ENGINE_FALLBACK (omitting stop_price from the signal dict
to allow engine to compute stop from actual fill price) cannot be deployed
directly to TS_Execution. The live signal schema requires stop_price as a
mandatory field. Per-symbol live deployment wrappers must restore stop_price
using the same ATR multiplier as ENGINE_FALLBACK (2.0x ATR).
P02/P03 research strategy.py omits stop_price — stop computed by
execution_loop.py at fill time from entry_price (not signal close).
TS_Execution signal_schema.py: stop_price is in _REQUIRED_FIELDS and
rejects signals missing it with SCHEMA_MISSING_STOP_PRICE.
Per-symbol live wrappers for P04 restored: stop_price = close +/- 2.0*atr_val.
Phase 0 smoke test passed for all 5 per-symbol instances.
ENGINE_FALLBACK is valid for research (avoids gap-over-stop on next-bar-open
fill). For live deployment, the stop must be computed at signal time using
signal-bar close, accepting a small gap risk on next-bar open — the same
trade-off as all other live strategies.
Any future strategy using ENGINE_FALLBACK in research must have its
per-symbol live wrapper compute and include stop_price explicitly.
Document the ATR multiplier used in the research directive so the live
wrapper replicates it exactly. This is a deployment translation step, not
a strategy change — the mathematical stop distance is identical.
---
---
---

---
2026-04-01 | Tags: CHOCH, timeframe, structural-comparison, XAUUSD, 30M, 1H, regime | Strategy: 26_STR_XAUUSD_30M_CHOCH_S02_V1_P00 | Run IDs: e03a2a247fcfb6cac019e34c
ChoCh at 30M amplifies noise vs 1H — same win rate (38.6% vs 40.0%) but K-Ratio -4.83 vs positive, PF 0.74 vs 1.08. 30M: 88 trades, PnL -136.40, high-vol bucket -173.63 kills result. 1H: 50 trades, PnL +25.61, Normal-vol Short PF 5.40 drives edge. ChoCh is timeframe-sensitive. At 30M the 3-swing streak (~30h) does not filter intraday noise; at 1H (~60h) it captures genuine regime shifts. The entry condition fires correctly at both TFs but follow-through collapses at 30M in high-vol. Do not compress ChoCh below 1H without either raising streak threshold (>=5) or gating on low-vol regime only. High-vol regime is destructive at 30M and should be excluded in any 30M pass. --- ---.
---

---
2026-04-01 | Tags: SFP, swing-validity, liquidity-grab, XAUUSD, 1H, guard | Strategy: 24_PA_XAUUSD_1H_SFP_S01_V1_P00 | Run IDs: 24_PA_XAUUSD_1H_SFP_S01_V1_P00
SFP requires validity guard: swing level must be unbroken in the MIN_SWING_AGE (3) bars between detection and current bar. Guard: recent_low >= swing_low across 3 intervening bars. Without this, SFP fires on already-broken levels; expected false-positive rate >30% on sweep bars. A wick-reversal pattern against a structural level is only valid if that level has not been violated in the intervening bars. Stale levels produce high false-positive rate. Any pattern referencing a prior swing for entry/TP/SL must include an intervening-bar violation check. Canonical pattern: recent_extreme vs swing_level before firing signal. --- ---.
---

---
2026-04-01 | Tags: LIQGRAB, asian-session, early-exit, XAUUSD, 15M, time-stop | Strategy: 25_REV_XAUUSD_15M_LIQGRAB_S01_V1_P01 | Run IDs: 25_REV_XAUUSD_15M_LIQGRAB_S01_V1_P01
Asian liquidity grab edge lives in first 3 bars post-sweep. Holding to 12:00 UTC converts winners into losers (55% fake-reversal rate in P00). P01 (TP=1.0R, 3-bar exit) produced cleaner curve vs P00 (TP=asian_range_opposite, 12:00 UTC exit). P00 degraded primarily in bars 4-12 post-entry. Session-reversal patterns have a decay window. The structural snap-back happens fast or not at all. Time stops at 3 bars are more protective than session-end exits for 15M setups. For session-reversal strategies on 15M, default time stop should be 3-5 bars. Wider exits expose the trade to re-sweeps and session continuation. Validate TP=1R vs 1.5R next. --- ---.
---

---
2026-04-02 | Tags: PINBAR, hybrid-exit, trailing-stop, MFE-giveback | Strategy: 27_MR_XAUUSD_1H_PINBAR_S01_V1_P05 | Run IDs: P03 (baseline), P04 (pure trail, failed), P05 (hybrid, promoted)
Pure trailing stop (remove TP, trail from 0.5R) destroyed edge on pin bars (PF 1.42->1.27, high-vol collapsed $411->$40). Hybrid exit (keep TP + trail only after 1.0R, lock 0.5R) preserved PF while improving Sharpe 2.23->2.82 and Return/DD 6.10->8.06. P04 pure trail: 438 trades PF 1.27 $642. P05 hybrid: 451 trades PF 1.41 $1061, Max DD 0.13%. Trail converted 28 time exits to locked wins without choking TP runners. Short-duration MR patterns (avg 5.8 bars) need fixed TP as primary exit -- pullbacks within the move exceed loose trail thresholds. Trailing only adds value as insurance layer above 1.0R, not as replacement for TP. For sub-10-bar MR strategies, never replace fixed TP with trailing. Hybrid trail (activate above 1R, lock 0.5R floor) is the only valid trailing architecture for this trade duration class. --- ---.
---

---
2026-04-04 | Tags: ENGULF, 15M, edge-decay, exit-timing, isolation-decomposition | Strategy: 28_PA_XAUUSD_15M_ENGULF_S03_V1_P01 through P07 | Run IDs: 683fd6191db71f348f34006a (P06 best), a4e9cb986f6a54c3001b42fb (1H P03)
15M bullish/bearish engulfing edge decays within 2 bars (~30 min). The P01 baseline's 2-bar exit was accidental (unrealized_pnl bug: ctx.get("unrealized_pnl", 0) always returns 0, so bars_held >= 2 AND unrealized_pnl <= 0 fires on ALL trades at bar 2). Isolation-first decomposition (P02 regime, P03 direction, P04 exit, P05 time-normalized, P06 combined best, P07 pure 5-bar) confirmed: removing the 2-bar exit destroys the edge in every variant tested. P06 (regime filter + direction gate, keeping 2-bar exit) is the optimal expression. P06: 123 trades, PF 2.55, Return/DD 7.97, Max DD $31.83. P07 (same as P06 minus 2-bar exit): PF 1.27, Return/DD 0.58, Max DD $174.65. P04 (8-bar exit): PF 0.89. P05 (32-bar): PF 0.86. 15M engulfing captures a micro-reversion impulse that completes within 2 bars. Holding longer adds noise, drawdown, and SL exposure (1 SL in P06 vs 4 in P07). The "bug" is the feature: fast exit locks in the mean-reversion impulse before fade. 1. For 15M MR patterns, always test bars_held decomposition before assuming exit timing from higher TFs. 1H optimal hold (8 bars) does NOT transfer to 15M. 2. When an accidental mechanism produces strong results, isolate and confirm it before "fixing" it. The bug produced PF 2.55; the fix produced PF 0.89. 3. Direction-specific regime gating (block shorts in LOW vol and STRONG UP only) required AST workaround: class-level string constants + frozenset membership tests bypass semantic_validator's BehavioralGuard. FilterStack only supports global regime exclusion. --- ---.
---

---
2026-04-04 | Tags: portfolio, diversification, multi-timeframe, same-instrument, correlation | Strategy: PF_9D1FEA9AD62B (1H P03 + 15M P06) | Run IDs: a4e9cb986f6a54c3001b42fb, 683fd6191db71f348f34006a
Two engulfing strategies on XAUUSD at different timeframes (1H + 15M) produce near-zero correlation (-0.05) and 42% drawdown diversification benefit. Combined: 258 trades, PF 1.57, Sharpe 2.08, 0/16 negative rolling windows. Only 24/210 active days had trades from both. Combined Max DD $87.43 vs sum-of-parts $150.49 (42% reduction). Combined Return/DD 5.84. MC 5th pctl CAGR +0.25%. 15M P06 anchors drawdown ($31.83 DD offsets 1H's $118.66 DD periods). Different timeframes on the same instrument act as independent signal sources. 15M micro-reversion (~30 min) is structurally distinct from 1H (~8hr). Multi-TF diversification is real and measurable. 1. When a strategy works on one TF, test adjacent TFs as portfolio diversifiers. 15M added $254 PnL while reducing combined DD below 1H standalone. 2. Same-instrument multi-TF portfolios should be evaluated as a unit -- individual metrics understate combined value. 3. Temporal separation (24/210 overlap days) explains diversification: strategies rarely compete for the same price action. --- ---.
---

---
2026-04-04 | Tags: session_close, mean_reversion, vwap_fade, exit_timing, regime_dependency | Strategy: 29_MR_XAUUSD_1H_CMR_S01 | Run IDs: ad3d27bf3d884a47398364d4, cbb5b0c79f00f51e9c6999f6
London close VWAP fade (16:00 UTC, 1.5x ATR extension) does not produce a universal mean-reversion edge on XAUUSD 1H. P00 (VWAP TP): PF 0.64. P01 (0.5R fixed TP): PF 0.87. The pullback exists but is shallow (<0.5R) and regime-dependent: Short x High Vol (PF 2.44, 33T) and Long x Low Vol (PF 3.62, 18T) are the only viable cells. P00->P01: PnL -$436 -> -$135, WR 41%->49%, DD $547->$376. TP hit rate stayed ~3% in both. Time exit bleed is the primary loss mechanism (70%->43%). The London close extension is not a session-anchored mean reversion -- it is a volatility-regime directional signal. Shorts work in high vol (institutional unwind), longs work in low vol (range compression snap). VWAP is not a valid TP anchor; extension remains a valid trigger. Do not pursue VWAP-based TP for session-close strategies. If revisiting, test as a regime-gated directional strategy (Short+HighVol only) with fixed 0.5R TP and 2-bar max hold. The 51-trade combined subset (~23/yr) needs at least 3 years of data to validate. --- ---.
---

---
2026-04-04 | Tags: SMI, divergence, direction_asymmetry, counter_trend, XAUUSD, 1H, EMAXO, family-32, regime-filters, meta-insight, XAUUSD, Date: 2026-04-04, Strategies: S01_P00 (1H), S02_P00 (30M), S03_P00 (15M), EMA(10/30) crossover on XAUUSD produces no raw edge (PF 0.83-1.13 across 15M/30M/1H). Conditional profitability appears in specific regime intersections, but is attributable to underlying market structure rather than the crossover signal. EMA crossover demonstrates that regime filters do not create edge but can isolate conditions where weak signals align with underlying market behavior. The observed edge in Long x WeakDn (PF 1.93-2.05, 36-99T) is not attributable to the crossover itself but to a broader pattern of mean-reverting bounces after trend exhaustion., Long x Normal Vol: PF 5.71 but only 20T (statistically fragile). Long x WeakUp: PF 1.73, 31T. Short x any cell: PF <= 0.78 except StrongDn (PF 1.07, 14T). 36% of time exits had MFE >= 0.5R., Unfiltered PF: 1H 1.13, 30M 0.83, 15M 1.08. Long x WeakDn isolated: 1H PF 2.05 (36T, $193), 15M PF 1.93 (99T, $335). Short x StrongUp consistently PF 0.38-0.43 across all TFs., Signal shows directional asymmetry; long-side behavior may contain weak edge but not yet validated. Bullish divergence aligns with mean-reverting behavior after downside exhaustion, while bearish divergence conflicts with persistent upward drift and continuation bias in XAUUSD. Reversal magnitude is insufficient to reach 1.0R within observed holding window, indicating shallow counter-moves rather than full reversals., This experiment confirms that filter stacks are effective for segmentation and analysis, but not for transforming non-edge signals into robust strategies. Regime-conditioned profitability in a weak signal reflects the regime's own behavior, not the signal's predictive power., P01 should test longs only + 0.5R TP to match observed MFE distribution. If long-only PF stays near 1.0 after TP change, the divergence signal lacks sufficient edge for deployment. The bottom-detection asymmetry may generalize to other trending instruments -- worth testing on indices if validated here., ---, ### Entry: Family 31 — BRK XAUUSD ATRSQZ — Cross-Timeframe Finding, ATRSQZ, family-31, cross-timeframe, XAUUSD, Date: 2026-04-04, Strategies: S01_P00 (1H), S02_P00 (30M), S02_P01 (30M long-only), S03_P00 (15M), When evaluating new signal classes, raw unfiltered PF < 1.0 should disqualify the signal before regime decomposition. Regime filters should refine existing edge, not rescue absent edge. The Long x WeakDn pattern may generalize as a structural feature of XAUUSD rather than a signal-specific finding -- future strategies showing this cell as dominant should be scrutinized for false attribution., ---, --- | Strategy: 30_REV_XAUUSD_1H_SMI_S01 | Run IDs: c983098dd875e9fa0ced28a0

732772dc867e82892dc92d50, a8cafb275069f1bb5e1a1583, a3f73d2563dbd9bcabdffde9
SMI pivot divergence on XAUUSD 1H produces strong directional asymmetry: longs PF 1.04 (92T, +$27), shorts PF 0.51 (152T, -$723). Bearish divergence fires 66% more often but wins only 41% vs 61% for bullish. Zero TP exits (0/244) at 1.0R target.
The ATR squeeze breakout strategy is the only tested class on XAUUSD showing stable expectancy across timeframes and regimes, with edge entirely driven by long-side expansion; short-side participation is structurally invalid.
---
2026-04-06 | Tags: momentum_ignition, BTCUSD, 1H, cross_timeframe, regime_filter, IMPULSE | Strategy: 33_TREND_BTCUSD_1H_IMPULSE_S03_V1_P02 | Run IDs: 717230561d233f4a243f8a1f

BTC 1H momentum ignition (bar_range > 1.8x avg_range(5), close in top/bottom 20% zone)
produces genuine edge after two isolation passes. Cross-timeframe comparison (15M/30M/1H)
confirmed 1H optimal: higher TF = better signal-to-noise for impulse detection. P01 excluded
WeakUp regime (trend_regime == 1) where both directions lose. P02 added Age 1 exclusion
(PF 0.53, noise immediately post-regime-transition). P03 (low-vol gate) and P04 (higher
range_mult 2.2x) both rejected -- trade count collapsed without proportional PF gain.
P05 extended backtest (2020-2026, 633 trades) validated P02 edge survives full BTC cycle
with no negative years but PF diluted from 1.70 to 1.45. P02 promoted to BURN_IN.
Cross-TF: 15M PF 1.06, 30M PF 1.17, 1H PF 1.25 (baseline). P02: 262 trades, PF 1.70,
Sharpe 2.98, Max DD 7.03%, Return/DD 11.39. P05 (6yr): PF 1.45, 633T, 0 negative years.
Impulse detection is timeframe-sensitive -- lower TFs produce more signals but worse
signal quality. WeakUp regime is structurally untradable for impulse (both Long PF 0.66
and Short PF 0.40 lose). Age 1 is pure noise post-transition (PF 0.53). These are
structural exclusions, not parameter tuning -- the market microstructure does not support
impulse follow-through in these conditions.
1. For impulse/breakout strategies, always test 15M/30M/1H before committing to a
   timeframe. The optimal TF depends on the instrument's noise profile, not the signal.
2. WeakUp regime exclusion should be tested on any trend-following BTC strategy --
   the regime represents directional ambiguity where impulse signals fire but lack
   follow-through momentum.
3. First BTC strategy in portfolio. Correlation with XAUUSD engines expected to be
   low (different asset class, different microstructure). Portfolio diversification
   benefit should be evaluated once burn-in data accumulates.
---
---
---

---
2026-04-06 | Tags: filter_stack, bug_fix, exclude_regime, direction_gate, infrastructure | Strategy: (all strategies using FilterStack with direction_gate + exclude_regime) | Run IDs: 717230561d233f4a243f8a1f

FilterStack had a silent bug: when direction_gate=true, the entire trend_filter block
was skipped via `continue` at line 114, which meant exclude_regime was never evaluated.
Any strategy combining direction_gate + exclude_regime was running WITHOUT the exclusion.
Discovered when P01 (exclude WeakUp) produced identical results to P00 (no exclusion).
Pre-fix P02: 264 trades, PnL $830.94, PF 1.73. Post-fix P02: 262 trades, PnL $800.40,
PF 1.70. 2 fewer trades taken, metrics slightly lower but edge confirmed genuine.
The exclude_regime check must fire BEFORE the direction_gate continue statement.
Fix applied: exclude_regime evaluation inserted before the `continue` in filter_stack.py.
All strategies using direction_gate + exclude_regime should be verified.
1. Any previously run strategy with both direction_gate=true AND exclude_regime set
   was effectively running without the exclusion. Results are valid but represent the
   unfiltered version. Re-run if the exclusion was material to the edge hypothesis.
2. filter_strategies.py merge logic also fixed: existing rows now get metrics refreshed
   from Master Filter on re-run (was append-only, never updated stale data).
   candidate_status also auto-syncs with portfolio.yaml on every run.
---
---
---

