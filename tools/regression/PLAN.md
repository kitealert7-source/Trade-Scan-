# Regression Harness — Implementation Plan

**Status:** Plan only — no code yet. Approved implementation proceeds in phases from §9.
**Scope constraint:** small and simple, 4 scenarios, <60s runtime. Expected size ~350–450 LOC — no artificial compression; prefer clarity over a target line count.
**Goal:** Convert manual refactor validation into a single-command PASS/FAIL safety net detecting determinism drift, authority drift, and output corruption across capital / portfolio / report / promote layers.

**Revision v2 (tightened):** Excel dropped from report layer (DB is source of truth). `--update-baseline` now gated behind `--force` with mandatory diff preview. YAML compared parsed + normalized, not raw text. Hard cap of 20 aggregate failures to prevent diff storms.

---

## 1. Baseline Strategy

**Location:** `tools/regression/baselines/` (git-tracked, small, deterministic)

```
tools/regression/
  baselines/
    capital/
      <DIRECTIVE_ID>/
        inputs/
          trades_tradelevel.csv          # frozen Stage-1 output
          broker_specs.json              # frozen broker cache
        golden/
          profile_comparison.json
          REAL_MODEL_V1/trades_enriched.csv
          REAL_MODEL_V1/capital_metrics.json
          signal_hash.txt                # 16-char SHA-256
    portfolio/
      <PF_ID>/
        inputs/
          run_ids.json                   # frozen constituent runs
          symbol_trades/<SYM>.csv        # per-symbol golden trades
        golden/
          portfolio_metrics.json
          master_portfolio_sheet_row.json
          deployed_profile.txt
    report/
      <RUN_ID>/
        inputs/
          ledger.db                      # seeded SQLite (single directive)
        golden/
          report.md                      # normalized (DB->Markdown projection)
          # NOTE: Excel intentionally excluded — DB is source of truth, and
          # Excel formatting is covered separately by verify_formatting.py.
    promote/
      <STRATEGY_ID>/
        inputs/
          portfolio_evaluation_snapshot.json
          portfolio.yaml                 # pre-promote
        golden/
          portfolio.yaml.after           # post-promote
          audit_log.jsonl                # normalized
          gate_results.json
```

**Size budget:** < 2 MB total. Curate ONE directive per layer — 50–100 trades, 2–3 symbols max. Reuse scenarios from `outputs/refactor_baseline/` by distilling the smallest usable subset.

**Artifact selection criteria:** only files where business correctness is observable (metrics, selection, ledger rows, gate decisions). Exclude plots, formatted Excel, and anything requiring ground-truth human judgment.

---

## 2. Test Scenario Design (one per layer)

| Scenario | Layer | Choke-Point Validated | Why Sufficient |
|---|---|---|---|
| **capital_replay** | capital | `compute_signal_hash` + `PortfolioState.process_entry` + broker-spec cache | Single deterministic run exercises hash generation, lot resolution, all 3 retail profiles, and JSON emission. Any break in determinism or profile math fails. |
| **portfolio_select** | portfolio | `_resolve_deployed_profile` + `update_master_portfolio_ledger` | Composite PF with >=2 symbols forces Step 7 selection path + ledger append. Validates authority + idempotency contract. |
| **report_project** | report | `_collect_symbol_payloads` -> `_build_*_section` -> `_write_markdown_reports` | Seeded DB -> rendered report catches any DB->Markdown projection drift. Single directive sufficient because builders are pure functions of DB state. |
| **promote_gate** | promote | gate evaluation + `yaml_writer` + audit append | Dry-run a known-passing strategy against frozen snapshot; assert YAML diff + audit entries match. Validates governance invariants without touching real vault. |

**Coverage rationale:** Each layer has a single write-authority or projection choke-point. One scenario per choke-point catches the regression class; more scenarios add runtime without proportional safety.

---

## 3. Comparison Strategy

| Artifact | Comparator | Mode |
|---|---|---|
| CSV | `pandas.read_csv` -> sort by deterministic key -> `DataFrame.equals` | **Strict** for strings/ints; numeric floats with `rtol=1e-9, atol=1e-12` |
| JSON | Recursive dict compare; sort lists flagged as sets (e.g., `constituent_run_ids`) | **Strict** for scalars; **normalized** for list-as-set fields |
| JSONL (audit logs) | Parse per-line -> drop/replace ephemeral fields -> line-by-line | **Normalized** for `ts`, `run_id` (if wall-clock) |
| Markdown | Collapse trailing whitespace, normalize timestamps to `<NORMALIZED>`, replace `PROJECT_ROOT` path prefix -> `difflib.unified_diff` | **Normalized** |
| YAML (e.g. `portfolio.yaml`) | `yaml.safe_load` -> recursive dict compare (key order irrelevant) | **Parsed + normalized** — never raw text compare |
| SQLite | Compare table dumps (ordered by PK) | **Strict** |

**Excel intentionally omitted.** DB is the source of truth; Excel is a derived projection and its formatting is already covered by `verify_formatting.py`. Comparing `.xlsx` would add noise (styling, column widths, conditional formats) without catching business-logic regressions.

**Strict invariants (must match exactly):**
- All numeric metrics (PnL, Sharpe, expectancy, etc.)
- `deployed_profile` selection
- `signal_hash` (16-char prefix)
- Gate pass/fail decisions
- Ledger row field count + identity fields

**Normalized fields (allowed adjustments):**
- Wall-clock timestamps -> `<NORMALIZED>`
- Absolute paths -> `<PROJECT_ROOT>`
- Python set iteration order -> sort before serialize
- Run IDs if timestamp-derived -> `<RUN_ID>`

---

## 4. Harness Structure

```
tools/regression/
  __init__.py
  cli.py                    # python -m tools.regression.cli [--layer capital|...] [--update-baseline --force]
  runner.py                 # orchestrates scenarios, aggregates results
  compare.py                # comparator primitives (csv, json, jsonl, md, yaml, sqlite)
  normalize.py              # timestamp/path/set-order normalization
  scenarios/
    __init__.py
    capital_replay.py       # def run(tmp_dir) -> list[Result]
    portfolio_select.py
    report_project.py
    promote_gate.py
  baselines/                # golden inputs + outputs (git-tracked)
  tmp/                      # transient workspace (gitignored)
  README.md                 # "how to add a scenario" + "how to update baselines"
```

**Responsibilities:**
- `cli.py`: argparse, flags, exit codes (0=PASS, 1=FAIL)
- `runner.py`: discover scenarios, create tmp workspace, run each, collect `Result` dataclasses, print summary table
- `compare.py`: pure comparator functions returning `(bool, diff_text)`
- `scenarios/*.py`: each exports a `run(tmp_dir, baseline_dir) -> list[Result]`

**`Result` shape:** `Result(scenario: str, artifact: str, passed: bool, diff: str | None)` — that's the entire framework.

**Output format:**
```
REGRESSION HARNESS
==================
capital_replay      : 4/4  PASS
portfolio_select    : 3/3  PASS
report_project      : 1/2  FAIL
promote_gate        : 2/2  PASS
--------------------------------
TOTAL: 10/11 PASS, 1 FAIL
See: tools/regression/tmp/report_project/DIFF_report.md
```

---

## 5. Execution Flow

1. **Setup:** `runner.py` clears `tmp/`, creates per-scenario subdirs.
2. **Scenario discovery:** import everything under `scenarios/`, call `run(tmp_dir, baseline_dir)`.
3. **Per-scenario sequence:**
   a. Copy `baselines/<layer>/<ID>/inputs/` -> `tmp/<scenario>/inputs/`
   b. Execute the system-under-test (import tools directly — no subprocess unless required for isolation)
   c. For each golden artifact, run corresponding comparator
   d. Return list of `Result`s
4. **Aggregate:** collect all results across scenarios, print summary table, write diffs to `tmp/<scenario>/DIFF_*` files.
5. **Exit:** `sys.exit(0 if all_passed else 1)`.

**Fail-fast vs aggregate:** **Aggregate within the failure cap.** Scenarios are independent (separate baselines), so running all yields more diagnostic value than stopping at first failure. Individual comparator failures within a scenario also aggregate.

**Failure cap (MAX_FAILURES = 20):** If total failures across all scenarios reach 20, abort remaining comparators and print `[ABORTED] failure cap reached — fix upstream breakage first`. This prevents a single broken layer (e.g. a renamed field) from producing hundreds of noisy diffs. The cap is applied at the comparator level, not the scenario level — one broken CSV with 500 mismatched rows still counts as 1 failure (the comparator already handles internal row-level summarization).

---

## 6. Determinism Handling

**Known non-determinisms (confirmed during recent refactor):**

| Source | Where It Shows | Normalization |
|---|---|---|
| `PYTHONHASHSEED` set iteration | `capital_wrapper` stdout (unique_hashes print), JSON lists derived from sets | Sort lists before serializing in goldens; in comparators, treat flagged fields as sets |
| Wall-clock timestamps | `generated_at` in JSON, report headers, audit log `ts` | Strip/replace with `<NORMALIZED>` in both sides before compare |
| Absolute paths | Strategy pointer files, report references | Replace `PROJECT_ROOT` prefix with `<PROJECT_ROOT>` |
| matplotlib font/backend warnings | stderr during plotting | Discard stderr OR disable plotting via `MPLBACKEND=Agg` + skip chart generation in scenarios (see §7) |

**Must remain strictly identical:**
- `compute_signal_hash` output (16-char SHA-256) — any mismatch = engine determinism broken
- All metric floats within tolerance (`rtol=1e-9`)
- `deployed_profile` string
- Gate pass/fail booleans
- Ledger row field values (except timestamps)

**Rule:** If a field is non-deterministic, either (a) normalize it consistently or (b) exclude it from the golden. Never compare a field whose variation is benign without normalization — it produces flaky tests.

---

## 7. Performance Considerations

**Per-scenario budget:** 15s target, 30s hard cap.

**Keep fast:**
- Capital: 3-month window, 1 symbol, ~50 trades (reuse smallest directive from `outputs/refactor_baseline/capital/`)
- Portfolio: 2–3 symbols, pre-computed trade CSVs (skip Stage-1 replay)
- Report: seed SQLite directly from JSON fixtures (skip stage2/stage3 recompilation)
- Promote: dry-run mode against sandboxed `portfolio.yaml` copy (no real vault snapshot)

**Disable:**
- Chart/plot generation (set env var or patch `generate_charts` to no-op)
- Excel formatting (compare raw values only)
- Full DRY_RUN_VAULT snapshots
- Any MT5 / broker live calls (use frozen `broker_specs.json`)

**Do NOT include:**
- End-to-end pipeline runs (`run_pipeline.py --all`) — too slow, scope creep
- Data validation against Anti_Gravity_DATA_ROOT
- TS_Execution contract checks (separate concern)
- Lint hooks (already pre-commit)
- Robustness suite replication (already a CLI)

**Total runtime target:** < 60s cold, < 30s warm.

---

## 8. Failure Reporting

**Per-mismatch format:**
```
[FAIL] portfolio_select::master_portfolio_sheet_row.json
  path: root.deployed_profile
  expected: "REAL_MODEL_V1"
  got:      "FIXED_USD_V1"
```

For CSV numeric drift:
```
[FAIL] capital_replay::REAL_MODEL_V1/trades_enriched.csv
  col 'pnl_usd' row 17: expected 123.45000, got 123.46001 (rel_diff=8.1e-5, tol=1e-9)
  2 other rows differ (see tmp/capital_replay/DIFF_trades_enriched.csv)
```

For markdown/jsonl:
```
[FAIL] report_project::report.md
  unified diff (first 20 lines at tmp/report_project/DIFF_report.md):
  @@ -42,3 +42,3 @@
  - Total Trades: 127
  + Total Trades: 128
```

**Noise control:**
- Truncate inline diff at 20 lines; full diff written to `tmp/<scenario>/DIFF_<artifact>`
- Summary table at end groups by scenario (one line per scenario)
- Exit code is binary; detail is in artifacts for triage

**`--update-baseline` mode (SAFEGUARDED):** Overwriting goldens is dangerous — a casual rebaseline can permanently erase a real bug. Two-step flow:

1. `python -m tools.regression.cli --update-baseline` (dry-run):
   - Runs all scenarios
   - Prints full diff summary per artifact that would change
   - Prints total artifact count about to be overwritten
   - Writes nothing — exits 0
2. `python -m tools.regression.cli --update-baseline --force`:
   - Required explicit confirmation flag
   - Only after operator has reviewed the dry-run output
   - Copies `tmp/<scenario>/*` over `baselines/<layer>/<ID>/golden/`
   - Appends a rebaseline record to `tools/regression/baselines/REBASELINE_LOG.md` (timestamp, scenarios touched, operator)
   - Exits 0 on success

**Never auto-accept.** Without `--force`, `--update-baseline` is strictly a preview. This prevents "green by overwrite" — the anti-pattern where failing tests get rebased instead of investigated.

---

## 9. Future Extensions

**CI integration:** Add pre-merge hook: `python -m tools.regression.cli`. Fail PR if any scenario regresses. Baselines committed in-tree keep it hermetic — no external fixtures. One GitHub Actions step, ~60s in CI.

**Adding scenarios safely:** Drop a new file into `scenarios/` implementing `run(tmp_dir, baseline_dir) -> list[Result]`; add corresponding `baselines/<layer>/<ID>/` folder. Runner auto-discovers via `pkgutil.iter_modules`. No central registration needed. Document the pattern in `tools/regression/README.md`.

---

## Summary — Fit Against Constraints

| Constraint | Fit |
|---|---|
| Small and simple | Realistic ~350–450 LOC across runner + compare + normalize + 4 scenarios. Not artificially compressed — clarity over line count. |
| 3–4 scenarios | Exactly 4 — one per layer. |
| <60s runtime | Achievable with small fixtures + skipped plotting. |
| System-level, not unit | All 4 scenarios exercise the layer's public choke-point. |
| Detect determinism drift | Signal hash + strict numeric compare. |
| Detect authority drift | `deployed_profile` + ledger row compare. |
| Detect output corruption | Markdown/JSON/CSV artifact compare. |
| Safe rebaseline | `--force` gate + dry-run diff preview + rebaseline log. |
| Noise cap | Hard stop at 20 failures prevents diff storms. |

**Next step on approval:** Implement in phases — (1) `compare.py` + `normalize.py` + `runner.py` skeleton, (2) `capital_replay` scenario + baseline distillation, (3) remaining three scenarios, (4) CI wire-up.
