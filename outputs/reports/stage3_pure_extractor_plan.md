# Plan: Eliminate Computation from Stage 3

## Context

The pipeline integrity report (`outputs/system_reports/02_pipeline_audit/pipeline_integrity_report.md`) identifies a "split-brain extraction" violation in Stage 3: `compute_trend_metrics()` reads `results_tradelevel.csv` directly (an Authority Layer artifact) to produce trend regime metrics, instead of deriving them exclusively from Stage 2's `AK_Trade_Report.xlsx`. Additionally, `trade_density` is computed arithmetically in Stage 3 from already-extracted Stage 2 values. Neither computation belongs in the aggregation stage. The goal is to relocate both computations into Stage 2 and make Stage 3 a pure extractor.

---

## 1. Exact Computation to Eliminate from Stage 3

### A. `compute_trend_metrics()` — `tools/stage3_compiler.py` lines 162–231
- Reads `results_tradelevel.csv`, iterates rows, aggregates `pnl_usd` by `trend_label`
- Produces 10 keys: `net_profit_strong_up/weak_up/neutral/weak_down/strong_down` and `trades_strong_up/weak_up/neutral/weak_down/strong_down`
- Called at line 242 inside `extract_from_report()`; result merged at line 280

### B. `trade_density` arithmetic — `extract_from_report()` lines 259–267
```python
row_data["trade_density"] = int(round(tt / (tp / 365.25)))
```
- Uses `total_trades` and `trading_period` already extracted from AK_Trade_Report
- Purely arithmetic; no new source data needed

---

## 2. Insertion Points in Stage 2 (`tools/stage2_compiler.py`)

### 2A. Add trend aggregation to `_compute_metrics_from_trades()` (after line ~487, after session breakdown block)

The session breakdown pattern (lines 407–427) is the exact model to follow. After the session block, add a trend label loop:

```python
# Trend regime breakdown (SOP v4.2)
trend_buckets = {
    "strong_up": [], "weak_up": [], "neutral": [], "weak_down": [], "strong_down": []
}
valid_labels = set(trend_buckets.keys())
for t in filtered:
    label = str(t.get("trend_label", "")).strip()
    if label in valid_labels:
        trend_buckets[label].append(_safe_float(t.get("pnl_usd", 0)))

net_profit_strong_up = sum(trend_buckets["strong_up"])
# ... (same pattern for all 5 labels)
trades_strong_up = len(trend_buckets["strong_up"])
# ... (same pattern for all 5 labels)

# Trade density (trades per year)
trade_density = int(round(trade_count / (trading_period_days / 365.25))) if trading_period_days > 0 else 0
```

Add to `return {}` dict at line 487: all 10 trend keys + `trade_density`.

### 2B. Add zero-inits to `_empty_metrics()` (line 490)

After the session zeros at line 511–513, add:
```python
"net_profit_strong_up": 0.0, "net_profit_weak_up": 0.0, "net_profit_neutral": 0.0,
"net_profit_weak_down": 0.0, "net_profit_strong_down": 0.0,
"trades_strong_up": 0, "trades_weak_up": 0, "trades_neutral": 0,
"trades_weak_down": 0, "trades_strong_down": 0,
"trade_density": 0,
```

### 2C. Add `add_row()` calls to `get_performance_summary_df()` (after line 742)

After the last session row (`add_row("Avg Trade - New York Session", ...)`), append:
```python
add_row("Trade Density (Trades/Year)", "trade_density")
add_row("Net Profit - Strong Up", "net_profit_strong_up")
add_row("Net Profit - Weak Up", "net_profit_weak_up")
add_row("Net Profit - Neutral", "net_profit_neutral")
add_row("Net Profit - Weak Down", "net_profit_weak_down")
add_row("Net Profit - Strong Down", "net_profit_strong_down")
add_row("Trades - Strong Up", "trades_strong_up")
add_row("Trades - Weak Up", "trades_weak_up")
add_row("Trades - Neutral", "trades_neutral")
add_row("Trades - Weak Down", "trades_weak_down")
add_row("Trades - Strong Down", "trades_strong_down")
```

`generate_excel_report()` needs no changes — it calls `get_performance_summary_df()` and writes the df as-is.

---

## 3. Schema Changes to `AK_Trade_Report.xlsx`

**Sheet:** Performance Summary
**Change:** 11 new rows appended after existing session rows

| Metric Label (exact) | Source key |
|---|---|
| `Trade Density (Trades/Year)` | `trade_density` |
| `Net Profit - Strong Up` | `net_profit_strong_up` |
| `Net Profit - Weak Up` | `net_profit_weak_up` |
| `Net Profit - Neutral` | `net_profit_neutral` |
| `Net Profit - Weak Down` | `net_profit_weak_down` |
| `Net Profit - Strong Down` | `net_profit_strong_down` |
| `Trades - Strong Up` | `trades_strong_up` |
| `Trades - Weak Up` | `trades_weak_up` |
| `Trades - Neutral` | `trades_neutral` |
| `Trades - Weak Down` | `trades_weak_down` |
| `Trades - Strong Down` | `trades_strong_down` |

**Invariant:** All three columns (`All Trades`, `Long Trades`, `Short Trades`) populated. Trade density only meaningful for `All Trades` (Long/Short decomposition allowed to be zero).

---

## 4. Stage 3 Changes (`tools/stage3_compiler.py`)

### 4A. Add `TREND_METRICS` dict (after `VOLATILITY_METRICS` at line 102)
```python
TREND_METRICS = {
    "net_profit_strong_up":  "Net Profit - Strong Up",
    "net_profit_weak_up":    "Net Profit - Weak Up",
    "net_profit_neutral":    "Net Profit - Neutral",
    "net_profit_weak_down":  "Net Profit - Weak Down",
    "net_profit_strong_down":"Net Profit - Strong Down",
    "trades_strong_up":      "Trades - Strong Up",
    "trades_weak_up":        "Trades - Weak Up",
    "trades_neutral":        "Trades - Neutral",
    "trades_weak_down":      "Trades - Weak Down",
    "trades_strong_down":    "Trades - Strong Down",
}
TRADE_DENSITY_LABEL = "Trade Density (Trades/Year)"
```

### 4B. Update `validate_required_metrics()` (line 154)
- Treat `TREND_METRICS` and `TRADE_DENSITY_LABEL` as **optional** (warn, do not fail) to preserve backward compat with old reports

### 4C. Rewrite `extract_from_report()` (lines 233–282)
- Remove the `compute_trend_metrics(run_folder)` call (lines 241–244)
- Remove the `trade_density` arithmetic block (lines 259–267)
- Remove `row_data.update(trend_aggs)` (line 280)
- Remove `run_folder` parameter (only used for `compute_trend_metrics`)
- Add extraction of `trade_density` from metrics dict with fallback:
  ```python
  if TRADE_DENSITY_LABEL in metrics:
      row_data["trade_density"] = int(metrics[TRADE_DENSITY_LABEL]) if pd.notnull(metrics[TRADE_DENSITY_LABEL]) else 0
  else:
      # Backward compat: derive from already-extracted Stage-2 values
      tt = float(row_data.get("total_trades") or 0)
      tp = float(row_data.get("trading_period") or 365.25)
      row_data["trade_density"] = int(round(tt / (tp / 365.25))) if tp > 0 else 0
  ```
- Add extraction of trend metrics from metrics dict with None fallback:
  ```python
  for col_name, label in TREND_METRICS.items():
      row_data[col_name] = metrics.get(label)  # None for old reports
  ```

### 4D. Delete `compute_trend_metrics()` entirely (lines 162–231)

### 4E. Update callers of `extract_from_report()` in `compile_stage3()`
- Remove the `run_folder` argument from the call site

---

## 5. Backward Compatibility

| Scenario | Behavior |
|---|---|
| New run (Stage 2 regenerated) | Stage 2 writes 11 new rows → Stage 3 extracts cleanly |
| Old run (AK_Trade_Report not regenerated) | Stage 3 extracts None for trend metrics, derives `trade_density` from existing metrics — no crash |
| Manual rebuild via `tools/rebuild_all_reports.py` | Regenerates AK_Trade_Report with new schema; old runs become fully compliant after rebuild |

Stage 3 will **not** error on missing trend labels. It will write `None` into `Strategy_Master_Filter.xlsx` for those columns, which is already the behavior for incompatible timeframes (see "Daily_Nan" session handling).

---

## 6. Validation Steps

1. **Run Stage 2 on one run folder**: confirm Performance Summary sheet contains 11 new rows with expected label strings
2. **Run Stage 3 on same run folder**: confirm `Strategy_Master_Filter.xlsx` contains populated trend columns — no call to `results_tradelevel.csv` in Stage 3 logs
3. **Grep check** — zero remaining computation in Stage 3:
   - `grep -n "compute_trend\|tradelevel\|iterrows\|\.sum()\|trade_density.*round" tools/stage3_compiler.py` → must return nothing
4. **Old-run backward compat**: run Stage 3 against a run folder whose AK_Trade_Report was generated before this change → confirm no crash; trend columns are None, `trade_density` is derived
5. **Full pipeline**: `python tools/run_pipeline.py --all` on a test directive → all stages pass, no regression

---

## Critical Files

| File | Change Type |
|---|---|
| `tools/stage2_compiler.py` | Add trend aggregation + `trade_density` to `_compute_metrics_from_trades()`, `_empty_metrics()`, `get_performance_summary_df()` |
| `tools/stage3_compiler.py` | Delete `compute_trend_metrics()`, rewrite `extract_from_report()` to extract-only, add `TREND_METRICS` dict |
