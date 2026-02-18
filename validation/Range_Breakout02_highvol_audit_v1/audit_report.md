# Audit Extraction Report: Range_Breakout02_highvol_audit_v1

## Executive Summary

This report extracts the exact logic from the immutable snapshot `Range_Breakout02_highvol_audit_v1`.

### 1. Strategy Timeframe

**Value**: `5m`
**Source**: `strategy/strategy.py:18`

```python
18:     timeframe = "5m"
```

### 2. Range Definition Window

**Value**: 03:00 to 06:00 UTC
**Source**: `strategy/strategy.py:32`

```python
32:         structure = session_range_structure(df, session_start="03:00", session_end="06:00")
```

### 3. Exact Breakout Trigger Condition

**Logic**:

1. **Breakout Detection**: High > Session High (Long) or Low < Session Low (Short), strictly *after* the session end (06:00).
    * **Source**: `indicators/range_breakout_session.py:78-83`
2. **Signal Generation**: Triggered on the exact bar where the break status transitions from `0` (No Break) to `1` or `-1`.
    * **Source**: `strategy/strategy.py:66`

    ```python
    66:         if self.prev_break_direction == 0 and current_break_direction != 0:
    ```

### 4. Daily Trade Cap Logic

**Logic**: Maximum **2** trades per day. Counter resets on date change.
**Source**: `strategy/strategy.py:69`

```python
69:             if self.daily_trade_count < 2:
```

### 5. Stop Loss Rule

**Logic**:

* **Long**: Exit if `current_low < session_low`
* **Short**: Exit if `current_high > session_high`
**Source**: `strategy/strategy.py:112-118`

### 6. Time-Based Exit Rule

**Logic**: Hard exit at **18:00 UTC** (Minute 0).
**Source**: `strategy/strategy.py:96`

```python
96:             if ts.hour == 18 and ts.minute == 0:
```

### 7. Volatility Filter at Entry

**Status**: **NONE**.
**Finding**: The `check_entry` method contains no logic to filter trades based on volatility or regime. It relies solely on `daily_trade_count` and `break_direction`.
**Source**: `strategy/strategy.py:39-81`

### 8. Regime Application

**Status**: **Post-Trade Annotation Only**.
**Finding**: Volatility regime ('low', 'normal', 'high') is computed by `compute_volatility_regimes` in the execution emitter. This modifies the trade record *after* the trade list is generated, primarily for reporting/splitting purposes. It does not prevent trade execution.
**Source**: `tools/execution_emitter_stage1.py:71-127`

### 9. Regime Shift Logic

**Status**: **N/A** (Regime is not used for entry).
**Note**: The emitter calculates regime based on `atr_entry` (or proxy) of the trade itself, effectively looking at the volatility *at the time of the trade* (or using static proxies like range or % of price). There is no "shift" applied references in the code.
