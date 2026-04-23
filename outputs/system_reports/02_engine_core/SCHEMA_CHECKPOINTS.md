# Engine Output Schema Checkpoints

Each entry marks a point at which the observable output schema of the engine
changed in a non-reversible way. Historical reproducibility is **conditional**
across these boundaries: a run re-executed under a later engine/emitter may
produce byte-different artifacts (new columns, new sheets) even with identical
input data + strategy.py. `artifact_hash` comparisons across a checkpoint will
diverge — this is expected, not corruption.

Use these entries when triaging:
- "why does this old run's hash not match a re-execution?"
- "which Stage-1 / Stage-2 artifacts gained / lost a column?"
- "what is the earliest engine that can read this CSV without missing fields?"

---

## 2026-04-23 — `exit_source` namespaced CSV column introduced

**Scope:** Stage-1 emitter, Stage-1 -> Stage-2 contract, Stage-2 report.

**Engine version:** v1.5.8 (no version bump — contract-additive only).

**Contract:** `Strategy.check_exit(ctx)` accepts `bool | str` (v1.3).
See `AGENT.md` "STRATEGY CONTRACT — `check_exit()` v1.3" for the namespace.

**New fields / sheets:**
- `results_tradelevel.csv` gains column `exit_source`
  (`ENGINE_*` | `STRATEGY_*` | `STRATEGY_UNSPECIFIED`).
- AK_Trade_Report `Performance Summary` gains row `Unspecified Exit %`.
- AK_Trade_Report gains sheet `Exit Source Breakdown`.

**Engine-internal vocabulary:** unchanged
(`STOP` / `TP` / `TIME_EXIT` / `SIGNAL_EXIT` / `DATA_END`).
Namespacing happens in the Stage-1 bridge (`tools/run_stage1.py`), not in the
engine. All existing tests and `verify_engine_integrity.py` continue to pass
against the unchanged engine-internal labels.

**Reproducibility implications:**
- Pre-checkpoint runs **remain valid** artifacts — their CSVs lack the column.
- Re-executing a pre-checkpoint run under this engine **will** add the column;
  `system_registry.py` `artifact_hash` will diverge from the original.
- Downstream CSV consumers (16 audited) tolerate the extra column
  (by-name access, no strict whitelist).

**Migration path for strategies:** return a `"STRATEGY_<REASON>"` string from
`check_exit()` instead of bare `True`. `tools/lint_check_exit_labels.py`
(pre-commit, warn-only) flags bare returns but never blocks. The canary
migration is `strategies/55_MR_XAUUSD_15M_ZREV_S01_V1_P00/strategy.py`.

**Precedence (enforced by engine execution order, not by post-hoc scan):**
`ENGINE_STOP` > `ENGINE_TP` > `ENGINE_TRAIL` > `ENGINE_SESSION_RESET` > `STRATEGY_*`.
SL/TP resolution runs before `check_exit()` — so when both would fire on the
same bar, `check_exit()` is never called and the exit is attributed to the
engine.

---
