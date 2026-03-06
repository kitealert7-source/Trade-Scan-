# TRADE_SCAN_DOCTRINE.md

Version: 1.1 Status: Foundational Constitutional Document Authority
Level: Above SOP_TESTING and SOP_OUTPUT (Philosophical Layer)

------------------------------------------------------------------------

## 1. PURPOSE

Trade_Scan exists to build a deterministic, research-grade strategy
evaluation system. Its objective is not discretionary trading, not
signal generation, and not optimization theater. Its objective is
structural truth discovery under controlled, reproducible conditions.

------------------------------------------------------------------------

## 2. SYSTEM IDENTITY

Trade_Scan is:

- A research engine
- Deterministic by design
- Batch-first and reproducibility-first
- Artifact-governed
- Mechanically auditable

Trade_Scan is NOT:

- A discretionary trading assistant
- A curve-fitting environment
- A parameter optimization playground
- A subjective performance evaluator

### 2.1 External Analytical Sandbox — Non-Authoritative

Trade_Scan tolerates an external analytical sandbox
(`research/adhoc_experiments/`) for exploratory, non-governed analysis.

This sandbox:

- Is **not** a co-equal operational plane
- Has **no** authority over pipeline state, artifacts, or registry
- May read from `runs/` (read-only)
- May **never** write to `runs/`, `backtests/`, or any governed output path
- Is structurally **outside** the FSM lifecycle

Research is tolerated — not institutionalized.

------------------------------------------------------------------------

## 3. OPTIMIZATION OBJECTIVE HIERARCHY

Primary Objective: Robust expectancy under realistic constraints.

Secondary Objectives:

1. Risk-adjusted return stability
2. Cross-year structural consistency
3. Drawdown containment
4. Controlled trade frequency
5. Variance containment

Absolute return is NOT the primary objective.

------------------------------------------------------------------------

## 4. NON-NEGOTIABLE CONSTRAINTS

- Trade_Scan is the ONLY permitted execution engine.
- Universal_Research_Engine must execute logic exactly as declared.
- Directive text is the sole source of strategy logic.
- No discretionary overrides.
- No inference when ambiguity exists.
- No recomputation of authoritative artifacts outside declared stages.
- Close-only execution unless explicitly redefined in engine version.

Any violation results in hard abort.

------------------------------------------------------------------------

## 5. RESEARCH PHILOSOPHY

- Deterministic batch execution only.
- Stage-1 emits canonical raw data.
- Stage-2 transforms only.
- Stage-3 aggregates mechanically.
- Improvement is hypothesis-driven, not emotion-driven.

No qualitative interpretation inside execution layers.

------------------------------------------------------------------------

## 6. STRATEGY EVALUATION STANDARD

A strategy is considered structurally viable only if:

- Expectancy \> 0 after costs
- Drawdown remains within defined risk tolerance
- Profit factor is stable across multiple years
- No single year dominates total performance
- Results are reproducible across isolated runs

High return with instability is considered structural failure.

------------------------------------------------------------------------

## 7. DEFINITION OF IMPROVEMENT

Improvement may include:

- Structural logic refinement
- Risk management restructuring
- Volatility conditioning
- Regime-based filtering
- Entry/exit asymmetry enhancement

Improvement may NOT include:

- Blind parameter optimization
- Retrofitting logic to historical outliers
- Changing engine behavior to satisfy a directive
- Removing losing trades by arbitrary filters

Improvement must increase robustness, not just metrics.

------------------------------------------------------------------------

## 8. LONG-TERM ARCHITECTURE INTENT

- Stage-1 remains the canonical data emission layer.
- All downstream stages remain pure transformations.
- Engine upgrades must preserve backward determinism unless versioned
    explicitly.
- Governance remains artifact-based.
- Parallel-safe batch execution is preferred over interactive
    workflows.

------------------------------------------------------------------------

## 9. WHAT THIS SYSTEM REFUSES TO BECOME

- A discretionary trading environment
- A GUI-driven optimization tool
- A manually adjusted backtest framework
- A narrative-driven performance analyzer

Trade_Scan evaluates structure, not stories.

------------------------------------------------------------------------

## 10. 5-YEAR SUCCESS CRITERIA

Success is defined as:

- A stable portfolio of structurally robust strategies
- Minimal philosophical drift across versions
- Deterministic reproducibility of all historical results
- Clear separation between research and execution
- Institutional-grade auditability

------------------------------------------------------------------------

END OF DOCUMENT
