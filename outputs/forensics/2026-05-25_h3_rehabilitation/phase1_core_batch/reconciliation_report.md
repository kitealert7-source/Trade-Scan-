# H3 Rehabilitation Batch - Reconciliation Report

Generated: 2026-05-25T12:06:09.660360+00:00
Evaluator: `evaluator_frozen.py` sha256=`124f42978b92d78c...` (workspace == original == recorded)
Restoration manifest sha256: `6013046891f77143...`

## Dispatch summary
- Reruns dispatched: **22 / 22**
- PASS: **22**
- FAIL: **0**
- Total elapsed: ~22.6 min (excluding cooldowns)

## Evidence chain verification (frozen evaluator)
- Originals satisfying full chain: **22 / 22**
- Originals NOT satisfying chain: **0**

## Verdict transitions (pre-fix -> post-fix)
- `CORE->CORE`: 20
- `CORE->FAIL`: 2

## Per-original status (proposed for tagging when chain passes)

| directive_id | status | pre verdict / Net% / DD% | post verdict / Net% / DD% | sibling run_id |
|---|---|---|---|---|
| `15M_PAIRX_S20_V1_P01` | EVIDENCE_CHAIN_PASS | CORE / 227.18 / 18.90 | CORE / 222.35 / 15.88 | `140ce5e3` |
| `15M_PAIRX_S21_V1_P04` | EVIDENCE_CHAIN_PASS | CORE / 222.80 / 26.01 | CORE / 265.24 / 24.20 | `6654e5f2` |
| `5M_PAIRX_S06_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 243.67 / 22.42 | FAIL / 268.00 / 23.34 | `3723327b` |
| `5M_PAIRX_S08_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 184.35 / 24.11 | CORE / 179.48 / 25.77 | `e622d7cc` |
| `5M_PAIRX_S08_V1_P01` | EVIDENCE_CHAIN_PASS | CORE / 153.18 / 26.80 | CORE / 145.49 / 28.12 | `1ab5395a` |
| `5M_PAIRX_S10_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 198.36 / 23.22 | CORE / 192.68 / 24.62 | `0959f089` |
| `5M_PAIRX_S10_V1_P01` | EVIDENCE_CHAIN_PASS | CORE / 156.04 / 25.98 | CORE / 149.20 / 27.21 | `c8226856` |
| `5M_PAIRX_S14_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 191.00 / 23.73 | CORE / 185.31 / 25.17 | `4220c1ef` |
| `5M_PAIRX_S15_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 100.65 / 32.21 | CORE / 110.55 / 28.78 | `346f889b` |
| `5M_PAIRX_S15_V1_P01` | EVIDENCE_CHAIN_PASS | CORE / 98.35 / 35.55 | CORE / 106.94 / 32.46 | `fb8bbc13` |
| `5M_PAIRX_S15_V1_P02` | EVIDENCE_CHAIN_PASS | CORE / 123.76 / 31.72 | CORE / 127.39 / 31.42 | `92baf719` |
| `5M_PAIRX_S15_V1_P03` | EVIDENCE_CHAIN_PASS | CORE / 202.57 / 24.09 | CORE / 199.04 / 24.98 | `1bcde37a` |
| `5M_PAIRX_S16_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 190.59 / 23.24 | CORE / 187.46 / 24.03 | `866ef078` |
| `5M_PAIRX_S17_V1_P03` | EVIDENCE_CHAIN_PASS | CORE / 205.67 / 20.68 | CORE / 246.74 / 20.96 | `c836647f` |
| `5M_PAIRX_S17_V1_P04` | EVIDENCE_CHAIN_PASS | CORE / 193.64 / 23.30 | CORE / 217.79 / 21.59 | `074e2f4a` |
| `5M_PAIRX_S18_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 192.91 / 24.56 | CORE / 175.04 / 27.33 | `751c1c2b` |
| `5M_PAIRX_S19_V1_P02` | EVIDENCE_CHAIN_PASS | CORE / 210.52 / 22.10 | CORE / 248.56 / 20.54 | `6c94315f` |
| `5M_PAIRX_S19_V1_P03` | EVIDENCE_CHAIN_PASS | CORE / 168.99 / 23.74 | CORE / 159.58 / 27.02 | `423c1bfe` |
| `5M_PAIRX_S21_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 230.54 / 20.99 | CORE / 283.15 / 22.41 | `450d94f3` |
| `5M_PAIRX_S21_V1_P02` | EVIDENCE_CHAIN_PASS | CORE / 191.27 / 27.01 | CORE / 217.35 / 24.54 | `2651c608` |
| `5M_PAIRX_S21_V1_P03` | EVIDENCE_CHAIN_PASS | CORE / 151.73 / 35.71 | FAIL / 129.29 / 33.92 | `a165db71` |
| `5M_PAIRX_S22_V1_P00` | EVIDENCE_CHAIN_PASS | CORE / 182.54 / 24.24 | CORE / 225.59 / 26.26 | `17cdb8cc` |

## Failures (if any)
_None. All 22 originals satisfy the full evidence chain via the frozen evaluator._

## Next step (gated on operator approval)

If `EVIDENCE_CHAIN_PASS = 22/22`, the proposed tagging action is identical to the earlier 5-row pass: SUPERSEDED + `superseded_by_run_id` + BUG_FIX reason. Use the frozen-evaluator-backed tag script for execution.