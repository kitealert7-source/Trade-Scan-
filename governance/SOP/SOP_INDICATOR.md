# SOP_INDICATOR.md

Version: 1.0 Authority Level: Subordinate to TRADE_SCAN_DOCTRINE Scope:
Indicator Repository Governance

------------------------------------------------------------------------

## 1. PURPOSE

This document defines the structural, behavioral, and architectural
rules governing the `indicators/` repository.

Indicators are reusable research primitives. They are NOT strategy
logic. They are NOT execution logic. They are NOT stateful systems.

------------------------------------------------------------------------

## 2. REPOSITORY LOCATION

All indicators MUST reside under:

    Trade_Scan/indicators/

Subfolder grouping by domain is permitted:

    indicators/structure/
    indicators/volatility/
    indicators/statistics/
    indicators/price/

------------------------------------------------------------------------

## 3. INDICATOR DEFINITION

An indicator is defined as:

-   A pure function
-   Deterministic
-   Stateless
-   Side-effect free
-   Returning a pandas Series

Indicators MUST NOT:

-   Access engine internals
-   Access strategy context
-   Modify external state
-   Perform file I/O
-   Depend on global variables

------------------------------------------------------------------------

## 4. FUNCTION CONTRACT

Indicators MUST:

-   Accept explicit inputs (DataFrame or Series)
-   Not rely on hidden data
-   Not mutate input objects
-   Return a new Series aligned to input index

Standard form:

    def indicator_name(df: pd.DataFrame, window: int) -> pd.Series

OR

    def indicator_name(series: pd.Series, window: int) -> pd.Series

------------------------------------------------------------------------

## 5. STRATEGY USAGE RULE

Strategies MUST import indicators from the repository:

    from indicators.volatility.atr import atr

Inline indicator implementations inside strategy plugins are PROHIBITED.

Detection of inline rolling/ATR-style logic SHALL result in hard failure
during Stage-1 preflight validation.

------------------------------------------------------------------------

## 6. VERSION STABILITY

Indicator function signatures MUST NOT change silently.

If a signature change is required:

-   A new function name MUST be introduced
-   Existing function MUST remain backward compatible
-   Dependent strategies MUST be updated explicitly

No breaking changes allowed without version traceability.

------------------------------------------------------------------------

## 7. REPRODUCIBILITY REQUIREMENT

Indicator logic is part of research determinism.

Therefore:

-   Indicator files are snapshotted indirectly through strategy
    snapshots.
-   Strategies depending on indicators assume indicator repository
    stability.

If an indicator is materially changed:

-   This constitutes research evolution.
-   Revalidation of dependent strategies is REQUIRED.

------------------------------------------------------------------------

## 8. DELETION POLICY

Unused indicators SHOULD be removed to prevent repository drift.

The repository is a curated research core --- not a sandbox for
experimental fragments.

------------------------------------------------------------------------

## 9. ENFORCEMENT

Stage-1 harness MAY enforce static validation to detect inline logic.

However, enforcement is governance-level only. Execution engine behavior
remains unaffected.

------------------------------------------------------------------------
## 10. Indicator Dependency Validation (MANDATORY)

Strategy plugins MUST declare indicator dependencies exclusively through:

    from indicators.<domain>.<module> import <function>

The following rules apply:

1. All referenced indicator modules MUST physically exist under:
   
       Trade_Scan/indicators/

2. Missing indicator files SHALL result in HARD FAILURE during Stage-1 preflight.

3. Dependency validation MUST occur BEFORE:
   - Strategy import
   - Engine execution
   - Any metric computation

4. No fallback behavior is permitted.
   No silent continuation is permitted.
   No automatic correction is permitted.

5. Inline recreation of missing indicators inside strategy plugins is PROHIBITED.

Dependency validation is structural enforcement only.
It does not modify execution semantics.

-----------------------------------------------------------------------

## 11. Parameterization & Duplication Policy (MANDATORY)

### 11.1 Generic Implementation Requirement

Indicators MUST be implemented as generic, parameterized primitives.

Example:

    def rsi(series: pd.Series, period: int) -> pd.Series

Hardcoded variants such as:

    rsi_14.py
    rsi_2.py
    atr_10.py

are STRICTLY PROHIBITED.

Period-specific behavior MUST be controlled via function parameters,
not via separate files or duplicated implementations.

---

### 11.2 Duplicate Indicator Prohibition

If a mathematical primitive already exists in the repository:

- It MUST NOT be reimplemented.
- It MUST NOT be cloned under a different name.
- It MUST NOT be embedded inline inside a strategy.

Strategies MUST reuse the existing repository implementation.

Detection of duplicate mathematical logic SHALL be treated as
repository drift and governance violation.

---

### 11.3 Parameter Variation Rule

Different parameter values (e.g., RSI(14), RSI(2), RSI(3)):

- DO NOT constitute new indicators.
- DO NOT require new repository files.
- MUST be handled at the strategy or directive level.

Indicator repository stores primitives.
Strategy controls parameter selection.
Directive controls parameter testing bounds.

---

### 11.4 Parameter Testing Governance

If parameter testing (grid search, bounded variation, etc.) is declared:

- Iteration MUST be declared explicitly in the directive.
- Each parameter configuration MUST produce an independent run.
- Indicator repository MUST remain unchanged.

Indicator files SHALL NOT be modified to accommodate parameter testing.

---

This policy ensures:
- Repository minimalism
- Mathematical consistency
- Reuse integrity
- Clean separation of concerns
- Future-safe parameter experimentation

-----------------------------------------------------------------------
END OF DOCUMENT



