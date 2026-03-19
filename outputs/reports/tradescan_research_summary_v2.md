# TradeScan Research Framework --- Phase-1 Stabilization Summary (Updated)

Date: 2026-03-16

## Objective

Stabilize the TradeScan research infrastructure and define the
structured discovery workflow for systematic strategy development.

------------------------------------------------------------------------

# 1. System Layers

ENGINE (frozen) PIPELINE (orchestration) RESEARCH (strategy discovery)

The execution engine is now considered stable. All experimentation
happens in the research layer without modifying engine logic.

------------------------------------------------------------------------

# 2. Data Authority Hierarchy

TradeScan_State/

-   backtests → immutable execution results
-   sandbox → evaluation and filtering ledger
-   candidates → promoted strategy ideas

backtests contains raw experiment artifacts including:

-   results_tradelevel.csv
-   results_standard.csv
-   results_risk.csv
-   equity_curve.csv
-   profile_comparison.json

sandbox contains only the evaluation ledger:

-   Strategy_Master_Filter.xlsx

candidates contains strategies that passed sandbox evaluation.

------------------------------------------------------------------------

# 3. Discovery Pipeline

INBOX → backtests → sandbox → candidates

INBOX Entry point for new strategy directives.

backtests Raw execution stage. All directives run with no filtering.

sandbox Loose filtering stage to identify promising ideas.

candidates Strategies worthy of deeper research.

------------------------------------------------------------------------

# 4. Three Pass Research Model

Maximum passes per strategy: 3

Pass 1 -- Concept Validation Confirm the strategy produces signals and
behaves reasonably.

Pass 2 -- Structural Robustness Test risk containment and cross-asset
stability.

Pass 3 -- Parameter Refinement Limited parameter exploration once the
idea proves viable.

Each pass introduces exactly one new constraint.

------------------------------------------------------------------------

# 5. Pass‑1 Operating Environment

Timeframes: 15 minute 1 hour

Test window: Jan 2024 → Present

Rules: Intraday exit required High trade density preferred Minimal
filtering

Goal: Maximize discovery throughput.

------------------------------------------------------------------------

# 6. Sandbox Diversity Principle (New)

Sandbox promotion must prioritize **idea diversity rather than raw run
count**.

Multiple runs from the same directive often represent the same
underlying strategy idea.

Therefore sandbox promotion must operate on **strategy families rather
than individual runs**.

Strategy family example:

02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00

Family identifier:

02_VOL_IDX_1D_VOLEXP_ATRFILT

Runs belonging to the same family are considered variations of the same
idea.

------------------------------------------------------------------------

# 7. Sandbox Diversity Controls

Recommended controls:

Maximum runs per strategy family: 2 Maximum runs per asset: 2

Selection criteria within each family:

Highest MAR (preferred) or highest Profit Factor with drawdown
constraint.

This prevents a single directive or asset from dominating the research
shortlist.

------------------------------------------------------------------------

# 8. Strategic Insight

Recent runs show that the system currently produces:

-   large signal counts
-   moderate drawdowns
-   significant trade opportunities

This indicates the platform is currently **capital constrained rather
than signal constrained**.

Future improvements are likely to come from:

-   capital allocation
-   portfolio scheduling
-   signal prioritization

------------------------------------------------------------------------

# 9. Research Discipline Principles

Deterministic infrastructure Clean phase boundaries Orthogonal research
passes Limited parameter optimization Promotion based on idea diversity

TradeScan now functions as a structured strategy discovery engine rather
than a simple backtesting tool.

------------------------------------------------------------------------

# 10. Failed Concept Log

## Squeeze Breakout — FX 4H (Ideas 14 / 16) | Closed 2026-03-19

**Concept:** Detect volatility squeeze via ATR percentile compression, enter
on close outside Bollinger Bands, exit via band logic or timeout.

**Variants tested:**

| ID | Squeeze | SL | Exit | Trades | PF | Net PnL |
|----|---------|-----|------|--------|-----|---------|
| 14 BBSQZ S01 | BB-width pct | Midline | Midline cross / 20-bar | 300 | 0.84 | -$120 |
| 14 BBSQZ S02 | ATR pct (fixed) | Midline | Midline cross / 20-bar | 288 | 0.89 | -$86 |
| 16 ATRSQZ S01 | ATR pct (fixed) | Opp band | Opp band touch / 20-bar | 258 | 0.82 | -$160 |

**What worked:**
- ATR-percentile squeeze detection is sounder than BB-width percentile
  (captures intraday range, not just close clustering).
- USDJPY and GBPUSD showed marginal positive edge across all variants —
  the concept may have pair-specific validity.
- Signal frequency was adequate (60–75 trades per pair over 2 years on 4H).

**Why it failed:**
- No trend filter — strategy enters breakouts in both directions equally,
  catching false breakouts in trending markets (StrongDn bleeds on all pairs).
- Exit logic couldn't be resolved cleanly: midline exit cuts winners early;
  opposite-band exit widens risk disproportionately to 3×ATR TP.
- The 3×ATR TP was never reached consistently — breakouts on 4H FX tend to
  retrace before extending, which requires a different TP or trail structure.

**Insights for future brainstorming:**
- A trend-filtered version (only take breakouts in trend direction) could
  be viable — GBPUSD/USDJPY showed positive residual.
- Squeeze + breakout works better with a trailing stop than a fixed TP,
  letting winners run after the expansion begins.
- Consider testing on shorter timeframe (1H) or higher-volatility instruments
  (XAUUSD) where post-squeeze expansion is more sustained.
- ATR-percentile squeeze detection is reusable for other strategy families
  as a pre-filter condition.
