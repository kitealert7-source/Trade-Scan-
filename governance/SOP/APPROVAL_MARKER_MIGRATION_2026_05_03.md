# Approval Marker Stabilization — Migration Note (2026-05-03)

## What changed

Strategy approval markers (`strategies/<ID>/strategy.py.approved`) moved from
**timestamp-only** (mtime comparison) to **hash-based** (sha256 of strategy.py
bytes). EXPERIMENT_DISCIPLINE checks now validate by content equality, not
file modification time.

## Why

A race between three admission-time mutations and an mtime-based check made
sweeps fail intermittently and forced manual marker refreshes between
admissions:

1. `tools/orchestration/pre_execution.py::enforce_signature_consistency`
   canonicalized `STRATEGY_SIGNATURE`, then wrote a timestamp-only marker.
2. `tools/strategy_provisioner.py` rewrote `strategy.py` during preflight
   (idempotent canonicalization), bumping mtime past the marker mtime.
3. `governance/preflight.py` EXPERIMENT_DISCIPLINE compared raw mtimes →
   falsely tripped because `marker.mtime < strategy.py.mtime` by milliseconds
   even when content was byte-identical.

Symptom: every batch sweep (NEWSBRK S02–S05, prior families) hit
EXPERIMENT_DISCIPLINE blocks within preflight; required manual `touch`
or `--rehash` between admissions.

## The new contract

- **Single source of truth**: `tools/approval_marker.py` provides
  `compute_strategy_hash`, `write_approved_marker`, `is_approval_current`,
  `read_approved_marker`.
- **Write site**: any process that mutates `strategy.py` and re-approves
  MUST call `write_approved_marker(marker, compute_strategy_hash(strategy))`
  immediately after the write. Never write timestamp-only markers.
- **Check site**: any EXPERIMENT_DISCIPLINE / approval-currency check MUST
  call `is_approval_current(strategy, marker)`. Never compare raw mtimes
  between strategy.py and marker.

## Files patched

| File | Change |
|------|--------|
| `tools/orchestration/pre_execution.py` | `enforce_signature_consistency` uses `is_approval_current` + `write_approved_marker` (was: raw timestamp marker write). |
| `tools/strategy_provisioner.py` | Refreshes hash-based marker after `strategy.py` rewrite. |
| `governance/preflight.py` | Both EXPERIMENT_DISCIPLINE checks use `is_approval_current`; second check short-circuits when hash confirms content stable. |
| `tools/reset_directive.py` | Both EXPERIMENT_DISCIPLINE branches use `is_approval_current` with mtime fallback. |

## Backward compatibility

Legacy timestamp-only markers (no `strategy_sha256:` line) continue to work:
`is_approval_current` falls back to mtime comparison when the marker has no
hash field. Auto-consistency upgrades them to hash-based on the next
admission pass — no manual migration needed. Existing strategies in the
field will heal on first run.

## Regression coverage

`tests/test_admission_race_stabilization.py` (11 tests, 6 classes):

1. Hash-marker round-trip (write → validate → read).
2. Legacy timestamp-only marker mtime pass/fail (back-compat).
3. **Idempotent rewrite preserves approval** — the core regression: byte-
   identical rewrite bumps strategy.py mtime past marker mtime, but hash
   match keeps approval current.
4. Genuine content change invalidates marker; re-approval restores it.
5. Cross-process subprocess validation matches in-process result (Windows
   mtime granularity immunity).
6. Static checks: all 4 patched files import + use the canonical helpers.

## How to apply this in new tooling

Any future code path that writes/reads `strategy.py.approved` MUST go through
`tools/approval_marker.py`. Do not roll your own mtime check, do not write
raw "approved: <timestamp>" markers. The race will return.
