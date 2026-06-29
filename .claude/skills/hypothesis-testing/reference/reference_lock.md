# Reference-lock edge cases

> Reference for [`/hypothesis-testing`](../SKILL.md) "Lock the reference run". Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

**Graceful degradation — lock what the resolver returns, note the gaps.** For an old or pruned
reference the resolver yields a *best-available* snapshot with `warnings` (metrics from CSV, a
`provenance_gap`, an absent capsule). That is **not** a halt: lock the fields present, record the
resolver's `warnings` next to `locked_at`, and proceed. The resolver never invents a value — an
`ABSENT` field is locked as absent, not guessed.

**Stale lock is advisory, never a halt.** If the reference run is modified or re-run
mid-session, the orchestrator continues, reports the delta against the now-stale snapshot,
and notes the stale `locked_at` in the §5 record. The human may re-lock if concerned; the
orchestrator never refuses a variant on lock-staleness grounds.

**Stale *baseline* (not just stale lock) → re-baseline via /rerun-backtest first.**
Lock-staleness (the reference was re-run mid-session) is advisory, above. But if the reference
run is stale in *data or engine* terms — more bars now exist, or the engine changed since it ran
— a fresh variant compared against it is not apples-to-apples. Offer to re-baseline the reference
through [`/rerun-backtest`](../../rerun-backtest/SKILL.md) (`DATA_FRESH` / `ENGINE`), then lock the
new run as the reference (re-lock steps below). The human decides; the orchestrator never forces it.

**To re-lock mid-session:** re-run the snapshot commands for the reference run, overwrite the
session note's values, and update `locked_at` to the current UTC. Document the re-lock
timestamp in the session summary so it is clear which baseline was used for subsequent
comparisons.
