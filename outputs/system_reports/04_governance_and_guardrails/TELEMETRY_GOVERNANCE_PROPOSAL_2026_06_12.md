# Rule Telemetry as a First-Class Research Artifact — Governance Proposal

**Status:** PHASES 1–3 APPROVED (operator, 2026-06-12) — writer envelope, summary
utility, BaselineReference pointer. PHASE 4 (skill integration) DEFERRED until one
more hypothesis cycle has been observed using the new tooling — tooling first,
researcher-behavior changes after refinement against real use.
**Origin:** the HF55/HF60/HL120/LM20 entry-filter arc (2026-06-12), where per-event
telemetry (`recycle_events.jsonl`, added at commit `81b5d033`) carried decision-grade
evidence: the HL/Hurst population disjointness, the MOVE_BLOCK driving-leg shares, the
blocked-value distributions, and the relocation-persistence mechanism were all read from
event artifacts, not from reruns.
**Doctrine line (operator):** *telemetry exists to support or refute scientific
conclusions, not to diagnose failures.*

---

## 1 · Governance

### 1.1 Classification

`raw/recycle_events.jsonl` is a **Research Artifact — Population Evidence** (operator
refinement 2026-06-12: canonical metrics already provide decision support; telemetry
answers the next two questions — *champion improved → WHICH entries changed → WHY*).
It is peer to `results_basket_per_bar.parquet` and the canonical metrics, NOT debug
output, and
is never pruned independently of its run capsule (pipeline-state-cleanup treats the
capsule as the unit, unchanged).

### 1.2 Ownership (three layers, one direction)

| Layer | Owns | Must NOT |
|---|---|---|
| **Rules** (`tools/recycle_rules/*`) | EMIT events: append plain dicts to `self.recycle_events`; one `action` key + event-specific fields | write files; know about schema envelopes |
| **Pipeline** (`tools/basket_report.py`) | PERSIST events: wrap in the schema envelope (§3) and write `raw/recycle_events.jsonl` | drop, reorder, or mutate event payloads |
| **Skills / analysis** | CONSUME through documented interfaces (§5 summary tool; direct JSONL read as fallback) | depend on undocumented payload fields without recording the dependency |

### 1.3 Expectations (each with its enforcement mechanism — Invariant: no
unenforced governance prose)

| Expectation | Meaning | Enforcement mechanism (proposed) |
|---|---|---|
| Deterministic | same directive + data + rule code → byte-identical events | already guaranteed by engine determinism; covered by existing parity tests (events compared byte-wise in `test_*_entry_gate.py`) |
| Reproducible | events re-derivable from the capsule (seed + code + data) | capsule already snapshots rule source (`basket_code/`, SHA-pinned) |
| Append-only within a run | writer emits the rule's list verbatim, in order | unit test asserts order + count == `recycle_event_count` (results_basket.csv) |
| Machine-readable | one JSON object per line; JSON-safe coercion | existing `_json_safe` + payload-fidelity tests (`test_basket_report_phase5b3a.py`) |
| Schema-versioned | every v1+ event carries `schema_version` | writer-level test asserts envelope on every written line |

### 1.4 Canonical location (Task 2)

`<backtest capsule>/raw/recycle_events.jsonl` — **canonical**; mirrored nowhere else.
Rules: one JSON object per line; file **omitted entirely** when the rule emitted no
events (matches the per-bar-parquet convention); historical runs lacking the file are
**fully valid** — absence means "no telemetry", never "invalid run".

---

## 2 · Coverage boundary (honest statement of what exists)

| Cohort / era | Telemetry on disk | Population recovery path |
|---|---|---|
| Champion `GP_ZCRS_CXN1_Z25`, HF55, and all runs before `81b5d033` | **none** | deterministic RECOMPUTATION from capsule (leg marks → indicator at entry bars — the Step-1 method); never a rerun, never a backfill |
| HF60, HL120, LM20 (2026-06-12) | **v0** (inline format: `action`, `bar_ts`, fields at top level; no envelope) | direct read; consumers must support v0 |
| Future runs (post-approval) | **v1** (envelope, §3) | direct read |

**No mutation of historical artifacts** — v0 files are never rewritten; the absent-file
era is never backfilled into capsules. (A derived re-characterization may be produced
OUTSIDE capsules, clearly marked DERIVED, but the default is recompute-on-demand: cheap,
and keeps capsule provenance pure.)

---

## 3 · Event schema v1 (Task 3)

### 3.1 Envelope — stamped by the WRITER, not the rules

Rules keep emitting today's lightweight dicts (zero rule-code changes — additive,
backward compatible). `basket_report._write_recycle_events` wraps each:

```json
{
  "schema_version": 1,
  "event_type":  "MOVE_BLOCK",            // from the rule dict's "action"
  "timestamp":   "2024-11-06T04:30:00",   // from "bar_ts", ISO-8601
  "rule_name":   "pine_ratio_zrev_v1_zcross_lm",
  "rule_version": 1,
  "run_id":      "e04c8a95a9c118f2735f0d2b",
  "directive_id": "90_PORT_..._LM20__E260127",
  "basket_id":   "AUDJPYESP35",
  "payload":     { "mm": 3.1, "leg": "ESP35", "threshold": 2.0, "direction": -1 }
}
```

**Required:** `schema_version, event_type, timestamp, rule_name, rule_version, run_id,
directive_id, payload`. **Optional:** `basket_id`, anything else.
Identity fields are stamped even though they are ambient in the capsule path, because
the dominant research workflow is **cross-run concatenation** (glob + concat over a
cohort) — path-parsing for identity was a friction in the LM20/HL120 analyses.

`pair` (operator's draft field): carried as `basket_id` (the canonical pair identity in
this corpus); per-leg attribution stays in payloads (`leg` in MOVE_BLOCK).

**Payload contract:** event-specific, owned by the emitting rule, documented in the
rule's module docstring (already the convention: HURST_BLOCK→`h`, HL_BLOCK→`hl` +
`non_reverting`, MOVE_BLOCK→`mm` + `leg`). JSON-portability rules: no `inf`/`nan` —
use `null` + a boolean flag (the HL_BLOCK `non_reverting` pattern is the precedent).

### 3.2 Version negotiation for consumers

`schema_version` present → v1 envelope. Absent → v0 inline (event_type = `action`,
timestamp = `bar_ts`, payload = remaining keys). One shared reader implements this once
(inside the §5 tool, importable: `load_recycle_events(path) -> list[dict-v1]` — v0 rows
up-converted in memory, never on disk).

---

## 4 · Skill integration (Task 4 — proposal text, lands via the friction-edit protocol)

- **hypothesis-testing §4 (Analyse):** add one bullet — *"When the hypothesis concerns
  entry filtering, population characterization, relocation effects, or detector
  overlap, Stage-4 analysis includes the telemetry artifacts
  (`raw/recycle_events.jsonl`, summarized via `tools/summarize_recycle_events.py`) —
  the blocked/affected population is evidence, not a diagnostic."*
- **execute-directives (Step 5/8 completion):** one note — *"Basket runs may have
  persisted per-event rule telemetry (`raw/recycle_events.jsonl`). For research
  hypotheses, review it before concluding; it is part of the run's evidence."*
- **generate-directives:** one line under doctrine — *"Telemetry requirements originate
  from RULE design (what the rule emits), never from directive generation; a directive
  cannot create or suppress telemetry."*

---

## 5 · Summary utility — `tools/summarize_recycle_events.py` (Task 5 — SPEC ONLY)

**Purpose:** answer population questions without hand-rolled JSONL scans (this arc
required three).

**Inputs (one of):** `--series <tag>` (anchored cohort match, both ledger sheets — the
`resolve_baseline` matching semantics), `--directive <id>`, `--run-dir <path>`.
**Options:** `--event-type <T>` filter · `--by-class` (pair-class split via the shared
taxonomy) · `--csv <out>` (tidy per-event rows for downstream) · `--fields` (explicit
payload fields; default auto-detect).

**Output (per event_type):** count, runs-covered/runs-with-events, numeric payload
fields → p05/p25/p50/p75/p95, boolean/categorical fields → shares. Example:

```text
GP_ZCRS_CXN1_Z25_LM20  (475 runs, 460 with events)
MOVE_BLOCK: count=2564   mm p25/p50/p95 = 2.25/2.62/4.89   leg: 54% non-FX
HL_BLOCK  : (none in this cohort)
```

**Contracts:** read-only; v0+v1 via the shared reader; absent files = silently
zero-coverage (reported in the runs-covered line, never an error); pooled-vs-class
output mirrors the Simpson-trap discipline. **Non-goals:** no plotting, no DB writes,
no cross-cohort joins (overlap analysis stays a documented recipe on top of `--csv`).

---

## 6 · Research-continuity doctrine + baseline resolution (Task 6 + Deliverable 6)

**Doctrine update (RESOLVE_BASELINE_SPEC + resolver memory):** a reproducible research
baseline = **directive seed + rule code + canonical metrics + telemetry artifacts
(when applicable)** — preserving "why was this concluded", not only "what happened".

**Recommendation on baseline resolution: YES, additively and lazily.** Add a
`reports.recycle_events` entry (path | `ABSENT`) to `BaselineReference` — pure pointer,
graceful for pre-telemetry runs, no metric computation. Defer wiring until schema v1
lands so resolver and writer integrate once. Telemetry must NOT gate resolution
(`ABSENT` is informative, never a failure) — same graceful-degradation doctrine as
seeds/metrics.

---

## 7 · Migration strategy (Deliverable 5)

1. **Phase 0 (this doc):** approve governance + schema; no code.
2. **Phase 1 (writer):** envelope stamping in `_write_recycle_events` (+ tests:
   envelope on every line, order/count vs `recycle_event_count`, v0 reader
   up-conversion). New runs emit v1. ~30 lines, one chokepoint.
3. **Phase 2 (consumer):** build `summarize_recycle_events.py` per §5 spec + shared
   reader; smoke it against the three v0 cohorts on disk.
4. **Phase 3 (skills + doctrine):** the three skill edits (§4) + RESOLVE_BASELINE_SPEC
   note + resolver `reports.recycle_events` pointer.
5. **Never:** backfill, rewrite, or version-bump historical artifacts.

**Success-criteria audit** (operator's four questions):
- *"Which entries did HF55 remove?"* — artifact-absent era: answerable by deterministic
  recomputation only (documented fallback, §2). Honest limitation, stated.
- *"Why did HL120 fail corpus-wide?"* — answered TODAY from v0 artifacts (70%
  non-reverting blocks, distinct population) — the arc that motivated this directive.
- *"LM20 ∩ HF60 overlap?"* — `--csv` exports joined on (directive, timestamp) — recipe
  documented with the tool.
- *"Characterize before launching a cohort?"* — yes for any post-telemetry hypothesis;
  pre-telemetry baselines via recomputation.
- *"Why was this branch CLOSED?"* (operator-added criterion) — closure reasoning must be
  reconstructable from artifacts alone: e.g. HL120 closed because telemetry showed its
  blocks were 70% non-reverting windows — a mostly-healthy population distinct from the
  Hurst one; LM20 advanced because pooled results improved while tails were preserved.
  At ~2,000 authentic backtests per session, preserving the REASONING now outweighs
  making the pipeline faster.

---

## 8 · Approval gates

| Item | Touches | Gate |
|---|---|---|
| Governance + schema (this doc §1–§3) | docs only | operator approval of this proposal |
| Writer envelope (Phase 1) | `tools/basket_report.py` (protected) | separate explicit approval |
| Summary tool (Phase 2) | new `tools/` file (protected) | separate explicit approval |
| Skill edits (Phase 3) | `.claude/skills/` (protected) | friction-protocol per-item approval |
| Resolver pointer (Phase 3) | `tools/resolve_baseline.py` (protected) | separate explicit approval |
