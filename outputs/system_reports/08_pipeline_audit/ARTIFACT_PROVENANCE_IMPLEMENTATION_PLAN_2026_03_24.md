# Artifact Provenance — Implementation Plan
**Type:** Surgical fix plan — no architecture changes
**Date:** 2026-03-24
**Scope:** Close 5 confirmed gaps from ARTIFACT_STORAGE_AUDIT_2026_03_24.md
**Status:** PLAN ONLY — not implemented

---

## 1. Pipeline Map

Five stages identified. Injection points are mapped to exact files and line numbers.

| # | Stage | File | Responsibility |
|---|---|---|---|
| 0 | Directive parsing + run_id generation | `tools/pipeline_utils.py:208` | `generate_run_id()` — parses directive YAML, computes `content_hash` (SHA256 of legacy flat config) |
| 1 | Stage-1 backtest execution | `tools/run_stage1.py:344` | `emit_result()` — runs engine, builds RawTradeRecord list, constructs Stage1Metadata |
| 2 | Artifact emission | `engine_dev/universal_research_engine/v1_5_3/execution_emitter_stage1.py:307` | `emit_stage1()` — writes all result CSVs + `run_metadata.json` to tmp dir |
| 3 | Post-emission patch (PATCH 3) | `tools/run_stage1.py:562` | Enriches `RUNS_DIR/run_id/data/run_metadata.json` with `content_hash`, `lineage_string`, `trend_filter_enabled` |
| 4 | UI view copy | `tools/run_stage1.py:547-556` | Copies artifacts from tmp to `BACKTESTS_DIR/{strategy}_{symbol}/` — runs BEFORE PATCH 3 |
| 5 | Run state + registry update | `tools/orchestration/stage_symbol_execution.py:178` | Marks run STAGE_1_COMPLETE in run_registry.json |

### Critical Ordering Issue (Root Cause of Gap A)

```
emit_stage1()              → writes run_metadata.json (no provenance fields)
    ↓
shutil.copy2() to BACKTESTS_DIR  ← copy happens HERE (no content_hash yet)
    ↓
PATCH 3 enriches RUNS_DIR/run_metadata.json  ← content_hash added HERE (too late for BACKTESTS_DIR)
```

`content_hash` already exists in `RUNS_DIR` — it is NOT missing from the system, only from the `BACKTESTS_DIR` view that all reporting tools read.

---

## 2. Insertion Points

### A — config_hash in BACKTESTS_DIR
- **Root cause:** PATCH 3 enriches only `RUNS_DIR`, not `BACKTESTS_DIR`
- **Data already available:** `content_hash` is a parameter of `emit_result()` (line 344 signature)
- **Injection point:** `tools/run_stage1.py` — after PATCH 3 block (after line 593), add a mirror write to `BACKTESTS_DIR/{strategy}_{symbol}/metadata/run_metadata.json`
- **Estimated lines:** 12

### B — code_version (git commit)
- **Currently present:** nowhere in pipeline
- **Pattern already exists:** `backup_dryrun_strategies.py:_git_commit()` uses `subprocess.run(["git", "rev-parse", "HEAD"])`
- **Injection point:** `tools/run_stage1.py` — top of `emit_result()` function, capture once. Include in PATCH 3 block and in mirror write
- **Fallback:** `"unknown"` if git unavailable (identical to existing pattern)
- **Estimated lines:** 8 (helper reuse + 1 field in PATCH 3)

### C — execution_model
- **order_type:** already in directive YAML (`order_placement.type`)
- **slippage_model:** tracked per-trade as `entry_slippage` in `results_tradelevel.csv` — no engine-level model parameter exists; correct label is `"actual_per_trade"` (not a fixed model)
- **spread_model:** not modeled — backtesting uses raw prices with no spread applied; correct label is `"none_applied"`
- **Data source:** `directive_content` string is already passed to `emit_result()`. One `yaml.safe_load(directive_content)` call extracts `order_placement.type`
- **Injection point:** `tools/run_stage1.py` — inside PATCH 3 block, append `execution_model` sub-dict alongside `content_hash`
- **Estimated lines:** 12

### D — Registry / index.csv
- **Currently:** no global index — `tools/system_registry.py` maintains only per-directive `run_registry.json` files
- **New file:** `TradeScan_State/research/index.csv` (append-only)
- **Data source:** `run_metadata.json` + `results_standard.csv` — both already written and in `BACKTESTS_DIR` by the time `STAGE_1_COMPLETE` is set
- **Injection point:** `tools/orchestration/stage_symbol_execution.py:179` — immediately after `transition_run_state(rid, "STAGE_1_COMPLETE")`, call `_append_to_index()`
- **New module:** `tools/run_index.py` (~35 lines) — single function, append-only CSV write
- **Failure safety:** wrapped in `try/except` — index write failure DOES NOT block STAGE_1_COMPLETE
- **Estimated lines:** 35 (new module) + 5 (call site)

### E — INVALID marker in BACKTESTS_DIR
- **Currently:** `status_no_trades.json` is written to `RUNS_DIR/run_id/` (line 170) but NOT copied to `BACKTESTS_DIR/{strategy}_{symbol}/`
- **Injection point:** `tools/orchestration/stage_symbol_execution.py:168-170` — add copy of marker to `BACKTESTS_DIR` raw dir at same location where it is written to RUNS_DIR
- **Estimated lines:** 5

---

## 3. Change Specification

### CHANGE 1 — `tools/run_stage1.py`
**Trigger:** Every successful Stage-1 run
**Modified function:** `emit_result()` (line 344)

```
# At top of emit_result():
git_commit = _git_commit(PROJECT_ROOT)   # ~5 lines — reuse pattern from backup_dryrun_strategies.py

# In PATCH 3 block (after line 579, before f.seek(0)):
data['git_commit']       = git_commit
data['execution_model']  = {
    'order_type':       yaml.safe_load(directive_content)
                            .get('order_placement', {}).get('type', 'market'),
    'execution_timing': yaml.safe_load(directive_content)
                            .get('order_placement', {}).get('execution_timing', 'next_bar_open'),
    'slippage_model':   'actual_per_trade',   # tracked in results_tradelevel.csv entry_slippage
    'spread_model':     'none_applied',        # no spread model in engine v1.5.3
}

# After PATCH 3 block (after line 593) — mirror to BACKTESTS_DIR:
ui_meta_run_metadata = ui_meta_dir / "run_metadata.json"
if ui_meta_run_metadata.exists():
    with open(ui_meta_run_metadata, 'r+', encoding='utf-8') as f:
        ui_data = json.load(f)
        ui_data['content_hash']    = content_hash
        ui_data['git_commit']      = git_commit
        ui_data['execution_model'] = data['execution_model']
        ui_data['schema_version']  = "1.3.0"
        f.seek(0); json.dump(ui_data, f, indent=2); f.truncate()
```

**Total new lines in run_stage1.py:** ~28
**Risk:** Low — additive only, no logic changes

---

### CHANGE 2 — `tools/run_index.py` (NEW FILE)
**Trigger:** Called from stage_symbol_execution.py after STAGE_1_COMPLETE
**Purpose:** Append-only global index for discoverability

```python
"""
run_index.py — Append-only global run index.
Writes one row per completed Stage-1 run to TradeScan_State/research/index.csv
Failure is non-blocking — never raises.
"""
import csv, json
from pathlib import Path
from config.state_paths import BACKTESTS_DIR, STATE_ROOT

INDEX_PATH = STATE_ROOT / "research" / "index.csv"
INDEX_FIELDS = [
    "run_id", "strategy_id", "symbol", "timeframe",
    "date_start", "date_end",
    "profit_factor", "max_drawdown_pct", "net_pnl_usd", "total_trades",
    "win_rate", "content_hash", "git_commit", "execution_timestamp_utc",
]

def append_run_to_index(strategy_id: str, symbol: str) -> None:
    try:
        folder    = BACKTESTS_DIR / f"{strategy_id}_{symbol}"
        meta      = json.loads((folder / "metadata" / "run_metadata.json").read_text())
        std_rows  = list(csv.DictReader((folder / "raw" / "results_standard.csv").open()))
        risk_rows = list(csv.DictReader((folder / "raw" / "results_risk.csv").open()))
        if not std_rows or not risk_rows:
            return
        s = std_rows[0]; r = risk_rows[0]

        row = {
            "run_id":                   meta.get("run_id", ""),
            "strategy_id":              strategy_id,
            "symbol":                   symbol,
            "timeframe":                meta.get("timeframe", ""),
            "date_start":               meta.get("date_range", {}).get("start", ""),
            "date_end":                 meta.get("date_range", {}).get("end", ""),
            "profit_factor":            s.get("profit_factor", ""),
            "max_drawdown_pct":         r.get("max_drawdown_pct", ""),
            "net_pnl_usd":              s.get("net_pnl_usd", ""),
            "total_trades":             s.get("trade_count", ""),
            "win_rate":                 s.get("win_rate", ""),
            "content_hash":             meta.get("content_hash", ""),
            "git_commit":               meta.get("git_commit", ""),
            "execution_timestamp_utc":  meta.get("execution_timestamp_utc", ""),
        }

        write_header = not INDEX_PATH.exists()
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"[INDEX] Non-blocking write failure: {e}")
```

**Total lines:** ~45
**Risk:** Zero — isolated module, non-blocking, no existing code modified except call site

---

### CHANGE 3 — `tools/orchestration/stage_symbol_execution.py`
**Two additions:**

**3a — Call index append after STAGE_1_COMPLETE (line 178-179):**
```python
# After: transition_run_state(rid, "STAGE_1_COMPLETE")
try:
    from tools.run_index import append_run_to_index
    append_run_to_index(clean_id, symbol)
except Exception as idx_err:
    print(f"[INDEX] append failed (non-blocking): {idx_err}")
```
**Lines:** 5

**3b — Mirror status_no_trades.json to BACKTESTS_DIR (at line 168-170):**
```python
# After existing: write status_no_trades.json to RUNS_DIR
# Add:
no_trades_ui = BACKTESTS_DIR / f"{clean_id}_{symbol}" / "raw" / "status_no_trades.json"
no_trades_ui.parent.mkdir(parents=True, exist_ok=True)
with open(no_trades_ui, "w", encoding="utf-8") as mf:
    json.dump(marker, mf, indent=2)
```
**Lines:** 4

---

## 4. Implementation Order

Each step is independently deployable. Later steps depend on earlier ones only for full effect, not for correctness.

| Order | Step | Files Touched | Blocks Pipeline if Fails? |
|---|---|---|---|
| 1 | Add `_git_commit()` helper + inject `git_commit` in PATCH 3 | `run_stage1.py` | No — wrapped in try |
| 2 | Inject `execution_model` block in PATCH 3 | `run_stage1.py` | No — additive |
| 3 | Mirror `content_hash` + `git_commit` + `execution_model` to BACKTESTS_DIR | `run_stage1.py` | No — separate write block |
| 4 | Create `tools/run_index.py` | New file | N/A |
| 5 | Add `append_run_to_index()` call in `stage_symbol_execution.py` | `stage_symbol_execution.py` | No — try/except |
| 6 | Mirror `status_no_trades.json` to BACKTESTS_DIR | `stage_symbol_execution.py` | No — additive |

---

## 5. Backward Compatibility

| Population | Treatment | Rationale |
|---|---|---|
| 223 existing `BACKTESTS_DIR` folders | **Ignored** — no backfill | Missing fields treated as absent. Do NOT guess git_commit or execution_model for past runs. |
| 169 `RUNS_DIR` folders with PATCH 3 | **Already have** `content_hash` + `lineage_string` | No action needed |
| 54 `PF_*` portfolio folders | **Out of scope** | These are downstream aggregates, not direct Stage-1 outputs. Fix requires separate audit of capital_wrapper.py |
| `schema_version` | Bump to `"1.3.0"` on enriched writes | New runs identifiable by schema version. Existing runs remain at `"1.2.0"` |
| `index.csv` | Starts empty — only new runs appear | Backfill of 223 existing runs is a separate optional one-time script (not part of this plan) |

---

## 6. Data Flow Consistency Check

| Constraint | Status |
|---|---|
| No recomputation of metrics | ✅ All data read from already-written files |
| No duplication of large data | ✅ index.csv stores only scalar metrics, not CSVs |
| No dependency on future stages | ✅ All injections occur at Stage-1 completion |
| No circular dependencies | ✅ run_index.py has no imports back to run_stage1.py |
| Registry failure blocks pipeline | ✅ No — all new writes in try/except |
| Corruption of existing artifacts | ✅ No — BACKTESTS_DIR write is r+, not overwrite |

---

## 7. Risk Assessment

```json
{
  "implementation_risk": "LOW",
  "rationale": [
    "content_hash already computed — no new logic, just propagation",
    "git_commit capture is a stdlib subprocess call with known fallback",
    "execution_model fields are static constants (not computed)",
    "index.csv is append-only with non-blocking failure handling",
    "no engine code touched",
    "no strategy code touched",
    "no existing artifact overwritten"
  ],
  "highest_risk_point": "PATCH 3 r+ file edit in run_stage1.py — seek/truncate pattern already in use at line 591, so pattern is proven",
  "engine_frozen": true,
  "strategy_untouched": true,
  "results_unmodified": true
}
```

---

## 8. Files Modified / Created

| File | Type | Lines Changed |
|---|---|---|
| `tools/run_stage1.py` | Modified | ~28 |
| `tools/run_index.py` | **New** | ~45 |
| `tools/orchestration/stage_symbol_execution.py` | Modified | ~9 |

**Total: 3 files, ~82 lines. Zero engine files. Zero strategy files.**

---

## 9. Verification (Post-Implementation)

Run any directive through the pipeline, then verify:

```bash
# 1. content_hash in BACKTESTS_DIR
python -c "import json; m=json.load(open(r'TradeScan_State\backtests\{ID}_{SYM}\metadata\run_metadata.json')); print(m.get('content_hash','MISSING'), m.get('git_commit','MISSING'))"

# 2. execution_model block present
python -c "import json; m=json.load(open(r'...\run_metadata.json')); print(m.get('execution_model','MISSING'))"

# 3. index.csv created and populated
python -c "import csv; rows=list(csv.DictReader(open(r'TradeScan_State\research\index.csv'))); print(f'{len(rows)} rows'); print(rows[-1])"

# 4. Discoverability query — no folder scanning needed
python -c "
import csv
rows = list(csv.DictReader(open(r'TradeScan_State\research\index.csv')))
hits = [r for r in rows if float(r['profit_factor'] or 0)>1.5 and float(r['max_drawdown_pct'] or 99)<10]
print(f'{len(hits)} runs match PF>1.5 DD<10%')
for r in hits: print(r['strategy_id'], r['symbol'], r['profit_factor'], r['max_drawdown_pct'])
"

# 5. INVALID marker in BACKTESTS_DIR (only visible on a run that produces no trades)
ls TradeScan_State\backtests\{no_trade_strategy}_{symbol}\raw\status_no_trades.json
```

Expected after verification:
- `content_hash`: 8-char hex string
- `git_commit`: 40-char hex string or `"unknown"`
- `execution_model`: dict with order_type, slippage_model, spread_model
- `index.csv`: 1+ rows with all 14 columns populated
- Query answer returned in O(1) — no folder scan
