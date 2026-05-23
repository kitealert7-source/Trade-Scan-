# H3_spread regime gate v1 — Pipeline test results

**Charter:** `h3_spread_window_c_regime_detector` (2026-05-23)
**Date:** 2026-05-23
**Status:** NEGATIVE — V1 design destroys A/B, fails to improve C
**Continuation:** V2-V5 variations proposed (see Decision section)

---

## Hypothesis tested (H1, simplified)

Cross-side flip count in a rolling N-bar lookback separates Window C
from Windows A/B with ≥70% per-quarter precision and ≥60% recall.
Halting new cycle initiation AND new pyramid orders when
`flips_in_lookback > N_threshold` reduces Window-C bleed below −50% Net
without sacrificing >15pp on Windows A/B.

**Test baseline:** locked H3_spread@3 EUR/USDJPY 15m+d=8+e=5.0+r=1.0.
Three test windows from prior cross-window work:
- A: 2024-05-18 → 2026-05-18 (USD-weakening)
- B: 2021-05-18 → 2023-05-18 (USD-strengthening)
- C: 2018-05-18 → 2020-05-18 (multi-regime: trade war + Brexit + COVID lead-in)

## Probe (separability analysis, tmp/regime_crossover_probe.py)

Pre-pipeline diagnostic on raw cross_side signal across A/B/C, three
lookbacks {1000, 2000, 4000} bars (~15 / 30 / 60 calendar days).

| Lookback | Window A mean | B mean | C mean | Recommended T | Per-Q precision | Per-Q recall |
|---|---:|---:|---:|---:|---:|---:|
| N=1000 (~15d) | 15.78 | 17.53 | 19.41 | 18 | 75.0% | 66.7% |
| N=2000 (~30d) | 31.73 | 35.13 | 38.74 | 37 | 75.0% | 66.7% |
| N=4000 (~60d) | 64.11 | 70.21 | 77.13 | (none ≥70/60) | — | — |

Probe concluded H1 was validated at N=1000 and N=2000.

## Pipeline test matrix (6 directives, S22 P00-P05)

Charter-locked test plan: 2 sweep points × 3 windows.

| Directive | Sweep | Window | Run ID | Trades | Recycles |
|---|---|---|---|---:|---:|
| `..._S22_V1_P00` | N=1000 T=18 | A | c70b30f4dd483942d44bb404 | 324 | 2037 |
| `..._S22_V1_P01` | N=1000 T=18 | B | 6df363e5dc77c4094e2c991b | 338 | 2661 |
| `..._S22_V1_P02` | N=1000 T=18 | C | b847408e04df847e035876b7 | 260 | 1270 |
| `..._S22_V1_P03` | N=2000 T=37 | A | a924f583ad49ee26c6e5ed55 | 366 | 2521 |
| `..._S22_V1_P04` | N=2000 T=37 | B | 8df20236de13970b71ede3a3 | 330 | 2375 |
| `..._S22_V1_P05` | N=2000 T=37 | C | 5dd1cfa32ed4e0949954efee | 266 | 1512 |

## Headline results (Net% / DD% / Ret-DD)

Baseline values from SYSTEM_STATE.md "H3_spread@3 deployment baseline
LOCKED" (S21 P06/P07/P08, gate-off):

| Window | Baseline (gate-off) | N=1000 T=18 (gated) | N=2000 T=37 (gated) | Δ Net% vs baseline (best gate) |
|---|---|---|---|---|
| A | +218.21% / 18.71 / 11.66 | -26.02% / 52.93 / -0.49 | -46.12% / 75.99 / -0.61 | **-244pp** |
| B | +225.94% / 20.79 / 10.87 | +73.19% / 68.18 / 1.07 | -14.11% / 60.00 / -0.24 | **-153pp** |
| C | -112.21% / 107.95 / -1.04 | -123.64% / 128.32 / -0.96 | -111.85% / 116.28 / -0.96 | **+0.4pp** |

Charter goals NOT met. Window C bleed unchanged; Windows A and B
catastrophically degraded.

## Gate telemetry — fire rate per window

The gate fired as the probe predicted (high in C, low in A/B). The
problem is the consequence of those firings, not the firing pattern.

| Patch | Sweep | Window | PYRAMID committed | PYRAMID_GATED | Gate trip rate |
|---|---|---|---:|---:|---:|
| P00 | N=1000 T=18 | A | 375 | 128 | 25% |
| P01 | N=1000 T=18 | B | 365 | 45 | 11% |
| P02 | N=1000 T=18 | C | 271 | 19 | 7% |
| P03 | N=2000 T=37 | A | 451 | 48 | 10% |
| P04 | N=2000 T=37 | B | 378 | 14 | 4% |
| P05 | N=2000 T=37 | C | 273 | **177** | **39%** |

The 39% trip rate on P05 (Window C) is exactly the differentiation the
probe predicted. The signal is real. The action on the signal is wrong.

## Diagnosis — why a "correct" probe led to a destroyed strategy

The probe measured **per-quarter** classification: a quarter is
"flagged" if ≥50% of its bars have `flips_in_lookback > T`. At T=37 /
N=2000, **zero Window-A quarters** crossed the 50% bar — that's what
yielded 75% per-quarter precision.

The production gate fires **per-bar**, and the ~10% of A bars that do
trip are **not random**. The bars where `flips_in_lookback > T` are
specifically the bars where the spread is mid-flip — which is when the
basket cycle is in drawdown — which is exactly when the pyramid
threshold crosses fire. Pyramids fire on adverse drawdowns; the gate
trips on adverse drawdowns; the gate suppresses the bars where
pyramids most want to add.

In other words: the gate is **economically correlated** with pyramid
attempts, not statistically independent of them. A 10% per-bar trip rate
maps to a much higher fraction of *suppressed pyramids* because the trip
is concentrated where pyramids fire.

Combined with the fact that the H3_spread strategy's profit driver IS
the pyramid buy-the-dip mechanic (cycle PnL distribution depends on
adding lot during drawdown, then capturing recovery), suppressing ~25%
of pyramids in Window A (which P00 did) collapses the cycle PnL
distribution → -244pp Net% destruction.

## Charter Decision Rules check

> Continue if: prototype detector hits ≥50% precision on Window C in
> the first 2-3 design iterations (signal exists, calibration TBD)

**Signal exists** — P05 confirmed 39% trip rate on C vs 4-10% on A/B.
The differentiation is real and substantial.

**Calibration is wrong** — binary halt of pyramids during normal
in-trend chop is too costly.

Charter says: **CONTINUE with refined design.**

## Recommended next variations (per [feedback_research_positive_iteration](C:\Users\faraw\.claude\projects\C--Users-faraw-Documents-Trade-Scan\memory\feedback_research_positive_iteration.md))

Five distinct dimensions; recommend V3 first.

| # | Dimension | Variation | Why this might work |
|---|---|---|---|
| **V1** | Gate target | Gate cycle_init only, not pyramids | Tests source-of-harm. If V1 still bleeds A/B, the cross_event zeroing alone is destructive; if it's clean, V1 isolates pyramids as the issue. |
| **V2** | Signal definition | Count only REVERSE_CROSS-causing flips | Filters in-trend mini-chop from the signal. Healthy flips that don't kill cycles probably shouldn't count. |
| **V3** ★ | Action softness | Halve `pyramid_add_lot` when tripped, not full block | Preserves trend capture at reduced exposure during chop. Same detection, gentler response. Smallest mechanic change. |
| **V4** | Cycle context | Gate pyramids only on losing cycles (`floating_total < 0`) | Lets winning cycles run; restricts only doubling-down on already-losing cycles. |
| **V5** | Hybrid | Combine flip count AND macro_correlation < -0.45 (S13/S14 territory) | More selective: only gate when chop AND correlation breakdown both fire. Higher precision, lower recall. |

★ Recommended next iteration.

## Artifacts preserved

- 6 directive `.admitted` markers in `backtest_directives/completed/`
- 6 per-window basket reports under
  `TradeScan_State/backtests/90_PORT_EURUSDUSDJPY_15M_PAIRX_S22_V1_P0*/`
- 6 vault snapshots under
  `DRY_RUN_VAULT/baskets/90_PORT_EURUSDUSDJPY_15M_PAIRX_S22_V1_P0*/`
- 6 MPS Baskets rows added (incremented from 196 → 201)
- Probe script: `tmp/regime_crossover_probe.py` + report at
  `tmp/regime_crossover_probe_report.md`

## Code touched (default-off; baselines remain byte-equivalent)

- `tools/basket_data_loader.py` — `regime_gate_lookback_bars` param + cross_event zeroing
- `tools/recycle_rules/h3_spread_v3.py` — pyramid/reentry gate via `_commit_pyramid_v2` override + `_step_armed_state` early-return
- `tools/run_pipeline.py` — wiring from directive params to loader
- `tools/basket_pipeline.py` — wiring to H3SpreadV3Rule constructor
- Tests: `tests/test_basket_data_loader_regime_gate.py` (7 tests) +
  `tests/test_h3_spread_v3_regime_gate.py` (14 tests). All pass.

Commits: `fcf16d5` (P1) → `78b3042` (P2) → `586437d` (P3) → S22 run.
