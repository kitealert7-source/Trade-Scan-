# H3 Phase-2 Rehabilitation - Final Reconciliation

Generated: 2026-05-25T12:48:51.130470+00:00
Batch id: `h3_bidir_phase2_rehab_20260525`

## Dispatch

- Reruns: **16 / 16**  PASS: **16**  FAIL: 0
- Verdict transitions: {'FAIL->FAIL': 14, 'FAIL->CORE': 1, 'WATCH->CORE': 1}

## Tagging

- Originals tagged SUPERSEDED: **16**
- Already-tagged skipped: 0

## Before / After

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| total_baskets_rows | 327 | 327 | 0 |
| untagged_total | 216 | 200 | -16 |
| SUPERSEDED | 62 | 78 | +16 |
| RETIRED | 49 | 49 | 0 |
| visible_core_watch | 85 | 84 | -1 |
| Leakage CI tests | n/a | **4 passed** | - |

## Remaining unresolved bidirectional pre-fix

| Verdict | Count | Disposition |
|---|---:|---|
| CORE | 0 | NONE - gate met |
| WATCH | 0 | NONE - gate met |
| FAIL | 13 | Triage-skipped (no rehab benefit) - remain visible as FAIL |

**GATE MET:** Remaining unresolved set is FAIL-only (13 rows triage-skipped).