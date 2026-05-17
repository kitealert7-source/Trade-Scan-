# Known Issues Truthfulness Gate — Design Notes

Background and design rationale for the gate at [`../SKILL.md`](../SKILL.md)
§9b. The skill has the operational commands; this file has the WHY.

## Background — why the gate exists

The S2 fix (2026-05-04) made `system_introspection.collect_known_issues()`
auto-populate the `### Auto-detected` section of `SYSTEM_STATE.md` from
the same signals this gate checks (gate-suite pytest, intent-index
audit, sweep_registry hash drift, broader-pytest baseline). The file is
honest by construction post-regen.

The §9b gate is now a **defensive backup** that catches three failure
modes the auto-populator alone can't cover:

1. **Auto-populator failed to run** — Step 9 regen errored, snapshot is
   stale, no auto section exists.
2. **Operator deferred items the automation can't see** — e.g. a data
   quality issue, an in-flight refactor, a TD that won't surface until
   the next pipeline run. These belong in `### Manual`.
3. **Bash-side double-check** — even if introspection worked, re-derive
   the underlying signals and confirm they agree with what's in the
   file. Catches stale snapshot + auto-populator parser drift.

## Why both Step A and Step B

Step A (broader-pytest baseline) catches **new** failures the
auto-populator can't see — it only checks the gate suite.

Step B (existence-check) catches **silent auto-populator failures** —
the file is missing the section it should have populated.

Together they close the gap that allowed pre-existing failures to slip
past session-close on 2026-05-15.

## Auto-detected vs Manual sections

`SYSTEM_STATE.md`'s Known Issues area has two subsections:

- `### Auto-detected` — regenerates each run from `collect_known_issues()`.
  Don't hand-edit; changes will be clobbered.
- `### Manual` — persists across regen. **UNRESOLVED + operationally
  relevant only** — in-flight TDs, data quality notes, operational
  caveats the operator needs at next-session start. Resolved entries
  (`~~strikethrough~~`, "closed by commit ...", "PASSED" status from
  completed phases, "superseded by ...") get REMOVED at session-close
  §3.2 — not archived. Git preserves history; the file is startup
  decision support, not historical documentation. Edit directly when
  adding; the §3.2 audit handles the prune.
