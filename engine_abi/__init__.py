"""engine_abi — versioned re-export packages for the universal research engine.

Sub-packages:
  engine_abi.v1_5_9   Active ABI (consumers: TS_Execution, basket_runner,
                      TS_SignalValidator)

History: a parallel `engine_abi.v1_5_3` package existed during the Phase 0a
recon. TS_Execution was intentionally migrated to v1_5_9 in 2026-05-13, so
the dual-ABI rationale collapsed to a single ABI. v1_5_3 was retired with
plan v11. Recon record archived to `archive/2026-05-13_phase0a_v1_5_3_retirement/`.

Each sub-package is governed by a manifest in `governance/engine_abi_<ver>_manifest.yaml`
and a triple-gate CI enforcement layer (`tools/abi_audit.py`). Re-exports only;
no new logic.

Plan: outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md
      Section 1l (single ABI on v1_5_9) and Phase 0a.
"""
