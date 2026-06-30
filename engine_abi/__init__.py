"""engine_abi — versioned re-export package for the universal research engine.

Sub-packages:
  engine_abi.v1_5_11  CANONICAL ABI — the single engine_abi surface. Consumers:
                      basket_runner (Trade_Scan basket compute), the TS_Execution
                      live bridge (main / execution_adapter / pipeline /
                      strategy_loader / replay), and TS_SignalValidator.

History: parallel ABIs engine_abi.v1_5_3 (Phase 0a recon), engine_abi.v1_5_9
(TS_Execution's binding 2026-05-13 .. 2026-06-30) and engine_abi.v1_5_10 (the inert
direction-aware successor) were retired. The ABI consolidation (2026-06-30)
collapsed every consumer onto v1_5_11 — full API parity (identical 16-symbol
surface); v1_5_9/v1_5_10 retirement records live in git history. v1_5_3 recon:
`archive/2026-05-13_phase0a_v1_5_3_retirement/`.

The sub-package is governed by `governance/engine_abi_v1_5_11_manifest.yaml` and a
triple-gate CI enforcement layer (`tools/abi_audit.py`). Re-exports only; no new logic.

Plan: outputs/system_reports/01_system_architecture/H2_ENGINE_PROMOTION_PLAN.md
      Section 1l (single ABI on v1_5_11) and Phase 0a.
"""
