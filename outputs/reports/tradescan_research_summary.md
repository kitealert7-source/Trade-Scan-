# TradeScan Research Framework --- Phase-1 Stabilization Summary

Date: 2026-03-16

## Objective

Stabilize the TradeScan research infrastructure and define the
structured discovery workflow for systematic strategy development.

## System Layers

### Engine Layer

-   Universal Research Engine (frozen execution semantics)
-   Deterministic trade execution
-   Manifest‑protected files
-   Engine changes only when execution logic changes

### Pipeline Layer

Handles orchestration: - Directive admission - Strategy provisioning -
Backtest execution - Artifact generation - Portfolio simulations

### Research Layer

Where strategy discovery occurs: - INBOX - backtests - sandbox -
candidates

------------------------------------------------------------------------

## Data Authority Hierarchy

TradeScan_State/

-   backtests → raw execution truth
-   sandbox → evaluation ledger
-   candidates → promoted strategies

backtests stores: - trade records - equity curves - portfolio profiles -
raw experiment outputs

sandbox stores: - Strategy_Master_Filter ledger - summary evaluation
metrics

candidates stores: - strategies that passed sandbox filtering

------------------------------------------------------------------------

## Discovery Workflow

INBOX → backtests → sandbox → candidates

INBOX - entry point for strategy ideas - directive validation and
provisioning

backtests - raw strategy execution - no filtering applied

sandbox - first evaluation stage - loose filtering rules

candidates - promising strategies for further refinement

------------------------------------------------------------------------

## Three‑Pass Research Model

Pass 1 --- Concept Validation - verify strategy produces trades - verify
reasonable behavior - no parameter optimization

Pass 2 --- Structural Robustness - basic risk constraints - verify
stability across symbols

Pass 3 --- Parameter Refinement - small parameter search - exit tuning -
volatility thresholds

Maximum passes per strategy: 3

------------------------------------------------------------------------

## Pass‑1 Operating Environment

Timeframes: - 15 minute - 1 hour

Test window: - Jan 2024 → Present

Rules: - mandatory intraday exit - high trade frequency required -
minimal filtering

Purpose: maximize discovery speed and strategy diversity

------------------------------------------------------------------------

## Strategic Insight

Initial testing shows:

-   hundreds of trades
-   manageable drawdowns
-   signal generation exceeds portfolio capacity

This indicates the system is currently **capital constrained rather than
signal constrained**.

Future improvements likely come from: - capital allocation models -
signal prioritization - portfolio scheduling

------------------------------------------------------------------------

## Research Principles

-   deterministic infrastructure
-   clean workflow boundaries
-   controlled experimentation
-   limited optimization

TradeScan now functions as a **structured strategy discovery engine**,
not merely a backtesting tool.
