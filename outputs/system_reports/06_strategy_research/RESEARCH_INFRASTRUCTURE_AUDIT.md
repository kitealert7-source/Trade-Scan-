# Research Infrastructure Capability Audit

This report provides a targeted audit of the **Trade_Scan** research platform to evaluate its current infrastructure capabilities across seven core dimensions.

---

## 1. Ledger Storage Authority

The Trade_Scan platform follows a tiered authority model for storage:

- **Authoritative Data Source (Run-Level):** The primary source of truth for any specific experiment run is the **CSV collection** found in `TradeScan_State/runs/<run_id>/raw/`. These are emitted by Stage-1 (`execution_emitter_stage1.py`) and are immutable.
- **Authoritative Index (Cross-Run):** The **`Strategy_Master_Filter.xlsx`** (governed by Stage-3) serves as the authoritative index and summary ledger. It determines which runs are valid for retention and comparison.
- **Portfolio Storage:** Detailed portfolio-level results are stored in **`Master_Portfolio_Sheet.xlsx`** (governed by Stage-4).

**Conclusion:** The platform uses a hybrid model where **CSVs are the authoritative raw data**, while **Excel ledgers serve as the authoritative index and analytical presentation layer**.

---

## 2. Experiment Metadata Tracking

The platform tracks comprehensive metadata for every run, ensuring high experimental traceability.

- **Storage Location:** Each run contains a `metadata/run_metadata.json` file.
- **Tracked Parameters:**
    - `run_id` (deterministic 24-character hash)
    - `strategy_name`
    - `symbol` / `symbol universe`
    - `timeframe`
    - `date_range_start` / `date_range_end`
    - `execution_timestamp_utc`
    - `engine_name` / `engine_version`
    - `broker`
    - `reference_capital_usd`
- **Assessment:** The system effectively functions as a distributed **experiment registry**. The deterministic `run_id` generation logic in `pipeline_utils.py` ensures that changes to the directive or engine version automatically produce new, distinct identities.

---

## 3. Experiment Comparison Capabilities

Systematic comparison of experiments is a first-class feature of the platform.

- **Tools:** `portfolio_evaluator.py` and `Strategy_Master_Filter.xlsx`.
- **Supported Analysis:**
    - **Cross-Symbol:** The Master Filter allows sorting and filtering strategy performance across the symbol universe.
    - **Cross-Profile:** Strategies with different parameter sets (identified by name/suffix) can be compared side-by-side in the Master Filter.
    - **Time-Range Sensitivity:** Metadata tracking allows for temporal performance comparison.
    - **Portfolio Evaluation:** Provides systematic comparison of contribution (PnL), correlation (equity curves), and stress test resilience.

---

## 4. Parameter Sweep Infrastructure

Parameter sweeps are handled with high governance via a centralized gate.

- **Governing Tool:** `tools/sweep_registry_gate.py`.
- **Registry:** `governance/namespace/sweep_registry.yaml`.
- **Capabilities:**
    - **Controlled Generation:** Allocates unique `SNN` (Sweep Number) tokens.
    - **Collision Prevention:** Prevents identical sweeps from being allocated to different idea IDs or vice versa.
    - **Idempotency:** Re-running the same sweep directive yields the same reserved identity.
    - **Sweep Tracking:** The resultant `run_id`s from a sweep are tracked in the Master Filter, allowing for direct result comparison.

---

## 5. Robustness Suite Evaluation

The robustness suite is highly mature, providing advanced stability analysis.

- **Location:** `tools/robustness/`.
- **Core Capabilities:**
    - **Monte Carlo:** Regime-aware block bootstrapping (500+ iterations).
    - **Tail Removal:** Evaluates strategy sensitivity to the best 1% and 5% of trades.
    - **Stability Tracks:** Identifies performance "negative clusters" and classifies window stability.
    - **Drawdown Diagnostics:** Clusters drawdowns and analyzes trade behavior during collapse.
    - **Friction Stress:** Simulates performance degradation under increased slippage/spread.
    - **Seasonality:** Detects monthly and weekday biases.

---

## 6. Visualization and Reporting

The platform currently relies on **artifact-based reporting** rather than interactive exploration.

- **Visual Artifacts:**
    - **Equity Curves & Drawdown Plots:** Generated per portfolio and strategy.
    - **Correlation Heatmaps:** Visualizes instrument interdependencies.
    - **PnL Contribution Charts:** Bar charts showing per-symbol impact.
- **Report Formats:**
    - **`REPORT_SUMMARY.md`:** Directive-level executive summary.
    - **`PORTFOLIO_<strategy>.md`:** Strategy-level portfolio audit.
    - **`ROBUSTNESS_REPORT.md`:** Detailed stability and stress test report.
- **Assessment:** Visualization is comprehensive but static. It is designed for **peer review and archival** rather than live, interactive parameter exploration.

---

## 7. Recommendations

- **Gap identified:** Lack of an interactive "Research Dashboard" for live parameter exploration (e.g., Streamlit).
- **Recommendation:** Integrate a lightweight web dashboard that reads from the `Strategy_Master_Filter.xlsx` to allow for real-time filtering and visualization of the entire experiment set.
- **Gap identified:** Standardized "Comparison Reports" between two specific `run_id`s are currently manual.
- **Recommendation:** Implement a `compare_runs.py` tool to generate a diff-style report between any two arbitrary run IDs.

---

**RESEARCH_INFRASTRUCTURE_AUDIT_COMPLETE**

---

## Addendum — 2026-03-24

### Discoverability Gap Closed

Section 1 above identifies `Strategy_Master_Filter.xlsx` as the authoritative cross-run index. A parallel programmatic discoverability gap (scanning 223 folders across 3 files each to answer a single filtered query) was formally confirmed by a subsequent artifact storage audit (`08_pipeline_audit/ARTIFACT_STORAGE_AUDIT_2026_03_24.md`).

That gap is now closed. A central flat index has been implemented:

**`TradeScan_State/research/index.csv`** — append-only, 15 columns per run:

| Field | Source |
|---|---|
| run_id, strategy_id, symbol, timeframe | run_metadata.json |
| date_start, date_end | run_metadata.json → date_range |
| profit_factor, net_pnl_usd, total_trades, win_rate | results_standard.csv |
| max_drawdown_pct | results_risk.csv |
| content_hash, git_commit, execution_timestamp_utc | run_metadata.json |
| schema_version | `"legacy"` for pre-patch runs / `"1.3.0"` for post-patch runs |

**Write mechanism:** `tools/run_index.py` — called automatically in `stage_symbol_execution.py` at `STAGE_1_COMPLETE`. Non-blocking (failure never blocks the pipeline). FileLock-protected for parallel runs.

**Backfill:** `tools/backfill_run_index.py` was run once on 2026-03-24, populating 167 legacy rows (`schema_version="legacy"`, `content_hash=""`, `git_commit=""` intentionally blank — not retroactively guessable).

**Query pattern (no folder scanning):**
```python
import csv
rows = list(csv.DictReader(open(r'TradeScan_State\research\index.csv')))
hits = [r for r in rows if float(r['profit_factor'] or 0) > 1.5
        and float(r['max_drawdown_pct'] or 99) < 10]
```

### Provenance Fields Added to run_metadata.json

The metadata gap identified in Section 2 (no config_hash, no code_version, no execution model) is also closed for all runs from 2026-03-24 onwards. The following fields are now injected into `run_metadata.json` at Stage-1 completion (both `RUNS_DIR` and `BACKTESTS_DIR` views):

| Field | Value |
|---|---|
| `content_hash` | SHA256[:8] of directive content — detects silent param drift |
| `git_commit` | `git rev-parse HEAD` at run time — ties results to exact code state |
| `execution_model.order_type` | From directive `order_placement.type` |
| `execution_model.slippage_model` | `"actual_per_trade"` (tracked in results_tradelevel.csv) |
| `execution_model.spread_model` | `"none_applied"` (no spread model in engine v1.5.3) |
| `schema_version` | `"1.3.0"` |

Implementation reference: `08_pipeline_audit/ARTIFACT_PROVENANCE_IMPLEMENTATION_PLAN_2026_03_24.md`.
