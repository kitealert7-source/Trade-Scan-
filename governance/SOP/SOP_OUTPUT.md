# SOP_OUTPUT — Results Emission & Human Analysis (STAGE-WISE)
## VERSION 4.1 (REPORT SCHEMA & AGGREGATION CLARIFIED)

**Applies to:** Trade_Scan  
**Status:** AUTHORITATIVE | ACTIVE  
**Scope:** Post-backtest outputs, reporting, aggregation, and agent boundaries

---

## Stage-0 — Global Governance & Core Rules

### 0.1 One-Pass Rule (HARD)
Execute → Capture → Compute → Emit.  
No replay, recomputation, or mutation allowed.

### 0.2 Storage & Presentation Standards
- Percentages stored: `0.0–1.0`
- Percentages presented: `0–100`
- Dates stored: ISO8601 UTC
- Dates presented: Native Excel

### 0.3 Metric Ownership Rule (HARD)
All economic metrics are **owned by Stage-1 definitions**.  
Later stages may aggregate but must not redefine metrics.

---

## Stage-1 — Execution & Metric Emission (AUTHORITATIVE)

**Authority:** Absolute  
**Mutability:** Immutable after run completion

### 1.1 Emitted Artifacts
- `results_tradelevel.csv`
- `results_standard.csv`
- `results_risk.csv`
- `results_yearwise.csv`
- `run_metadata.json`
- `metrics_glossary.csv`

---

### 1.2 results_tradelevel.csv

| Column | Type | Definition |
|------|------|------------|
| strategy_name | String | Strategy identifier |
| parent_trade_id | Integer | Unique trade grouping ID |
| sequence_index | Integer | Zero-based leg index |
| entry_timestamp | String | ISO8601 UTC |
| exit_timestamp | String | ISO8601 UTC |
| direction | Integer | 1 = Long, -1 = Short |
| entry_price | Float | Entry execution price |
| exit_price | Float | Exit execution price |
| pnl_usd | Float | (exit − entry) × units × direction |
| r_multiple | Float | pnl_usd / risk_usd |
| trade_high | Float/NULL | Highest price during trade |
| trade_low | Float/NULL | Lowest price during trade |
| bars_held | Integer/NULL | Bars in position |
| atr_entry | Float | ATR at entry |
| position_units | Float | Executed units |
| notional_usd | Float | position_units × entry_price |
| mfe_price | Float | Max favorable price |
| mae_price | Float | Max adverse price |
| mfe_r | Float | MFE in R |
| mae_r | Float | MAE in R |

---

### 1.3 results_standard.csv

| Metric | Type | Definition | Formula |
|------|------|------------|---------|
| net_pnl_usd | Float | Net profit | SUM(pnl_usd) |
| trade_count | Integer | Total trades | COUNT |
| win_rate | Float | Win fraction | wins / trades |
| profit_factor | Float | GP / GL | gross_profit / gross_loss |
| gross_profit | Float | Sum of wins | Σ pnl > 0 |
| gross_loss | Float | Sum of losses | ABS Σ pnl < 0 |

---

### 1.4 results_risk.csv

| Metric | Type | Definition | Formula |
|------|------|------------|---------|
| max_drawdown_usd | Float | Max peak-to-trough | max(peak − equity) |
| max_drawdown_pct | Float | DD % | dd / capital |
| return_dd_ratio | Float | Return / DD | net_pnl / dd |

---

### 1.5 results_yearwise.csv

| Column | Type | Definition |
|------|------|------------|
| year | Integer | Calendar year |
| net_pnl_usd | Float | Net profit |
| trade_count | Integer | Trades |
| win_rate | Float | Win rate |

---

### 1.6 run_metadata.json (MANDATORY — EXTENDED)

**Purpose:** Run identification, execution context, and capital reference.

#### Required Fields (HARD)
| Field | Type | Description |
|------|------|-------------|
| run_id | String | Unique run identifier (UUID) |
| strategy_name | String | Strategy identifier |
| symbol | String | Traded instrument |
| timeframe | String | Execution timeframe |
| date_range.start | String | ISO start date |
| date_range.end | String | ISO end date |
| execution_timestamp_utc | String | ISO8601 UTC execution time |
| engine_name | String | Execution engine |
| engine_version | String | Engine version |
| broker | String | Broker or data source |
| schema_version | String | Metadata schema version |
| reference_capital_usd | Float | Capital baseline for drawdown % and risk metrics |

**Rules**
- All fields above MUST exist for a run to be valid
- No field may be mutated post RUN_COMPLETE
- Additional fields are allowed only if non-derivative and informational

### 1.7 metrics_glossary.csv

| Field | Description |
|------|-------------|
| metric_key | Canonical key |
| full_name | Human name |
| definition | Formal definition |
| unit | Measurement unit |

---

## Stage-2 — Presentation & Reporting (NON-AUTHORITATIVE)

**Authority:** Deterministic presentation  
**Metric Ownership:** Stage-1  
**New Measurements:** Forbidden  
**Derivation & Aggregation:** Permitted (see rule below)

### Stage-2 Derivation & Aggregation Rule (CRITICAL)

Stage-2 MAY derive metrics **whose formulas depend exclusively on Stage-1 emitted fields and do not require reconstruction of capital or volatility paths**.

Stage-2 MAY perform:
- Arithmetic derivations using Stage-1 fields (ratios, averages, percentages)
- SUM, COUNT, AVG, MAX, MIN
- Grouping by year, session, direction, or **pre-emitted** regime labels
- Formatting, scaling, and ordering for presentation

Stage-2 MUST NOT:
- Reconstruct equity curves, capital paths, or volatility paths
- Recompute drawdown trajectories or risk paths
- Infer regimes, risk states, or missing execution values
- Use external data
- Alter Stage-1 formulas or redefine metric meaning

All Stage-2 outputs MUST be reproducible from immutable Stage-1 artifacts.

Derivation and aggregation are **presentation logic**, not execution or measurement.


---

### 2.1 AK Trade Report

**File:** `AK_Trade_Report_<strategy_name>_<NN>.xlsx`  
**Cardinality:** Exactly one report per completed run

#### Sheets & Sources
| Sheet | Source |
|------|--------|
| Settings | run_metadata.json |
| Performance Summary | Stage-2 aggregated from Stage-1 |
| Yearwise Performance | Stage-2 aggregated from Stage-1 |
| Trades List | results_tradelevel.csv |

---

### 2.2 Performance Summary — REQUIRED ROW SCHEMA (LOCKED)

Rows MUST appear in this exact order.

**Capital & Profitability**
- Starting Capital
- Net Profit (USD)
- Gross Profit (USD)
- Gross Loss (USD)
- Profit Factor
- Expectancy (USD)
- Return / Drawdown Ratio

**Trade Activity**
- Total Trades
- Winning Trades
- Losing Trades
- % Profitable
- Trades per Month
- Longest Flat Period (Days)

**Averages & Trade Quality**
- Avg Trade (USD)
- Avg Win (USD)
- Avg Loss (USD)
- Win/Loss Ratio
- Avg MFE (R)
- Avg MAE (R)
- Edge Ratio (MFE / MAE)

**Extremes & Concentration**
- Largest Win (USD)
- Largest Loss (USD)
- % of Gross Profit (Top Trades)
- Worst 5 Trades Loss %

**Streaks**
- Max Consecutive Wins
- Max Consecutive Losses

**Drawdown & Exposure**
- Max Drawdown (USD)
- Max Drawdown (%)
- Return on Capital
- % Time in Market

**Risk & System Quality**
- Sharpe Ratio
- Sortino Ratio
- K-Ratio
- SQN (System Quality Number)
- Return Retracement Ratio

**Duration**
- Avg Bars in Winning Trades
- Avg Bars in Losing Trades
- Avg Bars per Trade
- Trading Period (Days)

**Volatility Regime Breakdown**
- Net Profit (Low Vol)
- Net Profit (Normal Vol)
- Net Profit (High Vol)
- Trade Count (Low / Normal / High)
- Avg Trade by Regime

**Session Breakdown**
- Net Profit (Asia)
- Net Profit (London)
- Net Profit (New York)
- Trade Count by Session
- Avg Trade by Session

**Buy & Hold Comparison (LOCKED)**
- Buy & Hold Return (%)
- Strategy Return (%)
- Excess Return (%)
- Buy & Hold Trading Period (Days)
-If underlying market price series are unavailable, a trade-derived Buy & Hold benchmark MAY be computed 
  from the first trade entry price and last trade exit price, provided it is explicitly labeled 
  “Trade-Derived Buy & Hold (Contextual Only)” and excluded from Stage-3 comparisons.
---

### 2.3 Yearwise Performance — REQUIRED SCHEMA

**One row per calendar year. Values only.**

| Column |
|------|
| Year |
| Net Profit (USD) |
| Gross Profit (USD) |
| Gross Loss (USD) |
| Trade Count |
| Win Rate (%) |
| Profit Factor |
| Avg Trade (USD) |
| Max Drawdown (USD) |
| Max Drawdown (%) |
| Return / DD Ratio |
| Avg Bars per Trade |
| Winning Trades |
| Losing Trades |

**Source Rules**
- Year, Net Profit, Trade Count, Win Rate → `results_yearwise.csv`
- All other fields → aggregated from `results_tradelevel.csv`
- Scaling and definitions must match Performance Summary

---

## Stage-3 — Aggregation & Comparison (NON-AUTHORITATIVE)

**Authority:** Copy-only  
**Computation:** Forbidden

### 3.1 Strategy Master Filter

**File Location:**  
`backtests/<strategy_name>/Strategy_Master_Filter.xlsx`

**Scope Rules**
- Per-strategy, run-level aggregation only
- Aggregates sequential runs of the same strategy
- Exactly one row per atomically completed run
- Trade-level fields are explicitly forbidden

**Schema (MANDATORY)**

| Column | Description |
|--------|-------------|
| strategy_name | Strategy identifier |
| strategy | Strategy ID |
| timeframe | Execution timeframe |
| test_start | Start date (ISO) |
| test_end | End date (ISO) |
| trading_period | Days covered |
| total_trades | Trade count |
| total_net_profit | Net PnL (USD) |
| gross_profit | Gross profit (USD) |
| gross_loss | Gross loss (USD) |
| profit_factor | Profit factor |
| max_drawdown | Max drawdown (USD) |
| max_dd_pct | Max drawdown % |
| return_dd_ratio | Net profit / max DD |
| worst_5_loss_pct | Concentration risk |
| longest_loss_streak | Max loss streak |
| pct_time_in_market | Exposure % |
| avg_bars_in_trade | Avg duration |
| max_consec_losses | Max consecutive losses |
| trading_days | Active trading days |
| net_profit_high_vol | PnL in high volatility |
| net_profit_low_vol | PnL in low volatility |
| sharpe_ratio | Sharpe ratio |
| expectancy | Expectancy (USD) |

**Population Rule**
Populated via standard reporting pipeline only.  
No manual entry permitted.

**Formatting Rules**
- Percentages: `43` (0–100 integer scale)
- Currency: `#,##0.00`
- Dates: Native Excel
- Numbers: `#,##0`
- Headers: Bold, dark blue fill, freeze top row
- Append-only

---

## Stage-4 — Update & Run Integrity Rules

- One completed run → one report → one master row
- Failed or partial runs emit nothing
- Corrections require new run + new index

---

## Stage-5 — Strategy Persistence (POST-RUN INVARIANT)

- For every completed backtest run, the executed strategy logic MUST be saved to:
  `strategies/<RUN_ID>/strategy.py`
- Strategy folders MUST contain only:
  - `strategy.py`
  - `__pycache__/`
- This structure reflects the architecture where strategy logic is decoupled from execution.
- The `strategies/` directory is a mirror of `backtests/`.
- If a backtest folder is deleted, the corresponding strategy folder MUST also be deleted.

---

## Stage-6 — Agent Boundary (FINAL GATE)

Agents are advisory only.

Agents MUST NOT:
- Modify Stage-1 artifacts
- Recompute metrics
- Treat presentation outputs as authoritative
- Rank, promote, or select strategies

---

**End of SOP — VERSION 4.1**
