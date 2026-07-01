# Invariant Enforcement Map — Audit 2026-07-01

**Question answered:** how many invariants exist, how many have *teeth* (a live mechanism)
vs. are prose-only doctrine, and what to do about the count.

**Scope:** the 32 SYSTEM INVARIANTS in `AGENT.md` (+ 7 engine-standard invariants, summarised
at the end). Each classification below was checked against the codebase, not taken from the
invariant's own prose.

## Summary

| Class | Meaning | Count | Invariants |
|---|---|---|---|
| **MECHANICAL** | A gate / test / hook / hash fails the build or the run if violated | **18** | 1, 4, 5, 10, 12, 14, 15, 16, 17, 19, 20, 21, 22, 23, 27, 28, 29, 32 |
| **PARTIAL** | Some automation, but coverage has gaps (or is self-declared partial) | **8** | 2, 6, 7, 9, 11, 13, 24, 31 |
| **PROSE-ONLY** | Doctrine only — enforced by agent discipline, nothing machine-checks it | **5** | 3, 8, 18, 25, 30 |
| **WAS STALE → FIXED** | Contradicted reality; corrected this audit | **1** | 26 |

So **~56% are mechanically enforced**, ~25% partial, ~16% are honour-system doctrine (5 rows,
down from 6 after #11 was mechanised — see below).
The number (32) is not the problem — a mechanically-enforced invariant costs nothing to
hold, because the gate remembers it, not a human. The risk lives entirely in the
**prose-only** rows.

## The headline finding

**#26 rotted *because* it was prose-only.** It said "15-second cooldown / batch prohibited"
long after the cooldown was removed in code (2026-05-27) and parallelism became opt-in
(CLAUDE.md #7). No mechanism kept it honest, so the doctrine and the code silently diverged
for ~5 weeks. This is the exact failure mode every other prose-only invariant is exposed to.

## Full map (32 system invariants)

| # | Invariant | Enforcement mechanism (verified) | Class |
|---|---|---|---|
| 1 | Ledger Supremacy (append-only) | `test_master_filter_supersession`, `test_supersession_map_append_only`, `lint_supersession_map_append_only` (pre-commit) | MECHANICAL |
| 2 | Fail-Fast | Architectural (`PipelineExecutionError` aborts); no dedicated test | PARTIAL |
| 3 | Artifact Authority | Doctrine — gating reads artifacts, but nothing forbids memory-based gating | PROSE-ONLY |
| 4 | Snapshot Immutability | `STRATEGY_SNAPSHOT.manifest.json` hash → `SNAPSHOT_INTEGRITY_MISMATCH` | MECHANICAL |
| 5 | State Machine Integrity | `PipelineStateManager.verify_state` (pipeline_utils) | MECHANICAL |
| 6 | Directive Integrity | Pipeline moves INBOX→completed; `directive_audit.log` — no guard on tampering | PARTIAL |
| 7 | Deterministic Execution | `test_aggregation_idempotency_run_id` (partial coverage of one layer) | PARTIAL |
| 8 | Single Authority (run_state) | Convention — only `run_pipeline.py` writes; not enforced | PROSE-ONLY |
| 9 | Append-Only Audit | Code uses append mode; no test asserts it | PARTIAL |
| 10 | Human Gating | `PORTFOLIO_COMPLETE` state gate + human promote step | MECHANICAL |
| 11 | **Protected Infrastructure** | `commit-msg` hook `lint_protected_infra_approval.py` — blocks protected-dir commits lacking a `Protected-Infra-Approved:` trailer (landed 2026-07-01, `a7ed489`) | PARTIAL |
| 12 | Single Signature Authority | `directive_schema.normalize_signature` + `lint_signature_completeness` | MECHANICAL |
| 13 | Genesis/Clone Classification | `classifier_gate` (partial) | PARTIAL |
| 14 | No Workspace Mode | `verify_engine_integrity` + `tools_manifest` hash | MECHANICAL |
| 15 | Governance-Authorized Reset | `reset_directive.py` (`--force` removed) → `reset_audit_log.csv` | MECHANICAL |
| 16 | Guard-Layer Manifest | `generate_guard_manifest.py` + `lint_guard_manifest_sync` + `abi_audit` | MECHANICAL |
| 17 | Root-of-Trust Vault Binding | `verify_engine_integrity.py` ↔ `vault/root_of_trust.json` | MECHANICAL |
| 18 | Engine Manifest Generator (human-only) | Convention — "human-only", not machine-enforced | PROSE-ONLY |
| 19 | Directive Schema Freeze | `canonical_schema.py` + `directive_linter.py` (HARD FAIL) | MECHANICAL |
| 20 | Capital Model | `test_capital_wrapper_events` + regression harness `capital_replay` | MECHANICAL (spec) |
| 21 | Namespace Governance | `namespace_gate.py` (Stage -0.30) + `test_namespace_gate_regex` | MECHANICAL |
| 22 | Sweep Registry Integrity | `sweep_registry_gate.py` (Stage -0.35) + `test_sweep_registry_gate_regex` | MECHANICAL |
| 23 | Symbol Universe Admission | `governance/preflight.py` DATA_GATE before Stage-1 | MECHANICAL |
| 24 | Clean Repository Rule | `lint_no_hardcoded_paths` + artifacts-to-State convention (no immutability guard) | PARTIAL |
| 25 | **Scratch Script Placement** | **Agent discipline only — nothing blocks a script in repo root** | **PROSE-ONLY** |
| 26 | ~~Sequential Execution Only~~ → Sequential by Default; Opt-In Parallelism | FileLocks (Stage 3/4) enforce exclusivity; cooldown removed | WAS STALE → FIXED |
| 27 | Multi-Symbol Deployment | `strategy_loader.py` enforces `strategy.name == id` | MECHANICAL |
| 28 | Live Deployment Pre-Gate | Phase-0 smoke + signal-schema validation (TS_Execution) | MECHANICAL |
| 29 | Indicator Separation | `semantic_validator.py` Stage-0.5 (FORBIDDEN_TERMS / ExternalDataGuard / InlineIndicatorDetector) + `lint_indicator_registry_sync` | MECHANICAL |
| 30 | **Mandatory Tool Routing** | **Agent procedure only — consult TOOL_ROUTING_TABLE on failure** | **PROSE-ONLY** |
| 31 | Pipeline-Authoritative Conclusions | Self-declared split: action-layer mechanical (run_id-keyed writes); conclusion-layer STOP-doctrine | PARTIAL |
| 32 | Viewing-Layer / Ledger Separation | View-projections in `GUARD_FILES` + `lint_guard_manifest_sync` | MECHANICAL |

## The prose-only rows (the decay surface)

- **#11 Protected Infrastructure — MECHANISED 2026-07-01 (`a7ed489`), now PARTIAL.** The
  `commit-msg` hook `tools/lint_protected_infra_approval.py` blocks protected-dir commits
  that lack a `Protected-Infra-Approved: <reason>` trailer (auto-regen data exempt). It's a
  deliberate-acknowledgment gate + audit trail (`git log --grep Protected-Infra-Approved`),
  not cryptographic — but it catches accidental protected edits and records every approval.
  The 5 rows below remain honour-system.
- **#25 Scratch Script Placement**, **#30 Mandatory Tool Routing** — agent-discipline only;
  low blast radius, probably fine to leave as labelled doctrine.
- **#3 Artifact Authority**, **#8 Single Authority**, **#18 Engine Manifest Generator** —
  conventions; hard/uneconomic to mechanise.

## Recommendations

1. **Don't cap or consolidate for count's sake.** 32 mechanically-backed invariants is
   cheaper to live with than 10 prose ones. The apparent overlaps (#16/#17/#18 hash-bound
   files; #1/#9/#32 ledger) guard *distinct* surfaces — merging loses specificity.
2. **Label enforcement class inline in AGENT.md.** Tag each invariant `[MECHANICAL]` /
   `[PARTIAL]` / `[DOCTRINE]` so a reader instantly sees which are machine-checked and which
   rest on discipline. Honesty about the soft spots is the point.
3. ~~**Give #11 a mechanism**~~ — **DONE (2026-07-01, `a7ed489`)**: `commit-msg` hook
   `tools/lint_protected_infra_approval.py` blocks protected-dir commits without a
   `Protected-Infra-Approved:` trailer. #11 moved PROSE-ONLY → PARTIAL (still acknowledgment-
   based, not cryptographic). Remaining prose-only: #3, #8, #18, #25, #30.
4. **Add a periodic invariant↔mechanism re-audit** (quarterly, or per governance change) —
   this is the check that would have caught #26 five weeks earlier. Cheap; the audit above is
   the template. Aligns with the "enforceable mechanisms only; optional docs decay" principle.

## Engine-standard invariants (7, brief)

All 7 are MECHANICAL — enforced by `verify_engine_integrity.py` (per-version manifest hash),
`lint_no_removed_engine_imports` (pre-commit), and the `engine_abi` triple-gate: version
namespace, no-core-import-bypass, single execution authority, self-containment, shadow-core
prohibition, manifest localization, vault non-authority.
