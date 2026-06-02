# COINTREV N=3 decomposition - bucket attribution on triggered classes

**Date:** 2026-06-02 | **Scope (operator gate):** IDX-IDX + CRYPTO/METAL only

## Bucket definitions

- **A** -- shared-span trades with entry_time >= `start_date + 2 bdays` (== what N=5 would have generated)
- **B** -- shared-span trades with entry_time < `start_date + 2 bdays` (the newly-unlocked early-period trades; the operator question)
- **C** -- trades on N=3-only short spans (ncoint in {5,6}; do not exist at N=5)

Per-leg row aggregation. `pnl_usd` at fixed $1000 target notional per leg (no capital model -- direct comparison is meaningful WITHIN a directive and across directives in the same class).

## Directive counts

| Class | dirs | of which N=3-only short-span (bucket C) |
|---|---:|---:|
| IDX-IDX | 69 | 10 |
| CRYPTO/METAL | 95 | 21 |

## Per-bucket per-leg metrics

| Class | Bucket | n_legs | win% | mean pnl_usd | median pnl_usd | total pnl_usd |
|---|---|---:|---:|---:|---:|---:|
| IDX-IDX | A | 3397 | 53.3 | +0.03 | +0.40 | +97 |
| IDX-IDX | B | 433 | 54.3 | +1.17 | +0.39 | +507 |
| IDX-IDX | C | 8 | 62.5 | +1.62 | +3.57 | +13 |
| CRYPTO/METAL | A | 4878 | 54.8 | -4611.99 | +0.58 | -22497282 |
| CRYPTO/METAL | B | 702 | 54.3 | -3152.77 | +0.50 | -2213243 |
| CRYPTO/METAL | C | 38 | 65.8 | -63097.83 | +1.46 | -2397717 |

## Direct attribution: does the newly-unlocked early-period bucket B make money?

| Class | B win% | A win% | win% delta | B mean pnl_usd | A mean pnl_usd | mean delta | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| IDX-IDX | 54.3 | 53.3 | +1.0pp | +1.17 | +0.03 | +1.14 | **B accretive (early entries make money)** |
| CRYPTO/METAL | 54.3 | 54.8 | -0.5pp | -3152.77 | -4611.99 | +1459.22 | **mixed signals** |

## Read

**The operator question (do the newly-unlocked early-period trades make money?) is answered by the B vs A comparison above.**

Bucket C is a separate informational comparison -- N=3-only short spans are a different *kind* of relaxation (span-length, not entry-day) and answer a different sub-question. Listed for completeness.

**Trade-level scan:** read 162 per-directive results_tradelevel.csv files; bucket assignment by `entry_time` vs `start_date + 2 bdays` (Mon-Fri business days).