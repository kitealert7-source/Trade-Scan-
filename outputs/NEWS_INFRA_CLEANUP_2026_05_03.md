# NEWS Infrastructure Cleanup Report

**Date:** 2026-05-03
**Anchor:** `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
**Scope:** Post-NEWS-research cleanup + state hygiene + namespace audit + infra backlog + framework verification. **No new research, no new backtests.**

---

## TL;DR — Framework readiness verdict

**Will the framework fail for the same reasons if we start a fresh event-gated family tomorrow?**

**Yes — partially.** The framework's *race-class* surface (admission/preflight/marker/classifier) is solid: 57/58 tests pass, all 8 anchored files hash-match the baseline, no regressions introduced by today's cleanup. **But** 9 distinct infrastructure papercuts surfaced during the NEWS research are documented in [governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md](governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md). The next event-gated family will hit at least the top three (HIGH/MEDIUM severity) unless those are fixed.

| Status | Item |
|---|---|
| ✅ Framework race-class | Stable (`FRAMEWORK_BASELINE_2026_05_03` lock holds) |
| ✅ Approval marker contract | Stable |
| ✅ Classifier gate scoping | Stable |
| ✅ Reset directive (incl. stranded ghost) | Stable |
| ✅ Engine resolver policy | Stable |
| ⚠️ `bar_hour` convention | UNFIXED — silent zero-trades trap (INFRA-NEWS-001, HIGH) |
| ⚠️ Schema for novel filter blocks | UNFIXED — admission-block trap (INFRA-NEWS-003, MEDIUM) |
| ⚠️ Sweep slot collision detection | UNFIXED — silent registry data loss (INFRA-NEWS-009, MEDIUM) |
| ⚠️ PORT/MACDX duplication root cause | UNINVESTIGATED — affects discovery accuracy (INFRA-NEWS-006, MEDIUM) |

---

## Phase 1 — Scratch removal

| Action | Item | Type |
|---|---|---|
| DELETED | `strategies/22_CONT_FX_15M_RSIAVG_TRENDFILT_S13_V1_P00/` | Path A wrapper, side-channel only |
| DELETED | `strategies/22_CONT_FX_15M_RSIAVG_TRENDFILT_S14_V1_P00/` | Path A wrapper, side-channel only |
| DELETED | `backtest_directives/active_backup/22_CONT_FX_15M_RSIAVG_TRENDFILT_S14_V1_P00.txt` (+ `.admitted`) | Failed-admit residue |
| DELETED | `backtest_directives/INBOX/22_CONT_FX_15M_RSIAVG_TRENDFILT_S13_V1_P00.txt` | Failed-admit residue |
| DELETED | `sweep_registry.yaml` idea 22 → S13 entry | Stub, never produced runs |
| DELETED | `sweep_registry.yaml` idea 22 → S14 entry | Stub, never produced runs |
| MODIFIED | `sweep_registry.yaml` idea 22 → `next_sweep`: 15 → 13 | Restored sequential allocation |

**Total: 7 items removed + 1 registry value reverted.**

KEPT (research evidence — never delete from `outputs/`):
- All 13 NEWSBRK directives in `completed/`
- `tmp/news_*.py` and `tmp/rsiavg_*.py` scripts (referenced by output reports)
- `tmp/news_edge_discovery_results.csv` (the discovery dataset)
- `strategies/55_MR_XAUUSD_15M_ZREV_S11_V1_P00/strategy.py.bak` (pre-existing 2026-04-29, not from this session)
- `backtest_directives/completed/22_CONT_FX_30M_RSIAVG_TRENDFILT_S13_V1_P00.txt` (pre-existing 30M production directive)

---

## Phase 2 — State hygiene audit

Scanned all 287 `directive_state.json` files in `TradeScan_State/runs/`.

| Finding | Count | Action |
|---|--:|---|
| Stranded INITIALIZED ghosts | 0 | None needed (Phase 1 cleanup eliminated mine; no other ghosts in archive) |
| FAILED-state directives | 11 | Pre-existing, terminal state — left alone (not blocking new work) |
| Orphan .admitted markers in `active_backup/` | 4 (NEWSBRK S03_P03 + S04 P00/P01/P02) | Archived: directives moved to `completed/`, `.admitted` markers removed |
| Lock files (.lock, .busy, .monitor) | 1 (`.claude/scheduled_tasks.lock`) | System file, untouched |
| Stale .approved markers on deleted strategies | 0 | Phase 1 deleted markers along with their strategies |

**Result: state is clean.** `INBOX/` empty, `active/` empty, `active_backup/` empty. No stranded directives, no ghost PIPELINE_BUSY conditions, no orphan .admitted markers.

All repairs used framework-approved mechanisms only:
- `reset_directive` was used during the NEWS research itself (audit trail in `governance/reset_audit_log.csv`)
- Phase 2 cleanup used **archival move only** (.txt files from `active_backup/` to `completed/`); no manual edits to `directive_state.json` or any registry.

---

## Phase 3 — Namespace / sweep hygiene reconciliation

### Cleaned in this session
- Idea 22 `next_sweep` reverted from 15 → 13 (my S13/S14 stubs removed)
- Idea 22 sweep slots S13 + S14 entries removed
- The 30M directive `22_CONT_FX_30M_RSIAVG_TRENDFILT_S13_V1_P00` (pre-existing in `completed/`) had its sweep slot **silently overwritten** when I registered my 15M wrapper. Removal of my entry leaves the slot empty; if the 30M directive ever re-admits, the registry will recreate the slot fresh. Documented in INFRA-NEWS-009.

### Pre-existing findings (not cleaned — flagged only, per your "no manual state editing" rule)

**Placeholder-hash stubs (8 entries with `signature_hash: 0000...`):**
- `idea=22 sweep=S04`: `22_CONT_FX_15M_RSIAVG_TRENDFILT_S04_V1_P00`
- `idea=22 sweep=S05`: `22_CONT_FX_15M_RSIAVG_TRENDFILT_S05_V1_P00`
- `idea=22 sweep=S06`: `22_CONT_FX_15M_RSIAVG_TRENDFILT_S06_V1_P00`
- `idea=33 sweep=S03`: `33_TREND_BTCUSD_1H_IMPULSE_S03_V1_P00`
- `idea=42 sweep=S05`: `42_REV_GBPUSD_15M_LIQSWEEP_S05_V1_P00`
- `idea=42 sweep=S20`: `42_REV_USDCHF_15M_LIQSWEEP_S20_V1_P00`
- `idea=53 sweep=S01`: `53_MR_FX_4H_CMR_S01_V1_P00`
- `idea=55 sweep=S15`: `55_MR_EURUSD_15M_ZREV_S15_V1_P00`

These predate this session. Each is either a deliberately-reserved slot awaiting a real strategy, or stale residue from prior research. No way to tell from registry alone — needs human inspection. Tracked under INFRA-NEWS-007.

**Nominal orphan sweep entries (81 found):**
A scan of `sweep_registry.yaml` found 81 entries whose `directive_name` references a strategy with no folder and no directive file in any lifecycle location. **Caveat:** the scan likely includes false-positives because multi-symbol families register one base name in the registry but ship per-symbol strategy folders (e.g., registry has `01_MR_FX_1D_RSIAVG_TRENDFILT_S01_V1_P00` while strategies live as `..._S01_V1_P00_AUDJPY/`, `..._S01_V1_P00_USDJPY/`, etc.). A refined audit aware of the per-symbol pattern is needed before any deletion. Tracked under INFRA-NEWS-007.

**Idea 64 (NEWSBRK) status:**
`governance/namespace/idea_registry.yaml` reports `idea 64: status: active, closed_reason: -` despite the family being closed via three KILL reports. Not closing it via direct edit (your rule). Tracked under INFRA-NEWS-008.

---

## Phase 4 — Infrastructure backlog

Wrote [governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md](governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md) — 9 items:

| ID | Severity | Item |
|---|---|---|
| INFRA-NEWS-001 | **HIGH** | `bar_hour` not auto-populated → `session_filter` silently rejects all bars |
| INFRA-NEWS-002 | MEDIUM | Engine contract IDs hard-bound to specific engine versions (copy-and-rename trap) |
| INFRA-NEWS-003 | MEDIUM | Canonicalizer schema rejects new top-level filter blocks (no extension procedure) |
| INFRA-NEWS-004 | LOW | reset_directive blocks admin-only strategy edits via EXPERIMENT_DISCIPLINE (workaround undocumented) |
| INFRA-NEWS-005 | MEDIUM | Strategy directory drift detector blocks reset-and-recreate cycles |
| INFRA-NEWS-006 | MEDIUM | PORT/MACDX duplication anomaly (byte-identical trade lists from supposedly distinct strategies) |
| INFRA-NEWS-007 | LOW | Sweep registry orphan accumulation (81 nominal orphans, 8 placeholder-hash stubs) |
| INFRA-NEWS-008 | LOW | `idea_registry.yaml` doesn't auto-track research closure (NEWSBRK still `active`) |
| INFRA-NEWS-009 | MEDIUM | Sweep slot collision at registration (silent last-writer-wins overwrite) |

**Time impact during NEWS research:** ~3-4 hours of 7-8 total session hours were spent on these papercuts. Fixing the top 3 (001, 009, 006) would roughly halve the overhead for the next event-gated family.

---

## Phase 5 — Framework verification

```
$ python -m pytest tests/test_admission_race_stabilization.py \
                   tests/test_classifier_gate.py \
                   tests/test_engine_resolver_policy.py \
                   tests/test_engine_integrity_canonical_hash.py \
                   tests/test_integrity_uses_resolver.py
======================== 57 passed, 1 failed in 3.29s ========================
FAILED tests/test_classifier_gate.py::test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior
```

**The 1 failure is `INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK`** — documented as a pre-existing assertion-vs-implementation mismatch in [governance/INFRA_BACKLOG/INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md](governance/INFRA_BACKLOG/INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md). It was the only acceptable failure in [outputs/framework_baseline/REGRESSION_MANIFEST.md](outputs/framework_baseline/REGRESSION_MANIFEST.md) and remains the only failure today. **No new failures introduced by NEWS research or this cleanup.**

### Hash integrity vs FRAMEWORK_BASELINE_2026_05_03

```
OK     tests/test_admission_race_stabilization.py
OK     tests/test_classifier_gate.py
OK     tools/approval_marker.py
OK     tools/classifier_gate.py
OK     tools/orchestration/pre_execution.py
OK     tools/strategy_provisioner.py
OK     governance/preflight.py
OK     tools/reset_directive.py

VERIFIED — framework files match baseline manifest
```

All 8 anchored files unchanged since `afeda0a`. Cleanup operation did not touch the framework surface.

---

## Final answer to your question

> *"If we start a fresh event-gated family tomorrow, will the framework fail for the same reasons again?"*

**Race-class framework: NO.** The marker / EXPERIMENT_DISCIPLINE / mtime / cross-sweep classifier surface that motivated `FRAMEWORK_BASELINE_2026_05_03` is stable. Tests confirm. Hashes confirm.

**Operational papercuts: PARTIALLY.** A new event-gated family will hit:
1. **INFRA-NEWS-001 ($bar_hour$ silent rejection)** with near-certainty if it uses `session_filter`. **Fix priority: HIGH** — single-line engine fix removes the largest single category of debugging time.
2. **INFRA-NEWS-003 (schema reject for new filter blocks)** if it tries to declare a new filter category in directive YAML. **Fix priority: MEDIUM** — at minimum document the schema-extension procedure.
3. **INFRA-NEWS-009 (sweep slot collision)** if it reserves a slot manually. **Fix priority: MEDIUM** — single-line registry fix.

The remaining 6 backlog items are lower-frequency and not blocking.

### Unresolved blockers list (in fix-priority order)

1. **INFRA-NEWS-001** (HIGH) — `bar_hour` convention not enforced by engine
2. **INFRA-NEWS-009** (MEDIUM) — sweep slot collision at registration
3. **INFRA-NEWS-006** (MEDIUM) — PORT/MACDX duplication root cause
4. **INFRA-NEWS-002** (MEDIUM) — engine contract ID copy-trap
5. **INFRA-NEWS-003** (MEDIUM) — canonical_schema extension procedure
6. **INFRA-NEWS-005** (MEDIUM) — strategy directory drift on reset
7. **INFRA-NEWS-008** (LOW) — idea_registry research-closure tracking
8. **INFRA-NEWS-004** (LOW) — reset_directive admin-edit workaround discoverability
9. **INFRA-NEWS-007** (LOW) — sweep_registry orphan GC

### Framework verdict

The framework is **NOT marked ready for the next event-gated family** until INFRA-NEWS-001 is fixed. Without that fix, any session_filter-using strategy will silently produce zero trades, repeating my multi-hour debug cycle.

Once INFRA-NEWS-001 lands (single-line engine change to auto-populate `bar_hour`), the framework can be marked **ready for the next event-gated family** at the operational level. The race-class framework is already ready.

---

## What changed (cumulative — Phases 1 through 5)

- **Strategy folders deleted:** 2 (S13, S14 wrappers)
- **Directive files deleted:** 5 (.txt + .admitted across active_backup, INBOX, completed)
- **Directive files archived (active_backup → completed):** 4 (NEWSBRK S03_P03, S04 P00/P01/P02 — pre-existing orphans)
- **Sweep registry stubs removed:** 2 (S13, S14 under idea 22)
- **Registry values reverted:** 1 (idea 22 next_sweep: 15 → 13)
- **TradeScan_State run dirs removed:** 0 (S13/S14 had no run state)
- **Tests run:** 58 (57 pass + 1 known pre-existing failure)
- **Hash integrity check:** 8/8 OK against baseline manifest
- **New backlog items documented:** 9
- **No commits made** — cleanup is in worktree; mirror to main + commit pending your call.

---

## Artifacts

- This report: [outputs/NEWS_INFRA_CLEANUP_2026_05_03.md](outputs/NEWS_INFRA_CLEANUP_2026_05_03.md)
- Backlog: [governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md](governance/INFRA_BACKLOG/INFRA_BACKLOG_NEWS_EXECUTION.md)
- Framework baseline (unchanged): [outputs/framework_baseline/REGRESSION_MANIFEST.md](outputs/framework_baseline/REGRESSION_MANIFEST.md)
- Pre-existing test failure tracking: [governance/INFRA_BACKLOG/INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md](governance/INFRA_BACKLOG/INFRA_BACKLOG_001_ENGINE_RERUN_FALLBACK.md)
- Anchor: `FRAMEWORK_BASELINE_2026_05_03` / `afeda0a`
