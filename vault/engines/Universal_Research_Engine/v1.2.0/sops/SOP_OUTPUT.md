# SOP_OUTPUT — Results Emission & Human Analysis (COMPACT)

**Stage:** POST_BACKTEST | HUMAN_CONSUMPTION  
**Applies to:** Trade_Scan  
**Status:** AUTHORITATIVE | ACTIVE | COMPLEMENTS SOP_TESTING

---

## 1. Core Rules

| Rule | Specification |
|------|---------------|
| **One-Pass** | Execute → Capture → Compute → Emit. No replay/recomputation. |
| **Storage Format** | Percentages: `43.00` (0-100 scale, NOT 0.43). Dates: ISO8601 UTC. |
| **Presentation Format** | Percentages: `0-100`. Dates: Native Excel. |

---

## 2. Pipeline

| Stage | Artifacts | Authority |
|------|-----------|-----------|
| **Stage 1** | `results_*.csv`, `run_metadata.json` | Authoritative execution record. Immutable. |
| **Stage 2** | `AK_Trade_Report_<strategy_name>_<NN>.xlsx` | Deterministic derived presentation. |
| **Stage 3** | `Strategy_Master_Filter.xlsx` | Aggregated comparison view. Non-authoritative. |

Flow is strictly Stage 1 → Stage 2 → Stage 3.

- Stage 2 MAY compute presentation metrics only from Stage-1 artifacts.
- Stage 3 MUST only compile and aggregate Stage-2 outputs.
- No recomputation, inference, approximation, or metric creation is permitted outside Stage-2.
- Any metric appearing in Stage-2 MUST be fully materialized as a scalar value.

---

## 3. Directory Structure

```
backtests/<strategy_name>/
├── raw/
│ ├── results_tradelevel.csv
│ ├── results_standard.csv
│ ├── results_risk.csv
│ ├── results_yearwise.csv
│ └── metrics_glossary.csv
├── metadata/
│ └── run_metadata.json
├── <directive_copy>.md
├── AK_Trade_Report_<strategy_name>_<NN>.xlsx
└── Strategy_Master_Filter.xlsx 

All files are append-only.  
No files outside this structure are read or written by SOP_OUTPUT.

```



## 4. Required Artifacts 

### 4.1 results_tradelevel.csv (Authoritative Record)

| Column | Type | Notes |
|------|------|------|
| `strategy_name` | String | Strategy identifier |
| `parent_trade_id` | Integer | Identifier grouping multiple legs (MANDATORY) |
| `sequence_index` | Integer | Zero-based leg order within parent trade (MANDATORY) |
| `entry_timestamp` | String | ISO8601 UTC |
| `exit_timestamp` | String | ISO8601 UTC |
| `direction` | Integer | 1 = Long, -1 = Short |
| `entry_price` | Float | |
| `exit_price` | Float | |
| `pnl_usd` | Float | 2 decimal places |
| `r_multiple` | Float | |
| `trade_high` | Float / NULL | |
| `trade_low` | Float / NULL | |
| `bars_held` | Integer / NULL | |


### 4.2 results_standard.csv

Core run-level performance metrics emitted as authoritative execution artifacts.

All percentage-based metrics in this file MUST be stored as decimals
in the range 0.0–1.0.

Metrics:
- `net_pnl_usd`          — Net profit (USD)
- `win_rate`             — Win rate (decimal 0.0–1.0; presented as 0–100% in reports)
- `profit_factor`        — Gross profit / Gross loss
- `trade_count`          — Total number of trades



### 4.3 results_risk.csv

Risk metrics. See glossary.

### 4.4 results_yearwise.csv

One row per year: `year` (Integer) + metrics.

### 4.5 run_metadata.json

Required fields: `run_id`, `strategy_name`, `symbol`, `timeframe`, `date_range`, `execution_timestamp_utc`.

### 4.6 metrics_glossary.csv

Fields: `metric_key`, `full_name`, `definition`, `unit`.

---

## 5. AK Trade Report 

**File:** experiments/<strategy_name>AK_Trade_Report_<strategy_name>_<NN>.xlsx
- `<NN>` is sequential, append-only
- Exactly **one** report per completed run

| Sheet | Source |
|-------|--------|
| Settings | `run_metadata.json` |
| Performance Summary | `results_standard.csv` (scaled) |
| Yearwise Performance | `results_yearwise.csv` (scaled) |
| Trades List | `results_tradelevel.csv` |

**Formatting Rules:**
| Element | Format |
|---------|--------|
| Percentages | `43.00` (0-100 scale, NOT 0.43) |
| Currency | `$#,##0.00` |
| Dates | Native Excel dates (timezone-naive) |
| Numbers | `#,##0` (comma separator), rounded to 2 decimals |
| Headers | Bold, white text, dark blue fill (`#4472C4`), Freeze Top Row |
| Columns | Auto-fit width |
| Alternate Rows | Light blue shading (`#DCE6F1`) |

### 5.1 Performance Summary Schema (Mandatory)

Performance Summary Sheet — Required Structure in order

| Section                         | Rows  | Metrics                                                                 |
|---------------------------------|-------|-------------------------------------------------------------------------|
| Title                           | 1     | Strategy Performance Summary                                            |
| Headers                         | 3     | Metric / All Trades / Long Trades / Short Trades                        |

| Capital & Profitability         | 4–10  | Starting Capital, Net Profit (USD), Gross Profit (USD),                 |
|                                 |       | Gross Loss (USD), Profit Factor, Expectancy (USD),                      |
|                                 |       | Return / Drawdown Ratio                                                 |

| Trade Activity                  | 12–18 | Total Trades, Winning Trades, Losing Trades, % Profitable,              |
|                                 |       | Trades per Month, Longest Flat Period (Days)                            |

| Averages & Trade Quality        | 20–27 | Avg Trade (USD), Avg Win (USD), Avg Loss (USD),                          |
|                                 |       | Win/Loss Ratio, Avg MFE (R), Avg MAE (R),                                |
|                                 |       | Edge Ratio (MFE / MAE)                                                   |

| Extremes & Concentration        | 29–33 | Largest Win (USD), Largest Loss (USD),                                   |
|                                 |       | % of Gross Profit (Top Trades), Worst 5 Trades Loss %                   |

| Streaks                         | 35–36 | Max Consecutive Wins, Max Consecutive Losses                             |

| Drawdown & Exposure             | 38–41 | Max Drawdown (USD), Max Drawdown (%),                                    |
|                                 |       | Return on Capital, % Time in Market                                      |

| Risk & System Quality           | 43–47 | Sharpe Ratio, Sortino Ratio, K-Ratio,                                    |
|                                 |       | SQN (System Quality Number),                                             |
|                                 |       | Return Retracement Ratio                                                 |

| Duration                        | 49–52 | Avg Bars in Winning Trades, Avg Bars in Losing Trades,                   |
|                                 |       | Avg Bars per Trade, Trading Period (Days)                                |

| Volatility Regime Breakdown     | 54–64 | Net Profit by Low / Normal / High Volatility,                            |
|                                 |       | Trade Counts by Regime, Avg Trade by Regime                              |

| Session Breakdown               | 66–76 | Net Profit by Asia / London / New York,                                  |
|                                 |       | Trade Counts by Session, Avg Trade by Session                            |
| Buy & Hold Comparison           | 78–82 | Buy & Hold Return (%), |
|                                 |       | Strategy Return (%), |
|                                 |       | Excess Return (%), |
|                                 |       | Buy & Hold Trading Period (Days) |

Buy & Hold Definition (LOCKED)

Buy & Hold Definition (LOCKED)
Buy & Hold = long on the same symbol/timeframe from first bar close to final bar close, with no rebalancing or leverage changes.
Governance Rule
Buy & Hold metrics are contextual only, must use the same price series, must not influence execution or decisions, and must not appear in Stage-3.

#### Computational Inputs (Execution-Derived, Non-Surfaced)

Certain metrics used in the computation of Performance Summary values are
execution-derived inputs that may not appear explicitly as rows or columns
in the report.

These metrics:
- originate exclusively from immutable Stage-1 execution artifacts
- are used only to ensure correctness of reported metrics
- are not independently surfaced or reported

Permitted execution-derived computational inputs include:
- atr_entry
- position_units
- notional_usd
- mfe_price, mae_price
- mfe_r, mae_r

These inputs MAY be used by Stage-2 solely to compute or normalize metrics
already defined in the Performance Summary schema.

Metric Availability Rule (HARD)

All metrics presented in Stage-2 reports MUST be derived exclusively from
immutable Stage-1 execution artifacts.

Stage-2 MAY use additional execution-derived inputs for internal computation,
but MUST NOT surface metrics outside the schemas defined in this SOP.

Stage-3 aggregation is strictly copy-only.

No metric may be computed, recomputed, inferred, or derived outside this sheet.


### 5.2 — Yearwise Performance (MANDATORY)

Sheet: Yearwise Performance
Stage: Stage-2 (derived presentation)
Purpose: Stability and year-to-year consistency

Rules
One row per calendar year
Scalar values only (no formulas)
Percentages shown on 0–100 scale
Formatting identical to Performance Summary
Stage-3 is copy-only; no recomputation

Required Columns (Exact Order)
Column
Year
Net Profit (USD)
Gross Profit (USD)
Gross Loss (USD)
Trade Count
Win Rate (%)
Profit Factor
Avg Trade (USD)
Max Drawdown (USD)
Max Drawdown (%)
Return / DD Ratio
Avg Bars per Trade
Winning Trades
Losing Trades
Source Rules

Year, Net Profit, Trade Count, Win Rate → results_yearwise.csv
All other columns → derived in Stage-2 from results_tradelevel.csv
Definitions and scaling must match Performance Summary
Hard Constraint
All columns above MUST exist in:
AK_Trade_Report_<strategy_name>_<NN>.xlsx
No Yearwise metric may be computed outside Stage-2.

## 6. Strategy Master Filter

**File Location (MANDATORY):**
backtests/<strategy_name>/Strategy_Master_Filter.xlsx

**Scope:**
- Per-strategy, run-level aggregation only
- Aggregates sequential runs of the same strategy
- Exactly one row per atomically completed run
- Trade-level fields are explicitly forbidden


| Column | Description |
|--------|-------------|
| `strategy_name` | Integer | Sequential |
| `strategy` | Strategy ID |
| `timeframe` | Execution Timeframe |
| `test_start` | Start Date (ISO) |
| `test_end` | End Date (ISO) |
| `trading_period` | Days covered |
| `total_trades` | Trade Count |
| `total_net_profit` | Net PnL (USD) |
| `gross_profit` | Gross Profit (USD) |
| `gross_loss` | Gross Loss (USD) |
| `profit_factor` | Profit Factor |
| `max_drawdown` | Max DD (USD) |
| `max_dd_pct` | Max DD % |
| `return_dd_ratio` | Net Profit / Max DD |
| `worst_5_loss_pct` | Concentration Risk |
| `longest_loss_streak` | Max consecutive losses |
| `pct_time_in_market` | Exposure Time % |
| `avg_bars_in_trade` | Avg Duration |
| `max_consec_losses` | Max consecutive losses |
| `trading_days` | Active trading days |
| `net_profit_high_vol` | PnL in High Vol regime |
| `net_profit_low_vol` | PnL in Low Vol regime |
| `sharpe_ratio` | Sharpe Ratio |
| `expectancy` | Expectancy (USD) |

**Population:** Via Standard Reporting Pipeline only. No manual entry.

**Formatting Rules:**
| Element | Format |
|---------|--------|
| Percentages | `43` (0-100 INTEGER scale, NOT 0.43 or 43.00%) |
| Currency | `#,##0.00` |
| Dates | Native Excel dates |
| Numbers | `#,##0` (comma separator) |
| Headers | Bold, white text, dark blue fill (`#4472C4`), Freeze Top Row |
| Columns | Auto-fit width |
| Alternate Rows | Light blue shading (`#DCE6F1`) |

---

## 7. Update Rules

- Each completed run generates **one** `AK_Trade_Report_<strategy_name>_<NN>.xlsx`.
- Master Filter receives **one** new row per completed run.
- **Append-only.** No modifications to existing reports/rows.
- Corrections require **new run + new index**.
- Failed runs produce **no artifacts**.

---

## 8. Agent Boundary

All agent analysis is **advisory only**.
Agents MUST NOT:
- Modify authoritative execution artifacts or derived presentation artifacts
- Recompute execution metrics
- Treat presentation or analysis outputs as authoritative
- Make promotion, ranking, or selection decisions


---

**End of SOP**
