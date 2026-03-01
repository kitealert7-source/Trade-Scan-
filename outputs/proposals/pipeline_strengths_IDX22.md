# Pipeline Strengths — IDX22 Run Observations

**Source:** IDX22 live run post-mortem — 2026-02-28  
**Status:** Reference document

---

## Governance Layer Held Under Pressure

**Stage -0.25 Canonicalization Gate worked first time.**
When IDX22 arrived as flat-text, the gate rejected it with `YAML_PARSE_ERROR` before any pipeline state was written. No partial runs, no orphaned artifacts.

**Semantic validator caught the hollow shell immediately.**
First provision created the strategy shell. Semantic validation found `check_entry` unimplemented and issued `ADMISSION_GATE / PROVISION_REQUIRED` — clean stop with a clear action.

**Signature verification is tight.**
Every indicator addition (3 rounds: `atr_percentile`, `volatility_regime`) was caught when signature and directive diverged. `Indicator Set Match: 4 modules` is a genuine integrity check, not a rubber stamp.

---

## State Machine Was Reliable

**Fail-safe cleanup fired correctly every time.**
On every Stage-1 failure, all remaining symbol states immediately transitioned to `FAILED`. Zero orphan states across 5+ failure/reset cycles.

**Reset is clean and audited.**
Every reset archived the right state files, wrote to `governance/reset_audit_log.csv`, and returned the directive to `INITIALIZED`. No state corruption across an adversarial session.

**10-symbol parallel state management held.**
Run IDs deterministic per symbol, transitions consistent, cardinality check at Stage-4 (`10 runs in Master Ledger`) passed correctly.

---

## Engine Contract Enforcement Works

**`ABORT_GOVERNANCE` error is clear and actionable.**
Error message was unambiguous — exact column name, exact location. Fixed in one edit.

**Snapshot + manifest binding is solid.**
All 10 runs show `Snapshot Verified` and `Manifest Bound` before transitioning to `COMPLETE`. Artifact integrity verification ran across all 10 runs before Stage-4 was allowed to proceed.

---

## Root-of-Trust Chain Held

**Every modified file was detected.**
Hash system caught `run_pipeline.py` after both modifications — including a one-character Unicode change. `510247D7` vs `4B80C3D2`. The guard layer is working at the level it should be.

**Root-of-trust binding verified on every preflight.**
`[PREFLIGHT] Root-of-trust binding: VERIFIED` appeared on every clean run. Never silently skipped.

---

## Operational Quality

**GENESIS_MODE correctly classified without manual input.**
No existing `strategies/IDX22/strategy.py` → auto-classified GENESIS_MODE. No agent intervention needed.

**Dry-run confirmed live signals (97 entries on 254 bars).**
Even without full engine execution, dryrun confirmed the strategy produced signals before committing to a 10-symbol run.

**Backtest and deployable artifact generation is complete and structured.**
All pipeline stages produced artifacts without manual post-processing:

- `strategies/IDX22/portfolio_evaluation/` — equity curve, drawdown, correlation matrix, metrics CSV
- `strategies/IDX22/deployable/CONSERVATIVE_V1/` and `AGGRESSIVE_V1/` — capital profiles, equity curves, trade logs
- `backtests/IDX22_*/` — per-symbol trade reports for all 10 symbols

> [!NOTE]
> ⚠️ **Workflow gap noted:** The capital wrapper (Step 8) was not run automatically by the agent
> during the initial execution session. It requires an explicit invocation after Stage-4 completes.
> This is now documented in `pipeline_robustness_improvements.md` for future runs.

---

## Summary Table

| Aspect | Verdict |
|--------|---------|
| Canonicalization gate rejection | ✅ Exact and immediate |
| Semantic validation (hollow detection) | ✅ Clean ADMISSION_GATE |
| Signature mismatch detection | ✅ Caught every indicator delta |
| Fail-safe state cleanup | ✅ Zero orphan states across 5+ failures |
| Reset + audit trail | ✅ Clean, logged, no corruption |
| Hash-based integrity (tools + engine + snapshots) | ✅ Detected one-character changes |
| Root-of-trust chain | ✅ Verified on every preflight |
| Backtest + portfolio artifact generation | ✅ Complete (deployable stage not run — separate step) |

---

## Key Takeaway

The governance scaffolding is genuinely strong. Every failure during the IDX22 run occurred at **boundary conditions** — a new directive format, an undeclared engine column contract, a provision-only/full-run workflow split — not at the core pipeline mechanics. The pipeline found the right things wrong and stopped correctly every time.
