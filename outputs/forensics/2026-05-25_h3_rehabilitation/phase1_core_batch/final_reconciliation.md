# H3 Rehabilitation Batch - Final Reconciliation

Generated: 2026-05-25T12:10:42.852051+00:00
Batch id: `h3_bidir_core_rehab_20260525`

## Before / After

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| total_baskets_rows | 311 | 311 | 0 |
| untagged_total | 222 | 200 | -22 |
| SUPERSEDED | 40 | 62 | +22 |
| RETIRED | 49 | 49 | 0 |
| visible_core_watch | 105 | 83 | -22 |

| Leakage tests (pytest) | n/a | **4 passed** | - |

## Unresolved bidirectional pre-fix rows (by verdict)

| Verdict | Count | Action |
|---|---:|---|
| **CORE** | 0 | NONE - rehabilitation gate met |
| WATCH | 1 | Deferred per scope - eligible for next batch |
| FAIL | 28 | Lowest priority - deferred |

### Remaining WATCH rows (deferred)
- `90_PORT_EURUSDUSDJPY_5M_PAIRX_S21_V1_P01`

## Gate verification (per operator constraint)

**PASS:** No visible CORE row remains with sign-flipped accounting. The remaining unresolved set is FAIL/WATCH-only, as required.

## Artifacts
- Restoration manifest: `restoration_manifest.json`
- Dispatch log:         `dispatch_log.jsonl`
- Reconciliation:       `reconciliation_report.md`
- Frozen evaluator:     `evaluator_frozen.py` (sha256 in `checksums.json`)
- This file:            `final_reconciliation.md`