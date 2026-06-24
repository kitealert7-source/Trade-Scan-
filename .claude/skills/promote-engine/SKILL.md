---
name: promote-engine
description: Make an ENGINE change (add telemetry, add a directive flag, freeze-amend, or promote a new canonical engine version) without rediscovering the surface maps + landmines each time. The engine analog of /promote (which is for STRATEGY→LIVE). Use for any edit under engine_dev/ + its dispatch/identity surfaces. NOT for strategy promotion, directive runs, or trade-logic research.
---

# /promote-engine — Engine-Change Playbook + Promotion Tool

**Why this exists:** the v1.5.11 Patch A session proved that a *simple* engine change (6 counters; a
flag; a byte-identical promotion) costs a **marathon** — not because the logic is hard, but because
of (1) rediscovering where everything lives, (2) hand-flipping the promotion's ~13 identity surfaces,
(3) threading output through a long pipeline, and (4) tripping latent landmines (CRLF/LF hashes, a
missed self-check literal, a dead resolver). This skill captures all of that so the next change is
smooth. **`tools/promote_engine.py` automates the mechanical promotion; the maps + gotchas below kill
the rediscovery.**

## When to use / when NOT

- **USE:** editing anything under `engine_dev/universal_research_engine/<vN>/`; adding run-level
  telemetry to a run; adding a directive `engine_features` flag; promoting a new canonical engine;
  re-stamping an engine after an edit; fixing an identity/dispatch surface.
- **NOT:** strategy → LIVE (use `/promote`); running a directive (`/execute-directives`); trade-logic
  *research* (`/hypothesis-testing`); the `CURRENT`/`LIVE_ABI` dispatch convergence (its own design
  doc — `ENGINE_DISPATCH_CONVERGENCE_DESIGN_2026-06-24.md`).

## The tool — `tools/promote_engine.py`

```bash
# You edited an engine source file -> make the manifest + vault consistent (LF hashes) + verify.
python tools/promote_engine.py --restamp <vN>

# Flip canonical from the current authority to <vNEW> across ALL identity surfaces,
# freeze + vault, rehash ABI, regen guards, run the convergence gate. ALWAYS --dry-run first.
python tools/promote_engine.py --promote <vNEW> --dry-run
python tools/promote_engine.py --promote <vNEW>      # then for real

# Just run the verification (integrity + convergence gate + abi_audit). No edits.
python tools/promote_engine.py --verify <vN>
```
The tool **never commits** — review the diff, then commit. The convergence gate is the independent
verifier (it caught a mid-edit partial flip during v1.5.11). **Byte-identical trades are YOUR job**
(run the parity harness before `--promote`; the tool flips identity, it does not prove compute).

## STANDING DECISION — after a `--promote`, evaluate the dispatch convergence

The `CURRENT`/`LIVE_ABI` dispatch convergence is **DESIGNED + DEFERRED PENDING EVIDENCE**
(`outputs/system_reports/01_system_architecture/ENGINE_DISPATCH_CONVERGENCE_DESIGN_2026-06-24.md`).
The open question is whether the v1.5.11 marathon was a *tooling* problem (this skill + tool fix it)
or an *architecture* problem (too many surfaces → convergence). **The next real `--promote` IS the
experiment.** When you finish it, record the verdict:
- **Stayed "review one diff → commit", no new hand-edits, no per-version tool patching, no new
  identity surface** → the tax was tooling-shaped → **close convergence as YAGNI.**
- **Any of: a surface the tool couldn't flip · the tool needed non-trivial per-version patching · a
  new identity surface appeared · promotions got frequent enough that even reviewing the diff is
  friction** → the surface-count itself is the problem → **reconsider convergence** (weighed against
  its proof-layer-rework risk). 2nd data point: Patch A.1's event-log build (tests output-threading /
  Tax B, which neither this tool nor convergence fixes). Full record: [[project_v1_5_11_patch_a_canonical]].

## Surface maps — "to change X, edit these" (stop rediscovering)

| Change shape | Where to edit (in order) |
|---|---|
| **Add a `run_metadata.json` field** | `run_stage1.py:_emit_enrich_metadata_files` — Phase E (`data[...]`) **and** Phase F (UI mirror `ui_data[...]`). Nothing goes in `results_tradelevel.csv`. |
| **Add a directive flag** (`engine_features.*`) | (1) resolver in `tools/engine_features.py`; (2) register the block in `tools/canonical_schema.py` (`CANONICAL_BLOCKS`+`OPTIONAL_BLOCKS`+`BLOCK_TYPES`+`ALLOWED_NESTED_KEYS`+key-order) or Stage -0.25 canonicalization rejects it; (3) validate at admission — new gate in `tools/orchestration/admission_controller.py`; (4) if it's behavior-affecting, add the dotted leaf to `directive_diff_classifier._BEHAVIORAL_EXECUTION_LEAVES` so a change forces a `signal_version` bump; (5) stamp it in `run_metadata` (map above). |
| **Add a run-level engine counter / telemetry** | Engine counts into an **opt-in dict** (default `None` → byte-identical); thread it `run_engine(df,strategy,health=None)` → `run_engine_logic` (**version-safe**: pass only if `inspect.signature` accepts it, so the bridge serves old + new engines) → `_stage1_run_engine_with_htf_patches` → `_stage1_emit_and_verify` → `emit_result` → `_emit_enrich_metadata_files`. |
| **Promote a new canonical engine** | `promote_engine.py --promote` does all of: `basket_runner.py` import **+ the `:70` self-check literal**, `config/engine_authority.py` ×2, `config/engine_registry.json` active_engine + `engines{}` map, `test_engine_identity_convergence.py` version literals + EXPECT, `ENGINE_STATUS`, manifest freeze + LF-hashes, vault, ABI rehash, guard regen. |
| **Fix an engine bug after freeze** | Edit the file → `promote_engine.py --restamp <vN>` (re-stamps LF-hashes + vault + verifies). Update the manifest `promotion_note` if scope changed. |

## Landmines (every one of these bit during v1.5.11 — the tool now guards them)

1. **LF-normalized hashes, NOT raw `read_bytes()`.** Windows checkout is CRLF; the integrity gate
   (`verify_engine_integrity.canonical_sha256`) hashes CRLF→LF-normalized. Raw hashes fail the gate.
   `--restamp` does this for you.
2. **The `basket_runner.py:70` load-time self-check** asserts `ENGINE_ABI == "engine_abi.<v>"` — a
   *fourth* basket surface beyond the import. Miss it and the module fails closed at load (good — but
   surprising). The tool flips it.
3. **Edit engine files BEFORE freezing.** If you must amend a fresh freeze (as H6 did), use
   `--restamp` — never hand-edit the manifest hash.
4. **Dead-resolver class.** A "validator" that silently returns `UNKNOWN`/`None` validates *nothing*
   (H6: `get_runtime_engine_version` read a manifest that never existed → permanently fail-open).
   When you add a resolver-backed check, add a test that it resolves to a **real** value.
5. **The convergence gate is the net — run it.** `test_engine_identity_convergence.py` proves every
   selection surface agrees; it catches partial flips. `--promote`/`--restamp`/`--verify` all run it.
6. **Byte-identical telemetry is opt-in-guarded.** Counter/event code must sit behind
   `if health is not None:` so the default path (the parity harness, the warm-up wrapper, old engines)
   is line-for-line unchanged.
7. **Guarded-tool edits drift the manifest, and it surfaces LATE.** Editing any guarded tool (the
   pipeline spine, basket spine, the integrity primitives -- the full set is the keys of
   `tools/tools_manifest.json`) without regenerating leaves the next pipeline run to hard-fail at
   startup ("Tool content hash mismatch ..."). This bit a real run 3x on 2026-06-24. The edit-time
   hook now warns the moment you touch a guarded file, but before any pipeline/CI run check the
   working tree yourself: **`python tools/check_guard_drift.py`** (exit 0 = clean, 1 = drift), then
   `python tools/generate_guard_manifest.py` + `git add tools/tools_manifest.json` to clear it.
   (`promote_engine.py` does the regen as part of `--promote`/`--restamp`.)

## Byte-identical discipline (the safety, keep it)

A structural/telemetry engine change must not move a trade. Prove it: run the same strategy through
`run_execution_loop(df, strategy)` (no telemetry args) on **both** the old and new engine and assert
the trade lists are `==`; and run the new engine with the telemetry dict supplied and assert the
trade list is **unchanged** vs without it. Pattern: `tests/test_engine_health_counters_v1_5_11.py`.

## Related skills

| Skill | Relationship |
|---|---|
| `/promote` | Sibling — STRATEGY→LIVE. This skill is the ENGINE analog. |
| `/update-vault` | The vault contract `--promote` mirrors for the engine snapshot. |
| `/rerun-backtest` | After an engine change, re-run a representative directive to confirm pipeline-grade behavior. |

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-06-24 | Created from the v1.5.11 marathon — surface maps + landmines + `promote_engine.py` capture the rediscovery + hand-flip cost. | Initial skill. |
