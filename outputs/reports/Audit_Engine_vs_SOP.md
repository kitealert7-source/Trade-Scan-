# AGENT DIRECTIVE — ENGINE VS SOP DIVERGENCE AUDIT

## 1. Capital Model Implementation
**SOP Requirement (§4.3)**: "capital_deployed_t = sum(notional_usd of open trades)... Required metrics: peak_capital_deployed, capital_overextension_ratio."
**Engine Implementation**: `portfolio_evaluator.py` calculates `capital_utilization` based on *count* of concurrent trades (Line 245), not notional USD sum. Does not compute `peak_capital_deployed` or isolation ratio.
**Divergence**: **MISSING FEATURE**
**Recommended Action**: New feature required (Extend `portfolio_evaluator` to sum notional exposure).

## 2. Concurrency Logic
**SOP Requirement (§4.4)**: "Concurrency SHALL be determined exclusively using timestamp overlap logic... No alternative approximation methods are permitted."
**Engine Implementation**:
-   `apply_portfolio_constraints.py`: Uses exact timestamp overlap (`exit > entry`). **COMPLIANT.**
-   `portfolio_evaluator.py`: Uses daily binning (`active = df[entry <= dt & exit >= dt]`) in `concurrency_profile` (Line 276). This is a granularity approximation.
**Divergence**: **STRUCTURAL VIOLATION** (Evaluator uses daily binning, SOP forbids approximation).
**Recommended Action**: Refactor required (Update `portfolio_evaluator` to use exact timestamp logic from Constraint tool).

## 3. Stress-Window Definition
**SOP Requirement (§7)**: "max_pairwise_corr_stress is computed only within the start-to-trough period of the maximum observed portfolio drawdown."
**Engine Implementation**: `portfolio_evaluator.py` computes correlation (`avg_pairwise_corr`) on the *entire* dataset (Line 391). Calculating correlation specifically during the stress window is missing.
**Divergence**: **MISSING FEATURE**
**Recommended Action**: New feature required (Add stress-window slicing to `correlation_analysis`).

## 4. Ledger Enforcement
**SOP Requirement (§8)**: "All portfolios MUST be indexed in Master_Portfolio_Sheet.xlsx... Append-only."
**Engine Implementation**: `portfolio_evaluator.py` saves JSON/MD snapshots but does not write to any master Excel ledger. `stage3_compiler.py` exists for Strategy Ledger, but no Portfolio Ledger exists.
**Divergence**: **MISSING FEATURE**
**Recommended Action**: New feature required (Create `tools/update_portfolio_ledger.py`).

## 5. Artifact Scope
**SOP Requirement (§5)**: "Each portfolio MUST emit: portfolio_tradelevel.csv... All portfolio metrics MUST derive exclusively from this file."
**Engine Implementation**: `portfolio_evaluator.py` loads trades into memory (`portfolio_df`) but never saves a consolidated `portfolio_tradelevel.csv` to disk. Metrics are derived from in-memory DF.
**Divergence**: **MISSING FEATURE**
**Recommended Action**: New feature required (Save `portfolio_df` to CSV before metric computation).

## 6. Determinism (Input Discovery)
**SOP Requirement (§3)**: "constituent_run_ids (explicit list)".
**Engine Implementation**: `portfolio_evaluator.py` uses auto-discovery (`BACKTESTS_ROOT.iterdir()` matching `StrategyID_*`). Implicitly assumes all folders matching logic are constituents.
**Divergence**: **MINOR DEVIATION** (Implicit vs Explicit).
**Recommended Action**: Refactor required (Pass explicit list of Run IDs or enforce stricter folder matching).

## 7. Stage-1 Constraint Backup Naming
**SOP Requirement (SOP_TESTING §7A.1)**: Backup must be named `results_tradelevel_raw_snapshot.csv`.
**Engine Implementation**: `apply_portfolio_constraints.py` names backup `results_tradelevel_unconstrained.csv`.
**Divergence**: **TERMINOLOGY ALIGNMENT ONLY**
**Recommended Action**: Terminology alignment only (Rename backup file).
