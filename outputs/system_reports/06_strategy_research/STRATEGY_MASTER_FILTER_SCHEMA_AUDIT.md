# Strategy_Master_Filter Schema Audit Report

This report provides a detailed schema audit of the `Strategy_Master_Filter.xlsx` sheet, identifying field sources, classifications, and calculation formulas to support Phase-2 lifecycle documentation.

## 1. Source Identification
- **Source File**: `backtests\Strategy_Master_Filter.xlsx`
- **Primary Generation Script**: `tools\stage3_compiler.py`
- **Maintenance Script**: `tools\migrate_trade_density.py`
- **Filtering Script**: `tools\filter_strategies.py`

---

## 2. Column Schema & Classification

The following table documents the full column schema in the order it appears in the master sheet:

| Column Name | Type | Source | Formula / Description |
| :--- | :--- | :--- | :--- |
| **run_id** | metadata | directive | Unique run identifier (e.g., hash) |
| **strategy** | metadata | directive | Strategy name (strategy_name) |
| **symbol** | metadata | directive | Trading symbol |
| **timeframe** | metadata | directive | Trading timeframe |
| **test_start** | metadata | directive | Backtest start date |
| **test_end** | metadata | directive | Backtest end date |
| **trading_period** | raw | AK_Trade_Report | Duration of test in days |
| **total_trades** | raw | AK_Trade_Report | Number of trades executed |
| **trade_density** | **derived** | `stage3_compiler.py` | `round(total_trades / (trading_period / 365.25))` |
| **total_net_profit** | raw | AK_Trade_Report | Net profit in USD |
| **gross_profit** | raw | AK_Trade_Report | Gross profit in USD |
| **gross_loss** | raw | AK_Trade_Report | Gross loss in USD |
| **profit_factor** | raw | AK_Trade_Report | Gross Profit / Gross Loss |
| **expectancy** | raw | AK_Trade_Report | Average profit per trade in USD |
| **sharpe_ratio** | raw | AK_Trade_Report | Risk-adjusted return metric |
| **max_drawdown** | raw | AK_Trade_Report | Maximum peak-to-valley loss in USD |
| **max_dd_pct** | raw | AK_Trade_Report | Maximum drawdown as a % |
| **return_dd_ratio** | raw | AK_Trade_Report | Total Net Profit / Max Drawdown (USD) |
| **worst_5_loss_pct** | raw | AK_Trade_Report | Cumulative % loss of worst 5 trades |
| **longest_loss_streak** | raw | AK_Trade_Report | Max consecutive losing trades |
| **pct_time_in_market** | raw | AK_Trade_Report | % of bars with active exposure |
| **avg_bars_in_trade** | raw | AK_Trade_Report | Average duration of trades in bars |
| **net_profit_high_vol** | raw | AK_Trade_Report | Net profit during high volatility periods |
| **net_profit_normal_vol** | raw | AK_Trade_Report | Net profit during normal volatility periods |
| **net_profit_low_vol** | raw | AK_Trade_Report | Net profit during low volatility periods |
| **net_profit_asia** | raw | AK_Trade_Report | Net profit during Asian session |
| **net_profit_london** | raw | AK_Trade_Report | Net profit during London session |
| **net_profit_ny** | raw | AK_Trade_Report | Net profit during New York session |
| **net_profit_[regime]** | raw | tradelevel.csv | Net profit per trend regime (strong_up, etc.) |
| **trades_[regime]** | raw | tradelevel.csv | Trade count per trend regime |
| **IN_PORTFOLIO** | metadata | manual | Boolean flag for portfolio inclusion |

---

## 3. Promotion Logic Verification

The current strict filter (`tools\filter_strategies.py`) uses the following metrics and thresholds for promoting sandbox strategies to `Filtered_Strategies_Passed.xlsx`:

- **Profit Factor**: $\geq 1.3$
- **Return / DD Ratio**: $\geq 1.8$
- **Expectancy**: $\geq 2.5$
- **Total Trades**: $\geq 80$
- **Sharpe Ratio**: $\geq 1.2$

### 4. Gaps & Observations
- **Trade Density**: Used as a FAIL gate in `_compute_portfolio_status()` (`trade_density < 50` → FAIL). Prevents multi-symbol portfolios from passing the accepted trades threshold when per-symbol sample sizes are statistically meaningless. Also used in `filter_strategies.py` for CORE classification (`trade_density >= 50`).
- **Trend Regime Metrics**: These are populated but not yet integrated into the automated filtering criteria.
- **Formula Visibility**: Formulas are not embedded in the Excel cells (values are written as opaque scalars by pandas), but they are explicitly defined in the generation scripts.
