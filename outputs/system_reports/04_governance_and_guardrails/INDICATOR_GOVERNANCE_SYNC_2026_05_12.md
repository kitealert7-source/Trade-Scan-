# Indicator Governance Sync — 2026-05-12

**Status:** complete.
**Authority:** `indicators/INDICATOR_REGISTRY.yaml` is now the Stage-0.5 allowlist.
**Wiring:** `tools/semantic_validator.py` consults the registry on every
directive admission. An imported indicator module must (a) exist on disk
under `indicators/<category>/<name>.py` AND (b) have a `module_path`
entry in the registry. Either missing → admission fails with a clear
cause.

---

## Why this happened today

Yesterday's `outputs/REPORT_OWNERSHIP_AUDIT.md` flagged a path-ambiguity
in `tools/orchestration/stage_portfolio.py:173`. Investigating that
audit surfaced a structural mismatch: 30 days of multi-asset
`PORTFOLIO_<id>.md` reports had been silently dropped because the
function pointed at the wrong root. The fix landed in commit `4ac360f`.

Reviewing the broader pattern — *silent latent breakage that no
enforcement currently catches* — turned up the same shape in the
indicator surface:

- Stage-0.5 (`tools/semantic_validator.py`) accepted any import path
  beginning with `indicators.` as valid, without confirming the module
  actually existed on disk.
- `indicators/INDICATOR_REGISTRY.yaml` (45 entries, version 8) was
  documentation only — never read by enforcement code.
- 22 indicator modules existed on disk but had no registry entry.
- 14 strategy folders imported modules that don't exist on disk and
  weren't catching it at admission (the `ImportError` surfaces at run
  load instead).

This sync closes those gaps.

---

## What changed

### 1. Registry → allowlist authority

`tools/semantic_validator.py` now imports `yaml` and exposes:

- `INDICATOR_REGISTRY_PATH` (= `indicators/INDICATOR_REGISTRY.yaml`)
- `INDICATORS_ROOT` (= `indicators/`)
- `_load_registered_indicator_paths()` — returns the set of registered
  `module_path` strings; raises hard on missing/unparseable registry.
- `_enforce_indicator_allowlist(declared_modules)` — invoked at the end
  of the existing declared-vs-code set-equality test in
  `validate_semantic_signature()`. Raises with the specific cause:
  - **Not on disk** → "restore the missing module file(s) or remove the
    import + directive entry"
  - **On disk, not in registry** → "add an entry for each before this
    directive can be admitted"

### 2. Registry reconciliation

`indicators/INDICATOR_REGISTRY.yaml` bumped `registry_version: 8 → 9`.

22 new entries added as governance-sync stubs (minimum fields:
`module_path`, `category`, `registered_at`, `notes`). Rich metadata
(`function_name`, `input_requirements`, `output_columns`, etc.) is
deferred to a separate backfill pass — out of scope for today.

```
indicators.momentum.cmo
indicators.momentum.macd
indicators.momentum.macd_htf
indicators.momentum.rsi_extremes
indicators.price.consecutive_closes
indicators.price.consecutive_highs_lows
indicators.structure.avg_range
indicators.structure.choch_v2
indicators.structure.choch_v3
indicators.structure.dmi_wilder
indicators.structure.fair_value_gap
indicators.structure.prev_session_extremes
indicators.structure.session_clock
indicators.structure.session_clock_universal
indicators.structure.swing_pivots
indicators.trend.ema_cross
indicators.trend.gaussian_slope
indicators.volatility.atr_with_dollar_floor
indicators.volatility.atr_with_pip_floor
indicators.volatility.bar_range
indicators.volatility.bb_squeeze
indicators.volatility.bollinger_bands
```

Post-sync: **66 modules on disk ↔ 66 unique `module_path` entries in
the registry**. Bijection verified by
`tests/test_indicator_allowlist_enforcement.py::test_real_registry_resolves_every_entry_to_disk`.

Note: unused registry entries (modules registered but imported by no
strategy) were **not pruned**. Per the user's scope decision today:
*unused ≠ invalid; removal is governance policy, not enforcement.
Stabilize first, prune later.*

### 3. Tests pinned

`tests/test_indicator_allowlist_enforcement.py` — 8 tests covering:

| Case | Pin |
|---|---|
| Valid module: on disk ∧ in registry | passes silently |
| Empty input set | passes silently |
| Registered but missing on disk | raises with "do not exist on disk" |
| On disk but not registered | raises with "not registered" |
| Unknown to both | disk check fires first |
| Multiple failures in one set | all surfaced in one error |
| Disk check precedence | confirmed (simpler operator remediation) |
| Real registry ↔ disk bijection | enforced |

---

## Surfaced (not retired) — broken consumers

The audit identified **14 strategy folders that import indicator
modules which do not exist on disk**. Their structure passes the
existing import-set-equality check (the directive declares the same
non-existent module the strategy imports), but the modules fail at
runtime `ImportError` and would fail Stage-0.5 admission going forward.

**Missing indicator modules:**
- `indicators.macro.news_event_window`
- `indicators.structure.pre_event_range`

**Affected strategy folders:**

```
strategies/64_BRK_IDX_15M_NEWSBRK_S03_V1_P00
strategies/64_BRK_IDX_15M_NEWSBRK_S03_V1_P01
strategies/64_BRK_IDX_15M_NEWSBRK_S03_V1_P02
strategies/64_BRK_IDX_15M_NEWSBRK_S03_V1_P03
strategies/64_BRK_IDX_15M_NEWSBRK_S05_V1_P00
strategies/64_BRK_IDX_15M_NEWSBRK_S05_V1_P01
strategies/64_BRK_IDX_15M_NEWSBRK_S05_V1_P02
strategies/64_BRK_IDX_30M_NEWSBRK_S01_V1_P00
strategies/64_BRK_IDX_5M_NEWSBRK_S02_V1_P00
strategies/64_BRK_IDX_5M_NEWSBRK_S02_V1_P01
strategies/64_BRK_IDX_5M_NEWSBRK_S02_V1_P02
strategies/64_BRK_IDX_5M_NEWSBRK_S04_V1_P00
strategies/64_BRK_IDX_5M_NEWSBRK_S04_V1_P01
strategies/64_BRK_IDX_5M_NEWSBRK_S04_V1_P02
```

**Status:** these folders are not touched in this sync. Their
directives sit in `backtest_directives/completed/` as `*.txt.admitted`
markers — they admitted at some past date when the now-missing
indicators presumably existed. Retiring them is a governance-policy
decision, not enforcement.

**What happens going forward:** if any of these directives is
re-submitted (e.g. via the rerun-backtest workflow), Stage-0.5 admission
now fails fast with:

```
Indicator module(s) declared by directive and imported by strategy do
not exist on disk: ['indicators.macro.news_event_window',
'indicators.structure.pre_event_range']. Either restore the missing
module file(s) under indicators/ or remove the import + directive
entry.
```

That's the intended outcome — fail at the gate, not at runtime.

**Open question for a future session** (do not start now): are these
strategies wanted? Options:
- **(a)** Restore `news_event_window` + `pre_event_range` — implies
  there is an indicator design somewhere we want to formalize.
- **(b)** Retire the 14 folders + their `.admitted` directives.
- **(c)** Leave as-is (effectively `is_current=0` by virtue of being
  un-admittable).

This document captures the state so the question can be revisited with
full context whenever it's prioritized.

---

## Process — keeping the registry in sync going forward

Stage-0.5 catches drift at directive **admission**. The 2026-05-12
follow-up adds an earlier defence at **commit time** so drift never
lands in the first place.

### Author workflow

1. **Write the indicator module** at `indicators/<category>/<name>.py`.
2. **Generate the registry stub** in the same edit cycle:
   ```bash
   python tools/indicator_registry_sync.py --add-stub indicators.<category>.<name>
   # or, for several at once:
   python tools/indicator_registry_sync.py --add-stubs
   ```
   `--add-stub` refuses to register a `module_path` whose `.py` file
   does not exist — guards against typos and against re-creating the
   NEWSBRK-style phantom-registry-entry class of bug.
3. **Stage both files together**:
   ```bash
   git add indicators/<category>/<name>.py indicators/INDICATOR_REGISTRY.yaml
   ```
4. **Commit.** If steps 2–3 were skipped, the pre-commit hook blocks
   with a specific error message naming the file and the fix command.

### Enforcement layers (defence in depth)

| Layer | When | Tool | Failure mode |
|---|---|---|---|
| Commit | `git commit` | `tools/lint_indicator_registry_sync.py --staged` (wired into `tools/hooks/pre-commit`) | Hook returns 1; commit blocked with fix hint |
| Admission | Directive enters pipeline | `tools/semantic_validator.py::_enforce_indicator_allowlist` | `ValueError` raised at Stage-0.5; directive rejected |
| Ad-hoc audit | Anytime | `python tools/indicator_registry_sync.py --check` | Exit 1 with drift report |

### Operator commands

```bash
# Check current state — exits 1 if drift exists.
python tools/indicator_registry_sync.py --check

# List drift in human-readable form (always exits 0).
python tools/indicator_registry_sync.py --list

# Append stub entries for every disk module missing from the registry.
python tools/indicator_registry_sync.py --add-stubs

# Append one specific module by dotted path.
python tools/indicator_registry_sync.py --add-stub indicators.structure.new_breakout
```

### What is NOT enforced

- **Modifications** to existing indicator files — the registry entry
  already exists, no registry change needed.
- **Deletions** of indicator files — removing the module is a
  governance decision (does any strategy still depend on it?). The
  hook does not police deletions; Stage-0.5 will catch consumers that
  reference the deleted module at the next admission.
- **Rich metadata completeness** — stubs only require `module_path` +
  `category` + `registered_at` + `notes`. Rich fields
  (`function_name`, `input_requirements`, `output_columns`, etc.) are
  backfilled in a separate documentation pass.

### Tests pinning the process

`tests/test_indicator_registry_sync_hook.py`:

- Hook passes when indicator + registry are staged together
- Hook blocks when indicator added without registry update
- Hook ignores modifications to registered modules
- Hook ignores `__init__.py` additions
- Hook ignores files outside `indicators/`
- Hook reads the **staged** registry blob, not the working tree
  (catches the "edited registry but forgot `git add`" case)
- Helper `--check` passes against the real repo
- Helper `--add-stub` is idempotent
- Helper `--add-stub` refuses phantom paths (no disk file)

## References

- `tools/semantic_validator.py` — Stage-0.5 admission enforcement
- `tools/lint_indicator_registry_sync.py` — pre-commit hook step
- `tools/indicator_registry_sync.py` — operator helper
- `tools/hooks/pre-commit` — hook wiring (canonical source)
- `indicators/INDICATOR_REGISTRY.yaml` — allowlist authority (version 9)
- `tests/test_indicator_allowlist_enforcement.py` — Stage-0.5 regression
- `tests/test_indicator_registry_sync_hook.py` — hook regression
- `outputs/REPORT_OWNERSHIP_AUDIT.md` — yesterday's audit that surfaced
  the parallel path-fix pattern
- Invariant 9 (Indicator Separation) in `CLAUDE.md`
