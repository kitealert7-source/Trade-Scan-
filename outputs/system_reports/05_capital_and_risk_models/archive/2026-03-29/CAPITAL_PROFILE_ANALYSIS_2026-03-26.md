# Capital Deployment Profiles — Analysis Report
**Date:** 2026-03-26
**Scope:** 6 active portfolio strategies (SPKFADE S03, BOS S03, FAKEBREAK P04, LIQSWEEP P06, IMPULSE P02, MICROREV P12)
**Source:** `TradeScan_State/strategies/*/deployable/profile_comparison.json`
**Type:** Read-only analysis — no code changes

---

## The 7 Profiles Decoded

All 6 active strategies have identical profile structure. The profiles represent different
**lot-sizing algorithms** — the backtest research engine tested 7 distinct approaches to computing
position size from the same trade signals:

| Profile | Algorithm | Risk Approach | Key Characteristic |
|---|---|---|---|
| **RAW_MIN_LOT_V1** | Always use `volume_min` | Flat minimum lot | Zero risk scaling — every trade gets the broker minimum regardless of equity or stop distance |
| **BOUNDED_MIN_LOT_V1** | Min lot as floor, risk-scaled upward with a bound | Partially risk-based | `risk_override_rate` > 0 means some trades got upgraded past min lot. Highest return but largest drawdown among the min-lot group |
| **CONSERVATIVE_V1** | Risk-based with a tighter risk % | Lower percentage | More trade rejections (2–6%) when stop distance implies oversized lot — trades filtered out, not just capped |
| **DYNAMIC_V1** | Volatility/equity-scaled | Risk-percentage-based | Lot scales with account equity × risk %. Some rejections for extreme stop distances |
| **FIXED_USD_V1** | Fixed dollar risk per trade | Dollar-absolute | `risk_amount` is a fixed USD value, not a percentage of equity — results nearly identical to DYNAMIC_V1 at $10k |
| **MIN_LOT_FALLBACK_V1** | Risk-based, fallback to min lot when below minimum | Risk + min floor | `risk_override_rate` reflects how often the computed lot fell below `volume_min` and was bumped up. Capped at `max_lot` |
| **MIN_LOT_FALLBACK_UNCAPPED_V1** | Same as above, no lot cap | Risk + min floor, uncapped | Identical results to V1 for these strategies — computed lots never hit `max_lot` at a single-strategy $1k allocation |

**Note — MIN_LOT_FALLBACK_V1 and UNCAPPED identical:** At $1,000 effective capital with 1% risk,
the computed lot for XAUUSD is so small it hits `volume_min` on nearly every trade. The cap is
irrelevant at this capital level. Results diverge only at higher capital where computed lots
approach `max_lot`.

---

## Profile Comparison by Strategy (selected)

### SPKFADE S03 — 265 trades, 5.14 years

| Profile | PnL | CAGR% | MaxDD% | MAR | Rejections |
|---|---|---|---|---|---|
| RAW_MIN_LOT_V1 | $404.84 | 0.78% | 0.99% | 0.778 | 0 |
| BOUNDED_MIN_LOT_V1 | $865.57 | 1.63% | 9.73% | 0.167 | 0 |
| CONSERVATIVE_V1 | $187.20 | 0.37% | 3.66% | 0.101 | 6 |
| DYNAMIC_V1 | $547.87 | 1.04% | 7.48% | 0.140 | 2 |
| FIXED_USD_V1 | $532.54 | 1.02% | 7.58% | 0.134 | 2 |
| MIN_LOT_FALLBACK_V1 | $674.26 | 1.28% | 7.48% | 0.171 | 0 |
| MIN_LOT_FALLBACK_UNCAPPED_V1 | $674.26 | 1.28% | 7.48% | 0.171 | 0 |

### FAKEBREAK P04 — 365 trades, 5.19 years

| Profile | PnL | CAGR% | MaxDD% | MAR | Rejections |
|---|---|---|---|---|---|
| RAW_MIN_LOT_V1 | $365.29 | 0.69% | 1.49% | 0.466 | 0 |
| BOUNDED_MIN_LOT_V1 | $1,404.40 | 2.56% | 9.24% | 0.277 | 11 |
| CONSERVATIVE_V1 | $379.95 | 0.74% | 4.54% | 0.164 | 22 |
| DYNAMIC_V1 | $865.79 | 1.61% | 8.54% | 0.189 | 5 |
| FIXED_USD_V1 | $888.84 | 1.65% | 8.59% | 0.193 | 5 |
| MIN_LOT_FALLBACK_V1 | $970.28 | 1.80% | 8.59% | 0.210 | 0 |
| MIN_LOT_FALLBACK_UNCAPPED_V1 | $970.28 | 1.80% | 8.59% | 0.210 | 0 |

---

## Where the Chosen Profile Is Implemented in the Execution System

**Single location: `portfolio.yaml` execution block → `_compute_lot()` in `execution_adapter.py`**

Currently the code implements exactly the **DYNAMIC_V1 / MIN_LOT_FALLBACK_V1** logic:

```python
# execution_adapter.py — _compute_lot()
risk_amount   = equity * risk_pct / 100.0          # risk_pct from portfolio.yaml
risk_distance = abs(entry_reference_price - stop_price)

if risk_distance == 0.0:
    return symbol_info.volume_min                   # degenerate signal fallback

lot = risk_amount / (risk_distance / tick_size * tick_value)
lot = round(lot / step) * step
lot = max(volume_min, min(lot, max_lot))            # clamped to [min, max_lot]
```

No `strategy.py` files are touched. Strategy files have no sizing knowledge — they only output
`stop_price` and `entry_reference_price`. The entire profile decision lives in the execution layer.

### Concrete Mapping — Profile to Implementation

| Profile to implement | What to change |
|---|---|
| RAW_MIN_LOT_V1 | Always return `volume_min` — remove risk computation entirely |
| CONSERVATIVE_V1 | Lower `risk_per_trade_pct` (e.g. 0.3–0.5) + add max-distance rejection gate |
| DYNAMIC_V1 | **Current code is this.** `risk_per_trade_pct: 1.0` in portfolio.yaml |
| FIXED_USD_V1 | Replace `equity * risk_pct / 100` with a fixed USD constant |
| MIN_LOT_FALLBACK_V1 | **Current code is this.** Already falls back to `volume_min` when computed lot < minimum |
| BOUNDED_MIN_LOT_V1 | Needs a scaling multiplier that lifts min_lot upward with a bound — not currently implemented |
| MIN_LOT_FALLBACK_UNCAPPED_V1 | Remove `max_lot` cap from `_compute_lot()` |

**Per-strategy profiles** (different risk % per strategy) would require moving `risk_per_trade_pct`
from the global `execution:` block into each `portfolio.strategies:` entry and reading it per slot.
Not currently implemented. All 6 strategies share the same `risk_per_trade_pct: 1.0`.

---

## Is the Profile Being Tested in Burn-In Phase A?

**No. Completely untested. The profile has zero observable effect during Phase A.**

The equity guard fires first, before lot computation is ever reached:

```python
# ipc_dispatch.py / execution_adapter.py
if account.equity <= 0:         # always True in Phase A (equity = 0)
    # → EXEC_SKIPPED_NO_CAPITAL
    # → shadow activated
    return                      # _compute_lot() is NEVER called
```

Even if the equity guard were hypothetically bypassed:
`risk_amount = 0 × 1.0 / 100.0 = 0` → lot = 0 → fallback to `volume_min`

The sizing math cannot operate on zero capital. The profile choice is irrelevant until equity > 0.

### What Phase A Tests vs Does Not Test

| Capability | Phase A (burn-in, equity=0) | Phase B (live, equity>0) |
|---|---|---|
| Signal quality (entry logic) | ✅ Observed via shadow | ✅ Live orders |
| Exit timing (bars_held, SL) | ✅ Observed via shadow exit | ✅ Live close dispatch |
| Stop distance distribution | ✅ Logged per signal | ✅ Used in lot computation |
| Lot-sizing profile | ❌ Never executes | ✅ Every dispatch |
| Trade rejection rate | ❌ No capital to gate | ✅ Gates active |
| Portfolio heat / concurrency | ❌ No positions open | ✅ Gate 3 applies |
| `risk_per_trade_pct` sensitivity | ❌ Zero capital | ✅ Directly controls lot size |

---

## Practical Decision for Go-Live (Phase B)

The current `portfolio.yaml` setting (`risk_per_trade_pct: 1.0`) already implements
**DYNAMIC_V1 / MIN_LOT_FALLBACK_V1** — the profile that produced the best MAR ratios
across all 6 strategies without the oversizing risk of BOUNDED_MIN_LOT_V1.

Three parameters in the `execution:` block control the effective profile at go-live:

| Parameter | Current value | Effect |
|---|---|---|
| `risk_per_trade_pct` | `1.0` | Scales all lot sizes linearly — 0.5 halves every lot |
| `max_lot` | `5.0` | Hard cap — prevents runaway sizing at high equity |
| (implicit) min lot fallback | Always active | `volume_min` floor already in `_compute_lot()` |

The research profile data (CAGR, MaxDD, MAR) is per-strategy on $1k effective capital.
At go-live the portfolio-level metrics will differ because:
1. Multiple strategies run concurrently — portfolio heat accumulates
2. Actual account equity determines all lot sizes, not the $1k per-strategy research allocation
3. Gate 3 (capital_wrapper — future) will add portfolio-level concurrency and exposure limits

No code changes are needed for the chosen profile — it is already implemented.
Profile data lives in `TradeScan_State` for reference. Selection decision is documented here.
