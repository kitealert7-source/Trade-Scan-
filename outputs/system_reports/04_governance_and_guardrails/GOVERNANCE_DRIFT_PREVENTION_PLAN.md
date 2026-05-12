# Governance Drift Prevention Plan (2026-05-12)

Planning document only. No code is touched here. The goal is to lock down
indicator-registry drift end-to-end (Part A) and inventory every other
declarative file in the repo that could rot the same silent way (Part B).

Today's principle stands: **stabilize first, prune later.** None of the
patches below propose retiring strategies, deleting modules, or pruning
unused registry entries.

---

## Section 1 — Indicator registry hardening plan

### 1.1 Current state (3 layers landed today)

The 2026-05-12 governance sync wired `indicators/INDICATOR_REGISTRY.yaml`
in as authoritative allowlist and added two enforcement layers around it.

| Layer | Trigger | Authority | File | Lines |
|---|---|---|---|---|
| Operator helper | manual / ad-hoc | drift check + stub append | `tools/indicator_registry_sync.py` | 1-233 |
| Pre-commit hook | `git commit` (ADDED indicators) | block commit on missing registry entry | `tools/lint_indicator_registry_sync.py` (called from `tools/hooks/pre-commit:49-63`) | 1-197 |
| Admission gate | directive enters pipeline | reject directive whose imports miss disk or registry | `tools/semantic_validator.py::_enforce_indicator_allowlist` | 86-131, invoked at 325 |

Tests covering layers 1+2: `tests/test_indicator_registry_sync_hook.py`
(7 cases, includes phantom-path refusal and staged-blob vs working-tree
authority — both relevant to the gap below).

Tests covering layer 3: `tests/test_indicator_allowlist_enforcement.py`
(separate file, exists today).

### 1.2 Gap: session-close, CI, push-time, bypassable hook

The hook chain has four real-world holes:

| # | Hole | Why it leaks drift | Caught today by |
|---|---|---|---|
| H1 | `git commit --no-verify` | Author can skip the pre-commit hook entirely. Stage-0.5 still catches it eventually, but only if a directive runs against the affected indicator. Registry can sit drifted for weeks. | nothing |
| H2 | Manual YAML edit (no `.py` change) | The pre-commit hook only inspects `--diff-filter=A` for `*.py` under `indicators/`. A registry entry pointing at a non-existent module is invisible to the hook. (This is exactly the NEWSBRK precedent — 14 strategies referenced two indicator modules that don't exist.) | manual audit only |
| H3 | Indicator deletion (`git rm indicators/X/Y.py`) | The pre-commit hook scope is ADDED, not DELETED. Removing a `.py` file without removing the registry entry leaves a phantom registry entry. Stage-0.5 surfaces this on next admission for an affected directive, but if no directive uses it, drift sits silently. | nothing |
| H4 | Session-close / CI / push-time | None of the entrypoints used during session-close (`audit_intent_index.py --all`, `system_introspection.py`) or pre-push (none — `tools/hooks/` has no `pre-push`) verify registry sync. The `verify_engine_integrity.py` tool hashes engine + tool files but does NOT check the indicator registry. | nothing |

Hole H2 is the one that produced today's drift. The 14 NEWSBRK directives
imported `indicators.macro.news_event_window` + `indicators.structure.pre_event_range`,
which exist neither on disk nor in the registry — the audit caught them
manually; nothing automatic did.

### 1.3 Proposed insertion points

`python tools/indicator_registry_sync.py --check` is the right callable
in all five spots. It already exits 1 on any drift (disk-not-in-registry
OR registry-not-on-disk), which covers H1, H2, and H3. The insertions
below close H4.

| # | Insertion | File | Line | Wrapper needed | Failure mode |
|---|---|---|---|---|---|
| I1 | Session-close gate | `.claude/skills/session-close/SKILL.md` (Step 6 — "Enforcement system health") | between current Step 6 (`audit_intent_index.py --all`) and Step 7 (Pre-Push Gate). New sub-step "6b. Registry drift check". | None — direct `python tools/indicator_registry_sync.py --check`. Block session-close on non-zero exit. | Exit 1 → STOP session-close. Author must `--add-stubs`, commit, retry. |
| I2 | Pre-push hook | `.git/hooks/pre-push` (new file, installed via `tools/hooks/install.sh`) — also commit `tools/hooks/pre-push` as the tracked source like the existing `pre-commit` pattern. | new file in `tools/hooks/pre-push`, written to mirror `tools/hooks/pre-commit` shape. | Tracked source `tools/hooks/pre-push` → `install.sh` copies to `.git/hooks/pre-push`. | Exit 1 → push blocked. |
| I3 | Pipeline preflight | `tools/run_pipeline.py` adjacent to `verify_manifest_integrity` at line 341. New step `verify_indicator_registry_sync(project_root)`. | Thin wrapper around the same drift check — re-implementing avoids a subprocess call but `subprocess.run([sys.executable, 'tools/indicator_registry_sync.py', '--check'])` is fine and keeps a single source of truth. | Raise `PipelineAdmissionPause("Indicator registry drift detected")` on non-zero exit. |
| I4 | `verify_engine_integrity.py` self-test | `tools/verify_engine_integrity.py:run_check()` after the existing `verify_tools_integrity()` call at line 429. | Direct call. | `sys.exit(1)` on non-zero exit. |
| I5 | `audit_intent_index.py --all` mode (defensive backup) | `tools/audit_intent_index.py` — add a new `--registry-drift` mode and include it in `--all`. | Wraps `subprocess.run` of the sync check. | Add the warning/error to the audit's exit code (warn → 1, hard error → 2). The session-close skill already escalates exit 2 to block. |

**Why five and not just one** — defence in depth. I1 is the most likely
trigger; I2 catches `--no-verify` bypasses before they leave the local
clone; I3 catches them at pipeline-run time even if I1 and I2 were
skipped; I4 plugs the check into the engine integrity tool that other
operators reach for; I5 plugs it into the audit entrypoint
operators run during health checks. Cost: five lines per insertion. The
helper already exists; no new code is needed beyond the wrappers.

**Note on H3 (deletion-without-registry-cleanup)**: a `.py` removal that
doesn't update the registry produces a phantom registry entry. The sync
helper already detects this (`registered - on_disk`), so I1–I5 catch it.
The pre-commit hook does NOT need to be extended to `--diff-filter=D`;
the drift check at I1/I2/I3/I4/I5 covers it.

**Worktree note**: I1 (session-close) is reasonable to invoke from any
worktree; the helper resolves `PROJECT_ROOT = Path(__file__).resolve().parent.parent`,
which is the worktree's `tools/indicator_registry_sync.py` parent — that's
the worktree's repo root. The registry file is tracked, so the worktree
has its own copy. This is fine — drift between worktrees and main is
caught by git on next push or merge. Don't try to read across worktrees.

### 1.4 Schema validation rules

The registry has two shapes today (post-2026-05-12 sync). A minimal
schema must accommodate both without bloating.

**Sample of full entry** (lines 66-105, `candle_state`):

```
candle_state:
  module_path: indicators.price.candle_state          # REQUIRED, dotted-path
  category: price                                     # REQUIRED, str
  function_name: apply                                # optional
  classification: Momentum                            # optional
  input_requirements: [...]                           # optional
  parameters: {...}                                   # optional
  default_parameters: {...}                           # optional
  output_type: DataFrame                              # optional
  output_columns: [...]                               # optional
  lookahead_safe: true                                # optional
  rolling_window_used: false                          # optional
  vectorized: false                                   # optional
  htf_compatible: true                                # optional
  dependency_indicators: []                           # optional
  compatibility: {...}                                # optional
  lookback: 1                                         # optional
  warmup: 1                                           # optional
  input_columns: [open, high, low, close]             # optional
```

**Sample of stub entry** (added by `--add-stubs` today, lines 96-105 of
`tools/indicator_registry_sync.py`):

```
<name>:
  module_path: indicators.<cat>.<name>                # REQUIRED, dotted-path
  category: <cat>                                     # REQUIRED, str
  registered_at: <YYYY-MM-DD>                         # REQUIRED for stubs
  notes: "Stub entry added via indicator_registry_sync ..."  # REQUIRED for stubs
```

**Proposed minimum schema** (lifted to 4 universal requirements, no more):

| Field | Required | Rule | Failure code |
|---|---|---|---|
| `module_path` | yes | must be `str`, must start with `indicators.`, must resolve to an existing file `<PROJECT_ROOT>/<dotted>.py` | `SCHEMA_MODULE_PATH_INVALID` |
| `category` | yes | must be `str`, must equal `module_path.split('.')[1]` (catches `indicators.price.foo` declaring `category: structure`) | `SCHEMA_CATEGORY_MISMATCH` |
| top-level key | yes | dictionary key under `indicators:` must be a `str`; entry value must be a `dict` | `SCHEMA_ENTRY_SHAPE` |
| `registry_version` | yes (top-level) | int, monotonically increasing across commits (`new >= old`) | `SCHEMA_VERSION_REGRESSION` |

Anything else (function_name, classification, lookback, warmup,
output_columns, etc.) stays advisory — the registry already varies in
how much metadata is present, and Stage-0.5 doesn't read those fields.
Three required entry fields is enough to make malformed entries
impossible without enlarging the surface gratuitously.

**Where the schema check belongs**: folded into
`tools/indicator_registry_sync.py::_drift_report` as a separate pass
that runs before the disk-vs-registry diff. Schema violations should
fail with their own codes (above) so the error pinpoints what's wrong.
A new `--validate-schema` subcommand isn't necessary — schema validation
should be part of every `--check` and `--list` invocation. The drift
check is meaningless if half the entries are malformed.

The `registry_version` monotonic-increase check requires reading the
prior version. Two cheap implementations: (a) call out to
`git show HEAD:indicators/INDICATOR_REGISTRY.yaml` and parse, or
(b) skip the version-regression check when running outside git context
(e.g., tests). (a) is the right primary path; the hook is allowed to
shell out to git already.

### 1.5 Required regression tests (A/B/C/D)

Extend `tests/test_indicator_registry_sync_hook.py`. The fake_repo
fixture is already there and is the right scaffold for cases A–D.

| Test | Scenario | Fixture | Assertion |
|---|---|---|---|
| **A** — `test_check_blocks_when_module_on_disk_missing_from_registry` | Stage a `.py` under `indicators/` but commit BOTH the registry and the file (registry still doesn't list it). Run `--check`. | Build `fake_repo` with one indicator on disk + an empty registry. `git add -A; git commit`. Then `python tools/indicator_registry_sync.py --check`. | `returncode == 1`; stdout contains the dotted path under "On disk, NOT in registry". |
| **B** — `test_check_blocks_when_registry_entry_has_no_file` | Build a registry with one entry pointing at `indicators.fakecat.phantom`, no file present. Run `--check`. | `_make_registry(['indicators.fakecat.phantom'])` written without creating the `.py`. | `returncode == 1`; stdout contains the dotted path under "In registry, NOT on disk". Catches NEWSBRK-class drift. |
| **C** — `test_check_blocks_when_registry_entry_malformed` | Build a registry where one entry is missing `module_path` OR has `category` mismatching its dotted path. Run `--check`. | `entries['bad'] = {'category': 'price'}` (no module_path) OR `entries['bad'] = {'module_path': 'indicators.price.bad', 'category': 'structure'}` (mismatch). | `returncode == 1`; stdout contains the failure code (`SCHEMA_MODULE_PATH_INVALID` or `SCHEMA_CATEGORY_MISMATCH`). |
| **D** — `test_session_close_drift_check_fails_closed` | Simulate hook bypass: commit a `.py` without registry entry using `--no-verify` (or just don't install the hook), then run the session-close check. | Same fake_repo, `git commit --no-verify`, then run the session-close drift step (or directly `--check`). | `returncode == 1`. Document: this is the bypass-defence path. |

Each test extends the existing pytest collection — no new test file
needed. Cases A and B are already implicit in the existing helper-level
test `test_sync_helper_check_passes_on_real_registry` (which only
asserts the *positive*); A and B add the negative paths. C is a new
behavior (schema validation). D is a regression for the bypass scenario.

---

## Section 2 — Other governance surfaces audited

Each surface answers four questions: **owner**, **consumer**,
**current enforcement**, **risk classification** (SAFE / RISK / BUG).

### 2.1 `indicators/INDICATOR_REGISTRY.yaml`

- **Owner**: mixed — `tools/indicator_registry_sync.py --add-stubs` for governance fixups; humans for rich metadata.
- **Consumer**:
  - `tools/semantic_validator.py::_enforce_indicator_allowlist` (admission gate, lines 86-131).
  - `tools/indicator_registry_sync.py` (operator helper).
  - `tools/lint_indicator_registry_sync.py` (pre-commit hook).
  - Indirect: Stage-0.5 rejects any directive importing a module not in the registry. Affected directives FailFast at admission.
- **Current enforcement** (after 2026-05-12 + this plan's I1–I5):
  - Pre-commit hook (added today): catches ADDED `.py` without registry entry.
  - Admission gate (added today): catches drift at directive-entry.
  - Operator helper (added today): runnable on demand.
  - **Gaps before I1–I5**: H1 (`--no-verify`), H2 (manual YAML edit, phantom registry entry — NEWSBRK), H3 (deletion-without-registry-cleanup), H4 (no session-close / CI / push-time check).
- **Risk**: **RISK** (drift would re-introduce silent Stage-0.5 ImportError-class bugs and admission would not flag them until a specific directive's run; surfaces eventually but slowly — exactly today's NEWSBRK precedent). Becomes **SAFE** once I1–I5 land.

### 2.2 `governance/namespace/sweep_registry.yaml`

- **Owner**: auto-generated by `tools/sweep_registry_gate.py::reserve_or_idempotent_match()`. Per `CLAUDE.md` and `MEMORY.md`, never hand-edited (use `tools/new_pass.py --rehash` to update signature hash).
- **Consumer**:
  - `tools/sweep_registry_gate.py` — admission check at directive entry. New directive must match existing sweep slot's `signature_hash` (idempotent) or claim a new slot.
  - `tools/system_introspection.py` (lines 591-613) — flags `signature_hash` / `signature_hash_full` mismatches under Known Issues during session-close.
  - `tests/test_sweep_registry_gate_regex.py` — pre-commit gate test.
  - `tests/test_sweep_registry_td004_regression.py` — pre-commit gate test for the registry auto-heal corruption guard.
- **Current enforcement**: admission-time (sweep_registry_gate rejects mismatched signature_hash); pre-commit (gate-suite pytest); session-close (introspection flags short/full hash mismatch under Known Issues).
- **Risk**: **SAFE** — short/full mismatch surfaces at session-close, signature drift produces SweepRegistryError at admission, full file is hash-keyed so corruption is loud.

### 2.3 `governance/namespace/token_dictionary.yaml`

- **Owner**: manual (humans add new MODEL/FAMILY/FILTER tokens). MEMORY.md flags this as a frequent guesswork hazard (PSBRK validity check is mandatory before creating any new directive/strategy).
- **Consumer**:
  - `tools/namespace_gate.py` (lines 147-178) — directive admission. Token not in allowed set OR alias not normalized → `NamespaceValidationError("NAMESPACE_TOKEN_INVALID" / "NAMESPACE_ALIAS_FORBIDDEN")`.
  - `tests/test_namespace_gate_regex.py` — pre-commit gate test.
- **Current enforcement**: admission-time only.
- **Risk**: **SAFE** — admission gate is fail-closed. A token mistakenly added to the dictionary is benign until used; a missing token blocks the offending directive immediately. The risk asymmetry is good.

### 2.4 `governance/namespace/idea_registry.yaml`

- **Owner**: manual (idea_id allocation when a new research track is opened).
- **Consumer**:
  - `tools/namespace_gate.py` (line 147 — `_load_yaml(IDEA_REGISTRY_PATH)`) — directive admission. Idea_id parsed from filename must be a registered family.
  - `tools/convert_promoted_directives.py` — reads to validate promoted directive's family vs the registry.
- **Current enforcement**: admission-time (namespace_gate raises on missing or mismatched idea_id).
- **Risk**: **SAFE** — same fail-closed pattern as token_dictionary.

### 2.5 `governance/capability_catalog.yaml`

- **Owner**: manual.
- **Consumer**:
  - `tools/capability_inference.py` — AST-based inference of strategy capabilities at preflight.
  - `tools/engine_resolver.py:60` — drives `compatible_with` mapping for engine selection.
- **Current enforcement**: admission-time at preflight CHECK 6.8 (capability-resolution). MEMORY.md flags: "provisioner NOT yet wired" — a known gap, but the gate is in place at the preflight side.
- **Risk**: **SAFE** — engine resolution fails closed on capability mismatch (`EngineResolverError`). A token added to the catalog but never claimed is benign.

### 2.6 `governance/supersession_map.yaml`

- **Owner**: manual + append-only (per the file's docstring header lines 1-20).
- **Consumer**:
  - `tools/report/family_renderer.py` — cross-time report resolution.
  - `tools/family_report.py` — same.
  - `tools/ledger_db.py` — appears to read the map for cross-time consolidation.
- **Current enforcement**: NONE at admission. The invariant ("append-only, never remove a mapping") is documented in the file header but not gated.
- **Risk**: **RISK** — silent edit/deletion of a mapping causes wrong cross-time references in reports. Reports don't fail; they just resolve old IDs to themselves instead of canonical successors. Surfaces as a wrong number in a report that no automated check would flag. Detection lag could be weeks.

### 2.7 `tools/tools_manifest.json` (guard manifest)

- **Owner**: auto-generated via `tools/generate_guard_manifest.py`. SKILL.md (session-close Step 2) prescribes regeneration when any `tools/*.py` changed.
- **Consumer**:
  - `tools/run_pipeline.py:404` — `verify_tools_timestamp_guard(project_root)` runs at pipeline-start. Hash mismatch raises `PipelineExecutionError`.
  - `tools/verify_engine_integrity.py:101` — `verify_tools_integrity()` runs at engine self-test.
- **Current enforcement**:
  - Pipeline-start: hash-mismatch raises (BLOCKED).
  - `verify_engine_integrity.py` line 122-124: WARN-only when file modified after manifest timestamp.
- **Risk**: **SAFE** — fail-closed at pipeline start. Manifest can be stale, but the staleness is loud (hash mismatch → admission halt). Hole: a tool that gets a new `tools/*.py` but is NOT in `GUARD_FILES` (lines 36-53 of `generate_guard_manifest.py`) is not protected — but `GUARD_FILES` is the explicit allowlist, and the policy is "tools outside this list don't get manifest coverage" by design.

### 2.8 `config/engine_registry.json`

- **Owner**: manual (operator edits when promoting a new engine; the `active_engine` and per-engine `status: FROZEN | EXPERIMENTAL` are set by hand).
- **Consumer**:
  - `tools/pipeline_utils.py::get_engine_version` — pipeline reads `active_engine`.
  - `tools/verify_engine_integrity.py:38` — same.
  - `tools/system_introspection.py:139` — read for SYSTEM_STATE snapshot's `Engine version`.
  - `tools/engine_resolver.py` — reads the per-engine `status` for selection.
- **Current enforcement**: NONE at admission for the registry file itself; downstream uses fail-closed if the active_engine path doesn't exist on disk (`engine_dev/<version>/` missing).
- **Risk**: **SAFE** — the file's surface is tiny (`active_engine` + per-engine statuses). Wrong `active_engine` produces an immediate `FileNotFoundError` at pipeline-load. The `status: FROZEN` field is consumed by the resolver which already filters non-FROZEN engines. Manual edits are the documented governance path.

### 2.9 `TradeScan_State/registry/run_registry.json` (run lineage)

- **Owner**: auto-generated (each pipeline run appends; never hand-edited per AGENT.md invariant).
- **Consumer**:
  - `tools/system_registry.py::_load_registry` (line 29) — fail-hard semantics on corruption (raises if JSON is invalid).
  - `tools/system_preflight.py::_check_registry` (lines 183-235) — disk-vs-registry parity check + tier resolution.
  - `tools/sweep_registry_gate.py::_can_reclaim_sweep` — consults to decide if a sweep slot can be reclaimed.
- **Current enforcement**: preflight tier-aware parity check raises RED on orphans or missing entries; corrupt-JSON raises hard.
- **Risk**: **SAFE** — read-time fail-closed. Disk/registry parity is checked by `system_preflight.py` and reported by `system_introspection.py`.

### 2.10 `outputs/system_reports/INTENT_INDEX.yaml`

- **Owner**: manual (intents are hand-authored).
- **Consumer**:
  - `.claude/hooks/intent_injector.py` (loaded at every UserPromptSubmit).
  - `.claude/hooks/post_write_reminder.py`.
  - `tools/audit_intent_index.py` — exit 2 on hard errors at session-close Step 6.
- **Current enforcement**:
  - Session-close: `audit_intent_index.py --all` (exit 2 blocks close).
  - CI test: `tests/test_intent_injector_promote_subject.py::TestNakedFuzzyForbidden` enforces "no naked fuzzy intent" schema requirement.
  - Hook self-compile check via `py_compile.compile` in `audit_intent_index.py:193`.
- **Risk**: **SAFE** — session-close gate is the authoritative defense.

### 2.11 `governance/schemas/VALIDATED_ENGINE.manifest.schema.json`

- **Owner**: manual (schema document).
- **Consumer**: governance preflight (referenced via `governance/preflight.py` per the CLAUDE.md `engine_dev/` change protocols).
- **Current enforcement**: schema validation at engine promotion.
- **Risk**: **SAFE** — single-purpose schema, consumed at a single gate.

### 2.12 `engine_dev/universal_research_engine/<version>/engine_manifest.json`

- **Owner**: auto-generated (`tools/generate_engine_manifest.py`).
- **Consumer**:
  - `tools/verify_engine_integrity.py:46` (`MANIFEST_PATH`) — hash check.
  - `tools/engine_resolver.py` — manifest.contract_id integrity.
  - `tools/system_introspection.py` — engine status reporting.
- **Current enforcement**: hash-checked at startup via `verify_engine_integrity.verify_hashes()`. Mismatch aborts engine self-test.
- **Risk**: **SAFE** — manifest hashes are verified, the file is frozen per engine version.

### 2.13 `outputs/system_reports/INTENT_INDEX.yaml` and `.claude/skills/<skill>/SKILL.md` registration

- Already covered under 2.10. Skill-file additions/renames don't have a registry per se (the system-reminder lists skills by filesystem scan), so there's no drift surface.

### 2.14 `.claude/logs/intent_matches.jsonl`, `.claude/logs/violations.jsonl`, `.claude/logs/post_write.jsonl`

- These are append-only logs, consumed by `tools/audit_intent_index.py`. Drift = no entries (log not being written), caught by dead-intent detection at session-close. **SAFE**.

### 2.15 Other manifests / registries scanned (no drift surface)

- `governance/schemas/` — single schema file, used at one gate. **SAFE**.
- `tools/TOOLS_INDEX.md`, `tools/TOOLS_AUDIT_REPORT.md` — documentation files, not consumed by any tool. Drift = stale docs, but no functional impact. **RISK** at the documentation level only — not in scope for this plan.

---

## Section 3 — Risk classification table

| Surface | Owner | Consumer | Current enforcement | Risk |
|---|---|---|---|---|
| `indicators/INDICATOR_REGISTRY.yaml` | mixed (auto-stub + manual rich) | semantic_validator (admission) + lint + helper | pre-commit + admission + helper — **no session-close, no CI, no pre-push, hook bypassable, deletion not caught, manual YAML edit not caught** | **RISK** |
| `governance/namespace/sweep_registry.yaml` | auto (sweep_registry_gate.reserve_or_idempotent_match) | sweep_registry_gate at admission + introspection at session-close | admission + session-close + pre-commit gate tests | **SAFE** |
| `governance/namespace/token_dictionary.yaml` | manual | namespace_gate at admission | admission only | **SAFE** |
| `governance/namespace/idea_registry.yaml` | manual | namespace_gate at admission | admission only | **SAFE** |
| `governance/capability_catalog.yaml` | manual | capability_inference + engine_resolver at preflight | preflight admission | **SAFE** |
| `governance/supersession_map.yaml` | manual (append-only) | report renderers + ledger consolidation | **NONE** — invariant documented in file header but not gated | **RISK** |
| `tools/tools_manifest.json` | auto (generate_guard_manifest) | run_pipeline preflight + verify_engine_integrity | pipeline-start (hard); verify_engine_integrity (hard); session-close prescribes regen if tools changed | **SAFE** |
| `config/engine_registry.json` | manual | pipeline_utils + verify_engine_integrity + introspection + resolver | downstream fail-closed on missing engine dir | **SAFE** |
| `TradeScan_State/registry/run_registry.json` | auto | system_registry + system_preflight + sweep_registry_gate | preflight parity check + corrupt-JSON fail-hard | **SAFE** |
| `outputs/system_reports/INTENT_INDEX.yaml` | manual | intent_injector hook + post_write_reminder + audit_intent_index | session-close Step 6 (exit 2 blocks) + CI no-naked-fuzzy test | **SAFE** |
| `governance/schemas/VALIDATED_ENGINE.manifest.schema.json` | manual | engine promotion gate | promotion-time | **SAFE** |
| `engine_dev/.../engine_manifest.json` | auto | verify_engine_integrity + resolver + introspection | startup hash check (fail-closed) | **SAFE** |

**Summary**: 2 surfaces classified RISK
(`indicators/INDICATOR_REGISTRY.yaml`, `governance/supersession_map.yaml`).
The indicator registry RISK becomes SAFE after Section 4 patch sequence
patches 1–3 land. The supersession_map RISK requires patch 4. No BUGs
identified.

---

## Section 4 — Minimal patch sequence

Ordered by risk severity descending. Each patch lists the file touched,
the regression test that pins it, and the rationale for it being a
*separate* commit and not folded into a larger one.

### Patch 1 — Wire registry drift check into session-close (close H1 + H2 + H3 + H4 partial)

- **Why first**: highest user-frequency entrypoint. Session-close runs ~every working day; pre-push runs less; pipeline preflight only when pipeline runs. Catches the bypass scenario (`--no-verify`), the manual-YAML scenario (today's NEWSBRK precedent), and the deletion scenario. One step, one file, one assertion.
- **Touched file**:
  - `.claude/skills/session-close/SKILL.md` — add Step 6b "Registry drift check" between Step 6 ("Enforcement system health") and Step 7 ("Pre-Push Gate").
  - Update Quick Version copy-paste section to include the new step.
- **Body**:
  ```
  python tools/indicator_registry_sync.py --check
  # exit 1 → STOP session-close. Run --add-stubs (or manual fix), commit, retry.
  ```
- **Test that pins it**: `tests/test_indicator_registry_sync_hook.py::test_check_command_exits_nonzero_on_drift` (new — extend the existing `test_sync_helper_check_passes_on_real_registry` with the inverse case: stage a phantom registry entry in a fake repo, assert `--check` returns 1).
- **Why not folded into Patch 2 (pre-push)**: session-close runs in worktrees and on main; pre-push only fires from local clones with hooks installed. Different surfaces, different distribution. Session-close is the doc — pre-push is the script. Land docs separately so a botched pre-push install doesn't block close.

### Patch 2 — Add `tools/hooks/pre-push` with the same drift check (close H1 fully)

- **Why second**: covers `--no-verify` bypass at the network boundary. Even if Patch 1 is followed, an operator can skip session-close entirely; pre-push catches it at `git push` time. Mirror the existing `tools/hooks/pre-commit` pattern.
- **Touched files**:
  - **New**: `tools/hooks/pre-push` — a single-purpose script invoking `tools/indicator_registry_sync.py --check`. Exit 1 blocks push.
  - **Update**: `tools/hooks/install.sh` — extend to also copy `pre-push` into `$GIT_COMMON_DIR/hooks/pre-push` (parallel to current `pre-commit` install). One additional `cp -f`.
- **Test that pins it**:
  - `tests/test_indicator_registry_sync_hook.py::test_pre_push_blocks_on_drift` — fake_repo, write the new `tools/hooks/pre-push` into `tmp_path/tools/hooks/`, install via `install.sh`, attempt a `git push` (with a fake remote `--bare` repo as upstream), assert exit 1 and the push is rejected when registry drift is present.
  - `tests/test_indicator_registry_sync_hook.py::test_install_sh_installs_pre_push` — run `install.sh`, assert `<gitdir>/hooks/pre-push` exists and is executable.
- **Why not folded into Patch 1**: pre-push is a tracked-source + install step (parallel to the existing pre-commit pattern). It's a fresh capability with its own failure mode. Separate commit for the rollback story — a push-blocking bug should not require rolling back the session-close doc change.

### Patch 3 — Wire registry drift check into `tools/run_pipeline.py` preflight + `tools/verify_engine_integrity.py` (close H4 — admission-side)

- **Why third**: catches drift at pipeline-run time and at engine self-test time. Pipelines aren't a high-frequency trigger like session-close, but they are the path along which the NEWSBRK bug surfaced — and admission-time enforcement is what Stage-0.5 already does, this just makes the enforcement complete (a registry mismatch with no corresponding directive run today goes unnoticed until next admission of that strategy; this catches it sooner).
- **Touched files**:
  - `tools/run_pipeline.py` — add `verify_indicator_registry_sync(project_root)` adjacent to `verify_manifest_integrity` (line 341). Raise `PipelineAdmissionPause("Indicator registry drift detected — run python tools/indicator_registry_sync.py --check for detail")` on non-zero. Call from the orchestrator boot block at line 903 alongside `verify_manifest_integrity`.
  - `tools/verify_engine_integrity.py` — add a step after `verify_tools_integrity()` at line 429 that runs the same drift check. `sys.exit(1)` on failure.
- **Test that pins it**:
  - `tests/test_indicator_registry_sync_hook.py::test_pipeline_preflight_blocks_on_drift` — invoke `verify_indicator_registry_sync` directly with a synthetic project_root containing drifted state. Assert it raises `PipelineAdmissionPause`.
  - `tests/test_indicator_registry_sync_hook.py::test_engine_integrity_aborts_on_drift` — same, asserting `sys.exit(1)` from `verify_engine_integrity` when run_check() is invoked against a drifted state.
- **Why not folded into Patches 1+2**: these are runtime defenses; Patches 1+2 are author-time/push-time. Different surfaces, different code paths, separate concerns. Folding all into one commit creates one large diff and makes the rollback story messy.

### Patch 4 — Add `governance/supersession_map.yaml` append-only enforcement (close the second RISK)

- **Why fourth**: the supersession_map RISK is real but lower-impact than the registry RISK (it produces wrong report references, not failed admissions). It also has only documented-but-ungated invariants today, so adding enforcement is a net add.
- **Touched files**:
  - **New**: `tools/lint_supersession_map_append_only.py` — git-diff-aware lint. Reads `git show HEAD:governance/supersession_map.yaml` and compares to working tree. Mappings present at HEAD but missing in working tree → FAIL. Reasons / superseded_at_utc / path_b_batch edits to existing keys → FAIL (append-only invariant). Adding new mappings → PASS.
  - `tools/hooks/pre-commit` — wire the lint in, mirroring the existing `lint_indicator_registry_sync.py --staged` invocation.
- **Test that pins it**:
  - `tests/test_supersession_map_append_only.py` (new file) —
    - Case A: HEAD has mapping X, working tree removed X → lint returns 1.
    - Case B: HEAD has mapping X with reason="A", working tree changed reason to "B" → lint returns 1.
    - Case C: working tree adds new mapping Y not in HEAD → lint returns 0.
    - Case D: identical to HEAD → lint returns 0.
- **Why not folded into Patches 1–3**: this is a different governance surface with its own ownership model (manual append-only, not auto-generated). The pattern is reusable for any other manual append-only file (no other identified today — see Section 2.6).

### Patch 5 (optional, after 1–4 are live) — Schema validation on registry entries

- **Why fifth**: schema validation is a quality improvement, not a drift-blocker — Patches 1–3 already catch the structural drift cases that produced today's bug. Schema validation adds a second layer of defense against malformed entries (missing `module_path`, wrong category prefix, etc.) and prevents class-of-bugs we haven't seen yet.
- **Touched files**:
  - `tools/indicator_registry_sync.py` — add `_validate_schema(reg) -> list[str]` and call from `_drift_report` before the disk-vs-registry diff. Schema violations return a separate list; if non-empty, `--check` returns 1 with the schema error codes from Section 1.4.
  - `tools/lint_indicator_registry_sync.py` — when running `--staged`, also pass the schema validation; this surface needs special handling for the `git show :indicators/INDICATOR_REGISTRY.yaml` parse path.
- **Test that pins it**:
  - `tests/test_indicator_registry_sync_hook.py::test_schema_blocks_missing_module_path` (Test C from Section 1.5).
  - `tests/test_indicator_registry_sync_hook.py::test_schema_blocks_category_mismatch`.
  - `tests/test_indicator_registry_sync_hook.py::test_schema_blocks_version_regression` — write a registry with version 2, commit, then write with version 1 to working tree; lint returns 1.
- **Why last**: covers a class of malformations not seen today. Land after the high-frequency drift-prevention patches (1–3) are validating against the real registry without surprises.

### Patches not proposed

- **No prune step**: the registry currently has ~22 stub entries from today's sync, and there is an audit finding flagging 14 NEWSBRK directives importing phantom modules. The principle "stabilize first, prune later" forbids touching either in this plan.
- **No `--diff-filter=D` extension to pre-commit hook**: the deletion case (H3) is already covered by the drift check at I1/I2/I3/I4/I5. Adding it to the pre-commit hook would double-catch and risk over-firing on legitimate refactors that delete the file and the registry entry in the same commit.
- **No new `--validate-schema` subcommand**: schema validation belongs inside `--check`, not as a separate operator subcommand. The drift check shouldn't accept a malformed registry as "in sync".
- **No `tools/audit_intent_index.py` integration of registry drift** (originally proposed as I5): the four other insertions (session-close, pre-push, pipeline preflight, verify_engine_integrity) cover the same surface. Skipping I5 keeps the audit tool focused on intent routing.

---

## Appendix — file map (for traceability of patches)

| Patch | Files touched | Lines (approx) |
|---|---|---|
| 1 | `.claude/skills/session-close/SKILL.md` | +6 |
| 2 | `tools/hooks/pre-push` (new), `tools/hooks/install.sh` | +25, +5 |
| 3 | `tools/run_pipeline.py`, `tools/verify_engine_integrity.py` | +10, +4 |
| 4 | `tools/lint_supersession_map_append_only.py` (new), `tools/hooks/pre-commit`, `tests/test_supersession_map_append_only.py` (new) | +60, +10, +50 |
| 5 | `tools/indicator_registry_sync.py`, `tools/lint_indicator_registry_sync.py`, test extensions | +40, +15, +60 |

Total: roughly 100 LOC of production + 110 LOC of new tests + 6 lines of
documentation. No invasive changes to live tools, no protected-tool
edits, no breaking changes to existing surfaces. Each patch is small
enough to review in one sitting and revert cleanly.
