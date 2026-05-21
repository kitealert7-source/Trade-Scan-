> ⚠ **HISTORICAL — COINTREV v1 strategy chain retired 2026-05-21.**
> This phase describes the cointegration history matrix and its consumer
> contract. The history matrix infrastructure itself is **clean and
> retained** (`indicators/stats/cointegration_state.py`,
> `tools/cointegration_history_matrix.py`). What was retired is the
> strategy this manifest motivated (`cointegration_meanrev_v1.py`) and
> the directive generator (`generate_cointrev_directives.py`) — both
> deleted per the conflation story documented in
> `outputs/cointegration_screener_v1/backtest_v1/COHORT_REPORT.md` header.
> Re-evaluate the consumer-contract claims before any future strategy
> takes a dependency on this matrix.
>
> ---

# Phase C0 — Historical Cointegration Matrix Manifest

**Status:** BUILT + VERIFIED + ARTIFACT IMMUTABLE — 2026-05-20
**Spec reference:** [`COINTEGRATION_SCREENER_V1_SPEC.md`](../../system_reports/06_strategy_research/COINTEGRATION_SCREENER_V1_SPEC.md) §4 + addendum below
**Path C step:** 1 of 7 (foundation — all downstream backtest steps depend on this artifact)
**Versioning discipline:** content-addressable hash, sidecar manifest, never-overwrite, LATEST pointer
**Gate cleared:** Phase C1 (`indicators/stats/cointegration_state.py` wrapper) may begin

---

## Deliverables

| File | Purpose |
|---|---|
| `tools/cointegration_history_matrix.py` | Pre-compute script with `--force` and `--dry-run`. Idempotent on identical inputs (skips rebuild). |
| `tests/test_cointegration_history_matrix.py` | 14 unit tests: per-pair compute correctness, hash determinism, never-overwrite enforcement, LATEST-pointer behavior, manifest required fields. |
| `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/coint_1d_history_matrix_6e6202fa4958.parquet` | The matrix (11.5 MB) |
| `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/coint_1d_history_matrix_6e6202fa4958.manifest.json` | Provenance sidecar (87 KB) |
| `data_root/SYSTEM_FACTORS/FX_COINTEGRATION/coint_1d_history_matrix_LATEST.json` | Pointer to current build (≤1 KB; only mutable artifact) |

## Test gate

> 14/14 tests passing in 4.84s — `pytest tests/test_cointegration_history_matrix.py -v`

Covers: per-pair β/spread/z/ADF correctness, dtype freezing, warmup behavior, hash determinism, never-overwrite raises `FileExistsError`, `--force` allows intentional rebuild, different hashes coexist (no collision deletion), LATEST pointer overwrite IS allowed.

## Build artifact

- **Matrix hash:** `6e6202fa4958` (SHA-256 prefix of params + 18-pair × ~20-year CSV-mtime inventory)
- **Rows:** 623,322 (153 pair-pairs × 4074 daily bars)
- **Date range:** 2010-05-10 → 2026-05-20 (intersection of all 18 pairs)
- **Qualified rows:** 6,388 / 623,322 = **1.0%** of pair-day combinations
- **Build time:** 239.5s (~4 min)
- **Parquet size:** 11.5 MB

## Empirical findings from the matrix

**Cointegration is structurally uncommon in FX.** Only 1.0% of pair-days qualify (BOTH 252d AND 504d ADF p < 0.05) over the 14-year sample. This matches both intuition and the event-study finding that only 28-56 unique pair-pairs ever triggered at any threshold.

**Top 5 pair-pairs by qualified-day count:**

| Rank | Pair | Qualified days |
|---|---|---|
| 1 | GBPNZD / USDJPY | 441 |
| 2 | GBPAUD / NZDUSD | 357 |
| 3 | AUDNZD / USDCHF | 252 |
| 4 | EURUSD / USDJPY | 231 |
| 5 | GBPNZD / NZDJPY | 210 |

These are the structural workhorses — pair-pairs whose spread has been stationary for the longest cumulative time. They'll naturally dominate the backtest universe filter (any-time-qualified ≈ 28 pairs at τ=2.0).

## Versioning discipline — enforced by code, not convention

Per architectural review 2026-05-20 the matrix is **content-addressable**:

```
filename pattern: coint_1d_history_matrix_<HASH12>.parquet
hash inputs:     SHA-256 of (params + universe + per-CSV mtime)
                 — same inputs → same hash
                 — any param change OR data refresh → new hash
```

`write_artifact()` **refuses to overwrite** an existing hashed parquet (`FileExistsError`). To force a rebuild, the operator must either:
- Pass `--force` (explicit intent; destroys reproducibility for directives pinned to that hash)
- Manually delete the old artifact

The **LATEST pointer is the only mutable artifact** — it records the most recent hash for downstream tools that want "current" instead of pinning to a specific hash. Hashed parquets and manifests are immutable.

### What this means operationally for backtests

A backtest directive pins itself to a specific `matrix_hash`. Re-running the directive against that hash always produces identical trades (subject to source-data immutability, which the CSV mtimes capture). This is the cleanest reproducibility guarantee — a study can be re-run weeks or months later and produce bit-identical results, even if the live cointegration data has since moved on to a new hash.

When the live screener's daily run discovers new data (next morning's daily bars), the next history-matrix build will produce a NEW hash; the OLD hash stays on disk; previously-pinned directives stay reproducible.

## How to use the matrix (for downstream code)

```python
# Load by LATEST (most common case)
import json
from pathlib import Path
from config.path_authority import DATA_ROOT

ptr = json.loads((DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION"
                   / "coint_1d_history_matrix_LATEST.json").read_text())
matrix_path = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / ptr["parquet_file"]

# OR load by specific hash (when a backtest directive pins one)
matrix_path = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / f"coint_1d_history_matrix_{pinned_hash}.parquet"

import pandas as pd
matrix = pd.read_parquet(matrix_path)
matrix.set_index(["date", "pair_a", "pair_b"], inplace=True)

# Look up qualification for EURUSD/USDJPY at a specific date
row = matrix.loc[(pd.Timestamp("2024-05-15"), "EURUSD", "USDJPY")]
if row.qualified:
    proceed_with_15m_entry_logic(...)
```

## What's next (Path C remaining steps)

| Step | Deliverable | Depends on |
|---|---|---|
| C1 | `indicators/stats/cointegration_state.py` — read-from-matrix wrapper exposed in indicator contract | C0 ✓ |
| C2 | `tools/recycle_rules/cointegration_meanrev_v1.py` — entry on 15m \|z\|≥2 within daily-flagged window, exit at \|z\|≤1 or stop or time | C1 |
| C3 | Strategy.py + 1 hand-crafted directive (e.g. GBPNZD/USDJPY — top of leaderboard) | C2 |
| C4 | Directive generator for the ~28 τ=2.0-ever-triggered pairs | C3 |
| C5 | Run `tools/run_pipeline.py --all` across the generated directives | C4 |
| C6 | Aggregation + cross-check vs event-study cohort metrics | C5 |
| C7 | Backtest report + spec promotion to v1.1 if results pass | C6 |

## How to re-run (idempotent — no compute if hash already exists)

```powershell
cd C:\Users\faraw\Documents\Trade_Scan
python tools/cointegration_history_matrix.py             # builds if hash changed; SKIP otherwise
python tools/cointegration_history_matrix.py --dry-run   # print hash + params, no work
python tools/cointegration_history_matrix.py --force     # destroys reproducibility; intentional
```

## Files in production layout (post-C0)

```
data_root/SYSTEM_FACTORS/FX_COINTEGRATION/
    coint_1d_latest.parquet                                 (Phase 1 — runtime snapshot)
    metadata.json                                            (Phase 1)
    cointegration.db                                         (Phase 2 — daily history)
    Cointegration_Screener.xlsx                              (Phase 3 — human view)
    coint_1d_history_matrix_6e6202fa4958.parquet             (Phase C0 ← NEW)
    coint_1d_history_matrix_6e6202fa4958.manifest.json       (Phase C0 ← NEW)
    coint_1d_history_matrix_LATEST.json                      (Phase C0 ← NEW)
```
