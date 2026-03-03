---
description: Run the strict append-only strategy filter
---

# Run Strategy Filter

This workflow executes the strict, append-only strategy filter.
It analyzes the master ledger and non-destructively populates the passed strategies tracking sheet, preserving all existing rows manually promoted to the portfolio.

1. Run the filter script
// turbo

```bash
python tools/filter_strategies.py
```
