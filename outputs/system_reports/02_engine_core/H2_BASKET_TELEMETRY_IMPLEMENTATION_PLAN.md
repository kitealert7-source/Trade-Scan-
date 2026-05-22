# H2 Basket Telemetry — Implementation Plan

**Status:** APPROVED — operator 2026-05-16. Two modifications applied (see §0.5). Phase 1 coding may begin.
**Audit reference:** [outputs/H2_TELEMETRY_AUDIT.md](H2_TELEMETRY_AUDIT.md) (closed 2026-05-16, schema locked at top)
**Author session:** 2026-05-16
**Plan scope:** code patch + champion validation. No backfill — that gates on validation pass.

---

## 0.5. Resolutions from operator review (2026-05-16)

Two modifications applied to the original draft:

**M1 — MPS summary derives from in-memory accumulator, not from re-reading the just-written parquet.** Rationale (operator): redundant disk I/O, lock contention surface, and timing-bug risk grow with multiple baskets / parallel runs / network drives. Every value MPS needs is already computed bar-by-bar in the rule; persist it both to the in-memory summary stats and to parquet, but read the in-memory copy for the MPS row. Parquet remains the durable audit trail / machine source of truth — not the immediate summary source. Architectural impact: §4 grows a new `summary_stats` accumulator owned by the rule (§4.5); §6 derivation reads `basket_result.summary_stats` instead of `pd.read_parquet(...)`.

**M2 — `H2_ENGINE_PROMOTION_PLAN.md` (LOCKED v11) update is out of scope.** Rationale (operator): that doc is architecture authority, separately locked, and politically heavier than telemetry emission. Updating it before validation passes risks a partial-update state if validation fails. Removed from this patch entirely. If validation passes and backfill is approved, the doc update is a separate session with its own approval beat. Architectural impact: §3 drops touch point #5; §9 drops Phase 8; §2 lists it explicitly as out of scope.

Operator answers to the original §12 questions:

| # | Question | Resolution |
|---|---|---|
| 1 | `peak_lots` representation in MPS | **Option A** — `peak_lots_json` string column. Dynamic columns rejected. |
| 2 | Schema version | **`1.3.0-basket`** — additive, not breaking. Not 2.0. |
| 3 | Champion set | **B1 + AJ + B2 only**. No fourth basket. |
| 4 | Backfill sequencing | **Validation report first, then backfill decision.** |
| 5 | `H2_ENGINE_PROMOTION_PLAN.md` timing | **Removed from this patch entirely** (M2 above). |
| 6 | V2 / V3 rule scope | **`H2_recycle@1` only**. No cross-rule scope expansion. |

§12 (Open questions) has been removed — all six are resolved here.

---

## 0. Prerequisites (already satisfied)

| Item | Status |
|---|---|
| Audit deliverable locked (schema, format, sequencing, backfill deferral) | ✅ |
| Engine 1.5.8 FROZEN; pipeline queue empty | ✅ (SYSTEM_STATE OK) |
| `pyarrow` already a runtime dependency (`engines/regime_state_machine.py` calls `to_parquet` / `read_parquet`) | ✅ |
| Implementation surface read end-to-end this session (5 files) | ✅ |
| Champion baskets present on disk (B1, AJ, B2) for validation runs | ✅ |

---

## 1. Locked decisions (restated from audit §"DECISIONS LOCKED")

1. **Schema** — 35 fixed + 8 per-leg columns across 7 blocks (A–G). No edits.
2. **Format** — Machine: parquet (`raw/results_basket_per_bar.parquet`). Human: extend MPS `Baskets` sheet with derived summary columns.
3. **Implementation** — This plan doc → operator approval → code patch in a separate session.
4. **Backfill of 271 historical baskets** — Deferred until emitter is proven on champions.

Format-follows-consumer rule (governing): high-volume time-series → parquet; small artifacts / legacy schemas → CSV; human summaries → XLSX; per-run reports → markdown.

---

## 2. Scope

### In scope (this patch)

- Per-bar accumulator inside `H2RecycleRule` capturing all 35+8N locked-schema columns
- Parquet write at basket close (`raw/results_basket_per_bar.parquet`)
- MPS `Baskets` sheet — append derived columns to right edge (append-only invariant preserved)
- `basket_schema_version` bump `1.2.0-basket` → `1.3.0-basket` in `run_metadata.json`
- Champion validation: B1, AJ, B2 — three reruns + cross-checks
- Tests covering schema, parity, idempotency, and MPS additive integrity

### Out of scope (deferred or separate work)

- Backfill of 271 completed basket directives — gates on champion validation pass; separate decision
- Refactor of `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` from reload+replay to parquet read — landed as a follow-up after validation proves the ledger reconciles
- Composite-equity harvest_robustness modules — landed after the ledger exists (currently blocked on the missing per-bar artifact)
- Wide-rollout to non-H2 rules (`H2RecycleRuleV2`, `V3`, future rules) — patched alongside H2 in the same code change only if scope stays small; otherwise queued as a single-rule follow-up per rule. The plan opens with H2_recycle@1 as the reference implementation; the per_bar_records contract is documented so other rules can opt in
- `tools/format_excel_artifact.py` extension to format the Baskets sheet — Phase 5b.3b territory; out of this plan
- `Strategy_Master_Filter.xlsx` integration — baskets do not flow through this ledger today; no change
- **`outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` (LOCKED v11) update** — removed from scope per operator M2. The architecture doc lock stays at v11 through this patch. If post-validation backfill is approved, a separate session updates it to v12 with the ledger schema codified.

---

## 3. Implementation surface (file → change summary)

Four touch points. Estimated total patch size: ~130 lines of production code + ~250 lines of tests.

| # | File | Change | Approximate scope |
|---|---|---|---|
| 1 | `tools/recycle_rules/h2_recycle.py` | Add `per_bar_records: list[dict]` field; add `summary_stats: dict` accumulator (updated each bar — see §4.5); add `_record_bar()` helper; instrument every early-return path in `apply()` with the right `skip_reason` value | ~100 lines (dict construction across the 9 early-return paths + running summary accumulators) |
| 2 | `tools/basket_pipeline.py` | Extend `BasketRunResult` dataclass with `per_bar_records: list[dict]` AND `summary_stats: dict` fields; populate both from `rule.per_bar_records` and `rule.summary_stats` at the bottom of `run_basket_pipeline()` | ~6 lines |
| 3 | `tools/basket_report.py` | After existing CSV writes in `write_per_window_report_artifacts()`, write `raw/results_basket_per_bar.parquet`; bump `schema_version` in `_write_run_metadata` to `1.3.0-basket`; extend `_BASKET_METRICS_GLOSSARY_EXTRA` with the new derived metrics | ~50 lines |
| 4 | `tools/portfolio/basket_ledger_writer.py` | Extend `BASKETS_SHEET_COLUMNS` (append-only, right edge) with 10 derived columns; compute them in `_build_row()` from `basket_result.summary_stats` (in-memory, **NO parquet re-read** — see §6 M1 rationale) | ~30 lines |

Files NOT modified in this patch:

- `tools/basket_runner.py` — generic orchestrator; remains rule-agnostic. The accumulator lives in the rule (Section 4 rationale).
- `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` — refactor lands in a follow-up after validation pass.
- `engines/`, `engine_dev/` — no engine change required; the ledger captures rule-side state.
- `governance/recycle_rules/registry.yaml` — rule version stays `H2_recycle@1`. The telemetry is additive, not behavioral; no version bump.
- `outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md` — LOCKED v11 stays untouched per operator M2; v12 update deferred to a separate post-validation session.

---

## 4. Component A — Per-bar accumulator (rule-owned)

### Architectural choice (opinionated)

**The accumulator lives in `H2RecycleRule`, not in `BasketRunner`.**

Rationale:
- The rule already computes every value the schema needs (lines 175–217 of [h2_recycle.py](tools/recycle_rules/h2_recycle.py)). The runner does not — adding it there would require duplicating leg-state arithmetic that already runs inside `apply()`.
- The existing `recycle_events: list[dict]` field on the rule (line 130 of [h2_recycle.py](tools/recycle_rules/h2_recycle.py)) is the precedent: rule-owned, exposed via attribute, drained by the report writer at basket close. The per-bar record list is the same shape, one cadence finer.
- Other rules (`H2RecycleRuleV2`, `V3`, future) opt in by adopting the same `per_bar_records` attribute. The runner only requires that the field exists; it does not interpret the schema.

Alternative considered (and rejected): callback-based runner-owned accumulator. Cleaner separation, but doubles the amount of state passed between runner and rule per bar and forces every rule to implement a getter. Deferred until a second rule needs the telemetry with a divergent shape.

### Schema mapping — where each column comes from

For each call to `H2RecycleRule.apply(legs, i, bar_ts)`, after the existing logic runs, append exactly one dict to `self.per_bar_records` with all 35+8N keys. The values map to existing in-memory variables:

| Block | Column | Source in `apply()` |
|---|---|---|
| **A** | `timestamp` | `bar_ts` |
| A | `directive_id`, `basket_id` | Threaded in via constructor (new constructor args, optional, default empty) |
| A | `bar_index` | `i` |
| A | `run_id` | Threaded in via constructor (new arg) |
| **B** | `floating_total_usd` | `floating_total` (line 176) |
| B | `realized_total_usd` | `self.realized_total` |
| B | `equity_total_usd` | `equity` (line 177) |
| B | `peak_equity_usd` | running max maintained as instance state `_peak_equity` (new) |
| B | `dd_from_peak_usd` | `equity - self._peak_equity` |
| B | `dd_from_peak_pct` | `dd_from_peak_usd / self._peak_equity * 100` (guard div-by-zero) |
| **C** | `margin_used_usd` | `margin_used` (line 198) |
| C | `free_margin_usd` | `equity - margin_used` |
| C | `margin_level_pct` | `equity / margin_used * 100` (guard div-by-zero → emit `inf`-safe sentinel; plan choice = NaN) |
| C | `notional_total_usd` | Compute inline: `sum(leg.lot * bar_closes[s] * 100_000 for legs)` |
| C | `leverage_effective` | `self.leverage` |
| **D** | `dd_freeze_active` | `dd_breach` (line 199) |
| D | `margin_freeze_active` | `margin_breach` (line 200) OR projected-margin breach branch (line 259) — recorded as `margin_freeze_active=True` for that bar |
| D | `regime_gate_blocked` | `factor_val < self.factor_min` (line 216) |
| D | `recycle_attempted` | `True` once execution reaches the trigger-scan block (post-freeze gates pass) |
| D | `recycle_executed` | `True` only on the path that reaches line 264+ (commit) |
| D | `harvest_triggered` | `True` only on the bar that calls `_exit_all(..., reason="TARGET")` |
| D | `engine_paused` | `False` always for H2 (no engine-pause concept in basket path). Placeholder for future. |
| D | `skip_reason` | enum derived from which early-return path fires this bar (see §4.2 below) |
| **E** | `active_legs` | `sum(1 for leg in legs if leg.state.in_pos)` |
| E | `total_lot`, `largest_leg_lot`, `smallest_leg_lot` | derive from `leg.lot` over legs |
| **F** | `leg_<i>_symbol`, `leg_<i>_side` | `leg.symbol`, `"long" if leg.direction == 1 else "short"` |
| F | `leg_<i>_lot`, `leg_<i>_avg_entry` | `leg.lot`, `leg.state.entry_price` |
| F | `leg_<i>_mark` | `bar_closes[leg.symbol]` |
| F | `leg_<i>_floating_usd` | `leg_float[leg.symbol]` (line 175) |
| F | `leg_<i>_margin_usd` | per-leg margin from `_leg_margin_usd(leg, bar_closes[leg.symbol], self.leverage)` |
| F | `leg_<i>_notional_usd` | `leg.lot * bar_closes[leg.symbol] * 100_000` (USD-quote convention; for USD-base divide by `bar_closes`) |
| **G** | `recycle_count` | running counter, incremented on `recycle_executed` |
| G | `bars_since_last_recycle` | running counter; null until first recycle, 0 on recycle bar, +1 each subsequent bar |
| G | `bars_since_last_harvest` | for single-cycle H2 = bars since first bar (= `i`); shape-preserved for future multi-harvest rules |
| G | `gate_factor_value`, `gate_factor_name` | `factor_val`, `self.factor_column` |
| G | `winner_leg_idx`, `loser_leg_idx` | filled only on `recycle_executed` bars; null otherwise |

### 4.2 `skip_reason` enum — one value per early-return path

Every `return` in `apply()` corresponds to exactly one enum value:

| `apply()` return path | `skip_reason` |
|---|---|
| Line 160 (`self.harvested`) | `HARVESTED` |
| Line 172 (`bar_closes` build raises KeyError/ValueError) | `RULE_NOT_INVOKED` |
| Line 182 (`_exit_all` on TARGET) | `NONE` and `harvest_triggered=True` (the bar where the harvest fires — not technically a skip; record it as the harvest bar) |
| Lines 184–195 (`_exit_all` on FLOOR/BLOWN/TIME) | same shape: not a skip; record as the exit bar with `harvest_triggered=True` (the schema field is exit-agnostic; document this) |
| Line 206 (dd_breach or margin_breach) | `DD_FREEZE` if `dd_breach`; `MARGIN_FREEZE` if `margin_breach` (precedence: DD_FREEZE if both) |
| Line 211 (factor column missing) | `RULE_NOT_INVOKED` (data gap; matches "engine didn't see this bar" semantics) |
| Line 215 (factor_val NaN/ParseFail) | `RULE_NOT_INVOKED` |
| Line 218 (factor below min) | `REGIME_GATE` |
| Line 231 (no winner) | `NO_WINNER` |
| Line 241 (no loser) | `NO_LOSER` |
| Line 261 (projected margin breach) | `PROJECTED_MARGIN_BREACH` |
| Line 312 (commit completes; falls through) | `NONE` |

The audit's enum includes 9 values; one combined branch in apply() (`HARVESTED` short-circuit when called on subsequent bars after harvest) produces extra rows. Decision: **do not emit per-bar records after `self.harvested = True`.** The ledger ends at the harvest bar. This matches the natural "basket lifecycle" boundary; downstream consumers can identify basket close from the last row's `harvest_triggered=True`.

### 4.3 Implementation pattern — `_record_bar()` helper

To keep `apply()` readable, the per-bar dict construction goes in a helper method on the rule:

```
def _record_bar(self, legs, i, bar_ts, *, bar_closes, leg_float,
                floating_total, equity, margin_used,
                dd_breach, margin_breach, regime_blocked, factor_val,
                skip_reason, recycle_attempted, recycle_executed,
                harvest_triggered, winner_leg_idx=None, loser_leg_idx=None) -> None:
    ...
    self.per_bar_records.append(record_dict)
```

The early-return paths in `apply()` each compute their flags, call `_record_bar(...)`, then `return`. The commit path calls `_record_bar(...)` with `recycle_executed=True` after the trade record is appended.

**No new per-bar arithmetic.** Every variable the helper needs is already computed in `apply()` for the rule's own decision logic.

### 4.4 Run-id and identity threading

`H2RecycleRule.__init__` currently does not know its `run_id` or `directive_id`. Two threading options:

**Option A (chosen):** add optional `run_id`, `directive_id`, `basket_id` constructor kwargs. `basket_pipeline._instantiate_rule()` passes them in. They default to empty strings, so existing tests that construct rules without them still pass.

**Option B (rejected):** thread them via `apply()` kwargs each bar. More invasive; changes the `BasketRule` Protocol signature (line 85 of [basket_runner.py](tools/basket_runner.py)); breaks every existing rule's apply() signature.

Option A is local and additive.

### 4.5 Summary-stats accumulator (rule-owned, in-memory)

**Per operator M1: the MPS row derives from this accumulator, not from re-reading the parquet.** Parquet remains the durable audit trail; the in-memory summary is the immediate, lock-free source for the MPS write.

New rule attribute: `summary_stats: dict[str, Any]` (alongside the existing `recycle_events` and the new `per_bar_records`). Updated inside `_record_bar()` on each call. The dict carries running aggregates — not a snapshot of any single bar:

| Key | Update rule | Final-value semantics |
|---|---|---|
| `peak_floating_dd_usd` | running `min` of `dd_from_peak_usd` over all bars seen | absolute magnitude of the worst floating drawdown the basket touched |
| `peak_floating_dd_pct` | running `min` of `dd_from_peak_pct` | same, as % of peak equity |
| `dd_freeze_count` | counter incremented on `prev_dd_freeze == False AND curr_dd_freeze == True` transition | count of dd-freeze entry events (not bar-count of freeze duration) |
| `margin_freeze_count` | same pattern for `margin_freeze_active` | analogous |
| `regime_freeze_count` | same pattern for `regime_gate_blocked` | analogous |
| `peak_margin_used_usd` | running `max` of `margin_used_usd` | max margin tied up at any bar |
| `min_margin_level_pct` | running `min` of `margin_level_pct` (skipping the div-by-zero NaN bars) | nearest the broker margin-call threshold the basket got |
| `worst_floating_at_freeze_usd` | running `min` of `floating_total_usd` ONLY on bars where any freeze flag is True | tells operator what the basket was holding when the safety brake fired |
| `peak_lots` | dict `{symbol: max_lot_seen}` updated each bar via `max` | per-leg peak lot; serialized to `peak_lots_json` for MPS |
| `final_pnl_usd` | filled exactly once at harvest (`_exit_all`) — equals harvested cash minus starting stake | total realized gain |
| `return_on_real_capital_pct` | computed at harvest as `final_pnl_usd / (2 * abs(peak_floating_dd_usd)) * 100` (guard div-by-zero → null) | capital-efficiency metric per audit §"derived columns" |

Three additional fields filled by `_exit_all()` for completeness:
- `harvest_bar_index` — the `i` at which harvest fired
- `harvest_bar_ts` — the `bar_ts` at which harvest fired
- `harvest_reason` — TARGET / FLOOR / BLOWN / TIME (mirrors `exit_reason`)

**State maintenance contract:**
- Initialized to defaults in `__post_init__` (all counts at 0; peak/min at sentinels: peak at `-inf`, min at `+inf`; `peak_lots` to empty dict; harvest fields to None)
- Updated in `_record_bar()` after `per_bar_records.append(...)` — single source of truth: the same dict that goes to parquet drives the running aggregates
- Frozen after harvest — the harvest bar's `_record_bar()` is the final update; subsequent apply() calls return early at the `if self.harvested` short-circuit before `_record_bar` is reached
- Exposed as the rule's `summary_stats` attribute; carried out via `BasketRunResult.summary_stats` (new field)

**Why not "derive from per_bar_records at end of run":** that would be a second pass over the same data. The accumulator is O(1) per bar vs O(N) at close, but the real reason is simpler: we want the MPS row to be writable even if the parquet write fails (e.g., disk error on basket close). Decoupling MPS from parquet I/O is the operator's M1 principle.

---

## 5. Component B — Parquet write (basket_report.py)

### Write location and timing

After the existing raw CSV writes in `write_per_window_report_artifacts()` (lines 622–642 of [basket_report.py](tools/basket_report.py)), before `metrics_glossary.csv`:

```
# results_basket_per_bar.parquet (NEW — machine-consumed time-series)
p = raw_dir / "results_basket_per_bar.parquet"
df_per_bar = pd.DataFrame(basket_result.per_bar_records)
_enforce_ledger_schema(df_per_bar)  # raises if schema-locked columns missing
df_per_bar.to_parquet(p, engine="pyarrow", index=False)
paths["per_bar_ledger"] = p
```

### Schema enforcement helper

`_enforce_ledger_schema(df)` is a guard. It asserts:
1. All 35 fixed columns are present.
2. Every column has the expected dtype (datetime64[ns] for timestamp, bool for the 7 boolean flags, int for `bar_index`/`active_legs`/`recycle_count`, str for `directive_id`/`basket_id`/`run_id`/`skip_reason`/`gate_factor_name`/`leg_<i>_symbol`/`leg_<i>_side`, float for everything else, nullable Int for `winner_leg_idx`/`loser_leg_idx`).
3. Per-leg columns follow the pattern `leg_0_*` through `leg_(N-1)_*` for N legs detected from the data.
4. Raises a clear error message if anything is missing or mistyped — fail-fast.

This is the schema-version contract enforcement point. Subsequent reads (harvest_robustness modules) can trust the file.

### Parquet write specifics

- `engine="pyarrow"` (already a runtime dep)
- `index=False` (timestamp is a column, not the index — matches how regime_state_machine uses parquet)
- Compression: default (snappy via pyarrow) — no override
- `dtype_backend` not specified — pandas defaults are fine
- One file per basket run; lives alongside `results_basket.csv` in `raw/`

### Schema version bump

`tools/basket_report.py::_write_run_metadata` line 331:
```
"schema_version":   "1.2.0-basket",
```
becomes:
```
"schema_version":   "1.3.0-basket",
```

The reader logic in harvest_robustness modules can branch on schema_version when needed (legacy 1.2.0 = no ledger; 1.3.0+ = ledger present).

### Glossary entries

Extend `_BASKET_METRICS_GLOSSARY_EXTRA` in [basket_report.py:61](tools/basket_report.py:61) with the new derived metrics that will surface in MPS (peak_floating_dd_usd, dd_freeze_count, etc.). Keeps glossary co-located with telemetry.

---

## 6. Component C — MPS Baskets row extension

### New derived columns (append-only at right edge of `BASKETS_SHEET_COLUMNS`)

The existing sheet columns end at `vault_path` ([basket_ledger_writer.py:71](tools/portfolio/basket_ledger_writer.py:71)). The new columns append after, preserving the existing append-only invariant pattern documented at line 54.

Final order (existing | new):

```
[existing 16 columns] +
  peak_floating_dd_usd
  peak_floating_dd_pct
  dd_freeze_count
  margin_freeze_count
  regime_freeze_count
  peak_margin_used_usd
  min_margin_level_pct
  worst_floating_at_freeze_usd
  return_on_real_capital_pct
  schema_version
```

Plus per-leg peak lots — but leg count varies across baskets (2-leg today, up to N-leg in future). Sheet schema can't have a variable column set; alternatives:

- **Option A (chosen):** emit a single `peak_lots_json` string column carrying `{"EURUSD": 0.05, "USDJPY": 0.03}` per row. Pandas + Excel both handle JSON-as-string cleanly; downstream consumers parse on read.
- **Option B (rejected):** dynamic wide columns (`peak_lot_EURUSD`, `peak_lot_USDJPY`, ...) — pollutes the sheet schema; rows with disjoint leg sets have NaN sprawl.

### Source-of-derivation (revised per operator M1 — in-memory, NOT parquet re-read)

`_build_row()` ([basket_ledger_writer.py:89](tools/portfolio/basket_ledger_writer.py:89)) extends to:

```
def _build_row(*, basket_result, run_id, directive_id, backtests_path, vault_path, df_trades=None):
    base_row = {...existing 16 columns...}
    stats = basket_result.summary_stats or {}   # rule-owned accumulator; see §4.5
    derived = {
        "peak_floating_dd_usd":         abs(stats.get("peak_floating_dd_usd")) if stats else pd.NA,
        "peak_floating_dd_pct":         abs(stats.get("peak_floating_dd_pct")) if stats else pd.NA,
        "dd_freeze_count":              stats.get("dd_freeze_count", pd.NA),
        "margin_freeze_count":          stats.get("margin_freeze_count", pd.NA),
        "regime_freeze_count":          stats.get("regime_freeze_count", pd.NA),
        "peak_margin_used_usd":         stats.get("peak_margin_used_usd", pd.NA),
        "min_margin_level_pct":         stats.get("min_margin_level_pct", pd.NA),
        "worst_floating_at_freeze_usd": stats.get("worst_floating_at_freeze_usd", pd.NA),
        "return_on_real_capital_pct":   stats.get("return_on_real_capital_pct", pd.NA),
        "peak_lots_json":               json.dumps(stats.get("peak_lots", {})) if stats else pd.NA,
        "schema_version":               "1.3.0-basket" if stats else pd.NA,
    }
    return {**base_row, **derived}
```

**No parquet read.** `basket_result.summary_stats` is populated by `run_basket_pipeline()` directly from `rule.summary_stats` — the same dict that was being updated every bar inside the apply() loop. This eliminates:
1. The disk I/O of re-reading the just-written parquet (could be 100k rows / multi-MB)
2. The lock-contention surface when multiple basket dispatches race on the same file
3. The timing-bug risk if the parquet write fails between basket close and MPS write — under the in-memory design, MPS still gets a correct row even if disk failed for parquet
4. The "what dtype did parquet round-trip this as" worry for booleans and nullable ints

The parquet file remains authoritative for **subsequent** consumers (harvest_robustness modules reading it later), but is NOT read inside the basket dispatch sequence.

**Legacy basket runs** (pre-1.3.0-basket schema, before this patch): `basket_result.summary_stats` is None / missing. The new derived columns are NaN-filled for those rows. The MPS Baskets sheet's existing append-only NaN-fill block at lines 213–224 of [basket_ledger_writer.py](tools/portfolio/basket_ledger_writer.py:213) handles this without code change — the new columns are added to the column list, and pre-existing rows get `pd.NA` on the new columns automatically.

### Append-only invariant preservation

[basket_ledger_writer.py:205-211](tools/portfolio/basket_ledger_writer.py:205-211) already enforces "same run_id can't be written twice." Unchanged. Re-running a champion basket for validation requires `tools/reset_directive.py` to clear the old run_id, same as today.

### File-lock semantics

The existing `FileLock(str(lock_path), timeout=120)` on `Master_Portfolio_Sheet.xlsx.lock` ([line 188](tools/portfolio/basket_ledger_writer.py:188)) is shared with the per-symbol writer. Plan: leave untouched. The basket row write still uses this lock. No new concurrency surface.

### Format-excel-ledgers compatibility

The format_excel_ledgers skill (and `tools/format_excel_artifact.py`) currently does NOT format the Baskets sheet (note at [basket_ledger_writer.py:235](tools/portfolio/basket_ledger_writer.py:235)). New columns inherit this status — they appear as raw values in Excel until a basket-aware formatter is added (Phase 5b.3, out of scope here).

---

## 7. Component D — Champion validation protocol

### Three baskets exercised

| Label | Directive ID | Composition | Window | Why this one |
|---|---|---|---|---|
| **B1** | `90_PORT_H2_5M_RECYCLE_S03_V1_P00` | EURUSD long + USDJPY long | 2024-09-02 → 2026-05 (~302d to harvest) | Canonical champion; the audit's sample basket. Fast harvest, full TARGET exit. |
| **AJ** | `90_PORT_H2_5M_RECYCLE_S08_V1_P00` | AUDUSD long + USDJPY long | 2024-09-02 → 2026-05 | Phase-2 candidate (recently added directive series — P00..P09 in `backtest_directives/completed/`). Different leg-pair dynamics. |
| **B2** | `90_PORT_H2_5M_RECYCLE_S05_V1_P04` | AUDUSD long + USDCAD long | 2024-09-02 → 2026-05 (~591d to harvest, USD_BASE) | Longer cycle. USD_BASE leg (USDCAD) — exercises the `_USD_BASE` PnL convention. |

These cover: TARGET exit timing (fast vs slow), USD_QUOTE+USD_QUOTE composition (B1), USD_QUOTE+USD_QUOTE (AJ), USD_QUOTE+USD_BASE (B2). The combination spans the H2 pair-convention envelope.

### Reset prerequisites

For each champion:
```
python tools/reset_directive.py <DIRECTIVE_ID> --reason "Telemetry emitter validation — purge prior run before re-run"
```
This removes the directive's run folder, MPS Baskets row, and Master Filter rows so the re-run is clean. Reset is logged to `governance/reset_audit_log.csv` per Invariant 15.

### Validation gate 1 — schema conformance

After each champion runs, the per-bar parquet is loaded and asserted against the locked schema:

```
df = pd.read_parquet(basket_dir / "raw/results_basket_per_bar.parquet")

# Fixed-column count and identity
assert set(EXPECTED_FIXED_COLS) == set(df.columns) - {c for c in df.columns if c.startswith("leg_")}

# Per-leg columns: exactly 8 * leg_count
leg_cols = [c for c in df.columns if c.startswith("leg_")]
assert len(leg_cols) == 8 * basket_leg_count

# Dtypes match the lock
assert df["timestamp"].dtype.kind == "M"
assert df["floating_total_usd"].dtype == "float64"
assert df["dd_freeze_active"].dtype == "bool"
assert df["skip_reason"].dtype == object  # str
# ... etc.

# No NaN in mandatory columns
for col in MANDATORY_NON_NULL_COLS:  # timestamp, run_id, equity_total_usd, etc.
    assert df[col].notna().all()
```

Pass condition: all assertions hold. Failure → patch is rejected; fix and re-validate.

### Validation gate 2 — internal arithmetic parity

The ledger's final values must match the existing summary CSVs (which we know are correct under the existing pipeline):

| Ledger value (at last row) | Summary CSV value | Tolerance |
|---|---|---|
| `realized_total_usd` (at bar where `harvest_triggered=True`) | `results_basket.csv :: harvested_total_usd` | exact (same float source) |
| `max(realized_total_usd)` over the ledger | not directly emitted today; cross-check against `recycle_events.jsonl :: realized_total` last value | exact |
| `min(floating_total_usd)` (worst at-bar floating) | `recycle_events.jsonl :: floating_total` min (this is a LOWER BOUND — events are sparse; ledger should be ≤ this) | ledger ≤ event-min |
| `sum(recycle_executed)` over ledger | `results_basket.csv :: recycle_event_count` | exact |
| `sum(dd_freeze_active)` (count of freeze-bars) | not currently emitted; cross-check against `rule._n_dd_freezes` (instrument-only, requires test hook) | exact |
| Per-leg `peak(leg_<i>_lot)` | `max(loser_new_lot for events where loser==symbol)` from `recycle_events.jsonl` | exact |

Pass condition: all six identities hold for all three champions.

### Validation gate 3 — reconstruction reconciliation

The legacy reconstruction module ([h2_intrabar_floating_dd.py](tools/harvest_robustness/modules/h2_intrabar_floating_dd.py)) computes per-bar floating PnL via reload+replay. With the ledger in place, its CLOSE-based result must match the ledger:

```
# Run legacy reconstruction (uses recycle_events.jsonl + 5m OHLC)
legacy_df = reconstruct_floating_close_based(directive_id, basket)

# Compare against ledger (which the rule wrote directly)
ledger_df = pd.read_parquet(basket_dir / "raw/results_basket_per_bar.parquet")

# Align on timestamp
merged = legacy_df.merge(ledger_df[["timestamp", "floating_total_usd"]],
                        on="timestamp", suffixes=("_legacy", "_ledger"))

# Close-based reconstruction and ledger should be byte-equal (same math, same bars)
assert (merged["floating_total_usd_legacy"] - merged["floating_total_usd_ledger"]).abs().max() < 1e-6
```

Pass condition: byte-equality (sub-cent absolute difference) at every bar where both have a sample. The LOW-based reconstruction variant is not compared — it's a worst-case approximation; ledger is close-based truth.

If parity fails: the patch has a persistence bug or the reconstruction had a bug now exposed. Either way, investigation before sign-off.

### Validation gate 4 — MPS row integrity

For each champion's new MPS Baskets row:
1. Run_id appears exactly once (append-only invariant)
2. All 26 columns (16 existing + 10 new) populated; only schema-allowed NaN where applicable
3. `peak_floating_dd_usd` derived from ledger equals `-min(dd_from_peak_usd)` re-computed from the parquet
4. `dd_freeze_count` derived equals `sum(dd_freeze_active.diff() == 1)` from the parquet (count of False→True transitions)

Pass condition: all four identities hold.

### Validation gate 5 — backward compatibility

A pre-1.3.0-basket run (any of the 271 already-completed baskets, e.g., B1 vault snapshot before re-run, or a fresh non-H2 basket if one exists) must still:
1. Have `schema_version == "1.2.0-basket"` in `run_metadata.json` (untouched)
2. Not have `results_basket_per_bar.parquet`
3. Be readable by the (legacy, unchanged in this patch) harvest_robustness modules
4. Appear in MPS Baskets sheet with NaN in the 10 new columns

Pass condition: legacy basket flow unchanged; new columns NaN-pad on the sheet.

### Validation deliverable

After all 5 gates pass on all 3 champions, an `outputs/H2_TELEMETRY_EMITTER_VALIDATION.md` report is written documenting:
- Each gate's pass/fail with concrete numbers (e.g., "B1: ledger row count = 62,341; aligned-index length = 62,341; ✅")
- A diff table of MPS new columns vs ledger-derived re-computation
- Sign-off recommendation: backfill GO / NO-GO

This validation report is the gate on the deferred backfill decision (audit Decision #4).

---

## 8. Test plan (unit + integration)

### New unit tests (`tests/test_h2_recycle_ledger_emit.py`)

1. `test_per_bar_records_populated` — after running H2RecycleRule on a synthetic 100-bar fixture, `rule.per_bar_records` has 100 entries (or fewer if early harvest)
2. `test_skip_reason_enum_coverage` — synthetic fixtures that force each early-return path; assert correct `skip_reason` recorded
3. `test_recycle_executed_flag` — when a recycle commits, only that one bar has `recycle_executed=True`
4. `test_harvest_triggered_terminal` — on harvest, the harvest bar has `harvest_triggered=True` and is the last record
5. `test_no_records_after_harvest` — subsequent apply() calls after harvest do not append
6. `test_per_leg_block_widths` — 2-leg fixture → 16 leg columns; 3-leg fixture → 24 leg columns
7. `test_peak_equity_monotonic_nondecreasing` — `peak_equity_usd` never decreases across the ledger
8. `test_dd_from_peak_nonpositive` — `dd_from_peak_usd <= 0` always

### New integration tests (`tests/test_basket_telemetry_end_to_end.py`)

9. `test_parquet_written_at_basket_close` — after `write_per_window_report_artifacts`, `raw/results_basket_per_bar.parquet` exists
10. `test_schema_enforcement_blocks_malformed` — feeding a manually-corrupted per_bar_records list to the writer raises before write
11. `test_schema_version_bumped` — `run_metadata.json` reports `1.3.0-basket`
12. `test_mps_baskets_new_columns_populate` — running a basket end-to-end results in an MPS Baskets row with all 10 new columns populated (non-NaN)
13. `test_mps_backward_compat_legacy_rows_nan` — pre-existing rows from before the patch get NaN-filled on the new columns, append-only preserved
14. `test_legacy_basket_run_still_works` — running a basket with the OLD recycle_events.jsonl reconstruction path (i.e., legacy modules invoked) still produces correct results

### Test fixtures

- Synthetic 100-bar fixture for unit tests (already exists pattern in `tests/test_basket_runner_phase2.py`)
- B1 directive replay using the real (or NAS-recoverable) data for the integration test, or a slimmed sample if test runtime is a concern

### Pre-commit / CI

- `tools/lint_no_hardcoded_paths.py` — confirm patch contains no absolute user paths
- `tools/lint_encoding.py` — every new file open carries `encoding="utf-8"` where applicable (parquet writes don't need it; CSV reads in test code do)
- Existing test_engine_abi_v1_5_9 suite — must still pass (no engine change in this patch, so this is a regression check)

### Broader-pytest baseline impact

SYSTEM_STATE notes 3 known pre-existing test failures (Phase 5b.4 stale assertion, two path-authority tests). The patch must not introduce additional failures. After patch: re-run `python tools/check_broader_pytest_baseline.py` to confirm.

---

## 9. Sequencing (phase-by-phase)

| Phase | Deliverable | Estimated wall-clock | Gate to next |
|---|---|---|---|
| **0** | This plan doc → operator review | passive | Operator approval to begin coding |
| **1** | Implement Component A (h2_recycle.py + basket_pipeline.py) | ~2h coding + tests | Unit tests 1–8 pass |
| **2** | Implement Component B (basket_report.py parquet write + schema-version bump) | ~1h | Integration tests 9–11 pass |
| **3** | Implement Component C (basket_ledger_writer.py MPS row extension) | ~1h | Integration tests 12–13 pass |
| **4** | Run champion validation (Gates 1–5 across B1, AJ, B2) | ~30 min total pipeline + cross-check work | All gates pass → write `H2_TELEMETRY_EMITTER_VALIDATION.md` |
| **5** | Operator review of validation report → decision on backfill (deferred from audit) | passive | Operator GO/NO-GO |
| **6** (optional, post-decision) | Backfill remaining ~268 historical baskets via batch rerun | ~25 min pipeline | Validation complete |
| **7** (follow-up, separate session) | Refactor `h2_intrabar_floating_dd.py` from reload+replay to parquet read | ~2h | New module faster, parity proven, legacy module retained as fallback |

Phases 1–4 are atomic — they ship together in one commit (one logical change: telemetry emitter + champion proof). Phases 6–7 are independent follow-ups. `H2_ENGINE_PROMOTION_PLAN.md` LOCKED v11 → v12 update is **explicitly excluded** from this implementation chain per operator M2 and lives in a future session gated on validation pass + backfill decision.

---

## 10. Acceptance criteria

The patch is accepted when:

1. All unit tests (1–8) and integration tests (9–14) pass on a clean checkout
2. All five champion validation gates pass for B1, AJ, B2
3. `outputs/H2_TELEMETRY_EMITTER_VALIDATION.md` written, reviewed, recommends GO on backfill
4. Pre-commit lint (path + encoding) clean
5. Broader-pytest baseline unchanged (same 3 pre-existing failures, no new ones)
6. Engine manifest hash unchanged (this is a tools/ patch, no engine touch)
7. SYSTEM_STATE generated post-patch shows: pipeline queue empty, MPS Baskets sheet has new columns, working tree clean

---

## 11. Rollback plan

If validation fails or a downstream consumer breaks:

1. Revert the patch commit (single commit, atomic — easy revert)
2. Schema_version returns to `1.2.0-basket`; new artifacts don't appear; MPS Baskets sheet columns become orphan-but-empty (`pd.NA` everywhere because no row writes them)
3. The orphan columns can stay in the sheet or be manually dropped — they don't violate append-only since no row ever populated them
4. Legacy harvest_robustness modules (unchanged in this patch) continue working on all baskets — no consumer is broken

The patch is fully reversible. The only one-way artifact is the new parquet files, which are not consumed by anything else if the writer is removed; they sit harmless on disk until cleanup.

---

## 12. Resolutions

All six approval questions have been resolved by operator 2026-05-16. See §0.5 for the resolution table.

---

## 13. References

- [outputs/H2_TELEMETRY_AUDIT.md](H2_TELEMETRY_AUDIT.md) — schema authority (locked)
- [outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md](system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md) — basket architecture authority (LOCKED v11; **untouched by this patch** per operator M2; v12 ledger codification deferred to a separate post-validation session)
- `tools/recycle_rules/h2_recycle.py` — primary patch surface (per-bar accumulator)
- `tools/basket_pipeline.py` — `BasketRunResult` carrier
- `tools/basket_report.py` — parquet writer + schema_version bump
- `tools/portfolio/basket_ledger_writer.py` — MPS Baskets row appender
- `tools/harvest_robustness/modules/h2_intrabar_floating_dd.py` — legacy reconstruction (refactor follow-up, not in this patch)
- `governance/recycle_rules/registry.yaml` — rule registry (not touched; no rule version bump)

---

**End of plan. Awaiting operator approval to begin Phase 1 coding.**
