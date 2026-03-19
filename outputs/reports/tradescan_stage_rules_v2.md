# TradeScan Research Pipeline --- Operational Stage Rules (Updated)

Date: 2026-03-16

------------------------------------------------------------------------

# Stage 1 --- INBOX

Purpose: Introduce new strategy ideas.

Requirements:

Directive must pass schema validation. Directive naming must follow
namespace rules. Directive must define:

-   timeframe
-   symbol universe
-   execution rules
-   exit rules

Directives must be deterministic.

Output: Directive moves to backtests execution.

------------------------------------------------------------------------

# Stage 2 --- BACKTESTS

Purpose: Raw experiment execution.

Rules:

No filtering allowed. All directives must execute fully. Artifacts must
be generated per symbol.

Artifacts include:

-   trade level results
-   risk metrics
-   equity curves
-   portfolio simulations

Backtest artifacts are immutable once generated.

Goal: Collect statistically meaningful observations.

------------------------------------------------------------------------

# Stage 3 --- SANDBOX

Purpose: First evaluation filter.

Filtering must remain loose.

Suggested baseline filters:

trade_count \> 50 CAGR \> 0 max_drawdown \< 20% profit_factor \> 1.05

Sandbox also applies **diversity filtering**.

------------------------------------------------------------------------

# Sandbox Diversity Rules

Group runs by strategy family.

Example:

02_VOL_IDX_1D_VOLEXP_ATRFILT_S00_V1_P00

Family identifier:

02_VOL_IDX_1D_VOLEXP_ATRFILT

Within each family:

select maximum 2 runs.

Asset diversity rule:

maximum 2 runs per asset.

Ranking metric:

highest MAR preferred.

This prevents a single directive or asset from dominating the sandbox
shortlist.

------------------------------------------------------------------------

# Stage 4 --- CANDIDATES

Purpose: Store promising strategies that passed sandbox evaluation.

Rules:

Strategy snapshot must remain immutable. Strategy history must remain
traceable. No structural modifications allowed at this stage.

Candidates will later undergo:

-   robustness testing
-   parameter exploration
-   portfolio interaction testing

------------------------------------------------------------------------

# Research Pass Discipline

Maximum passes per strategy: 3

Pass 1 -- Concept validation Pass 2 -- Structural robustness Pass 3 --
Parameter refinement

Each pass introduces exactly **one orthogonal constraint**.

------------------------------------------------------------------------

# Pass‑1 Operating Constraints

Timeframes:

15m 1h

Test window:

Jan 2024 → present

Holding rule:

intraday exit required

Purpose:

maximize signal discovery speed.

------------------------------------------------------------------------

# Core Research Principle

Validate ideas first. Optimize parameters later.

Early optimization increases overfitting risk.

TradeScan is designed to operate as a **systematic research framework
rather than an ad‑hoc backtesting environment**.
