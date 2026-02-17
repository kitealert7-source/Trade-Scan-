# Strategy Plugin Contract — Trade_Scan (LOCKED)

**Status:** AUTHORITATIVE  
**Applies to:** All strategies executed by Trade_Scan  
**Purpose:** Define the mandatory interface and placement rules for strategy plugins.

This document defines **what a strategy is allowed to be**, and **what the engine is forbidden from knowing**.

---

## 1. Placement (MANDATORY)

Every strategy MUST reside at:

```
Trade_Scan/strategies/<STRATEGY_ID>/strategy.py
```

Examples:

```
strategies/SPX01/strategy.py
strategies/FF001/strategy.py
```

No other locations are permitted.

---

## 2. Ownership Rules (LOCKED)

- All **indicator invocation and parameter selection** belong to the strategy.
- All **entry / exit decision logic** belongs to the strategy.
- All **indicator implementation** belongs to the `indicators/` repository and MUST NOT be reimplemented inline.

- The engine MUST NOT:
  - compute indicators
  - inspect indicator values
  - branch on strategy identity

The engine interacts with strategies **only through this contract**.

---

## 3. Mandatory Strategy Interface

Every `strategy.py` MUST expose exactly one class named `Strategy`.

```python
class Strategy:
    # --- Static Declarations ---
    name: str                  # Strategy ID (must match directive)
    instrument_class: str       # FOREX | INDEX | CRYPTO
    timeframe: str              # Execution timeframe (e.g. 15m, D1)

    # --- Lifecycle Hooks ---
    def prepare_indicators(self, df):
        """
        Compute and attach all indicators.
        Must return a dataframe.
        """

    def check_entry(self, ctx) -> bool:
        """
        Return True to enter a new position.
        ctx contains current and historical bar context.
        """

    def check_exit(self, ctx) -> bool:
        """
        Return True to exit the active position.
        ctx contains current bar and trade state.
        """
```

No additional public methods are allowed.

---

## 4. Context Object (Read-Only)

The engine supplies a read-only `ctx` object containing:

- current bar data
- prior bars (as needed)
- bars_held
- entry_price
- best_price / worst_price (if in position)

Strategies MUST NOT:

- mutate engine state
- access broker specs directly
- write artifacts

---

## 5. Indicator Constraints

- Indicators may use:
  - numpy
  - pandas
  - pure helper functions
- Indicators MUST be:
  - deterministic
  - NaN-safe
  - stateless

No caching, global state, or cross-strategy sharing.

---

## 6. Governance Integration

### SOP_TESTING

- Strategy logic MUST comply with this contract.
- Any deviation invalidates the run.

### Preflight Agent

Preflight MUST block execution if:

- strategy module is missing
- `Strategy` class is missing
- required attributes are absent
- module fails to import cleanly

---

## 7. Change Policy (HARD)

Any change to this contract:

- is **engine evolution**
- requires a new engine version
- requires SOP update
- requires explicit human approval

---

**End of Strategy Plugin Contract**
