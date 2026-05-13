"""recycle_rules — pluggable basket-level rules for tools/basket_runner.py.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 3 (Section 7-8).

A RecycleRule is a basket-level state mutator. It runs after every per-bar
leg evaluation inside BasketRunner.run() and may close + re-open legs to
implement basket-strategy mechanics (recycle, harvest, regime-gate).

Each rule MUST:
  - declare `name` matching its registry entry in
    `governance/recycle_rules/registry.yaml`.
  - declare `version: int` matching the registry version.
  - mutate ONLY through leg.state / leg.trades (no global state).
  - be deterministic: same inputs at bar i -> same mutations.

Available rules:
  H2RecycleRule              - The validated H2 strategy: Variant G (winner-
                               add-to-loser at $10 trigger) + $2k harvest exit
                               + USD_SYNTH compression>=10 gate on adds.
                               Registered as H2_recycle@1.
  H2CompressionRecycleRule   - DEPRECATED. Misimplemented H2 mechanic
                               (close+reopen-all on $2k floating threshold).
                               Preserved for audit-replay of any vault that
                               referenced H2_v7_compression@1. Do not use
                               for new vaults.
"""
from tools.recycle_rules.h2_compression import H2CompressionRecycleRule
from tools.recycle_rules.h2_recycle import H2RecycleRule

__all__ = ["H2RecycleRule", "H2CompressionRecycleRule"]
