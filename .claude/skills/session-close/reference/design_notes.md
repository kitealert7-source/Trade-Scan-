# Session-Close Design Notes

Background and rationale for non-obvious choices in
[`../SKILL.md`](../SKILL.md). The skill body owns the operational
commands and gates; this file owns the WHY.

---

## Design principle: transactional finalization, not maximum cleanliness

Session-close optimizes for **deterministic transactional finalization**
— commit, gate, push, snapshot — and explicitly NOT for *maximizing
system cleanliness*. Hygiene, refactoring, audits, and periodic
maintenance live in other skills or in Deferred Maintenance, not here.

The principle exists because operational gravity is a one-way ratchet:
every step added to session-close survives forever, makes the close
longer, and (worse) trains future contributors to add more. Resisting
that ratchet requires an explicit gate before any new step lands.

### Step taxonomy

When considering whether a new step belongs in session-close, classify
it against the table below. Only the first two categories live here.

| Category | Test | Goes in |
|---|---|---|
| **CORE** | Skipping fails a transactional or integrity guarantee (commit, push, hard gate, snapshot consistency) | session-close §3 CORE block |
| **EPILOGUE** | Skipping degrades next session's correctness, but no guarantee fails immediately (e.g., stale idea-gate joins, missing ledger export) | session-close §3 EPILOGUE block |
| **Deferred Maintenance** | Skipping accrues cleanliness debt over time; nothing breaks | `SYSTEM_STATE.md ## Deferred Maintenance` (emitted by §3.9) |
| **Manual/operator-curated** | Operator-specific; no automation possible | `SYSTEM_STATE.md ## Known Issues ### Manual` (operational caveats) or `## Deferred Maintenance ### Manual` (deferred hygiene) |

### Anti-pattern to resist

The natural tendency when a problem surfaces during a session is to add
"a quick check at session-close to catch this next time." That check
then runs every session forever, even when no signal is present. The
right response in 90% of cases:

- If the problem has a **detectable signal** → emit a Deferred Maintenance
  entry (§3.9), not a new step
- If the problem **already has a skill that handles it** → reference that
  skill, don't duplicate
- If the problem is **truly transactional or integrity-critical** → CORE
  or EPILOGUE, with explicit justification in this file

---

## Ordering principle: SYSTEM_STATE regen is FINAL

`SYSTEM_STATE.md` is regenerated as the LAST step of Phase 3, *after*
the main push, so its snapshot reads `0 unpushed` and reflects the
session's true end state. Committing it earlier bakes a misleading
"BROKEN: N unpushed" line into the snapshot — which the next session's
first read then propagates as gospel.

---

## §3.5 indicator registry drift — why a defence layer

The pre-commit hook catches new indicator files added without a
registry entry, but there are bypass paths:

- `git commit --no-verify` (skips the hook)
- Manual YAML edits introducing phantom entries (no `.py` diff to
  trigger the hook)
- Indicator file deletion without removing the registry entry

The drift check at Phase 3.5 catches all three. This is the defence
layer against the same class of bug that produced the 22-module
registry gap closed by the 2026-05-12 governance sync. Stage-0.5
admission still enforces the invariant at directive entry — Phase 3.5
makes sure drift never leaves the local clone in the first place.

---

## §3.9 weekend periodic skills — why a structural reminder

Repo debt + state drift + memory drift all accrue silently between
sessions. Without a structural reminder they never get addressed
until something breaks. The weekend slot was chosen because:

(a) Most strategy work happens weekdays
(b) FX market is closed → no live activity to coordinate around
(c) The operator is more likely to have buffer time

The drift-triggered subset runs only when a threshold is crossed, so
the prompt isn't busywork on a calm weekend.

---

## §3.10 in-flight activity during close

If a background pipeline run has altered other tracked files between
the pre-push gate (Phase 3.7) and the FINAL regen (Phase 3.10) — e.g.
sweep_registry reservation, tools_manifest regen, a new directive
file — those changes are NOT part of this session's close. The fix:
`git checkout --` the SYSTEM_STATE you just wrote, note the in-flight
activity in the Phase 4 summary, and let the NEXT session close it.

This keeps the session boundary clean rather than chasing a moving
target.

---

## §3.11 HEAD consistency — the permanent off-by-one

After the closing commit lands, `SYSTEM_STATE.md`'s `Last substantive
commit:` line will necessarily reference the commit BEFORE itself —
the file cannot self-reference its own commit hash without amend-loop
gymnastics.

This permanent off-by-one is acceptable AS LONG AS the file documents
the prior session-close commit, not an even-earlier one. The label
"substantive" makes the semantic explicit: it is the last commit
other than the snapshot itself, not HEAD. The next session's first
read sees `Last substantive commit: <closing snapshot hash>` — which
identifies the prior session's true end state.
