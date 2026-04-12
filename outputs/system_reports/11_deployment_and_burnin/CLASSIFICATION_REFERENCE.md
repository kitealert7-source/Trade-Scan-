# Classification Reference — CORE / WATCH / FAIL

Single source of truth for strategy classification across the pipeline.

---

## Entity Types

| Entity Type | Where Created | Sheet | Example ID |
|---|---|---|---|
| Per-symbol run | `run_pipeline.py` Stage 1 | Strategy_Master_Filter.xlsx | `22_CONT_FX_30M_RSIAVG_..._P03_AUDJPY` |
| Multi-asset composite | `portfolio_evaluator.py` | MPS → Portfolios | `PF_04C5F80CB1E3` |
| Single-asset composite | `portfolio_evaluator.py` | MPS → Single-Asset Composites | `PF_0C0C974A75F7` |

---

## Classification Gates by System

### 1. `filter_strategies.py` — Per-Symbol Screening

**Input:** Strategy_Master_Filter.xlsx rows (one per symbol per run).

| Status | Gate |
|---|---|
| PASS | SQN >= configured threshold AND trade_count >= minimum |
| FAIL | Below thresholds |

No CORE/WATCH distinction — binary pass/fail at this stage.

### 2. `portfolio_evaluator.py` — Portfolio Status (Step 7)

**Input:** Master_Portfolio_Sheet.xlsx rows. **Sole authority** for portfolio_status.

#### Universal FAIL gates (checked first, both sheets)

| Condition | Result |
|---|---|
| `realized_pnl <= 0` | FAIL |
| `trades_accepted < 50` | FAIL |
| `trade_density < 50` | FAIL |
| `expectancy < asset_class_gate` | FAIL |

#### CORE gates (additive — must clear ALL universal gates first)

| Sheet | Primary Metric | Threshold | Additional Requirements |
|---|---|---|---|
| Portfolios | `edge_quality` | >= 0.12 | realized > 1000, accepted >= 200, rejection <= 30% |
| Single-Asset | `SQN` | >= 2.5 | realized > 1000, accepted >= 200, rejection <= 30% |

#### WATCH gates (routing by entity type)

| Sheet | Primary Metric | Threshold | Fallback |
|---|---|---|---|
| Portfolios | `edge_quality` | >= 0.08 | SQN >= 2.0 if edge_quality unavailable |
| Single-Asset | `SQN` | >= 2.0 | edge_quality >= 0.08 if SQN unavailable |

Anything below WATCH thresholds that passed universal gates → FAIL.

### 3. `promote_to_burnin.py` — Promotion Quality Gate

**Input:** `results_tradelevel.csv` from backtest folders. Runs at promote time.

| Metric | HARD FAIL | WARN | Direction |
|---|---|---|---|
| Top-5 concentration (%) | > 70% | > 50% | Lower is better |
| PnL without top 5 trades (%) | < 0% | < 30% | Higher is better |
| Flat period (%) | > 40% | > 30% | Lower is better |
| Edge ratio (MFE/MAE) | < 1.0 | < 1.2 | Higher is better |
| Trade count | < 100 | < 200 | Higher is better |
| PF after removing top 5% | < 1.0 | < 1.1 | Higher is better |

HARD FAIL blocks promotion. WARN is advisory (proceeds unless `--skip-quality-gate` needed).

### 4. Expectancy Floor (`config/asset_classification.py`)

Per-symbol minimum expectancy, checked at both portfolio evaluation and promotion:

| Asset Class | Floor |
|---|---|
| FX | $0.15 |
| XAU | $0.50 |
| BTC | $0.50 |
| INDEX | $0.50 |

---

## Metric Disambiguation

| Term | System | Meaning |
|---|---|---|
| `edge_quality` | `portfolio_evaluator.py` | Portfolio-level edge metric (Portfolios sheet) |
| `edge_ratio` | `promote_to_burnin.py` | MFE/MAE ratio from individual trades |
| `SQN` | `portfolio_evaluator.py` | System Quality Number (Single-Asset sheet) |
| `profit_factor` | Multiple | Gross profit / gross loss |
| `trade_density` | `portfolio_evaluator.py` | Per-symbol trade count (catches inflated portfolio totals) |

---

## Composite Portfolio Promotion

Composite portfolios (PF_*) cannot be promoted directly — they have no strategy.py
and no single run_id. Use `--composite` flag to auto-decompose and promote constituents:

```bash
python tools/promote_to_burnin.py PF_XXXX --composite --profile PROFILE --dry-run
```

The tool decomposes the PF_ ID into constituent base strategies, runs per-constituent
quality gates, and promotes each passing constituent individually. Constituents already
in portfolio.yaml are skipped.
