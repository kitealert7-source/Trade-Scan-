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
  H2RecycleRuleV2            - @1 + loser-leg lot cap. Registered as
                               H2_recycle@2. Rejected by S04 research
                               (disables compounding); kept for replay.
  H2RecycleRuleV3            - @2 + generalized cross-pair PnL via USD-anchored
                               reference rates. Registered as H2_recycle@3.
                               Supports non-USD-anchored basket legs.
  H2RecycleRuleV4            - @1 + bump-and-liquidate mechanic. Registered
                               as H2_recycle@4. After N=5 consecutive same-
                               loser adds, fires a one-time (N+1)*0.01 bump
                               to the winner and enters HOLD mode. Liquidates
                               on 30% retrace from winner peak via the
                               BasketRunner.soft_reset_basket primitive, then
                               restarts a fresh sub-basket. 10-window matrix:
                               10/10 survival, max DD halved 120%->60%, B2
                               COVID blow-up prevented. See research/
                               FX_BASKET_RECYCLE_RESEARCH.md §5.4b.
  H2CompressionRecycleRule   - DEPRECATED. Misimplemented H2 mechanic
                               (close+reopen-all on $2k floating threshold).
                               Preserved for audit-replay of any vault that
                               referenced H2_v7_compression@1. Do not use
                               for new vaults.
"""
from tools.recycle_rules.h2_compression import H2CompressionRecycleRule
from tools.recycle_rules.h2_recycle import H2RecycleRule
from tools.recycle_rules.h2_recycle_v2 import H2RecycleRuleV2
from tools.recycle_rules.h2_recycle_v3 import H2RecycleRuleV3
from tools.recycle_rules.h2_recycle_v4 import H2RecycleRuleV4

__all__ = [
    "H2RecycleRule",
    "H2RecycleRuleV2",
    "H2RecycleRuleV3",
    "H2RecycleRuleV4",
    "H2CompressionRecycleRule",
]
