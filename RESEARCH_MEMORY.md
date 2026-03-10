# RESEARCH MEMORY





THIS FILE IS APPEND-ONLY.

Existing entries must never be modified.

Corrections must be added as new entries.



This file stores important findings from experiments.

Rules:

* Append only
* Never delete prior entries
* Each entry must include date, finding, evidence, conclusion, implication
* Each entry must include a Tags: block with 3-5 keywords describing the research finding.

2026-03-06
Tags:
zscore
entry\_logic
mean\_reversion

Finding:
Deeper Z-score entry reduces PF

Evidence:
PF dropped from 1.20 to 1.17 in E3 test

Conclusion:
Prefer moderate stretch entries

Implication:
Avoid extreme stretch entry thresholds in future strategies

2026-03-06
Tags:
portfolio_construction
common_history
risk_metrics
evaluation_window

Finding:
Common-history alignment improved risk-adjusted portfolio metrics for the selected multi-symbol basket.

Evidence:
For the same 4-run portfolio set, full-history evaluation produced Sharpe 0.8328, MaxDD -2.13%, Return/DD 6.7259 (440 trades). Common-history window (2024-01-02 to 2026-01-31) produced Sharpe 1.8866, MaxDD -1.10%, Return/DD 8.0604 (221 trades).

Conclusion:
Window misalignment across components can dilute comparability and mask the true recent joint behavior of the basket.

Implication:
Use a common-history evaluation pass as a standard comparison layer before portfolio selection and ranking decisions.

2026-03-07
Tags:
nas100
volatility_expansion
atr_filter
pullback
daily_timeframe

Finding:
ATR-percentile threshold filter (>75 exclusion) outperforms ATR-percentile band filter (60–72 exclusion) on NAS100 daily volatility pullback strategy.

Evidence:
S02 (threshold >75, 4-bar cooldown, ATR10): 35 trades, Sharpe 3.18, MaxDD -1.12%, Return/DD 2.60, verdict PROMOTE.
S03 (band 60–72 outside, 5-bar cooldown, ATR14): 42 trades, Sharpe 2.84, MaxDD -2.49%, Return/DD 1.51, verdict PROMOTE. Same window, same symbol, same base logic.

Conclusion:
Excluding only extreme volatility (>75th pct) allows more trades and delivers better risk-adjusted returns than a band filter that also blocks moderate vol.

Implication:
For NAS100 daily pullback strategies, prefer simple upper-threshold ATR filters over band filters. Band filters reduce trade count without improving Return/DD.

2026-03-07
Tags:
xauusd
stop_loss
atr_multiplier
time_exit
sensitivity

Finding:
Tighter ATR stop (2.1×) with longer time exit (15 bars) outperforms wider stop (2.3×) with shorter time exit (14 bars) on the same XAUUSD 1H entry pattern.

Evidence:
S04 (stop 2.1, exit 15): 89 trades, Sharpe 1.53, MaxDD -0.92%, Return/DD 0.99, verdict HOLD.
S05 (stop 2.3, exit 14): 89 trades, Sharpe 0.87, MaxDD -1.46%, Return/DD 0.38, verdict HOLD. Identical entry signals (same trade count), different exit params only.

Conclusion:
Increasing ATR stop from 2.1× to 2.3× degraded Sharpe and Return/DD on the tested XAUUSD 1H trend-pullback system.

Implication:
Wider stops did not improve drawdown and reduced risk-adjusted returns in this configuration. Future sweeps should prioritize testing tighter stops (1.8–2.1×) rather than expanding the stop width further.

2026-03-07
Tags:
fx
mean_reversion
exit_design
friction_sensitivity
strategy_refinement

Strategy:
01_MR_FX_1H_ULTC_REGFILT_S02_V1_P00

Status:
PLANNED EXPERIMENT

Finding:
Friction stress test confirmed genuine strategy vulnerability. 1 pip round-trip cost reduces PF from ~1.18 to ~0.94. Diagnostic ruled out modeling error. Root cause is structural: exit-too-fast / stop-too-wide.

Evidence:
Strategy has ~2,178 trades over 2 years. Approximately 98% of trades exit within 1 bar. Avg winner $10.42, avg loser $12.81, payoff ratio 0.81. Avg profit per trade ~$0.95. 1-pip friction cost ~$1.10 per trade, consuming 87% of edge. Total friction drag ($2,774) exceeds total baseline profit ($2,064), producing net loss of -$709 under 1-pip slippage. Friction cost validated: expected $2,771 vs observed $2,774 (0.09% variance — no modeling error). Monte Carlo median CAGR 0.14% vs backtest 14.45%, indicating significant regime-fit. Top 1% of trades (21 winners) generate 57.81% of total profit. Per-trade edge eroding: 2024 $1.63/trade → 2025 $0.78/trade. AUDNZD generates 37% of profit (best symbol); EURUSD weakest (55.5% WR, $0.52/trade).

Conclusion:
The strategy captures only the initial snap of mean reversion before the primary move develops, while allowing losers to run past the reversion window. The payoff ratio (0.81) and thin edge per trade make live execution under realistic friction conditions unviable without structural changes.

Implication:
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

2026-03-08
Tags:
limit_entry
mean_reversion
entry_design
oscillator
fill_rate

Strategy:
01_MR_FX_1H_ULTC_REGFILT_S10/S11/S12_V1_P00

Finding:
ATR-scaled limit orders offset from the signal bar close hurt performance vs immediate next-bar-open market entry for UC%-based mean reversion strategies.

Evidence:
Three controlled experiments (k=0.05, 0.10, 0.15 ATR offset, expiry=2 bars) vs S07 baseline. Fill rates 83–90%. PF degraded from 1.198 to ~1.145 across all k-values. Sharpe approximately halved. MaxDD increased 30–58% relative to baseline. Recovery factor fell. All three k-values produced worse risk-adjusted outcomes than immediate market entry.

Conclusion:
For UC%-based oscillator signals on FX 1H, the signal bar itself represents the adverse excursion. Waiting for further pullback from signal close selects weaker setups — trades that stalled rather than reversed immediately — and misses the primary reversion snap that occurs on bar N+1.

Implication:
Do not test limit entry offsets against oscillator-triggered MR strategies without a structural reason to expect the signal bar to precede a deeper pullback. Limit entry designs are better suited to trend-following or breakout contexts where entry timing relative to a level matters. This experiment axis is closed for the 01_MR_FX_1H_ULTC_REGFILT lineage.

2026-03-08
Tags:
oscillator_tuning
indicator_variant
mean_reversion
signal_quality
sweep_exhaustion

Strategy:
01_MR_FX_1H_ULTC_REGFILT_S07_V1_P01/P02/P03

Finding:
Changing the UC% oscillator preset mode (fast / balanced / slow) does not improve on the S07_V1_P00 baseline. The original UC% defaults (lookback=5, smooth=3, OB/OS=75/25) are already well-tuned for this strategy configuration.

Evidence:
P01 (fast: smooth=1, OB/OS=80/20): trades 5179 vs 2467 baseline (2× frequency), port PF 1.05, robustness PF 1.13, exp/trade $0.65 vs $1.22, MaxDD $840 vs $442, recovery 3.33 vs 5.55. P02 (balanced: smooth=2, OB/OS=80/20): port PF 1.08, CAGR 15.3% vs 17.1%, recovery 4.74. P03 (slow: lookback=7, smooth=3, OB/OS=75/25): port PF 1.09, CAGR 5.99%, MC 5th pctl CAGR turns negative (-0.03%), top-5% trade concentration at 392% of total PnL — highly tail-dependent. All three variants fail to match baseline on PF, expectancy, recovery factor, and MC worst-case DD.

Conclusion:
Faster modes over-signal and dilute per-trade edge. Slower modes reduce frequency and concentrate returns into extreme tail events, making equity fragile. The baseline preset is the strongest configuration tested.

Implication:
UC% oscillator mode sweeps are exhausted for the 01_MR_FX_1H_ULTC_REGFILT lineage. Do not re-test smoothing or OB/OS threshold variants without a structural change to entry or exit logic that changes the reward profile of individual trades. Future experiments should focus on other structural levers (stop width, exit design, symbol selection) rather than oscillator parameterisation.

2026-03-09
Tags:
xauusd
dayoc
volatility_filter
atr_percentile
parameter_sweep

Strategy:
06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P00 through P15

Finding:
For the DAYOC (Daily Open-to-Close) model on XAUUSD 15M, the ATR percentile volatility filter has two independent levers — low_threshold_pct (the percentile cutoff defining LOW regime) and window (the rolling lookback for percentile ranking). Both levers interact non-linearly. Threshold=37 and window=120 individually improve on the baseline (threshold=33, window=100) and the combination (P13) achieves the best Sharpe of the entire sweep (4.92) at the lowest MaxDD% (1.36%). The interaction effect is real but modest: P13 beats each single-axis winner on Sharpe but trails P05 on absolute return and RetDD.

Evidence:
14-patch sweep (P00–P14) across two axes:
Axis 1 (threshold, window fixed at 100): Sharpe peaked at P05 (37%, Sharpe 4.65, RetDD 6.62). PnL rose monotonically to P07 (50%, $1,154) but RetDD degraded above 42%.
Axis 2 (window, threshold fixed at 33): window=60 collapsed Sharpe to 2.16 (over-noisy); window=120 optimal (P11, Sharpe 4.90); window=150 over-filtered (58 trades, $423 PnL).
Interaction P13 (37/120): Sharpe 4.92, MaxDD 1.36%, RetDD 5.78, CAGR 4.99%.
Interaction P14 (42/120): Sharpe 4.44, MaxDD 1.39%, RetDD 6.15, CAGR 5.44%. Confirms wider window disciplines higher threshold well.

Conclusion:
Best risk-adjusted: P13 (37/120). Best return/risk balance: P14 (42/120). Best absolute return: P05 (37/100, RetDD 6.62). Threshold and window interact — combining best single-axis values improves Sharpe but shifts trade-off away from return maximisation toward drawdown minimisation.

Implication:
For DAYOC-family strategies with ATR percentile regime filters, treat threshold and window as a joint decision. Do not optimise either axis in isolation and expect the combination to be additive. Test the interaction explicitly (as P13/P14 did here) before finalising parameter selection.

2026-03-09
Tags:
xauusd
dayoc
trade_window
regime_stability
long_horizon_validation

Strategy:
06_PA_XAUUSD_15M_DAYOC_REGFILT_S02_V1_P15 (P06 config, extended to 2023-2026)

Finding:
Extending the P06 DAYOC strategy back to 2023 (adding 126 trades from 2023) added only $17 of net PnL while collapsing Sharpe from 4.37 to 2.86, doubling MaxDD from 1.37% to 2.38%, and cutting RetDD from 7.03 to 4.33. The 2024-01-01 trade window gate used in the main sweep was not an artefact of data availability — it reflects a genuine structural regime difference in XAUUSD.

Evidence:
P06 (2024-2026): 160 trades, $1,029.95 PnL, Sharpe 4.37, MaxDD 1.37%, RetDD 7.03, CAGR 6.14%.
P15 (2023-2026, same parameters): 286 trades, $1,046.92 PnL, Sharpe 2.86, MaxDD 2.38%, RetDD 4.33, CAGR 3.73%.
126 additional 2023 trades contributed ~$17 net profit (avg $0.13/trade vs P06 avg $6.44/trade). Pipeline rated both PROMOTE but quality metrics diverged sharply.

Conclusion:
Gold in 2023 was in post-Fed-tightening consolidation. LOW-ATR days in 2023 were structurally different from 2024-2026: choppy-quiet rather than trending-quiet. The DAYOC model (first-bar entry, penultimate-bar exit) requires directional resolve within a session to profit. In 2023, low ATR days lacked that resolve.

Implication:
The 2024-01-01 trade window gate is a structural feature, not a data constraint. Do not remove it for future DAYOC variants without confirming that the earlier period has comparable session directionality. For any PA-family strategy on XAUUSD, run a long-horizon validation pass (P15-style) to verify the chosen trade window is justified by regime quality, not convenience.

2026-03-09
Tags:
xauusd
smi
mean_reversion
oscillator_asymmetry
idea_exhausted

Strategy:
07_MR_XAUUSD_15M_SMI_SMIFILT_S01 and S02 (P00–P04)

Finding:
Multi-timeframe SMI mean reversion on XAUUSD 15M has no tradable edge across the 2024–2026 test window in any tested configuration. Five variants across two sweeps were discarded.

Evidence:
S01_P00 (1H SMI < -50, no vol filter): 148 trades, $8.92 net, Sharpe 0.05 — flat.
S01_P01 (1H SMI < -80): 10 trades — insufficient sample, no inference possible.
S02_P02 (state gate + LOW/HIGH vol filter): 116 trades, Sharpe 1.92, but 2024 = -$115, 2025 = +$527. Monte Carlo mean CAGR 0.02%.
S02_P03 (event window, 1H cross-below -50, long only): 31 trades, Sharpe 5.14, but 2024 = -$150, 2025 = +$379. 28/100 block bootstrap runs end below start.
S02_P04 (bidirectional mirror of P03): 64 trades, -$146 net, Sharpe -1.27 — short side net -$357 in LOW regime, confirming structural asymmetry.

Conclusion:
The edge in P02 and P03 is entirely concentrated in 2025 and fragile under block bootstrap reshuffling. 2024 is a systematic loss year in every long-only variant, not random noise. The underlying cause: XAUUSD's long-run upward drift means "overbought" SMI is not a reversion condition (P04 short side failure), and "oversold" SMI during 2024 trending moves admits entries into sustained downtrends rather than true capitulation reversals. The event-window design (P03) correctly diagnosed and partially addressed this, but the 2024 regime is inherently hostile to this approach.

Implication:
Idea 07 (SMI oscillator mean reversion on XAUUSD 15M) is exhausted in its current form. Do not iterate further on threshold, window size, or vol filter variants — the architecture is sound but the instrument-timeframe combination does not support the hypothesis consistently. If revisiting, require either: (a) a secondary directional filter (e.g., daily trend alignment confirming gold is in a range, not a trend) to exclude the 2024 trending-down environment, or (b) a different instrument where SMI oversold conditions are genuinely reverting rather than momentum-continuing.
