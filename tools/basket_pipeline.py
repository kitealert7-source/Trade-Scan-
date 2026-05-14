"""basket_pipeline.py — Stage-3/4 adapter for basket directives.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 4 (Section 7-8).

Phase 4 contract (binding):
  * Per-symbol directives flow through stage3_compiler / portfolio_evaluator
    UNCHANGED. This module is invoked only when the directive contains a
    `basket:` block (model == RECYCLE).
  * Per-leg artifacts (each leg's trade list, equity curve, basic metrics)
    are produced in a shape stage3_compiler can later ingest if needed.
  * A single "basket result" row is produced with execution_mode=basket
    + basket_id + per-leg metadata, suitable for Master_Portfolio_Sheet
    once Phase 5 lands the first basket directive end-to-end.

This module DOES NOT modify any existing pipeline tool. The integration
point is `tools/run_pipeline.py` (Phase 4 wiring), which detects basket
directives via `tools.basket_schema.is_basket_directive` and routes to
`run_basket_pipeline()`. The per-symbol code paths are untouched.

Phase 5 will:
  - load real per-leg data via DATA_INGRESS/path_authority
  - call this module with the live directive
  - write the basket result into Master_Portfolio_Sheet.xlsx
  - run the bit-for-bit parity vs basket_sim across 10 historical windows
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from tools.basket_runner import BasketLeg, BasketRunner
from tools.basket_schema import validate_basket_block
from tools.recycle_rules import H2CompressionRecycleRule, H2RecycleRule  # noqa: F401  (kept import for adversarial/legacy tests)


# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------


@dataclass
class BasketRunResult:
    """Stage-3/4-compatible basket result. One per basket directive run."""
    basket_id:              str
    execution_mode:         str = "basket"
    legs:                   list[dict[str, Any]] = field(default_factory=list)
    per_leg_trades:         dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recycle_events:         list[dict[str, Any]] = field(default_factory=list)
    harvested_total_usd:    float = 0.0
    rule_name:              str = ""
    rule_version:           int = 0
    exit_reason:            str = ""   # TARGET | FLOOR | BLOWN | TIME | "" (still open)

    def to_mps_row(self) -> dict[str, Any]:
        """Render a single Master_Portfolio_Sheet-compatible row.

        Phase 4 sketches the shape; Phase 5 wires the actual write. Columns
        deliberately mirror the per-symbol MPS schema where applicable,
        with basket-specific extensions for legs / rule / harvest.
        """
        total_trades = sum(len(t) for t in self.per_leg_trades.values())
        return {
            "strategy_id":         self.basket_id,
            "execution_mode":      self.execution_mode,
            "basket_id":           self.basket_id,
            "basket_legs":         self.legs,
            "rule_name":           self.rule_name,
            "rule_version":        self.rule_version,
            "trades_total":        total_trades,
            "harvested_total_usd": self.harvested_total_usd,
            "recycle_event_count": len(self.recycle_events),
        }


def _instantiate_rule(rule_cfg: dict[str, Any], factor_column: str | None = None):
    """Construct a RecycleRule instance from the directive's recycle_rule block.

    Adding a new rule = adding a new branch here + entry in
    governance/recycle_rules/registry.yaml.

    Supported rules:
      H2_recycle@1            — the validated H2 strategy (Variant G +
                                $2k harvest + compression gate on adds)
      H2_v7_compression@1     — DEPRECATED misimplementation; refuses to
                                instantiate. Directives that still
                                reference this rule must migrate to
                                H2_recycle@1. Historical vaults that
                                reference it remain audit-replayable by
                                manually instantiating H2CompressionRecycleRule.
    """
    name = rule_cfg["name"]
    version = int(rule_cfg.get("version", 1))
    params = rule_cfg.get("params", {}) or {}

    if name == "H2_recycle" and version == 1:
        # Pull params with sensible defaults matching the registry entry.
        return H2RecycleRule(
            trigger_usd=float(params.get("trigger_usd", 10.0)),
            add_lot=float(params.get("add_lot", 0.01)),
            starting_equity=float(params.get("starting_equity", 1000.0)),
            harvest_target_usd=float(params.get("harvest_target_usd", 2000.0)),
            equity_floor_usd=(
                float(params["equity_floor_usd"])
                if params.get("equity_floor_usd") is not None else None
            ),
            time_stop_days=(
                int(params["time_stop_days"])
                if params.get("time_stop_days") is not None else None
            ),
            dd_freeze_frac=float(params.get("dd_freeze_frac", 0.10)),
            margin_freeze_frac=float(params.get("margin_freeze_frac", 0.15)),
            leverage=float(params.get("leverage", 1000.0)),
            factor_column=factor_column or params.get("factor_column", "compression_5d"),
            factor_min=float(params.get("factor_min", 10.0)),
        )

    if name == "H2_v7_compression" and version == 1:
        raise NotImplementedError(
            "basket_pipeline: rule H2_v7_compression@1 is DEPRECATED — it "
            "misimplemented the H2 mechanic and produced zero recycle events "
            "in our 18-month smoke test. Migrate the directive to "
            "recycle_rule.name=H2_recycle, version=1 (the validated "
            "Variant G + $2k harvest + compression gate). The deprecated "
            "rule class remains importable for replaying historical vaults."
        )

    raise NotImplementedError(
        f"basket_pipeline: rule {name!r}@v{version} is not wired yet. "
        f"Add a branch in _instantiate_rule and an entry in "
        f"governance/recycle_rules/registry.yaml."
    )


def _legs_from_directive(directive: dict[str, Any],
                         leg_data: dict[str, pd.DataFrame],
                         leg_strategies: dict[str, Any]
                         ) -> list[BasketLeg]:
    """Build BasketLeg objects from directive config + caller-supplied data.

    `leg_data` and `leg_strategies` are dicts keyed by symbol. The caller
    is responsible for loading the OHLC and constructing each leg's
    strategy. In Phase 5 this happens inside the pipeline orchestrator
    using DATA_INGRESS via config.path_authority.
    """
    block = directive["basket"]
    legs_cfg = block["legs"]
    legs: list[BasketLeg] = []
    for leg_cfg in legs_cfg:
        sym = leg_cfg["symbol"]
        if sym not in leg_data:
            raise KeyError(f"basket_pipeline: missing OHLC data for leg symbol {sym!r}")
        if sym not in leg_strategies:
            raise KeyError(f"basket_pipeline: missing strategy for leg symbol {sym!r}")
        direction = +1 if leg_cfg["direction"] == "long" else -1
        legs.append(BasketLeg(
            symbol=sym,
            lot=float(leg_cfg["lot"]),
            direction=direction,
            df=leg_data[sym],
            strategy=leg_strategies[sym],
        ))
    return legs


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_basket_pipeline(directive: dict[str, Any],
                        leg_data: dict[str, pd.DataFrame],
                        leg_strategies: dict[str, Any],
                        *,
                        recycle_registry_path: Path | None = None,
                        ) -> BasketRunResult:
    """Run a basket directive end-to-end through BasketRunner + rules.

    Args:
      directive:              parsed directive dict (must contain `basket:` block)
      leg_data:               {symbol: OHLC DataFrame} for each leg
      leg_strategies:         {symbol: StrategyProtocol instance} for each leg
      recycle_registry_path:  governance/recycle_rules/registry.yaml; defaults
                              to the canonical location under REAL_REPO_ROOT.

    Returns:
      BasketRunResult — call .to_mps_row() for the MPS-compatible payload.
    """
    # Schema sanity (Phase 1 schema check) — defensive; pipeline already runs it.
    schema_errors = validate_basket_block(
        directive,
        recycle_registry_path=recycle_registry_path,
    )
    if schema_errors:
        raise ValueError("basket_pipeline: directive failed schema check:\n  - " + "\n  - ".join(schema_errors))

    block = directive["basket"]
    rule = _instantiate_rule(block["recycle_rule"])

    legs = _legs_from_directive(directive, leg_data, leg_strategies)
    runner = BasketRunner(legs=legs, rules=[rule])
    per_leg_trades = runner.run()

    return BasketRunResult(
        basket_id=block["basket_id"],
        legs=block["legs"],
        per_leg_trades=per_leg_trades,
        recycle_events=list(rule.recycle_events),
        harvested_total_usd=rule.harvested_total_usd,
        rule_name=rule.name,
        rule_version=rule.version,
        exit_reason=str(getattr(rule, "exit_reason", "") or ""),
    )


__all__ = ["BasketRunResult", "run_basket_pipeline"]
