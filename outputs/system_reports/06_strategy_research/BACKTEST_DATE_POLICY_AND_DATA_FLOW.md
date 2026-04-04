# Backtest Date Policy & Multi-Timeframe Data Flow

This report documents the backtest date range policy, warm-up extension mechanism,
and the multi-timeframe data flow used during backtesting. It serves as the
authoritative reference for directive creation and data pipeline understanding.

---

## 1. Date Range Policy (Initial Screening vs Extended Validation)

**Config file:** `config/backtest_date_policy.yaml`
**Helper:** `config/backtest_dates.py` (`resolve_dates(timeframe, stage, symbols)`)

### Stage A -- Initial Screening

Shorter windows for high-frequency timeframes to keep trade counts manageable
(target: 500--3000 trades) and robustness tests fast.

| Timeframe | Start Date   | Approx Period | Est. Candles | Rationale                                |
|-----------|-------------|---------------|-------------|------------------------------------------|
| 1D        | 2024-01-02  | ~2.25 years   | ~570        | Low frequency -- need full history       |
| 4H        | 2024-01-02  | ~2.25 years   | ~3,400      | Still manageable trade counts            |
| 1H        | 2024-10-01  | ~1.5 years    | ~9,400      | Good regime diversity, ~1000-2000 trades |
| 30M       | 2025-01-02  | ~1.25 years   | ~15,600     | Balanced diversity vs speed              |
| 15M       | 2025-01-02  | ~1 year       | ~25,000     | Cuts excessive trade count by ~55%       |
| 5M        | 2025-10-01  | ~6 months     | ~37,400     | Minimum viable regime coverage           |

**End date** is always auto-resolved from `data_root/freshness_index.json`
(the `latest_date` field). For multi-symbol directives, uses the earliest
`latest_date` across all requested symbols (conservative -- no future-peeking).

### Stage B -- Extended Validation (PROMOTE candidates only)

- **Start date:** 2024-01-02 (always full available history)
- **End date:** auto from freshness index
- Applied only after initial screening passes
- Confirms edge holds across more regimes and out-of-sample periods

### Usage

```python
from config.backtest_dates import resolve_dates

# Initial screening for a 15M strategy
start, end = resolve_dates("15m")
# ("2025-01-02", "2026-03-31")

# Extended validation for PROMOTE candidate
start, end = resolve_dates("15m", stage="extended")
# ("2024-01-02", "2026-03-31")

# Multi-symbol (conservative end date)
start, end = resolve_dates("15m", symbols=["XAUUSD", "AUDUSD"])

# Standalone report
python config/backtest_dates.py
```

---

## 2. Indicator Warm-Up Extension

**Problem:** Strategies using long-lookback indicators (200-period EMA, 100-bar ATR)
need N bars before the first valid signal. Without warm-up, the first portion of the
backtest window produces no signals, effectively shrinking the evaluation period.

**Solution:** The pipeline automatically extends the data window backward from
`start_date` by the per-strategy resolved warm-up bars.

### Resolution Chain

```
Directive start_date (e.g. 2025-01-02)
       |
       v
indicator_warmup_resolver.py
  - Reads strategy's indicator list
  - Looks up each indicator in INDICATOR_REGISTRY.yaml
  - Evaluates warmup formula (e.g. "window * 2 + 10")
  - Returns max across all indicators
       |
       v
RESOLVED_WARMUP_BARS = max(calculated, 50)   # safety floor
       |
       v
run_stage1.py (data loading)
  - Loads data from (start_date - RESOLVED_WARMUP_BARS) to end_date
  - Engine only scores signals from start_date onward
```

### Key Files

| File | Role |
|------|------|
| `engines/indicator_warmup_resolver.py` | Computes per-strategy warm-up from registry |
| `indicators/INDICATOR_REGISTRY.yaml` | Indicator metadata with warmup formulas |
| `tools/run_stage1.py` (line 207-218) | Extends data window backward by warmup bars |
| `engine_dev/.../v1_5_3/main.py` (line 66-93) | Engine-level signal muting during warm-up |

### Warm-Up Implementation (run_stage1.py)

```python
# Line 213-218: Data window extension
warmup_bars = RESOLVED_WARMUP_BARS
requested_start_idx = df.index[df['timestamp'] >= START_DATE]
if not requested_start_idx.empty:
    start_idx = max(0, requested_start_idx[0] - warmup_bars)
    df = df.iloc[start_idx:]
```

### Double Safety Gate

1. **Data level** (run_stage1.py): Loads extra bars before start_date
2. **Engine level** (main.py v1.5.3): Wraps `check_entry`/`check_exit` to suppress
   signals during the warm-up period -- even if data extension is insufficient

### Defaults and Fallbacks

- **Safety floor:** 50 bars minimum (even if resolver returns less)
- **Fallback:** 250 bars if resolver fails entirely
- **Invariant:** `RESOLVED_WARMUP_BARS <= 0` triggers FATAL abort (line 717)

---

## 3. Multi-Timeframe Data Flow

The backtest pipeline operates on **three distinct timeframe levels** during execution.
Understanding this flow is critical for directive creation and debugging.

### Architecture: Signal TF + Regime 4H + HTF Daily

```
                   Data Loading
                   ============

   Signal Data                        Regime Data
   (Directive TF)                     (Fixed 4H)
        |                                  |
  load_market_data(symbol)          load_market_data(symbol, tf_override="4h")
        |                                  |
        v                                  v
   df (e.g. 15M bars)               df_regime (4H bars)
        |                                  |
        |                         apply_regime_model(df_regime)
        |                                  |
        |                    +-------------+-------------+
        |                    |             |             |
        |              Direction      Structure     Volatility
        |              Axis           Axis          Axis
        |                    |             |             |
        v                    v             v             v
   pd.merge_asof(df, df_regime, direction='backward')
        |
        v
   Merged DataFrame
   (15M bars with 4H regime columns forward-filled)
        |
        v
   Engine Execution Loop
   (signals evaluated on merged data)
```

### Level 1: Signal Timeframe (from directive)

- Timeframe specified in the directive YAML (`test.timeframe`)
- Used for entry/exit signal evaluation
- Warm-up extension applied to this data
- Examples: 5M, 15M, 30M, 1H, 4H, 1D

### Level 2: Regime Timeframe (fixed at 4H)

- **Always 4H** regardless of signal timeframe (`run_stage1.py` line 781)
- The regime state machine computes 13 indicator columns on 4H bars:

| Category | Indicators | Lookback |
|----------|-----------|----------|
| **Direction** (5) | `regime_lr` (linreg, w=50), `regime_lr_htf` (daily resample, w=200), `regime_kalman`, `regime_sha`, `regime_ema` (w=20) | 20--200 bars |
| **Structure** (5) | `regime_er`, `regime_tp`, `regime_hurst`, `val_adx`, `regime_autocorr` | 14--100 bars |
| **Volatility** (3) | `regime_vol_legacy` (ATR w=14), `val_atr_percentile`, `val_realized_vol` | 14--50 bars |

- These are merged into the signal-timeframe DataFrame via `pd.merge_asof(..., direction='backward')`
- Each signal bar inherits the most recent completed 4H regime state

### Level 3: HTF Daily (resampled from 4H internally)

- `linreg_regime_htf` (called inside the regime model) takes the 4H data and
  **resamples to daily closes** internally
- Computes linear regression on daily bars with `window=200`
- Forward-fills the daily regime back to 4H resolution
- This provides long-term directional bias (200 trading days ~ 10 months lookback)
- Requires ~200 daily bars (~10 months of 4H data) to warm up

### HTF Isolation Patch (run_stage1.py lines 829-890)

To prevent the engine from recomputing regime on signal-timeframe data (which
would produce incorrect regime states), the pipeline applies a **monkey-patch**:

1. `apply_regime_model` is patched to no-op ("Engine Regime Lock: 4H states preserved")
2. `strategy.prepare_indicators` is patched to re-merge 4H regime columns after
   any strategy indicator computation (prevents strategy from overwriting regime fields)
3. Both patches are restored in a `finally` block after execution

### Regime Columns Merged into Signal Data

The following columns are forward-filled from 4H into the signal-timeframe DataFrame:

```
market_regime, regime_id, regime_age,
direction_state, structure_state, volatility_state,
trend_score, trend_regime, trend_label, volatility_regime
```

Strategies access these as if they were computed on the signal timeframe.
The `merge_asof(direction='backward')` ensures no lookahead bias.

---

## 4. Data Freshness

**Source:** `data_root/freshness_index.json` (written by DATA_INGRESS after each ingest)
**Reader:** Trade_Scan is read-only; the pipeline reports stale symbols at run end.

### Freshness Index Schema

```json
{
  "buffer_days": 3,
  "entries": {
    "XAUUSD_OCTAFX_1h": {
      "first_date": "2015-01-02",
      "latest_date": "2026-03-31",
      "days_behind": 0,
      "source_file": "XAUUSD_OCTAFX_1h_2026_RESEARCH.csv"
    }
  }
}
```

- `first_date`: Earliest available data for this symbol/timeframe
- `latest_date`: Most recent bar date
- `days_behind`: Days since latest market close (0 = current)
- `buffer_days`: Threshold for stale warning (default: 3)

### Auto-Resolution

`config/backtest_dates.py` reads `freshness_index.json` to resolve `end_date`:
- Single symbol: uses that symbol's `latest_date`
- Multi-symbol: uses the **earliest** `latest_date` across all symbols (conservative)
- Missing index: falls back to `date.today()`

---

## 5. Run Summary View

**File:** `TradeScan_State/research/run_summary.csv`
**Generator:** `tools/generate_run_summary.py`

A denormalized join of all data sources into a single queryable CSV:

| Source | Columns Contributed |
|--------|-------------------|
| `run_registry.json` | tier, status, created_at |
| `research/index.csv` | Aggregated metrics (trades, PnL, PF, DD, win_rate) |
| `Master_Portfolio_Sheet.xlsx` | portfolio_verdict, portfolio_pf, portfolio_sharpe |
| `Filtered_Strategies_Passed.xlsx` | candidate_status, in_portfolio |

**Auto-updated** after every `PORTFOLIO_COMPLETE` directive (hooked in `run_pipeline.py`).
**Standalone:** `python tools/generate_run_summary.py`

Primary use: before forming any new directive, query this single file to check what
has been tried, what worked, and what verdict each run received.

---

## 6. Quick Reference: Directive Date Fields

```yaml
test:
  broker: OctaFX
  start_date: '2025-01-02'    # From backtest_date_policy.yaml
  end_date: '2026-03-31'      # From freshness_index.json
  timeframe: 15m
  name: STRATEGY_NAME
  strategy: STRATEGY_NAME
```

### Date Resolution Priority

1. `config/backtest_date_policy.yaml` -- timeframe-based start_date
2. `data_root/freshness_index.json` -- auto end_date from latest available data
3. `config/backtest_dates.py` -- helper function combining both

### Checklist Before Creating a Directive

1. Run `python config/backtest_dates.py` to confirm current date policy and freshness
2. Verify `start_date` matches the timeframe in `backtest_date_policy.yaml`
3. Verify `end_date` is current (check freshness report for stale symbols)
4. For PROMOTE candidates: switch to `stage="extended"` (full history)
