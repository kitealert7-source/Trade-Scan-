---
name: skill-maintenance
description: Governed audit of all .claude/skills/ — verifies friction-log format, SELF_IMPROVEMENT.md compliance, archive caps, and reference-link integrity. Read-only by default; lands at most one commit on explicit human approval. Triggered automatically by /session-close §6c when skills were invoked, or manually when skill drift is suspected.
---

# /skill-maintenance — Governed Skill Audit

Read-only scan of every `SKILL.md` under `.claude/skills/` against the
contracts in [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md) and
[`../CONVENTIONS.md`](../CONVENTIONS.md). Produces a concise report of
actionable issues with proposed surgical fixes, stops for human
approval, then lands at most one commit on `apply`.

> **Never auto-edit. Never auto-apply.** The whole point of this skill
> is human-gated governance — silent fixes defeat the purpose.

---

## When to run

- **Automatic:** called by [`/session-close`](../session-close/SKILL.md) §6c as
  the final governance checkpoint before the pre-push gate, when one
  or more skills were invoked during the session.
- **Manual:** when skill drift is suspected — friction logs feel
  stale, headers look inconsistent across skills, or a recent rename
  / split didn't fully propagate.

---

## Scope

| In scope | Out of scope |
|---|---|
| Every `<skill>/SKILL.md` (frontmatter, friction log, pointer integrity) | Skill body prose, command correctness, operational logic |
| Every `<skill>/reference/*.md` (existence of referenced files) | Cross-skill semantic consistency beyond format/link integrity |
| Every `<skill>/friction_archive.md` (overflow file presence) | The doctrine docs themselves (`SELF_IMPROVEMENT.md`, `CONVENTIONS.md`, `CATALOG.md`) |
| Doctrine pointers in SKILL.md back to `../SELF_IMPROVEMENT.md` etc. | |

---

## Checks

| # | Check | Source contract | Severity |
|---|---|---|---|
| 1 | `## Friction log` section present | SELF_IMPROVEMENT.md | hard |
| 2 | Protocol pointer line present (`Protocol: see [...](../SELF_IMPROVEMENT.md).`) | SELF_IMPROVEMENT.md | hard |
| 3 | Table header exactly `\| Date \| Friction (1 line) \| Edit landed \|` | canonical (set 2026-05-17) | hard |
| 4 | Header followed by separator `\|---\|---\|---\|` | markdown grammar | hard |
| 5 | No pending friction without landed edit (Friction filled, Edit landed empty) | SELF_IMPROVEMENT.md (single-commit rule) | hard |
| 6 | No duplicate friction text across live-log rows | SELF_IMPROVEMENT.md (dedup intent) | soft |
| 7 | Live log ≤10 data rows; overflow triggers an archive action | SELF_IMPROVEMENT.md archive rule | hard |
| 8 | If row count >10, `friction_archive.md` must exist | SELF_IMPROVEMENT.md archive rule | hard |
| 9 | Date column matches `YYYY-MM-DD` (or `_none yet_` placeholder) | SELF_IMPROVEMENT.md phrasing | soft |
| 10 | Friction column ≤80 chars; Edit landed column ≤80 chars | SELF_IMPROVEMENT.md edit cap | soft |
| 11 | Frontmatter `name:` matches the folder slug | skill conventions | hard |
| 12 | All relative `./reference/<file>.md` links resolve on disk | filesystem | hard |
| 13 | If a pointer to `./friction_archive.md` exists, file must resolve | filesystem | hard |

**Hard** = blocks the audit "clean" verdict; surfaced as auto-fixable
or as needs-operator-decision.
**Soft** = surfaced for visibility; apply can proceed without them.

---

## Step 1 — Enumerate skills

Use `Glob` to list every `.claude/skills/*/SKILL.md`. Derive the slug
from each parent folder name. Skip `CATALOG.md`, `CONVENTIONS.md`,
`SELF_IMPROVEMENT.md` — they are doctrine, not skills.

## Step 2 — Read the doctrine

Read `SELF_IMPROVEMENT.md` and `CONVENTIONS.md` to capture the
canonical strings used in checks 2 + 3 + 4. The audit reads contracts
dynamically — if the canonical header changes in the protocol, this
audit picks it up next run without code edits here.

## Step 3 — Per-skill scan

For each skill, read its `SKILL.md` and apply checks 1–11. Parse the
friction-log table (rows after the `|---|---|---|` separator until the
next blank line or EOF) and collect violations into a per-skill
findings list.

## Step 4 — Reference-link integrity

For each `SKILL.md`, extract every relative markdown link matching
`./reference/<file>.md` or `./friction_archive.md`. Verify each
referenced file exists on disk. Missing → check 12 / 13 violation.

## Step 5 — Produce the review report

Print the report to the operator. Format:

```
=== SKILL MAINTENANCE REPORT (<UTC>) ===
Skills scanned: N
Hard findings : H        Soft findings: S

Auto-fixable (will land on `apply`):
  [<skill>] #3 header drift
    OLD: | Date | Friction | Edit landed |
    NEW: | Date | Friction (1 line) | Edit landed |
  [<skill>] #7 archive overflow (12 rows)
    ACTION: move oldest 2 rows → friction_archive.md (create if absent)
  [<skill>] #2 missing protocol pointer
    INSERT below `## Friction log` line:
      Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

Needs operator decision (NOT auto-fixable):
  [<skill>] #5 pending row 2026-05-12 "<friction>" has no Edit landed
    → operator either provides the Edit text, or removes the row

Soft / informational (no fix proposed):
  [<skill>] #9 row 2026-05-17 date is "May 17, 2026" not "2026-05-17"

Continue with `apply` / `apply except <skill>` / `skip` / `dry-run-only`?
==========================================
```

If **all skills pass**, print `All N skills clean — no action
required.` and exit. Do not prompt for approval when nothing needs to
happen.

## Step 6 — Human approval gate

Wait for explicit `apply` (or scoped variant). `skip`,
`dry-run-only`, or no response → exit without changes.

**No batch flag. No implicit yes.** Partial approvals are honored
(e.g., `apply only header fixes` → only checks #3 / #4 / #11 fixes).

## Step 7 — Apply (governed)

For each approved auto-fixable finding:

- **Header / schema fix** → `Edit` the SKILL.md to rewrite the
  canonical header (≤5 net added lines).
- **Missing protocol pointer** → `Edit` to insert the pointer line
  directly below `## Friction log`.
- **Archive overflow** → create `<skill>/friction_archive.md` if
  absent, move the oldest rows from the live log table to the archive
  (preserve date order), commit both files together.
- **Missing reference file** → flag as needs-operator-decision; do
  NOT auto-create empty stubs.
- **Pending friction with no Edit landed** → flag as
  needs-operator-decision; do NOT hand-write the missing Edit text
  (guessing produces fake history).

Stage every affected file by explicit path (no `-A`). Single commit:

```
skills: maintenance audit <UTC-date> — <N> fixes, <A> archive actions
```

## Step 8 — Post-apply verification

Re-run Steps 1–5 against the working tree. Expected: 0 hard findings
on the previously-flagged skills. If hard findings remain, the apply
was incomplete — surface the delta and stop without further commits.

Report final status:

| Item | Value |
|---|---|
| Skills scanned | N |
| Hard findings (pre) | H |
| Auto-fix edits applied | F |
| Archive actions | C |
| Decisions deferred to operator | D |
| Commit | `<SHA>` |
| Hard findings (post) | 0 (expected) |

---

## Anti-patterns

- **Auto-apply without explicit approval.** The whole point of this
  skill is human-gated governance.
- **Bulk-fix soft findings without the operator opting in.** Soft is
  informational; phrasing and date-format choices stay with the operator.
- **Edit >5 net added lines per fix.** Anything larger is a refactor;
  escalate rather than force.
- **Touch out-of-scope content** (skill body, command correctness,
  prose). This audit is format-and-link only.
- **Hand-write fixes for pending-friction rows.** The Edit-landed text
  comes from the operator who saw the friction — guessing it here
  produces fake history.
- **Modify SELF_IMPROVEMENT.md or CONVENTIONS.md mid-audit to make
  findings disappear.** Doctrine changes are a separate decision; the
  audit reports against the doctrine in effect at scan time.

---

## Related

- [`/session-close`](../session-close/SKILL.md) — calls this skill at
  §6c when any skill was invoked during the session
- [`SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md) — the friction-log /
  edit-loop protocol this audit enforces
- [`CONVENTIONS.md`](../CONVENTIONS.md) — `// turbo` doctrine + other
  cross-skill conventions
- [`CATALOG.md`](../CATALOG.md) — by-category skill index

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
