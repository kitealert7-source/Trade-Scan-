# News Calendar Ingestion Pipeline — Architecture-Aligned Design Plan

**Status:** PLAN ONLY — NO CODE  
**Date:** 2026-04-11  
**Scope:** DATA_INGRESS pipeline extension for economic news calendar data

---

## 1. Summary of Existing Ingestion Architecture (Observed)

The DATA_INGRESS pipeline follows a strict 5-phase lifecycle for instrument price data:

| Phase | Module | Purpose |
|-------|--------|---------|
| RAW | `raw_update_sop17.py` | Immutable append-only ingestion; tail-buffer merge; atomic `os.replace()` |
| CLEAN | `clean_rebuild_sop17.py` | Dedup, UTC-naive normalization, monotonic sort, structural validation |
| RESEARCH | `rebuild_research_sop17.py` | Lineage-tracked derivation with SHA256 hash registry (`_lineage.json`) |
| SYSTEM_FACTORS | `build_usd_synth.py`, `build_jpy_synth.py` | Derived cross-instrument factors; flat structure (no RAW/CLEAN/RESEARCH) |
| Governance | `daily_pipeline.py` | Orchestrator; `last_successful_daily_run.json` written only on full success |

**Key conventions observed:**

- **Path authority:** `config/path_config.py` — all paths derived from `Path(__file__).resolve()`
- **File naming:** `{ASSET}_{FEED}_{TIMEFRAME}_{YEAR}_{TYPE}.csv` (e.g., `XAUUSD_OCTAFX_15m_2021_RESEARCH.csv`)
- **Directory structure:** `MASTER_DATA/{ASSET}_{FEED}_MASTER/{RAW,CLEAN,RESEARCH}/`
- **Manifest files:** `{filename}_manifest.json` — SHA256, row count, first/last timestamps, schema version
- **Lineage files:** `{filename}_lineage.json` — CLEAN → RESEARCH hash provenance
- **SYSTEM_FACTORS:** Flat output directory (`metadata.json` + `README.md` + output CSVs), source hash tracking in `metadata.json.source_data_hashes`
- **Timestamp convention:** All RESEARCH-layer data is UTC-naive (timezone stripped after conversion)
- **Validation:** `dataset_validator_sop17.py` — structural validation at each transition
- **Atomicity:** `os.replace()` for RAW updates; `.fsync()` for disk guarantees

---

## 2. Architectural Classification: Where Does News Data Fit?

### The tension

News calendar data is **none** of:
- Instrument price data (MASTER_DATA) — it has no OHLCV schema, no per-instrument identity
- Derived-from-MASTER_DATA (SYSTEM_FACTORS) — it's sourced externally, not computed from price data

### Resolution: EXTERNAL_DATA — a new peer of MASTER_DATA and SYSTEM_FACTORS

**Justification:**
- MASTER_DATA is structurally coupled to `{ASSET}_{FEED}_MASTER` naming and OHLCV schema
- SYSTEM_FACTORS is for *derived* data computed from RESEARCH-layer prices; news data is *sourced* externally
- News data has its own ingestion lifecycle (download → normalize → validate) that maps cleanly to RAW → CLEAN → RESEARCH, but with different schemas at each layer
- Creating `EXTERNAL_DATA/` as a peer directory follows the established pattern of top-level data categories while keeping the RAW/CLEAN/RESEARCH lifecycle that the system enforces

**Precedent:** The system already has two top-level categories (MASTER_DATA, SYSTEM_FACTORS). A third for externally-sourced non-price data is a minimal, justified extension.

---

## 3. Proposed Directory Structure

```
Anti_Gravity_DATA_ROOT/
├── MASTER_DATA/                          # existing — unchanged
├── SYSTEM_FACTORS/                       # existing — unchanged
└── EXTERNAL_DATA/
    └── NEWS_CALENDAR/
        ├── RAW/
        │   ├── FOREXFACTORY_2024.csv
        │   ├── FOREXFACTORY_2025.csv
        │   ├── FOREXFACTORY_2026.csv
        │   └── ...
        ├── CLEAN/
        │   ├── NEWS_CALENDAR_2024_CLEAN.csv
        │   ├── NEWS_CALENDAR_2024_CLEAN.csv_manifest.json
        │   ├── NEWS_CALENDAR_2025_CLEAN.csv
        │   ├── NEWS_CALENDAR_2025_CLEAN.csv_manifest.json
        │   └── ...
        ├── RESEARCH/
        │   ├── NEWS_CALENDAR_2024_RESEARCH.csv
        │   ├── NEWS_CALENDAR_2024_RESEARCH.csv_manifest.json
        │   ├── NEWS_CALENDAR_2024_RESEARCH.csv_lineage.json
        │   ├── NEWS_CALENDAR_2025_RESEARCH.csv
        │   └── ...
        ├── metadata.json
        └── README.md
```

**Symlink in Trade_Scan** (following existing pattern):
```
Trade_Scan/data_root/EXTERNAL_DATA → ../Anti_Gravity_DATA_ROOT/EXTERNAL_DATA
```

---

## 4. File Naming Strategy

| Layer | Pattern | Example |
|-------|---------|---------|
| RAW | `{SOURCE}_{YEAR}.csv` | `FOREXFACTORY_2025.csv` |
| CLEAN | `NEWS_CALENDAR_{YEAR}_CLEAN.csv` | `NEWS_CALENDAR_2025_CLEAN.csv` |
| RESEARCH | `NEWS_CALENDAR_{YEAR}_RESEARCH.csv` | `NEWS_CALENDAR_2025_RESEARCH.csv` |

**Rationale:**
- RAW preserves source identity (`FOREXFACTORY`) — if a second source is added later, files coexist without collision
- CLEAN/RESEARCH use source-agnostic `NEWS_CALENDAR` because the CLEAN layer merges and deduplicates across sources
- Year partitioning matches MASTER_DATA convention and keeps files manageable (~1000-2000 events/year)
- Manifest and lineage files follow existing `{filename}_manifest.json` / `{filename}_lineage.json` convention

---

## 5. Data Flow: Download → RAW → CLEAN → RESEARCH

### Phase 1: RAW Ingestion

**Input:** Manually downloaded ForexFactory CSV exports (placed in a staging area)  
**Output:** `RAW/{SOURCE}_{YEAR}.csv` — byte-for-byte copy of source file

**Rules (aligned with `raw_update_sop17.py`):**
- RAW files are **immutable once written** — no in-place edits
- New data for same year → full file replacement via atomic `os.replace()`
- No schema transformation at RAW layer — preserve original column names, encoding, quirks
- Each RAW write logs: source filename, SHA256 hash, row count, timestamp

**Deviation from MASTER_DATA pattern:** No tail-buffer merge. MASTER_DATA appends new bars to existing files; news calendars are downloaded as complete year files and replaced atomically. This is simpler and appropriate — calendar events don't stream in real-time.

### Phase 2: CLEAN Rebuild

**Input:** All `RAW/*.csv` files  
**Output:** `CLEAN/NEWS_CALENDAR_{YEAR}_CLEAN.csv` + manifest

**Transformations (aligned with `clean_rebuild_sop17.py`):**
1. **Column normalization:** Map source-specific columns to canonical schema (see Section 6)
2. **Timestamp normalization:** Parse Date+Time from US/Eastern → localize → convert to UTC → strip timezone (UTC-naive, matching MASTER_DATA CLEAN convention)
3. **DST safety:** `ambiguous='NaT'`, `nonexistent='NaT'` — drop unparseable rows, log count
4. **Unusable rows:** Drop "All Day", "Tentative", blank Time values
5. **Date forward-fill:** ForexFactory leaves Date blank for same-day events
6. **Impact normalization:** Strip whitespace, capitalize → enforce `{High, Medium, Low}`
7. **Currency normalization:** Strip whitespace, uppercase
8. **Deduplication:** Drop exact duplicates on `(datetime_utc, Currency, Event)`, keep first
9. **Sort:** Ascending by `datetime_utc`
10. **Year partitioning:** Split into per-year output files

**Manifest (`_manifest.json`):**
```json
{
  "sha256": "...",
  "row_count": 487,
  "first_event": "2025-01-02T13:30:00",
  "last_event": "2025-12-31T21:00:00",
  "schema_version": "1.0",
  "impact_distribution": {"High": 152, "Medium": 201, "Low": 134},
  "currencies": ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"],
  "source_files": ["FOREXFACTORY_2025.csv"],
  "rebuild_timestamp": "2026-04-11T12:00:00Z"
}
```

### Phase 3: RESEARCH Rebuild

**Input:** `CLEAN/NEWS_CALENDAR_{YEAR}_CLEAN.csv`  
**Output:** `RESEARCH/NEWS_CALENDAR_{YEAR}_RESEARCH.csv` + manifest + lineage

**Transformations:**
1. **Pass-through with lineage:** For news data, RESEARCH = CLEAN + lineage tracking (no additional derivation needed — the CLEAN layer already produces the canonical schema)
2. **Lineage file:** SHA256 of source CLEAN file, rebuild timestamp, module version

**Why not skip RESEARCH?** Consistency. Every consumer in Trade_Scan reads from `RESEARCH/`. The report module (`tools/news_calendar.py`) should point at RESEARCH, maintaining the invariant that research code never reads RAW or CLEAN directly.

**Lineage (`_lineage.json`):**
```json
{
  "source_file": "NEWS_CALENDAR_2025_CLEAN.csv",
  "source_hash": "sha256:...",
  "rebuild_module": "build_news_calendar.py",
  "rebuild_version": "1.0",
  "rebuild_timestamp": "2026-04-11T12:00:00Z"
}
```

### Phase 4: metadata.json

**Written after successful RESEARCH rebuild.** Follows SYSTEM_FACTORS pattern:

```json
{
  "name": "NEWS_CALENDAR",
  "version": "NEWS_CALENDAR_v1.0",
  "source": "ForexFactory",
  "timezone_input": "US/Eastern",
  "timezone_output": "UTC (naive)",
  "impact_levels": ["High", "Medium", "Low"],
  "source_data_hashes": {
    "NEWS_CALENDAR_2024_RESEARCH.csv": "sha256:...",
    "NEWS_CALENDAR_2025_RESEARCH.csv": "sha256:...",
    "NEWS_CALENDAR_2026_RESEARCH.csv": "sha256:..."
  },
  "creation_timestamp": "2026-04-11T12:00:00Z",
  "validation_stats": {
    "total_events": 3200,
    "year_range": "2024-2026",
    "currencies_covered": 8
  }
}
```

---

## 6. Schema Definitions

### RAW Layer (source-native — ForexFactory format)

Preserved as-is. Typical ForexFactory columns:
```
Date, Time, Currency, Impact, Event, Actual, Forecast, Previous
```

No transformation. No guarantees on data quality. This is the "receipt."

### CLEAN Layer (canonical schema)

```
datetime_utc     | datetime64[ns]  | UTC-naive timestamp (timezone stripped)
Currency         | str             | 3-letter ISO (USD, EUR, GBP, ...)
Impact           | str             | High / Medium / Low
Event            | str             | Event name (e.g., "Non-Farm Payrolls")
Actual           | str (nullable)  | Reported value (kept as string — mixed formats)
Forecast         | str (nullable)  | Consensus forecast
Previous         | str (nullable)  | Prior period value
```

**Design note:** `Actual`, `Forecast`, `Previous` are kept as strings because ForexFactory uses mixed formats (percentages, raw numbers, "K"/"M" suffixes). Parsing these is a downstream concern, not a CLEAN-layer responsibility.

### RESEARCH Layer (identical to CLEAN)

Same schema. The RESEARCH layer adds lineage tracking, not schema changes. This is consistent with how SYSTEM_FACTORS treats simple derived data.

---

## 7. Reuse Opportunities

| Existing Module | Reuse For |
|-----------------|-----------|
| `config/path_config.py` | Add `EXTERNAL_DATA` and `NEWS_CALENDAR` path constants |
| `dataset_validator_sop17.py` | Extend with news-specific validation rules (column presence, Impact enum, UTC range) |
| `compute_file_hash()` from `build_usd_synth.py` | SHA256 manifest/lineage hashing — identical pattern |
| `daily_pipeline.py` | Add news calendar rebuild as optional phase (after SYSTEM_FACTORS, before governance write) |
| `tools/news_calendar.py` (Trade_Scan) | Update path from `data_root/news_calendar/` → `data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/` — remove all timestamp normalization (already done at CLEAN layer) |

### What gets simpler in `tools/news_calendar.py` after this:

The existing `_normalize_timestamps()` function (lines 92-154) becomes unnecessary — RESEARCH-layer data is already UTC-naive with canonical columns. The loader reduces to: read CSVs → parse `datetime_utc` → validate → build windows.

---

## 8. Deviations from Existing System (Justified)

| Deviation | Existing Pattern | News Calendar | Justification |
|-----------|-----------------|---------------|---------------|
| Top-level directory | `MASTER_DATA/`, `SYSTEM_FACTORS/` | `EXTERNAL_DATA/` | News data is neither instrument prices nor derived from them |
| RAW update strategy | Tail-buffer merge (streaming bars) | Full file atomic replace | Calendar data comes as complete year exports, not streaming |
| RESEARCH = CLEAN | RESEARCH adds execution model columns | RESEARCH = CLEAN + lineage only | No additional derivation needed; layer exists for consumer convention + lineage |
| No `{ASSET}_{FEED}_MASTER` naming | All MASTER_DATA uses this | `NEWS_CALENDAR/` | News data is cross-asset (events belong to currencies, not trading instruments) |
| Year partitioning by event date | Year from filename/data range | Year from `datetime_utc` | Events belong to the year they occur in, not the year of the source file |

---

## 9. Risks and Edge Cases

### Data quality risks
- **ForexFactory format changes:** Column names or order may change between exports. CLEAN layer must detect and reject schema mismatches rather than silently producing corrupt data.
- **Duplicate events across year boundaries:** A December export might include early January events. Year-partitioning at CLEAN must handle this without duplicating events.
- **Missing or ambiguous timestamps:** Some events have "Tentative" or "All Day" times. These are dropped at CLEAN (already implemented in current `news_calendar.py`).

### DST edge cases
- **Spring forward:** 2:00 AM EST → 3:00 AM EDT. An event at 2:30 AM doesn't exist. `nonexistent='NaT'` drops it.
- **Fall back:** 1:00 AM EDT → 1:00 AM EST. An event at 1:30 AM is ambiguous. `ambiguous='NaT'` drops it.
- **Impact:** These affect ~2-4 events per year at most. Acceptable loss vs. incorrect timestamps.

### Operational risks
- **Manual download dependency:** ForexFactory doesn't offer an API. RAW ingestion depends on human-downloaded exports. Document the expected source format and placement directory.
- **Stale data:** No automatic freshness detection (unlike MASTER_DATA which has MT5 delta fetch). Mitigation: `metadata.json.creation_timestamp` + governance log entry.
- **Year boundary during rebuild:** If a rebuild runs mid-year, the current year's file is partial. This is expected and correct — the manifest records `last_event` to make this visible.

### Consumer migration risk
- **`tools/news_calendar.py` path change:** Currently reads from `data_root/news_calendar/`. After migration, reads from `data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/`. This is a one-line path change + removal of now-redundant normalization code. The consumer API (`load_news_calendar()`) stays identical.

---

## 10. Implementation Sequence (When Approved)

1. **DATA_INGRESS:** Add `EXTERNAL_DATA` / `NEWS_CALENDAR` to `config/path_config.py`
2. **Anti_Gravity_DATA_ROOT:** Create `EXTERNAL_DATA/NEWS_CALENDAR/{RAW,CLEAN,RESEARCH}/` directories
3. **DATA_INGRESS:** Write `engines/ops/build_news_calendar.py` — RAW → CLEAN → RESEARCH pipeline
4. **DATA_INGRESS:** Wire into `daily_pipeline.py` as optional phase
5. **Anti_Gravity_DATA_ROOT:** Place initial ForexFactory exports into `RAW/`
6. **DATA_INGRESS:** Run pipeline, verify CLEAN + RESEARCH output + manifests + lineage
7. **Trade_Scan:** Create symlink `data_root/EXTERNAL_DATA` → `../Anti_Gravity_DATA_ROOT/EXTERNAL_DATA`
8. **Trade_Scan:** Update `tools/news_calendar.py` — new path, remove `_normalize_timestamps()` complexity
9. **Trade_Scan:** Run `tests/test_news_policy.py` — verify all 52 tests still pass
10. **Cleanup:** Remove `data_root/news_calendar/` (old ad-hoc path) after confirming migration

---

## 11. System Alignment Verification

### 11.1 RAW Immutability / Versioning

**What the current system does:**

`raw_update_sop17.py` uses an **append-via-tail-merge** strategy, NOT true immutability:

1. New data is fetched from MT5/Delta APIs
2. The existing file's tail (last N bars) is read into memory
3. New data is merged with the tail, deduplicated on `time`, sorted
4. The result is written to `{file}.tmp`
5. `SOP17Validator.validate_raw_extended()` validates the `.tmp` file
6. On PASS: `os.replace(tmp, filepath)` — atomic commit
7. On FAIL: `.tmp` is deleted, original untouched (rollback)
8. Post-commit: SHA256 is verified (`_pre_commit_hash` vs `_post_commit_hash`); checksum mismatch → file quarantined to `.corrupt`
9. `_write_raw_manifest()` emits `{file}_manifest.json` with `sha256`, `row_count`, `first_timestamp`, `last_timestamp`, `schema_version`, `columns`, `interval_seconds`

RAW files are therefore **replaceable** (not append-only in the filesystem sense), but replacements are controlled via atomic `os.replace()` with pre/post checksum verification and quarantine on mismatch.

**Whether it already solves the concern:**

Partially. The atomic replace + checksum + quarantine pattern protects against corruption. But the tail-merge strategy is specific to streaming OHLCV data and doesn't apply to news calendar data (which arrives as complete year files, not incremental bar streams).

**What the news pipeline should do: ADAPT (justified)**

- **Reuse:** Atomic `os.replace()` commit pattern, pre/post SHA256 verification, quarantine on mismatch, `_write_raw_manifest()` structure
- **Adapt:** Skip tail-buffer merge entirely. News RAW ingestion is a simple "place file → validate → write manifest" operation. The source file IS the RAW artifact. Replacement of an existing year file (e.g., updated ForexFactory export) uses the same atomic `os.replace()` pattern with the same checksum guard.
- **Reuse:** `log_integrity_event()` from `raw_update_sop17.py` for RAW replacement logging to `state/integrity_events.log` (append-only JSONL)
- **Override:** No `validate_timeframe_delta()` call — news data has no OHLCV interval to validate. This guard is structurally inapplicable.

**RAW manifest format for news (aligned with existing):**

```json
{
  "schema_version": "1.0.0",
  "source": "FOREXFACTORY",
  "year": 2025,
  "row_count": 1847,
  "first_timestamp": null,
  "last_timestamp": null,
  "raw_time_range_hint": "Date column only (unparsed, US/Eastern)",
  "columns": ["Date", "Time", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"],
  "sha256": "...",
  "generated_utc": "2026-04-11T12:00:00Z"
}
```

Note: `first_timestamp` and `last_timestamp` are null at RAW layer because timestamps haven't been parsed yet (source format is Date+Time in US/Eastern, not a single parseable column). `raw_time_range_hint` records the unparsed format for debugging without breaking layer purity. Both fields become populated with proper UTC values at CLEAN layer.

---

### 11.2 Deduplication Policy

**What the current system does:**

CLEAN dedup in `clean_rebuild_sop17.py` (`apply_clean_logic`, line 361):

```python
df_dedup = df_dedup.drop_duplicates(subset=['time'], keep='first')
```

Single key: `time`. This is correct for OHLCV data where each timestamp has exactly one bar.

RESEARCH dedup in `rebuild_research_sop17.py` (line 523/545):

```python
combined = combined.drop_duplicates(subset=['time'], keep='last')
```

Also single key `time`, but `keep='last'` to prefer the newly-computed RESEARCH row over the existing one.

**Whether it already solves the concern:**

No. The existing dedup key (`time` alone) is structurally specific to OHLCV data. News data has **multiple events at the same timestamp** — different currencies, different events. A `time`-only dedup would destroy data.

**What the news pipeline should do: EXTEND (justified)**

- **Dedup key:** `(datetime_utc, Currency, Event)` — this is the natural composite key for news events. Two events can occur at the same time for different currencies, and two events can occur for the same currency at different times. All three fields are needed.
- **Keep strategy:** `keep='first'` at CLEAN layer (matching existing CLEAN convention). If a source file contains true duplicates, the first occurrence wins.
- **Why not include Impact:** Impact is an attribute of the event, not an identifier. The same event (e.g., "Non-Farm Payrolls" for USD at 13:30 UTC) should appear once regardless of how its impact is classified.
- **Conflict resolution:** If conflicting Impact values exist for identical `(datetime_utc, Currency, Event)`, the first occurrence is retained deterministically (`keep='first'`). This can happen when a source revises an event's impact classification between exports. The collapsed row's Impact reflects the earlier export's assessment. This is an acceptable tradeoff — impact revisions are rare (~1-2/year), and the alternative (including Impact in the key) would create duplicate event rows that break downstream window construction.
- **Cross-file dedup:** When multiple RAW source files cover overlapping periods, dedup at CLEAN ensures no event appears twice in the output. This matches the existing CLEAN role as the "single source of truth" layer.

**Alignment:** The dedup *pattern* (single `drop_duplicates` call at CLEAN layer) is reused identically. Only the `subset` parameter changes. This is not new logic — it's a parameterization of existing logic.

---

### 11.3 Hash / Manifest / Lineage Policies

**What the current system does:**

Three distinct hash/manifest mechanisms exist:

**A. RAW manifest** (`_write_raw_manifest` in `raw_update_sop17.py`):
```python
manifest = {
    "schema_version": "1.0.0",
    "symbol": asset, "feed": feed, "timeframe": timeframe, "year": int(year),
    "row_count": len(df),
    "first_timestamp": str(df['time'].iloc[0])[:19],
    "last_timestamp": str(df['time'].iloc[-1])[:19],
    "columns": list(df.columns),
    "interval_seconds": interval_seconds,
    "sha256": compute_file_sha256(filepath),
    "generated_utc": datetime.now(timezone.utc).isoformat()
}
```
Written atomically via `.tmp` + `os.replace()`.

**B. CLEAN manifest** (`_write_clean_manifest_dvg` in `clean_rebuild_sop17.py`):
Uses `DatasetVersionGovernor.generate_clean_manifest()` + extends with RAW linkage fields:
```python
manifest["raw_sha256"] = raw_m.get("sha256")
manifest["raw_row_count"] = raw_m.get("row_count")
manifest["raw_first_timestamp"] = raw_m.get("first_timestamp")
manifest["raw_last_timestamp"] = raw_m.get("last_timestamp")
```
This enables **staleness detection**: `_check_raw_staleness()` compares RAW manifest against CLEAN manifest's recorded RAW state. If they diverge → CLEAN is stale → force rebuild.

**C. RESEARCH manifest** (`_write_research_manifest` in `rebuild_research_sop17.py`):
```python
manifest = {
    "clean_sha256": clean_sha,
    "clean_row_count": clean_row_count,
    "research_sha256": compute_file_sha256(research_path),
    "generated_utc": datetime.datetime.utcnow().isoformat() + "Z"
}
```
Same staleness pattern: `_check_clean_staleness()` compares CLEAN manifest against RESEARCH manifest. Divergence → RESEARCH rebuild.

**D. Pipeline hash registry** (`metadata/pipeline_hash_registry.json`):
Global registry tracking `(clean_basename + execution_model_version)` → `{clean_sha256, research_sha256, dataset_version}`. Enforces that re-derivation from the same CLEAN input produces the same RESEARCH output. Violations raise `RuntimeError`.

**E. SHA256 computation** (`compute_file_sha256` — duplicated across all three core modules):
```python
def compute_file_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for line in f:
            if not line.startswith(b'#'):
                h.update(line)
    return h.hexdigest()
```
Skips `#` comment lines (RESEARCH files have comment headers). This is consistent across all modules.

**Whether it already solves the concern:**

Yes — the staleness detection chain (RAW manifest → CLEAN manifest → RESEARCH manifest) already provides end-to-end lineage. If RAW changes, CLEAN is rebuilt; if CLEAN changes, RESEARCH is rebuilt. No manual tracking required.

**What the news pipeline should do: REUSE entirely**

- **`compute_file_sha256()`:** Import from existing module (or factor into shared utility). Do NOT reimplement.
- **RAW manifest:** Write using same structure, adapted fields (see 11.1). Atomic `.tmp` + `os.replace()`.
- **CLEAN manifest:** Write with RAW linkage fields. Enables `_check_raw_staleness()` pattern.
- **RESEARCH manifest:** Write with CLEAN linkage fields. Enables `_check_clean_staleness()` pattern.
- **Staleness detection:** Reuse `_check_raw_staleness()` and `_check_clean_staleness()` logic directly. News pipeline benefits from automatic rebuild triggering when upstream data changes.
- **Pipeline hash registry:** NOT needed for news data. The registry exists because RESEARCH derivation from CLEAN is non-trivial (spread adjustment, execution model). News RESEARCH = CLEAN copy + lineage — deterministic by construction, no execution model version to track.

**Correction to original plan Section 5:** The original plan proposed a standalone `_lineage.json` file (Section 5, Phase 3). This is WRONG — the existing system uses `_manifest.json` with embedded CLEAN linkage fields for staleness, not a separate lineage file. The MASTER_DATA `_lineage.json` files are a secondary artifact, not the primary lineage mechanism.

**Updated RESEARCH manifest for news (aligned with existing):**
```json
{
  "clean_sha256": "...",
  "clean_row_count": 487,
  "research_sha256": "...",
  "generated_utc": "2026-04-11T12:00:00Z"
}
```

The separate `_lineage.json` from the original plan is **dropped** in favor of the manifest-embedded lineage that the system actually uses.

---

### 11.4 Timestamp / Partitioning Rules

**What the current system does:**

**Year partitioning** in `raw_update_sop17.py` (`save_data`, line 347):
```python
df['year'] = df['time'].dt.year
unique_years = df['year'].unique()
for year in unique_years:
    year_df = df[df['year'] == year].copy()
    filename = f"{asset}_{feed}_{timeframe}_{year}_RAW.csv"
```

Partitioning is by the **data timestamp's year**, NOT by the source file's year or download date. UTC-naive timestamps are used (timezone stripped before partitioning).

**Timezone normalization** in `clean_rebuild_sop17.py`:
- Timestamps are already UTC from MT5/Delta API
- CLEAN strips timezone info: `df['time'] = df['time'].dt.tz_localize(None)` — all CLEAN data is UTC-naive
- No explicit timezone conversion needed (source is already UTC)

**In RESEARCH layer:**
- `rebuild_research_sop17.py` preserves UTC-naive convention
- Comment header declares `# utc_normalization_flag: TRUE`

**Whether it already solves the concern:**

Partially. The year-from-timestamp partitioning rule is directly applicable. But the timezone handling differs: MASTER_DATA sources are already UTC, while news data arrives in US/Eastern and requires active conversion.

**What the news pipeline should do:**

- **REUSE: Year partitioning** by UTC timestamp year (after conversion). Partition at CLEAN layer using `df['datetime_utc'].dt.year`, identical to existing pattern.
- **EXTEND: Timezone conversion** at CLEAN layer (US/Eastern → UTC → strip timezone). This is new logic because existing CLEAN doesn't need conversion — sources are already UTC. The conversion logic already exists and is tested in `tools/news_calendar.py` (`_normalize_timestamps`, lines 92-154). It should be moved into the CLEAN builder.
- **REUSE: UTC-naive output convention.** CLEAN output is UTC-naive (`datetime64[ns]` without tzinfo), matching all existing CLEAN/RESEARCH data.

**Edge case — cross-year events:** A ForexFactory export for "2025" may contain events from late December 2024 or early January 2026 due to export window overlap. The UTC-based year partitioning at CLEAN naturally handles this: events land in the correct year file based on their UTC timestamp, regardless of which RAW source file they came from. Cross-file dedup (Section 11.2) prevents duplicates.

---

### 11.5 Validation Framework

**What the current system does:**

`SOP17Validator` in `dataset_validator_sop17.py` provides:

1. **Filename convention:** Regex `^(?P<asset>[A-Z0-9]+)_(?P<feed>[A-Z]+)_(?P<timeframe>\d+[mhdwn]+)_(?P<year>\d{4})_(?P<type>RAW|CLEAN|RESEARCH)\.csv$`
2. **Column presence:** Requires `time` column
3. **Duplicate detection:** `df['time'].duplicated().sum()`
4. **Monotonic timestamps:** `df['time'].is_monotonic_increasing`
5. **Resampling check:** Median interval vs filename-declared interval
6. **Gap detection:** With asset-class-specific tolerances (FOREX: 600 bars, CRYPTO: 0, INDEX_CFD: 10000)
7. **Minimum row thresholds:** Per-timeframe minimums
8. **Freshness gate:** Staleness check for current-year partitions
9. **Feed-timeframe matrix:** Validates `{OCTAFX, DELTA, MT5, YAHOO}` × allowed timeframes

All validators return `ValidationResult` with `valid`, `status`, `errors`, `warnings`, and `ValidationMetrics`.

Entry points: `validate_raw_extended()` (full), `validate_raw()` / `validate_clean()` (bool wrappers).

**Whether it already solves the concern:**

No. `SOP17Validator` is deeply coupled to OHLCV data:
- Filename regex requires `{ASSET}_{FEED}_{TIMEFRAME}_{YEAR}_{TYPE}` — news filenames don't have ASSET/FEED/TIMEFRAME segments
- Requires `time` column (news uses `datetime_utc`)
- Gap detection, resampling check, freshness gate, feed-timeframe matrix — all OHLCV-specific
- Asset class detection (`_detect_asset_class`) looks for instrument names in filename

None of these validation rules apply to news data. Extending `SOP17Validator` would require so many conditional branches that it would compromise the validator's clarity.

**What the news pipeline should do: SEPARATE VALIDATOR (justified)**

Create a dedicated `NewsCalendarValidator` class — NOT by extending `SOP17Validator`, but as a new class following the same interface pattern (`ValidationResult`, `ValidationMetrics`).

**Validation rules for news data:**

| Rule | Layer | Hard Fail? |
|------|-------|------------|
| Required columns: `datetime_utc`, `Currency`, `Impact`, `Event` | CLEAN | Yes |
| `Impact` ∈ {High, Medium, Low} | CLEAN | Yes — invalid rows dropped |
| `Currency` is 3-letter uppercase | CLEAN | Yes — invalid rows dropped |
| `datetime_utc` is valid, non-null | CLEAN | Yes — null rows dropped |
| No duplicate `(datetime_utc, Currency, Event)` | CLEAN | Yes |
| Chronological sort (ascending `datetime_utc`) | CLEAN | Yes |
| Row count > 0 | CLEAN/RESEARCH | Yes |
| Year matches partition filename | CLEAN/RESEARCH | Yes |

**Reuse from existing validator:**
- `ValidationResult` and `ValidationMetrics` dataclasses — import directly
- Atomic write pattern (validate `.tmp` → commit or rollback)
- The `abort_on_failure()` static method pattern

**What NOT to reuse:**
- `NAMING_REGEX` — different filename convention
- `_detect_asset_class()` — not applicable
- `_parse_timeframe()` — not applicable
- `_check_freshness()` — news data has no automatic freshness expectation
- Gap detection — events are aperiodic by nature

**Correction to original plan Section 7:** The original plan said "Extend `dataset_validator_sop17.py` with news-specific validation rules." This is WRONG — the validator is too OHLCV-specific to extend cleanly. A separate validator following the same interface is the correct approach.

---

### Summary of Corrections to Original Plan

| Section | Original Claim | Correction |
|---------|---------------|------------|
| §5 Phase 3 | Separate `_lineage.json` files | **Drop.** Use manifest-embedded CLEAN linkage (existing pattern) |
| §7 Row 2 | Extend `dataset_validator_sop17.py` | **Separate validator.** SOP17Validator is OHLCV-coupled; extend interface, not class |
| §7 Row 3 | Reuse `compute_file_hash()` from `build_usd_synth.py` | **Import from `raw_update_sop17.py`** (or factor into shared utility). Same function exists in 3 modules — use canonical source |
| §5 Phase 1 | "RAW files are immutable once written" | **Clarify:** RAW files are *replaceable* via atomic `os.replace()`, not immutable. Same as existing system. |
| §8 Row 3 | "RESEARCH = CLEAN" listed as deviation | **Not a deviation** — lineage-only RESEARCH is justified by the staleness detection chain, which requires manifests at each layer |

---

## 12. Execution Safety Locks (Pre-Implementation Gates)

### 12.1 Staleness Chain Must Actually Trigger

The plan claims reuse of the manifest-based staleness chain. This must be verified during implementation — if it doesn't work, the pipeline silently breaks (stale CLEAN/RESEARCH served indefinitely after RAW updates).

**Required chain:**

```
RAW replaced → RAW manifest updated (new sha256)
                    ↓
         CLEAN manifest has old raw_sha256
                    ↓
         _check_raw_staleness() returns True
                    ↓
         CLEAN rebuild triggered → new CLEAN manifest (new clean_sha256)
                    ↓
         RESEARCH manifest has old clean_sha256
                    ↓
         _check_clean_staleness() returns True
                    ↓
         RESEARCH rebuild triggered → new RESEARCH manifest
```

**Implementation gate (MUST pass before pipeline is considered working):**

1. Place a RAW file, run full pipeline → verify CLEAN + RESEARCH created with manifests
2. Replace the RAW file with modified content (add/remove one event)
3. Re-run pipeline
4. **Assert:** CLEAN file SHA256 changed, CLEAN manifest `raw_sha256` matches new RAW manifest
5. **Assert:** RESEARCH file SHA256 changed, RESEARCH manifest `clean_sha256` matches new CLEAN manifest
6. If either assertion fails → staleness detection is broken → do NOT ship

**Specific implementation requirements:**

- `build_news_calendar.py` MUST write CLEAN manifests with `raw_sha256`, `raw_row_count` fields (mirroring `_write_clean_manifest_dvg`)
- `build_news_calendar.py` MUST write RESEARCH manifests with `clean_sha256`, `clean_row_count` fields (mirroring `_write_research_manifest`)
- `build_news_calendar.py` MUST call staleness checks before deciding to skip a rebuild
- The staleness check functions (`_check_raw_staleness`, `_check_clean_staleness`) should be imported from existing modules or factored into a shared utility — NOT reimplemented

---

### 12.2 Consumer Must NOT Double-Normalize

After migration, `tools/news_calendar.py` reads from RESEARCH, which guarantees:
- `datetime_utc` column exists, is UTC-naive `datetime64[ns]`
- Timestamps already converted from US/Eastern → UTC
- Date already forward-filled
- Unusable rows already dropped
- Dedup already applied

**If `news_calendar.py` still runs its normalization logic on already-normalized data, the following silent bugs occur:**

| Current function | What goes wrong if kept |
|-----------------|------------------------|
| `_normalize_timestamps()` — US/Eastern → UTC | UTC timestamps re-interpreted as US/Eastern, shifted by 4-5 hours. Every event window is wrong. |
| Date ffill | No-op (dates already filled), but masks schema changes |
| "All Day"/"Tentative" drop | No-op (already dropped), but dead code obscures intent |
| `pd.to_datetime(dt_combined)` with year fallback | Attempts to re-parse an already-parsed ISO timestamp with string concatenation — potential parse failures |

**Mandatory changes to `tools/news_calendar.py` at migration (Step 8 in §10):**

```python
# DELETE entirely:
def _normalize_timestamps(df):  # lines 92-154 — all of it

# REPLACE _load_raw_calendar + _normalize_timestamps call chain with:
def _load_research_calendar(calendar_dir: Path):
    """Read RESEARCH-layer news calendar CSVs. No normalization needed."""
    csv_files = sorted(calendar_dir.glob("*.csv"))
    if not csv_files:
        return None
    frames = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding="utf-8")
            if len(df) > 0:
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
                frames.append(df)
        except Exception as e:
            print(f"[NEWS-CAL] Failed to read {f.name}: {e}")
    if not frames:
        return None
    result = pd.concat(frames, ignore_index=True)

    # Runtime guards — catch double-normalization or corrupt RESEARCH data
    assert result['datetime_utc'].dt.tz is None, \
        "RESEARCH datetime_utc must be UTC-naive — timezone attached means double-normalization or corrupt source"
    assert result['datetime_utc'].min().year >= 2000, \
        f"RESEARCH datetime_utc min year {result['datetime_utc'].min().year} < 2000 — likely parse corruption"

    return result
```

**Functions that STAY unchanged:**
- `derive_currencies()` — symbol→currency mapping, not a normalization function
- `_validate_calendar()` — defensive check, safe to keep as belt-and-suspenders
- `_build_windows()` — window construction, no normalization
- `group_windows_by_currency()` — grouping, no normalization
- `load_news_calendar()` — public API, signature unchanged

**Implementation gate (MUST pass before migration is considered complete):**

1. After updating `news_calendar.py`, run `tests/test_news_policy.py` — all 52 tests must pass
2. Manually verify: load a RESEARCH CSV, confirm `datetime_utc` values match expected UTC times (not shifted by 4-5 hours)
3. `grep -n "tz_localize\|tz_convert\|CALENDAR_TIMEZONE\|ffill\|All Day\|Tentative" tools/news_calendar.py` — must return ZERO matches (all normalization logic removed)

---

## Appendix: Consumer Path After Migration

```python
# tools/news_calendar.py — BEFORE
_calendar_dir = _data_root / "news_calendar"

# tools/news_calendar.py — AFTER
_calendar_dir = _data_root / "EXTERNAL_DATA" / "NEWS_CALENDAR" / "RESEARCH"
```

The `load_news_calendar()` function signature, caching, window construction, and `group_windows_by_currency()` remain unchanged. `_normalize_timestamps()` and `_load_raw_calendar()` are deleted entirely and replaced by `_load_research_calendar()` which does a single `pd.to_datetime(df['datetime_utc'])` parse — no timezone conversion, no ffill, no filtering.
