# News Pipeline — Live State Audit vs April Design Plan

**Date:** 2026-05-02
**Scope:** Verify the *operational* state of the news ingestion + report pipeline, not the design intent. Use [outputs/NEWS_CALENDAR_INGESTION_PLAN.md](outputs/NEWS_CALENDAR_INGESTION_PLAN.md) and [outputs/NEWSBRK_DISCOVERY_REPORT.md](outputs/NEWSBRK_DISCOVERY_REPORT.md) only as references — verify every claim against live data, code, and scheduler logs.
**Outcome:** The ingestion pipeline is **operationally complete**. The Trade_Scan loader is fully migrated. The only material gaps are **last-mile research features in the report pipeline** (asymmetric pre/post windows, impact sweep, news-subset quality metrics).

---

## TL;DR

| Layer | Status | Notes |
|---|---|---|
| RAW / CLEAN / RESEARCH directories | **A — operationally complete** | Live data 2024–2026, 10,296 events |
| Manifests + staleness chain | **A — operationally complete** | RAW→CLEAN→RESEARCH sha256 chain, [SKIP] when unchanged, [COMMIT] when sources change |
| Windows scheduled task | **A — operationally complete** | `AntiGravity_Daily_Preflight`, daily 05:45, last result = 0, next run 2026-05-03 05:45 |
| Daily news fetch + build phases (5.4 + 5.5) | **A — operationally complete** | PASS on every recent run; gap-recovery worked correctly on 2026-04-28 |
| `tools/news_calendar.py` migration to RESEARCH | **A — operationally complete** | No legacy `_normalize_timestamps`, `tz_convert`, ffill, "All Day"/"Tentative" handling, raw parsing |
| `tests/test_news_policy.py` | **A — operationally complete** | 48/48 PASS on live implementation |
| RESEARCH columns: `datetime_utc`, `currency`, `impact`, `event` | **A — operationally complete** | Plus `source` provenance column. H/M/L impact preserved (1857 High events 2024–2026) |
| Loader API (`pre_min`, `post_min`, `impact_filter`) | **A — operationally complete** | Defaults: `pre_min=15`, `post_min=15`, `impact_filter="High"` |
| Report pipeline: news vs outside aggregate, per-symbol, Go-Flat scenarios | **A — operationally complete** | All 565 strategy/symbol cells in the corpus carry it |
| **Asymmetric pre/post windows in reports** | **C — missing** | `_build_news_policy_section` calls `load_news_calendar(calendar_dir)` with defaults → cannot sweep windows |
| **Impact sweep in reports** | **C — missing** | Single hard-coded `impact_filter="High"` default; no Medium / High+Medium variants emitted |
| **Per-trade pre-only / post-only / straddle tags** | **C — missing** | Classifier emits `news_flag, entry_in_window, straddles, earliest_window_start` only |
| **News-subset quality metrics** (yearwise news-PF, top-5 news, longest-flat news) | **C — missing** | Baseline metrics only; news-only equivalents not computed |
| **Per-impact PF breakdown** in News Policy section | **C — missing** | Single aggregate row only |

A = already implemented; B = partially implemented but legacy logic remains; C = missing and required for NEWSBRK v1.

There is no Class B in this audit. The migration is clean — no legacy code lingers in the loader.

---

## 1. EXTERNAL_DATA/NEWS_CALENDAR layer existence + live data

**Status: A — operationally complete.**

```
C:\Users\faraw\Documents\Anti_Gravity_DATA_ROOT\EXTERNAL_DATA\NEWS_CALENDAR\
├── RAW/         6 source files (FOREXFACTORY_2024..2026, multiple snapshot dates)
├── CLEAN/       NEWS_CALENDAR_{2024,2025,2026}_CLEAN.csv + manifests
├── RESEARCH/    NEWS_CALENDAR_{2024,2025,2026}_RESEARCH.csv + manifests
└── metadata.json
```

Row counts (verified by direct read):

| Year | RESEARCH rows | Impact distribution |
|---|---|---|
| 2024 | 3,546 | Low: 2,364 / Medium: 485 / High: 697 |
| 2025 | 4,759 | Low: 3,313 / Medium: 600 / High: 846 |
| 2026 | 1,991 | Low: 1,457 / Medium: 220 / High: 314 |
| **Total** | **10,296** | **High: 1,857** |

`metadata.json.creation_timestamp = 2026-05-02T00:28:51` matches the latest scheduler run; `validation_stats.total_events = 10296` matches direct CSV row counts.

Symlink exists: `Trade_Scan\data_root\EXTERNAL_DATA → ../Anti_Gravity_DATA_ROOT/EXTERNAL_DATA` (verified by listing `Trade_Scan/data_root/EXTERNAL_DATA/NEWS_CALENDAR/` and seeing the same files).

The April plan's directory layout (Section 3) is exactly what's on disk.

---

## 2. Manifests + staleness-chain hashes end-to-end

**Status: A — operationally complete.**

Live chain (verified for `NEWS_CALENDAR_2026`):

```
RAW manifest (FOREXFACTORY_2026_2026-05-02.csv_manifest.json)
   sha256 = 9105fb1adcfacbdced7396b2f5655d0eeb9fb6931a99dafd9e87d9eca7d4060f
            ↓ (build merges 4 RAW files for 2026 into a composite raw_sha256)
CLEAN manifest (NEWS_CALENDAR_2026_CLEAN.csv_manifest.json)
   raw_sha256       = 8a00d86e3c929330a26e8ef023303ba4f80cc204cc426e933d7a949b1e44014b
   raw_source_files = [FOREXFACTORY_2026_2026-04-11, ..04-30, ..05-01, ..05-02]
   clean_sha256     = 2d59509cd8e88fb8c5bd281bfe4c382133704052586a4890537aee3f699e29b0
            ↓
RESEARCH manifest (NEWS_CALENDAR_2026_RESEARCH.csv_manifest.json)
   clean_sha256    = 2d59509cd8e88fb8c5bd281bfe4c382133704052586a4890537aee3f699e29b0  ← matches CLEAN
   research_sha256 = 2d59509cd8e88fb8c5bd281bfe4c382133704052586a4890537aee3f699e29b0  ← pass-through
            ↓
metadata.json
   source_data_hashes["NEWS_CALENDAR_2026_RESEARCH.csv"] = 2d59509cd8e88fb8c5bd281bfe4c382133704052586a4890537aee3f699e29b0
```

The 2024 and 2025 RESEARCH/CLEAN manifests are byte-stable across runs (their RAW snapshot files have not been re-fetched since 2026-04-11, so the build correctly logs `[SKIP] NEWS_CALENDAR_2024_CLEAN.csv - RAW unchanged` / `[SKIP] NEWS_CALENDAR_2024_RESEARCH.csv - CLEAN unchanged` every day).

**Live evidence of staleness chain working:** in the 2026-05-02 scheduler log, only the 2026 file produced `[COMMIT]` lines (RAW changed for that year, since a fresh ForexFactory snapshot was downloaded). 2024 and 2025 produced `[SKIP]` lines because their `raw_sha256` and `clean_sha256` matched the stored manifest values. This is precisely the chain semantics promised by the April plan §11.3 / §12.1.

The April plan's "implementation gate" assertions in §12.1 (assert CLEAN sha changes when RAW changes; assert RESEARCH manifest's `clean_sha256` matches new CLEAN) are passing on real production data daily.

---

## 3. Windows scheduled task + daily cadence

**Status: A — operationally complete.**

Scheduled task `AntiGravity_Daily_Preflight`:
- State: Ready
- Action: `powershell.exe ... DATA_INGRESS\engines\ops\invoke_preflight.ps1`
- LastRun: 2026-05-02 05:45:01 (today)
- LastResult: 0 (success)
- NextRun: 2026-05-03 05:45:00

Daily run pattern (last 7 scheduler logs at `DATA_INGRESS/logs/SCHEDULER/scheduler_*.log`, UTF-16 encoded):

| Date | Phase 5.4 fetch | Phase 5.5 build | NEWS-HEALTH | Notes |
|---|---|---|---|---|
| 2026-05-02 | PASS — 510 events | PASS — 2 COMMIT, 4 SKIP | PASS, hours_since=0.0 | New 2026 RAW fetched |
| 2026-05-01 | PASS | PASS — 2 COMMIT, 4 SKIP | PASS | New 2026 RAW fetched |
| 2026-04-30 | PASS | PASS — 0 COMMIT, 6 SKIP | (no rebuild needed) | RAW unchanged |
| 2026-04-29 | PASS | PASS — 0 COMMIT, 6 SKIP | (no rebuild needed) | RAW unchanged |
| 2026-04-28 | did not run | did not run | n/a | Preflight detected gap (last run 2026-04-26 vs today 2026-04-28); decision = `RUN_RECOVERY`; pipeline correctly **did NOT auto-run** — by design, manual investigation required |
| 2026-04-26 | PASS | PASS | (no rebuild needed) | RAW unchanged |
| 2026-04-25 | PASS | PASS | (no rebuild needed) | RAW unchanged |

The Apr-28 entry is **expected behavior**, not a failure — the preflight gate's gap-recovery rule is part of the system design and was demonstrated to work. From Apr-29 onwards, daily cadence resumed cleanly.

Live RESEARCH growth proof: 2026 file went from a single 2026-04-11 snapshot to a composite of 4 snapshots (Apr-11, Apr-30, May-01, May-02) over the audit window, with manifest sha256s rotating each time the source content changed. Events for early-May 2026 (e.g., 2026-05-01 ECB testimonies, 2026-05-02 NFP) are present in `NEWS_CALENDAR_2026_RESEARCH.csv`.

The April plan's "Phase 4 + Phase 5: build_news_calendar.py + daily_pipeline.py wiring" (Section 10 steps 3–4) is fully wired.

---

## 4. `tools/news_calendar.py` — migration audit

**Status: A — operationally complete. No legacy code remains.**

Verified by reading [tools/news_calendar.py](tools/news_calendar.py) end-to-end:

| Legacy signal | Found? |
|---|---|
| `_normalize_timestamps()` function | **No** |
| `tz_localize` / `tz_convert` | **No** |
| `CALENDAR_TIMEZONE` constant | **No** |
| Date column ffill | **No** |
| "All Day" / "Tentative" filtering | **No** |
| Raw `Date+Time` string concatenation parse | **No** |
| `_load_raw_calendar()` function | **No** |

What exists instead:

- `_load_research_calendar(calendar_dir)` — single `pd.read_csv` + `pd.to_datetime(df['datetime_utc'])`, no transformation
- Two **runtime guards** (line 94–97) that assert RESEARCH data is UTC-naive and `min(year) >= 2000` — these will trip immediately if upstream regresses to double-normalization or schema corruption
- `_validate_calendar()` — drops rows with invalid impact / wrong dtypes / duplicate `(datetime_utc, currency, event)` (this is a defensive belt-and-braces — CLEAN already does this, but the guard is appropriate)
- Public API `load_news_calendar(calendar_dir, *, pre_min=15, post_min=15, impact_filter="High")` — defaults to **High-impact-only with ±15 minute symmetric windows**

The April plan §12.2 grep test passes:

```
grep -n "tz_localize|tz_convert|CALENDAR_TIMEZONE|ffill|All Day|Tentative" tools/news_calendar.py
→ 0 matches
```

This corrects an assumption in the discovery report: every News Policy section in the existing 1,076 strategy reports was generated against **High-impact events only**, not all impacts. The corpus's news-PF figures already reflect the High-only filter.

---

## 5. RESEARCH CSV columns + downstream slicing readiness

**Status: A — operationally complete.**

```csv
datetime_utc,currency,impact,event,source
2026-01-01 00:00:00,USD,High,Unemployment Claims,FOREXFACTORY_2025_2026-04-11.csv
2026-01-01 02:00:00,USD,Low,Crude Oil Inventories,FOREXFACTORY_2025_2026-04-11.csv
2026-01-02 17:30:00,GBP,Low,Nationwide HPI m/m,FOREXFACTORY_2026_2026-04-11.csv
```

All five fields needed for NEWSBRK slicing are present:
- `datetime_utc` — UTC-naive `datetime64[ns]`
- `currency` — 3-letter ISO, normalized uppercase
- `impact` — `{High, Medium, Low}` exactly
- `event` — event name (NFP, CPI, FOMC, etc.) — usable for event-name allowlists later
- `source` — provenance trail back to RAW snapshot file (bonus, not in the original plan but useful)

Currency coverage in 2026 file: AUD, CAD, CHF, CNY, EUR, GBP, JPY, NZD, USD. All currencies implied by `_SYMBOL_CURRENCY_OVERRIDES` are covered.

---

## 6. Report pipeline news segmentation on live data

**Status: A — operationally complete for the current report contract; C — missing for NEWSBRK research dimensions.**

What works today (verified by reading `tools/report/report_sections/news.py` and `tools/report/report_news_policy.py`, plus by reading 50+ existing `REPORT_*.md` News Policy sections):

| Capability | Implementation |
|---|---|
| Trade-vs-window overlap classification | `_classify_all_trades_news()` in [tools/report/report_news_policy.py](tools/report/report_news_policy.py) — vectorized per-symbol, per-currency-windows |
| Per-trade tags | `_news_flag`, `_entry_in_window`, `_straddles`, `_earliest_ws` |
| Aggregate metrics | trades, net_pnl, pf, win_pct, max_dd via `_compute_news_metrics()` |
| Scenario comparisons | Baseline / No-Entry / Go-Flat (with OHLC-priced exit at earliest window_start for straddlers) |
| Per-symbol sensitivity table | News PF vs Outside PF per symbol |
| Per-symbol Helps/Hurts/Neutral classification | based on `\|pf_n - pf_o\| < 0.1` threshold |

What is **missing** for NEWSBRK v1 research:

| Missing capability | Why needed |
|---|---|
| Asymmetric pre/post windows (`pre_window_minutes`, `post_window_minutes` as separate report-level params, not just defaults) | Architecture A1 (pre-event compression) wants `[event - 60min, event - 5min]`; Architecture A3 (reclaim) wants `[event + 5min, event + 4×TF]`. The loader supports it; the report does not pass it through. |
| Per-trade `news_pre_only` / `news_post_only` / `news_straddle` tags | All three architectures need to distinguish trades that fired *before* an event from those that fired *after*. Today the classifier collapses both into a single `news_flag`. |
| Multi-impact sweep in one report (High vs High+Medium vs Medium-only) | Today the section uses one filter (default `High`). Tail-thinning hypothesis can't be tested without re-running the report at multiple impact filters. |
| Per-impact PF breakdown table | Stratifying news PF by `{High, Medium}` reveals whether the edge is concentrated in High events or distributed |
| Per-currency PF breakdown for multi-currency symbols | XAUUSD, NAS100 inherit USD windows; XAGUSD, GER40 inherit other-currency windows. Today everything is averaged. |
| News-subset yearwise PF | Baseline yearwise table exists; news-only yearwise does not. Required by pre-promote quality gate to confirm news edge isn't a single-year artifact. |
| News-subset Top-5 % concentration / longest-flat / edge-ratio | Baseline-only today; news-only equivalents required by pre-promote quality gate (`feedback_promote_quality_gate`). |
| Single-event high-impact-day clustering metric | NFP day has 5+ events; CPI day has 2–3. Many "news" trades may overlap *the same event chain*. Without de-duplication by event-day, sample sizes are inflated. |

These are all additive computations on top of the existing `_classify_all_trades_news` infrastructure — they do not require any change to ingestion or to the loader.

---

## Gap classification

| Class | Description | Items |
|---|---|---|
| **A — Already implemented** | Working in production today | RAW/CLEAN/RESEARCH layout; staleness chain; daily scheduler at 05:45; loader migrated; tests 48/48 pass; impact + currency + event + datetime_utc present; loader supports asymmetric windows + impact filter via kwargs |
| **B — Partially implemented, legacy remains** | Code regressed or migration half-done | **None found.** Migration is clean. |
| **C — Missing, required for NEWSBRK v1** | New research dimensions on top of existing infrastructure | Report-level pre/post window params; per-trade pre/post/straddle tags; multi-impact emission in one report; per-impact PF breakdown; per-currency PF breakdown; news-subset yearwise / Top-5 / longest-flat / edge-ratio; event-day clustering metric |

---

## Ranked execution plan for NEWSBRK v1 (live-state-aware)

This replaces Section 8 of `NEWSBRK_DISCOVERY_REPORT.md`. Steps that the discovery report assumed needed building are **already done**; the live system needs only the report-side research extensions before any new strategy is authored.

### Step 0 — Skipped. Already done.
Ingestion, RESEARCH layer, manifests, staleness chain, loader migration, scheduler — all live. No work needed. The design plan's Sections 1–11 + §12.1–12.2 are realized.

### Step 1 — Report-side research extensions (no new strategy yet)

Single-PR scope, all changes confined to [tools/report/report_news_policy.py](tools/report/report_news_policy.py) and [tools/report/report_sections/news.py](tools/report/report_sections/news.py). Estimate: 1 work session.

1. Plumb `pre_window_minutes`, `post_window_minutes`, `impact_filter` (and an `impact_sweep: list[str]` for High / High+Medium / Medium-only emission) from `_build_news_policy_section` down through to `load_news_calendar`. Defaults remain `(15, 15, "High")` so existing reports don't regress.
2. Extend `_classify_all_trades_news` to emit three additional per-trade boolean tags: `_news_pre_only` (trade is fully inside `[event_start, event_dt)`), `_news_post_only` (fully inside `[event_dt, event_end]`), `_news_straddle` (entry in pre, exit in post — already captured by `_straddles`, just rename).
3. Add a "News Subset Yearwise" table emitter — same shape as the existing Yearwise table but filtered to `_news_flag == True`.
4. Add a "News Subset Top-5 / Longest-Flat / Edge-Ratio" sub-section, computed with the same helpers used in the baseline risk characteristics section.
5. Add per-impact PF breakdown (High / Medium rows) and per-currency PF breakdown (USD / EUR / JPY rows for symbols with multi-currency windows).
6. **Verify gate:** re-run the report on three diverse strategies (`63_BRK_IDX_30M_ATRBRK_S13_V2_P00_NAS100`, `62_TREND_IDX_5M_KALFLIP_S01_V2_P15_NAS100`, `03_TREND_XAUUSD_1H_IMPULSE_S02_V1_P02_XAUUSD`) and visually inspect the new sections; confirm `tests/test_news_policy.py` passes plus add unit tests for the new tags.

### Step 2 — Re-classify the existing corpus with the extended report

Re-emit the News Policy section across the 1,076 existing reports (no engine re-run required — `_classify_all_trades_news` consumes existing trade ledgers). This regenerates `news_classified.md` with:
- pre vs post split per cell
- impact stratification per cell
- news-subset yearwise stability per cell
- news-subset tail concentration per cell

The discovery report's headline is likely to sharpen, not weaken: the ATRBRK news-edge probably concentrates further in **post-event windows on High-impact USD events**, and the news-subset top-5 % concentration on the strongest cells will be the deciding number for the pre-promote quality gate.

### Step 3 — Author NEWSBRK_S01_V1 only after Step 2

`NEWSBRK_S01_V1` = ATRBRK on NAS100 30M with explicit `news_window=[event-30min, event+90min]`, `impact={High}`, `currencies={USD}`. The directive's plumbing reads a `news_filter` block on the directive YAML that the existing engine FilterStack can host (the loader already supports the kwargs; the FilterStack just needs a thin block that calls it with the directive's parameters).

This is the only meaningful new code: a `NewsWindowFilter` block in `engines/filter_stack/`, configurable from directive YAML. Estimate: 1 work session, gated by Step 2 confirming the news edge holds under the asymmetric / impact-stratified view.

### Step 4 — Cross-symbol replication (was Step 3 in the discovery report)

Same as discovery report Step 3 — replicate to GER40, JPN225, EUSTX50, ESP35, UK100. Now uses the Step-3 NewsWindowFilter, so each symbol just changes the directive's `currencies` set.

### Step 5–7

Identical to discovery report Steps 4–7 (KALFLIP A2 substrate, A1+A2 portfolio combine, A3 reclaim, BTCUSD stretch).

### Pre-flight gates (apply at every step)
- F19 re-test guard against RESEARCH_MEMORY before each directive
- Pre-promote quality gate **on the news subset specifically**, using the metrics added in Step 1 (Top-5 news, longest-flat news, news-subset yearwise PF)
- Engine v1.5.8 dual-time regime alignment intact under the news gate

---

## What this audit does NOT change

- The discovery report's classification of strategies (A / B / C) is unchanged. The corpus News Policy data was already generated under `impact_filter="High"` defaults, so the news-PF figures in [tmp/news_scan.csv](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_scan.csv) and [tmp/news_classified.md](.claude/worktrees/vigilant-allen-a3c2a7/tmp/news_classified.md) are High-impact-only news-PFs as initially intended (this corrects the discovery report's caveat #1 in §7 — impact filtering was not missing, it was on by default).
- The architecture mapping (A1 / A2 / A3) is unchanged. The substrate evidence stands.
- The symbol/timeframe ranking is unchanged.

What changes vs the discovery report's roadmap: **Step 1 (calendar tooling extensions) is now lighter** because the loader already supports asymmetric windows and impact filtering — only the report-side plumbing and per-trade pre/post tags + news-subset quality metrics are missing. The "build the calendar pipeline" framing of the April design doc is obsolete; only research-layer features remain.

---

## Appendix — Verification commands used

```bash
# Layer existence
ls C:/Users/faraw/Documents/Anti_Gravity_DATA_ROOT/EXTERNAL_DATA/NEWS_CALENDAR/{RAW,CLEAN,RESEARCH}/

# Schema + impact distribution
python -c "import csv; from collections import Counter; ..."  # see §1

# Manifest staleness chain
cat .../NEWS_CALENDAR_2026_{CLEAN,RESEARCH}.csv_manifest.json

# Scheduler last 7 runs (UTF-16 logs)
python -c "raw=open(...).read(); text=raw[2:].decode('utf-16-le'); ..."

# Tests
python -m pytest tests/test_news_policy.py -x   # 48/48 PASS

# Legacy-code grep
grep -n "tz_localize|tz_convert|CALENDAR_TIMEZONE|ffill|All Day|Tentative" tools/news_calendar.py
# → 0 matches

# Scheduled task
Get-ScheduledTask | Where-Object {$_.Actions.Arguments -match 'invoke_preflight'} | ...
# → AntiGravity_Daily_Preflight, Ready, last result 0
```
