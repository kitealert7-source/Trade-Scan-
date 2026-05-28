# Cointegration Research Ledger — Design & Implementation Plan

**Status:** COMPLETE — all phases (P0–P5) landed 2026-05-28. Commits: `b2d31cd` (this plan), `1beba64` (P0), `eb937c6` (P1), `a9814c9` (P2), `23fd2bd` (P3), `417a04c` (P4), `cf83656` (P5). Full cointegration test suite 64/64; gate suite + regression harness green on every commit.
**Date:** 2026-05-28
**Scope:** A greenfield, methodology-aware ledger for cointegration-join research — schema-separate from `basket_sheet`, infrastructure-shared, with a lean human view over a rich, future-proof DB.

---

## 1. Context & problem

One table (`basket_sheet`) was being asked to represent two incompatible ontologies:

| Operational basket ontology | Cointegration ontology |
|---|---|
| persistent deployable structures | episodic regime-valid structures |
| operational portfolio systems | methodology-sensitive research systems |
| broad lifecycle evaluation | narrow admissible windows |
| deployment gating | regime-validity gating |
| stable production semantics | conditional statistical semantics |

That mismatch is *why* verdict semantics felt wrong, provenance fields were missing, regime continuity suddenly mattered, and Ret/DD interpretation became ambiguous on cointegration runs. After the screener/window-validity changes (2026-05-28 reinterpretation), cointegration is no longer "just another basket strategy" — it is a regime-conditioned research domain with explicit admissibility semantics, and it deserves its own representation layer.

**Principle:** separate the *ontology / schema / view*, share the *engine / ledger mechanics / export / lineage*. Not an infrastructure fork.

---

## 2. Locked decisions

| ID | Decision |
|---|---|
| D1 | Routing key = presence of `basket.cointegration_join` on the directive (deterministic; same signal the window-validity gate uses). Not a fuzzy "research vs operational" label. |
| D2 | Allow override windows strictly inside the span; keep both `test_*` (executed window) and `span_*` (cointegrated span) in the DB. |
| D3 | Keep both `n_obs` (exec-TF bars) and `continuous_span_obs` (aligned daily rows) — named to disambiguate. |
| D4 | **No verdict in v1.** Rank by Ret/DD only. (See Rejected Alternatives.) |
| D5 | Clean DB-native lineage: `is_current` + populated `superseded_by/_at/_reason` + `supersede_kind`. |
| D6 | New `cointegration_sheet` table in the same `ledger.db`; new "Cointegration" tab in the same MPS workbook. |
| D7 | `classifier_version` is the screener-generation provenance — auto-captured from run-loaded data. |
| D8 | `research_metrics_registry.yaml` governs first-class columns + a `metrics_json` extras column; typed, flat, namespaced, scalar-only; writer fail-fasts on unknown keys. |
| D9 | Reproducibility quartet: `engine_version`, `strategy_code_sha256`, `directive_sha256`, `data_vintage` (+ `stake_usd`). |
| D10 | `supersede_kind` enum incl. `screener_change`. |
| D11 | Substrate retention via vault snapshot + `parquet_sha256`; pipeline-state-cleanup must not prune a coint row's substrate. |
| — | `methodology_generation` **removed entirely** (see Rejected Alternatives). |
| — | `research_rank` **not stored** — view-derived (see Rejected Alternatives). |

---

## 3. Architecture & seam

- **Storage:** new table `cointegration_sheet` in `ledger.db`.
- **Writer:** `tools/portfolio/cointegration_ledger_writer.py` — mirrors the basket writer's *mechanics* (FileLock on `Master_Portfolio_Sheet.xlsx.lock`, pre-insert SELECT-1 append-only, upsert, export trigger); owns its own schema.
- **Routing:** fork at `tools/run_pipeline.py` (the `append_basket_row_to_mps` call site): `cointegration_join` present → coint writer; else basket writer.
- **Export:** new "Cointegration" sheet via `export_mps` (already multi-sheet, row-conditional).
- **Single schema source:** `tools/portfolio/cointegration_schema.py` — DDL, writer, and formatter all import from it (no 4-way drift).
- **Shared:** `canonical_metrics`, execution/dispatch, FileLock, upsert/append-only, export plumbing.
- **Separate:** schema, ranking, display order, the tab.

---

## 4. Data flow — pure-sink writer

The writer reads **only local run artifacts** (result object + parquet + a `provenance` dict). It never opens the screener DB (`cointegration.db`, which lives in `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/`, not in `TradeScan_State`).

| Field group | Source | When |
|---|---|---|
| `regime_state`, `classifier_version` | the run's own loaded data (`coint_regime` column joined by `basket_data_loader`) | during backtest |
| `span_start/end`, `continuous_span_obs`, `fragment_count`, `pct_cointegrated`, `window_validation_status` | admission gate (`evaluate_window_validity()`, non-raising), threaded forward | at admission |

The screener is read **once, at admission, on the Trade_Scan side** (where the gate already reads it). Its result flows forward with the run; `TradeScan_State` only ever stores results.

---

## 5. DB schema (single source: `cointegration_schema.py`)

- **Identity/lineage:** `run_id`(PK), `directive_id`, `pair_a`, `pair_b`, `candidate_key`, `leg_specs`, `completed_at_utc`, `is_current`, `superseded_by`, `superseded_at`, `supersede_reason`, `supersede_kind`
- **Config:** `timeframe`, `lookback_days`
- **Run window:** `test_start`, `test_end`, `n_obs`, `stake_usd`
- **Regime provenance:** `span_start`, `span_end`, `continuous_span_obs`, `fragment_count`, `pct_cointegrated`, `regime_state`, `window_validation_status` (DB-only), `classifier_version`
- **Reproducibility:** `engine_version`, `engine_abi`, `strategy_code_sha256`, `directive_sha256`, `data_vintage`, `parquet_sha256`, `vault_path`, `backtests_path`
- **Metrics (reuse `canonical_metrics`):** `canonical_net_pct`, `canonical_max_dd_pct`, `canonical_max_dd_pct_vs_stake`, `canonical_ret_dd`, `canonical_final_equity_usd`, `cycle_win_rate_pct`, `cycles_completed`, `trades_total`
- **Extensible:** `metrics_json`, `metrics_fn_version`
- **Bookkeeping:** `schema_version` (`coint-1.0`), `enrichment_status`

No `verdict_status`, no `verdict_logic_version`, no stored `research_rank`.

---

## 6. Metrics extensibility (future-proofing)

`governance/research_metrics_registry.yaml` lists every admissible metric: `key → {type, namespace, first_class}`. `first_class: true` → typed column; else → `metrics_json` (zero-DDL). Writer enforces **scalar-only (no nesting), type-checked, registry-known, namespaced** keys; fail-fast otherwise. Promotion = flip the flag + one deliberate ALTER. `reenrich_cointegration_row(run_id)` recomputes derived metrics from the retained parquet → **a new metric is a recompute, not a re-run, not a migration.** A screener/data change is a *re-run* (new inputs) → new row, supersede old (`supersede_kind=screener_change`).

---

## 7. Human view (lean, ~16 cols)

`rank · pair · timeframe · lookback · run_date · test_start · test_end · return_dd_ratio · net_pct · max drawdown % · final_equity_usd · total_trades · cycles · win_rate · regime · backtest`

- Labels alias DB columns to the familiar names used by older sheets.
- Header comments self-document: `max drawdown %` → "peak-relative, mark-to-market incl. floating; not % of stake"; `win_rate` → "cycle-level"; `cycles` vs `total_trades`.
- `backtest` = clickable hyperlink to `../backtests/<id>/` from the stored `backtests_path` (not reconstructed) — fixes the "open yesterday's backtest" path-derivation failure.
- Sort that produces `rank`: `[canonical_ret_dd, completed_at_utc, run_id]` desc, stable; exact-tie → recency.
- Everything else is DB-only / hidden. Column-budget test caps the view at ≤ 17.

---

## 8. Verdict posture

v1 = pure Ret/DD `rank` (view-derived). No hard CORE/WATCH/FAIL. Verdict semantics get added later (append-only, with a `verdict_logic_version`) only after a meaningful B-compliant rerun corpus exists.

---

## 9. Phases

| # | Deliverable | Status |
|---|---|---|
| P0 | Single-source schema + `cointegration_sheet` table + types + tests | **DONE** `1beba64` |
| P1 | Non-raising `evaluate_window_validity()` + regime-provenance result object | **DONE** `eb937c6` |
| P2 | `cointegration_ledger_writer` (pure sink, fail-fast, append-only) + metrics registry | **DONE** `a9814c9` |
| P3 | Routing fork + provenance assembler + reproducibility threading | **DONE** `23fd2bd` |
| P4 | Export Cointegration tab + lean human view (rename, multi-key sort, hyperlink) | **DONE** `417a04c` |
| P5 | `reenrich` tool + `metrics_fn_version` + substrate-retention guard | **DONE** `cf83656` |

Notes on what shifted during execution: the run-side `classifier_version`/`data_vintage` emission (originally sketched in P1/P3) was deferred to `reenrich`/follow-up (both nullable, no migration needed); header comments on the human tab were deferred (friendly renames already carry the meaning). Neither affects the data layer.

---

## 10. Enforcement mechanisms

Writer fail-fast (missing provenance / missing backtest folder / unknown metric key) · metrics-registry validation · column-budget test · sort-order test · append-only SELECT-1 · `parquet_sha256` + retention guard · basket regression suite staying green (non-entanglement proof) · the schema module docstring + a test that bans verdict/rank columns.

---

## 11. Rejected alternatives

> Negative decisions, recorded so they are not re-litigated. Each is the answer to a future "why don't we just…".

### 11.1 Retrofitting cointegration into `basket_sheet` — REJECTED
*"Why don't we just add cointegration columns to the Baskets tab?"* — Because one table would carry two incompatible ontologies (§1). Retrofitting forces impossible questions ("what does CORE mean differently per basket family?"), produces NULL-heavy wide-union columns, and risks destabilizing the H2-recycle **deployment-critical** path. The 2026-05-28 audit found `basket_sheet` already carries 4-way schema drift, dead columns (`return_on_real_capital_pct`, the unused `superseded_*` trio), and a 3-way supersession split-brain — piling a second ontology on top compounds that entropy. Separation is *cheaper* to build (greenfield, no migration) and isolates blast radius: `basket_sheet` stays frozen.

### 11.2 Live screener dependency in the ledger writer — REJECTED
*"Why don't we just look the regime data up from the screener when building the row?"* — Because `TradeScan_State` stores results of backtests; it must not reach back into the master data store (`DATA_ROOT/SYSTEM_FACTORS`) at write time. Reading a *live* external DB at write time couples the ledger to state that drifts (the screener is re-run and reclassifies), so a row's provenance would not be frozen at the moment it was tested. Instead the screener is read once at admission (Trade_Scan side, where the gate already reads it) and the run emits regime fields from its own loaded data; the writer is a pure sink. This also removes the path-derivation fragility that caused the "open yesterday's backtest" error chain — the backtest path is *stored and validated*, never reconstructed.

### 11.3 Verdict semantics (CORE/WATCH/FAIL) — DEFERRED, not built in v1
*"Why don't we just classify these like everything else?"* — Because the CORE/WATCH/FAIL framing itself became suspect once screener/window assumptions changed. On short cointegrated windows those deployment-scale gates mislabel legitimate edge as FAIL (scale rejection ≠ edge rejection). There is not yet a B-compliant rerun corpus to calibrate a verdict against. v1 ranks by Ret/DD; verdict semantics are added later (append-only, with `verdict_logic_version`) once evidence exists. An **empty placeholder** verdict column was *also* rejected: it creates gravitational pull toward prematurely rebuilding classification complexity before the data justifies it.

### 11.4 `methodology_generation` column — REMOVED entirely
*"Why don't we stamp a generation tag on each row?"* — Because in a greenfield ledger that only ever holds post-enforcement runs, the tag is near-constant (every row shares it), and *being in this table at all* already encodes "post-enforcement." It is redundant with `classifier_version` (the screener generation, auto-captured from run data, at finer grain) plus `engine_version`. A constant/derived column is noise, and — like an empty verdict — it invites premature complexity. When a genuine second methodology generation eventually exists, `classifier_version` already distinguishes it.

### 11.5 Storing `research_rank` — REJECTED; rank is view-derived
*"Why don't we store the rank so every reader agrees?"* — Because rank is computed deterministically at export from `[canonical_ret_dd, completed_at_utc, run_id]` desc. A stored rank goes stale the moment any sibling row is added or superseded, and it implies an authority it does not have (it is an ordering of the current *visible set*, not a property of the row). The DB stores the raw inputs; readers re-derive identical ordering. A stored rank would be a cache that rots.

---

## 12. Out of scope (Track 2 — separate project)

Basket schema 4-way drift, dead-column removal, basket lineage unification, enum reconciliation, display-order derivation. Deliberately not entangled with this build.

---

## 13. Risks

- **Consumer fan-out** (one-time, bounded): `export_mps`, the formatter (`_PORTFOLIO_DATA_SHEETS`, sort/rank, hyperlinks), SYSTEM_STATE counts, `cointrev_v1_2_aggregator`. Enumerated in P4 so none silently miss the new source.
- **Admission→run threading** of the gate result + reproducibility fields is the one cross-component seam (P1/P3).
- **Screener DB must exist at admission** — already a fail-fast in the gate.
