# Capital Formula Audit Report

This report provides full transparency of capital-related calculations utilized in portfolio summary generation, adhering strictly to the source logic currently persisted in the system.

---

### METRIC: effective_capital

**FORMULA:**
```python
num_assets = len(global_unique_symbols)
if num_assets == 0:
    effective_capital = 1000.0
else:
    effective_capital = num_assets * 1000.0
```

**INPUTS:**
- `global_unique_symbols` → Extracted natively from `deployable_trade_log.csv` (`tools/post_process_capital.py` > `process_profile_comparison`)

**CAPITAL BASE:**
derived indirectly

**NOTES:**
- Assumes an arbitrary allocation of $1,000 baseline capital per unqiue asset actively traded, fully segregated from the native `starting_capital`.

---

### METRIC: avg_heat_utilization_pct

**FORMULA:**
```python
avg_heat = sum(state.heat_samples) / len(state.heat_samples)
# (sampled at every trade exit: heat_samples.append(total_open_risk / equity))
avg_heat_utilization_pct = round(avg_heat * 100, 4)
```

**INPUTS:**
- `total_open_risk` → Accumulated USD risk (`tools/capital_wrapper.py` > `PortfolioState.process_exit`)
- `equity` → Running simulated equity (`tools/capital_wrapper.py` > `PortfolioState.process_exit`)

**CAPITAL BASE:**
starting

**NOTES:**
- Heat utilization is structurally sampled *exclusively* at trade exit events, meaning peak intra-trade heat durations (active holding periods) are skipped if they do not overlap with an exit timestamp.

---

### METRIC: max_drawdown_pct_real

**FORMULA:**
```python
max_drawdown_pct_real = max_drawdown_usd / effective_capital
```

**INPUTS:**
- `max_drawdown_usd` → Sourced directly from `profile_comparison.json` (`tools/post_process_capital.py` > `process_profile_comparison`)
- `effective_capital` → Computed natively from asset counts (`tools/post_process_capital.py` > `process_profile_comparison`)

**CAPITAL BASE:**
mixed

**NOTES:**
- **Inconsistency:** The `max_drawdown_usd` metric was mechanically derived from a simulation seeded with a strict $10,000 starting base. Dividing this raw USD loss by `effective_capital` (e.g. $1,000 for a single asset) mathematically inflates the drawdown percentage artificially by a factor of 10x.

---

### METRIC: cagr_real

**FORMULA:**
```python
scale_factor = effective_capital / 10000.0
scaled_final_equity = final_equity * scale_factor

if scaled_final_equity <= 0:
    cagr_real = -1.0
else:
    cagr_real = (scaled_final_equity / effective_capital) ** (1.0 / sim_years) - 1.0
```

**INPUTS:**
- `final_equity` → Sourced directly from `profile_comparison.json` (`tools/post_process_capital.py`)
- `sim_years` → Sourced directly from `profile_comparison.json` (`tools/post_process_capital.py`)
- `effective_capital` → Computed locally (`tools/post_process_capital.py`)

**CAPITAL BASE:**
starting 

**NOTES:**
- **Implicit Math Cancellation:** If you substitute `scaled_final_equity` into the equation, it becomes `((final_equity * (effective_capital / 10000.0)) / effective_capital)`, causing `effective_capital` to perfectly cancel out algebraically. The formula mechanically resolves precisely to `(final_equity / 10000.0) ** (1/sim_years) - 1`. `cagr_real` is materially identical to standard `cagr`; the scaling logic creates an absolute mathematical illusion.

---

### METRIC: mar_real

**FORMULA:**
```python
if abs(max_drawdown_pct_real) > 1e-9:
    mar_real = cagr_real / abs(max_drawdown_pct_real)
else:
    mar_real = float('inf') if cagr_real > 0 else 0.0
```

**INPUTS:**
- `cagr_real` → Computed locally (`tools/post_process_capital.py`)
- `max_drawdown_pct_real` → Computed locally (`tools/post_process_capital.py`)

**CAPITAL BASE:**
mixed

**NOTES:**
- Deeply skewed downside penalty. Because `cagr_real` effectively defaults to the non-scaled $10k base behavior, while `max_drawdown_pct_real` applies mismatched inflation, `mar_real` is massively and falsely understated for lower-asset strategies.

---

### METRIC: realized_pnl

**FORMULA:**
```python
pnl_usd = price_delta * trade.usd_per_price_unit_per_lot * trade.lot_size
self.realized_pnl += pnl_usd
```

**INPUTS:**
- Execution data → `exit_price`, `entry_price`, `direction`, `lot_size`
- Conversion variable → `usd_per_price_unit_per_lot` (`tools/capital_wrapper.py` > `PortfolioState.process_exit`)

**CAPITAL BASE:**
starting

**NOTES:**
- Functions identically correctly to the execution logic deployed iteratively from the core `starting_capital=10000` base constraint.

---

### METRIC: capital_validity_flag

**FORMULA:**
```python
capital_validity_flag = True
if max_drawdown_usd > effective_capital or scaled_final_equity <= 0:
    capital_validity_flag = False
```

**INPUTS:**
- `max_drawdown_usd` → `profile_comparison.json` (from $10K baseline)
- `scaled_final_equity` → Computed locally (`tools/post_process_capital.py`)
- `effective_capital` → Computed locally (`tools/post_process_capital.py`)

**CAPITAL BASE:**
mixed

**NOTES:**
- **Mismatch:** Checks if a raw USD drawdown generated by leveraging a $10,000 base violently slices through the dynamically derived `effective_capital` constraint. If an uncapped profile draws $1,500 down locally over a $10k run, it falsely fails validation on a single-asset run (`effective_capital` = 1000).

---

## FINAL SECTION

#### 1. Models utilizing Inconsistent Capital Bases
- `max_drawdown_pct_real` (Combines $10k base DD_USD against variable asset Base)
- `mar_real` (Inherits inconsistency from the drawdown inflation)
- `capital_validity_flag` (Evaluates $10k scale losses against dynamically scaled caps)

#### 2. Duplicate or Redundant Metrics
- `cagr_real` vs `cagr`: They are completely redundant algebraic mirrors. The attempt to scale final equity before dividing down identically matches standard unscaled mechanics. 

#### 3. Misleading metrics given Partial Capital Utilization
- `max_drawdown_pct_real`: Extremely misleading. Reporting a 70% DD against an `effective_capital` of $1,000 when the original strategy was heavily executing against a $10,000 allocation severely fractures the risk reality.
- `avg_heat_utilization_pct`: Misleadingly smoothed. Samples are exclusively dropped on exit checkpoints, intentionally skipping peak heat exposures accrued simultaneously during overlapping open durations unless exits coincide.
