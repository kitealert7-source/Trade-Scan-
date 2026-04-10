# Baseline Snapshot — capital_model_v2_deterministic_selection

**Locked:** 2026-04-10
**Tag:** `capital_model_v2_deterministic_selection`

## State at Lock

| Metric | Value |
|--------|-------|
| Total portfolios (Portfolios tab) | 81 |
| Total single-asset composites | 62 |
| Capital model | `max_concurrent × 1000` |
| Capital owner | Step 7 (`portfolio_evaluator.py`) — single writer |
| Profile selector | Deterministic, pure read, no disk mutation |
| Unresolved profiles | 0 |
| Invariant violations | 0 |
| Non-deterministic detections | 0 |

## Smoke Test Results (all PASS)

1. Capital invariant: 143/143 rows valid
2. Profile validity: 0 UNRESOLVED
3. Determinism: 3 portfolios tested, identical on repeat
4. Aggregation safety: UNRESOLVED excluded from all downstream
5. Output integrity: edge_quality in Portfolios, sqn in Single-Asset, removed columns absent
6. Notes tab: glossary entries survive regeneration

## Key Invariants Enforced

- `reference_capital_usd` owned exclusively by Step 7
- `select_deployed_profile()` is pure — no file I/O, no mutation
- `load_profile_comparison()` has SHA-256 hash guard (read-only verified)
- `PORTFOLIO_PROFILE_UNRESOLVED` rows excluded from reconcile, run_summary, aggregation
- Selected profile must exist as key in `profile_comparison.json`
