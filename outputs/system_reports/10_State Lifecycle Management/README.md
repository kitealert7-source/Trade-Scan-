# 10_State Lifecycle Management

Read before performing cleanup, archival, or any operation that deletes or moves run artifacts.

| Document | When to read |
|---|---|
| `Workflow_Design.md` | **Only document here.** Full lineage-aware cleanup workflow: KEEP_RUNS extraction → referential integrity checks → artifact mapping → dry-run → execution. |

**Critical:** Never delete from TradeScan_State without completing Stage 1 (lineage extraction) and Stage 1B (referential integrity check) first. The workflow aborts on any validation failure — this is intentional.
