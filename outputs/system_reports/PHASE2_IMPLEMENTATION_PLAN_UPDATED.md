# PHASE2_IMPLEMENTATION_PLAN_UPDATED.md

## Objective

Complete the Phase‑2 lifecycle implementation of the TradeScan research
pipeline while **keeping all existing evaluation infrastructure
intact**.

Phase‑2 only formalizes the **research lifecycle structure** and
**pipeline stop point**.

No structural changes will be made to:

-   Strategy_Master_Filter.xlsx schema
-   AK_Trade_Report outputs
-   existing evaluation formulas
-   the structure of filtering scripts

The goal is **structural organization only**, not metric redesign.

------------------------------------------------------------------------

# Existing Evaluation Architecture (Confirmed)

The current system already produces two research layers:

runs\
↓\
Strategy_Master_Filter.xlsx\
↓\
Filtered_Strategies_Passed.xlsx

Interpretation under Phase‑2:

runs → sandbox → candidates

Where:

Strategy_Master_Filter.xlsx = **sandbox evaluation layer**\
Filtered_Strategies_Passed.xlsx = **candidate strategy list**

No schema changes are required.

------------------------------------------------------------------------

# Candidate Promotion Logic

Candidate filtering is currently implemented in:

tools/filter_strategies.py

The script itself remains the **mechanism for promotion**.

### Important Implementation Rule

The **structure of `filter_strategies.py` must not be modified**.

Only **threshold values may be adjusted**.\
No architectural or structural refactoring of the script is required.

This prevents unnecessary expansion of scope.

------------------------------------------------------------------------

# Updated Candidate Promotion Criteria

Previous fixed trade rule:

Total Trades ≥ 80

is replaced with **trade density filtering**.

Trade density is already calculated in the Strategy_Master_Filter sheet.

### Candidate Promotion Metrics

Baseline filtering should use:

-   Return / DD Ratio
-   Expectancy
-   Profit Factor
-   Sharpe Ratio
-   Trade Density

Trade density ensures sufficient statistical sample size while remaining
independent of test duration.

Trade density formula:

trade_density = total_trades / (trading_period / 365.25)

Trade density filtering is only applied when:

trading_period ≥ 365 days

Strategies with shorter test windows are excluded from candidate
promotion.

Exact thresholds may be adjusted in the filtering script but the script
structure remains unchanged.

------------------------------------------------------------------------

# Phase‑2 Implementation Steps (Order of Execution)

## Step 1 --- Introduce STATE_ROOT (Research State Separation)

Create a dedicated research state directory outside the code repository.

Example structure:

Documents/ Trade_Scan/ ← code repository TradeScan_State/ ← research
outputs

### STATE_ROOT Definition

Use a relative project path instead of a hard‑coded location.

Example:

PROJECT_ROOT = Path(**file**).resolve().parents\[1\]\
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"

All research artifact paths must derive from `STATE_ROOT`.

------------------------------------------------------------------------

## Step 2 --- Create Lifecycle Directories

Inside STATE_ROOT ensure the following folders exist:

runs/\
sandbox/\
candidates/\
strategies/\
registry/\
archive/\
quarantine/\
logs/

Lifecycle model becomes:

runs → sandbox → candidates → portfolio discovery

------------------------------------------------------------------------

## Step 3 --- Define Write Boundaries

To prevent state corruption, automated processes may only write to
specific directories.

Allowed write locations:

runs/\
sandbox/\
candidates/

Read‑only during Phase‑2:

strategies/\
registry/\
archive/\
quarantine/

------------------------------------------------------------------------

## Step 4 --- Map Existing Evaluation to Lifecycle

The pipeline already generates:

Strategy_Master_Filter.xlsx

This becomes the **sandbox evaluation output**.

Filtering via:

tools/filter_strategies.py

produces:

Filtered_Strategies_Passed.xlsx

This becomes the **candidate strategy list**.

Lifecycle becomes:

directive\
↓\
runs\
↓\
Strategy_Master_Filter.xlsx (sandbox)\
↓\
Filtered_Strategies_Passed.xlsx (candidates)

------------------------------------------------------------------------

## Step 5 --- Deterministic Rebuild Requirement

Directive execution must be **deterministic**.

Running:

python tools/run_pipeline.py --all

must produce identical outputs for identical directives.

Sources of nondeterminism that must be avoided:

-   timestamps in evaluation logic
-   uncontrolled random seeds
-   unordered file iteration
-   floating precision drift

This ensures research results are reproducible.

------------------------------------------------------------------------

## Step 6 --- Adjust Pipeline Stop Point

Pipeline execution must stop after candidate generation.

Execution chain:

directive\
↓\
run_pipeline.py\
↓\
Strategy_Master_Filter.xlsx\
↓\
filter_strategies.py\
↓\
Filtered_Strategies_Passed.xlsx\
↓\
STOP

Portfolio discovery becomes a **separate research stage**.

------------------------------------------------------------------------

## Step 7 --- Candidate Identity Requirements

Candidate strategies should contain minimal identifiers to avoid fragile
references.

Recommended columns:

-   strategy_name
-   directive_id
-   timeframe
-   trade_density
-   return_dd
-   profit_factor
-   expectancy
-   sharpe

No schema redesign is required --- identifiers must simply exist.

------------------------------------------------------------------------

## Step 8 --- Clean Rebuild of Research State

Because earlier artifacts were generated before infrastructure
separation, perform a clean rebuild.

Procedure:

1.  Backup the current TradeScan directory.
2.  Create empty TradeScan_State.
3.  Create lifecycle directories.
4.  Clear previous run outputs.
5.  Rebuild runs using:

python tools/run_pipeline.py --all

6.  Regenerate Strategy_Master_Filter.xlsx.
7.  Execute filter_strategies.py.
8.  Verify Filtered_Strategies_Passed.xlsx.

Old artifacts should not be migrated and may be moved to:

archive/

Directives remain the canonical source of truth.

------------------------------------------------------------------------

# Final Lifecycle After Phase‑2

directive\
↓\
runs\
↓\
sandbox evaluation\
Strategy_Master_Filter.xlsx\
↓\
candidate filtering\
Filtered_Strategies_Passed.xlsx\
↓\
STOP\
↓\
manual portfolio research

------------------------------------------------------------------------

# Out of Scope for Phase‑2

The following items are intentionally excluded to prevent scope
expansion:

-   modification of Strategy_Master_Filter schema
-   structural modification of filter_strategies.py
-   portfolio discovery automation
-   capital engine redesign
-   registry redesign
-   strategy metadata refactoring
-   additional pipeline features suggested by audits

These may be evaluated later but are **not required for Phase‑2
completion**.

------------------------------------------------------------------------

# Completion Criteria

Phase‑2 is complete when:

-   STATE_ROOT separation is implemented
-   lifecycle directories exist under TradeScan_State
-   write boundaries are respected
-   pipeline stops at candidate generation
-   filter_strategies.py produces candidate strategies
-   trade_density replaces fixed trade count filtering
-   directives can rebuild the entire research state
-   rebuilds produce deterministic outputs

At that point the infrastructure phase is considered **closed**, and
research can resume.
