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
---

---
2026-04-07 | Tags: regime_gate, pipeline_staging, OOS_validation, overfit, capital_wrapper | Run IDs: experiments/regime_gate_validation.py, experiments/results/regime_gate_validation.json
Regime gating (blocking trades in unprofitable regime cells) improves in-sample metrics but fails OOS stability — 0/5 active-gated portfolios survived 60/40 split. Direction reversal in all cases: blocked trades were losers in training but winners in OOS. In-sample: 5/9 improved, +$9525 total dPnL, avg PF +0.11, avg DD -0.45pp. OOS: 0/5 active stable; PF_7FCF1D2EB158 reversed from +$6420 IS to -$7360 OOS. Blocked OOS PnL was positive in all 5 cases ($1427, $455, $160, $52, $1143). REJECT for pipeline integration. Regime labels lack forward-predictive signal at current sample sizes (min_trades=10). Ordering confirmed: if ever used, gating must precede capital allocation (B != C in 5/5 active cases). Profile selection unaffected (0/9 changed). Stage 4 Regime Audit stays diagnostic/reporting only — never auto-block. If revisited: require min_trades >= 50, walk-forward validation, regime-cluster stability checks. Strategy Activation System remains valid as monitoring layer, not gating layer. --- ---. --- ---.
---

---
2026-04-07 | Tags: regime_gate, activation, exposure_control, concurrency, pipeline_staging | Run IDs: experiments/regime_gate_validation.py, experiments/activation_vs_filtering.py, experiments/exposure_control_vs_activation.py, experiments/concurrency_diagnostics.py
Portfolio-level regime filtering, activation, and exposure control do not provide material improvement with current regime definitions. Regime buckets (vol, trend) are too coarse to partition trades into stable, behaviorally distinct populations. 3 experiments, 9 portfolios. Post-trade filtering: +$1058 avg IS but 0/5 OOS stable. Binary activation: -$3332 avg but 9/9 OOS stable (returns to baseline). Exposure control: +$11 avg (noise). REV max_concurrent=2, cap fires 6-9 trades. TREND low-vol signal ~$130 avg. Do not implement regime-based gating, activation, or exposure control in pipeline. REV×TREND overlap is beneficial diversification. Only valid signal (TREND in low-vol) is too small for system-level rules. Revisit only if regime classification becomes granular and aligned with strategy entry logic. No Stage 4 Regime Audit in pipeline. Current regime labels (vol bucket, trend label) lack forward-predictive power for trade-level decisions. Future work requires feature-level regime alignment, not coarse state labels. --- ---. --- ---.
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
---

---
2026-04-10 | Tags: uk100_15m, session_filter, pullback, trade_quality, regime_gating | Strategy: 40_CONT_UK100_15M_RSIPULL_SESSFILT_S08–S11_V2_P00
Three independent session filters applied to UK100 London-open short pullback (S08 baseline PF 1.24, 133 trades) all improved PF by blocking low-quality entry conditions. S09 (Wednesday exclusion) → PF 1.43/112 trades; S10 (weak_down regime block) → PF 1.56/68 trades; S11 (range_low_vol block) → PF 1.39/101 trades. S10 weak_down block delivers best PF lift (+0.32) but halves trade count to 68 — single-symbol statistical floor concern. S09 Wednesday block achieves +0.19 PF with only 16% trade reduction, best efficiency ratio. UK100 London-open shorts have a measurable regime dependency — weak downtrends and low-volatility ranges produce negative-expectancy entries that dilute the edge. Wednesday exclusion likely proxies for a mid-week liquidity/volatility trough specific to FTSE. The filters are additive in mechanism (day-of-week vs trend vs volatility) suggesting combinatorial stacking may compound gains, but trade count erosion per filter must be monitored. For UK100 London-open pullback variants, test combinatorial filter stacking (S09+S10 or S09+S11) only if the combined trade count stays above 80. Treat weak_down regime gating as a universal pre-filter candidate for any index session strategy — the PF lift is too large to be noise at 68 trades. ---. --- ---.
---

---
2026-04-13 | Tags: F42, LIQSWEEP, SESSION_FILTER, FX_15M, CROSS_SYMBOL | Strategy: 42_REV_EURJPY/GBPUSD_15M_LIQSWEEP | Run IDs: S13_P04, S05_P03
Asia session exclusion [0-7 UTC] is the dominant filter for JPY crosses and GBP pairs on LIQSWEEP 15M. Regime age adds marginal lift only. EURJPY: base PF 1.20 → session only PF 1.40 SQN 2.40 (331T) vs regime_age_only PF 1.24 SQN 1.72 (455T). GBPUSD best: age[6-10] + excl. WeakUp → PF 1.88 SQN 2.81 97T. Asia session noise systematically degrades LIQSWEEP signal on JPY crosses. Regime age responds differently per symbol — GBPUSD: mature bars (6-10); EURJPY: session filter dominates. The two filters are not additive. For future LIQSWEEP FX passes, test session filter as primary gate first. Regime age is secondary exploration only on symbols that survive session filtering. --- ---.
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
---

---
2026-04-14 | Tags: CHOCH_v2, direction-asymmetry, XAU, BTC, 1H | Strategy: 46_STR_XAU_1H_CHOCH_S01_V2_P01 | Run IDs: ff42d3d84bca6ce5d4782adc, dda4eef019b3252ba211e96c, 69b70372bc2604b73596dd12
CHOCH_v2 shows clear directional asymmetry on XAU 1H (long-only PF 1.15 -> 1.33 at 373 trades); asymmetry is weak on BTC 1H (long PF 1.09 vs short 1.02). - XAU: long arm PF 1.33 (n=373) vs blended PF 1.15 (n=572); short arm ~1.0 - BTC: long arm PF 1.09 (n=384) vs short arm PF 1.02 (n=365); blended 1.054. Short-side trades dilute edge on XAU where long-side carries the signal. On BTC the asymmetry is marginal and both directions cluster near break-even. The behavior is consistent with a pivot-breakout (not true CHOCH) interacting with asset-specific trend regimes (XAU uptrend vs BTC mixed). Future CHOCH work on XAU should be long-biased or direction-gated. BTC CHOCH_v2 requires an orthogonal filter (session, regime) rather than direction restriction alone. ---. --- ---. --- ---.
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
---

---
2026-04-17 | Tags: exit_timing, mean_reversion, h4, cmr, signal_persistence, reentry_frequency | Strategy: 53_MR_EURUSD_4H_CMR_S01_V1_P00..P05 | Run IDs: P00, P01, P02, P03, P05 (EURUSD, 2024-01-02 -> 2026-04-15)
For the 3-consecutive-close MR signal on EURUSD H4, a 3-bar time-exit (P01) dominates all tested alternatives (day-close, 6-bar, PnL-gated 1-2 bars, signal-only). P01 PF=1.17 / SQN=1.09 / DD=4.83%. P02 PF=1.14 with higher DD (11.48%). P05 PF=1.11 with avg_bars=11.63 and ~50% lower trade count. P03 PF=1.01, showing edge collapse under early profit-taking. Edge is concentrated in a short 2-3 bar window. Exiting too early truncates the positive tail, while holding beyond this window leads to edge decay. Signal persistence is not the dominant driver; re-entry cadence and capital recycling are key contributors to total PnL. For consecutive-close MR signals on H4 FX: default exit = ~3 bars; avoid PnL-gated early exits; avoid relying solely on signal reversal; re-entry frequency is additive to performance even when per-trade expectancy is lower. --- ---. --- ---.
---

---
2026-04-17 | Tags: timeframe_scaling, mean_reversion, cmr, signal_quality, daily_tf | Strategy: 53_MR_EURUSD_1D_CMR_S02_V1_P00 | Run IDs: 423cb6c67747cc63ca063922 (EURUSD, 2024-01-01 -> 2026-04-14)
3-consecutive-close MR signal shows materially higher PF and stability on Daily (PF 1.65, SQN 1.47) vs H4 variants (best PF 1.17). 1D: 63 trades, PF 1.65, SQN 1.47, DD 0.034%, long PF 1.74 / short PF 1.52. H4 P01: 359 trades, PF 1.17, SQN 1.09, DD 4.83%. Edge persists across timeframe scaling and improves under noise reduction. Signal structure is consistent, but lower-frequency sampling increases signal quality at the cost of trade count. Daily timeframe is a higher-quality representation of the same signal. Next step is to increase sample size via multi-pair expansion before modifying thresholds or rules. ---. --- ---. --- ---.
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
---
---
---

---
2026-04-17 | Tags: 53_MR, CMR, ASSET_SELECTION | Strategy: 53_MR_EURUSD_1D_CMR_S02_V1 | Run IDs: P07 vs P06
Removing persistently negative-expectancy pairs (NZDUSD PF 0.37, GBPUSD PF 0.73) materially improves system performance (PF 1.30→1.64, MAR 1.84→2.31). P06→P07: 363→322 trades; MaxDD 11.2%→10.0%; CAGR 20.6%→23.1%; net PnL +$544→+$616. The CMR signal is asset-sensitive. Performance depends on structural compatibility between the signal and the underlying pair behavior. Pairs with persistent directional regimes support the signal; balanced or mean-reverting pairs degrade it. Asset selection must be empirical and driven by compatibility, not predefined currency categories. Default approach: exclude structurally negative pairs and validate inclusion individually. ---. --- ---. --- ---.
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
---
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
---
---
---

---
2026-04-19 | Tags: 54_STR, MACDX, XAUUSD, 5M, VOLATILITY_FILTER, DIRECTION_CONDITIONAL | Strategy: 54_STR_XAUUSD_5M_MACDX_S13/S20/S21_V1_P00 | Run IDs: S20=58ccdb5b/S21=a6c1814e — see TradeScan_State/backtests/54_STR_XAUUSD_5M_MACDX_S{20, 21}_V1_P00_XAUUSD
Volatility-regime filter (exclude low) on S13 triple-convergence MACDX improves all risk-adjusted metrics; effect is overwhelmingly short-side. S13 N=1301 PF=1.34 SQN=2.64 DD=$235 top10=58%; S20 (both dirs vol!=low) N=817 PF=1.55 SQN=3.88 DD=$172; S21 (shorts only vol!=low) N=1134 PF=1.48 SQN=3.58 DD=$195. Short PF 1.385 -> 1.820 in both variants; longs identical S13 vs S21. Low-vol shorts were the contaminated cluster in S13; direction-conditional vol gate (short-only) recovers most of the benefit while keeping all long-side trades. S20 maximises PF/SQN/DD; S21 maximises PnL and reduces tail concentration to 48%. Prefer S21-style direction-conditional filters when one side's edge is already clean: cheaper in trade count lost, stronger on PnL. Use engine-owned volatility_regime via ctx.require inside try/except for dry-run safety; never import indicators.volatility.volatility_regime in strategy (engine-owned-fields guard). --- ---. --- ---.
---

---
2026-04-19 | Tags: infra, partial_exits, capital_wrapper, engine_v157, scope_decision | Strategy: 54_STR_XAUUSD_5M_MACDX_S23_V1_P00
Partial-exit infra integrated; exits rejected as edge lever after full accounting validation. --- ---. --- ---.
---

---
2026-04-20 | Tags: 54_STR, MACDX, XAUUSD, 5M, BE, partial_exit, engine_v157, sweep, close_based_ur | Strategy: S21-style sweep variants

Engine: v1.5.7
v1.5.7 parity PASS: no-hook S21 produces 1301 trades PF=1.182 R=170.32 — byte-identical to v1.5.6 (both baseline variants). S22 control (1532 trades, close-based UR stub) also PASS: every entry/exit timestamp and price identical across both engines. Key findings from 6-variant sweep on 20-month 5M XAUUSD data (neutral regime stub):
BE-only (V1) — ZERO effect: The v1.5.7 stop_mutation hook triggers on close-based UR >= 1.0001. On volatile 5M XAUUSD, losing trades frequently wick intrabar to 1R+ but close BELOW 1R — the close-based UR never fires for these trades. SL is checked against bar_low (resolve_exit uses OHLC), so a trade that wicks to 1R intraday but closes below 1R gets SL-hit at -1R later without BE ever firing. Result: 0 trades converted from -1R to 0R in 20 months. Close-based UR is too conservative for volatile short-TF markets.
Partial only (V2) — modest impact: 585/1301 trades (45%) had close >= UR 1.0001 and triggered partial at 50%. PF drops 1.182 → 1.169 (partial surrenders upside on subsequent TP hits), DD drops 39.89 → 29.33 R (−10.56R, −26%). Trade-off: slightly worse expectancy, meaningfully lower variance. Partial does activate — close-based barrier is crossed for 45% of trades even though losing trades never reach it.
BE+Partial+TP off (V3) — pathological lock-in: With TP disabled and BE at entry, trades reaching 1R are trapped indefinitely (stop=entry, no TP). Result: 11 total trades over 20 months. entry_when_flat_only blocks new entries while position is open. CONFIRMED: TP-off + BE creates near-immortal positions on XAUUSD 5M; do not use without a time-exit gate.
BE+Partial+TP on (V4) — identical to V2: BE adds nothing on top of partial for same reason as V1.
Design implication: For BE to be effective on 5M volatile markets, either (a) use bar_high-based UR threshold (intrabar; requires engine change), or (b) lower close-based UR trigger to 0.5 to capture partial runs, or (c) use bars_held-based BE gate instead of UR. DO NOT test BE further with close-based UR >= 1.0001 on 5M assets — the effect is zero.
---
---
---
---
---

---
2026-04-20 | Tags: 54_STR, MACDX, XAUUSD, 5M, BE, intrabar_ur, engine_design, CRITICAL | Strategy: S21-style baseline 1301 trades

Engine: post-hoc probe
CRITICAL FINDING — Intrabar BE is MATERIAL on XAUUSD 5M MACDX baseline.
Post-hoc probe on engine's exact 1301 trades: replaced close-based UR with bar_high (long) / bar_low (short) for BE trigger. Result: 301/933 SL exits (32.3%) convert from -1R to 0R. PF: 1.1819 -> 1.7481 (+0.5662). Total R: 170.3 -> 473.6 (+303.3R). Max DD: 39.89R -> 12.00R (-70%). Mean converted R before: -1.008R (exactly the SL level). After: 0.000R. Net gain: +303.3R across 301 trades (1.008R per conversion). The remaining 632 SL trades had intrabar UR < 1 throughout — those are genuine losers that bar_high never crossed entry+1R.
Math check: 368 TP wins x ~3R + 0R x 301 BE + (-1R) x 632 genuine_SL = ~472R (~473.6 reported, consistent).
Root cause: SL check uses bar_low (OHLC), but UR uses close. Trades that spike to 1R+ intrabar then close below 1R get SL-hit later — this mismatch is the asymmetry BE is solving. Intrabar UR (bar_high for longs) aligns the trigger with the actual market path, not just the close.
Action required: v1.5.8 engine must expose ctx.unrealized_r_intrabar (bar_high for long, bar_low for short) alongside existing close-based ctx.unrealized_r. Strategy check_stop_mutation uses intrabar UR >= threshold to fire BE. No other engine changes. Probe is conservative (no downstream entry re-scheduling modeled) — real improvement may be higher or lower depending on position freed-up slots.
Do NOT implement via close-based UR workaround (threshold lowering etc.) — the mechanism is fundamentally bar_high/bar_low. Engine change is the correct path.
---
---
---
---

---
2026-04-21 | Tags: CMR, FX-1D, TF-dilation, basket, macro-filter, JPY-concentration | Strategy: 53_MR_FX_1D_CMR_S02_V1_P00/P03 | Run IDs: 53_MR_FX_1D_CMR_S02_V1_P00, 53_MR_FX_1D_CMR_S02_V1_P01, 53_MR_FX_1D_CMR_S02_V1_P03
3-bar consecutive-close pattern on FX 1D shows marginal basket edge (avg PF=1.08) with JPY pairs dominating: USDJPY PF=1.68, CADJPY PF=1.63 vs non-JPY/non-EUR pairs clustering near PF=1.0 or below (7/18 losing). 11/18 symbols PF>1.0; losers range PF=0.65-0.97. P03 macro union gate: PF avg 1.08->1.10, PnL +29% (268->345 USD total), trades 79->72 avg per symbol. TF dilation 4H->1D did not preserve edge uniformly. Residual signal concentrates in JPY crosses, likely driven by JPY macro-regime correlation with 3-bar directional patterns at daily resolution. Macro union gate adds mild selection value but does not rescue the non-JPY tail. If pursuing CMR at 1D, narrow to JPY pairs only as targeted follow-up. Full 18-pair basket is not viable. Do not promote any P00/P01/P03 symbols -- PF and trade counts are below portfolio quality gate. --- ---.
---

---
2026-04-23 | Tags: XAUUSD, 15M, ZREV, filter_stack, directional_trend_filter | Strategy: 55_MR_XAUUSD_15M_ZREV_S05_V1_P00 | Run IDs: 378c4f957101046dfbc0190f
S05 locks in volatility_filter (gte 0) + trend_filter(direction_gate: shorts gated to trend_regime >= 0) over ZREV P08 base as the chosen XAUUSD 15M mean-reversion candidate across the S04/S05/S06 probe series. S05 PF=1.31 exp=$1.70 R/DD=10.12 SQN=3.51 trades=1755 (vs S04 PF=1.20 exp=$1.13 R/DD=6.02; S06 added regime_age filter PF=1.33 but R/DD regressed to 9.56). Short-side weakness in S04 (PF=1.04) driven by counter-trend shorts in weak_down/strong_down regimes; directional trend filter eliminates that loss cluster (short PF 1.04 -> 1.21, WeakDn PnL -$233 -> +$73, StrongDn -$384 -> -$51) without touching long side. regime_age filter (S06) is a weaker probe: age 0/1 removed but edge dilutes at age 2. Default next-iteration probe: test asymmetric entry thresholds or long-side short-squeeze detection rather than stacking more FilterStack blocks. Do NOT stack regime_age on top of S05 - marginal PF gain is eaten by R/DD regression. ---. --- ---.
---

---
2026-04-23 | Tags: XAUUSD, 15M, ZREV, tail-dependence, structural-ceiling, S05-series-exhausted | Strategy: 55_MR_XAUUSD_15M_ZREV_S07/S08/S10/S11/S12/S13_V1_P00 | Run IDs: 97c6aa71ab48cd05bd27b876, be36a5e5cc2399515dec46fd, 98f343160e76a65512584a85, S11/S12/S13 (see FSP)
S05 base (PF 1.31, tail-PF 0.53, Gate 6 HARD FAIL) cannot be lifted past robustness Gate 6 (PF-after-top-5%-removal >= 1.0) via any single- or dual-lever probe. Six successive probes (S07 BE-at-+1R, S08 BE+trail-after-+2R, S10 slope_norm 0.0005 entry filter, S11 slope_norm 0.0003 relax, S12 z-gate entry 0.5, S13 partial-50%-at-+1R + BE) walk tail-PF from 0.53 -> 0.87 -> 0.90 ceiling without breaching 1.0. Stop-side probes (S07/S08) no-op on tail metrics (tail-PF 0.53/0.51): Z-extension exit at 2.15-sigma fires before trades reach +2R MFE in 95.5% of cases, so trail never fires and BE is noise-benign. Entry-side probe S10 (slope_norm > 0.0005) lifts tail-PF 0.53->0.87 but cuts trades 41% (1755->1038) and real-model PF drops 1.30->1.24. Relaxation S11 (0.0003) recovers trades but tail-PF collapses back to 0.55 -- the quality gain is non-linear and sits in the 0.0004-0.0005 window. S12 z-gate (|z|>0.5 entry) holds tail-PF at 0.87 but slips PF to 1.32. S13 (partial + BE exit) reaches tail-PF 0.90 (new best), Max DD $235 (new best), flat-period 16.5%, Top-5 concentration 28.5% -- every robustness dim improves but Gate 6 still XX at 0.90. The Z-extension exit at 2.15-sigma is itself the tail-generating mechanism. Winners that reach Z>=2.15 are structurally larger than median trades because the distance from entry (near HMA) to Z=2.15 is multi-sigma. Any exit-side intervention that preserves full position size to Z-exit preserves the fat tail. Stop mutation cannot help because trades rarely reach +2R MFE before Z-exit fires. Entry-side filtration has a ceiling at tail-PF ~0.87-0.90 because the trades that survive a tight entry filter are disproportionately the ones that go on to hit the tail. Partial extraction gets closer (0.90) but cannot breach 1.0 because the remaining 50% runner still carries the full tail. S05 series is exhausted at tail-PF 0.90 ceiling. Do NOT iterate further on ZREV S-variants (no threshold tweak, no stacking, no second partial) -- marginal gains are unlikely to clear 1.0 and risk of overfitting is high. S13 is the structurally cleanest variant (best-of-series on Gate 6, Max DD, flat-period, Top-5 concentration) but cannot promote because Gate 6 remains HARD FAIL. Pivot to a different mean-reversion architecture: the next MR probe should NOT use Z-sigma-extension exit as the primary profit-taking mechanism, since that mechanism is what manufactures the tail dependency being rejected by Gate 6. --- ---.
---

---
2026-04-23 | Tags: MR, ZREV, architecture-dead, cross-asset, tail-dependence | Strategy: 55_MR_EURUSD_15M_ZREV_S15_V1_P00 | Run IDs: 2212a1f63de22d584a3309da
ZREV (Z-extreme entry + zero-cross exit) is architecturally tail-dependent across assets; XAUUSD directional drift masked weakness that EURUSD exposed. S14 XAUUSD: PF 1.20, Top-5=123.4%, Long PF 1.82 vs Short PF 0.93. S15 EURUSD (S14 clone, pip-floor stop): PF 0.93, Top-5=148.4%, Long PF 0.96 vs Short PF 0.90 — symmetrically broken. Zero-cross exit manufactures the tail regardless of symbol; XAUUSD's apparent edge was Long-WeakDn drift (PF 3.45). Proper SL calibration does not resolve the distribution pathology. ZREV architecture is not viable under distributed-edge constraint. Do not probe further zero-cross MR variants on any symbol. S01-S13 tail-PF 0.90 ceiling + S14/S15 cross-asset confirmation closes this architecture. --- ---.
---

---
2026-04-24 | Tags: state_primitive, REGMISMATCH, regime_age, architecture_probe, filter_layer_candidate | Strategy: 58_STATE_XAUUSD_15M_REGMISMATCH_S01_V1_P00 | Run IDs: 81dd13a679d1081c002bde4a
State-mismatch (|delta_trend_regime|>=2 + regime_age_exec<=5) on XAUUSD 15M isolates a real but too-sparse edge to carry a standalone strategy; retain as filter-layer concept only. 34 trades / 25 months (1.4/mo); PF 3.13 but Top-5 concentration 90%, longest flat 539 days; Long PF 1.17 vs Short PF 6.25 (asymmetric); 100% of fills at regime_age 0-1, yearwise density collapses 28T/5T/1T across 2024/25/26. State primitive isolates rare, asymmetric events but produces insufficient density and excessive tail concentration for standalone deployment; the short/WeakDn cluster is mechanically real, the long side is near break-even. Do not pursue as standalone probe line; park REGMISMATCH state primitive as a candidate gating/filter feature on future price-based entries (e.g. zscore, momentum, breakout) where density is already sufficient. Re-evaluate only in filter-layer context, not as P00/P01 extension. --- ---.
---

---
2026-04-24 | Tags: idea59, runfail, engine-interface, no-trades, closure | Strategy: 59_MICRO_XAUUSD_15M_RUNFAIL_S01_V2_P00 | Run IDs: efda76b5e8e4071861074500
Idea 59 (RUNFAIL: 3-down-close + midpoint-confirm long) closed as engine-interface diagnostic branch, not economic falsification. V1 (inline close-rotation state) and V2 (validated candle_sign_sequence primitive) both produced NO_TRADES on XAUUSD 15M 2024-01-01..2026-03-20. Shift-based reference counts 205 entry-eligible bars on same window; primitive matches bar-for-bar. Dry-run (1000-bar sample, direct check_entry) emits 2 signals. Stage-1 engine loop on full window emits 0 trades for both V1 and V2. Hypothesis was never economically tested. The bug lies downstream of strategy-owned state — in engine ctx field surfacing or FilterStack interaction — where run_len / prev_high / prev_low are not reaching check_entry during Stage-1 execution despite succeeding under dry-run. Do not re-open idea 59 as a research branch. Any similar signal-bar entry depending on multi-bar ctx fields requires an engine-side diagnostic first (compare dry-run vs Stage-1 ctx dict contents for the same bar). Treat dry-run vs Stage-1 trade-count divergence as a first-class engine bug, not a strategy bug. --- ---.
---

---
2026-04-24 | Tags: idea-60, symseq, btcusd, regime-age, local-edge, asymmetric, scale-local | Strategy: 60_MICRO_BTCUSD_4H_SYMSEQ_S03_V1_P00 | Run IDs: dbd9f979388cd7de61698992, 73e52526fc336b2b0c764974, 19f8f9e807b9cc6197b9edd5
SYMSEQ 001+regime_age{0,1} edge on BTCUSD 4H is narrow and non-generalizable: confirmed long-only, 4H-local, drift-carried. Short-side mirror (110) and 1H scale transport both fail. S03 BTC 4H long: 90T PF 1.73 3/3 positive years. S04 BTC 4H short (110, no filter): 523T PF 0.995 1/3 positive. S05 BTC 1H long (same filter): 361T PF 0.988 1/3 positive. Post-hoc age-slice inverts: long age=0 PF 2.44 vs short age=0 PF 0.81. Mechanism is neither symmetric microstructure nor scale-invariant. It is a specific 4H+1D-HTF coupling capturing long-side continuation within 1 trading day of a regime flip on a trending asset; 'fresh-flip symbolic edge' as a general principle is unsupported. Do not promote regime_age{0,1}+001 to other symbols, timeframes, or short side without re-establishing each from scratch. Future symbolic-sequence probes must pre-declare direction + TF locality before generalization; post-hoc slices do not license extrapolation. --- ---.
---

---
2026-04-28 | Tags: gma_slope_flip, regime_asymmetry, htf_filter | Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P00 | Run IDs: 4e36cfcfe8bfeceff7d76060
Pure GMA slope-flip on NAS100 5M generates positive expectancy in WeakDn / Neutral regimes but loses on WeakUp; total edge is regime-asymmetric. WeakDn 407T +$541 PF~1.6; WeakUp 705T -$149 PF<1 (largest trade share, worst bucket). Slope-flip catches reversal-into-trend in down/sideways markets but whipsaws under sustained-up conditions where the GMA flips frequently without mean-reversion; WeakUp is dominated by failed shorts that get stopped. Future GMAFLIP variants (S01 P01 onward) MUST gate entry on HTF trend regime: skip WeakUp bucket entirely; allow WeakDn / Neutral trades unconditionally. --- ---.
---

---
2026-04-28 | Tags: gma_slope_flip, filter_iteration, negative_finding, regime_filter | Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P01..P04 | Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P01, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P02, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P03, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P04
Sweep across 4 GMAFLIP filter variants: HTF regime filter is the only individually-positive filter. Persistence filter alone degrades PF; combined regime+persistence trades return for drawdown safety; tighter Gaussian sigma (4.0 vs 5.0 DSP convention) is worse. P01 regime: PF 1.13->1.25, Sharpe 0.51->0.92; P02 persistence: PF 1.13->1.09 (worse); P03 combined: best DD 0.15% but PF 1.20<P01. Slope-flip wobbles persist 3+ bars natively, so persistence filter rarely triggers and just delays entries by 3 bars (worse fills). HTF regime is the structural filter that matters because P00 trade_edge data showed losses concentrated in WeakUp regime. Sigma=5 (DSP length/6 convention) outperforms sigma=4 — more responsive MA generates noise flips without alpha. For GMAFLIP variants going forward: (a) always include HTF regime filter (skip regime>=1); (b) skip persistence filter unless combined with another noise reducer; (c) lock sigma at length/6 DSP convention; (d) next iterations should test stop multiplier (1.5x / 2x / 4x) and HTF timeframe (1H regime feed). --- ---.
---

---
2026-04-28 | Tags: gma_slope_flip, persistence_sweep, slope_angle, non_monotonic | Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P05..P08 | Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P05, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P06, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P07, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P08
Persistence-bar sweep (1, 3, 5, 7) on top of regime filter is non-monotonic and never beats P01 (no persistence). Slope-angle filter at 5pct of ATR over-restricts to 32 trades but those 32 hit best PF/Sharpe — angle threshold should be much lower. Persistence sweep PF: bars=0 1.25, bars=1 1.15, bars=3 1.20, bars=5 0.98 (NEG), bars=7 1.12; slope angle 5pct: 32T PF 1.30 Sharpe 1.41. Slope flips on Gaussian length=30 sigma=5 naturally persist 7+ bars in 95pct of cases — persistence filter rarely triggers and only delays entries. The PF=0.98 dip at bars=5 is sample-noise, not a structural minimum. Slope-angle filter showed best per-trade quality but threshold of 5pct of ATR cuts 98pct of signals; lower thresholds (0.5-2pct) would yield more usable variants. S02 going forward: (a) drop persistence from filter library; (b) sweep slope_angle threshold at 0.005, 0.01, 0.02, 0.03 to find usable upper bound; (c) regime filter remains the only robust filter; (d) test stop multiplier sweep next (1.5, 2.0, 4.0 vs current 3.0) since DD per trade is 50pct of stop budget. --- ---.
---

---
2026-04-28 | Tags: gma_slope_flip, stop_sweep, slope_angle_combined, exhaustive_sweep | Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P09..P11 | Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P09, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P10, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P11
Slope-angle filter combined with regime filter (P09 1pct, P10 2pct) hurts every variant — over-filtering removes good trades. Tighter stop (1.5xATR vs 3xATR) hurts win rate from 42pct to 33pct, indicating 3xATR is at or above the noise floor and 1.5x sits inside it. P09 (regime+slope1pct): 549T 63 PF 1.11 (vs P01 853T 59 PF 1.25); P11 (regime+stop1.5x): 1039T 06 WR 33pct (vs P01 853T 59 WR 42pct). Filter stacking is sub-additive: each filter removes more good trades than bad ones above the first. P01 (regime alone) is the structural local optimum for this primitive on this data. Stop=3xATR is correct/loose — tighter stops sit in the noise envelope of NAS100 5M and clip valid trades. Slope angle works in isolation (P05) but conflicts with regime filter when stacked. GMAFLIP family is parameter-saturated: P01 is the operating point. To improve further requires architectural change — try GMAFLIP on higher timeframe (15M, 1H) where regime dynamics differ, or add a genuinely independent filter (volume/liquidity/news) that does not overlap with regime. Stop sweep direction should be wider (4x, 5x) not tighter. --- ---.
---

---
2026-04-28 | Tags: gma_slope_flip, filter_by_exclusion, session_filter, vol_filter, sub_additive_confirmed | Strategy: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P12..P14

Kalman Price Filter [BackQuant] — Pine v6 prototype (TS_Execution/pine) | Run IDs: 61_TREND_IDX_5M_GMAFLIP_S01_V2_P12, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P13, 61_TREND_IDX_5M_GMAFLIP_S01_V2_P14
kalman_price_filter_v1_0_strategy.pine (locked baseline), kalman_price_filter_v2_0_strategy.pine (rejected — order-2), kalman_price_filter_v1_1_strategy.pine (+session, equivalence-tested), kalman_price_filter_v1_2_strategy.pine [LOCKED] (+orthogonal triple stack)
Filter-by-exclusion final pass tested 3 orthogonal filters (NY-only session, drop-London surgical session, Direction*Volatility via atr_percentile). All three improved Sharpe and DD vs P01 baseline but reduced absolute P&L. None overcame the filter-stacking sub-additivity rule established in earlier batches.
Adapted BackQuant's Kalman Price Filter (order-1 scalar Kalman) into a long-only flip strategy on NAS100 5M. Calibrated baseline (OHLC4 source, M=4 measurement noise, 2-tick slippage, all sessions) achieved PF 1.195 / Sharpe 0.545 / +26.9% annual / max DD 4.5%. Stacking three orthogonal regime filters on top — ADX(15) trend strength, smoothed RSI(2)/SMA(3) > 35 momentum confirmation, Hurst(0.45) persistence, all loose thresholds — produced strict additivity: final config achieves PF 1.312 / Sharpe 0.640 / Sortino 2.215 / +30.5% annual / max DD 4.0%, with per-trade $ +71% vs baseline ($1.14 -> $1.95). This contradicts the GMAFLIP P-sweep finding of universal sub-additivity. The reconciling principle is signal-density: HIGH-frequency signal generators (>1500 trades/year on native TF) admit additive loose-filter stacking; LOW-frequency generators (<1000 trades/year) suffer sub-additivity even with loose filters.
P12 NY-only: 336T 79 PF 1.23 Sharpe 1.05; P13 surgical-session: 554T 47 PF 1.22 Sharpe 0.96; P14 vol filter: 677T 90 PF 1.16 Sharpe 0.72; all vs P01 853T 59 PF 1.25 Sharpe 0.92
v1.0 baseline 2358T 27.23%WR PF 1.195 Sharpe 0.545 Sortino 1.581 DD$451 $1.14/T
v2.0 order-2 Kalman 2131T 36.74%WR PF 1.163 Sortino 1.799 (REJECTED — velocity overshoots reversals on financial returns; WNA assumption violated)
v1.1 drop-Asian session 1428T PF 1.20 Sharpe 0.40 Sortino 1.108 DD$677 (REJECTED — sub-additive, DD +50%, Sharpe -27%)
v1.2 ADX(15) alone 1801T PF 1.248 Sharpe 0.638 Sortino 1.805 DD$497 $1.51/T
v1.2 Hurst(0.45) alone 2160T PF 1.221 Sharpe 0.561 Sortino 1.616 DD$480 $1.31/T (best absolute P&L of any single filter at $2,837)
v1.2 ADX(15)+Hurst(0.45) 1670T PF 1.282 Sharpe 0.631 Sortino 1.920 DD$396 $1.75/T
v1.2 ADX(15)+RSI(35)+Hurst(0.45) 1568T 27.87%WR PF 1.312 Sharpe 0.640 Sortino 2.215 DD$395 $1.95/T (PRODUCTION LOCK)
B&H 12-month return $3,901 — locked config captures 78.1% of B&H with 26% of B&H DD profile
Each filter cuts roughly proportional good and bad trades. The directional buckets exposed by the report (Asia Long PF 1.57, London 1.04, Long*LowVol 0.39) become diluted when implemented as filters because the underlying regime filter (P01) already removes much of the same loser population. Genuine filter independence requires the new filter to address losses NOT already addressed by regime filter, which is rare.
1. SIGNAL-DENSITY PRINCIPLE: Filter additivity vs sub-additivity is determined by signal-generator frequency, not by filter quality. Kalman flip generates 2358 raw signals/year on NAS100 5M; loose orthogonal filters can each prune the worst 5-15% tail without touching the core signal — strict additivity. GMAFLIP S01 generates 600 raw signals/year on same instrument/TF; even loose filters prune disproportionately into edge — sub-additivity. This explains the contradiction between the two experiments.
2. LOOSE THRESHOLDS WIN: ADX=15 (below 20 textbook), RSI=35 (below 50 neutral), Hurst=0.45 (below 0.50 random walk). Each catches only the worst tail of its dimension. Strict thresholds (ADX 25, RSI 50, Hurst 0.50) overfilter and reduce edge.
3. ORTHOGONALITY MATTERS: ADX measures strength of directional movement (directionless); RSI measures recent momentum direction (short window); Hurst measures long-memory persistence (regime). All three look at completely different properties — that's why their intersection contains higher-quality trades than any pair.
4. ORDER-2 KALMAN INFERIOR for financial series: White-noise-acceleration assumption is violated by jump-prone returns; velocity term overshoots at reversals, compressing R:R from 3.2 to 2.0. The simpler order-1 prediction (assume tomorrow=today, then correct) is more robust to non-stationary noise. Order-2 wins win rate but loses on PF/DD/Sharpe.
5. SESSION FILTERING SUB-ADDITIVE on this strategy too — dropping Asian session lost $606 P&L without improving PF, with DD +50% and Sharpe -27%. Asian's small wins were acting as DD buffer (correlation-smoothing across sessions).
6. LONG-ONLY STRUCTURAL for index: Both-direction mode bled $939 on shorts and triggered all 32 margin calls. NAS100's structural drift makes shorting sub-zero-expectancy.
7. INPUT PRE-FILTERING (close -> OHLC4) is a separate axis from indicator parameter tuning. Adds win rate at the cost of slight R:R compression. OHLC4 is the locked source.
GMAFLIP family fully exhausted on NAS100 5M. P01 (regime alone) is the operating point. Future variants must change the SIGNAL primitive (not stack more filters) to escape the sub-additivity wall — try GMAFLIP on 15M/1H, on a different symbol class (XAUUSD/BTCUSD), or replace slope-flip with a different trend primitive entirely (Hull/Kalman/Linreg).
1. Production-locked configuration ready for Trade_Scan port: 64_TREND_IDX_5M_KALFLIP_S01_V1_P00 with all three filters enabled at locked thresholds. All required indicators (kalman_filter, adx, rsi, hurst) already exist in repository per user; only the strategy directive YAML needs to be written.
2. Future research must classify the signal generator by frequency BEFORE designing filters. HIGH-frequency primitives (>1500T/yr) can stack 2-3 orthogonal loose filters. LOW-frequency primitives (<1000T/yr) should use a single strong regime filter and avoid stacking.
3. The signal-density principle should be tested on other HIGH-frequency strategies in the family to confirm it generalizes beyond Kalman/NAS100. Any flip-style strategy on liquid intraday TF is a candidate.
4. Per-trade $ +71% gain is the cost-survival headline. Strategy has substantial headroom against spread widening and would degrade gracefully under stress. Expect PF to hold above 1.20 even under 2x slippage stress (4 ticks vs 2).
5. Order-2 Kalman exploration is a closed branch for financial series. Future Kalman variants should explore: (a) different price sources (HLC3, HL2), (b) different timeframes (15m, 1h on NAS100), (c) different liquid index symbols (SPX, DAX). NOT order-2.
6. The full 24h baseline (no session filter) should be retained — session attribution is an artifact of trade-sequencing, not a source of independent edge.
---
---
---

---
2026-05-08 | Tags: IBREAK, consecutive_structure, XAUUSD, 5m, pine_port, short_regime_leak, H1_pass, H2_partial | Strategy: 66_BRK_XAUUSD_5M_IBREAK_S01_V1_P00 | Run IDs: 74e4d550c96d16940f584ee9
Pine consecutive_structure_v2_0 (3-HH/3-LL + ADX(10,Wilder) > 20 rising + structural stop + gap-safeguard) ports to OctaFX 5M with H1 survival (PF 1.24) but fails SQN quality gate (1.91 < 2.0). Short-in-uptrend is the primary structural leak; long-side and short-in-downtrend are sound. OctaFX P00 (2025-08-22 to 2026-05-07, 0.01 lots): 803T, PF 1.24, WR 36.6%, net $1,949, max DD $584. Pine baseline: OANDA 1,071T PF 1.319 WR 36.5%. WR near-identical; trade-count 25% lower (broker data differences). Top-5 concentration 57.4%; SQN 1.91; longest flat 83 days. 2025 sub-period PF 0.95 (452T, -$165) vs 2026 PF 1.46 (351T, $2,114). Direction x Trend breakdown: Short x StrongUp PF 0.47 (40T, -$238) and Short x WeakUp PF 0.78 (152T, -$366) are the primary loss clusters. Long x StrongUp PF 2.06 (96T, $735) is the strongest cell; Short x StrongDn PF 1.81 (91T, $732). Asia long dominates: PF 1.81 (149T). Short overall positive only in downtrend regimes (WeakDn PF 1.36, StrongDn PF 1.81). H1 PASS (PF 1.24 >= 1.10). H2 PARTIAL: non-StrongUp subset ~$1,453 net positive (74.5% of trades), but WeakUp short is the structural drag; strategy is NOT robust in rising markets for shorts. H3 PASS: architecture fully preserved (indicator separation, gap-safeguard, stage-0.56 warn confirmed). Quality gate FAIL: SQN 1.91 < 2.0 threshold, top-5 concentration too high, 2025 sub-period loss. The edge is real but regime-conditional — long works across regimes; short must be gated to downtrend context. P01: apply direction_gate to short branch — gate shorts to trend_regime <= 0 (Neutral/WeakDn/StrongDn only). This removes the Short x StrongUp (PF 0.47) and Short x WeakUp (PF 0.78) clusters. Expected: fewer trades but higher SQN and better tail concentration. Do NOT explore long-only variant before testing short-gated P01 — the short branch contributes $673 in valid downtrend contexts and is worth preserving conditionally. Age-2 exclusion (64T, -$27, PF 0.95) is a secondary probe, not a first priority. --- ---. --- ---. --- ---.
---

---
2026-05-16 | Tags: H2_telemetry, intrabar_DD_correction, methodology_correction, basket_sim_spec, legacy_module_deprecation | Run IDs: 515a6b81beb5bf5d00f0012d, d7e3a692c0d22ffc268aae9d, 1f6ee7227cf82c7b05aff660
Legacy h2_intrabar_floating_dd.py overstates basket Max DD by 5-35% due to state-model bugs (winner-lot reset to 0.01 on every realize, bar-0 vs bar-1 entry-price). Spec-correct 1.3.0-basket parquet emitter is now authoritative; legacy module flagged DEPRECATED. B1 forensic 2026-05-16: legacy reports Max DD $495 (49.5%); emitter reports $325 (32.5%) at a 113-day-different worst-bar (legacy=2025-06-03, emitter=2025-02-10). recycle_events.jsonl on disk shows top winner_realized $271.50 on EUR Δ0.02715 — implies actual lot 0.10, directly contradicting legacy's hardcoded 0.01 assumption. §3.7 of FX_BASKET_RECYCLE_RESEARCH.md DD numbers (B1 $495, AJ $529, GBP+JPY $947, composites) are overstated. The 1.3.0-basket per-bar parquet at TradeScan_State/backtests/<id>_H2/raw/results_basket_per_bar.parquet is authoritative going forward. Legacy module retained for replay of pre-1.3.0 baskets only. Re-derive composite DD and capital sizing from per-basket parquet ledgers before any live deployment decision. Phase 7 refactor of harvest_robustness module will rewrite reload+replay path to parquet-read and fix the two state bugs at the same time. Until then, ignore §3.7 absolute DD magnitudes; relative basket comparisons remain qualitatively valid. --- ---. --- ---. --- ---.
---

---
2026-05-21 | Tags: cointegration, correlation_conflation, screener_v1, COINTREV_retired, beta_weighting, cross_asset_universe | Strategy: 91_PORT_*_COINTREV_S01..S48 (retired)

COINTREV v1 strategy chain retired (commit 605317c) due to a cointegration/correlation conflation: the basket rule (cointegration_meanrev_v1.py) used equal-lot sizing rather than β-weighted sizing per the OLS hedge ratio the screener computed. Every COINTREV trade was therefore a directional bet weighted by whichever leg had higher dollar-volatility, not a spread trade. The P01 universe filter (mean_beta > 0, 0.10 < corr < 0.85) added in generate_cointrev_directives.py was a workaround that selected pairs where equal-lot ≈ β-weighted-lot — making the +$850 cohort total correlation-pair-trading dressed in cointegration language. The screener's ADF test was incidental to what was actually captured.
Quarantined: 98 directive admission records (49 .txt + 49 .admitted) to TradeScan_State/quarantine/20260521T032947Z_coint_v1_retirement/ with manifest. Deleted: cointegration_meanrev_v1.py, generate_cointrev_directives.py, cointrev_cohort_report.py, CointMeanRevLegStrategy, test files, COINTREV_meanrev registry entry, basket_data_loader auto-join. Stripped: TRADABILITY columns + correlation lookup from cointegration_excel.py (returned to pure cointegration view).
Output reports annotated: COHORT/CONCURRENCY = POLLUTED banner; EVENT_STUDY = methodology clean but actionable claim (37% qualified reversion → strategy worth backtesting) was tested with the wrong strategy and must be re-validated; PHASE_C0 + spec doc = retained-infrastructure note. Defer β-weighted v1.2 strategy build to future session if pursued; defer stocks-universe pivot indefinitely.
Same session: screener universe expanded from 18 FX → 21 symbols (XAU/BTC/ETH added; commit b8f4251). 210 pair-pairs total. First-run cross-asset BOTH-window cointegrated finds: BTCUSD/NZDJPY (p252=0.0015, p504=0.0210), GBPJPY/XAUUSD (p252=0.0135, p504=0.0437), EURJPY/XAUUSD (p252=0.0165, p504=0.0370). CHFJPY/XAUUSD one tick from BOTH at 504d (p=0.0531). Yen-cross / XAU cluster is economically intuitive (risk-off / inflation-hedge drivers); BTC/NZDJPY surprising and warrants follow-up sanity check.
Lesson: a cointegration screener is symbol-agnostic correct math; a cointegration STRATEGY must construct the cointegrating portfolio (β-weighted), not equal-lot. Adding a correlation-based filter on top is a confession that the strategy isn't honoring the underlying math. If a strategy filter looks like it's compensating for sizing error, it usually is.
---
---
---
---
---
---

---
2026-05-22 | Tags: H3_spread_v2, z_zero_exit, unsmoothed_cross, exit_timing, S16_probe, capital_efficiency | Strategy: 90_PORT_EURUSDUSDJPY_5M_PAIRX_S16_V1_P00 | Run IDs: c775cc8cdf27f1847537028d, b4c9e1ffd26c83e802eb33d0
Unsmoothed reverse-cross exit (cross_side_raw = sign(z_a - z_b), no SMA) on H3_spread@2 with macro filter is net-neutral on Net% vs S10 baseline while delivering structural cycle-hygiene improvements. Mechanism fires exits earlier as designed but the time-shifted exits trade saved adverse losses for missed harvest upside roughly 1:1. S16 vs S10 (EUR/USDJPY 5m, Window A 2024-05->2026-05, same params except reverse_cross_column): Net% 198.36 -> 190.59 (-7.77pp), DD 23.22 -> 23.24 (flat), Ret/DD 8.54 -> 8.20 (-0.34); WR 28.7 -> 34.5 (+20%), cycle PF 1.44 -> 1.47, time-in-position 23.2 -> 18.1 (-22%), total give-back 14157 -> 11573 (-18.2%); ADVERSE_STOP exits 192 -> 145 (-24.5%), REVERSE_CROSS exits 114 -> 164 (+44%), scale-to-core events 111 -> 94 (-15%), pyramids 776 -> 705 (-9%). The unsmoothed signal IS firing reverse-cross exits earlier as theorized (47 fewer adverse-stop cycles, lower give-back, lower time-in-position prove the mechanic works). But on Net% the saved adverse losses are offset by 17 fewer cycles reaching full-harvest territory (cycles that would have generated higher PnL got reverse-crossed at lower MFE instead). Capital-efficiency improved (same Net with 22% less time deployed); raw Net% did not. z=0-style faster reverse-cross is not the lever for further Net% gains on this strategy. The next refinement axis should target the multi-leg-capture phenomenon (h3_spread@3 high-z exit + re-entry) which addresses cycles ending too early in long macro-aligned trends - a DIFFERENT failure mode than the residual-give-back z=0 was designed for. Keep cross_side_raw infrastructure (committed c8e400a + f12abe0) for future probes (deadband / hysteresis exit variants). For deployment, S10 V1 P00 remains the baseline; S16 is a capital-efficiency variant worth retaining as a research peer but not the headline winner. --- ---. --- ---. --- ---.
---

---
2026-05-22 | Tags: H3_spread_v3, multi_leg_capture, extreme_z_exit, armed_for_reentry, deployment_baseline, timeframe_15m, entry_delay_8, cross_window_validated | Strategy: 90_PORT_EURUSDUSDJPY_15M_PAIRX_S21_V1_P06, S21_V1_P07, S21_V1_P08 | Run IDs: 0e2ee38a33cc56e64d85913e, 0c22ea3accce3d3a94556b57, 176918c50512ada558517a89
H3_spread@3 with extreme_z=5.0 + reentry_z=1.0 + 15m TF + entry_delay_bars=8 is the NEW cross-window deployment baseline for EUR/USDJPY, replacing 5m @2 d=12. @3 architecture (commits c8e400a + f12abe0 + faecf6b + 6344753 + fa0f18e + ed40845 + 246bb7d + 7166970): inherits all @2 mechanics + adds extreme-z take-profit exit (cycle_dir*diff > 5.0 -> LIQUIDATE_EXTREME_Z) + ARMED_FOR_REENTRY phase (after EXTREME_Z exit, re-enter when 0 < cycle_dir*diff < 1.0 AND macro+cross still aligned; abort on flip; max 3 re-entries per regime). All @3 params default off -> byte-equivalent to @2 (regression-tested in test_h3_spread_v3.py). Calibration sweep summary (Window A): e=2.0 +58.52%, e=3.5 +93.10%, e=5.0 +205.67% (winner), e=6.0 +210.52%, e=7.0 +193.64% -- e=5.0 robust on Windows A+B; e=6.0 wins A by noise but loses B. Cross-window 5m @3 e=5.0 d=12: Win A +205.67%, Win B +192.91%, Win C -148.74%. Cross-TF 15m @3 e=5.0 d=12: Win A +162.66% (worse), Win B +227.18% (better) -- window-dependent. Entry-delay sweep: 5m+d=4 +230.54 wins Win A but +144.10 fails Win B; 15m+d=8 wins BOTH (Win A +218.21 / 18.71 DD / 11.66 RetDD; Win B +225.94 / 20.79 DD / 10.87 RetDD; Win C -112.21 / 107.95 DD = bounded improvement vs @2 -129.98). Final deployment baseline 15m+d=8+@3 e=5.0 r=1.0 vs prior 5m @2 d=12: Window A +20pp Net% / +37% RetDD; Window B +70pp / +81%; Window C bleed reduced 18pp / DD -16.4pp. Window C still requires operator regime gate (same posture as @2). 5m+d=4 retained as Window-A-only research peer; 5m @2 baseline retained for replay. Open question for future session: programmatic regime detector for Window C-like environments (correlation health + intra-macro coherence + macro-flip frequency) to flip "regime-conditional + manual gate" to "regime-tolerant + automated". ---. --- ---. --- ---.
---

---
2026-05-24 | Tags: COINTREV_v1_2_retired, daily_tf_negative, regime_degradation_dominates, beta_sizing_variance, screener_signal_weak, thesis_failed | Strategy: cointegration_meanrev_v1_2 | Run IDs: 8085fb37d7d42d760328ced2, bba65573c6f31f5e02d3aac3, e97b6a785d33f6df82954b8d, 182df4cd1500e5b611276ea0
COINTREV v1.2 retired after daily-TF retest decisive negative on 5 best-performing IDX-IDX pairs from prior 15m pilot. The mean-reversion thesis does not survive realistic exit mechanics on daily TF; the 15m wins were 15-hour time-stop truncating noise, not signal edge. Daily-TF 5-pair cohort: 1 winner (JPN225/SPX500 +1.26%), 4 losers (mean -1.50%). Same pairs on 15m TF: 5/5 positive (mean +0.60%). 14/22 cycles exit via regime degradation (cointegration relationship breaks down before mean-rev completes); 8/22 via mean-rev; 0/22 via time-stop. EUSTX50/UK100 flips +1.73% (15m) -> -6.59% (1d) with all 4 exits regime-driven. Cointegration_triggers signal carries unstable relationships -- the screener's regime classifier flips cointegrated->breaking/broken faster than mean-reversion completes on most pair-pairs. The 15m wins observed in the pilot were sizing+truncation artifacts, not real edge. The strategy thesis (beta-weighted mean-reversion on screener triggers) does not work at v1.2 base on either 15m or daily TF across FX-FX or IDX-IDX cohorts. Do NOT re-explore v1.2.x parameter sweeps (sizing, exit_z, time_stop_bars) -- no parameter setting will manufacture edge a weak signal does not carry. Do NOT re-explore the 263-pair blanket cohort framing. Three follow-on arcs remain viable if revisited: (1) same-region intuitive pair selection with longer min_gap + earlier mean-rev exit (small cohort, 1 session); (2) signal-side classifier predicting mean-rev vs regime-deg outcomes (research arc); (3) different strategy class on the trigger ledger (trend-following on breakdown). The screener infrastructure + CointTriggerLegStrategy + universal cross-asset PnL helpers + two-bar leg-rule protocol are reusable; preserve. See REPORT_pilot_2026-05-24.md addenda 1-5 for full forensic. SUPERSEDED BY 2026-05-24 leg_direction_flip_bug entry below -- retirement basis under review pending engine-flow investigation. --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-24 | Tags: leg_direction_flip_bug, signal_sign_dropped, basket_engine_flow, v1_2_retirement_invalidated, pine_zrev_v1_artifact, base_direction_only, structural_engine_bug, H3_spread_bidirectional_at_risk | Strategy: pine_ratio_zrev_v1 + cointegration_meanrev_v1_2 | Run IDs: d0eff0a9465289355f4ec932, 2fac3127e8f0cf6f1e7e6f20, 8099400b3bf78240225ae417, 93375b57c63ef1b672c0e25f
Basket leg directions DO NOT FLIP across cycle reversals in either pine_ratio_zrev_v1 (Pine port, built this session) or cointegration_meanrev_v1_2 (just-retired). Every observed cycle opens in BASE direction (= leg.direction loaded from directive YAML). The shared "signal = position_direction * proposed_direction" pattern in CointTriggerLegStrategy / PineZRevLegStrategy is not honored by the engine on open -- the leg opens per leg.direction regardless of signal sign. Empirical evidence: today's Pine port runs on CHFJPY/UK100 and EURJPY/US30 show 23/24 (CHFJPY) and 20/21 (EURJPY) trades in BASE direction despite 23 and 20 reversals counted respectively. Even more conclusively, three sampled retired v1.2 runs (90_PORT_AUDUSDGBPJPY_15M, 90_PORT_EURGBPGBPJPY_15M, 90_PORT_AUS200SPX500_1D) show 100% BASE direction (e.g., AUDUSD: 11/11 +1, GBPJPY: 11/11 -1) -- zero SHORT_SPREAD cycles ever activated across the entire v1.2 pilot + daily retest. Implication 1: the v1.2 retirement verdict (preceding entry) was drawn from data where the strategy wasn't actually testing mean-reversion -- it was testing "always-long-BASE-spread with occasional liquidate-and-reopen-same-direction". The "regime_degradation_dominates" conclusion reflects "BASE-direction directional bet on cointegrated pair didn't work", not "mean-reversion didn't work". The cointegration mean-reversion thesis has NOT been rigorously falsified; v1.2 retirement basis is invalidated pending re-test after fix. Implication 2: Pine port pipeline results from today (CHFJPY/UK100 v1.1 +270%/82% DD, EURJPY/US30 v1.1 -352% blowup, plus the v1.0 lot-equal versions) are BASE-direction directional-bias artifacts, NOT edge measurements. The strategy was effectively just "long CHFJPY + short UK100 / long EURJPY + short US30, scaled by 0.07/0.07 or 0.08/0.02 lots". CHFJPY/UK100 +270% = base orientation happened to be favorable over 9 years; EURJPY/US30 -352% = base orientation was unfavorable. Do NOT cite the +270% as Pine port validation, and do NOT cite the -352% as EURJPY/US30 cointegration failure. Implication 3: H3_spread bidirectional mode (cross_watch_direction=0 in SpreadCrossLegStrategy) likely affected by the same engine-flow bug -- the Active Charter h3_spread regime detector V3 probe runs in this mode and may also produce direction-bias artifacts. Worth verifying before any further H3 work. Implication 4: 4 MPS Baskets rows in Master_Portfolio_Sheet.xlsx today (run_ids in header) are direction-bias artifacts -- mark them as such in any portfolio analysis. Next-session investigation: trace engine code path from leg.check_entry returning {"signal": +/-1} to leg.state.direction being assigned at engine fill. Target files: engine_dev/universal_research_engine/v1_5_8/execution_loop.py and tools/basket_runner.py open-position path. Hypothesis to confirm or kill: engine uses leg.direction (BASE from YAML) directly on open and ignores signal sign. Fix candidate: mutate leg.direction in rule's _maybe_approve before the engine fills, mirroring v1.2's existing leg.lot mutation pattern (which DOES propagate to the open). After fix: re-run one v1.2 directive (e.g., EUSTX50/UK100 1D) to confirm SHORT_SPREAD cycles now activate; if v1.2 verdict changes, the cointegration thesis re-test becomes a real research arc. --- ---. ---. --- ---. --- ---.
---

---
2026-05-24 | Tags: leg_direction_flip_bug_FIXED, basket_pnl_accounting, SHORT_SPREAD_sign_inversion, v1_2_retirement_invalidated_2, EURJPY_US30_resurrected, CHFJPY_UK100_dd_revealed, pine_ratio_zrev_corrected, cointegration_meanrev_v1_2_corrected | Strategy: pine_ratio_zrev_v1 + cointegration_meanrev_v1_2 | Run IDs: 1ddacbb81cfc6c8b39c780c9, 165dac969aa5e9957c521306
leg_direction_flip_bug fix landed — the bug was rule-side accounting (NOT engine open-path as previously hypothesized). _leg_pnl_usd_universal + _liquidate + _emit_record all read leg.direction (YAML BASE) instead of leg.state.direction (engine's actual cycle direction). Engine correctly opens at signal sign (evaluate_bar.py:355,363 state.direction = pe_signal['signal']); rule then sign-flips PnL on every SHORT_SPREAD cycle. Fix mirrors h3_spread_v2's BASKET_OPEN workaround (sync leg.direction = leg.state.direction once at open) — applied to pine_ratio_zrev_v1 and cointegration_meanrev_v1_2 only. Three reruns confirm impact: CHFJPY/UK100 v1.1 +270%/DD-82% → +335%/DD-335% (DD was masked by sign-flip); EURJPY/US30 v1.1 -352% blowup → +234%/DD-83% (was NEVER a blowup); EUSTX50/UK100 v1.2 -6.59% → +6.59% literal sign-flip (100% SHORT_SPREAD cycles in 4 trades). Per-bar parquet leg_X_side now varies per cycle (was stuck on BASE). 127 recycle-rule tests pass including 2 new regression tests mirroring test_v2_bidirectional_mutates_leg_direction_on_open. Bug fix is byte-equivalent for LONG_SPREAD cycles (state.direction == leg.direction) and corrects accounting for SHORT_SPREAD cycles. Pine z_r v1.1 CHFJPY/UK100 is worse than the +270% headline (true DD -335%); EURJPY/US30 is BETTER than blowup (+234% real edge). v1.2 retirement basis is INVALIDATED for the second time — the original retirement reading was the sign-flipped equity, which is the inverse of true performance on SHORT-dominant cycle cohorts. H3_spread (deployment baseline) UNAFFECTED — workaround already in h3_spread_v2 and inherited by h3_spread@3. DO NOT cite pre-fix Pine z_r / v1.2 / v1 equity numbers in any analysis — they're sign-flipped on SHORT cycles. Re-run any retired or actively-cited basket directive that uses pine_ratio_zrev_v1 or cointegration_meanrev_v1_2 BEFORE making any strategic decision based on its numbers. The retired v1.2 cohort (5 daily-TF pairs cited in 2026-05-24 retirement entry) is the priority re-evaluation. Architectural cleanup deferred: helper-level fix in _leg_pnl_usd_universal/_leg_pnl_usd_fx to read state.direction directly is preferred long-term; current Option-A workaround is minimal-blast pragmatic landing. The hypothesis in the 2026-05-24 leg_direction_flip_bug entry was partially wrong (engine open-path is correct); the bug was rule-side. Future bug investigations: read the actual code path before drawing engine-vs-rule conclusions from trade-ledger pattern alone. --- ---. ---. --- ---. --- ---.
---

---
2026-05-24 | Tags: v1_2_cohort_re_evaluation, 5_pair_daily_TF, retirement_basis_invalid, SHORT_cycle_distribution, cointegration_mean_rev_thesis_NOT_falsified | Strategy: cointegration_meanrev_v1_2 | Run IDs: eb07c30c8361d13bac8468a6, 165dac969aa5e9957c521306
v1.2 retirement cohort (5 daily-TF pairs) re-evaluated post-fix. Pre-fix verdict 1/5 winner (mean -1.49%) was reading sign-flipped equity. Post-fix verdict 3/5 winners (mean +1.07%) — cohort flipped from net-negative to net-positive. EUSTX50/UK100 and FRA40/JPN225 had 100% SHORT_SPREAD cycles and sign-flipped exactly. EUSTX50/FRA40 had 0 SHORT cycles (5 LONG) and post-fix matches pre-fix identically — confirms bug only affected SHORT cycles. Per-pair pre vs post net%: AUS200/SPX500 -0.39% to -0.81% (mixed 2L/5S), EUSTX50/FRA40 -1.15% to -1.15% (5L/0S, no change as expected), EUSTX50/UK100 -6.59% to +6.59% (0L/4S, exact sign-flip), FRA40/JPN225 -0.61% to +0.61% (0L/3S, sign-flip), JPN225/SPX500 +1.26% to +0.12% (3L/1S, partial change). Total trades per pair 6-14 (too small for statistical significance). Mean DD% post-fix: -3.22 (was -4.06%). v1.2 retirement basis is INVALID. The 'regime_degradation_dominates' conclusion was based on equity that was sign-flipped on every SHORT_SPREAD cycle. Post-fix cohort shows slight POSITIVE mean (+1.07%) instead of negative — the cointegration mean-reversion thesis has NOT been rigorously falsified. However, sample size (3-7 trades per pair) is too small to confidently re-validate either. The signal-quality concern (cointegration triggers carry unstable relationships) is partially supported by the post-fix mean still being small magnitude — the strategy doesn't show strong edge even with correct accounting. v1.2 should be RE-OPENED as an active research arc, not retired. Next steps if pursued: (1) Expand cohort to all pairs the screener produced triggers for (not just the 5 best from prior 15m pilot), (2) Use longer test windows (multi-year, not 1-year), (3) Categorize by SHORT-cycle vs LONG-cycle pair to see if one class has edge. DO NOT delete the v1.2 strategy code or quarantined directives — they're the foundation for any re-evaluation. The 2026-05-24 retirement entry should be marked SUPERSEDED in RESEARCH_MEMORY going forward, not deleted. Future basket research: any new rule MUST include test_basket_open_syncs_leg_direction_to_state_direction-style regression coverage from day 1, OR delegate PnL/exit handling to inherited h3_spread_v2 BASKET_OPEN block that already handles this. --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-24 | Tags: leg_direction_flip_bug_OPTION_B, architectural_fix, effective_direction_property, workaround_residual_bug, h3_spread_bidirectional_corrected, entry_bar_pnl_sign_flip, immutability_invariant | Strategy: BasketLeg + recycle_rules family | Run IDs: commit_ac14d1e
Option B architectural fix landed (commit ac14d1e). BasketLeg gains an effective_direction property that returns state.direction when in_pos (signed) else falls back to YAML BASE leg.direction. All 19 cycle-aware reads in 9 rule files now use effective_direction. Three BASKET_OPEN workarounds removed (pine_ratio_zrev_v1, cointegration_meanrev_v1_2, h3_spread_v2). Invariant guard test catches future workaround attempts that try to mutate leg.direction. Option B caught a residual bug in the Option-A workaround pattern: the leg.direction mutation ran at BASKET_OPEN AFTER the bar's floating PnL was already computed in the same apply() call. Every SHORT-cycle entry bar had sign-flipped PnL even with the workaround. Byte-equivalence verification: pine_ratio_zrev_v1 CHFJPY/UK100 and cointegration_meanrev_v1_2 EUSTX50/UK100 final equity IDENTICAL (entry-bar error magnitude was tiny vs liquidation-realized PnL). H3 bidirectional MATERIALLY different: h3_spread_v3 PAIRX S22 Window A went +25.32% (Option A) to +57.45% (Option B) because pyramid mechanic amplifies entry-bar PnL error into compounding pyramid-decision divergence. Bar 212 (first BASKET_OPEN) floating sums to exactly 0.0000 USD between Option A and B runs (exact sign flip confirms hypothesis). 214 tests pass including 5 new invariant-guard tests. Option B is architecturally correct AND more numerically correct than Option A. Pine and Coint results from earlier today (E003/E001 reruns) remain valid at headline-equity level. H3 bidirectional results are SLIGHTLY off in all prior runs that used h3_spread_v2 (pre-this-session and post-Option-A-fix today) because the v2 workaround was placed AFTER the per-bar PnL computation. The h3_spread@3 EUR/USDJPY 15m d=8 e=5.0 r=1.0 deployment baseline (locked 2026-05-22 per SYSTEM_STATE Manual) needs re-running under Option B; the prior +218%/19% / +226%/21% / -112% Window-A/B/C numbers are quantitatively wrong though directionally likely similar. (1) Use leg.effective_direction in any new basket rule code. (2) NEVER mutate leg.direction post-init (invariant guarded by test_leg_direction_immutable_through_short_spread_cycle). (3) The h3_spread@3 deployment baseline numbers in SYSTEM_STATE Manual are now stale and must be updated after re-run (in progress task). (4) When designing per-bar PnL flows in basket rules, place any direction-aware state mutations BEFORE the PnL computation in apply() OR rely solely on the engine's state.direction reads via effective_direction. (5) Architectural lesson: a workaround that fixes an observable symptom (post-liquidation PnL) but doesn't fix the root cause (effective_direction = state.direction always) can leave residual bugs in adjacent code paths. --- ---. ---. --- ---. --- ---.
---

---
2026-05-25 | Tags: H3_rehabilitation_batch, leg_direction_flip_bug_OPTION_B_correction, supersession_lineage_established, bidirectional_pyramid_pnl_correction, methodology_correction | Strategy: 90_PORT_EURUSDUSDJPY_*M_PAIRX_S*_V1_P*__E001 | Run IDs: batch=h3_bidir_core_rehab_20260525; key examples 140ce5e37bf54586b81cd97d (S20 P01 15M), 6654e5f2551d9340edfd4fbe (S21 P04 15M), 17cdb8cc51bca4901b2551a1 (S22 P00 5M)
Rehabilitated 22 CORE-visible bidirectional pre-fix H3_spread rows under Option-B entry-bar PnL accounting. Frozen evaluator (sha256=124f42978b92) enforced consistent evidence chain across manifest generation, sibling validation, and tagging. All 22 reruns dispatched sequentially in alphabetical order with stop-on-failure gate; 22/22 PASS, no halts. Restoration from git (.txt.admitted markers were empty on disk for older directives) preserved canonical directive content with per-file commit SHA + blob SHA-256 provenance in restoration_manifest.json. Evidence: MPS Baskets state before/after: visible CORE/WATCH 105 -> 83 (-22), SUPERSEDED 40 -> 62 (+22), total 311 unchanged. Net% delta range -22.4 to +52.6 (S21 P00 biggest gain; S21 P03 biggest loss). Largest Net% jumps: S21 P00 +52.6pp, S21 P04 +42.4pp, S22 P00 +43.1pp, S17 P03 +41.1pp. Verdict transitions: 20 CORE->CORE, 2 CORE->FAIL. The S06 P00 case is methodologically significant: headline Net% IMPROVED (+24pp to 268.00) but verdict flipped to FAIL — secondary governance metric exposed instability the pre-fix sign-flipped accounting was masking. Remaining unresolved bidirectional rows: 0 CORE / 1 WATCH / 28 FAIL — gate met (no visible CORE has sign-flipped accounting). Conclusion: Pre-Option-B vs post-Option-B bidirectional H3_spread accounting can flip verdict classifications even when headline Net% looks similar or improves. The entry-bar PnL re-accounting in the pyramid mechanic is material — not cosmetic. The leg_direction_flip_bug (originally diagnosed as a one-line accounting fix) had cascading impact on cycle-level PnL distribution, quality metrics, and verdict classification. Validating only headline equity post-fix is insufficient; every quality gate must be re-evaluated. The S06 P00 -> FAIL transition is the strongest evidence the rehabilitation was not cosmetic: a pre-fix CORE row whose post-fix Net% IMPROVED still failed governance, meaning the old accounting was hiding structural weakness. Implication: (1) Future bidirectional basket-rule changes MUST trigger full rehabilitation pass on prior CORE/WATCH rows, not just spot-check headline equity. (2) basket_id BIDIR/BEAR/BULL suffix is convention-only — worth formalizing as registry constraint so future rules cannot ambiguously declare direction mode. (3) Empty .txt.admitted markers (older directives only recoverable from git history) are operational debt — admission tooling should preserve canonical content somewhere persistent or document the git-as-source-of-truth contract. (4) Forensics workspace preserved at tmp/rehabilitation_batch_20260525/ with full per-row provenance: restoration_manifest.json (22 git commits + blob SHA-256), dispatch_log.jsonl (22 PASS records with run_ids), reconciliation_report.md (frozen evaluator verification), final_reconciliation.md (before/after state). DO NOT delete this workspace — it is the audit trail for this methodology correction. --- ---. --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-25 | Tags: H3_rehabilitation_phase2, leg_direction_flip_bug_OPTION_B_correction, triage_classification_sensitivity, bidirectional_pyramid_pnl_correction, supersession_lineage_phase2 | Strategy: 90_PORT_EURUSDUSDJPY_*M_PAIRX_S*_V1_P*__E001/E002 | Run IDs: batch=h3_bidir_phase2_rehab_20260525; key flips S20_P00=fff5e7..., S21_P01=2b5fff... (verdict transitions WATCH->CORE and FAIL->CORE)
Phase-2 follow-on rehabilitation rebuilt 16 of 29 remaining bidirectional pre-Option-B rows (1 WATCH + 15 near-threshold FAIL with positive Net% and DD < 50). Triage explicitly skipped 13 rows where corrected entry-bar PnL accounting could not plausibly change governance outcome (DD too high, catastrophic loss, or below-threshold-by-far). Same frozen evaluator (sha256=124f42978b92) and provenance-preserving workflow as Phase 1. 16/16 reruns PASS, 16/16 evidence chain PASS, 16 originals tagged SUPERSEDED via frozen evaluator. Verdict transitions: 1 WATCH->CORE (S21 P01: Net% 144.10->179.41, DD 43.44->36.13), 1 FAIL->CORE (S20 P00: Net% 162.66->168.46, DD 30.91->28.22), 14 FAIL->FAIL despite Net% shifts up to +64pp (S17 P00 58.52->122.73, S17 P01 93.10->130.84, S19 P00 116.87->146.87, S22 P00 25.32->57.45). MPS state: visible CORE/WATCH 85->84, SUPERSEDED 62->78, total 327 rows append-only honored. Remaining unresolved bidirectional pre-fix: 0 CORE / 0 WATCH / 13 FAIL (all triage-skipped); GATE MET (no visible CORE/WATCH has sign-flipped accounting). Triage heuristic (positive Net% AND DD < 50 -> dispatch) was effective signal selection: 14/16 stayed FAIL despite re-accounting because the FAIL was structural (quality-gate failure resistant to small per-cycle PnL deltas), but 2/16 flipped to CORE — the directionally rare cases where re-accounting crossed a verdict threshold. Brute-force rerun of the 13 triage-skipped rows would not have produced additional verdict flips (DD too far above gate, loss too large to recover). The S17 P00 case is methodologically notable: Net% nearly doubled (58.52 -> 122.73) but verdict held at FAIL, proving that headline Net% improvement alone does not guarantee governance flip — secondary quality gates can be the binding constraint. Combined Phase 1 + Phase 2: 49 H3 bidirectional pre-fix rows rehabilitated under correct entry-bar PnL accounting (5 originally proven + 22 CORE-batch + 16 phase-2 + 6 H3 still in original triage); 0 CORE/WATCH bidirectional pre-fix rows remain with sign-flipped accounting. (1) For future bidirectional-rule supersession passes, the triage heuristic (verdict-driving metric polarity + distance from threshold) is the right pre-filter to avoid brute-force replay cost. (2) The 13 triage-skipped FAIL rows can remain visible-as-FAIL because they have no rehabilitation upside; do not quarantine without replacement lineage. (3) Phase 1 + Phase 2 workspaces preserved at tmp/rehabilitation_batch_20260525*/ — full audit trail for the H3 leg_direction_flip_bug correction (49 superseded run_ids documented). (4) Two CI guard tests (test_quarantine_integrity.py + test_basket_id_convention.py) now prevent future similar bug classes: untagged superseded rows + ambiguous bidirectional declarations. --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-25 | Tags: directive_admission_sentinel, orphan_marker_cleanup, lineage_pruner_sidecar_pairing, recover_admitted_directive_tool, pipeline_state_cleanup_followup | Strategy: infrastructure | Run IDs: commits=0933560, fad4695, 081dbbc, 4a26c4a, f75462a
Resolved the directive .txt.admitted operational-debt root cause flagged in the 2026-05-25 H3 rehab batch. Admission (run_pipeline.admit_directive) creates .txt + a separate 0-byte .admitted sentinel via marker_path.touch() — content is never truncated. The 2026-05-22 pipeline-state-cleanup (1317fba) globbed *.txt only and quarantined 274 directive .txt files without their .admitted siblings, leaving 433 orphaned 0-byte markers in completed/ that looked like truncated files. Fix landed in 5 atomic commits: lineage_pruner sidecar-tuple pairing, one-shot sweep tool with sha256 manifest, recover_admitted_directive (live→quarantine→git with --json provenance), and dead .txt.admitted fallback removal in generate_strategy_card. Pre-fix state: 542 .admitted markers in completed/ (100% empty, 433 orphans). Post-fix: 123 .admitted (100% paired, 0 orphans). Recovery byte-equivalence verified: recover_admitted_directive on 90_PORT_EURUSDUSDJPY_5M_PAIRX_S15_V1_P03 returned sha256 4e47b993a120274676c806d8ce5ed62c1d7dc45cc5f00653e10b3a45b2c9a3f9 from quarantine, byte-identical to manual git recovery in H3 rehab restoration_manifest.json. 25 regression tests added (5+7+13), all pass; 70/70 gate suite green across all 5 commits; second --execute idempotent. Sweep manifest archived at outputs/system_reports/10_State Lifecycle Management/2026-05-25_admitted_orphan_sweep_manifest.json (203 KB, 433 entries). Admission code was never the bug. The actual defect was the cleanup tool's sidecar-blind glob — easy to miss in review because .admitted files are 0-byte sentinels with no information value, but their absence-as-pair confused future readers into thinking content was lost. Two-source recovery (quarantine + git) is now a first-class tool with provenance, not tribal knowledge. The fossilized .txt.admitted size>10 fallback in generate_strategy_card._find_directive was actively harmful as documentation — it perpetuated the ambiguity about canonical source. (1) Configurable DIRECTIVE_SIDECAR_SUFFIXES tuple in lineage_pruner: adding future sidecars is one line, plumbed through scan + quarantine automatically. (2) Manifest schema (orig_path, quarantine_destination, size_bytes, mtime_utc, sha256) makes state-changing sweeps deterministically reconstructable — replicate in other cleanup tools. (3) recover_admitted_directive --json mode makes governance automation possible; no more manual git log walking for routine recoveries. (4) When investigating any 'missing' directive: ALWAYS run python tools/recover_admitted_directive.py <ID> before assuming data loss. (5) Dead defensive branches that hint at non-canonical sources should be removed, not left as 'no harm' — they perpetuate misconceptions that surface as expensive rehab batches later. --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-25 | Tags: terminal_closure, archived_unresolved_governance_state, triage_skip_classification, no_replacement_lineage_policy, H3_phase2_closure | Strategy: 90_PORT_EURUSDUSDJPY_*M_PAIRX_S*_V1_P* (+GBPUSDUSDJPY +AUDUSDUSDCAD subset) | Run IDs: batch=h3_bidir_phase2_archived_unresolved_20260525; 13 directives; evaluator_sha256=124f42978b92
Closed 13 triage-skipped FAIL rows from the leg_direction_flip_bug Phase-2 rehabilitation as terminal ARCHIVED_UNRESOLVED governance state. Distinct from SUPERSEDED (no replacement lineage exists). Rows remain visible-as-FAIL internally but are excluded from all active research/ranking views by default via the existing quarantine_status.notna() filter that the formatter, cointrev_v1_2_aggregator, and h2_parity_run already enforce. Frozen evaluator re-verified each row was still unresolved (no sibling appeared since phase-2 close) before tagging; 13/13 confirmed, 0 drift. Triage class distribution: 1 catastrophic_dd (S06 P01: Net% +3.96 but DD 94.91), 6 modest_loss (Net% -34 to -91, DD 61-103: S13 P02, S09 P00, GBPJPY S11 P00, S22 P05, AUDCAD S12 P01, S14 P02), 6 catastrophic_loss (Net% -123 to -152, DD 119-220: S07 P01, S11 P01, AUDCAD S12 P00, S08 P02, S10 P02, S18 P01). Per-row metadata in MPS: quarantine_status=ARCHIVED_UNRESOLVED, quarantine_reason carries verbatim triage rationale + closure preamble, superseded_by_run_id=NULL (explicitly distinguishing from SUPERSEDED). Forensic manifest at tmp/rehabilitation_batch_20260525_phase2/archived_unresolved_manifest.json records the closure transaction with timestamps and class assignments. These 13 rows are consciously closed as low-value rehabilitation candidates, not forgotten debt. The corrected entry-bar PnL accounting magnitude (small per-cycle, bounded by pyramid mechanic) cannot realistically cross any governance threshold given their initial state: catastrophic DD already 90+%, large structurally-negative expectancy, or both. Brute-force replay would consume compute without producing actionable lineage changes. The ARCHIVED_UNRESOLVED governance state preserves append-only semantics, makes the closure rationale discoverable from MPS row metadata itself (quarantine_reason field), and integrates with existing view/aggregator hide-passes that filter on quarantine_status.notna(). (1) Future operators inspecting these directives should treat the ARCHIVED_UNRESOLVED tag as terminal CLOSURE, not pending work. (2) Reruns are NOT authorized unless a future methodological change materially alters the expected outcome space (e.g., a new quality-gate weighting that could lift catastrophic-DD rows, or a structural rule fix that changes loss characteristics). (3) When introducing a NEW quarantine_status value in future cleanups, follow the same pattern: distinct from SUPERSEDED (replacement) and RETIRED (rule-level), carry a quarantine_reason that documents the rationale verbatim, and confirm the existing aggregator/formatter notna() filter is sufficient (or extend it if needed). (4) Combined Phase-1 + Phase-2 + Phase-2-closure totals: 49 H3 bidirectional pre-fix rows superseded (with replacement lineage) + 13 archived (terminal, no replacement) = 62 total governance-finalized rows under the leg_direction_flip_bug correction. (5) The CI guard test_quarantine_integrity.py PASSes with ARCHIVED_UNRESOLVED tagging — same column, same notna() filter contract; no test update needed. ---. --- ---. --- ---. --- ---.
---

---
2026-05-28 | Tags: cointegration_join_viability, B_window_gate_redirector, cohort_shift_index_crosses, methodological_validity_not_edge, post_enforcement_reinterpretation, coint_span_survey | Strategy: cointegration_meanrev_v1_2 | Run IDs: survey=coint_span_survey_2026-05-28; ref=cointegration_daily@as_of_2026-05-28; gate_commit=5b954bc
Post-enforcement read-only survey of the full 465-pair cointegration_daily universe (reusing Task B's exact span logic; no DB mutation) reinterprets the entire cointegration branch: cointegration-join is VIABLE but for a minority cohort structurally different from the FX-major pairs previously tested -- the B window-validity gate is a REDIRECTOR, not a blocker. Evidence (lookback=252, 1d): 123/465 pairs (26%) have a LATEST continuous cointegrated span >=30 obs (admissible through B now), 14 (3%) >=90, only 23 (5%) never cointegrated, 253 (54%) longest-ever >=30; top CURRENT candidates are index-crosses (EURUSD/GER40 150 obs ongoing->05-27, GBPJPY/UK100 135 ongoing, ESP35/GBPJPY 117) NOT the tested FX majors (EURUSD/USDJPY broken 94%, AUDJPY/AUDNZD 22% but fragmented across 8 spans). Conclusion: the prior weak/negative cointegration verdict tested the WRONG pairs -- durable cointegration concentrates in index x index and index x JPY/CHF crosses, not FX majors; B's apparent strictness is correct redirection toward the ~26% of pairs whose precondition actually holds; the tiny spans on the tested pairs are honest deterministic data (a screener rerun reproduces them exactly), not a gate artifact. Implication: PRESERVE THE DISTINCTION span-validity = METHODOLOGICAL cleanliness (the cointegration precondition holds across the window), NOT profitability -- these are clean test candidates not winners, never cite span length as edge; historical broad-window results should be treated as EXPLORATORY unless revalidated under B-compliant windows. Next operational/research session: run disciplined clean-window backtests [span_start->today] on the ~7 currently-cointegrated L252 candidates (EURUSD/GER40, GBPJPY/UK100, ESP35/GBPJPY, CADJPY/FRA40, CADJPY/UK100, CADJPY/ESP35, UK100/USDJPY) under the hardened methodology. Do NOT widen the survey (strategic question answered); survey script preserved at tmp/coint_span_survey.py (read-only, re-runnable). --- ---. --- ---. --- ---. --- ---.
---

---
2026-05-29 | Tags: cointegration_corpus, pair_class_edge, FX_FX_favorable, IDX_IDX_favorable, FX_IDX_cross_hostile, corpus_n335 | Strategy: pine_ratio_zrev_v1 (COINTREV_V3 episode corpus) | Run IDs: cointegration_sheet is_current=1 n=335 as_of 2026-05-29 (tools/cointegration_aggregator.py)
FX-FX and IDX-IDX are the favorable cointegration pair-classes while FX-IDX cross is hostile, confirmed at full 335-episode corpus scale (pine_ratio_zrev_v1 / COINTREV_V3). n=335: FX-FX n=88 62% pos, net% mean +1.6, ret/dd 0.66, 0 blowups; IDX-IDX n=39 54% pos, +2.1, rdd 0.51, 2 blowups; FX-IDX n=148 44% pos, -2.4, rdd 0.21, 22 blowups; CRYPTO/METAL n=60 55% pos, 23 blowups. The pine_ratio_zrev_v1 cointegration edge concentrates in same-asset-class pairs (FX-FX cleanest with zero blowups; IDX-IDX modest positive); cross-class FX-IDX is structurally hostile and CRYPTO/METAL is high-variance. Corroborates the earlier pine_n30 FX-FX/IDX-IDX-favorable, CROSS-hostile finding at full corpus scale. For future cointegration / spread-MR pair selection prefer FX-FX and IDX-IDX compositions, avoid FX-IDX cross pairs, and treat CRYPTO/METAL as blowup-prone even when positive; rank candidates by Ret/DD not headline net%. --- ---. --- ---. --- ---.
---

---
2026-05-30 | Tags: cointegration_screen_math_v2, log_prices, eg_mackinnon, methodology_version_column, regime_reset_transition, audit_reproduced, infrastructure_milestone | Strategy: infrastructure | Run IDs: commits=ec96046(C1), e829302(C2), 7154d6e(C3), C4_pending
Cointegration screener math correction landed (C1 design doc + C2 schema + C3 math + C4 rendering). compute_pair_stats now runs statsmodels.tsa.stattools.coint(lb, la, trend='c', autolag='AIC') on log prices, replacing adfuller(spread) with Engle-Granger/MacKinnon critical values — the correctness fix vs v1's plain unit-root criticals that systematically over-rejected. Field names adf_statistic / adf_pvalue retained for schema stability; semantics flip via TEST_METHOD='eg_mackinnon'. methodology_version TEXT NOT NULL column added across PARQUET_COLUMNS + DB_COLUMNS + SINGLES_DB_COLUMNS + COINTEGRATION_SHEET_COLUMNS; idempotent ALTER TABLE migration backfills existing rows to 'v1_raw_adf'; writers mandatory (no NULL write path). Pair cohort tag = 'v2_log_eg'; singles cohort tag = 'v2_log_adf' (singles math was already log+ADF; tag bumped to mark post-C3 era). Regime hysteresis transition handled via methodology filter on query_for_classifier + existing bootstrap fallback: same-cohort priors only, classify from current-pvalue alone when <5 same-cohort rows exist — clean regime reset on the math cutover, no v1+v2 p-value mixing. MPS Cointegration tab + screener All Pairs (Diagnostic) tab surface the methodology column so legacy v1 episodes (339 in cointegration_sheet) are visually distinct from future v2 ingestions. Universe diagnostic via the production code path (compute only, no parquet/DB write): 83 qualified pairs at 1d×252 p<0.05 vs 2026-05-29 audit's ~84 (delta=1, autolag selection drift). Class composition FX-FX 37 / FX-IDX (CROSS) 42 / IDX-IDX 4, tracking audit's qualitative finding that FX-IDX dominates under EG criticals. Math correctness now pipeline-grade; the universe stat is reproducible through the production path. The audit's deeper conclusions ('cointegration as 1d×252 screen is weak', 'strength is anti-correlated with edge', 'strong-FX-FX cell uniformly low-edge' from project_cointegration_methodology_audit) remain PROVISIONAL per AGENT.md Invariant #31 — they were derived from the v1-tagged 339-episode corpus, which is NOT being rebuilt under v2 per operator decision (info-gain unfavorable; FDR would zero the universe regardless). Next v2 production writes happen on next cointegration_daily_runner tick. FDR explicitly deferred (separate policy decision; flag-extensible via future methodology_version='v3_log_eg_fdr'). Reference: outputs/system_reports/06_strategy_research/COINTEGRATION_SCREEN_MATH_V2.md. --- ---. --- ---. --- ---.
---

---
2026-05-30 | Tags: cointegration_v2_baseline, v1_retired, cr_exit_fix, last_coint_idx_exit, corpus_n473_pairs258, fx_fx_cleanest, snapshot_doc, transition_complete | Strategy: pine_ratio_zrev_v1 (COINTREV_V3 v2_log_eg cohort) | Run IDs: cointegration_sheet methodology_version='v2_log_eg' is_current=1 n=473; v1 corpus retired commits 950a7ab+4dc482f; generator b529583+f948415
v2 cointegration baseline LANDED. **Canonical snapshot:** `outputs/system_reports/06_strategy_research/COINTEGRATION_V1_TO_V2_TRANSITION.md` — full v1→v2 transition record (retirement audit + CR-EXIT-FIX rule revision + 488/473 silent-skip audit + corpus aggregation). v1_raw_adf corpus retired: 330 ledger rows dropped via repair_integrity, 330 backtests/ + 323 runs/ folders removed, 366 v1 directives moved to backtest_directives/archive/v1_legacy_corpus/, 68 superseded v1 tombstones retained as audit lineage. v2 generation rules locked: N=5 confirmation, entry=onset+N+1, exit=last_coint_idx (NOT break+1 — first attempt with exit=break+1 had all 527 directives rejected at window_validity_gate; CR-EXIT-FIX revised rule before regenerating 488). Corpus aggregation (cointegration_aggregator): ALL n=473 pos=52% ret/dd=0.41 verdicts WINNER:169 NEUTRAL:176 LOSER:108 BLOWUP:20. By pair-class — FX-FX n=127 62%pos rdd=0.54 BLOWUP:0 (cleanest, edge intact post-math-correction); IDX-IDX n=56 43%pos rdd=0.50 BLOWUP:1 (dropped vs prior 67%pos under v1 — v2 hysteresis stricter); FX-IDX n=218 50%pos rdd=0.28 BLOWUP:8 (largest+weakest, CROSS-hostile pattern preserved); CRYPTO/METAL n=72 46%pos rdd=0.52 BLOWUP:11 (fat-tail signature unchanged). 15 directives silently skipped at engine min-bars (≤3-day windows) — basket pipeline never ported run_stage1's RESOLVED_WARMUP_BARS mechanism; documented + spawned for follow-up. Generator now carries gate-verify pre-write check (commit f948415) to catch operator-locked-rule conflicts before bulk write. Implication: future cointegration / spread-MR pair selection prefer FX-FX (62% pos, zero blowups) and selectively IDX-IDX; avoid FX-IDX cross; treat CRYPTO/METAL as blowup-prone. Rank by Ret/DD not headline net%. Replaces the 2026-05-29 n=335 entry — that was v1_raw_adf cohort; this is the v2_log_eg replacement. Old v1 numbers are NOT comparable (different math + different classifier + different windowing). ---. --- ---. --- ---.
---

---
2026-06-02 | Tags: COINTREV_V3, cointegration-pthreshold, N-confirmation-gate | Strategy: pine_ratio_zrev_v1 | Run IDs: a4b28edf152a5dfbae99085b, 22d64647eca8b0e051d7b3c1
p<=0.01 cointegration admission lifts canonical outcomes, but a P01 N=0-vs-N=5 decomposition shows the N=5 confirmation gate (not the p-threshold) supplies the return-quality; p<=0.01 supplies the blowup-safety. P01,N5: median net 0.456, Ret/DD 0.249, blowup 0.7%. Drop N=5 (P01,N0): median net 0.130, Ret/DD 0.074 (~=P05 base 0.123/0.049), blowup stays 0.3%; N0-unique trades median net 0.068. N=5 correctly filters noise: the short spans it excludes are baseline-grade (median net 0.068, 53% positive, no edge). The p-threshold effect is concentrated in blowup reduction (0.3-0.7% vs 3.7%), retained at N=0. N=5 also improves entry timing on shared spans (0.295 at N=0 vs 0.456 at N=5). Keep the N=5 confirmation gate for cointegration return-quality; treat p<=0.01 as a blowup-safety control, not a return driver. N=0 additionally yields ~14.6% window-invalid premature entries (gate-rejected). --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: cointegration, leg_sizing, granular_parity, tail_risk, sizing_mode | Strategy: pine_ratio_zrev_v1 | Run IDs: 2410492ed851dea6b8910fb8, 9238f5e2580f6e7c28151754, 0081200bf52a755fba74e0b0
Granular notional-parity vs equal-notional (lot-equal-floored) leg sizing on the FULL cointegration universe: 474 matched pairs, both arms freshly run same-day (same broker snapshot), 0 trade-count mismatches (sizing changes lots only, not entries). ret/dd ~neutral (granular mean +0.42 vs notional +0.36, improves on 53%) but tail far worse: maxDD>50% = 41 vs 2 (20x), worst DD 172.6% vs 81.3%, catastrophic net<-50% = 12 vs 1; worst pair BTCUSD/ESP35 net -110% vs -24%. Granular parity does NOT improve risk-adjusted return; lot-equal-flooring was an accidental tail-brake and removing it (~3x notional deployed) inflates blowup risk 10-20x with no central-performance gain. Do NOT adopt as the sizing default. Keep equal-notional (lot-equal-floored) default. granular_parity/notional_ctl stay opt-in research only. If ever deploying true notional, pair with loser-leg-notional tail control (cf. H2 Martingale-tail), never granular parity alone. --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: cointegration, leg_sizing, granular_parity, candidate_level, deployable_portfolio | Strategy: pine_ratio_zrev_v1 | Run IDs: 2410492ed851dea6b8910fb8, 9238f5e2580f6e7c28151754, 0081200bf52a755fba74e0b0
REFINES the prior corpus-level granular_parity verdict to the DEPLOYABLE subset (the real decision). Candidate-level: each arm's top-N by ret/dd + the production approved candidate set (runs>=5, n=246), fresh _GP vs _GPN same-snapshot. On approved top-10/20/50 ret/dd is a WASH (N +1.16/1.28/1.20 vs G +1.13/1.27/1.22) while granular nets ~2x (12-15% vs 5-6%) for ~2x DD; catastrophic tail is junk-only (top-N #DD>50=0; approved set only 1-2 moderate ~56% blowups vs notional 0). On the portfolio actually deployed, granular_parity is NOT catastrophic and NOT a ret/dd improvement -- it is a capital-efficiency lever: ~2x return for ~2x DD at parity risk-adjusted return. The corpus-wide '10-20x blowup' stat was dominated by undeployable junk pairs. Decide sizing on the candidate subset, not the 474-pair average. Conservative default (notional/0.01) stays defensible; granular is viable IF more deployed capital is wanted AND a per-pair DD cap handles the 1-2 moderate (~56%) blowups on the approved set. --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: engine_fidelity, liquidation, leverage, sizing, backtest_validity | Strategy: pine_ratio_zrev_v1 | Run IDs: e8208ba06643d3bca2b60270, 2410492ed851dea6b8910fb8
Frozen v1_5_8 basket engine enforces NO margin-call/liquidation: high-leverage sizing (vol_parity, granular_parity) can run to NEGATIVE equity (loss > stake) instead of liquidating at the stake. Surfaced via the 14 SZVP runs; forensic SZVP_LEVERAGE_FORENSIC.md. 326 runs scanned, 0 freezes ever fired (margin level to -2061%, equity to -$67k). Negative-equity CONFINED to SZVP (14/14) + GP (6/474); base + ~4500 others bounded (dd_vs_stake<=100% is exact proof; 300-run sample 0 negative, 0 freeze). Backtest-FIDELITY issue ONLY: live is broker-margined at 0.01 lot (RAW_MIN_LOT_V1), notional sizing is mathematically bounded. Blast radius = leveraged-sizing studies; production research unaffected. Granular tail magnitudes inflated (worst net -132%/DD 173% -> floored -100%/100%) but FREQUENCY unchanged (41 vs 2 runs >50% DD) so the granular verdict holds. Apply tools/leverage_liquidation_adjust.py floor (intra-run min_equity<0 -> net -100/DD 100/ret_dd -1) for ANY leveraged study; no-op on notional. Do NOT modify the frozen engine, NOT add run-halting liquidation, NOT re-run production. SZVP archived (is_current=0) as research artifact; raw kept. --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: cointegration, leg_sizing, DECISION, sizing_settled, granular_parity | Strategy: pine_ratio_zrev_v1 | Run IDs: 0081200bf52a755fba74e0b0, 2410492ed851dea6b8910fb8
DECISION (FROZEN 2026-06-04): granular_parity (GP) adopted as the baseline leg sizing for COINTREV_V3 cointegration baskets. Sizing research arc CLOSED -- do not re-litigate or re-run parity experiments. Full-universe 474-pair GP-vs-notional (same broker snapshot): candidate rankings stable (Spearman +0.917, top-N overlap 70-78%); approved-set ret/dd parity (top10/20/50 N +1.16/1.28/1.20 vs G +1.13/1.27/1.22); 0 trade-count mismatches => sizing changes scale, not selection. GP adopted because: (1) economically coherent -- deploys the intended notional vs the lot-equal-floored under-deployment; (2) better parity; (3) similar candidate rankings; (4) no evidence sizing drives edge (matched controls: same ~5% edge across arms); (5) research question settled, expected info gain from more sizing work is low. Frozen to prevent re-debate. CLOSE sizing research. Discovery default stays notional (selection sizing-invariant + bounded); GP live application + per-pair DD-cap folds into the LIVE-DEPLOYMENT-SIZING topic. NEXT roadmap (higher expected deployment impact): capital model -> portfolio construction/allocation -> live deployment sizing -> correlation management. --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: cointegration, leg_sizing, DECISION, granular_parity, baseline_promotion | Strategy: pine_ratio_zrev_v1 | Run IDs: 0081200bf52a755fba74e0b0, 2410492ed851dea6b8910fb8
EXECUTION + CORRECTION (2026-06-04): GP promoted to the methodology DEFAULT. The cointegration generator now defaults to granular_parity. This SUPERSEDES the prior decision entry's 'discovery default stays notional' (operator override: GP IS the base; future research runs on it). generate_cointrev_v3_directives default flipped notional->granular_parity (commit bcf2a6ec; 30 tests + promotion-lock test). GPN archived: 474/474 tombstoned (is_current=0), exact duplicate of base, raw preserved. Rule internal fallback stays notional (legacy reproduction). MPS Cointegration 4680->4206. Future cointegration research runs granular by default (_GP = active base). Old untagged-notional base (1827 rows) kept ACTIVE transitionally (plan A) as the candidates(runs>=5) density source until the GP corpus matures, then archive it. Drop stale notional-default expectations -- GP is the base. PENDING: (a) build out GP coverage via future research, then archive the old notional base; (b) wire tools/leverage_liquidation_adjust into the candidates view so granular tails show realistically (-100% cap). --- ---. --- ---. --- ---.
---

---
2026-06-04 | Tags: cointegration, exit_logic, zcross, zopp, confirmation | Strategy: pine_ratio_zrev_v1 | Run IDs: 4399e24940508844587423e0, cf6e7f307d24cdcdbf23094b, 083ed1438eeddcbf66854138
Exit-logic 3-way under the GP baseline (granular, same windows, liquidation floor): current exit (reverse@+-2) vs Z=0/zcross (flat@mean) vs ZOPP/opposite-band (flat@opposite +-1). 473-474 matched pairs each. Z=0 dominates: ret/dd mean +0.48 vs baseline +0.42 vs ZOPP +0.44; net% +0.4 vs +0.5 vs -0.1; maxDD>50 = 20 vs 41 vs 22; catastrophic = 6 vs 12 vs 8; top10 median ret/dd 4.33 vs 3.76 vs 3.95. ZOPP beats baseline on tail but loses to Z=0 on EVERY metric. Z=0 (exit at the mean) is the optimal exit -- recommended over baseline (~2x less tail at equal ret/dd). ZOPP (ride past the mean to opposite +-1) is RULED OUT: dominated by Z=0 -- overshooting past the mean gives back the reversion profit (net -0.1 vs Z=0 +0.4) and adds DD, no benefit. The 'later exit' hypothesis is falsified for this signal. If the exit is changed, adopt Z=0 (pine_ratio_zrev_v1_zcross), not ZOPP. zopp engine capability kept (opt-in, not adopted). Z=0 adoption (promote zcross to default) is a separate decision, not yet made. Exit experiment cohorts (_GP_ZCRS/_GP_ZOPP) archived as research artifacts. --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, forced_z_stop, reentry_latch, branch_closure, champion_stands | Strategy: pine_ratio_zrev_v1 (GP_ZCRS_CXN1_Z25 champion) | Run IDs: cohorts GP_ZSTOP_CXN1_Z25 (z_stop=4.0) + GP_ZSTOP3_CXN1_Z25 (z_stop=3.0); n=475 matched pairs each vs champion; no hex run UUIDs in source -- series tags are the pointers
A hard |z|-stop exit + re-entry latch (z_stop=4.0 then 3.0; z_entry=2.5 preserved) did NOT improve risk-adjusted performance vs the no-stop champion -- z_stop=4.0 a wash, z_stop=3.0 net-negative on corpus. Because the zcross reference position holds to zero-cross, the latch did not demonstrably bind in a way that altered corpus-level outcomes, so this tested FORCED EXIT, not regime memory. z_stop=4.0 n=475: stop fired 184/475 dirs (327 fires), forced exit changed Ret/DD in 176/184 (med dRetDD -0.0073), corpus net% 89 vs 89 identical, worst -89.7 both, non-fired set byte-identical to champion. z_stop=3.0 n=475: corpus net% 89 vs -29 (-118pp), paired med Ret/DD & net% deltas ~0 (variant better 37%/38%), win% 60 vs 50, worst -89.7 vs -80.1, 0 blowups, trade-freq 100%. Forced-exit branch SHELVED -- cutting at z=3.0 or 4.0 adds no risk-adjusted value (4.0 wash, 3.0 worse); the champion's no-stop ride-to-zcross exit stands. The regime-memory hypothesis remains UNTESTED: the re-entry latch did not demonstrably bind, so nothing was learned about suppressing re-entry after a stop. Do NOT add a forced |z|-stop (3.0-4.0) to the champion, and do NOT cite this as 'z-stop disproven' or 'regime memory fails' -- only forced-exit-without-a-binding-latch was tested. A real regime-memory test must make the latch BIND (e.g. flatten the reference at the stop), else it is a no-op. --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, entry_threshold, z40, cohort_specific, champion_stands | Strategy: pine_ratio_zrev_v1 (GP_ZCRS_CXN1_Z25 champion) | Run IDs: cohort GP_ZCRS_CXN1_Z40; n=475 matched pairs vs champion (z_entry 2.5 -> 4.0, all else identical); no hex run UUIDs in source
A deeper entry threshold (z_entry=4.0 vs the champion's 2.5; exit/sizing/no-stop identical) collapses trade frequency and degrades the edge -- it does not buy a better fill, it mostly stops trading. n=475: trade-freq 6% of champion (94% fewer; TOTAL cycles 13521->882, trades 27184->1766), median cycles 15->1 / trades 32->2; corpus net% 89 vs 28 (-61pp); paired med Ret/DD delta -0.030 (Z40 better 44%), net% delta -0.400 (better 42%); win% 60 vs 0. maxDD% lower for Z40 (median champ 7.634 vs Z40 1.461; mean 12.13 vs 3.47) only because it barely trades; worst net% -89.7 vs -42.1; 0 blowups. (dMed = median of per-pair deltas, champ minus Z40.). Z40 is REJECTED -- pushing entry to z=4.0 removes ~94% of trades and the survivors do not compensate (Ret/DD and net% both worse, corpus net% -61pp). COHORT-SPECIFIC to the COINTREV_V3 GP_ZCRS champion, not a universal law about deep entries. Keep z_entry=2.5 as the champion entry threshold. Frame Z40 as 'too deep for THIS signal/cohort' -- the shallow-band reversion edge lives near 2.5; entering only at 4.0 forfeits it. (The pyramiding analysis re-derives the same 'enter-at-z=4' population and reaches the same verdict.) --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, pyramiding, report_only, survivorship_bias, champion_stands | Strategy: pine_ratio_zrev_v1 (GP_ZCRS_CXN1_Z25 champion) | Run IDs: report-only analysis (tmp/pyramid_report.md); champion GP_ZCRS_CXN1_Z25 n=475 dirs / 13592 cycles; no backtest run
Report-only assessment of a secondary 0.5x entry at |z|=4.0 (same zcross exit): expected decision-changing information from a canonical backtest ~= 0, so the branch is REJECTED without further work; the champion stays unchanged (no pyramiding, no stop). 99.7% in-sample reversion at |z|>=4 (325/326) is a survivorship artifact -- the window gate admits only continuous-cointegrated spans, so counted cycles revert by construction; add P&L +1.29/cycle same-bar -> +0.59 next-bar -> +$0.007/add (t=0.01, p=0.99). Add fires on the worst cohort (30.1% vs 61.4% base win-rate at |z|=4) at the 99th-pctile excursion ceiling, with no margin of safety. REJECT the pyramiding branch. Strongest argument: the premise and the fatal flaw are the SAME fact -- the 'z=4 reliably reverts' edge is manufactured by the windowed, zcross-only corpus, so the live failure mode the add doubles into (a z=4 that keeps diverging) is structurally absent from every in-corpus test. ZSTOP4 + Z40 already jointly predict this. Do NOT elevate pyramiding to a backtest -- more in-corpus data re-measures the survivorship artifact at higher fidelity, it cannot surface the tail that matters. A real test needs OUT-OF-CORPUS / cointegration-break data. The only unmeasured upside is the opposite (scaling OUT near z-extremes), out of scope here. --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, hurst_entry_filter, entry_regime, champion_overlay, class_scoped | Strategy: pine_ratio_zrev_v1_zcross_hf (HF55 arm vs GP_ZCRS_CXN1_Z25 champion) | Run IDs: cohort GP_ZCRS_CXN1_Z25_HF55 n=475 matched vs champion GP_ZCRS_CXN1_Z25; rule commit 28a80cc8; series tags are the pointers
Blocking entries when the canonical ratio's trailing 50-bar R/S Hurst > 0.55 (one moving variable, thresholds operator-fixed, no tuning) removed ~22% of trades, roughly doubled corpus net%, and lowered median DD; run-level blowups unchanged (0) -- reproducing the Step-1 report-only stratification (tmp/hurst_step1_report.md) through the canonical pipeline. n=475 matched: corpus net% 89 vs 181; median maxDD 7.63 vs 6.37 (trades 27184 vs 21156, blowups 0 both). The filter excises the locally-persistent-spread entry population (25% of champion cycles, -$9.4k aggregate, blocked-H p50 0.575) -- a cycle-QUALITY lever, not blowup protection (blowup-run entries show the same H as healthy runs); gains concentrate in CRY/MET-X (-173 -> -65) and FX-FX (+177 -> +205, worst -39.5 -> -18.7) while FX-IDX/IDX-IDX trade small net for better tails. Adoption is a separate decision -- evaluate class-scoped (CRY/MET-X + FX-FX) before corpus-wide; do not tune 50/0.55 without a new tagged arm; HURST_BLOCK payloads persist to raw/recycle_events.jsonl from commit 81b5d033 onward (required before any live arm). --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, hurst_entry_filter, threshold_class_interaction, hf60 | Strategy: pine_ratio_zrev_v1_zcross_hf (HF60 vs champion + HF55) | Run IDs: cohort GP_ZCRS_CXN1_Z25_HF60 n=475 matched vs GP_ZCRS_CXN1_Z25 and _HF55
H-threshold preference is a CLASS property, not a corpus constant: 0.60 flips FX-IDX positive and leads IDX-IDX; 0.55 is the only arm that rescues CRY/MET-X (0.60 there is worse than no filter). Corpus net ties; HF55 keeps the DD/tail compression. Corpus net% 89/181/178 (champ/HF55/HF60), median maxDD 7.63/6.37/7.20; class net FX-IDX -48/-60/+16, CRY/MET-X -173/-65/-177. The 0.55-0.60 H band is net-negative in CRY/MET but net-positive in index classes; offline sims missed it -- entry relocation only exists in-pipeline. Adoption = class-scoped threshold choice (0.55 CRY/MET-X, 0.60 FX-IDX/IDX-IDX, FX-FX either); per-class winner-picking across 2 arms is in-sample -- validate the mix or accept as bounded. No further threshold sweeps. --- ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, half_life_filter, hl120, branch_closed, fx_idx_stuck_entries | Strategy: pine_ratio_zrev_v1_zcross_hl (HL120 vs champion) | Run IDs: cohort GP_ZCRS_CXN1_Z25_HL120 n=475 matched vs GP_ZCRS_CXN1_Z25; commit pending push
Local half-life entry block (AR(1) W=100, >120 bars/non-reverting) REJECTED corpus-wide -- net below the unfiltered champion; NOT redundant with Hurst (70% of 981 blocks were non-reverting windows = a different, mostly-healthy population) -- except FX-IDX, where it is the best arm yet. Corpus net% 89 vs 76; FX-IDX -48 -> +36 (2nd independent arm to rescue it, after HF60 +16), CRY/MET -173 -> -227. Reversion-speed blocking taxes classes where relocation is expensive; FX-IDX entry toxicity is consistently 'locally-stuck spread' regardless of detector. HL branch closed for corpus-wide adoption. FX-IDX repeatedly improves under independent stuck-entry detectors (HF60, HL120) -- entry toxicity there is STRUCTURAL, not detector-specific: future work should characterize the shared stuck-spread population, not test more detector families. BTCUSD/USDCAD E250130 crossed -100 under every relocation arm -- floor/exclude it in adoption math. ---. --- ---. --- ---.
---

---
2026-06-12 | Tags: cointegration, legmove_filter, lm20, relocation_persistence | Strategy: pine_ratio_zrev_v1_zcross_lm (LM20 vs champion + 3 arms) | Run IDs: cohort GP_ZCRS_CXN1_Z25_LM20 n=475 matched vs GP_ZCRS_CXN1_Z25
Displacement gate ('don't fade >2-sigma trailing leg repricings') is the best single corpus-wide arm -- but did NOT rescue FX-IDX, the class that motivated it. Corpus net% 89/181/188 (champ/HF55/LM20), blowups 0, worst -87.0 (improved); FX-IDX -48 -> -50 vs HL120's +36. Block-condition PERSISTENCE determines relocation quality: ~hours-long displacement spikes relocate entries into the same repricing episode (FX-IDX unmoved), while ~25h H/HL conditions outlast it (FX-IDX rescued). Only observable in-pipeline. Adoption menu: LM20 corpus-wide (net/tails) vs HF55 (DD compression); 4 classes x 4 different winners = selection trap -- class-scoped mixes need out-of-corpus validation. Entry-filter detector-STATISTIC family CLOSED; persistence-duration effects identified as the remaining open mechanism. ---. --- ---.
---

---
2026-06-13 | Tags: cointegration, entry_trigger, z_average, champion_stands | Strategy: pine_ratio_zrev_v1_zcross_zavg | Run IDs: cohort GP_ZCRS_CXN1_Z25_ZAVG2 n=475 matched vs GP_ZCRS_CXN1_Z25
2-bar z-average entry trigger (mean(z,2) cross +/-2.5) vs the single-bar zcross champion; exit/sizing/window/threshold identical. n=475: corpus net% 89 -> -223; med Ret/DD 0.014->0.007, net% 0.20->0.12; trades 32->24 (73% freq); win 60->58; 0 blowups; only 45% pairs improve. Averaging KEEPS the persistent/deep extreme (poor-reversion, fat-tail loser population) and SKIPS the sharp single-bar crossing (the reversion edge) -- it inverts entry quality. Do NOT smooth/persist/average the entry trigger; the edge IS the sharp crossing (3rd confirm: persistence N+2/3 + HF55 Hurst + ZAVG2). The live over-trade is real-time threshold NOISE -> fix is producer bar-settlement, which a settled backtest cannot validate. --- ---.
---

---
2026-06-14 | Tags: cointegration, session-filter, GP_ZCRS, window-robustness | Strategy: pine_ratio_zrev_v1_session_window | Run IDs: 76a7ced597b38643ddec57c2, ce332badd5a599683f0242e3
Session overlay (enter 00:00-21:00 UTC, force-flat at NY close, flat overnight) vs the 24h GP_ZCRS_Z25 v1.5.10 cointegration baseline, conditioned on ROBUST 24h winners (Ret/DD>=1.0, >=30 trades, >=20d window): only 7 of 476 pairs qualify; 34 of 41 nominal winners are <20d/<30-trade short-window artifacts. Robust winners 7: session improved 2 (both index: GBPUSD/GER40 2.27->2.58, NAS100/US30 1.31->1.48), worsened 5 (crypto ETHUSD/GBPAUD 3.72->3.02, BTCUSD/EUSTX50 3.36->2.01). Overlay does not reliably help even the good pairs (5/7 worse); the cointegration edge needs the full MR reversion (often overnight), which force-flat cuts short. Only positive is a weak, inconsistent index-cross effect (indices quiet overnight). Naive top-Ret/DD candidate lists are dominated by short-window artifacts. Reject session-flat as a corpus/class overlay. Narrow optional follow-up: overnight-flat on index-cross pairs only. Separately: add a min-window/min-trades guard to candidate ranking - the corpus high-Ret/DD tail is mostly thin spans. --- ---.
---

---
2026-06-14 | Tags: cointegration, entry-filter, HF55, cost-dominated | Strategy: pine_ratio_zrev_v1_zcross_hf | Run IDs: 76a7ced597b38643ddec57c2, 59f4834c433f6bd506719add
HF55 Hurst entry filter (block entry when ratio Hurst>0.55) on the GP_ZCRS_Z25 v1.5.10 cointegration baseline, 476 matched pairs. net% -2.89->-2.20 (median +0.17, 52% up), maxDD 9.59->8.44 (79% up), blowups 2->1, trades 32->24; but win% flat (mean -0.85), profitable-pair frac 25%->26%, median net gain 0.19 < spread saved 0.79. HF55 reduces the bleed via tail-risk cut (blocks trending/diverging entries) + spread saved from ~25% fewer trades, NOT trade selection: flat win% means no per-trade edge, and it cut net-positive trades too. Strategy stays net-negative; 6/7 robust 24h winners worse. No entry filter fixes a per-trade-edge<cost (over-trading) problem. Next: frequency/timescale (higher trade TF), not another filter. --- ---.
---

---
2026-06-14 | Tags: cointegration, timeframe, frequency, over-trading | Strategy: pine_ratio_zrev_v1_zcross | Run IDs: 76a7ced597b38643ddec57c2, 9f9577ccb5de2affd3a0deb5
Re-ran the GP_ZCRS_Z25 v1.5.10 cointegration baseline on 1H instead of 15m (same spans, same params: z_entry=2.5/n_window=30/granular_parity) to test the over-trading/cost diagnosis. 466 matched pairs. Trades 34->8 (4x fewer), blowups 2->0, maxDD 9.7->6.6, mean net% -7.3->-1.2; BUT median 0.00 is a thin-span artifact (52% of spans <10 trades); robust spans (>=20tr,>=20d, n=128) still -3.05 median, 38% net-pos; 1H beats 15m on 80% of robust spans. Frequency is the right lever (cost cut 4x, tail risk gone, 1H>15m on 80% of robust spans) but NOT sufficient: even at 1H the active spans over-trade, per-trade edge still < spread. Strategy goes from bleeding (-7.3% mean) to slow leak (-1.2% mean), not profit. The break-even median is a thin-span illusion (window-robustness lesson). Test 4H to find the frequency floor. If 4H lands at the same ~-3% robust-span floor, the edge is too thin to beat retail spreads at any frequency on this universe; pivot to cost-per-trade (instrument selection) or the ~10% robust subset. --- ---.
---

---
2026-06-14 | Tags: cointegration, timeframe, frequency, frequency-floor | Strategy: pine_ratio_zrev_v1_zcross | Run IDs: 76a7ced597b38643ddec57c2, 4e3c9f40391c29f1e355a451
Completed the frequency sweep 15m/1H/4H on the GP_ZCRS_Z25 v1.5.10 cointegration baseline (same spans/params) to locate the cost-vs-sample sweet spot of the over-trading diagnosis. Robust-span (>=20tr,>=20d) median net%: 15m -10.26 -> 1H -3.05 -> 4H -4.61 (robust n: 204/128/9); median trades 32/8/2; blowups 3/0/0; all-span mean net% -7.46/-1.17/-0.03. Frequency lever EXHAUSTED at 1H: 15m->1H cuts over-trading loss + kills blowups, but 4H collapses the sample (median 2 trades, only 9 robust spans) and robust net% gets WORSE. The all-span mean->0 is a thin-span artifact. NO timeframe is profitable; best rung (1H) still -3.05% on robust spans. Per-trade edge too thin to beat the spread at any frequency. Frequency arc CLOSED. Only remaining lever that can flip the SIGN is execution-side: earn the spread (passive limit buy@bid/sell@ask) vs pay it. Next: limit-fill engine model, fills validated on 5m bars. --- ---.
---

---
2026-06-15 | Tags: execution_arc, passive_basket_entry, basket_synchronization, dual_passive_completion_RETIRED, broker_behavior, spread_capture | Strategy: pine_ratio_zrev_v1 cointegration baskets (CADJPYUSDCHF/CHFJPYEURUSD/EURJPYGBPJPY/EURJPYUSDJPY/GBPAUDUSDCHF) | Run IDs: EXECUTION PROBE (live broker behavior, NOT pipeline-producible; no pipeline run_id): tmp/basket_phase1_20260615T060759Z.jsonl + 20260615T063941Z.jsonl, n=64, OctaFX-Demo 213872531
Live passive 2-leg basket entry (per-leg min-distance limits, both-legs-or-cancel) is execution-fragile: faithful per-leg fills but terrible leg SYNCHRONIZATION -- two correlated legs almost never fill together. 64 basket-windows (5 coint baskets): (a) both-fill 5% / (b) single-leg 41% / (c) neither 55%; 3 co-fills 60-150s apart, ZERO under 30s. Single-leg market-completion cost ~37-42pt/$0.26, TIMING-INVARIANT (immediate ~= window-end $0.26-0.29; waiting 12-cheaper/14-costlier; hindsight-best $0.18). Passive execution does NOT work for opening two-leg baskets via simultaneous passive limits. The broker fills limits faithfully (at-limit, confirmed earlier) but legs desynchronize; a single-leg fill IS the adverse move, so market-completing it pays a fixed unavoidable tax that no timing escapes. Architecture dual-passive-entry + market-completion RETIRED. Do NOT engineer PARTIAL_FILL->MARKET_COMPLETE->OPEN. For 2-leg basket entry, passive both-or-cancel is non-viable; entry must be market (pay spread) or single-instrument. DECISION-GRADE for execution behavior (live demo authoritative); strategy-PnL viability under any execution model stays pipeline-gated (re-pricing + at-touch-wide-spread untested). Scope: min-distance proxy, n=64, one session. --- ---.
---

---
2026-06-15 | Tags: execution_arc, limit_order_probe, spread_capture, stops_level, broker_gate, arc_closed | Strategy: pine_ratio_zrev_v1 cointegration baskets (COINTREV_V3) | Run IDs: EXECUTION PROBE (no pipeline run_id): tmp/limit_probe_20260615T041518Z.jsonl + T042046Z + T042140Z + T043642Z + T043722Z; OctaFX-Demo 213872531
OctaFX's stops_level constraint prevents at-touch limit order placement for all tested FX pairs — passive spread-capture is not viable on this broker. Limit-order spread-capture arc CLOSED. 5 JSONL probe files (04:15–04:37 UTC 2026-06-15, 7 FX symbols). Dry-run phase: stops_level > spread for every pair (AUDJPY 32>23, AUDNZD 44>25, EURUSD 14>13, USDCHF 26>14, GBPJPY 28>25, USDJPY 24>21, GBPAUD 90>27); can_rest_at_touch=false for all. Live at-touch attempt (AUDJPY BUY+SELL at bid/ask): retcode=10015 "Invalid price" — both rejected immediately. Live with stops_level offset (bid−12pts BUY): accepted + parked, not filled in 150s; SELL still 10015. Live offset multi-symbol (5 pairs, USDCHF/EURUSD/GBPJPY/USDJPY/GBPAUD): all accepted and parked, zero fills in 150s, all cleanly cancelled (retcode=10009). Contradicts the prior 2026-06-14 read-only symbol_info check that stated "FX majors stops_level<spread" — that was a dynamic snapshot; live order placement shows stops_level>=spread in practice for all 7 tested pairs. Spread-capture requires BUY_LIMIT@bid / SELL_LIMIT@ask. OctaFX's stops_level is >= spread for all tested FX pairs under live conditions, making at-touch placement structurally impossible (retcode=10015). Offset limits place but do not fill. The +2.48% earn-spread ceiling from the gross decomposition is theoretically correct but broker-inaccessible. Arc CLOSED — no further limit-order spread-capture work warranted on OctaFX without a structural broker change. The frequency arc (CLOSED 2026-06-14) and limit-order arc (CLOSED here) exhaust the known levers for making the charged GP_ZCRS_CXN1_Z25 corpus net-positive. The cointegration MR signal has no remaining execution-side path to profitability at retail OctaFX spreads with market fills. Entry-filter experiments (HF55/LM20/BB-on-spread/ADX-gate) are also closed by the v1.5.10 per-trade-edge verdict — no entry filter flips a universe-wide negative edge. Research pivot: live execution quality (bar-settlement producer fix) and the signal-driven producer wiring are the active open arcs. --- ---.
---

