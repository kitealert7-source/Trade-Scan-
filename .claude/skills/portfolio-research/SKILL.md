---
name: portfolio-research
description: Analyze candidate pool and assist in portfolio construction
---

# Portfolio Research Workflow

Analyze the **Candidates** population to construct optimal trading portfolios. This workflow is read-only against pipeline artifacts and does not modify governance states.

### 1. Population Ranking

Load and rank the current candidates by performance, stability, and risk-adjusted return.

1. Open `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx`.
2. Rank by `Return/DD` and `Profit Factor`.
3. Identify top-tier candidates for deeper analysis.

### 2. Ledger Enrichment (Step 8.5 — Validator Only)

Enrich the Master Portfolio Sheet with realized execution metrics from the deployed capital profiles.
**Note:** Profile *selection* is owned by Step 7 (`portfolio_evaluator.py`).
`profile_selector.py` is a read-only validator/enricher — it reads Step 7's choice from
the ledger and populates realized_pnl, trades_accepted, rejection_rate, etc.

// turbo

```powershell
python tools/profile_selector.py --all
```

### 3. Deep Robustness Analysis (Optional)

Run the 16-test robustness suite on a shortlisted candidate.

// turbo

```powershell
python -m tools.robustness.cli <STRATEGY_ID> --suite full
```

### 4. Correlation & Portfolio Construction

1. Review equity curve correlations in the `Master_Portfolio_Sheet.xlsx`.
2. Select strategies with low correlation to maximize diversification benefit.
3. Shortlist the final "Live Portfolio" candidates.

### 5. Research Artifacts

- **Report Summaries**: Check `backtests/<DIRECTIVE_NAME>/REPORT_SUMMARY.md`.
- **Robustness Reports**: Review `TradeScan_State/strategies/<STRATEGY_ID>/ROBUSTNESS_*.md`.

---

### Reference: System Contract
Robustness reports and research summaries are observational artifacts with no governance authority. They must not be used to re-validate or re-promote runs in the registry.
