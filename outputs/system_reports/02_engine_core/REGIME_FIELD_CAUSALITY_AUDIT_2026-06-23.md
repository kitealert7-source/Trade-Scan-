# Regime-Field Causality Audit — `market_regime` & `trend_label` are point-in-time, engine-owned, entry-safe

- **Status:** REPORT-ONLY verification audit. No code change, no engine modification. Source-grounded read of frozen engine + indicators.
- **Date:** 2026-06-23
- **Engine:** v1.5.10 (canonical, FROZEN). Trade records audited from charged v1.5.10 runs.
- **Trigger:** The gold DMA mean-reversion-fade decomposition (idea 72, runs `48d2b946` S01 / `f184e866` S02) surfaced a clean leak — `LONG × market_regime=unstable_trend = -$731 / 254 trades`, while `trend_label=neutral = -$797`. Before that decomposition could justify a P01 entry filter, the discriminating fields had to be proven **causal / observable at entry**, not future- or post-trade-derived. A contaminated label would make the entire decomposition a postmortem, not a tradable signal.

---

## 1. Question

Two parts, both load-bearing:

1. **HOW** are `market_regime` and `trend_label` computed — from what inputs, and do any of those inputs use future data (negative shift, centred window, whole-series quantile, a smoother, or forward returns)?
2. **WHEN** are they stamped onto a trade — at the signal bar (safe), the fill bar (safe), or post-trade / from a bar after the fill (contaminated)?

Plus: are they **engine-owned** (computed on price independently of any strategy), or derived from the strategy's own trade outcomes?

## 2. Verdict

**PASS — causal, point-in-time, engine-owned. Safe to gate entries on.** Use the **`_signal`** variant (`market_regime_signal`), never `_fill`. The `LONG × unstable_trend` decomposition is a tradable, entry-observable relationship — not a hindsight description.

This clears the **look-ahead** gate only. It does **not** clear **durability** — see §9.

## 3. HOW `market_regime` is built — `engines/regime_state_machine.py`

A **3-axis state model**, not a single statistic and nothing trade-derived:

| Axis | Inputs (all price-only) | Code |
|---|---|---|
| Direction (−1..1) | linreg slope(50), linreg-HTF(200, daily resample), Kalman filter slope, SHA, EMA(20) | `compute_axis_states:92-93` |
| Structure (0..1) | Kaufman efficiency ratio, trend-persistence, Hurst(200), ADX, log-return autocorr | `:96-104` |
| Volatility (0..1) | ATR-percentile(100), realized-vol-percentile(200), vol-regime | `:106-112` |

The 3 axes map to 6 regimes through **hard-coded constant thresholds** (`resolve_market_regime:117-142`): `abs(direction) > 0.4`, `structure > 0.6`, `volatility > 0.6 / 0.4`. `unstable_trend` = directional conviction (`abs_dir>0.4`) **without** structural confirmation (`structure <= 0.6`). **No data-derived quantiles → no whole-series fitting at the resolution step.**

A **forward bar-by-bar state machine** (`:251-296`) then walks the series and commits a regime change only after **3 consecutive confirming bars** (`regime_confirm_bars=3`). That is a *lag* — the structural opposite of anticipation. Each bar's value depends only on bars `<= i`.

## 4. HOW `trend_label` is built — same file, `:352-375`

Deterministic: a 5-indicator **vote sum** (`regime_lr + regime_lr_htf + regime_kalman + regime_tp + regime_er`, each −1/0/+1) thresholded by **fixed cutoffs** (`>=3 strong_up … 0 neutral … <=-2 strong_down`). `neutral` = the votes cancel. No tuning, no future data.

## 5. Are the inputs causal? Every one verified — yes

| Indicator | File | Mechanism | Causal |
|---|---|---|---|
| `atr_percentile`, `volatility_regime`, `realized_vol` | `indicators/volatility/*` | `rolling(W).apply(sum(x<=x[-1])/len)` — current bar's rank in a **trailing** window | ✓ |
| `kalman_regime` | `indicators/trend/kalman_regime.py:52-62` | forward **filter** (`for i in 1..n`, prior state + current obs only) — **not** an RTS smoother | ✓ |
| `linreg_regime` | `indicators/trend/linreg_regime.py:28-38` | trailing `rolling(50)` slope | ✓ |
| `linreg_regime_htf` | `indicators/trend/linreg_regime_htf.py:75-77` | daily resample, rolling slope, explicit `.shift(1)` ("Prevent Lookahead") → intraday sees only the prior completed day | ✓ |
| `hurst_regime` | `indicators/trend/hurst_regime.py:63-66` | `rolling(200).apply(R/S)` on **past** 200 bars — not whole-series | ✓ |
| `trend_persistence` | `indicators/trend/trend_persistence.py:22-30` | trailing `rolling(20)` of `sign(diff)` | ✓ |
| `efficiency_ratio_regime` | `indicators/trend/efficiency_ratio_regime.py:20-27` | trailing `rolling(20)` over `diff` / `shift(window)` | ✓ |

Every input is trailing-window. **No `.shift(-n)`, no `center=True`, no full-series quantile/rank used as a threshold, no smoother, no forward-return term.** Direct answers to the two red flags: rolling *future* returns — **no**; entire-trade statistics — **no** (the regime is computed on the price series in `apply_regime_model` *before* any trade is simulated).

## 6. WHEN are they stamped? At the **signal bar**, frozen at entry

`engine_dev/universal_research_engine/v1_5_10/evaluate_bar.py` captures regime into `entry_market_state` the moment the entry fires and freezes it:

- `:530` `'market_regime_signal': _signal_market_regime` — the **signal-bar** snapshot
- `:704` the emitted trade reads `market_regime_signal` from `state.entry_market_state.get(...)` — the value frozen at entry
- `:527 / :690 / :775` `trend_label` likewise pulled from the entry-bar context and frozen

The engine maintains an explicit **signal/fill split**:

- `market_regime_signal` = regime at bar N (the decision bar) → **the field the decomposition used**
- `market_regime_fill` = `row.get('market_regime')` at bar N+1 (`:390`) — the fill-bar view, **not** used
- `regime_age_fill = regime_age.shift(-1)` carries an explicit comment (`regime_state_machine.py:315-318`): *"never consulted inside check_entry() … unless the strategy explicitly opts in"*

The engine itself draws exactly the contamination line we were worried about, and the audited field sits on the safe side of it. (Mirrored in `execution_loop.py:430/496/664/734`.)

## 7. Engine-owned

`apply_regime_model()` (`regime_state_machine.py:145-398`) is the **universal regime layer** — computed once per dataset, cached per-symbol (parquet, keyed on `symbol|last_ts|len|freq`), bar-by-bar, identically for every strategy, from price alone. It predates and is independent of any single strategy; trade P&L never feeds back into it.

## 8. The one nuance — whole-series compute is still causal

`apply_regime_model` runs over the whole series in a single vectorized pass (then caches). This does **not** leak: as shown in §5, every per-bar value depends only on bars `<= i` (trailing windows + a forward, *lagging* state machine). Full-series *computation* with strictly-causal *operations* is the correct vectorized pattern; research and live produce the identical label at bar N. The only forward-touching field is `regime_age_fill` (`shift(-1)`), which is explicitly fenced off from `check_entry()`.

## 9. Implications

1. **Legitimate as an entry filter.** A regime-gated entry — e.g. "no LONG when `market_regime_signal == unstable_trend`" — is a real hypothesis, not hindsight. The DMA decomposition stands.
2. **Always gate on `_signal`, never `_fill`** / any forward-shifted variant.
3. **Audit a field family once, reuse the verdict.** This closes look-ahead for the regime/trend field family — future regime-gate ideas need not re-audit the classifier + 8 indicators + emitter.
4. **Causality cleared ≠ durability cleared.** Passing this gate makes the filter *legitimate*, not *good*. The DMA turn-around was 77–88% concentrated in 2024–2026 with 2017–2022 net-negative under every filter — a separate gate only a pipeline run settles (Invariant #31). This audit is upstream of that, not a substitute for it.
5. **Transferable principle** (for the vault Library layer): *a decomposition-derived filter is tradable only if its discriminating field is causal (trailing-window inputs) and stamped at the signal bar — the HOW + WHEN look-ahead gate.*

## Appendix — file:line index

- `engines/regime_state_machine.py` — `resolve_market_regime:117-142` (fixed thresholds), forward state machine `:251-296`, `trend_label` `:352-375`, `regime_age_fill` lookahead note `:315-320`, alignment invariant `:327-339`, `apply_regime_model:145-398`.
- `indicators/trend/`: `kalman_regime.py:52-62`, `linreg_regime.py:28-38`, `linreg_regime_htf.py:75-77`, `hurst_regime.py:63-66`, `trend_persistence.py:22-30`, `efficiency_ratio_regime.py:20-27`.
- `indicators/volatility/`: `atr_percentile.py:37-40`, `volatility_regime.py:34-37`, `realized_vol.py:34-42`.
- `engine_dev/universal_research_engine/v1_5_10/evaluate_bar.py:527,530,690,704-705,775,789-790`; `execution_loop.py:430-431,496,664-665,734-735`; `execution_emitter_stage1.py:475,481,542-543`.
- Trade records: `TradeScan_State/backtests/72_MR_XAUUSD_5M_DMA_S0{1,2}_*/raw/results_tradelevel.csv`.
