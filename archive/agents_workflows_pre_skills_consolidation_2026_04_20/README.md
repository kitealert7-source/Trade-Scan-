# Archived: `.agents/workflows/` — 2026-04-20

This directory is the **frozen** copy of `.agents/workflows/` immediately before the
skills consolidation on 2026-04-20.

## Why this was archived

The repo previously maintained 15 skill documents in **two parallel locations**:

- `.agents/workflows/<name>.md` — flat directory used by `tools/audit_intent_index.py`
  and referenced across governance docs.
- `.claude/skills/<name>/SKILL.md` — folder-per-skill form required by Claude Code
  for runtime skill discovery (`/<name>` invocation).

An audit found that **every one of the 15 pairs had drifted** — some files had richer
bodies on one side, some on the other, and a recent burn-in constraint edit only
landed in the `.agents/` copy.

To eliminate the drift class permanently, `.claude/skills/` became the single source
of truth (runtime requires it) and `.agents/workflows/` was archived here. Per-pair
merges were applied to `.claude/skills/` before archival so no content was lost:

| File                            | Merge direction        |
|---------------------------------|------------------------|
| `format-excel-ledgers.md`       | `.agents/` body → skills, kept skills `name:` |
| `rerun-backtest.md`             | `.agents/` body → skills, kept skills `name:` |
| `session-close.md`              | `.agents/` body → skills, kept skills `name:` |
| `system-maintenance.md`         | `.agents/` body → skills, kept skills `name:` |
| *(other 11 files)*              | skills version already authoritative |

## Use this archive for

- Historical forensics — what the `.agents/` copy said at a given moment.
- Recovery if a merge missed content (diff any file here against its
  `.claude/skills/<name>/SKILL.md` counterpart).

## Do NOT

- Edit files here. This is frozen history, not an active workflow store.
- Re-introduce `.agents/workflows/` elsewhere in the tree.

## Current location

All operational skills now live in `.claude/skills/<name>/SKILL.md`. References in
`CLAUDE.md`, `AGENT.md`, `tools/audit_intent_index.py`, and related docs were
updated in the same commit as the archival.
