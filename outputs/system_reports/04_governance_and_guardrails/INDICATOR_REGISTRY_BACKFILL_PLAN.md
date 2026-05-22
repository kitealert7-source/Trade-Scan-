# INDICATOR_REGISTRY Backfill Plan — 22 Stub Entries

**Date:** 2026-05-12
**Predecessor:** `outputs/INDICATOR_GOVERNANCE_SYNC_2026_05_12.md` (version_9 sync)
**Purpose:** Backfill required fields (`lookback`, `warmup`, `input_columns`) for the 22 stub entries added in commit `5a354db` so that `tests/test_registry_integrity.py` passes.

All 22 module imports were probed via `importlib.import_module` — every one resolves clean (no missing-dependency surprises).

## Per-Indicator Audit Table

| Indicator | Module path | Disk file | Imports OK | Active strategy hits | Missing required | Inference plan |
|---|---|---|---|---|---|---|
| `cmo` | `indicators.momentum.cmo` | `indicators/momentum/cmo.py` | yes | 0 | lookback, warmup, input_columns | Single `period` arg default=9; `series.rolling(period).sum()` -> lookback=period, warmup=period; reads close series only -> input_columns=[close] |
| `macd` | `indicators.momentum.macd` | `indicators/momentum/macd.py` | yes | 0 | lookback, warmup, input_columns | fast=12/slow=26/signal=9; warmup = slow+signal (explicit in code line 59 `warmup = slow + signal`); lookback = slow; close only |
| `macd_htf` | `indicators.momentum.macd_htf` | `indicators/momentum/macd_htf.py` | yes | 1 (utils) | lookback, warmup, input_columns | Same as macd: `warmup = slow + signal` (code line 158); close only |
| `rsi_extremes` | `indicators.momentum.rsi_extremes` | `indicators/momentum/rsi_extremes.py` | yes | 0 | lookback, warmup, input_columns | `period=14` + `lookback=20`; chain depends on rsi(period) then rolling(lookback); lookback = period + lookback (max of `lookback` window over rsi which itself needs `period`); close only |
| `consecutive_closes` | `indicators.price.consecutive_closes` | `indicators/price/consecutive_closes.py` | yes | 1 (test) | lookback, warmup, input_columns | `n` param default=3; compares close to prior close → lookback=2 (current+prev); close only |
| `consecutive_highs_lows` | `indicators.price.consecutive_highs_lows` | `indicators/price/consecutive_highs_lows.py` | yes | 0 | lookback, warmup, input_columns | `n` default=3; uses n+1 bar window (lines 37-38: `range(n+1)`) → lookback = n+1; reads high+low |
| `avg_range` | `indicators.structure.avg_range` | `indicators/structure/avg_range.py` | yes | 0 | lookback, warmup, input_columns | `window` default=5; rolling(window); high+low |
| `choch_v2` | `indicators.structure.choch_v2` | `indicators/structure/choch_v2.py` | yes | 11 | lookback, warmup, input_columns | Depends on swing_pivots k=3 confirmation delay; lookback >= 2*K+1=7 (k bars left + k right for pivot, plus current); warmup ~7; high+low+close |
| `choch_v3` | `indicators.structure.choch_v3` | `indicators/structure/choch_v3.py` | yes | 7 | lookback, warmup, input_columns | Same swing_pivots k=3 dependency + structure tracking; lookback >= 7; warmup ~7; high+low+close |
| `dmi_wilder` | `indicators.structure.dmi_wilder` | `indicators/structure/dmi_wilder.py` | yes | 0 | lookback, warmup, input_columns | `period` default=14; Wilder RMA `ewm(alpha=1/period, min_periods=period)`; high+low+close |
| `fair_value_gap` | `indicators.structure.fair_value_gap` | `indicators/structure/fair_value_gap.py` | yes | 0 | lookback, warmup, input_columns | 3-bar window (line 98: `for i in range(2, n):`); lookback=3, warmup=3; high+low+close |
| `prev_session_extremes` | `indicators.structure.prev_session_extremes` | `indicators/structure/prev_session_extremes.py` | yes | 1 (test) | lookback, warmup, input_columns | Stateful per-session reduce; requires session_clock output frame; one full session warmup. Lookback~1, warmup~1 (per-bar state, no rolling window); open+close (+ high+low when `expand_during_dead_zone`) |
| `session_clock` | `indicators.structure.session_clock` | `indicators/structure/session_clock.py` | yes | 0 | lookback, warmup, input_columns | Stateless per-bar; needs DatetimeIndex; lookback=1, warmup=1; high+low |
| `session_clock_universal` | `indicators.structure.session_clock_universal` | `indicators/structure/session_clock_universal.py` | yes | 0 | lookback, warmup, input_columns | Same shape as session_clock; lookback=1, warmup=1; high+low |
| `swing_pivots` | `indicators.structure.swing_pivots` | `indicators/structure/swing_pivots.py` | yes | 4 | lookback, warmup, input_columns | Fixed `_K = 3` (line 32); needs k left + k right; lookback = 2*K+1 = 7; warmup = 7 (first valid pivot at index K=3, but the right-side window only completes at i=K, so first confirmation = bar K+K = 7); high+low |
| `ema_cross` | `indicators.trend.ema_cross` | `indicators/trend/ema_cross.py` | yes | 1 (test) | lookback, warmup, input_columns | fast=50/slow=200; explicit `warmup = slow` (line 44); lookback=slow; close only |
| `gaussian_slope` | `indicators.trend.gaussian_slope` | `indicators/trend/gaussian_slope.py` | yes | 0 | lookback, warmup, input_columns | `length=30` (default), `sigma=7.0`; explicit `warmup = length` (line 61); lookback=length; close only |
| `atr_with_dollar_floor` | `indicators.volatility.atr_with_dollar_floor` | `indicators/volatility/atr_with_dollar_floor.py` | yes | 0 | lookback, warmup, input_columns | Wraps `atr(df, window=window)`; no default for `window` in signature (required arg); lookback/warmup = window; high+low+close |
| `atr_with_pip_floor` | `indicators.volatility.atr_with_pip_floor` | `indicators/volatility/atr_with_pip_floor.py` | yes | 0 | lookback, warmup, input_columns | Same as atr_with_dollar_floor — wraps atr(window); high+low+close |
| `bar_range` | `indicators.volatility.bar_range` | `indicators/volatility/bar_range.py` | yes | 0 | lookback, warmup, input_columns | Stateless `df['high'] - df['low']`; lookback=1, warmup=1; high+low |
| `bb_squeeze` | `indicators.volatility.bb_squeeze` | `indicators/volatility/bb_squeeze.py` | yes | 0 | lookback, warmup, input_columns | Takes pre-computed `atr_pct_series` + `squeeze_window` + `threshold` (no defaults). Lookback=squeeze_window, warmup=squeeze_window; input is the ATR-pct series (not raw OHLC) — handled in input_columns by listing the dependent column conceptually (`atr_percentile`) per registry convention used for `apply_choch_state` (which lists `choch_event`) |
| `bollinger_bands` | `indicators.volatility.bollinger_bands` | `indicators/volatility/bollinger_bands.py` | yes | 0 | lookback, warmup, input_columns | `series.rolling(window)`; window has no default (required arg); lookback=window, warmup=window*2 (matches `bollinger_band_width` registry precedent on line 1164); close only |

## Active-strategy usage summary

| Tier | Indicators |
|---|---|
| Heavy use (>= 3 active strategy imports) | `choch_v2` (11), `choch_v3` (7), `swing_pivots` (4) |
| Single use (1 = test/utils only) | `macd_htf`, `consecutive_closes`, `prev_session_extremes`, `ema_cross` |
| No active strategy use (0) | the remaining 15 (`cmo`, `macd`, `rsi_extremes`, `consecutive_highs_lows`, `avg_range`, `dmi_wilder`, `fair_value_gap`, `session_clock`, `session_clock_universal`, `gaussian_slope`, `atr_with_dollar_floor`, `atr_with_pip_floor`, `bar_range`, `bb_squeeze`, `bollinger_bands`) |

Most of these stubs exist as library primitives that can be imported into a future strategy but currently have no live consumer. That is consistent with the project's stabilize-first-prune-later doctrine — none of them is being deleted in this pass.

## Inference confidence

### Direct (default-arg literal or explicit `warmup = ...` line)
| Indicator | Source |
|---|---|
| `cmo` | `def cmo(series, period=9)` and `series.rolling(period).sum()` |
| `macd` | line 59: `warmup = slow + signal` (explicit) |
| `macd_htf` | line 158: `warmup = slow + signal` (explicit) |
| `consecutive_closes` | `n=3` default; close-vs-prev-close comparison only |
| `consecutive_highs_lows` | `n=3` default; explicit `range(n+1)` window |
| `avg_range` | `window=5` default, rolling(window) |
| `dmi_wilder` | `period=14` default; `min_periods=period` in ewm |
| `ema_cross` | line 44: `warmup = slow`; defaults `fast=50, slow=200` |
| `gaussian_slope` | line 61: `warmup = length`; default `length=30` |
| `swing_pivots` | `_K = 3` literal; explicit `range(K, n-K)` validity window |
| `fair_value_gap` | explicit `for i in range(2, n)` -> needs 3 bars |
| `session_clock` / `session_clock_universal` / `bar_range` | stateless single-bar transforms; lookback=warmup=1 |

### Inferred (judgment call required)
| Indicator | Reason |
|---|---|
| `rsi_extremes` | Chain depth: `rsi(period=14)` -> rolling(`lookback=20`) -> shift(`shift=1`). The first valid output appears after `period + lookback + shift` = 35 bars. Choosing **lookback = max(period, lookback) = 20**, **warmup = period + lookback + shift = 35** — conservative side; deterministic from source. |
| `choch_v2` | Depends on `swing_pivots` (K=3) with confirmation delay -> first pivot usable at bar K+K=6. Setting **lookback = 7, warmup = 7** to match swing_pivots and add the same conservative buffer used for `compute_choch_state` (lookback=20, warmup=23 = lookback+3 in the existing entry — but that's a different algorithm). For pivot-confirmed CHOCH, warmup=7 is the structural minimum. |
| `choch_v3` | Same dependency on swing_pivots K=3 plus structure tracking that needs at least 2 pivots in each direction to fire — but that's pattern-dependent, not bar-count-dependent. Use lookback=7, warmup=7 — first event is _possible_ after warmup but not guaranteed. |
| `prev_session_extremes` | Stateful per-bar reducer that needs at least one full real session to elapse before `prev_session_high/low` is non-NaN. Hard to express in bar-count without timeframe context. Use **lookback=1, warmup=1** (per-bar state, accepting that real usability requires ~one session — but bar-count-warmup is genuinely 1). |
| `atr_with_dollar_floor` / `atr_with_pip_floor` | Both wrap `atr(df, window)` where `window` is a required (no-default) parameter. Use the parameter symbol directly: **lookback = window, warmup = window**. This matches how `atr` itself is registered (line 1088-1089). |
| `bollinger_bands` | `window` required; precedent from `bollinger_band_width` registry entry sets **warmup = window * 2** (line 1164). Use the same convention here. **lookback = window, warmup = window * 2**. |
| `bb_squeeze` | Takes pre-computed `atr_pct_series` + `squeeze_window` (no defaults). For `input_columns`, naming "atr_percentile" as the dependent column follows the precedent of `apply_choch_state` (input_columns: `choch_event`). |

### REQUIRES_MANUAL_REVIEW
**None.** All 22 indicators can be inferred deterministically from source. Most are direct extractions; a handful (`rsi_extremes`, `choch_v2/v3`, the ATR-wrappers, `bollinger_bands`, `bb_squeeze`, `prev_session_extremes`) require a small judgment call that is documented above and traceable to source-line evidence.

This is below the >3 manual-review halt threshold. Proceeding to Phase 2/3.

## Future-hypothesis flags

- `macd_htf` lookback/warmup are expressed in **HTF bars**, not base-TF bars. The current `lookback = slow` and `warmup = slow + signal` are correct for the HTF stream but the engine consumer needs to know that to scale right. This is not a blocker for the registry but is worth surfacing.
- `prev_session_extremes` doesn't have a clean bar-count warmup — its real usability is "one full real session of bars on the index." Setting warmup=1 satisfies the integrity test but understates the true cold-start cost. Flag for a future warmup-semantics refinement.
- `bb_squeeze` consumes a *derived series* (atr_percentile) rather than raw OHLC; the `input_columns` field is a misnomer for upstream-derived inputs. Existing registry handles this for `apply_choch_state` and `atr_percentile`. Keeping the precedent.
- `atr_with_dollar_floor` / `atr_with_pip_floor` take additional sizing parameters (`min_dollars`, `sl_atr_mult`, etc.) that ARE NOT bar-count parameters. Documented in `parameters:` but not in lookback/warmup. Correct.
