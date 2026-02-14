# SOP_PORTFOLIO_ANALYSIS --- VERSION 1.0

**Status:** AUTHORITATIVE | POST-RUN ANALYSIS  
**Precedence:**  
TRADE_SCAN_DOCTRINE  
→ SOP_TESTING  
→ SOP_OUTPUT  
→ SOP_PORTFOLIO_ANALYSIS

------------------------------------------------------------------------

## 1. Purpose

This SOP governs deterministic cross-run portfolio construction and
evaluation.

Portfolio analysis: - Operates only on RUN_COMPLETE strategies - Does
not alter Stage-1, Stage-2, or Stage-3 artifacts - Produces independent
portfolio artifacts - Maintains strict forward-only flow

Portfolio analysis is structural synthesis, not execution truth.

------------------------------------------------------------------------

## 2. Authority & Directionality (HARD)

Stage-4:

-   MAY read Stage-1, Stage-2, and Stage-3 artifacts
-   MUST NOT modify any prior artifact
-   MUST NOT write to Strategy_Master_Filter.xlsx
-   MUST NOT trigger cleanup
-   MUST NOT influence strategy registry state

Flow is strictly:

Stage-1 → Stage-2 → Stage-3 → Stage-4 → Human

No backward mutation permitted.

------------------------------------------------------------------------

## 3. Portfolio Identity

Each portfolio MUST define:

-   portfolio_id (unique, immutable)
-   creation_timestamp_utc
-   constituent_run_ids (explicit list)
-   reference_capital_usd
-   capital_model_version = "v1.0_trade_close_compounding"
-   portfolio_engine_version
-   rolling_window_length (default: 252)
-   schema_version

Portfolio is a synthetic research object.

------------------------------------------------------------------------

## 4. Capital Model --- v1.0 (LOCKED)

### Model Type

Dynamic Capital Scaling --- Trade-Close Compounding

### Rules

1.  All trades from constituent runs are executed.
2.  No trade is rejected due to capital insufficiency.
3.  reference_capital_usd is the initial equity baseline.
4.  Equity updates ONLY when trades close.
5.  No mark-to-market adjustments are permitted.

------------------------------------------------------------------------

### 4.1 Equity Definition

Initial capital:

E0 = reference_capital_usd

After each trade close:

E_t = E\_(t-1) + pnl_t

------------------------------------------------------------------------

### 4.2 Return Definition

For each closed trade:

return_t = pnl_t / E\_(t-1)

Sharpe and CAGR are derived from this return series.

CAGR:

CAGR = (E_final / E0)\^(1 / years) - 1

------------------------------------------------------------------------

### 4.3 Capital Transparency (MANDATORY)

At any time t:

capital_deployed_t = sum(notional_usd of open trades)

Required metrics:

-   peak_capital_deployed
-   capital_overextension_ratio = peak_capital_deployed /
    max_equity_observed

These MUST be emitted.

------------------------------------------------------------------------

### 4.4 Concurrency Definition (AUTHORITATIVE)

Two trades A and B are considered concurrent if and only if:

entry_A < exit_B AND entry_B < exit_A

Where:

- entry_X = trade entry timestamp
- exit_X  = trade exit timestamp

This definition SHALL be used for:

- avg_concurrent_positions
- max_concurrent_positions
- capital_deployed_t
- peak_capital_deployed
- concurrency_at_entry
- capital_deployed_at_entry

Concurrency SHALL be determined exclusively using timestamp overlap logic.
No alternative approximation methods are permitted.

All concurrency calculations MUST reference a single deterministic implementation.

Any deviation constitutes metric drift and requires engine evolution.

------------------------------------------------------------------------

## 5. Portfolio Trade-Level Artifact

Each portfolio MUST emit:

portfolio_tradelevel.csv

Required fields:

-   source_run_id
-   strategy_name
-   entry_timestamp
-   exit_timestamp
-   direction
-   entry_price
-   exit_price
-   pnl_usd
-   position_units
-   notional_usd
-   bars_held
-   equity_before_trade
-   equity_after_trade
-   concurrency_at_entry
-   capital_deployed_at_entry

All portfolio metrics MUST derive exclusively from this file.

------------------------------------------------------------------------

## 6. Required Portfolio Metrics (v1.0 Minimal Set)

### 6.1 Performance

-   net_pnl_usd
-   CAGR
-   Sharpe Ratio
-   Max Drawdown (USD)
-   Max Drawdown (%)
-   Return / DD

### 6.2 Capital & Concurrency

-   peak_capital_deployed
-   capital_overextension_ratio
-   avg_concurrent_positions
-   max_concurrent_positions

### 6.3 Correlation (Minimal Scope)

Correlation MUST be computed from aligned portfolio return series.

Required metrics:

-   avg_pairwise_corr
-   max_pairwise_corr_stress

------------------------------------------------------------------------

## 7. Stress Definition (Simplified v1.0)

Stress window is defined as:

The start-to-trough period of the maximum observed portfolio drawdown.

max_pairwise_corr_stress is computed only within this window.

------------------------------------------------------------------------

## 8. Portfolio Ledger

All portfolios MUST be indexed in:

Master_Portfolio_Sheet.xlsx

Append-only.

The ledger SHALL contain the following required governance fields:

- portfolio_id
- creation_timestamp
- constituent_run_ids
- reference_capital_usd
- net_pnl_usd
- sharpe
- max_dd_pct
- return_dd_ratio
- peak_capital_deployed
- capital_overextension_ratio
- avg_pairwise_corr
- max_pairwise_corr_stress
- portfolio_engine_version

These fields constitute the minimum constitutional dataset and MUST exist for every portfolio entry.

-----------------------------------------------------------------------

### 8.1 Extended Analytical Fields (Permitted)

Additional analytical fields MAY be included in the ledger for operational visibility, provided:

- They do not replace required governance fields.
- They do not alter interpretation of required fields.
- They remain derived from authoritative portfolio artifacts.
- They do not introduce non-deterministic logic.

Examples of permitted extended fields:

- total_trades
- avg_concurrent_positions
- max_concurrent_positions
- source_strategy (if auto-discovered)
- additional diagnostic metrics

Extended fields MUST NOT:

- Modify historical rows.
- Change meaning of required fields.
- Introduce schema-breaking transformations.

-----------------------------------------------------------------------

Portfolio ledger is independent from Strategy_Master_Filter.xlsx.

It serves as a manually governed registry of portfolio evaluations.

The ledger is append-only by default.
Modification or deletion of rows requires explicit human authorization.

Portfolio registry state does not influence strategy-level governance.


------------------------------------------------------------------------

## 9. Prohibitions

Stage-4 MUST NOT:

-   Modify Stage-1 artifacts
-   Modify Stage-2 reports
-   Modify Stage-3 master sheet
-   Retroactively scale Stage-1 trade pnl
-   Apply undeclared capital reweighting
-   Influence strategy promotion decisions

Any change to capital model constitutes portfolio engine evolution.

------------------------------------------------------------------------

## 10. Reproducibility Requirement

Given:

-   constituent_run_ids
-   portfolio_metadata.json
-   portfolio_tradelevel.csv

The entire portfolio evaluation MUST be reproducible deterministically.

------------------------------------------------------------------------

## 11. Constitutional Principle

Portfolio analysis reveals structural interaction. It does not redefine
execution truth. It is synthesis, not mutation.

------------------------------------------------------------------------

END OF SOP_PORTFOLIO_ANALYSIS v1.0
