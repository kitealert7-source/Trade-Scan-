# Reproducibility Gap — Indicators Are Not Snapshotted With strategy.py + Directive

**Date:** 2026-06-29
**Severity:** HIGH for reproducibility / faithful re-run / Replay Admission.
**Status:** REPORT — fix tracked as a spawned chip task (Protected Infrastructure, Invariant #6).

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

## Where the save points are (implementation surface — Protected Infra)

- `tools/run_stage1.py` — `emit_result` / the run-folder snapshot writer (writes strategy.py +
  directive into `runs/<run_id>/`).
- `tools/strategy_provisioner.py` — writes `strategies/<id>/strategy.py`.
- the execution-capsule writer (`backtests/<dir>/` + `DIRECTIVE_SOURCE.txt`).
- `tools/backfill_run_directives.py` — extend to also backfill the indicator snapshot for existing runs.
- `engines/indicator_warmup_resolver.py` already has `extract_indicators_from_strategy(...)` — reuse it
  to enumerate exactly which indicator modules a strategy imports.

## Acceptance

- Every new backtest folder/run/strategy carries an `indicators_manifest.json` (+ source copies).
- Replay/contract verification fails loud on indicator hash drift.
- Backfill covers existing runs (best-effort: manifest from current modules, flagged as
  retro-captured).
- Reconcile the Replay Admission FROZEN design (§2/§3) to "verify indicators against snapshot," not
  "resolve against live."
