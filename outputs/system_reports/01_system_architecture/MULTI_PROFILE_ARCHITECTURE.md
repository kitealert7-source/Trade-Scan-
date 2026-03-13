# AGENT DIRECTIVE — MULTI-PROFILE WRAPPER ARCHITECTURE VALIDATION

## SECTION 1 — ARCHITECTURE OPTIONS

### Option A: Sequential Profile Execution

Run the full event-driven queue once per profile. Each profile gets its own complete pass over the chronological trade stream.

| Criterion | Assessment |
| :--- | :--- |
| **Implementation Complexity** | LOW |
| **Performance Impact** | 2× wall-clock time (linear scaling per profile added) |
| **Reporting Complexity** | LOW — Each run produces independent artifacts |
| **Risk of State Contamination** | ZERO — Completely isolated executions |
| **Determinism Stability** | PERFECT — Identical input → identical output per profile, guaranteed |

### Option B: Parallel Multi-State Execution

Single event loop iterates the chronological queue once. Each event is dispatched to N independent `PortfolioState` objects simultaneously.

| Criterion | Assessment |
| :--- | :--- |
| **Implementation Complexity** | MEDIUM |
| **Performance Impact** | ~1.1× wall-clock (single pass, marginal overhead per state update) |
| **Reporting Complexity** | MEDIUM — Must split emissions per profile at write-time |
| **Risk of State Contamination** | LOW — Requires strict object isolation discipline (no shared mutables) |
| **Determinism Stability** | PERFECT — Single-threaded, sequential event dispatch; no concurrency hazard |

### Comparison Summary

| Factor | Sequential (A) | Parallel (B) |
| :--- | :--- | :--- |
| Speed (2 profiles) | ~2× | ~1.1× |
| Speed (5 profiles) | ~5× | ~1.3× |
| Code simplicity | Trivial loop wrapper | Moderate state management |
| Scalability to N profiles | Poor | Excellent |
| State safety | Guaranteed | Requires defensive coding |

---

## SECTION 2 — OUTPUT STRUCTURE DESIGN

### Option 1: Directory-Split

```
results_deployable/
    CONSERVATIVE_V1/
        results_tradelevel.csv
        summary_metrics.json
        equity_curve.csv
    AGGRESSIVE_V1/
        results_tradelevel.csv
        summary_metrics.json
        equity_curve.csv
```

### Option 2: Column-Tagged

```
results_deployable.csv
    → columns: profile, symbol, entry_timestamp, ...
```

### Recommendation: **Option 1 (Directory-Split)**

| Justification |
| :--- |
| Aligns with existing governance artifact structure (`backtests/{strategy}/raw/`). |
| Each profile produces self-contained, independently archivable artifacts. |
| Column-tagged CSVs create parsing complexity for downstream consumers and break the existing 1-CSV = 1-context contract. |
| Directory-split trivially supports adding new profiles without schema migration. |
| Snapshot archival (`vault/`) and cleanup reconciler already operate on directory-level granularity. |

---

## SECTION 3 — METRIC COMPARABILITY

| Question | Recommendation |
| :--- | :--- |
| **`summary_metrics.json` structure** | **A) Separate per profile.** Each profile directory gets its own `summary_metrics.json` containing CAGR, Max DD, MAR, Sharpe, heat utilization, rejection count, etc. |
| **Unified comparison JSON** | YES — Additionally emit a single `profile_comparison.json` at the parent `results_deployable/` level aggregating key metrics side-by-side for quick diff. |
| **Side-by-side comparative report** | YES — The reporting engine should auto-generate a comparison table. |

### Proposed `profile_comparison.json` Schema

```
{
  "profiles": {
    "CONSERVATIVE_V1": {
      "cagr": ..., "max_dd_pct": ..., "mar": ...,
      "trades_accepted": ..., "trades_rejected": ...,
      "final_equity": ...
    },
    "AGGRESSIVE_V1": {
      "cagr": ..., "max_dd_pct": ..., "mar": ...,
      "trades_accepted": ..., "trades_rejected": ...,
      "final_equity": ...
    }
  },
  "generated_utc": "..."
}
```

---

## SECTION 4 — RECOMMENDATION

**Recommended Architecture:** **Option B — Parallel Multi-State Execution**

| Rationale |
| :--- |
| The event queue (chronological sort of all Stage-1 CSVs) is the most expensive operation. Iterating it once and dispatching to multiple lightweight `PortfolioState` objects is far more efficient than rebuilding and re-sorting the queue per profile. |
| State contamination risk is LOW because each `PortfolioState` is a self-contained object with its own equity float, heat tracker, and rejection log — no shared mutables exist. |
| Determinism is guaranteed by single-threaded sequential dispatch. |
| Scales cleanly to 5+ profiles without proportional wall-clock increase. |

**Output Structure:** Option 1 (Directory-Split)

**Metrics:** Separate per-profile `summary_metrics.json` + unified `profile_comparison.json`

### Added Complexity (Transparent Disclosure)

| Area | Complexity Added |
| :--- | :--- |
| `PortfolioState` class design | Must be fully self-contained (equity, heat, margin, rejection log) |
| Event dispatcher | Must iterate states in a loop per event — trivial but must be tested for isolation |
| Emission logic | Must route CSV writes to correct profile subdirectory |
| Comparison report generator | New ~100-line module to diff profile metrics |

Total additional complexity vs single-profile wrapper: **~150–200 LOC**.
