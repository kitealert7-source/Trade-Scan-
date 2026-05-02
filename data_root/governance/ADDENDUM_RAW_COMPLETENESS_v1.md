# ADDENDUM: RAW Completeness Invariant (Phase 1.5)

**Status**: ENFORCED
**Date**: 2026-04-30
**Scope**: DATA_INGRESS daily pipeline
**Reference**: `DATA_INGRESS/config/path_config.py` — `EXPECTED_COVERAGE`, `COVERAGE_MAX_DAYS_BEHIND`

---

## Problem This Closes

On 2026-04-28, `mt5.copy_rates_from()` silently returned `None` for 28 (symbol, tf) combos
at 1m/5m (cross pairs and indices that were not subscribed in Market Watch). Phase 1 (RAW
update) reported `[PASS]` — it did not crash — but no RAW data was written for the affected
tuples. The gap was detected only ~24 h later via a manual freshness scan.

Root cause: "Phase 1 didn't crash" is not equivalent to "every expected dataset is fresh."
There was no automated check that promoted one to the other.

---

## The Invariant

After Phase 1 completes, **every (sym_broker, tf) tuple in `EXPECTED_COVERAGE`** must have:

1. A 2026 RAW CSV at the canonical path `{sym_broker}_MASTER/RAW/{sym_broker}_{tf}_2026_RAW.csv`
2. A last valid timestamp within `COVERAGE_MAX_DAYS_BEHIND[tf]` days of today UTC

If either condition fails for any tuple, Phase 1.5 exits 1 and the pipeline halts before
Phase 2 (structural validation). Governance is not updated.

---

## Coverage Inventory

234 tuples total. Sanity assertion in `path_config.py` enforces this count at import time.

| Asset class | Symbols | Timeframes | Count |
|-------------|---------|------------|-------|
| FX majors + crosses + Index CFDs (OctaFX) | 28 | 1m 5m 15m 30m 1h 4h 1d | 196 |
| Crypto + Gold (OctaFX: BTCUSD, ETHUSD, XAUUSD) | 3 | 1m 3m 5m 15m 30m 1h 4h 1d | 24 |
| Crypto (Delta Exchange: BTC_DELTA, ETH_DELTA) | 2 | 1m 3m 5m 15m 1h 4h 1d | 14 |
| **Total** | | | **234** |

**Intentional exclusions:**
- `BTC_OCTAFX_MASTER` — Windows directory junction aliased to `BTCUSD_OCTAFX_MASTER` (verified
  2026-04-28; both paths resolve to the same inode). Produces no distinct data; no coverage
  obligation. The freshness_index double-counts it cosmetically — separate issue.
- `US10Y_YAHOO_MASTER` — Yahoo Finance has native multi-day publishing latency that does not fit
  the same threshold semantics as broker feeds. Excluded until migrated to a real-time source.

---

## Staleness Thresholds

| Timeframe | Max days behind |
|-----------|----------------|
| 1m | 5 |
| 3m | 5 |
| 5m | 5 |
| 15m | 5 |
| 30m | 5 |
| 1h | 5 |
| 4h | 7 |
| 1d | 7 |

Buffer absorbs long weekends and occasional broker holidays. Tight enough that a missed
weekday still trips the check.

---

## Enforcement

**Script**: `DATA_INGRESS/engines/ops/assert_raw_coverage.py`
**Pipeline role**: Phase 1.5 — runs after Phase 1, before Phase 2
**Exit codes**: 0 = PASS, 1 = FAIL (at least one violation)
**State file**: `DATA_INGRESS/state/last_coverage_assertion.json` (full structured report)

Temporary exceptions can be registered in `COVERAGE_EXCEPTIONS` in `path_config.py`.
Format: `{(sym_broker, tf): "reason — owner — review_date"}`.
The dict is empty by default — the contract is the whole inventory.

---

## Adding or Removing a Symbol / Timeframe

1. Update `EXPECTED_COVERAGE` in `config/path_config.py` (add/remove from the relevant set)
2. Update the sanity assert count: `assert len(EXPECTED_COVERAGE) == N`
3. If adding a new `*_MASTER` directory, add it to `CANONICAL_MASTER_DIRS` in the same file
4. Run `python engines/ops/assert_raw_coverage.py` to confirm the new tuple is satisfied
5. Commit `path_config.py` — the inventory is review-gated by design

---

## Related Documents

- `ANTI_GRAVITY_SOP_v17.md` — master SOP
- `DATA_INGRESS/DAILY_EXECUTION_CONTRACT.md` §1 Failure Semantics — Phase 1.5 gate
- `DATA_INGRESS/CLAUDE.md` — pipeline phase table
