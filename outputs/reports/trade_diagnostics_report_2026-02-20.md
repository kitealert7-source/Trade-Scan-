# Trade Diagnostics Audit Report

**Date:** 2026-02-20
**Scope:** AK Trade Sheet Columns O (atr_entry), Q (mae_r), S (mfe_r), V (r_multiple)
**Method:** Source inspection only. No code modified. No backtests regenerated.

---

## 1. Source Files Inspected

| File | Role |
| :--- | :--- |
| `engine_dev/universal_research_engine/1.3.0/execution_loop.py` | Trade loop + market state capture |
| `tools/run_stage1.py` → `emit_result()` | RawTradeRecord construction + field mapping |
| `tools/execution_emitter_stage1.py` | `RawTradeRecord` dataclass + CSV writer |

---

## 2. Per-Metric Root Cause Analysis

### A. `atr_entry` (Column O)

**Where it should be computed:**
At trade entry, the engine captures the ATR from the entry bar.

**Relevant code in `execution_loop.py` (Line 188):**

```python
"atr_entry": row.get('atr', row.get('ATR', 0.0))  # Best effort
```

**Relevant code in `run_stage1.py` emit_result (Line 380):**

```python
atr_entry=t.get('atr'),
```

**Finding:**
The engine reads ATR from the bar row using key `'atr'` (lowercase). The emit_result() function **also tries key `'atr'`**, but the trade dictionary emitted by the execution loop stores the value under key `'atr_entry'`, not `'atr'`. Therefore `t.get('atr')` resolves to `None`.

**Classification: C — Stored but not exported (key mismatch)**

> `atr_entry` is correctly captured inside `entry_market_state['atr_entry']` in the execution loop and passed in the trade dict. However, `emit_result()` calls `t.get('atr')` rather than `t.get('atr_entry')`, so the field is always `None`, which the CSV emitter writes as an empty string.

> **Secondary Condition:** Even if the key were correct, the strategy (`Range_Breakout_02_AllVol`) must compute and attach an `atr` column to the DataFrame for the engine to capture it. If the strategy does not compute ATR, the row lookup returns 0.0 fallback regardless.

---

### B. `mae_r` (Column Q) and `mfe_r` (Column S)

**Where they should be computed:**
MAE-R and MFE-R are R-normalized versions of max adverse excursion and max favorable excursion, defined as:

- `mae_r = mae_price / initial_risk_distance`
- `mfe_r = mfe_price / initial_risk_distance`

**Relevant code in `run_stage1.py` emit_result (Lines 385–386):**

```python
mfe_r=0.0,
mae_r=0.0,
```

**Relevant code in `execution_loop.py`:**

- `trade_high` and `trade_low` **are tracked** per-bar during trade duration (Lines 196–202).
- `mfe_price` and `mae_price` **are computed** by emit_result (Lines 359–363):

  ```python
  if direction == 1:
      mfe_price = trade_high - entry
      mae_price = entry - trade_low
  else:
      mfe_price = entry - trade_low
      mae_price = trade_high - entry
  ```

- These `mfe_price` and `mae_price` values **are correctly emitted** to the CSV.

**Finding:**
`mfe_price` and `mae_price` are computed and exported correctly. However, the R-normalized versions (`mfe_r`, `mae_r`) are **hardcoded to 0.0** in the `RawTradeRecord` constructor call because no `initial_risk_distance` is stored anywhere in the pipeline.

**Classification: A — Not implemented in engine**

> R-normalization requires a stop-loss distance (initial risk per trade in price units). No stop-loss is stored per trade anywhere in the execution loop, trade dict, or emit_result function. The engine has no concept of initial risk. Therefore `mae_r` and `mfe_r` cannot be computed without a structural addition to the engine.

---

### C. `r_multiple` (Column V)

**Where it should be computed:**
`r_multiple = pnl_usd / initial_risk_usd`

**Relevant code in `run_stage1.py` emit_result (Line 387):**

```python
r_multiple=0.0,
```

**Relevant code in `execution_loop.py`:**

- No stop-loss price is stored.
- No initial risk (in USD or price units) is stored per trade.
- No `stop_distance` or `risk_per_trade` column is computed anywhere.

**Finding:**
`r_multiple` is **explicitly hardcoded to 0.0** in emit_result. This is not a bug or an oversight in the export layer — it is a deliberate placeholder acknowledging that the engine has no stop-loss model. Without a stop-loss price or initial risk distance, R-multiple is mathematically undefined.

**Classification: A — Not implemented in engine**

---

## 3. Structural Classification Summary

| Metric | Classification | Root Cause |
| :--- | :--- | :--- |
| **atr_entry** | **C — Stored, Not Exported** | `emit_result` uses `t.get('atr')` but trade dict key is `'atr_entry'`. Secondary: strategy may not compute ATR column. |
| **mae_r** | **A — Not Implemented** | No stop-loss / initial risk distance in engine. R-normalization impossible. Hardcoded `0.0`. |
| **mfe_r** | **A — Not Implemented** | Same as `mae_r`. Hardcoded `0.0`. |
| **r_multiple** | **A — Not Implemented** | No stop-loss model. R-multiple is structurally undefined. Hardcoded `0.0`. |

> **Note:** `mfe_price` and `mae_price` (price-unit excursions) **are correctly computed and exported**. Only the R-normalized versions are missing.

---

## 4. Final Summary

### Root Cause (Concise)

- **atr_entry** fails due to a **key name mismatch** between the execution loop trade dict (`'atr_entry'`) and the `emit_result()` accessor (`t.get('atr')`).
- **mae_r, mfe_r, r_multiple** are **structural gaps** — the engine has no stop-loss model and therefore no initial risk reference. These are intentionally left as 0.0 placeholders pending a risk model.

### Fix Ownership

| Metric | Fix Belongs In | Notes |
| :--- | :--- | :--- |
| **atr_entry** | `run_stage1.py` → `emit_result()` | Change `t.get('atr')` → `t.get('atr_entry')`. Also verify strategy computes `atr` column. |
| **mae_r / mfe_r** | `execution_loop.py` + `run_stage1.py` | Requires stop-loss price stored per trade. Then R-normalize in `emit_result`. |
| **r_multiple** | `execution_loop.py` + `run_stage1.py` | Requires initial_risk_usd. Derived from stop_distance × position_units. |

### Backtest Regeneration Required?

| Metric | Requires Regen? |
| :--- | :--- |
| **atr_entry** | **Yes** — fix is in execution layer, not post-processing |
| **mae_r / mfe_r** | **Yes** — requires engine-level stop tracking |
| **r_multiple** | **Yes** — same dependency |

### Estimated Complexity

| Metric | Complexity | Notes |
| :--- | :--- | :--- |
| **atr_entry** | **Low** | One-line key fix. Assumes strategy already computes `atr` column. |
| **mae_r / mfe_r** | **Medium** | Requires engine contract update (stop_distance field) + emit_result computation |
| **r_multiple** | **Medium** | Same as above; USD conversion of risk distance also required |
