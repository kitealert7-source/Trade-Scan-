# N=3 entry-day-since-onset shape (preview for N=0 design)

**Date:** 2026-06-02 | **Source:** existing N=3 corpus, read-only

Decomposition of per-leg trades by entry-day-since-onset, from day 4 (the N=3 floor) onwards. 
Day 1-3 entries do NOT exist in this corpus -- only an N=0 run would produce them. Shape from day 4 onward
is the strongest available evidence for whether the N=0 run is worth committing.

## Shape per pair-class

| Class | day 4 | day 5 | day 6 | day 7-9 | day 10-14 | day 15-30 | day 31+ |
|---|---|---|---|---|---|---|---|
| **FX-FX win%** | 52.5% (n=711) | 52.8% (n=576) | 49.7% (n=515) | 56.5% (n=1368) | 55.0% (n=1646) | 56.6% (n=2692) | 56.1% (n=2065) |
| FX-FX mean pnl | -0.09 | -0.06 | -0.13 | +0.20 | +0.05 | +0.18 | +0.13 |
| FX-FX median pnl | +0.14 | +0.10 | -0.04 | +0.31 | +0.24 | +0.26 | +0.25 |
| **IDX-IDX win%** | 51.7% (n=261) | 58.3% (n=180) | 47.2% (n=161) | 57.1% (n=459) | 54.7% (n=537) | 52.8% (n=1091) | 52.5% (n=1149) |
| IDX-IDX mean pnl | +0.84 | +1.67 | -1.42 | +0.27 | +0.15 | +0.08 | +0.04 |
| IDX-IDX median pnl | +0.23 | +0.70 | -0.21 | +0.70 | +0.58 | +0.39 | +0.29 |
| **FX-IDX win%** | 51.7% (n=1045) | 54.7% (n=781) | 53.0% (n=757) | 54.5% (n=1737) | 55.4% (n=2343) | 55.7% (n=4915) | 53.5% (n=4767) |
| FX-IDX mean pnl | +0.17 | -0.22 | -0.01 | +0.63 | +0.26 | +0.08 | -0.11 |
| FX-IDX median pnl | +0.10 | +0.38 | +0.24 | +0.26 | +0.34 | +0.44 | +0.27 |
| **CRYPTO/METAL win%** | 56.4% (n=413) | 52.9% (n=327) | 57.9% (n=321) | 56.2% (n=758) | 55.6% (n=939) | 53.9% (n=1517) | 53.6% (n=1343) |
| CRYPTO/METAL mean pnl | -6112.38 | -6380.88 | -7238.36 | -7628.67 | -4578.88 | -5820.64 | -939.51 |
| CRYPTO/METAL median pnl | +0.70 | +0.30 | +1.05 | +0.62 | +0.58 | +0.51 | +0.52 |

## Read

- **Day 4** is the N=3 entry boundary (= onset + 4 bdays); **day 6** is the N=5 entry boundary.
- **The shape on day 4 vs day 6+ is the same data the prior decomposition reported (B vs A)**, just finer-grained.
- The shape from day 7+ onwards shows whether edge erodes or persists with longer holding-period sampling.

**If shape is flat from day 4 to day 31+**: the confirmation gate is pure opportunity cost --
  the day 1-3 entries an N=0 run would unlock are very likely also flat (no shape change before day 4).
**If shape rises from day 4 to day 7-9 then flattens**: entry stability matters; day 1-3 might be worse.
**If shape falls with later entries**: the early-period unlocked trades carry the edge; N=0 is worth running.