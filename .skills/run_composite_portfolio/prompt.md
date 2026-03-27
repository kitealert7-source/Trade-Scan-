---
description: Construct and evaluate a composite portfolio from multiple strategy runs
---

# Run Composite Portfolio Analysis

This workflow guides the process of combining multiple individual strategy runs into a single unified portfolio, evaluating its combined performance, generating deployable capital profiles, and running the final robustness tests.

---

### 0. Identify Portfolio ID

The Portfolio ID is deterministic — derived from the sorted run IDs:

```python
import hashlib
run_ids = ['<RUN_ID_1>', '<RUN_ID_2>']  # add all run IDs
sorted_ids = sorted(run_ids)
h = hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()[:12]
print(f"PF_{h.upper()}")
```

Collect run IDs from `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`,
column `run_id` where `IN_PORTFOLIO == True`.

---

### 1. Data Preparation

Two separate copies of the trade data are required — one for each downstream script.

#### 1a. Copy sandbox runs → `runs/` (required by portfolio_evaluator)

`portfolio_evaluator.py` reads from `TradeScan_State/runs/{run_id}/data/`.
Completed runs live in `sandbox/` after Stage 4. Copy them back temporarily:

```python
import shutil, os
from config.state_paths import RUNS_DIR, POOL_DIR  # POOL_DIR = sandbox

for run_id in ['<RUN_ID_1>', '<RUN_ID_2>']:
    src = POOL_DIR / run_id
    dst = RUNS_DIR / run_id
    if not dst.exists():
        shutil.copytree(str(src), str(dst))
        print(f"Copied {run_id} -> runs/")
```

#### 1b. Copy trade data → `backtests/` (required by capital_wrapper)

`capital_wrapper.py` reads from `TradeScan_State/backtests/<PF_ID>_<TAG>/raw/results_tradelevel.csv`.

**Important — same-symbol portfolios:** If multiple strategies share the same symbol
(e.g., two XAUUSD strategies), they cannot share a single `PF_ID_XAUUSD/` folder.
Use a short strategy tag to differentiate folder names. Do NOT create a directive
file for the PF ID — use the fallback glob mode so capital_wrapper discovers all
subfolders automatically.

```python
import shutil
from config.state_paths import BACKTESTS_DIR, POOL_DIR

# Map each run_id to a unique short tag (e.g. strategy abbreviation)
runs = {
    '<RUN_ID_1>': '<PF_ID>_<TAG_1>',  # e.g. PF_00911A453775_11REV_XAUUSD
    '<RUN_ID_2>': '<PF_ID>_<TAG_2>',  # e.g. PF_00911A453775_12STR_XAUUSD
}
for run_id, folder_name in runs.items():
    src = POOL_DIR / run_id / 'data' / 'results_tradelevel.csv'
    dst_dir = BACKTESTS_DIR / folder_name / 'raw'
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst_dir / 'results_tradelevel.csv'))
    print(f"Copied {run_id} -> backtests/{folder_name}/raw/")
```

---

### 2. Portfolio Evaluation

Run the foundational evaluator to combine the trades, ensure governance compliance,
and generate the baseline portfolio artifacts.

*(Note: Multi-strategy portfolios with different STRATEGY_SIGNATUREs will produce a
`[WARN] Mixed signature hashes detected` message — this is expected and non-blocking.
The `--force-ledger` flag is NOT needed when combining 2+ run IDs.)*

```powershell
python tools/portfolio_evaluator.py <PORTFOLIO_ID> --run-ids <RUN_ID_1> <RUN_ID_2>
```

#### 2c. Clean up temporary `runs/` copies

After portfolio_evaluator completes, remove the temporary copies:

```python
import shutil
from config.state_paths import RUNS_DIR

for run_id in ['<RUN_ID_1>', '<RUN_ID_2>']:
    dst = RUNS_DIR / run_id
    if dst.exists():
        shutil.rmtree(str(dst))
        print(f"Cleaned up runs/{run_id}")
```

---

### 3. Capital Wrapper (Simulation)

Generate trade sizing simulations across all standard execution profiles
(`DYNAMIC_V1`, `CONSERVATIVE_V1`, `FIXED_USD_V1`, `MIN_LOT_FALLBACK_V1`,
`MIN_LOT_FALLBACK_UNCAPPED_V1`, `BOUNDED_MIN_LOT_V1`) against the aggregated
portfolio trades.

No directive file should exist for `<PORTFOLIO_ID>` — capital_wrapper uses
fallback glob mode and auto-discovers all `backtests/<PORTFOLIO_ID>_*/` subfolders.

// turbo
```powershell
python tools/capital_wrapper.py <PORTFOLIO_ID>
```

---

### 4. Optimal Profile Selection

Mathematically identify and select the optimal capital profile for the portfolio
based on Return/Drawdown ratio. This automatically updates `Master_Portfolio_Sheet.xlsx`
with the finalized live profile.

// turbo
```powershell
python tools/profile_selector.py <PORTFOLIO_ID>
```

---

### 5. Final Robustness Evaluation

Run the comprehensive robustness test suite against the optimally selected profile
to generate the final tear sheet. The engine automatically detects the best profile
determined in Step 4.

// turbo
```powershell
python -m tools.robustness.cli <PORTFOLIO_ID> --suite full
```
