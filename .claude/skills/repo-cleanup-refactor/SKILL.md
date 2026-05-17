---
name: repo-cleanup-refactor
description: Periodic repo hygiene + code DRY pass — worktrees, branches, untracked root files, cross-repo state orphans, duplicate-function extraction. Distinct from session-close (per-session) and pipeline-state-cleanup (TradeScan_State pipeline lineage). Run weekend before close, or Monday before starting work.
---

# Repo Cleanup & Refactor Workflow

Periodic hygiene pass for organizational debt that accumulates between sessions. **NOT a substitute for `/session-close` (every session) or `/pipeline-state-cleanup` (pipeline lineage).** This skill focuses on cross-cutting repo hygiene + cross-repo state + code DRY — concerns that don't naturally surface in either of those skills.

**When to run:**
- Weekend before `/session-close` (clears debt before the snapshot)
- Monday before starting work (clean slate)
- After major phase completion (Phase 7a → next phase, etc.)
- Whenever a stuck/disorganized feeling sets in

**When NOT to run:** mid-session active work; right before pushing critical changes (run AFTER they land).

---

## 0. Safety preflight — MANDATORY first step

This skill modifies repo state. Establish what's in flight first; nothing this skill does should touch active processes' state.

### 0a. List long-running processes that own state

```powershell
# Validators / shims / live runners
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*run_validator*' -or
                 $_.CommandLine -like '*basket_pipeline*' -or
                 $_.CommandLine -like '*heartbeat_stale_monitor*' } |
  ForEach-Object {
    $age_min = ((Get-Date) - (Get-Date $_.CreationDate)).TotalMinutes
    Write-Output ("PID " + $_.ProcessId + " alive " + [math]::Round($age_min, 1) + "m: " + $_.CommandLine.Substring(0, [Math]::Min(120, $_.CommandLine.Length)))
  }

# Scheduled tasks
Get-ScheduledTask | Where-Object { $_.State -eq 'Running' } | Select-Object TaskName, State
```

### 0b. Build the don't-touch list

For each in-flight process, identify the paths it reads/writes. Common cases:

| In-flight process | Don't-touch paths |
|---|---|
| TS_SignalValidator validator | `TS_SIGNAL_STATE/decisions/<vault>/`, `TS_SIGNAL_STATE/heartbeats/<vault>/`, `VALIDATION_DATASET/<corpus>/` (read-only) |
| Heartbeat staleness monitor | `TS_SIGNAL_STATE/events/stale_heartbeat.jsonl` (write) |
| basket_pipeline live runner | `TS_SIGNAL_STATE/h2_live/actions.jsonl` (write), `DRY_RUN_VAULT/baskets/<dir_id>/` (read) |
| TS_Execution H2 shim | `TS_SIGNAL_STATE/h2_live/executions.jsonl` (write) |
| Pipeline run | `TradeScan_State/runs/<run_id>/`, `TradeScan_State/backtests/<dir>/` |

**If anything in flight is writing to a path you'd otherwise touch in this skill, defer that step.** The skill is paused, not failed.

### 0c. Verify pre-skill repo state

```bash
git status --short            # what's tracked-dirty / untracked
git log --oneline origin/main..HEAD   # any unpushed work
```

If unpushed work exists: push first or commit deliberately. The skill's commits should land cleanly on top of a synced `main`.

---

## 1. Phase 1 — Repo hygiene (worktrees, branches, root untracked)

### 1a. Worktrees

```bash
git worktree list
```

For each worktree besides `main`:
```bash
# Check ahead-count
git log --oneline main..<branch> | wc -l
```

**Decision rule:**
- **0 ahead** → `git worktree remove --force <path>` then `git branch -D <branch>` (work was already merged or branch is dead)
- **N ahead** → inspect commits via `git log --oneline main..<branch>`:
  - All commits look like operational debris (session snapshots, tools_manifest regens) → same as 0 ahead, delete
  - Real engineering work that wasn't merged but was ABANDONED → tag-before-delete (Phase 1c)
  - Real engineering work in flight → leave alone, flag for operator

After removals: `git worktree prune` to clean up `.git/worktrees/` dangling entries.

### 1b. Standalone branches (no worktree)

```bash
git branch | grep -v "^\*"    # all non-current branches
```

For each `claude/*` branch (or other transient pattern), same ahead-count check + decision rule as 1a.

### 1c. Tag-before-delete for abandoned-but-valuable work

When a branch has unmerged commits that were genuinely abandoned (e.g., a strategy variant that was killed, an experiment that didn't pan out), preserve the commits via a tag before deleting the branch:

```bash
git tag -a archive/<descriptive-name> <branch> -m "Archived YYYY-MM-DD: <N> commits from <branch>. Reason: <abandoned/killed/superseded>. HEAD <short-sha>."
git push origin archive/<descriptive-name>
git branch -D <branch>
```

The tag preserves the commits indefinitely; the branch goes away. `git tag -l "archive/*"` shows everything ever archived this way.

### 1d. Untracked root files

```bash
git status --short | grep "^??"
```

For each untracked file/dir in repo root or `outputs/`:

**Decision tree:**
- **Stale research artifact** (CSVs, JSONs, PNGs from prior sessions, names suggest temporary): `rm -rf` after eyeballing one or two for "yes, this is dead"
- **Audit doc / strategic content** (markdown, has substance, would be useful for future sessions): MOVE to appropriate subfolder (`outputs/system_reports/<area>/`) + RENAME if filename has spaces or is `.txt`-when-it's-markdown + commit
- **External research artifacts** (Pine exports, broker outputs, third-party data): MOVE to `archive/<dated-folder>/` rather than delete
- **Looks important but unclear**: leave alone, ask operator

---

## 2. Phase 2 — State root orphans (TS_SIGNAL_STATE, DRY_RUN_VAULT, etc.)

State roots accumulate per-vault subdirectories. When a vault is retired or replaced, the directories often linger.

### 2a. TS_SIGNAL_STATE orphan vault dirs

```bash
ls C:/Users/faraw/Documents/TS_SIGNAL_STATE/decisions/
ls C:/Users/faraw/Documents/TS_SIGNAL_STATE/heartbeats/
```

Compare against the active in-flight processes' vault_ids (from Step 0a). Any vault_id that:
- Hasn't been written to in days
- Is not the target of any current Task Scheduler entry
- Is not referenced in any `config.*.yaml` you intend to use again

→ safe to `rm -rf`.

**Always preserve `events/`** (DISRUPTION_LOG.jsonl + stale_heartbeat.jsonl + orphan_alert.jsonl). These are operator-managed audit logs.

### 2b. DRY_RUN_VAULT shadow_backups (optional)

Old daily snapshots (`shadow_trades_YYYYMMDD.xlsx`) accumulate. Per the cleanup backlog: leave for now (small, historical reference), revisit only if disk pressure becomes real.

### 2c. Cross-repo state roots (TS_SignalValidator outputs/, etc.)

For each consumer repo (TS_SignalValidator, TS_Execution): check `outputs/` for stale per-run debug logs / metric dumps. Delete if not referenced in any commit message (use `git log --all -S "filename" --oneline` to confirm).

---

## 3. Phase 3 — Code DRY refactoring (within-repo only)

Duplicate logic across modules creates algorithm-drift risk. Periodic extraction keeps it manageable.

### 3a. Find candidate duplicates

Heuristic search:
```bash
# Find function defs that appear in 2+ files (candidates for extraction)
grep -rn "^def [a-z_]" --include="*.py" tools/ | \
  awk -F: '{print $3}' | sort | uniq -c | sort -rn | head -20
```

Visually inspect the top hits. A function with the same body in 2+ places is a refactor candidate.

### 3b. Extraction protocol

For each genuine duplicate:

1. Create a shared utility module at the appropriate level:
   - Same package → `<package>/<topic>_utils.py`
   - Cross-package → `<repo_root>/<topic>.py`
2. Move the function body verbatim (no behavior changes during extraction).
3. Update consumers to import from the new module:
   ```python
   from <package>.<topic>_utils import <fn> as _<fn>
   ```
   The `as _<fn>` rename preserves the existing call-site name (no churn in callers).
4. Run all relevant tests:
   ```powershell
   python -m pytest tests/ -v
   # If any test mocks the function's `os.replace` / similar via the consumer
   # module path, retarget the patch to the new utility module's path.
   ```
5. End-to-end verification (where applicable): re-run the canonical regression that exercises the function (e.g., Stage 1 byte-equivalence replay for TS_SignalValidator).
6. Commit with message documenting:
   - What was duplicated
   - Where (consumers)
   - Behavior preservation evidence (test counts, byte-equivalence hashes)

### 3c. Cross-repo duplication

When the duplicate spans repos (e.g., a helper used in both `Trade_Scan/tools/` and `TS_SignalValidator/`), DO NOT cross the repo boundary. Per H2 plan §1l repo-separation discipline:

- Extract within ONE repo's copy (the canonical home)
- In the OTHER repo's copy: leave the duplicate, ADD a doc-comment pointer to the canonical version, e.g.:
  ```python
  # NOTE: identical to `<other_repo>/<path>::<fn>`. Cannot share across
  # repos by H2 plan §1l. If you change one, change both.
  ```

If many helpers accrue in this pattern: consider vendoring into a shared `engine_abi`-style module (separate decision; out of skill scope).

---

## 4. Phase 4 — Documentation consolidation

### 4a. Audit docs in `outputs/system_reports/`

Subfolder structure (`01_system_architecture/`, `08_pipeline_audit/`, etc.) should be respected. Audit docs that landed at the wrong level:

- `outputs/<file>.md` (root) → move to appropriate `outputs/system_reports/<area>/<file>.md`
- Files with spaces in names → rename
- `.txt` files that are clearly markdown → rename to `.md`

### 4b. Rolling-vs-snapshot policy (operator decision, not skill default)

Periodic audit docs (`PHASE_NN_PROGRESS_AUDIT.md`) should generally be kept per-phase as snapshots. Resist the urge to consolidate into a single rolling log — snapshot attribution is more valuable than less file count.

### 4c. Cross-document staleness

Read the SYSTEM_STATE Manual section + look for items marked closed/done that no longer need the manual entry. Edit to remove or strikethrough — keep the section short.

---

## 5. Phase 5 — Capture policy items

Some cleanup items aren't mechanical — they need explicit operator decisions (retention windows, consolidation strategies, cross-repo concerns). Capture these:

- Add a `## Cleanup items requiring operator decision` section to the most recent `PHASE_NN_PROGRESS_AUDIT.md` (or create `outputs/system_reports/01_system_architecture/CLEANUP_BACKLOG_<date>.md`)
- For each item: state the question, your recommendation, the cost of delaying

---

## 6. Phase 6 — Wrap-up

### 6a. One commit per phase

Don't lump everything into one giant commit. The natural commit groups from this skill:

1. "chore(cleanup): pass N — root untracked + worktrees + state orphans" (Phase 1+2)
2. "refactor(<scope>): extract <X> shared module" (Phase 3, one per extraction)
3. "docs: <audit-doc-update>" (Phase 4 + 5)

Each commit body should document what was decided + verification evidence.

### 6b. Push + verify

```bash
git push origin main
git status --porcelain | grep -v "^??"   # must be empty
```

### 6c. Post-skill verification

Re-run the safety preflight (Step 0a) — confirm any in-flight processes are still healthy. The skill should NOT have affected them; this verifies.

### 6d. Optionally trigger `/session-close`

If running this skill before EOD, follow up with `/session-close` to formalize the snapshot.

---

## Anti-patterns (don't)

- **Don't lump everything into one commit.** Phase-by-phase commits make rollback granular.
- **Don't delete `.git/` debris with `rm -rf`** — use `git worktree remove` / `git branch -D` / `git tag -d` so git's own bookkeeping stays consistent.
- **Don't run during active validator / live-trading processes** unless you've verified your operations don't touch their state paths.
- **Don't extract refactors during high-stakes pre-deployment windows** (e.g., 24h before a Phase X go-live). Wait for a calm window.
- **Don't delete branches with unmerged commits without tag-then-delete.** Even abandoned work is sometimes useful as a historical reference.
- **Don't consolidate per-phase audit docs into a rolling log.** Each is a moment-in-time snapshot — attribution matters.

---

## Recovery

Everything this skill does is recoverable:

- **Deleted untracked files**: gone unless backed up. Inspect carefully before deleting.
- **Deleted tracked files**: in git history (`git log --all --diff-filter=D --name-only` to find).
- **Deleted branches**: in git reflog for ~90 days; if you tag-before-delete, indefinitely.
- **Refactored modules**: previous version in git history; revertable per-commit.
- **State root cleanup**: gone unless backed up — for `events/*.jsonl` files, never delete; for vault-specific dirs, content was re-derivable from the active vault anyway.

If something goes wrong and the validator dies because of a step in this skill: that's a skill bug, not your error. Filing it as a counter-example to incorporate into the next version is more useful than blame.

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
