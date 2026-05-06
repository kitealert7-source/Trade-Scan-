
---

## Trade Path Geometry

### Path Archetypes

| Archetype | N | % | Avg R | Med MFE |
|-----------|---|---|-------|---------|
| Fast Expand      (pos exit, mae <= 0.25R) | 2 | 16.7% | +1.00R | 1.20R |
| Recover Win      (pos exit, adverse first) | 2 | 16.7% | +1.80R | 2.15R |
| Profit Giveback  (SL, mfe >= 1R) | 2 | 16.7% | -1.00R | 1.50R |
| Stall-Decay      (SL, mfe 0.1–1R) | 3 | 25.0% | -1.00R | 0.40R |
| Immediate Adverse(SL, mfe < 0.1R) | 2 | 16.7% | -1.00R | 0.05R |
| Time-Flat        (non-SL exit, r <= 0) | 1 | 8.3% | -0.20R | 0.30R |

### Capture Quality

| Metric | Value |
|--------|-------|
| MFE Capture Ratio (winners) | 84.1% |
| Wasted-Edge (SL with mfe >= 0.5R) | 28.6% (2 trades) |
| Immediate-Adverse (SL, mfe < 0.1R) | 28.6% (2 trades) |

**Stall-Decay:** 3 trades (25.0%) | avg 16 bars held | avg MFE 0.38R | avg exit -1.00R — primary DD driver; investigate time-in-trade trail.

**Profit Giveback:** 2 trades (28.6% of SL) | avg peak MFE 1.50R | avg final R -1.00R — investigate partial/lock trigger level.
