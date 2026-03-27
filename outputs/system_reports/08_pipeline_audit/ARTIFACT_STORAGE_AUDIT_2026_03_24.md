# Artifact Storage Audit Report
**Scope:** Trade_Scan / TradeScan_State backtest artifact system
**Date:** 2026-03-24
**Type:** Read-only diagnostic — no files modified
**Sample:** 223 backtest folders across 66 strategies

---

## Section 1 — Run Structure Validation

**Required files checked per run:**

| Folder | config.json | meta.json | trades.csv | equity_curve.csv | results_standard | results_risk | results_yearwise | run_metadata.json | STATUS |
|---|---|---|---|---|---|---|---|---|---|
| 03_TREND_XAUUSD_1H_IMPULSE_..._XAUUSD | ❌ | ❌ | ✅ (tradelevel) | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| 11_REV_XAUUSD_1H_SPKFADE_..._XAUUSD | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| 01_MR_FX_1H_ULTC_..._AUDUSD | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| 02_VOL_IDX_1D_VOLEXP_..._XAUUSD | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |
| PF_* portfolio folders (×54) | ❌ | ❌ | ✅ only | ❌ | ❌ | ❌ | ❌ | ❌ | **BROKEN** |
| 14_BRK_FX_4H_BBSQZ_..._EURUSD | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **PARTIAL** |

**Summary across all 223 folders:**

| Status | Count | Pct |
|---|---|---|
| COMPLETE | 0 | 0% |
| PARTIAL | 169 | 76% |
| BROKEN | 54 | 24% |

---

## Section 2 — Reproducibility Check

**Fields audited across all runs:**

| Field | Present | Location | Example value |
|---|---|---|---|
| `config_hash` | ❌ MISSING | — | — |
| `code_version` / `git_commit` | ❌ MISSING | — | — |
| `slippage_model` | ❌ MISSING | — | — |
| `spread_model` | ❌ MISSING | — | — |
| `order_type` | ❌ MISSING | — | — |
| `symbol` | ✅ | `run_metadata.json` | `XAUUSD` |
| `timeframe` | ✅ | `run_metadata.json` | `1h` |
| `date_range` | ✅ | `run_metadata.json` | `2021-01-01 → 2026-03-20` |
| `broker` | ✅ | `run_metadata.json` | `OctaFX` |
| `engine_version` | ✅ | `run_metadata.json` | `1.5.3` |
| `run_id` | ✅ | `run_metadata.json` | `7f030aac9bcfe612...` (opaque) |

**Reproducibility classification:**

| Class | Count | Reason |
|---|---|---|
| REPRODUCIBLE | 0 | — |
| WEAK | 169 | Data signature present; no code version, no config hash, no execution model |
| NON_REPRODUCIBLE | 54 | PF_ folders — no metadata at all |

---

## Section 3 — Run Isolation Check

| Check | Result |
|---|---|
| Each run has its own unique folder | ✅ |
| No shared files between runs | ✅ |
| No overwrites detected | ✅ |
| Multi-symbol runs correctly isolated | ✅ |
| run_id is config-derivable / human-readable | ❌ Opaque random hash — not tied to config state |

**Verdict: ISOLATED — but run identity is opaque.**
`run_id` cannot be reconstructed from inputs. Two runs of the same config produce different IDs with no way to detect they are equivalent.

---

## Section 4 — Report Linkage Check

| Artifact | Linked to run_id? | Linked to config? |
|---|---|---|
| `results_standard.csv` | ❌ | ❌ |
| `results_risk.csv` | ❌ | ❌ |
| `run_metadata.json` | ✅ Contains run_id | ❌ No config reference |
| `portfolio_summary.json` | ❌ Standalone | ❌ |
| `portfolio_tradelevel.csv` | ❌ Standalone | ❌ |

**Classification: UNLINKED**
Reports exist but do not reference run_id or config state. Traceability is folder-position-dependent, not self-describing. Moving or renaming a folder severs all provenance.

---

## Section 5 — Duplication / Redundancy Check

| Issue | Detail |
|---|---|
| Exact duplicate runs | None detected |
| Pass variants without config diff | `_P00` through `_P03` variants exist with no stored explanation of what changed between passes — curve fitting risk is unauditable |
| Duplicate trade data | `portfolio_tradelevel.csv` in `portfolio_evaluation/` AND `results_tradelevel.csv` in `raw/` — same data stored twice per run |
| PF_ folder purpose | 54 folders contain only `results_tradelevel.csv` — origin, purpose, and parent run completely undocumented |

---

## Section 6 — Discoverability Test

**Query simulated:** *"Find all runs where PF > 1.5, DD < 10%, timeframe = 1H"*

| Step | Action required |
|---|---|
| 1 | Open 223 folders manually |
| 2 | Open `raw/results_standard.csv` in each — contains `profit_factor` |
| 3 | Open `raw/results_risk.csv` in each — contains `max_drawdown_pct` (separate file) |
| 4 | Open `run_metadata.json` in each — contains `timeframe` |
| 5 | Cross-reference across 3 files manually — no join mechanism exists |

- Minimum files to open to answer query: **669** (3 × 223)
- Central index: **does not exist**
- Programmatic query without custom scan script: **impossible**

**Classification: PAINFUL**

---

## Section 7 — Failure Mode Check

| Issue | Count | Detail |
|---|---|---|
| Incomplete runs present with no flag | 54 | PF_ folders — 1 file only, no INVALID marker, no error log |
| Missing equity_curve.csv, unflagged | ≥1 | `01_MR_FX_1H_ULTC_..._AUDUSD` |
| Silent failures (no marker files) | Confirmed | No INVALID, no FAILED, no partial-run indicators anywhere |
| Zero-byte result files | 0 | None detected |

---

## Final Verdict

```json
{
  "artifact_integrity":    "WEAK",
  "reproducibility":       "NON_REPRODUCIBLE",
  "run_isolation":         "STRONG",
  "report_linkage":        "UNLINKED",
  "discoverability":       "PAINFUL",
  "failure_transparency":  "NONE",

  "critical_gaps": [
    "config_hash absent from all 223 runs — param drift between passes undetectable",
    "code_version / git_commit absent — results untraceable to code state",
    "execution model (slippage, spread, order_type) undocumented in any run",
    "no central index — discovery requires scanning 223 folders across 3 files each",
    "54 PF_ portfolio folders broken — purpose and provenance completely unknown",
    "pass variants (_P00, _P01...) have no diff record — curve fitting risk unauditable"
  ],

  "what_works": [
    "run isolation — each run in its own folder, no overwrites",
    "data signature partially complete — symbol, timeframe, broker, date range in run_metadata.json",
    "results files present and non-empty in 169/223 runs",
    "engine version recorded in run_metadata.json"
  ],

  "registry_needed": true,
  "registry_priority": "HIGH",

  "minimum_viable_additions": [
    "config_hash per run (SHA256 of directive content)",
    "code_version.txt (git commit hash at run time)",
    "execution_model fields appended to run_metadata.json",
    "central index.csv — append-only, PF + DD + trades per run",
    "INVALID marker file for broken or incomplete runs"
  ]
}
```

---

## Bottom Line

The system has **good run isolation and partial data signatures** but **zero provenance traceability**. Every run is a black box — the *what* is tested is known, but not *with what code*, *with what exact config*, or *under what execution assumptions*. The 54 broken PF_ folders are silently incomplete with no flags. Answering a single filtered query requires manually opening a minimum of 669 files.

**A registry layer is warranted.** The minimum viable additions (config_hash + git commit + index.csv) close the critical gaps without restructuring the existing storage layout or touching any pipeline code.
