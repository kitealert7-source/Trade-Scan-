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
  H2CompressionRecycleRule  - EUR-long + JPY-short with USD_SYNTH compression
                              gate, fixed-stake recycle on profit harvest.
"""
from tools.recycle_rules.h2_compression import H2CompressionRecycleRule

__all__ = ["H2CompressionRecycleRule"]
