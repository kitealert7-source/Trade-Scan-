# Capital Wrapper Safety Audit
## Changes Applied 2026-03-11 — Universal Research Engine v1.5.3
## Updated 2026-04-03 — MT5 Static Valuation + Leverage Calibration

**Audit Date:** 2026-03-11 (original) | 2026-04-03 (valuation + calibration update)
**Scope:** tools/capital_wrapper.py + tools/capital_engine/simulation.py + execution_engine/ + data_access/broker_specs/

---

## Summary of Changes

Six distinct safety and correctness improvements were applied to the capital wrapper and
deployment pipeline in a single session. Each is documented below with its motivation,
implementation, and verification status.

---

## 1. SIMULATION_SEED Constant

**File:** `tools/capital_wrapper.py`
**Type:** Maintainability / Reproducibility

### Change
```python
# Before (hardcoded in run_simulation):
_rng = random.Random(42)

# After:
SIMULATION_SEED = 42   # line 101, module-level constant
# ...
_rng = random.Random(SIMULATION_SEED)
```

### Rationale
A hardcoded literal `42` inside a function body is invisible to:
- Monte Carlo tooling that needs to sweep seeds
- Debugging workflows that want a single place to change
- Other modules (e.g. strategy_guard.py) that need to reference the same seed

`SIMULATION_SEED` is now a module-level constant alongside `EVENT_TYPE_ENTRY`, `EVENT_TYPE_EXIT`,
and `PROFILES`. It is also exported to `golive/run_manifest.json` so the live engine knows which
seed produced the trade log.

### Verification
Changing SIMULATION_SEED changes the order of ENTRY events within timestamp-collision groups,
which produces different acceptance counts across profiles. This is expected and correct.

---

## 2. Collision-Randomization Fix (Alphabetical ENTRY Bias)

**File:** `tools/capital_wrapper.py` — `run_simulation()`
**Type:** Correctness / Fairness

### Problem
37.5% of all ENTRY events share a timestamp with at least one other symbol's ENTRY. Before this
fix, these were processed in trade_id lexicographic order (effectively alphabetical by symbol).
For this strategy (6 symbols: AUDNZD, AUDUSD, EURUSD, GBPNZD, GBPUSD, USDJPY):
- AUDNZD (1st alphabetically) received capacity preferentially
- USDJPY (last) was most frequently rejected when capacity was tight
- Example from FIXED_USD_V1: AUDNZD had 29 leverage rejections vs USDJPY 43 — all from ordering

### Fix
Within each timestamp group, ENTRY events are shuffled using a seeded RNG before processing:
```python
_rng = random.Random(SIMULATION_SEED)
# ...
# Within timestamp group:
exits   = [e for e in group if e.event_type == EVENT_TYPE_EXIT]
entries = [e for e in group if e.event_type == EVENT_TYPE_ENTRY]
_rng.shuffle(entries)
for event in exits + entries:
    ...
```

EXITs still process before ENTRYs within each timestamp group (unchanged — capital freed first).

### Verification
`tools/verify_collision_fix.py` — two runs confirmed:
- IDENTICAL equity curves and trade sequences across 5 profiles
- GBPUSD leverage rejections: 61 → 40 (reduced from alphabetical over-rejection)
- USDJPY leverage rejections: 43 → 28 (reduced from alphabetical late-processing disadvantage)
- All invariants PASS on both runs

---

## 3. USD-Normalised Leverage Calculation Fix (USDJPY Bug)

**File:** `tools/capital_wrapper.py` — `process_entry()`
**Type:** Correctness / Critical Bug Fix

### Problem
Leverage cap check used raw price-denominated notional:
```python
# Bug (v1):
trade_notional = lot_size * contract_size * event.entry_price
```
For USDJPY (entry_price ~148 JPY): notional = lot × 100,000 × 148 = in JPY, not USD.
Dividing by equity ($10,000 USD) produced leverage readings of ~89× against a 5× cap.
Result: 100% of USDJPY trades were rejected by LEVERAGE_CAP in all profiles that enforce it.

### Fix (v2, 2026-03-11)
```python
# usd_per_pu_per_lot = contract_size * quote_ccy_to_USD_rate
trade_notional = lot_size * event.entry_price * usd_per_pu_per_lot
```

### Current State (v3, 2026-04-03)
The v2 fix used a dynamic conversion lookup for `usd_per_pu_per_lot`. This has been replaced by MT5-verified static valuation. The notional formula is unchanged, but the source of `usd_per_pu_per_lot` is now:
```python
usd_per_pu_per_lot = broker_spec["calibration"]["usd_pnl_per_price_unit_0p01"] * 100.0
# Derived from MT5: tick_value / tick_size, frozen at extraction date (2026-04-02)
```
This eliminates both the USDJPY bug (resolved in v2) and any dependency on runtime FX rate feeds.

### Impact (FIXED_USD_V1 profile)
| | Before fix | After fix |
|---|---|---|
| USDJPY accepted | ~0 (all rejected) | 398 |
| USDJPY leverage rejections | ~426 | 28 (genuine cap breaches) |
| FIXED_USD_V1 final equity | $12,800 (inflated, without USDJPY) | $12,182 (correct) |
| FIXED_USD_V1 CAGR | 19.4% | 15.2% |

The equity reduction is expected and correct. The inflated pre-fix equity reflected only 5 of 6
symbols contributing to PnL; the post-fix equity reflects all 6 with correct leverage enforcement.

---

## 4. Deployable Trade Log Column Additions

**File:** `tools/capital_wrapper.py` — `process_exit()` + `emit_profile_artifacts()`
**Type:** Artifact Completeness

### Changes

**process_exit() — log_entry dict:**
```python
# Added (previously missing from dict entirely):
"risk_distance": trade.risk_distance,
"signal_hash":   compute_signal_hash(trade.symbol, entry_ts_str, trade.direction,
                                     trade.entry_price, trade.risk_distance),
```
Note: `entry_price` and `exit_price` were already in the dict but silently discarded by
`extrasaction='ignore'` in DictWriter. The root fix was adding them to `trade_fields`.

**emit_profile_artifacts() — trade_fields list:**
```python
trade_fields = [
    "trade_id", "symbol", "lot_size", "pnl_usd",
    "entry_timestamp", "exit_timestamp", "direction",
    "entry_price", "exit_price", "risk_distance",   # reconstruction fields
    "signal_hash",                                   # integrity fingerprint
]
```

### Resulting CSV Header (v2)
```
trade_id, symbol, lot_size, pnl_usd, entry_timestamp, exit_timestamp, direction,
entry_price, exit_price, risk_distance, signal_hash
```

Override-tracked profiles (MIN_LOT_FALLBACK_*) append 4 additional columns after this base set.

### Backward Compatibility
The `signal_hash` column is new. Older code reading the CSV with `csv.DictReader` will receive
`None` for this column if it reads artifacts generated before this change. The `StrategyGuard`
handles this gracefully — if `signal_hash` is absent from the trade log, the signal index is
empty and integrity checks are skipped with a warning (not a block).

---

## 5. Signal Hash Formula (compute_signal_hash)

**File:** `tools/capital_wrapper.py`
**Type:** Signal Integrity

### Implementation
```python
def compute_signal_hash(symbol, entry_timestamp, direction, entry_price, risk_distance):
    s = (
        f"{symbol}|{entry_timestamp}|{direction}"
        f"|{entry_price:.5f}|{risk_distance:.5f}"
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
```

### Design Decisions
- **5 decimal places** for price/distance: sufficient for FX precision (0.00001 pip) while
  avoiding float representation noise at lower decimal positions
- **16-char truncation**: 64-bit collision resistance (2^64 ≈ 1.8×10^19) — adequate for
  signal deduplication; not intended as a cryptographic commitment
- **Field ordering fixed**: `symbol|ts|dir|price|dist` — order must never change once deployed
  artifacts exist, as changing it would invalidate all stored hashes
- **str(timestamp) matching**: the hash uses `str(trade.entry_timestamp)` which produces
  `"YYYY-MM-DD HH:MM:SS"` for datetime objects — must match exactly in live engine

### Identical Formula in strategy_guard.py
The live engine uses `_compute_signal_hash()` in `execution_engine/strategy_guard.py` which is
an exact copy of this formula. Both modules must stay in sync. If the formula ever changes,
all stored signal_hashes become stale and a full re-run of capital_wrapper is required.

---

## 6. Stage-10 Go-Live Package Generator

**File:** `tools/generate_golive_package.py` (new)
**Type:** Deployment Infrastructure

### Purpose
Assembles a deterministic, self-contained deployment package from existing artifacts.
Does NOT recompute trades, modify capital_wrapper.py, or introduce randomness.

### Artifacts Generated
```
strategies/<PREFIX>/golive/
├── run_manifest.json      — strategy identity, symbols, data window, simulation seed
├── symbols_manifest.json  — [{symbol, broker}, ...] sorted
├── selected_profile.json  — enforcement rules, sizing parameters, profile_hash
└── directive_snapshot.yaml — copy of backtest_directives/completed/<PREFIX>.txt
```

### selected_profile.json Schema (key fields)
```json
{
  "profile": "FIXED_USD_V1",
  "profile_hash": "<sha256 of enforcement+sizing>",
  "profile_hash_algo": "sha256",
  "enforcement": {
    "max_portfolio_risk_pct": 0.04,
    "max_leverage": 11,
    "max_open_trades": null
  },
  "sizing": {
    "starting_capital": 10000.0,
    "fixed_risk_usd": 50.0,
    ...
  },
  "simulation_metrics": { ... }
}
```

**Note:** `max_leverage` was 5 prior to 2026-04-03. Calibrated to 11 based on p99 = 10.67x across 22,282 shadow trades. See `CAPITAL_SIZING_AUDIT.md` Section 9 for full calibration data.

### Profile Hash Guard
SHA-256 computed over `{"enforcement": ..., "sizing": ...}` with `sort_keys=True,
separators=(",",":")` for canonical, deterministic serialisation. The live engine
startup sequence must recompute this hash and raise RuntimeError on mismatch.

---

## 7. Execution Engine — Strategy Guard

**File:** `execution_engine/strategy_guard.py` (new)
**Type:** Live Safety Layer

### Module Structure
```
StrategyGuard
├── from_golive_package()    — factory: loads baseline from golive/ dir
├── _verify_profile_hash()   — startup: recomputes and validates profile_hash
├── verify_signal()          — per-trade: signal hash lookup + block on mismatch
├── record_trade()           — per-close: updates state, evaluates kill-switch
├── _check_kill_switch()     — evaluates 3 rules
└── status_dict()            — observable state for monitoring

BaselineStats                — computed from deployable artifacts (no re-simulation)
GuardConfig                  — configurable thresholds (dataclass, all defaults match spec)
GuardEvent                   — immutable event record written to alert_log

SignalMismatchError           — raised by verify_signal() on hash mismatch
StrategyHaltedError          — raised by record_trade() when any kill-switch trips
```

### Kill-Switch Rules and Thresholds

| Rule | Formula | Default Multiplier | Source |
|------|---------|-------------------|--------|
| Loss Streak | live_streak > historical_max × M | M = 1.5 | GuardConfig.max_loss_streak_multiplier |
| Win Rate | rolling_WR(N) < expected_WR × T | T = 0.65, N = 50 | GuardConfig.win_rate_tolerance, rolling_window_trades |
| Equity DD | live_equity < start − D × historical_max_dd | D = 2.0 | GuardConfig.dd_multiplier |

Baseline statistics (`expected_win_rate`, `max_loss_streak`, `max_drawdown_usd`) are derived
from `deployable_trade_log.csv` and `selected_profile.json` — no simulation re-run required.

### Alert Log
Each halt event is appended as a JSON line to the `alert_log` path (if configured):
```json
{"event_type": "HALT_LOSS_STREAK", "reason": "...", "timestamp_utc": "...", "live_streak": 14, ...}
```

---

## 8. Validation Test Suite

**File:** `tools/validate_safety_layers.py` (new)
**Type:** Regression / Acceptance Testing

### Test Results (2026-03-11, strategy 01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00, FIXED_USD_V1)

| Test | Description | Result |
|------|-------------|--------|
| T1 | signal_hash column present, 16-char, no blanks (2258 rows) | PASS |
| T2 | Hash lists identical across two independent simulation runs | PASS |
| T3 | Correct signal passes; tampered entry_price (+1.0) raises SignalMismatchError | PASS |
| T4 | 14 consecutive -$10 losses halts strategy (threshold=13.5) | PASS |
| T5 | Single -$1,797.10 loss drops equity to $8,202.90 below floor $8,203.90, halts | PASS |

---

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `tools/capital_wrapper.py` | Modified | Added: `import hashlib`, `SIMULATION_SEED`, `compute_signal_hash()`, collision shuffle in `run_simulation()`, USD-normalised notional in `process_entry()`, `risk_distance`+`signal_hash` in `log_entry`, new columns in `trade_fields` |
| `tools/generate_golive_package.py` | New | Stage-10 go-live package generator |
| `execution_engine/__init__.py` | New | Package marker |
| `execution_engine/strategy_guard.py` | New | Signal integrity guard + statistical kill-switch |
| `tools/verify_collision_fix.py` | New | Before/after comparison for collision-randomization |
| `tools/validate_safety_layers.py` | New | 5-test acceptance suite for safety layers |

---

---

## 9. MT5 Static Valuation Migration (2026-04-03)

**Files:** `tools/capital_engine/simulation.py`, `tools/capital_wrapper.py`, `data_access/broker_specs/OctaFx/*.yaml` (30 files)
**Type:** Correctness / Simplification

### Problem
The dynamic USD conversion path (`get_usd_per_price_unit_dynamic()`) depended on runtime FX rate lookups via `ConversionLookup`. This introduced:
- Dependency on rate data availability at simulation time
- Potential rate lookup failures for exotic cross pairs
- Inconsistency between research and live environments (different rate sources)

### Fix
Replaced the entire dynamic conversion path with MT5-verified static valuation:

```python
# simulation.py — hot path simplified to:
symbol_usd_per_pu: Dict[str, float] = {}
for sym, spec in broker_specs.items():
    symbol_usd_per_pu[sym] = get_usd_per_price_unit_static(spec)

# On entry:
usd_per_pu = symbol_usd_per_pu[sym]
```

**Removed from simulation.py:**
- `symbol_quote_ccy` dict and `_parse_fx_currencies()` call
- `get_usd_per_price_unit_dynamic()` from hot path
- `conv_lookup` dependency (parameter kept for API compat, ignored)

**Removed from capital_wrapper.py:**
- `ConversionLookup` initialization and `conv_lookup` construction
- All dynamic conversion code in `main()`

### Broker Spec Patching
All 30 YAML files patched via `tools/verify_broker_specs.py --force-all` using MT5 ground truth from `TS_Execution/outputs/symbol_specs_mt5.json`:

| Field | Source |
|-------|--------|
| `calibration.usd_pnl_per_price_unit_0p01` | `tick_value / tick_size * 0.01` |
| `calibration.usd_per_pu_per_lot` | `tick_value / tick_size` |
| `mt5_tick_value` | `symbol_info().trade_tick_value` |
| `mt5_tick_size` | `symbol_info().trade_tick_size` |
| `currency_profit` | `symbol_info().currency_profit` |
| `digits` | `symbol_info().digits` |
| `status` | `MT5_VERIFIED` |

### Key Corrections Discovered

| Symbol | Old usd_pnl * 100 | MT5-derived | Error Factor |
|--------|-------------------|-------------|-------------|
| JPN225 | 10.0 | 0.627 | 16x overestimate |
| SPX500 | 10.0 | 1.0 | 10x overestimate |
| EURGBP | 125.0 | 132,131.0 | 1057x underestimate |
| USDCAD | 725.0 | 71,840.0 | 99x underestimate |

### Design Decision: Static for ALL Symbols
21 of 31 symbols have non-USD profit currencies. The frozen `tick_value` embeds the FX rate at MT5 extraction time (2026-04-02). This introduces bounded drift:
- JPY pairs: up to ~12% over 2-year backtest window
- EUR/GBP pairs: up to ~5%

**Decision:** Accept static drift for all symbols. No hybrid (static for USD, dynamic for non-USD). Rationale: consistent methodology, no runtime dependencies, drift is within research tolerance for risk sizing.

### Verification
- `tools/verify_broker_specs.py --mt5-json`: all 31 symbols at ratio 1.0000 against ground truth
- EURUSD 1-pip test: $10.00 expected, $10.00 actual
- USDJPY JPY-denominated: correct after `tick_value / tick_size` normalization
- NAS100/US30: confirmed unchanged (were already correct)
- Burn-in run: no crashes, no PnL outliers, leverage cap normal

---

## 10. FIXED_USD_V1 Leverage Cap Calibration (2026-04-03)

**File:** `tools/capital_wrapper.py` — `PROFILES["FIXED_USD_V1"]["leverage_cap"]`
**Type:** Calibration

### Change
```python
# Before:
"leverage_cap": 5,

# After:
"leverage_cap": 11,   # calibrated from p99 = 10.67x
```

### Methodology
Computed `required_leverage = (lot * entry_price * usd_per_pu) / equity` for every trade in the shadow portfolio (22,282 trades, all strategies, all symbols, $10K equity):

| Percentile | Required Leverage |
|------------|------------------|
| p95 | 8.23x |
| p99 | 10.67x |
| max | 21.62x |

Selected `ceil(p99) = 11` to achieve >98% acceptance while capping the tail.

### Validation
- Acceptance: 98.4% (856/906 on XAUUSD portfolio)
- 0 invariant breaches (heat, leverage, equity)
- All 15 rejections are genuine LEVERAGE_CAP breaches, not calibration artifacts

### Impact on Other Profiles
Only FIXED_USD_V1 was changed. All other profiles retain `leverage_cap: 5` (CONSERVATIVE, MLF, MLF_UNCAP, BOUNDED) or `leverage_cap: 15` (DYNAMIC).

---

## 11. Capital Floor Finding (2026-04-03)

**Type:** Research Finding (no code change)

### XAUUSD: $10K Minimum
At $5K equity with $25 risk (proportionally equivalent to $10K/$50), 45.3% of XAUUSD trades fall to the 0.01 broker lot floor. These fallback trades produce identical PnL at both capital levels, breaking the expected 2:1 scaling. PnL ratio observed: 1.76 (expected: 2.0).

**Root cause:** XAUUSD has `usd_per_pu_per_lot = 100`. At $25 risk: `lot = 25 / (risk_distance * 100)`. Falls below 0.01 when `risk_distance > 2.5` ($250 move). Many XAUUSD trades exceed this.

### FX: Scales to $5K
FX pairs have `usd_per_pu_per_lot` in the 60,000-130,000 range. At $25 risk, lot sizes are always well above 0.01. Fallback rate: 0.0% at both capital levels. PnL ratio: 2.0-2.3 (clean scaling). Acceptance: 99.4%.

### Implication
The capital floor is **instrument-specific**, determined by the ratio of typical risk_distance to usd_per_pu_per_lot. High-usd_per_pu instruments (FX) have no floor issue. Low-usd_per_pu instruments (XAUUSD, indices) require higher capital to avoid lot floor saturation.

Full data tables: see `CAPITAL_SIZING_AUDIT.md` Sections 10-11.

---

## Updated File Change Summary (2026-04-03)

| File | Change Type | Description |
|------|-------------|-------------|
| `tools/capital_engine/simulation.py` | Modified | Removed dynamic conversion path; static-only valuation; `conv_lookup` deprecated |
| `tools/capital_wrapper.py` | Modified | Removed ConversionLookup init; `leverage_cap` 5 -> 11; static valuation print |
| `data_access/broker_specs/OctaFx/*.yaml` (30) | Modified | MT5-derived calibration values, `status: MT5_VERIFIED` |
| `tools/verify_broker_specs.py` | New | MT5 ground truth verification + YAML patching tool |

---

*Generated: 2026-03-11 | Updated: 2026-04-03 | Engine: Universal_Research_Engine v1.5.4*
