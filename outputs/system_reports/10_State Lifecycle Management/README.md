# 10_State Lifecycle Management

Read before performing cleanup, archival, or any operation that deletes or moves run artifacts.

| Document | When to read |
|---|---|
| `Workflow_Design.md` §1-3 | Full lineage-aware cleanup workflow: KEEP_RUNS extraction → referential integrity checks → artifact mapping → dry-run → execution. |
| `Workflow_Design.md` §4 | Directive admission sentinel design, sidecar-pairing invariant, and the live → quarantine → git recovery precedence implemented in `tools/recover_admitted_directive.py`. Read before investigating any "missing" directive. |
| `2026-05-25_admitted_orphan_sweep_manifest.json` | Audit record of the 433-marker orphan sweep on 2026-05-25 (per-entry sha256, mtime, size, quarantine destination). |
| `ORPHAN_RECONCILE_GATE_PLAN_2026-06-25.md` | **PROPOSAL** (awaiting approval) — a post-delete gate that asserts 0 orphaned live rows across every derived sheet + the 3-tier run store. Generalizes the per-sheet orphan detection in `repair_integrity.py` into one non-zero-exit assertion. Read before extending cleanup-time integrity checks. |

**Critical:** Never delete from TradeScan_State without completing Stage 1 (lineage extraction) and Stage 1B (referential integrity check) first. The workflow aborts on any validation failure — this is intentional.

**For "missing" directives:** Run `python tools/recover_admitted_directive.py <DIRECTIVE_ID>` before assuming data loss. Most cases resolve from quarantine without touching git history.
