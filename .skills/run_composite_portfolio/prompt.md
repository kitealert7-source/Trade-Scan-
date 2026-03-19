# Run Composite Portfolio Analysis

This workflow guides the process of combining multiple individual strategy runs into a single unified portfolio, evaluating its combined performance, generating deployable capital profiles, and running the final robustness tests.

### 1. Data Preparation
To construct a portfolio, the raw trade data for the chosen runs must be accessible in the `backtests` directory.
If the runs are currently stored in `runs/` or `sandbox/`, they must be copied into `backtests/` using the portfolio ID prefix.

**Required Action:**
For each run corresponding to a symbol, ensure its `results_tradelevel.csv` is relocated correctly.
Example for Portfolio ID `PF_MYPORT` and run symbol `[SYMBOL]`:
Ensure `results_tradelevel.csv` exists at: `TradeScan_State/backtests/PF_MYPORT_[SYMBOL]/raw/results_tradelevel.csv`

### 2. Portfolio Evaluation
Run the foundational evaluator to combine the trades, ensure governance compliance, and generate the baseline portfolio artifacts.
*(Note: If the portfolio intentionally combines diverse, non-homogenous strategies, you may need to bypass the strict signature hash validation check in `tools/portfolio_evaluator.py`).*

```powershell
python tools/portfolio_evaluator.py <PORTFOLIO_ID> --run-ids <RUN_ID_1> <RUN_ID_2> <RUN_ID_3>
```

### 3. Capital Wrapper (Simulation)
Generate trade sizing simulations across all standard execution profiles (e.g., `DYNAMIC`, `CONSERVATIVE`, `FIXED_USD`, `MIN_LOT_FALLBACK`) against the aggregated portfolio trades.

// turbo
```powershell
python tools/capital_wrapper.py <PORTFOLIO_ID>
```

### 4. Optimal Profile Selection
Mathematically identify and select the optimal capital profile for the portfolio based on Return/Drawdown ratio. This automatically updates `Master_Portfolio_Sheet.xlsx` with the finalized live profile.

// turbo
```powershell
python tools/profile_selector.py <PORTFOLIO_ID>
```

### 5. Final Robustness Evaluation
Run the comprehensive robustness test suite against the optimally selected profile to generate the final tear sheet. The engine will automatically detect and evaluate the best profile determined in Step 4.

// turbo
```powershell
python -m tools.robustness.cli <PORTFOLIO_ID> --suite full
```
