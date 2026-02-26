# AGENT DIRECTIVE — FULL CAPITAL & PORTFOLIO AUDIT (TREND SCAN)

## SECTION 1 — INDIVIDUAL ASSET ENGINE AUDIT

| Component | Finding |
| :--- | :--- |
| **Initial capital assumption** | Static baseline inherited from `broker_spec` (e.g., \$5k, \$10k). Detached from trade sizing. |
| **Position sizing model** | Fixed Lot (`min_lot` * `contract_size`). Sometimes overridden by strategy `size_multiplier`. Never equity-aware. |
| **Compounding logic** | None. Nominal position sizes remain completely static over the 19-year horizon. |
| **Slippage & spread modeling** | None. Engine executes at pure price data (`row['close']`) with zero friction modeled. |
| **Contract size normalization** | Functional. Implemented correctly via `broker_specs` and `normalize_pnl_to_usd()`. |
| **Risk calculation method** | Stop distance computed via ATR or strategy logic. Only mapped to R-multiples for post-trade reporting. |
| **Leverage and margin assumptions** | Not modeled. Zero margin constraints or capital limits applied per trade. |
| **Exposure calculation logic** | Static target notional (Units * Entry Price), entirely decoupled from running equity limits. |
| **Max risk cap per trade** | None strictly enforced. |
| **Hidden capital resets** | Implicit 100% reset on every trade. Zero path dependency (lack of compounding simulates daily profit sweep / recapitalization). |

**Inconsistencies & Distortions:**

- True Geometric Risk (risk of ruin) is neutralized due to unlimited invisible capital.
- Static lot sizing heavily overweighs early trades (% of account) and underweighs late trades.
- Zero friction models over 19 years highly inflate PnL, especially in lower timeframes.

---

## SECTION 2 — PORTFOLIO ENGINE AUDIT

| Component | Finding |
| :--- | :--- |
| **Is capital shared across symbols?** | No. Portfolio is a post-simulation linear aggregation of independent symbol backtests. |
| **Is risk allocated independently per symbol?** | Yes, completely siloed. |
| **Portfolio heat limit** | Measured post-facto (via `concurrency_profile`), but never enforced pre-entry. |
| **Correlation-aware logic** | Evaluated in Stage-3 reporting (`compute_stress_correlation`), not used to modulate active dynamic sizing. |
| **Concurrent trade handling** | Engine executes all simultaneous signals unconditionally. Assumes infinite portfolio margin. |
| **Margin aggregation model** | DATA NOT AVAILABLE. Margin requirements are not tracked or aggregated. |
| **Capital exhaustion behavior** | Unchecked limits. Trades execute even if theoretical portfolio equity < 0. |
| **Handling of overlapping signals** | 100% acceptance rate. |
| **Position rejection logic** | None. |
| **Equity curve construction method** | Linearly sums daily PnLs from isolated, fixed-size runs to a static initialization pool (`CAPITAL_PER_SYMBOL * N`). |

**Logical Flow of Portfolio Builder:**

1. Individual asset tests run completely decoupled via `run_stage1.py`.
2. Emitted artifacts are dumped as independent raw CSVs.
3. `portfolio_evaluator.py` dynamically aligns CSVs by timestamp.
4. Generates additive PnL array (`portfolio_equity = daily_pnl.cumsum() + N * 5000`).
5. Generates metrics against false compounded illusion.

**Distortions:**

- Massive overestimation of risk-adjusted returns (Sharpe/Sortino) due to infinite margin scaling.

---

## SECTION 3 — POSITION SIZING ANALYSIS

| Metric | Observation |
| :--- | :--- |
| **Risk per trade consistency (19 Yr)** | Fails geometrically. Fixed nominal lot over 19 yrs causes risk % to decay as equity grows, or inflate as drawdown deepens. |
| **Volatility regime adaptation** | Stops adapt dynamically to ATR. Trade sizing does not shrink to neutralize expanded stop distances. |
| **ATR normalization correctness** | Structurally decoupled from position sizing architecture. |
| **Risk drift over equity growth** | Severe drift. 1 Lot risks 1% at \$10k, but only 0.1% at \$100k account size. |
| **Risk clustering in correlated pairs** | Massive unaccounted tail risk. 4 highly correlated assets simultaneously firing will unilaterally 4x portfolio VaR limit. |
| **Compounding on DD acceleration** | Completely masked. Geometric drawdown devastation is entirely invisible in simple additive scaling. |
| **Portfolio-level risk stacking** | Additive theoretically without bounds up to `max_assets`. |

**Summary Matrix:**

| Model Type | Strength | Structural Weakness | Failure Mode |
| :--- | :--- | :--- | :--- |
| **Static Lot + Post-Summation** | Simple, reproducible, 100% deterministic testing. | Zero capital path dependency; mathematically invalid aggregate limits. | Unbounded drawdown in highly correlated stress environments due to unlimited leverage assumptions. |

---

## SECTION 4 — LONG-HORIZON DISTORTION CHECK (19 YEARS)

| Metric | Assessment |
| :--- | :--- |
| **Regime stability (rolling 5yr)** | Invalidated by sizing skew. Early 5-year periods register much higher relative variance than late 5-year periods. |
| **Rolling CAGR** | Distorted. High linear PnL additions late in the cycle artificially suppress mathematically scaled CAGRs. |
| **Rolling Max DD** | Nominal USD DDs mask percentage wipeouts in early trajectory. |
| **Drawdown clustering** | Captured nominally, but portfolio-level impacts are muted by unbounded capital survival. |
| **Tail risk events impact** | Drastically understated due to survival bias (inability to bankrupt). |
| **Spread regime changes effect** | 100% missing. Inflates low timeframe systems significantly during 2008 / 2020 regimes when spreads exploded. |
| **Capital path dependency bias** | Absent. The simulation evaluates pure alpha logic, not total return survival mechanics. |
| **Early equity curve overweighting** | Structurally systemic. Early sequence holds total dominant weight on nominal trajectory. |

**Assessments:**

- **Structural Fragility**: Extreme. Systems currently optimized for nominal performance will likely explode geometrically if forced into True Fixed Fractional % compounded environments.
- **Overfitting Warning**: Current evaluations over-bias toward high win-rate / low RR systems that churn raw point sums but would bleed to death via spreads and sequential capital degradation in reality.

---

## SECTION 5 — CAPITAL EFFICIENCY METRICS

| Metric | Current Computation | Institutional Reality Check |
| :--- | :--- | :--- |
| **CAGR** | Derived from linearly added PnL over static capital baseline. | Meaningless without compounding scaling. |
| **Max DD %** | Computed dynamically against linear equity peak. | Heavily masks early DD severity. |
| **Return / DD (MAR)** | Linear Nominal USD Net Profit / Nominal USD Max Drawdown. | Warped over 19 years due to size/capital drift. |
| **Ulcer Index** | DATA NOT AVAILABLE in primary standard outputs. | N/A |
| **Exposure %** | `bars_held / total_bars` logic in Stage 2. Time-based, not capital-based. | Missing portfolio delta-weighting. |
| **Return per margin used** | DATA NOT AVAILABLE. | Engine runs unconstrained. |

---

## SECTION 6 — FAILURE SCENARIOS

| Scenario | Engine Handling | Impact on Simulation |
| :--- | :--- | :--- |
| **Correlation spike event** | Engine loads all positions independently and aggregates. | Unlimited VaR stacking. Massive unrejected drawdowns. |
| **Volatility compression regime** | Fixed lot sizes blindly trade narrow ranges. | Overweighs chop/whipsaw periods ignoring true portfolio sizing limits. |
| **High spread regime**| Ignores spreads completely via raw `close` data. | Wildly inflates performance. Major flaw. |
| **Capital drawdown > 30%**| Ploughs through seamlessly. Capital goes negative seamlessly. | Masks Sequence of Return Risk and structural ruin. |
| **Sequential loss clustering**| Summed linearly in nominal USD. | Does not collapse equity geometrically, artificially lowering recovery steepness. |

---

## SECTION 7 — FINAL VERDICT

**Is current capital modeling institutionally valid?**
NO.

**Is portfolio simulation realistic?**
NO.

**Are 19-year results inflated?**
YES.

**Top 3 Structural Weaknesses:**

1. **Unconstrained Infinite Leverage:** Complete lack of shared capital awareness, margin checking, or maximum portfolio heat capping prior to trade entry.
2. **Path Dependency Deletion:** Fixed-lot non-compounding logic entirely deletes the geometric realities (and destructiveness) of sequential losses across a multi-decade timeframe.
3. **Frictionless Delusion:** Zero modeled slippage and 0-pip spreads synthetically inflate strategy expectancy, particularly crippling high-frequency/4H systems.

**Priority-Ranked Action List:**

1. Provide a Portfolio Simulation architecture to model shared capital exhaustion, overlapping margin limits, and correlation-driven pre-entry rejection.
2. Implement True Fixed Fractional position sizing logically tethered to a running equity balance to expose true sequence of return risks over the 19-year period.
3. Introduce dynamic or fixed friction models strictly attached to trade execution (Slippage + Spreads), natively in `execution_loop.py`.

*End of analysis.*
