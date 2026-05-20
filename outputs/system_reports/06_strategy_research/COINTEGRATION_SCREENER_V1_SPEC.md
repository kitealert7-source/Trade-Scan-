# COINTEGRATION SCREENER — V1 SPECIFICATION (FROZEN)

**Status:** v1 frozen — implementation may proceed once Phase 0 (identity smoke test) passes
**Owner:** research-infrastructure layer
**Author:** session 2026-05-20
**Supersedes:** none (greenfield)

---

## 1. Purpose & Scope

A daily-cadence batch screener that computes cointegration statistics for every pair-combination in the 18-pair FX universe, persists the results to two stores serving two different consumers, and surfaces them through an Excel viewing layer for human research.

**In scope (v1):**
- 18 FX pairs from `tools/factors/fx_correlation_matrix.py::FX_UNIVERSE`, yielding 153 unordered pair-pairs.
- Daily TF only. Two rolling window lengths run side-by-side: **252 bars (1y)** and **504 bars (2y)** — both written, neither preferred at the schema level.
- Per pair-pair per window: ADF p-value, half-life (OU fit), hedge ratio (β), current spread z-score, regime label.
- Two persistence stores (see §4) and one Excel report (see §9).
- Daily scheduled run via Windows Task Scheduler under a validated service identity (see §10).

**Out of scope (v1):**
- Johansen multi-asset cointegration (deferred to v2)
- Kalman-filtered hedge ratios (β method extensible — see §5)
- Intraday cadence
- Non-FX symbols (XAU/XAG/indices/crypto)
- Auto-trading or execution coupling — this is a research artifact only

---

## 2. Dataflow

```
MASTER_DATA / <SYM>_OCTAFX_MASTER / RESEARCH / <SYM>_OCTAFX_1d_<YEAR>_RESEARCH.csv
    │
    │  (year-files, 18 symbols × ~20 years × CSV)
    ▼
[ compute_engine ]                              ← tools/cointegration_screen.py
    │
    │  pandas DataFrame (153 rows × N columns) per (as_of, window)
    ▼
[ parquet snapshot — SOURCE OF TRUTH ]          ← coint_1d_latest.parquet
    │                                              (overwritten each run; reproducible
    │                                               from inputs alone)
    │
    ▼
[ SQLite append — REPORTING SINK ]              ← cointegration.db
    │                                              (longitudinal history; append-only;
    │                                               never the source for compute)
    │
    ▼
[ Excel regeneration ]                          ← Cointegration_Screener.xlsx
                                                   (rebuilt from SQLite on demand)
```

**Architectural rule (FROZEN):** parquet is the computation artifact. SQLite is the reporting sink. Excel is the human view.
**Never:** compute → SQLite → everything else.
**Never:** treat SQLite as the recompute source.

---

## 3. Source-of-Truth Hierarchy

| Question | Authoritative source |
|---|---|
| "What is today's cointegration state for pair X?" | `coint_1d_latest.parquet` |
| "Has this pair been cointegrated for the last 6 months?" | `cointegration.db` (history) |
| "Why did pair X get half-life 12 days?" | Rerun compute from MASTER_DATA CSVs → bit-identical parquet (by `data_version`) |
| "What does the operator see?" | `Cointegration_Screener.xlsx` regenerated from SQLite |

**Recompute contract:** running the screener with the same MASTER_DATA snapshot + same code commit must produce a bit-identical `coint_1d_latest.parquet`. SQLite rows then derive from parquet, not the other way round.

---

## 4. Storage Architecture

**All cointegration artifacts co-located under SYSTEM_FACTORS** so backtests have a single read location for the full FX-cointegration surface (matches the `FX_CORRELATION_MATRIX` precedent):

```
DATA_ROOT / SYSTEM_FACTORS / FX_COINTEGRATION /
    coint_1d_latest.parquet         (Phase 1 — runtime source of truth; overwritten each run)
    metadata.json                   (Phase 1 — schema version, universe, provenance)
    cointegration.db                (Phase 2 — single table; append-only; daily history)
    Cointegration_Screener.xlsx     (Phase 3 — regenerated from DB on demand)
    .xlsx.lock                      (FileLock sidecar; matches safe_append_excel.py pattern)
    coint_1d_history.parquet        (DEFERRED to v1.1 — optional rolling-window accumulator)
```

### 4a. Parquet — runtime / system-factor consumption

The `coint_1d_latest.parquet` is the deterministic computation artifact. Matches the `FX_CORRELATION_MATRIX` convention; integrates natively with pandas/polars for any future runtime consumer (e.g. a basket_data_loader join); no DB-lock concerns; reproducible from inputs alone.

### 4b. SQLite — longitudinal audit + Excel reporting

The `cointegration.db` holds the time-series of test results, queryable for "when did pair X break/recover" history.

**Why SQLite here (not in TradeScan_State, where the original draft placed it):** SQLite is derived FX reference data, not pipeline run state. Backtests querying "was this pair cointegrated on date X?" should not have to reach into the pipeline-output repo for input data — the parquet (runtime), SQLite (history), and Excel (human view) sit together under SYSTEM_FACTORS. TradeScan_State remains focused on strategy ledgers, run lineage, and portfolio state. **Architectural correction logged 2026-05-20.**

### 4c. Historical state-lake matrix — content-addressable, immutable per build (Phase C0, addendum 2026-05-20)

`coint_1d_history_matrix_<HASH12>.parquet` is the **backtest-time** input — full historical cointegration features for every (date, pair_a, pair_b) over the 14-year intersection window. Distinct from §4a's `coint_1d_latest.parquet` (single snapshot) and §4b's `cointegration.db` (accumulating live history).

**Versioning discipline (enforced by code in `tools/cointegration_history_matrix.py`):**

| Rule | Mechanism |
|---|---|
| **Hash it** | Filename embeds SHA-256 prefix of (params + universe + per-CSV mtime). Same inputs → same hash. |
| **Manifest it** | Sidecar `coint_1d_history_matrix_<HASH>.manifest.json` captures params, universe, source CSV inventory, date range, matrix stats, generated_at. |
| **Freeze per backtest batch** | A backtest directive pins itself to a specific `matrix_hash`. Re-running against that hash produces identical trades. |
| **Never overwrite** | `write_artifact()` raises `FileExistsError` if an artifact with the same hash already exists. `--force` flag required for intentional rebuild. |
| **LATEST pointer is the sole mutable file** | `coint_1d_history_matrix_LATEST.json` records the most-recent hash; downstream code that wants "current" reads this. Hashed parquets + manifests stay immutable. |

**Why this discipline matters:** once the qualification matrix changes, all downstream entries / trades / statistics change too. Provenance discipline protects against accidental result drift during a research study — a directive run on matrix v1 always produces v1's results, regardless of what's been built since.

**Operational use:** the live screener's daily run (§4a) writes its own daily snapshot; it does NOT update the history matrix. Matrix rebuilds are intentional research events, not automated.

---

## 5. Schema

### 5a. Parquet (`coint_1d_latest.parquet`)

One row per (pair_a, pair_b, window). 153 pairs × 2 windows = **306 rows per run.**

| Column | Type | Required | Description |
|---|---|---|---|
| `pair_a` | string | yes | Alphabetically first leg (deterministic) |
| `pair_b` | string | yes | Alphabetically second leg |
| `tf` | string | yes | Always `"1d"` in v1 |
| `lookback_days` | int32 | yes | 252 or 504 |
| `window_start` | datetime64[ns, UTC] | yes | First bar in compute window — reproducibility |
| `window_end` | datetime64[ns, UTC] | yes | Last bar in compute window |
| `sample_size` | int32 | yes | Actual bars used (≤ lookback_days; sanity check for NaN drops) |
| `adf_pvalue` | float32 | yes | Augmented Dickey-Fuller p-value on spread |
| `pvalue_rolling_median_5d` | float32 | nullable | Median of last 5 `adf_pvalue` snapshots for this (pair_a, pair_b, lookback). **Observability only in v1** — NOT used by the classifier. Enables empirical evaluation of a smoothed regime classifier in v1.1. NaN until 5 prior snapshots exist. |
| `adf_statistic` | float32 | yes | ADF test statistic |
| `half_life_days` | float32 | nullable | OU half-life; NaN if non-stationary or β<0 |
| `hedge_ratio` | float32 | yes | β from OLS regression `B = α + β·A + ε` |
| `beta_method` | string | yes | `"ols_static"` in v1; `"kalman"` / `"rolling_ols"` in v1.x |
| `test_method` | string | yes | `"adf"` in v1; `"johansen"` in v2 |
| `current_zscore` | float32 | yes | Live z-score of spread at `window_end` (units of in-sample σ) |
| `regime` | string | yes | `"cointegrated"` / `"breaking"` / `"broken"` — see §7 |
| `data_version` | string | yes | Hash of MASTER_DATA inputs — guards against silent rewrites |
| `generated_at` | datetime64[ns, UTC] | yes | Run timestamp |

**Future-proof columns rationale (per architectural review):** `window_start/end`, `sample_size`, `beta_method`, `test_method`, `data_version` are written from day 1 even though v1 only ever populates one value per method column. Cost is zero, payoff is large when v2 adds Johansen / Kalman without schema migration.

### 5b. SQLite (`cointegration_daily` table)

```sql
CREATE TABLE IF NOT EXISTS cointegration_daily (
    as_of           TEXT    NOT NULL,    -- ISO date (UTC)
    pair_a          TEXT    NOT NULL,
    pair_b          TEXT    NOT NULL,
    tf              TEXT    NOT NULL,
    lookback_days   INTEGER NOT NULL,
    window_start    TEXT    NOT NULL,
    window_end      TEXT    NOT NULL,
    sample_size     INTEGER NOT NULL,
    adf_pvalue      REAL    NOT NULL,
    pvalue_rolling_median_5d REAL,           -- observability only; nullable; not used by classifier
    history_depth   INTEGER NOT NULL DEFAULT 0,  -- # prior snapshots used for this row's classification (0..HYSTERESIS_LOOKBACK); <5 = bootstrap path active
    adf_statistic   REAL    NOT NULL,
    half_life_days  REAL,                -- nullable
    hedge_ratio     REAL    NOT NULL,
    beta_method     TEXT    NOT NULL,
    test_method     TEXT    NOT NULL,
    current_zscore  REAL    NOT NULL,
    regime          TEXT    NOT NULL,
    data_version    TEXT    NOT NULL,
    inserted_at     TEXT    NOT NULL,    -- ISO datetime (audit; separate from generated_at)
    PRIMARY KEY (as_of, pair_a, pair_b, tf, lookback_days)
);

CREATE INDEX IF NOT EXISTS idx_coint_pair    ON cointegration_daily (pair_a, pair_b);
CREATE INDEX IF NOT EXISTS idx_coint_regime  ON cointegration_daily (as_of, regime);
CREATE INDEX IF NOT EXISTS idx_coint_history ON cointegration_daily (pair_a, pair_b, lookback_days, as_of DESC);
```

**Append-only:** the PK prevents duplicate inserts; on re-run for the same `as_of` the upsert uses `ON CONFLICT REPLACE` for the most recent run only. Never delete rows — the history sequence is the whole point.

---

## 6. Compute Engine

**Module:** `tools/cointegration_screen.py`
**Helper:** `tools/cointegration_db.py` (mirrors `tools/ledger_db.py` API subset)

### 6a. Universe & combinations

Universe = `tools/factors/fx_correlation_matrix.py::FX_UNIVERSE` (18 symbols). Pairs are unordered (153 combos). Naming: alphabetically sorted, matching the existing correlation matrix convention.

### 6b. Cadence

- **Trigger:** chained off the existing **DATA_INGRESS daily pipeline** (`AntiGravity_Daily_Preflight` task at 00:15 UTC). After `daily_pipeline.py` completes successfully (`$exitCode -eq 0`), the wrapper `invoke_daily_pipeline.ps1` calls `python tools/cointegration_daily_runner.py` as a non-blocking post-step (same pattern as the existing NEWS_CALENDAR health check). Skipped on data-update failure to avoid computing against stale/partial data. **No standalone Windows Task** — chained execution eliminates duplication and guarantees fresh-data ordering. **Architectural correction logged 2026-05-20.**
- **Run duration target:** < 5 minutes per full pass (typical: ~3 seconds — Phase 1 compute dominates).
- **Recompute on demand:** CLI flag `--as-of YYYY-MM-DD` re-runs for a historical date (parquet overwritten, SQLite upserts on conflict).
- **Manual re-run:** `python tools/cointegration_daily_runner.py` from any session — does not require the data update to have run today.

### 6c. Per-pair compute

For each (pair_a, pair_b) and each lookback ∈ {252, 504}:

1. Load daily closes via `_load_native_closes(symbol, tf="1d", start, end)` (the existing loader, lifted out of `fx_correlation_matrix.py` into a shared utility).
2. Take last `lookback` bars. Drop NaN rows (record drop count in `sample_size`).
3. Regress `B = α + β·A + ε` (statsmodels `OLS`).
4. Compute spread = `B − β·A`.
5. ADF test on spread (`statsmodels.tsa.stattools.adfuller`, maxlag = floor((N−1)/3), AIC).
6. Half-life: OU fit via regression of `Δspread_t` on `spread_{t−1}`; half-life = `−ln(2) / λ` where λ is the coefficient. NaN if λ ≥ 0 (non-mean-reverting).
7. Spread z-score = `(spread_t − mean(spread)) / std(spread)`.
8. Apply regime classifier (§7).
9. Append row to results DataFrame.

### 6d. Data version

`data_version` = SHA-256 of `(start_date, end_date, [csv_file_modtime_unix per symbol])` truncated to first 12 chars. Captures input identity so we can detect silent historical rewrites.

---

## 7. Regime Definitions

Three-state classifier applied at write time. Inputs: current `adf_pvalue`, prior 5 daily snapshots from SQLite.

| Regime | Condition |
|---|---|
| `cointegrated` | current `adf_pvalue` < 0.05 AND ≥ 4 of last 5 snapshots also < 0.05 |
| `breaking` | current `adf_pvalue` in [0.05, 0.10) OR (< 0.05 but last 5 were all ≥ 0.10) |
| `broken` | current `adf_pvalue` ≥ 0.10 |

**Bootstrap exception:** if fewer than 5 prior snapshots exist in SQLite, classify on current p-value alone (`<0.05 → cointegrated`, `[0.05, 0.10) → breaking`, `≥0.10 → broken`).

**Why this not "just p-value":** a single-day p-value crossing is too noisy to act on. The hysteresis prevents flip-flopping between `cointegrated` and `breaking` on day-to-day p-value jitter.

---

## 8. Ranking Formula

**FROZEN doctrine:** *do NOT rank by lowest p-value.* With 16 years × 153 pairs you will find dozens of spuriously significant pairs by chance, and ranking by p-value selects exactly those — the project would silently become data-mined spread fitting.

**v1 ranking score** (computed at Excel-export time, not stored in DB):

```
score = stability_persistence × half_life_quality × excursion_containment

stability_persistence  = fraction of last 90 days in regime "cointegrated"          ∈ [0, 1]
half_life_quality      = exp(−|log(half_life_days / 15)|)                            ∈ (0, 1]
                         (peaks at 15 days; falls off below 3 or above 60)
excursion_containment  = fraction of last 252 days with |spread_zscore| ≤ 3.0       ∈ [0, 1]
```

Each component capped at 1.0. NaN inputs → component = 0 (score → 0).

**Interpretation:**
- `stability_persistence` rewards relationships that *stayed* cointegrated, not ones that briefly tested significant.
- `half_life_quality` rewards mean-reversion speeds in the operational sweet spot (3–60 days); too fast = noise, too slow = capital locked.
- `excursion_containment` rewards pairs that haven't blown through ±3σ recently — directly addresses the 90-series Martingale-tail-risk failure mode.

Pairs are sorted descending by `score` in the Excel "Today" sheet. Reported alongside `score` are its three components so the operator can see *why* a pair ranked where it did.

---

## 9. Excel Report Layout

**Output:** `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/Cointegration_Screener.xlsx`
**Formatter profile:** new entry `"cointegration"` in `tools/excel_format/rules.py`.
**Regeneration:** `python tools/cointegration_db.py --export` (mirrors `tools/ledger_db.py --export-mps`).

### Sheet 1: `Summary` (operator's universe-level view — added per architectural review 2026-05-20)

Aggregate metrics across all 153 pairs, regenerated each run. Sections:

1. **Universe regime distribution** — 2×3 table (rows: 252d / 504d; cols: cointegrated / breaking / broken). Conditional fill on cell magnitude.
2. **Half-life summary** — median / mean / min / max half-life in the cointegrated subset, per window.
3. **Top recurring currencies in cointegrated pairs** — counts how often each currency appears as a leg in cointegrated pair-pairs (252d only). Flags pairs that share USD exposure are over-represented vs cross-currency cointegration.
4. **Window agreement** — 4-bucket count: `BOTH` (both windows cointegrated, strongest) · `252-only` (recent formation, possibly false-positive — flag for caution) · `504-only` (degrading) · `NEITHER` (broken everywhere).
5. **Regime changes vs prior snapshot** — pairs newly broken (was cointegrated yesterday → broken today) + pairs newly recovered. Empty until 2+ daily runs exist.
6. **Bootstrap visibility** — count of rows with `history_depth < HYSTERESIS_LOOKBACK` vs ≥, plus the calendar date when proper hysteresis activates universe-wide. Important so the operator never mistakes "first observation" for "persistent cointegration".

### Sheet 2: `Today` (pair-level — pivoted by window per architectural review)

One row per **(pair_a, pair_b)** — windows pivoted to columns so 252d vs 504d are visually adjacent. 153 rows max.

Columns: `pair_a · pair_b · agreement · regime_252 · regime_504 · adf_pvalue_252 · adf_pvalue_504 · half_life_days_252 · half_life_days_504 · current_zscore_252 · current_zscore_504 · hedge_ratio_252 · hedge_ratio_504 · history_depth · score`.

`agreement` column (single-glance regime-divergence flag):
- `BOTH` — both windows cointegrated (strongest signal)
- `252-only` — only short window cointegrated (recent formation; possibly unstable; operator must verify before acting)
- `504-only` — only long window cointegrated (relationship degrading)
- `NEITHER` — neither window cointegrated

**Raw values stay visible** alongside the composite `score` (doctrine: ranking helps sorting, never replaces diagnostics — operators eventually distrust black-box composites).

Conditional formatting:
- `regime_*` cells: green = `cointegrated`, yellow = `breaking`, red = `broken`
- `agreement`: green = `BOTH`, yellow = `252-only` or `504-only`, red = `NEITHER`
- `half_life_days_*`: green 5-30, yellow 30-60 or 3-5, red <3 or >60 or NaN
- `current_zscore_*`: yellow `|z| ≥ 2.0`, red `|z| ≥ 3.0`
- `history_depth` < `HYSTERESIS_LOOKBACK`: yellow background flag — bootstrap classifier active for that row

### Sheet 3: `History`

One row per (pair_a, pair_b, lookback, as_of) for the last 90 days. Used to see regime transitions over time.

Filter recommendation written into the sheet's frozen header: "Filter `regime` ≠ `cointegrated` to see recent breakage events."

### Sheet 4: `Notes`

Auto-generated via `excel_format/notes.py` (existing pattern). Documents the ranking formula, regime definitions, and the "don't rank by p-value" warning so operators encountering the file standalone understand it.

---

## 10. Scheduled-Task Identity Model

**The single most important pre-coding step.**

`MASTER_DATA` has an ACL `DENY INTERACTIVE` (confirmed during investigation — interactive PowerShell/CMD cannot list it; only Python invoked through the scheduled task identity can read it via `SeBackupPrivilege`). This is the same mechanism that `backup_repos.ps1` and the existing daily pipeline jobs depend on.

### Phase 0 — Identity Smoke Test (MUST pass before any compute code lands)

Procedure mandated by CLAUDE.md "Service-Account Migration Safety" section:

```powershell
powershell -File tools\scheduled_task_identity_smoke.ps1 `
    -Mode validate `
    -ExpectedUser   '<service-account>' `
    -RequiredGroup  'BATCH' `
    -ForbiddenGroup 'INTERACTIVE' `
    -TargetDir      'C:\Users\faraw\Documents\Anti_Gravity_DATA_ROOT\MASTER_DATA\EURUSD_OCTAFX_MASTER\RESEARCH' `
    -LogonType      'Password'
```

Must exit `0`. Non-zero exit codes (101–107) block proceeding — no interpretation, no override.

### Phase 0a — End-to-end dry-run cycle

A minimal probe script invoked under the same scheduled-task identity must successfully:
1. Read one year-file from each of the 18 symbols' RESEARCH dirs (read access).
2. Write a 1-row dummy parquet to `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/_smoke.parquet` (write access).
3. Open `DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/cointegration.db` (creating if absent), upsert 1 row, query it back (SQLite access).
4. Delete the dummy parquet and the dummy SQLite row.
5. Exit 0.

This proves the production execution context can complete one full I/O cycle end-to-end. **No compute development begins until this passes.**

### Task XML pattern

Follow `launch-windows-supervised-task` skill (per memory). LogonType most likely `Password` or `S4U` (TBD by smoke test); `RunLevel=Highest` for SeBackupPrivilege; UTF-16 BOM XML; PYTHONPATH self-bootstrap so the task survives venv detachment.

---

## 11. Failure Handling

| Failure | Behavior |
|---|---|
| MASTER_DATA read denied | Fail-fast; do NOT write parquet/SQLite; emit `[FAIL] ACL` to log; non-zero exit so Task Scheduler shows failure. |
| ADF raises (e.g. constant series) | Log warning; row written with `adf_pvalue=1.0`, `regime="broken"`, `half_life_days=NaN`. Run continues. |
| Half-life computation fails | `half_life_days=NaN`, `half_life_quality=0` in ranking. Run continues. |
| SQLite locked (concurrent reader) | Retry 5× with 2s backoff; if still locked, log warning and skip SQLite write — parquet still produced (parquet is source of truth, SQLite can be re-derived). |
| Excel locked (open in user's TV/Excel) | Skip Excel regeneration; log warning; next run will catch up. |
| Data freshness check fails (`freshness_index.json` shows stale latest year file) | Fail-fast with explicit reference to DATA_INGRESS recovery procedure. |
| Schema drift (parquet read finds unexpected column) | Fail-fast; do not write. Schema is FROZEN — additions require spec bump. |

**No silent partial successes.** Either the full 306-row write completes, or the run is marked failed and the previous snapshot stands.

---

## 12. Implementation Phases

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Identity smoke test passes (§10) | exit 0 from `scheduled_task_identity_smoke.ps1` |
| 0a | End-to-end I/O dry-run passes (§10) | dummy parquet write + dummy SQLite roundtrip |
| 1 | `tools/cointegration_screen.py` compute → parquet | unit test: compute against fixed inputs produces byte-identical parquet (modulo `generated_at`) |
| 2 | `tools/cointegration_db.py` parquet → SQLite upsert | unit test: parquet→DB→DataFrame roundtrip preserves all columns |
| 3 | `tools/excel_format/rules.py` adds `"cointegration"` profile + CLI hook | manual verify: Excel opens with conditional formatting visible |
| 4 | Windows Task XML registered via `launch-windows-supervised-task` | 7 consecutive successful nightly runs (1 week of supervised observation) before declaring v1 stable |

Phases 1–3 are pure code under non-protected paths; phase 4 touches the supervised-task launcher infrastructure and follows that skill's protocol.

---

## 13. Out of Scope for v1 (explicit, to prevent scope creep)

- Johansen multi-asset cointegration
- Kalman / rolling-OLS hedge ratios
- Intraday cadence
- XAU/XAG/index/crypto symbols
- Live alerting (Pine indicator, email, Slack)
- Auto-trading / execution coupling — Trade_Scan has no execution authority and this stays research-only
- A "today's tradable spreads" promotion path into the existing PORTFOLIO_COMPLETE pipeline — that's a separate decision after we have 90 days of clean v1 history to evaluate

---

## 14. Open Questions (logged but non-blocking)

1. **Stationarity-test scaling.** ADF assumes mean-reverting AR(1). Real FX spreads sometimes need detrending first (cointegration with drift). v1 uses no detrending; revisit if `excursion_containment` shows systematically low values across the whole universe.
2. **Window-length stress test.** v1 hardcodes {252, 504}. Should be tested whether {126, 252, 504, 1008} (6m, 1y, 2y, 4y) is more informative; deferred to v1.1 when we have actual operational experience.
3. **Excel regeneration trigger.** v1 regenerates Excel as part of every daily run. If file-lock collisions with the user opening it become common, switch to on-demand-only via the existing `format_excel_artifact.py` CLI.
4. **Smoothed regime classifier (empirical decision).** ADF p-values are noisy near the 0.05 / 0.10 thresholds; the 5-day hysteresis in §7 mitigates single-day jitter but does not eliminate sustained oscillation in the boundary zone. v1 writes `pvalue_rolling_median_5d` as an observability-only column (§5). After 90 days of operational data, compare `adf_pvalue`-driven regimes vs hypothetical `pvalue_rolling_median_5d`-driven regimes; if they diverge during real boundary-zone events, swap the classifier in v1.1 with constants tuned to actual observed behavior. If they track tightly, the current classifier stands. Decision deferred deliberately — tuning the smoother without operational data is speculation.

---

## Sign-off

This spec is FROZEN at the level of:
- dataflow shape
- two-store architecture (parquet = source of truth, SQLite = reporting sink)
- schema columns (additions require spec bump)
- ranking doctrine (composite score, never raw p-value)
- pre-code identity smoke test requirement

Iteration is welcome on: ranking formula constants (the `15` in half-life quality, the `3.0` z-score threshold), regime hysteresis thresholds, Excel conditional-format colors — these are tunable and don't require spec changes.

End of v1 specification.
