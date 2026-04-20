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

Portfolio analysis:

- Operates only on RUN_COMPLETE strategies
- Does not alter Stage-1, Stage-2, or Stage-3 artifacts
- Produces independent portfolio artifacts
- Maintains strict forward-only flow

Portfolio analysis is structural synthesis, not execution truth.

------------------------------------------------------------------------

## 2. Authority & Directionality (HARD)

Stage-4:

- MAY read Stage-1, Stage-2, and Stage-3 artifacts
- MUST NOT modify any prior artifact
- MUST NOT write to Strategy_Master_Filter.xlsx
- MUST NOT trigger cleanup
- MUST NOT influence strategy registry state

Flow is strictly:

Stage-1 → Stage-2 → Stage-3 → Stage-4 → Human

No backward mutation permitted.

------------------------------------------------------------------------

## 3. Portfolio Identity

Each portfolio MUST define:

- portfolio_id (unique, immutable)
- creation_timestamp_utc
- constituent_run_ids (explicit list)
- reference_capital_usd
- capital_model_version = "v2.0_profile_based_scaling"
- deployed_profile (selected capital profile — one of `RAW_MIN_LOT_V1`, `FIXED_USD_V1`, `REAL_MODEL_V1`)
- portfolio_engine_version
- rolling_window_length (default: 252)
- schema_version

Portfolio is a synthetic research object.

------------------------------------------------------------------------

## 4. Capital Model --- v2.0 (Profile-Based Scaling)

### Model Type

Profile-Based Capital Allocation with Dynamic Scaling

### Rules

1. Trades from constituent runs are evaluated against the active capital profile.
2. Trades MAY be rejected if position sizing violates heat cap, leverage cap, or lot constraints.
3. reference_capital_usd is the initial equity baseline (default: $10,000).
4. Equity updates ONLY when trades close.
5. No mark-to-market adjustments are permitted.
6. EXIT events are processed before ENTRY events at the same timestamp.

------------------------------------------------------------------------

### 4.5 Capital Profiles (v3.0 — Retail Amateur Model, effective 2026-04-16)

Three profiles are evaluated for every portfolio. The v2.0 institutional set
(`DYNAMIC_V1`, `CONSERVATIVE_V1`, `FIXED_USD_V1`/$10k/$50, plus `MIN_LOT_FALLBACK_V1`,
`MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1`) has been **retired** — it
modelled desk-style portfolio heat / leverage caps that do not apply to a single
retail OctaFx account.

**RAW_MIN_LOT_V1** — diagnostic baseline

- starting_capital = $1,000
- raw_lot_mode = True (0.01 lot unconditionally, no risk/heat/leverage gates)
- min_lot = 0.01, lot_step = 0.01
- Purpose: "Is the directional edge real?" probe, independent of sizing.

**FIXED_USD_V1** — retail conservative

- starting_capital = $1,000
- risk_per_trade = 0.02
- fixed_risk_usd_floor = $20  (effective risk = max(2% of equity, $20))
- heat_cap = 9999 (disabled), leverage_cap = 9999 (disabled)
- min_lot = 0.01, lot_step = 0.01
- Sub-min_lot trades SKIP honestly — no fallback.

**REAL_MODEL_V1** — retail aggressive (tier-ramp)

- starting_capital = $1,000
- risk_per_trade = 0.02 (base)
- tier_ramp = True, tier_base_pct = 0.02, tier_step_pct = 0.01, tier_cap_pct = 0.05, tier_multiplier = 2.0
  (risk steps +1% each time equity doubles from start, capped at 5%; symmetric on retracement)
- heat_cap = 9999 (disabled), leverage_cap = 9999 (disabled)
- retail_max_lot = 10.0  (trades requiring more than 10 lots SKIP; OctaFx vol_max=500 is admin/marketing)
- min_lot = 0.01, lot_step = 0.01

Profiles are evaluated by `tools/capital_wrapper.py` — definitive spec is the
`PROFILES` dict in that file.
Profile artifacts are emitted to `strategies/<portfolio_id>/deployable/<PROFILE>/`.

**Parallel reference model — REAL_MODEL_V1 (always-on, CORE only)**

`tools/real_model_evaluator.py` writes `Real_Model_Evaluation.xlsx` as an
independent pooled-equity reference for every MPS row with `portfolio_status='CORE'`.
It is a cross-check, NOT part of profile selection — its output never feeds into
`deployed_profile`.

------------------------------------------------------------------------

### 4.6 Profile Selection

After all profiles are evaluated, `tools/profile_selector.py` selects
the best-performing profile per strategy using:

    selection_metric = realized_pnl / max_drawdown (Return/DD ratio)

Rules:

- Profiles with zero realized PnL are excluded.
- Profiles with zero max drawdown receive infinite Return/DD and are preferred.
- Ties are broken by realized PnL.
- The selected profile is recorded as `deployed_profile` in `Master_Portfolio_Sheet.xlsx`.

Profile selection is deterministic and idempotent.

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

- peak_capital_deployed
- capital_overextension_ratio = peak_capital_deployed /
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

Concurrency calculation functions MUST be side-effect free (PURE) and IDEMPOTENT. They must not mutate the input DataFrame.

------------------------------------------------------------------------

## 5. Strategy Master Filter (Stage-3) — Regime-Aware Metrics

The Strategy Master Filter aggregates finalized Stage-1 trade artifacts.

It MUST:

- Operate strictly on emitted trade-level metadata.
- Preserve volatility_regime and trend_regime dimensions.
- Never recompute or reclassify market state.
- Persist regime-based breakdown metrics as first-class evaluation axes.

Each portfolio MUST emit:

portfolio_tradelevel.csv

Required fields:

- source_run_id
- strategy_name
- entry_timestamp
- exit_timestamp
- direction
- entry_price
- exit_price
- pnl_usd
- position_units
- notional_usd
- bars_held
- equity_before_trade
- equity_after_trade
- concurrency_at_entry
- capital_deployed_at_entry

All portfolio metrics MUST derive exclusively from this file.

### 5.1 Market State Breakdown Requirements

Stage-3 MUST compute and persist:

Volatility Dimension:

- net_profit_high_vol
- net_profit_normal_vol
- net_profit_low_vol

Trend Dimension:

- net_profit_strong_up
- net_profit_weak_up
- net_profit_neutral
- net_profit_weak_down
- net_profit_strong_down
- trades_strong_up
- trades_weak_up
- trades_neutral
- trades_weak_down
- trades_strong_down

These metrics are mandatory analytical outputs.

They:

- MUST use Stage-1 emitted metadata.
- MUST NOT derive new classifications.
- MUST remain deterministic.

---

### 5.2 Evaluation Philosophy

Strategy evaluation is multi-dimensional.

Performance must be assessed across:

- Absolute performance
- Risk-adjusted performance
- Volatility regime exposure
- Trend regime exposure
- Capital efficiency

Regime dimensions are not optional filters.
They are structural evaluation axes.

------------------------------------------------------------------------

## 6. Required Portfolio Metrics (v1.0 Minimal Set)

### 6.1 Performance

- net_pnl_usd
- CAGR
- Sharpe Ratio
- Max Drawdown (USD)
- Max Drawdown (%) (Stored as 0.0-1.0 decimal)
- Return / DD

### 6.2 Capital & Concurrency

- peak_capital_deployed
- capital_overextension_ratio
- avg_concurrent
- max_concurrent

### 6.3 Correlation (Minimal Scope)

Correlation MUST be computed from aligned portfolio return series.

Required metrics:

- avg_pairwise_corr
- max_pairwise_corr_stress

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
- deployed_profile
- realized_pnl_usd
- trades_accepted
- trades_rejected
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

### 8.2 Technical Implementation Constraints (Governance)

- **Zero OpenPyXL**: Engines MUST NOT import `openpyxl`. All Excel styling MUST be delegated to `tools/format_excel_artifact.py`.
- **Decimal Storage**: All percentage metrics MUST be stored as decimals (e.g. `0.125` for 12.5%).
- **No Checkpoint Rounding**: Computing functions MUST NOT round intermediate float values. Rounding is a presentation-layer concern only.

-----------------------------------------------------------------------

Portfolio ledger is independent from Strategy_Master_Filter.xlsx.

It serves as a manually governed registry of portfolio evaluations.

The ledger is append-only by default.
Modification or deletion of rows requires explicit human authorization.

Portfolio registry state does not influence strategy-level governance.

------------------------------------------------------------------------

## 9. Prohibitions

Stage-4 MUST NOT:

- Modify Stage-1 artifacts
- Modify Stage-2 reports
- Modify Stage-3 master sheet
- Retroactively scale Stage-1 trade pnl
- Apply undeclared capital reweighting
- Influence strategy promotion decisions

Any change to capital model constitutes portfolio engine evolution.

------------------------------------------------------------------------

## 10. Reproducibility Requirement

Given:

- constituent_run_ids
- portfolio_metadata.json
- portfolio_tradelevel.csv

The entire portfolio evaluation MUST be reproducible deterministically.

------------------------------------------------------------------------

## 11. Constitutional Principle

Portfolio analysis reveals structural interaction. It does not redefine
execution truth. It is synthesis, not mutation.

------------------------------------------------------------------------

END OF SOP_PORTFOLIO_ANALYSIS v1.0
