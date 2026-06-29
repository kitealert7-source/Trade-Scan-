# Reproducibility Gap — Indicators Are Not Snapshotted With strategy.py + Directive

**Date:** 2026-06-29
**Severity:** HIGH for reproducibility / faithful re-run / Replay Admission.
**Status:** RESOLVED (forward-path) 2026-06-29 — every new run/strategy/capsule now emits an
`indicators_manifest.json` + `indicators_snapshot/` source copies, and `verify_indicator_snapshot`
fails loud on drift. Backfill of pre-existing runs was **descoped** (forward-path only, operator
decision) to keep the change small. Protected-Infra change made under an approved plan (Invariant #6).

**Implementation:**
- Enumerate (transitive AST scan, works on archived/non-importable files + basket recycle rules):
  `tools/indicator_imports.py::extract_imported_indicator_modules`
- Snapshot + fail-loud verify: `tools/run_indicator_snapshot.py`
  (`snapshot_indicators` / `require_indicator_snapshot` / `verify_indicator_snapshot`; `verify` CLI)
- Wired at: `tools/run_stage1.py` (→ `runs/<run_id>/`, fail-fast), `tools/strategy_provisioner.py`
  (→ `strategies/<id>/`, refresh-on-reprovision), `tools/basket_report.py` (→ the `backtests/<dir>/`
  capsule, best-effort post-result)
- Tests: `tests/test_run_indicator_snapshot.py`
- Replay contract reconciled: `outputs/system_reports/01_system_architecture/REPLAY_ADMISSION_DESIGN_2026-06-29.md` §2/§3/§6/§8

> **Enumeration note:** the original report suggested reusing
> `engines/indicator_warmup_resolver.py::extract_indicators_from_strategy(...)`. That helper reads a
> *loaded* `Strategy`'s `STRATEGY_SIGNATURE` (registry *names*, plus synthesized engine-owned filter
> indicators) — it can't see basket recycle rules, needs an importable strategy, and misses transitive
> indicator→indicator deps. The implementation instead uses a transitive **AST import scan** of the
> executed `.py` (the faithful "modules actually imported"), which also covers baskets and archived
> snapshots. Decision recorded with the operator 2026-06-29.

---

## The gap

For faithful re-run, the pipeline snapshots two of the three things that determine a backtest's
behavior:

| Determinant | Snapshotted today? | Where |
|---|---|---|
| `strategy.py` (logic + params) | ✅ | `runs/<run_id>/strategy.py`, `strategies/<id>/strategy.py`, capsule |
| directive (run config) | ✅ | `runs/<run_id>/directive.txt`, `backtests/<dir>/DIRECTIVE_SOURCE.txt` |
| **indicators** (`indicators/*` modules the strategy imports) | ❌ **NOT snapshotted** | resolved against the **live** `indicators/` registry at run time |

A strategy.py imports e.g. `indicators.volatility.atr`, `indicators.volatility.volatility_regime`,
`indicators.structure.highest_high`. Those modules carry their own logic + default parameters. If any
are **changed later** (a default window, a calc tweak, a bug fix), then re-running the *byte-identical*
strategy.py + directive **silently produces different results** — the experiment is no longer
reproducible, and nothing detects the drift.

This is the third leg of the stool. Saving strategy.py + directive but not indicators makes "faithful
re-run" an illusion the moment any indicator evolves.

## Why it matters now

- **Replay Admission (FROZEN design)** assumed *"indicators resolve against the live registry"* — this
  report **supersedes that line**: replay must verify indicators against a **snapshot**, not live, or it
  is not faithful. The Experiment Bundle must carry indicator provenance.
- **Legacy re-validation arc** — we just replayed legacy strategy.py files against *today's* indicators.
  If any of those indicators changed since the original run, our charged verdicts are subtly off. (Worth
  a spot-check of the indicators F6/F5 import vs their original versions.)
- **Engine-upgrade regression / audit / reproducibility** — all depend on the full input being captured.

## What to capture (everywhere strategy.py + directive are saved)

The strategy's imported indicator modules, captured at backtest time into the same locations
(`runs/<run_id>/`, `strategies/<id>/`, the `backtests/<dir>/` capsule, and the Replay Experiment Bundle):

- **Minimum (drift detection):** an `indicators_manifest.json` — for each imported `indicators.*`
  module: module id + **content hash** (+ registry version). At replay, the contract recomputes live
  hashes and **fails loud on any mismatch** (don't silently run a drifted indicator).
- **Full (reproduction):** also copy the indicator **source files** into the snapshot, so a drifted
  experiment can be reproduced bit-exactly even after the live module changes.

Recommendation: do **both** — manifest for cheap drift detection on every run + source copies for
guaranteed reproduction. (Mirrors how strategy.py is both hashed and copied.)

## Where the save points are (implementation surface — Protected Infra) — DONE

- ✅ `tools/run_stage1.py` — in `_stage1_load_market_data_and_snapshot`, after the strategy.py +
  directive snapshot, `require_indicator_snapshot(...)` → `runs/<run_id>/` (fail-fast: a snapshot
  failure marks the run FAILED).
- ✅ `tools/strategy_provisioner.py` — `_colocate_indicators_with_strategy(...)` after the directive
  co-location, both provision branches → `strategies/<id>/` (refresh-on-reprovision, `write_once=False`).
- ✅ `tools/basket_report.py` — the execution-capsule writer (beside `DIRECTIVE_SOURCE.txt` /
  `RECYCLE_RULE_SOURCE.py`) → `backtests/<dir>/` capsule (enumerated from the recycle rule; best-effort
  since card generation runs post-result).
- ⛔ `tools/backfill_run_directives.py` — **descoped** (forward-path only, operator decision 2026-06-29).
- Enumeration: a transitive **AST import scan** (`tools/indicator_imports.py`) of the executed `.py`,
  **not** `extract_indicators_from_strategy(...)` — see the Status note above for why.

## Snapshot homes (per architecture — intentional asymmetry)

The manifest + source copies land in each run's **authoritative reproduction home**, which differs by
architecture — this is deliberate, not an oversight:

| Architecture | Authoritative home (carries the manifest) | Why |
|---|---|---|
| **Single-asset** | `runs/<run_id>/` (+ `strategies/<id>/`) | single-asset runs have no `DIRECTIVE_SOURCE.txt` capsule — `runs/<run_id>/` is where the strategy.py + directive snapshots live and where reproduction sources from |
| **Basket** | the `backtests/<dir>/` **capsule** | per the Execution Capsule Contract the capsule is the *"authoritative byte-level home… reproduction starts from the capsule"*; rerun/`resolve_baseline`/Replay all source from it |

**Basket `runs/<run_id>/` folders intentionally do NOT carry the manifest.** A basket reproduces from
its capsule, never from the run folder, so a manifest there would be redundant (the run folder's
`directive.txt` + `basket_code/` are already convenience copies of what the capsule holds
authoritatively). See `governance/SOP/EXECUTION_CAPSULE_CONTRACT.md` → "What a capsule contains".

## Acceptance

- ✅ Every new backtest run/strategy/capsule carries an `indicators_manifest.json` (+ source copies).
- ✅ Replay/contract verification fails loud on indicator hash drift (`verify_indicator_snapshot`).
- ⛔ Backfill of existing runs — **descoped** by operator decision (forward-path only).
- ✅ Reconcile the Replay Admission FROZEN design (§2/§3, also §6/§8) to "verify indicators against
  snapshot," not "resolve against live."
