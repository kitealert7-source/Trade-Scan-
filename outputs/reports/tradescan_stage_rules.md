# TradeScan Research Pipeline --- Stage Rules

Date: 2026-03-16

This document defines the operational rules for each stage of the
TradeScan research pipeline.

------------------------------------------------------------------------

# Stage 1 --- INBOX

Purpose: Introduce new strategy ideas.

Rules: - directive must pass schema validation - naming must follow
namespace rules - directive must define: - timeframe - symbol universe -
execution rules - volatility filter (if used) - directive must be
deterministic - directives cannot reference previous runs

Output: Strategy moves to backtests execution stage.

------------------------------------------------------------------------

# Stage 2 --- BACKTESTS

Purpose: Raw execution and data generation.

Rules: - no filtering allowed - all directives execute fully - artifacts
must be generated per symbol - runs must be immutable once completed

Artifacts generated: - trade level results - risk metrics - equity
curves - portfolio simulation outputs

Goal: Collect statistically meaningful observations.

------------------------------------------------------------------------

# Stage 3 --- SANDBOX

Purpose: First evaluation filter.

Rules: Filtering must remain loose.

Recommended filters: - trade_count \> 50 - CAGR \> 0 - max_drawdown \<
20% - profit_factor \> 1.05

Goal: Remove clearly unviable strategies while preserving diversity.

Promotion: Strategies passing filters move to candidates.

------------------------------------------------------------------------

# Stage 4 --- CANDIDATES

Purpose: Store promising strategies.

Rules: - snapshot of backtest artifacts preserved - no raw execution
changes allowed - candidate strategy history must remain traceable

Future tasks: - robustness checks - structural analysis - portfolio
interaction testing

------------------------------------------------------------------------

# Three‑Pass Research Constraint

Every strategy may go through a maximum of three passes.

Pass 1 --- Concept Validation Pass 2 --- Structural Robustness Pass 3
--- Parameter Refinement

Each pass introduces exactly **one additional constraint**.

This prevents overfitting and ensures controlled experimentation.

------------------------------------------------------------------------

# Pass‑1 Operating Constraints

Timeframes: - 15m - 1h

Test Window: Jan 2024 → present

Holding Rules: - intraday exit required - short holding periods
preferred

Purpose: maximize signal throughput for early discovery.

------------------------------------------------------------------------

# Core Research Principle

Validate ideas first. Optimize parameters later.

Early optimization leads to overfitting and unreliable results.

TradeScan is designed to behave as a **scientific research framework**
rather than a brute‑force optimizer.
