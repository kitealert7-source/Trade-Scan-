# Robustness Engine Consolidation + Seasonality Integration Proposal

---

## Phase 1 — Robustness Engine Inventory Audit

### 1.1 Module Inventory

#### Computation Layer (`tools/utils/research/`)

| Module | Functions | Responsibility | Inputs | Outputs | Classification |
|--------|-----------|---------------|--------|---------|---------------|
| `simulators.py` | `simulate_percent_path`, `run_reverse_path_test`, `run_random_sequence_mc` | Percent-return path simulation, sequence MC | `deployable_trade_log.csv` | dict (equity, CAGR, DD, loss streak) or DataFrame | **Core robustness** |
| `robustness.py` | `tail_contribution`, `tail_removal`, `directional_removal`, `symbol_isolation`, `early_late_split` | Tail analysis, directional bias, symbol dependency, temporal split | `deployable_trade_log.csv` | dicts/lists | **Core robustness** |
| `rolling.py` | `rolling_window`, `classify_stability` | Rolling windowed returns + stability classification | `equity_curve.csv` + `deployable_trade_log.csv` | DataFrame + dict | **Core robustness** |
| `drawdown.py` | `identify_dd_clusters`, `analyze_dd_exposure`, `analyze_dd_trade_behavior` | DD cluster identification + in-cluster diagnostics | `equity_curve.csv` + `deployable_trade_log.csv` | list[dict] / dict | **Core robustness** |
| `friction.py` | `apply_friction`, `run_friction_scenarios` | Spread/slippage stress testing | `deployable_trade_log.csv` | DataFrame / list[dict] | **Core robustness** |
| `block_bootstrap.py` | `run_block_bootstrap` | Year-block bootstrap via capital_wrapper replay | `deployable_trade_log.csv` + backtest dirs + broker specs | DataFrame | **Core robustness** (heavy coupling) |

#### Orchestration Layer (`tools/`)

| Module | Functions | Responsibility | Classification |
|--------|-----------|---------------|---------------|
| `evaluate_robustness.py` | `_load_artifacts`, 12 `_section_*` fns, `main` | CLI orchestrator: loads artifacts, calls research modules, formats markdown | **Orchestrator + Formatter** (mixed) |
| `report_generator.py` | `generate_backtest_report`, `generate_strategy_portfolio_report` | Deterministic markdown from raw CSV / portfolio JSON | **Formatter only** (no robustness logic) |
| `portfolio_evaluator.py` | ~1600 lines, 10 stages | Full portfolio evaluation: equity curve, correlation, regime breakdown, stress tests, ledger | **Separate system** (not robustness) |

#### Unrelated (despite naming)

| Module | Reality |
|--------|---------|
| `verify_batch_robustness.py` | Pipeline canonical-hash test + failure isolation. **Not robustness analysis.** |
| `verify_batch_trend.py` | Trend indicator validation. **Not robustness analysis.** |

### 1.2 Dependency Map

```
evaluate_robustness.py (Orchestrator + Formatter)
├── tools.utils.research.simulators
│   ├── simulate_percent_path()     ← used by Section 3 (Sequence MC)
│   └── run_random_sequence_mc()    ← used by Section 3
├── tools.utils.research.robustness
│   ├── tail_contribution()         ← Section 2
│   ├── tail_removal()              ← Section 2
│   ├── directional_removal()       ← Section 10
│   ├── symbol_isolation()          ← Section 12
│   │   └── calls simulators.simulate_percent_path()
│   └── early_late_split()          ← Section 11
│       └── calls simulators.simulate_percent_path()
├── tools.utils.research.rolling
│   ├── rolling_window()            ← Section 4
│   └── classify_stability()        ← Section 4
├── tools.utils.research.drawdown
│   ├── identify_dd_clusters()      ← Section 5/6
│   ├── analyze_dd_exposure()       ← Section 6 (portfolio only)
│   └── analyze_dd_trade_behavior() ← Section 5
└── tools.utils.research.friction
    └── run_friction_scenarios()    ← Section 9

block_bootstrap.py (standalone, called from evaluate_robustness §14)
├── tools.capital_wrapper (HEAVY coupling)
│   ├── load_trades, build_events, PortfolioState
│   ├── ConversionLookup, load_broker_spec
│   └── _parse_fx_currencies, get_usd_per_price_unit_*
└── reads: backtests/, strategies/<prefix>/deployable/<profile>/
```

### 1.3 Identified Issues

| Issue | Location | Severity |
|-------|----------|----------|
| **Mixed concerns** | `evaluate_robustness.py` merges computation orchestration + markdown formatting in the same `_section_*` functions | Medium |
| **Duplicated timestamp parsing** | `pd.to_datetime()` on `entry_timestamp`/`exit_timestamp` happens in every module independently | Low |
| **File I/O scattered** | `_load_artifacts()` reads CSVs; `block_bootstrap` reads CSVs again independently; `symbol_isolation` and `early_late_split` internally re-simulate | Medium |
| **Heavy coupling** | `block_bootstrap.py` imports 6 functions from `capital_wrapper.py` — a 44KB module | High |
| **No shared trade DataFrame contract** | Each module assumes its own column set — no formal schema | Medium |
| **Implicit section numbering** | Section numbers are hardcoded in format strings (`## Section 8 —`) — fragile to reordering | Low |

---

## Phase 2 — Consolidation Proposal

### 2.1 Proposed Architecture

```
tools/
  robustness/
    __init__.py          # Version tag, public API exports
    schema.py            # Trade/equity DataFrame contracts, column enums
    loader.py            # Canonical artifact loader (single read, shared DF)
    
    # ── Computation modules (pure functions, no I/O, no formatting) ──
    tail.py              # tail_contribution, tail_removal
    rolling.py           # rolling_window, classify_stability
    drawdown.py          # identify_dd_clusters, analyze_dd_exposure, analyze_dd_trade_behavior
    friction.py          # apply_friction, run_friction_scenarios
    monte_carlo.py       # simulate_percent_path, run_reverse_path, run_random_sequence_mc
    bootstrap.py         # run_block_bootstrap (kept separate due to capital_wrapper coupling)
    directional.py       # directional_removal
    symbol.py            # symbol_isolation, symbol_breakdown
    temporal.py          # early_late_split
    seasonality.py       # [NEW] monthly/weekday analysis per Seasonality v2
    
    # ── Aggregation layer ──
    runner.py            # Orchestrates all computation modules, returns structured results dict
    
    # ── Formatting layer ──
    formatter.py         # Takes results dict → markdown sections
    
    # ── CLI ──
    cli.py               # Argument parsing, calls runner → formatter → writes files
```

### 2.2 Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Single canonical DataFrame** | `loader.py` reads CSVs once; passes `tr_df`, `eq_df`, `metrics` to all modules |
| **Schema enforcement** | `schema.py` defines required columns, validates on load (fail-fast) |
| **Computation ≠ Formatting** | Modules return dicts/DataFrames; `formatter.py` converts to markdown |
| **No internal file I/O** | Computation modules never call `pd.read_csv()` — they receive DataFrames |
| **Deterministic seeds** | All MC/bootstrap functions accept `seed` param (already true) |
| **Section registry** | `runner.py` defines ordered section list with gating predicates — no hardcoded section numbers |

### 2.3 Justification for This Structure Over Alternatives

**Alternative A: Monolith (single `robustness_engine.py`)**

- Rejected: 400+ lines already; adding seasonality pushes to 600+. Hard to test individual sections.

**Alternative B: Keep current `tools/utils/research/` + wrap**

- Partially viable but `utils/research/` is too deeply nested; the module names don't clearly map to report sections.

**Alternative C (chosen): `tools/robustness/` package**

- Clean namespace: `from tools.robustness import tail, rolling`
- Each file maps to 1–2 report sections
- `runner.py` + `formatter.py` separation enables testing computation without report generation
- Future sections (seasonality) are self-contained additions

---

## Phase 3 — Seasonality Integration in Consolidated Architecture

### 3.1 Module Location

```
tools/robustness/seasonality.py
```

### 3.2 Interface Contract

```python
# tools/robustness/seasonality.py

def analyze_monthly(
    tr_df: pd.DataFrame,
    timeframe: str,        # from strategy identity
    horizon_years: float,  # computed by runner
) -> dict:
    """
    Returns:
      {
        "mode": "FULL" | "MEDIUM" | "SHORT",
        "suppressed": bool,
        "suppression_reason": str | None,
        "test_statistic": float,    # Kruskal-Wallis H
        "p_value": float,
        "effect_size": float,       # η²
        "verdict": str,
        "buckets": [{"month": int, "trades": int, "pnl": float, "pf": float, 
                      "flag": bool, "stable": bool | None}],
        "exposure_decisions": [{"month": int, "action": str, "pf": float}] | None
      }
    """

def analyze_weekday(tr_df, timeframe, horizon_years) -> dict:
    """Same structure, 5 buckets instead of 12."""
```

### 3.3 How It Integrates

| Concern | Integration Point |
|---------|------------------|
| **Trade DataFrame** | Receives canonical `tr_df` from `runner.py` — no file reads |
| **Gating** | `runner.py` checks `len(tr_df)` thresholds and `timeframe` before calling |
| **Horizon detection** | `runner.py` computes `horizon_years` from `tr_df` timestamps, passes to seasonality |
| **Stability split** | Seasonality module handles its own half-split internally (no external dependency) |
| **Formatting** | Returns dict → `formatter.py` renders markdown with mode badge, verdict, optional table |
| **Result object** | Identical structure to all other sections — dict consumed by `formatter.py` |

### 3.4 No Cross-Dependencies

| System | Dependency? |
|--------|------------|
| Strategy engine | ❌ None — reads trade log only |
| Execution engine | ❌ None |
| Capital wrapper | ❌ None (only `bootstrap.py` depends on it, existing) |
| Portfolio evaluator | ❌ None |

---

## Phase 4 — Regression Test Harness

### 4.1 Approach: Frozen Baseline + Hash Comparison

**Step 1: Freeze baseline outputs**

For a reference strategy (e.g., `AK36_FX_PORTABILITY_4H / CONSERVATIVE_V1`), run the current `evaluate_robustness.py` and capture every computation module's raw output as JSON:

```
tools/tests/baselines/
  AK36_CONSERVATIVE_V1/
    tail.json
    sequence_mc.json      # seed=42, 500 iterations
    rolling.json
    drawdown.json
    friction.json
    directional.json
    symbol_isolation.json
    early_late.json
    block_bootstrap.json  # seed=42, 100 iterations
```

**Step 2: Regression runner**

```
tools/tests/test_robustness_regression.py
```

Calls each new `tools/robustness/` module with the same inputs, compares outputs against frozen baselines using:

- Exact match for integer fields (trade counts, streak lengths)
- Tolerance match for float fields (|Δ| < 1e-6 for PnL, < 1e-4 for percentages)
- Hash match for structural keys (dict keys, array lengths)

**Step 3: Deterministic seed control**

All MC/bootstrap functions already accept `seed` parameter. The regression runner enforces `seed=42` for all stochastic tests.

### 4.2 Specific Regression Checks

| Section | What Must Match |
|---------|----------------|
| Tail contribution | `top_1`, `top_5`, `top_1pct`, `top_5pct` ratios |
| Sequence MC | Median CAGR, 5th/95th percentiles (seed=42, 500 runs) |
| Rolling windows | Window count, negative window count, worst return |
| Drawdown clusters | Top-3 cluster start dates, DD percentages |
| Friction scenarios | 4 scenario net PnLs and PFs |
| Directional removal | Baseline PF, no-long20 PF, no-short20 PF |
| Symbol isolation | Per-symbol CAGR after removal |
| Early/Late | Both-half CAGR, win rate |
| Block bootstrap | Median equity, 5th pctl CAGR (seed=42, 100 runs) |

### 4.3 Execution

```bash
# Before consolidation: capture baselines
python tools/tests/freeze_baselines.py AK36_FX_PORTABILITY_4H --profile CONSERVATIVE_V1

# After each migration step
python tools/tests/test_robustness_regression.py
```

---

## Phase 5 — Governance

### 5.1 Versioning

| Component | Current | After Consolidation |
|-----------|---------|-------------------|
| Robustness report | Unversioned | **Robustness v2.0** |
| After seasonality | — | **Robustness v2.1** |

Version tag stored in `tools/robustness/__init__.py`:

```python
__version__ = "2.0.0"  # bumped to 2.1.0 when seasonality added
```

Report header includes version:

```markdown
# ROBUSTNESS REPORT — AK36_FX_PORTABILITY_4H / CONSERVATIVE_V1
Engine: Robustness v2.0 | Generated: 2026-02-26 12:00:00
```

### 5.2 Legacy Module Disposition

| Current Module | Action | Timeline |
|----------------|--------|----------|
| `tools/utils/research/simulators.py` | **Wrap** — `tools/robustness/monte_carlo.py` imports and re-exports. Delete original after regression passes | Migration step 4 |
| `tools/utils/research/robustness.py` | **Split + Wrap** — functions migrate to `tail.py`, `directional.py`, `symbol.py`, `temporal.py` | Migration step 4 |
| `tools/utils/research/rolling.py` | **Wrap** — move to `tools/robustness/rolling.py` | Migration step 4 |
| `tools/utils/research/drawdown.py` | **Wrap** — move to `tools/robustness/drawdown.py` | Migration step 4 |
| `tools/utils/research/friction.py` | **Wrap** — move to `tools/robustness/friction.py` | Migration step 4 |
| `tools/utils/research/block_bootstrap.py` | **Wrap** — move to `tools/robustness/bootstrap.py` | Migration step 4 |
| `tools/evaluate_robustness.py` | **Replace** with `tools/robustness/cli.py` — old file becomes shim that calls new CLI | Migration step 5 |
| `tools/utils/research/__init__.py` | **Deprecate** — add `DeprecationWarning` pointing to `tools.robustness` | Migration step 6 |

### 5.3 Backward Compatibility

`tools/evaluate_robustness.py` will be preserved as a **thin shim** that imports from `tools.robustness.cli` and calls `main()`. Any existing workflow references continue to work. The shim includes a deprecation notice in output:

```
[DEPRECATION] evaluate_robustness.py will be removed in v3.0. Use tools/robustness/cli.py directly.
```

---

## Phase 6 — Proposed Execution Order

| Step | Action | Validation |
|------|--------|-----------|
| **1. Audit** | ✅ This document | Review and approve |
| **2. Freeze baseline** | Run `freeze_baselines.py` on AK36 CONSERVATIVE_V1 | Capture JSON baselines |
| **3. Create package skeleton** | Create `tools/robustness/` with `__init__.py`, `schema.py`, `loader.py` | Structure only, no logic |
| **4. Migrate computation modules** | Copy functions from `tools/utils/research/` → `tools/robustness/` split by domain | Run regression: all checks pass |
| **5. Build runner + formatter** | Create `runner.py` (orchestration) and `formatter.py` (markdown) | Regression: report output byte-identical |
| **6. Create CLI shim** | `tools/robustness/cli.py` replaces `evaluate_robustness.py` logic | Run on all existing strategies: diff reports |
| **7. Deprecate legacy** | Add deprecation warnings to `tools/utils/research/`, shim old CLI | Idempotence: old CLI → same output via shim |
| **8. Add seasonality** | Implement `tools/robustness/seasonality.py` per Seasonality v2 | New section appears; existing sections unchanged |
| **9. Bump version** | `__version__ = "2.1.0"` | Version tag in report header |
| **10. Final validation** | Run full regression + seasonality tests on all strategies | All gates pass |

> [!IMPORTANT]
> Steps 4–6 must each pass regression before proceeding. If any step breaks parity, halt and fix before continuing. This is strictly mechanical — no logic changes.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **Logic drift during migration** | Low | High | Regression harness with frozen baselines |
| **Float precision differences** | Low | Low | Tolerance-based comparison (1e-6 PnL, 1e-4 %) |
| **block_bootstrap coupling** | Medium | Medium | Keep as-is initially; refactor capital_wrapper dependency only in v3 |
| **External script references** | Low | Medium | Shim preserves old CLI path |
| **Merge conflicts with active work** | Medium | Medium | Execute consolidation as an isolated branch |

---

## Recommendation

**PARTIAL CONSOLIDATION**

Full consolidation (Phase 2 architecture) is structurally sound but carries execution risk if done as a single large migration. The recommended approach:

1. **Do now:** Create `tools/robustness/` package, freeze baselines, migrate computation modules with regression checks (Steps 1–4)
2. **Do next:** Build runner + formatter + CLI shim (Steps 5–7) — this is the highest-risk step but mechanically straightforward
3. **Do after:** Add seasonality (Steps 8–9) — cleanly additive, no existing logic changes
4. **Defer:** Refactoring `block_bootstrap.py`'s coupling to `capital_wrapper` — this is a v3.0 concern, not worth the risk now

This sequence ensures no logic drift, preserves backward compatibility, and gates seasonality integration on a stable consolidated foundation.
