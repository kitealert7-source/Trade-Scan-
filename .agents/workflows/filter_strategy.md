---
description: Run the strict append-only strategy filter
---

# Run Strategy Filter

This workflow executes the strict, append-only strategy filter.
It analyzes the master ledger and non-destructively populates the passed strategies tracking sheet, preserving all existing rows manually promoted to the portfolio.

### Step 0: Read Failure Playbook

Before any execution, you MUST read the `AGENT.md` failure classification and recovery playbook at the project root.

1. Run the filter script
// turbo

```bash
python tools/filter_strategies.py
```

1. Format artifacts
// turbo

```bash
python tools/format_excel_artifact.py --file backtests/Strategy_Master_Filter.xlsx --profile strategy
python tools/format_excel_artifact.py --file strategies/Filtered_Strategies_Passed.xlsx --profile strategy
```
