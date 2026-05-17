# Skill Conventions

Cross-skill formatting and authoring conventions. Companion to
[`SELF_IMPROVEMENT.md`](./SELF_IMPROVEMENT.md) (friction-log / edit-loop
protocol) and [`CATALOG.md`](./CATALOG.md) (by-category skill index).

---

## The `// turbo` marker

A line `// turbo` immediately before a fenced code block marks the
command as **pre-authorized** for this skill — the user has standing
consent for `/skill-name` to run it without pausing for per-call
permission.

**Use it when:**

- The command is a documented step in the skill's flow
- The command is idempotent OR the mutation is the intended effect
- A permission pause would add friction without judgment value
  (the user already opted in by invoking the skill)

**Do NOT use it on:**

- Prose, section headers, or "read this" instructions — the marker is
  a no-op outside a fenced code block
- The first run of a long pipeline whose side effects the operator
  should preview; mark inner commands if needed
- Operations with `--force`, mass deletes, or anything that wants a
  sanity-check before firing

**Placement:** own line, blank line above, code fence directly below.

```markdown
// turbo

```bash
python tools/<command>.py
```
```

---

## Known drift (2026-05-17 audit)

The following `// turbo` placements are no-ops (applied to prose, not
code). Clean up next time the affected skill is edited:

| Skill | Location | Issue |
|---|---|---|
| `rerun-backtest` | §"What `prepare` Does" (~line 75) | marker on numbered prose, no command |
| `rerun-backtest` | §"What `finalize` Does" (~line 96) | marker on numbered prose, no command |
| `update-vault` | Step 1 "Read the contract" (~line 29) | marker on a read instruction |
| `promote` | Pre-Conditions header (~line 49) | marker on numbered checklist |
| `promote` | Single Strategy section (~line 110) | marker on header, commands further down |

These are listed here rather than fixed in bulk so the fix lands with
the next genuine edit to each skill (no churn-only commit).
