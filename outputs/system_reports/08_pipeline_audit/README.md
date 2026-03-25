# 08_pipeline_audit

Read before changing artifact storage layout, provenance fields, or stage entry gating.

| Document | When to read |
|---|---|
| `ARTIFACT_STORAGE_AUDIT_2026_03_24.md` | **Start here.** Maps every artifact to its authoritative storage location. Identifies provenance gaps. |
| `ARTIFACT_PROVENANCE_IMPLEMENTATION_PLAN_2026_03_24.md` | Surgical fix plan for provenance gaps (content_hash, git_commit, schema_version). Check status before re-implementing. |
| `Results Output Schema.md` | Before changing results CSV columns or adding new output fields to Stage 1/2. |
| `VERIFY_STAGE_ENTRY_GATING_COVERAGE_V1.md` | Before modifying stage gate logic — maps which gates are enforced at each stage transition. |

**Recommended reading order:** STORAGE_AUDIT → PROVENANCE_PLAN → SCHEMA → GATING
