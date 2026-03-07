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
