---
title: Worktree Reconciliation — Hardening Sprint Lineage
date: 2026-05-03
mode: read-only audit (no commits, edits, resets, stashes, or cleans performed)
---

# Worktree Reconciliation — H2 + Final Hardening Sprint

## TL;DR

The H2 closure + Final Hardening Sprint work is **safe and intact** in the main checkout (`C:/Users/faraw/Documents/Trade_Scan`) on branch `spike/v1_5_9_extraction`. It is **uncommitted but fully staged**. No re-implementation needed.

The vigilant-allen-a3c2a7 worktree contains a **stale duplicate** of the framework-stabilization work that has already been committed to main as `afeda0a` (tag: `FRAMEWORK_BASELINE_2026_05_03`). Its 12 staged files overlap two key files (`tools/orchestration/pre_execution.py`, `tools/tools_manifest.json`) with the hardening sprint and contain **older versions** that would regress the hardening if committed.

---

## Q1. Which checkout contains the real hardening work?

**Main checkout: `C:/Users/faraw/Documents/Trade_Scan`** on branch `spike/v1_5_9_extraction`, HEAD `5e7da71`.

All seven anchor files are present:

| Anchor | Status |
|---|---|
| `outputs/H2_CLOSURE_2026_05_03.md` | PRESENT (untracked) |
| `outputs/FINAL_HARDENING_SPRINT_2026_05_03.md` | PRESENT (untracked) |
| `outputs/ADVERSARIAL_INFRA_AUDIT_2026_05_03.md` | PRESENT (untracked) |
| `tests/test_lint_encoding_extended.py` | PRESENT (staged, A) |
| `tests/test_manifest_hash_guard.py` | PRESENT (staged, A) |
| `tests/test_state_paths_worktree.py` | PRESENT (staged, A) |
| `tests/test_sweep_registry_writers_hardened.py` | PRESENT (staged, A) |

Content markers verified in `outputs/FINAL_HARDENING_SPRINT_2026_05_03.md`:
- "Can framework state files be moved between Windows/Linux..." ✓
- "Can state, registry, or integrity silently diverge..." ✓

**15 hardening-related files staged in main:**
```
config/state_paths.py
tests/test_lint_encoding_extended.py
tests/test_manifest_hash_guard.py
tests/test_state_paths_worktree.py
tests/test_sweep_registry_writers_hardened.py
tools/capital/capital_broker_spec.py
tools/create_audit_snapshot.py
tools/lint_encoding.py
tools/new_pass.py
tools/orchestration/pre_execution.py
tools/orchestration/watchdog_daemon.py
tools/robustness/loader.py
tools/run_pipeline.py
tools/sweep_registry_gate.py
tools/tools_manifest.json
```

This matches the 15-file Commit 1 manifest from the prior session summary exactly.

`tools/lint_encoding.py` shows status `MM` — staged H2-extension version PLUS an unstaged modification on top, which is the cp1252-stdout fix from this session (UTF-8 stdout reconfigure block at lines 30–38). That fix is required to unblock the pre-commit hook.

---

## Q2. Which checkout contains the staged framework stabilization work?

**Both — but main's is committed, the worktree's is uncommitted duplicate.**

| Checkout | State |
|---|---|
| Main (`C:/Users/faraw/Documents/Trade_Scan`) | Already committed as `afeda0a` (tag `FRAMEWORK_BASELINE_2026_05_03`) on 2026-05-03 |
| `.claude/worktrees/vigilant-allen-a3c2a7` | Same 12 files staged, uncommitted, on branch `claude/vigilant-allen-a3c2a7` (HEAD `c0e14e8`) |

The 12 files staged in vigilant-allen-a3c2a7 match `git show afeda0a --stat` exactly:

```
governance/SOP/APPROVAL_MARKER_MIGRATION_2026_05_03.md         (new)
governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md           (new)
governance/SOP/CLASSIFIER_GATE_SCOPING_PLAN_2026_05_03.md      (new)
governance/preflight.py
outputs/FRAMEWORK_STABILIZATION_PROOF_2026_05_03.md            (new)
tests/test_admission_race_stabilization.py                     (new)
tests/test_classifier_gate.py
tools/classifier_gate.py
tools/orchestration/pre_execution.py
tools/reset_directive.py
tools/strategy_provisioner.py
tools/tools_manifest.json
```

The `claude/vigilant-allen-a3c2a7` branch was apparently created from an older base (before `afeda0a`) and accumulated the same admission-race + classifier-gate work in parallel. The work was completed and committed in main's branch (`spike/v1_5_9_extraction`) but the vigilant-allen-a3c2a7 worktree was never rebased or synced.

The third worktree, `hardcore-snyder-32cef5` (branch `claude/hardcore-snyder-32cef5` at `bf6c77d`), contains **none** of the H2 / hardening / framework-stabilization artifacts. It is on an older commit (`bf6c77d`) that predates all of this work.

---

## Q3. Conflicting versions of pre_execution.py / lint_encoding.py / tools_manifest.json?

### `tools/orchestration/pre_execution.py` — REAL CONFLICT

Both checkouts have this file staged with different content:

- **Main staged** (hardening sprint version): `_update_sweep_registry_hash` refactored to route through the canonical lock-protected `update_sweep_signature_hash` API in `sweep_registry_gate.py`. Eliminates substring-matching corruption + concurrent-write race. ~50 lines added/changed.
- **vigilant-allen-a3c2a7 staged** (framework-baseline version, identical to `afeda0a`): the older `_update_sweep_registry_hash` that uses substring matching + direct `write_text`.

If vigilant-allen-a3c2a7 commits and is later merged anywhere upstream of main, the C3+M5 hardening would be silently reverted.

### `tools/lint_encoding.py` — DIVERGENT (no actual conflict yet)

- **Main**: HEAD has the bare-`read_text()`-only version. Main has staged the full H2 extension (read_text + write_text + open). On top of staging, an unstaged modification adds the UTF-8 stdout reconfigure block needed to unblock the pre-commit hook.
- **vigilant-allen-a3c2a7**: HEAD-clean (working-tree matches HEAD = the bare-read_text version). My earlier Edit attempt against this worktree's path appears to have landed on the main checkout file instead (the unstaged diff in main shows my exact insertion, vigilant-allen-a3c2a7's working-tree copy is unchanged).

Only main contains the H2 work; vigilant-allen-a3c2a7 doesn't have a competing version.

### `tools/tools_manifest.json` — TRIVIAL DRIFT

- Both checkouts have the file staged.
- Diff is one line: the `generated_at` timestamp.
- Hash content fields (the load-bearing data) need to be regenerated post-commit anyway, so this is irrelevant — but if vigilant-allen-a3c2a7 commits its version, hash-guard tests in main may need re-baselining.

### Other overlap (informational)

The vigilant-allen-a3c2a7 worktree also stages `governance/preflight.py`, `tools/classifier_gate.py`, `tools/reset_directive.py`, `tools/strategy_provisioner.py`, `tests/test_classifier_gate.py`. All are bit-for-bit identical to what's already in `afeda0a`. Committing them in vigilant-allen-a3c2a7 would create a redundant-but-harmless duplicate commit that any merge to main would resolve as a no-op (since main already has them).

---

## Q4. Which branch/checkout should become canonical?

**Main checkout (`C:/Users/faraw/Documents/Trade_Scan`, branch `spike/v1_5_9_extraction`).**

Reasons:
1. It already holds the FRAMEWORK_BASELINE_2026_05_03 + EVENT_READY_BASELINE_2026_05_03 anchor commits. Lineage is intact through to those tags.
2. It contains the only copy of the H2 / Adversarial Audit / Final Hardening Sprint reports.
3. It has the 4 new test files staged (the regression coverage that proves hardening correctness).
4. Its staged `pre_execution.py` is the only correct (lock-protected) version.
5. The pre-commit fix to `lint_encoding.py` (cp1252 stdout safety) only exists here as an unstaged modification on top of the H2 staging — committing this is the unblock for the original "Commit 1" attempt.

The vigilant-allen-a3c2a7 worktree should be **abandoned** for the hardening lineage:
- Its 12 staged files are duplicates of `afeda0a` (already in main's history).
- Its staged `pre_execution.py` is the **older, unhardened** version.
- Its branch (`claude/vigilant-allen-a3c2a7`) does not contain the FRAMEWORK_BASELINE or EVENT_READY tags.

The hardcore-snyder-32cef5 worktree is uninvolved (older base, no relevant artifacts).

---

## Recommended commit action

1. **Switch to the main checkout.** All subsequent work happens in `C:/Users/faraw/Documents/Trade_Scan` against branch `spike/v1_5_9_extraction`. Do not commit anything in vigilant-allen-a3c2a7 — its staged 12 files would be a redundant snapshot of `afeda0a` and its `pre_execution.py` would regress hardening if it ever merged.

2. **Stage the lint_encoding.py cp1252 fix.** In main, `tools/lint_encoding.py` currently has the H2 extension staged + the UTF-8 stdout reconfigure unstaged on top. `git add tools/lint_encoding.py` to combine.

3. **Run the pre-commit hook locally first** (before `git commit`) to confirm the cp1252 fix works:
   ```
   python tools/lint_encoding.py --staged
   ```
   Expected: clean exit, or any printed VIOLATION lines now render without `UnicodeEncodeError`.

4. **Commit 1 — code + tests** (15 files):
   ```
   infra: complete hardening sprint (C1, C2, C3, M5) + H2 encoding closure
   ```

5. **Commit 2 — docs** (3 untracked outputs):
   ```
   git add outputs/ADVERSARIAL_INFRA_AUDIT_2026_05_03.md \
           outputs/FINAL_HARDENING_SPRINT_2026_05_03.md \
           outputs/H2_CLOSURE_2026_05_03.md \
           outputs/WORKTREE_RECONCILIATION_2026_05_03.md
   ```
   Suggested subject:
   ```
   docs: close infrastructure hardening and encoding audit
   ```

6. **Re-issue regression manifest** (Step 3 of the original three-item plan): update `outputs/framework_baseline/REGRESSION_MANIFEST.md` with the new sha256 of `tools/orchestration/pre_execution.py` and the four new test files. Commit 3.

7. **Tag** `INFRA_HARDENED_BASELINE_2026_05_03` on the head of the docs/manifest commit.

8. **Append RESEARCH_MEMORY entries** (NEWSBRK NAS100 KILL, Path B selection-bias methodology lesson, PORT/MACDX duplication pattern). Commit 4 — only after explicit user review of the drafted entries (per CLAUDE.md research-memory append discipline).

9. **Decide vigilant-allen-a3c2a7's fate separately.** Once main is committed and tagged, the vigilant-allen-a3c2a7 worktree is just an orphaned duplicate of pre-hardening framework-baseline work. Options:
   - Discard the staged changes (`git reset`) and remove the worktree (`git worktree remove`).
   - Leave it idle and clean it up at session-close.
   - Do **not** commit and merge — it would regress `pre_execution.py`.

---

## Confirmation: nothing was modified during this audit

This audit performed only:
- `git worktree list`, `git status`, `git log`, `git show`, `git diff`, `git tag --list`
- `ls`, `Read` (file content)
- `Grep` (content marker search)

No `git add`, `git commit`, `git reset`, `git stash`, `git clean`, file edits, or file writes (other than this report itself).

The pre-existing diff against `tools/lint_encoding.py` in the main checkout (the UTF-8 stdout reconfigure block) was created in the **previous** session, not this one — it was already on disk when this audit began.
