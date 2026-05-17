# Skill Self-Improvement Protocol

How a `SKILL.md` improves itself based on friction the agent surfaced
while using it. Referenced by the `## Friction log` section in each
SKILL.md — the protocol lives here once; logs live next to each skill.

## When to log

LOG when an invocation surfaced friction the next invocation should
not re-discover:

- A precondition the skill didn't mention caused a step to fail
- A command was wrong / stale / missing a flag
- The agent had to scan the repo for a file or symbol the skill could have named
- A pitfall not covered in the existing `Anti-patterns` / `Pitfalls` bit the agent
- A documented step drifted out of sync with the tool it invokes

DO NOT log:

- Clean runs — the skill worked, nothing to learn
- One-off environment issues (network blip, transient file lock)
- User-error, not skill-error
- Friction already covered by an existing section (just follow it next time)
- Anything that needs more than a 5-line edit — that is a refactor, not
  a friction edit; surface it as a task instead

## Edit cap

Each candidate edit is **≤5 net added lines**. Prefer extending an
existing section over adding a new one. If the fix needs more, it is
not a friction edit.

## Approval flow

At end of task, for each in-scope friction the agent proposes:

```
FRICTION: <one-line, what went wrong>
WHERE:    <skill>, <section or step number>
EDIT:     <old_string → new_string, ≤5 net added lines>
LOG ROW:  | <YYYY-MM-DD> | <friction, ≤80 chars> | <edit, ≤80 chars> |
```

User responds **approve / reject / modify** per item. On approve, the
agent lands the skill body edit and the log row in a single commit:

```
skill(<name>): friction-log update — <one-line friction>
```

No auto-apply. No batch approval. Each friction is its own decision.

## Archive rule

Each skill's `## Friction log` caps at **10 entries**. On the 11th:

1. Create `.claude/skills/<skill>/friction_archive.md` if absent
2. Move the oldest row from the live table to the archive (preserve date order)
3. Append the new row to the live table

Archive is append-only; never pruned.

## Phrasing rules

- **Friction column:** ≤80 chars, past tense, what went wrong (not what was fixed)
- **Edit landed column:** ≤80 chars, past tense, what changed (not rationale)

## Out of scope

- Stylistic notes ("this could be cleaner") — not friction
- Backlog of planned improvements — use a task or memory entry
- Substitute for `## Related Files` / `## Anti-patterns` — those are
  first-class skill content; the log is only the history of how the
  skill grew
