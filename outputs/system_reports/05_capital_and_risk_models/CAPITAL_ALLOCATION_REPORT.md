# Capital Allocation Investigation Report

## 1. Where does the $5,000 per asset originate?
The pipeline currently utilizes a hardcoded, static top-level capitalization of **$10,000**, regardless of how many assets are included in the portfolio:
* **`portfolio_evaluator.py`**: Defines `TOTAL_PORTFOLIO_CAPITAL = 10000.0`. When this evaluates a 2-asset portfolio, the math inherently resolves to **$5,000 per asset**, which is exactly what you are seeing written to the `reference_capital_usd` column in the Master Portfolio Sheet.
* **`capital_wrapper.py`**: Every single capital profile (`CONSERVATIVE_V1`, `MIN_LOT_FALLBACK_V1`, etc.) hardcodes `starting_capital: 10000.0` as its sizing baseline.

## 2. Does this affect the Robustness Reports?
**Yes, significantly.** Because the `capital_wrapper` sizes and filters trades (like heat cap limits and margin limits) against a $10,000 account rather than your intended $2,000 account (2 assets @ $1k):
* **Diluted Drawdowns:** The Robustness Report measures drawdown percentages against the mathematical peak of the account. A $300 drawdown on a $10,000 account is a highly-masked 3% DD, but on your intended $2,000 account, it should accurately register as a 15% DD.
* **Concurrency Bypass (Heat Cap):** The profiles implement a 4% `heat_cap`. On a $10k account, the wrapper allows up to $400 in simultaneous risk. On a $2k account, it should strictly cap at $80. Therefore, the engine is currently bypassing necessary concurrency rejections and allowing too many overlapping trades.
* **Concurrency Bypass (Leverage Cap):** As you astutely noted, the profiles (such as `CONSERVATIVE_V1` and `MIN_LOT_FALLBACK_V1`) implement a `leverage_cap: 5`. On an inflated $10,000 account, the engine allows up to **$50,000** in simultaneous notional exposure. If the account were correctly sized to $2,000, the ceiling would strictly be **$10,000**. This massive 5x artificial buffer is further allowing trades to bypass intended exposure limits during the robustness test.

## 3. Should the framework be updated?
**Yes**, the current hardcoded $10,000 logic heavily distorts the live probability modeling if your actual allocation intent is $1,000 per asset. 

**Recommended Next Steps:**
1. **Dynamic Scaling:** Update `portfolio_evaluator.py` to calculate `TOTAL_PORTFOLIO_CAPITAL = len(symbols) * 1000.0` rather than a flat $10,000.
2. **Dynamic Wrapper Integration:** Update `capital_wrapper.py` so the profiles dynamically inherit their `starting_capital` from the portfolio's actual asset count rather than using static `$10k` config blocks.
3. **Database Flush:** Re-run the portfolio and robustness steps on portfolios to correct the bloated denominator data currently sitting in the Master Sheet.
