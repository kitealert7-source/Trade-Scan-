---
name: git-hygiene
description: Read-only multi-repo git state check — uncommitted, unpushed, branches, untracked (one screenful).
---

# git-hygiene

**Purpose:** answer "what git mess would I leave behind if I stopped now?" across all repos.
One screenful. ~30 seconds. No side effects.

---

## Repos to check

Run all checks against each of these (skip silently if `.git` directory absent):

```
Trade_Scan      (current dir)
DATA_INGRESS    ../DATA_INGRESS
TS_Execution    ../TS_Execution
TradeScan_State ../TradeScan_State
```

---

## Checks

Run all six in parallel via a single bash block:

```bash
python -c "
import subprocess, sys

REPOS = [
    ('Trade_Scan',    '.'),
    ('DATA_INGRESS',  '../DATA_INGRESS'),
    ('TS_Execution',  '../TS_Execution'),
    ('TradeScan_State', '../TradeScan_State'),
]

def git(repo, *args):
    r = subprocess.run(['git', '-C', repo] + list(args),
                       capture_output=True, text=True)
    return r.stdout.strip()

def git_lines(repo, *args):
    out = git(repo, *args)
    return [l for l in out.splitlines() if l.strip()] if out else []

action, cleanup, watch = [], [], []

for name, path in REPOS:
    import os
    if not os.path.isdir(os.path.join(path, '.git')):
        continue

    # 1+3. Branch + unpushed (combined — feature branch alone is not a problem)
    branch = git(path, 'rev-parse', '--abbrev-ref', 'HEAD')
    try:
        count = int(git(path, 'rev-list', '--count', '@{u}..HEAD') or '0')
    except Exception:
        count = 0
    if branch and branch != 'main':
        if count > 0:
            action.append(f'{name}: branch \"{branch}\" + {count} unpushed commit(s)')
        else:
            cleanup.append(f'{name}: on branch \"{branch}\" (all pushed)')
    elif count > 0:
        subjects = git_lines(path, 'log', '--oneline', f'-{count}', '@{u}..HEAD')
        action.append(f'{name}: {count} unpushed commit(s) on main -- {subjects[0] if subjects else \"\"}')

    # 2. Dirty working tree
    dirty = git_lines(path, 'status', '--porcelain')
    if dirty:
        action.append(f'{name}: {len(dirty)} uncommitted change(s)')

    # 4. Unmerged local branches → always WATCH (skill cannot know if safe to delete)
    unmerged = git_lines(path, 'branch', '--no-merged', 'main')
    for b in unmerged:
        b = b.strip().lstrip('* ')
        ahead = git(path, 'rev-list', '--count', f'main..{b}')
        try:
            ahead = int(ahead)
        except Exception:
            ahead = 0
        has_remote = bool(git(path, 'branch', '-r', '--list', f'origin/{b}').strip())
        suffix = f', remote exists' if has_remote else ''
        watch.append(f'{name}: unmerged branch \"{b}\" ({ahead} commit(s) ahead{suffix})')

    # 5. Stale remote branches (merged into main, not main/HEAD itself)
    stale = git_lines(path, 'branch', '-r', '--merged', 'main')
    for b in stale:
        b = b.strip()
        if 'origin/main' in b or 'origin/HEAD' in b:
            continue
        cleanup.append(f'{name}: remote branch \"{b}\" merged, can delete')

    # 6. Untracked non-ignored artifacts (root + nested). --directory collapses a
    #    wholly-untracked dir to one entry (e.g. outputs/cointegration_screener_v1/);
    #    a single --directory call also avoids double-counting files inside such dirs.
    #    --exclude-standard already drops gitignored output, so what remains is
    #    genuinely non-ignored: root files are the classic stray-file mess; nested
    #    dirs/files are accumulating output that likely wants gitignoring (2026-06-19:
    #    an 8.6MB outputs/cointegration_screener_v1/ sat untracked, invisible to the
    #    old root-only filter). Summarised to respect the one-screenful cap.
    untracked = git_lines(path, 'ls-files', '--others', '--exclude-standard', '--directory')
    if untracked:
        root   = [f for f in untracked if '/' not in f.rstrip('/')]
        nested = [f for f in untracked if '/' in f.rstrip('/')]
        parts = []
        if root:
            parts.append(f'{len(root)} root: {\" \".join(root[:3])}')
        if nested:
            more = f' (+{len(nested)-3} more)' if len(nested) > 3 else ''
            parts.append(f'{len(nested)} nested: {\" \".join(nested[:3])}{more}')
        watch.append(f'{name}: untracked -- ' + '; '.join(parts))

# Emit
any_output = False
if action:
    print('ACTION')
    for i in action: print(f'  - {i}')
    any_output = True
if cleanup:
    print('CLEANUP')
    for i in cleanup: print(f'  - {i}')
    any_output = True
if watch:
    print('WATCH')
    for i in watch: print(f'  - {i}')
    any_output = True
if not any_output:
    print('All clean.')
"
```

---

## Output format

Print only non-empty buckets. If all buckets empty, print `All clean.`

```
ACTION          ← must resolve before stopping work
  - repo: issue

CLEANUP         ← deterministic safe deletions (merged remote branches only)
  - repo: issue

WATCH           ← human decision required; includes ALL unmerged local branches
  - repo: unmerged branch "feature/foo" (1 commit ahead)
  - repo: unmerged branch "feature/bar" (8 commits ahead, remote exists)
```

**Unmerged branches are always WATCH, never CLEANUP.** The skill knows *not merged*;
it does not know *safe to delete*. A 1-commit branch can be abandoned or active.
Commit count and remote-exists are severity signals for prioritisation — the human decides.

**Hard cap: one screenful.** If any bucket would exceed ~8 items, truncate with `(+N more)`.

---

## Constraints

- **Read-only.** No commits, no pushes, no deletes.
- **No context loading.** Do not read SYSTEM_STATE, RESEARCH_MEMORY, or any project doc.
- **No interpretation.** Print facts; do not recommend strategies or next research steps.
- **Silent skips.** Repo absent / no upstream set / detached HEAD → skip without warning.

---

## When to invoke

- End of a heavy session before closing
- Weekly on Monday before starting work
- Any time git state feels unclear

## Related skills

- `/session-close` — commits, pushes, and closes the session properly (run this first)
- `/session-start` — broader orientation including research + infra priorities

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| 2026-06-18 | Feature branch alone flagged as ACTION; only actionable when combined with unpushed work | branch+unpushed combined into single check; feature-branch-only demoted to CLEANUP |
| 2026-06-18 | feat/cointegration-onboarding (70 commits) surfaced as CLEANUP alongside 1-commit stale branches — no commit count, no severity signal, no way to distinguish active merge candidate from abandoned stub | All unmerged local branches moved to WATCH; commit count and remote-exists flag added to every entry |
| 2026-06-19 | Untracked check was root-level-only → missed an 8.6MB nested outputs/cointegration_screener_v1/ + a nested scratch harness (Infra-#1 cleanup found them via session-start §1.8, not this skill); also double-counted files in untracked dirs | Check 6 now reports root + nested non-ignored untracked (single --directory call, summarised + capped) |
