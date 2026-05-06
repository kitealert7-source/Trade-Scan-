# SYSTEM STATE

## SESSION STATUS: OK

> Generated: 2026-05-06T13:51:23Z
>
> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).

## Engine
- **Version:** 1.5.8 | **Status:** FROZEN | **Manifest:** VALID

## Pipeline Queue
- Queue empty. No directives in INBOX or active.
- Completed: 221 directives

## Ledgers

- **Master Filter:** 1061 rows

- **Master Portfolio Sheet:** `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx`
  - **Portfolios:** 120 rows — CORE: 4, FAIL: 112, PROFILE_UNRESOLVED: 1, WATCH: 3
  - **Single-Asset Composites:** 80 rows — CORE: 11, FAIL: 63, PROFILE_UNRESOLVED: 1, WATCH: 5

- **Candidates (FPS):** 472 rows — BURN_IN: 13, CORE: 14, FAIL: 307, RBIN: 2, RESERVE: 25, WATCH: 111

## Portfolio (TS_Execution)
- **Total entries:** 9 | **Enabled:** 9
- BURN_IN: 9 | WAITING: 0 | LIVE: 0 | LEGACY: 0

## Burn-In Status
- **Process:** RUNNING | run_id=20260505T032727Z_55340 | bars=1036
- **Shadow trades:** 2 active | **Signals (7d):** 54 entry, 20 exit
- **Alerts:** silence_alerts=OFF | watchdog=ACTIVE

## Vault (DRY_RUN_VAULT)
- Snapshots: 17 | WAITING: 0 | Latest: `DRY_RUN_2026_04_30__c0abdf0e`

## Data Freshness
- Latest bar: **2026-05-06** | Symbols: 243

## Artifacts
- Run directories: 1278

## Git Sync
- Remote: IN SYNC
- Working tree: clean
- Last commit: `3a4499f session: refresh tools_manifest.json post idea-gate refresh`

## Known Issues
### Auto-detected (regenerated each run)
- **Burn-in ABORT:** `22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P06` — DD 28.48% >= abort threshold 12.0%

### Manual (deferred TDs, operational context)
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->

#### PSBRK V4 5M family — pending work (carried 2026-05-06)

**Ready for action:**
- **Promote P14 as the new V4 5M deployable winner** (replacing P09).
  P14 = P11 + armed-once-per-session-per-direction guard. Beats P09 on
  every primary risk-adjusted metric: PF 1.34 vs 1.24, Sharpe 1.39 vs
  1.01 (+38%), Expectancy $2.73 vs $1.77 (+54%), Max DD slightly
  better. Backtest report:
  `TradeScan_State/backtests/65_BRK_XAUUSD_5M_PSBRK_S01_V4_P14_XAUUSD/`.

**Experiment queue (all build on P14 baseline):**
- **P16 = P14 + pyramid add at MAE -0.50R.** Probe-positive design
  from path-geometry analysis. Single add at -0.50R gives +0.16 R
  per R0 risk (vs base +0.136), max per-trade loss capped at 1.50× R0.
  Avoid stacked ladder (no efficiency gain, 2.6× max loss).
- **P17 = P14 + bar-12 / 6-bar / 0.15R stall trail to BE.** Now safe
  to test — the armed-once guard in P14 prevents the reentry storm
  that invalidated P13 (P13 went 1221 → 2250 trades on P11 base).
- **P18 = P14 + tighter initial stop.** Recovery Boundary subsection
  shows recovery rate stays 64-94% across all 0-0.90R MAE bands —
  there's no graceful collapse curve before the structural stop. The
  ~1R structural session-extreme stop IS the boundary; tightening
  stop distance is a separate axis worth probing.

**Documented runner-up:**
- P15 (= P09 + armed-once, no TP) was tested but P14 wins head-to-head.
  P15 retained as a clean-baseline reference for future no-TP variant
  experiments. 901 trades, PF 1.30, Sharpe 1.25.

#### Family-wide infrastructure debt

- **`_is_patch_sibling` does not handle cross-TF families.** The
  PSBRK V4 sweep is a 15M parent (P00) with 5M children (P01-P15)
  by intentional design, but `tools/sweep_registry_gate.py::_is_patch_sibling`
  strips only the `_PNN` suffix, not the TF segment. Any new
  same-family child registration (P16+) will fail at Stage -0.35
  SWEEP GATE and require manual `sweep_registry.yaml` insert (precedent:
  commits `807e217`, `ebf2da4`, `0b1c0f0`). Proper fix is a small
  refactor to make `_is_patch_sibling` TF-aware while preserving
  the timeframe-in-hash discrimination that prevents cross-family
  collisions.

#### Operational context for the auto-detected ABORT

- **22_CONT_FX_30M_RSIAVG_TRENDFILT_S02_V1_P06 ABORT** (auto-detected
  above) is a known measurement artifact verdicted **KEEP_ABORT** in
  prior session. Real cause: bulk-export sequencing + nominal $10K
  notional denominator + AUDJPY whipsaw. Do not investigate further
  unless live execution shows fresh degradation.

