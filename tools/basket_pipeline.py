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
from tools.recycle_rules import CointegrationMeanRevV1_2Rule, H2CompressionRecycleRule, H2RecycleRule, H2RecycleRuleV2, H2RecycleRuleV3, H2RecycleRuleV4, H2RecycleRuleV5, H3SpreadV1Rule, H3SpreadV2Rule, H3SpreadV3Rule, PineRatioZRevRule, PineRatioZRevRuleZBand, PineRatioZRevRuleZCross  # noqa: F401  (kept imports for adversarial/legacy tests + v2/v3/v4/v5/H3_spread @1/@2/@3 + cointegration_meanrev_v1_2 + pine_ratio_zrev_v1 + pine_ratio_zrev_v1_zcross + pine_ratio_zrev_v1_zband dispatch)


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

    # 1.3.0-basket schema additions (plan §3 / §4 / §6). Empty defaults so
    # rules that don't emit ledger telemetry (V2, V3 today) flow through
    # unchanged — downstream consumers treat empty as "no ledger this run".
    per_bar_records:        list[dict[str, Any]] = field(default_factory=list)
    summary_stats:          dict[str, Any] = field(default_factory=dict)

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


# ---------------------------------------------------------------------------
# Strict param validation
# ---------------------------------------------------------------------------
#
# `basket.recycle_rule.params` in a directive YAML is consumed by THREE
# surfaces: the rule constructor here (_instantiate_rule), the leg-strategy
# construction in run_pipeline.py, and the data loader in basket_data_loader.py.
# Each consumer reads only the params it knows about; unknown params are
# silently dropped.
#
# This caused a real silent-no-op on 2026-05-24: `vol_neutral_sizing: true` was
# added to a directive, the dispatcher didn't forward it to the rule, and the
# experiment APPEARED to run with the new param but actually used the equal-lot
# default. We only caught it because the per-leg lots in the output parquet
# were still 0.10/0.10.
#
# Strict validation here catches:
#   1. Typos in directive YAML (e.g., `vol_neutral_seizing`)
#   2. Params that exist on the rule dataclass but aren't wired through this
#      dispatcher (same class as the bug above)
#   3. Stale params left in directives after a rule schema change
#
# Update protocol:
#   - Add a new param on a rule dataclass -> add it to _instantiate_rule's
#     constructor call AND it will auto-be-accepted by the validator.
#   - Add a new param read by run_pipeline.py / basket_data_loader.py (e.g.,
#     a new macro filter knob) -> add the param name to _EXTERNAL_CONSUMER_PARAMS
#     under the affected (rule_name, version) entries.
#   - Add a backward-compat alias for a renamed param -> add to _RULE_PARAM_ALIASES.

# Runtime-only fields on rule dataclasses (NOT settable from directive YAML).
_RUNTIME_ONLY_FIELDS = frozenset({"run_id", "directive_id", "basket_id"})

# Documented backward-compat aliases for renamed params, per (rule_name, version).
# Each alias is silently accepted by the validator (the dispatcher itself
# handles the alias-to-canonical mapping in its kwargs construction).
_RULE_PARAM_ALIASES: dict[tuple[str, int], frozenset[str]] = {
    ("H3_spread", 2): frozenset({"harvest_delay_levels"}),
    ("H3_spread", 3): frozenset({"harvest_delay_levels"}),
}

# Params read by external consumers (run_pipeline.py / basket_data_loader.py)
# that don't appear on the rule's own dataclass. These get forwarded to the
# leg strategy or data loader, not to the rule constructor. Per (rule_name,
# version) since not all rules use all external consumers.
_EXTERNAL_CONSUMER_PARAMS: dict[tuple[str, int], frozenset[str]] = {
    # H3_spread family: leg strategy reads entry_delay_bars; data loader reads
    # all macro_* params (macro_direction_timeframe is the gate, the rest are
    # window overrides for the cross-signal computation).
    ("H3_spread", 1): frozenset({
        "entry_delay_bars",
        "macro_direction_timeframe", "macro_warmup_days",
        "macro_z_window", "macro_sma_window",
        "macro_correlation_window", "macro_correlation_threshold",
    }),
    ("H3_spread", 2): frozenset({
        "entry_delay_bars",
        "macro_direction_timeframe", "macro_warmup_days",
        "macro_z_window", "macro_sma_window",
        "macro_correlation_window", "macro_correlation_threshold",
    }),
    ("H3_spread", 3): frozenset({
        "entry_delay_bars",
        "macro_direction_timeframe", "macro_warmup_days",
        "macro_z_window", "macro_sma_window",
        "macro_correlation_window", "macro_correlation_threshold",
    }),
}


def _validate_recycle_rule_params(
    rule_class: type, params: dict, rule_name: str, version: int,
) -> None:
    """Fail-loud on any key in `params` not recognized by SOME consumer.

    Accepted = (public, non-runtime fields on the rule dataclass) UNION
               (documented aliases for (rule_name, version)) UNION
               (external-consumer params for (rule_name, version)).

    Raises ValueError with a diagnostic listing of valid params if anything
    unknown appears. Catches the silent-no-op bug class — see module
    docstring above.
    """
    import dataclasses
    rule_fields = {
        f.name for f in dataclasses.fields(rule_class)
        if not f.name.startswith("_") and f.name not in _RUNTIME_ONLY_FIELDS
    }
    aliases = _RULE_PARAM_ALIASES.get((rule_name, version), frozenset())
    external = _EXTERNAL_CONSUMER_PARAMS.get((rule_name, version), frozenset())
    accepted = rule_fields | aliases | external
    unknown = set(params.keys()) - accepted
    if unknown:
        raise ValueError(
            f"recycle_rule.params validation failed for {rule_name}@{version} "
            f"({rule_class.__name__}):\n"
            f"  Unknown params in directive YAML: {sorted(unknown)}\n"
            f"  Rule dataclass fields (user-settable):\n"
            f"    {sorted(rule_fields)}\n"
            f"  External-consumer params (leg strategy / data loader):\n"
            f"    {sorted(external) if external else '(none)'}\n"
            f"  Documented aliases: "
            f"{sorted(aliases) if aliases else '(none)'}\n"
            f"  If this is a NEW param: add it to the rule's dataclass + the "
            f"dispatcher branch below, OR add it to _EXTERNAL_CONSUMER_PARAMS "
            f"if it's read by run_pipeline.py / basket_data_loader.py.\n"
            f"  If this is a TYPO: fix the directive YAML.\n"
            f"  (Strict validation added 2026-05-24 after a silent-no-op "
            f"experiment confused the vol_neutral_sizing test.)"
        )


def _validate_basket_id_convention(
    basket_id: str, params: dict, rule_name: str, version: int,
) -> None:
    """Enforce H3_spread basket_id direction-suffix convention.

    For H3_spread (any version):
      - If params.bidirectional is True  -> basket_id MUST end with 'BIDIR'.
      - Otherwise (False/absent)         -> basket_id MUST end with 'BEAR' or 'BULL'.

    Formalizes the convention observed in the 2026-05-25 H3 rehabilitation
    batch where basket_id suffix served as in-band evidence of direction
    mode but was not actually enforced — leaving the door open to silent
    BIDIR/BEAR/BULL mislabeling. Other rule families (H2_recycle, cointegration_*,
    pine_ratio_zrev_v1) do not use this convention and are skipped.

    Skipped entirely when basket_id is empty (test-mode invocation of
    _instantiate_rule that doesn't supply basket_id).
    """
    if rule_name != "H3_spread":
        return
    if not basket_id:
        # Test-mode invocation. Real pipeline calls always supply basket_id.
        return
    is_bidir = bool(params.get("bidirectional", False))
    bid = str(basket_id)
    if is_bidir:
        if not bid.endswith("BIDIR"):
            raise ValueError(
                f"basket_id convention violation: {rule_name}@{version} directive "
                f"declares bidirectional=true but basket_id={bid!r} does not end "
                f"with 'BIDIR'. Required for in-band direction-mode identification "
                f"(formalized 2026-05-25 from H3 rehabilitation batch). "
                f"Fix: rename basket_id to end with 'BIDIR' (e.g., '{bid}BIDIR'), "
                f"or set bidirectional=false."
            )
    else:
        if not (bid.endswith("BEAR") or bid.endswith("BULL")):
            present = "false" if "bidirectional" in params else "absent (default false)"
            raise ValueError(
                f"basket_id convention violation: {rule_name}@{version} directive "
                f"has bidirectional={present} (unidirectional) but basket_id={bid!r} "
                f"does not end with 'BEAR' or 'BULL'. Required for in-band "
                f"direction-mode identification (formalized 2026-05-25 from H3 "
                f"rehabilitation batch). Fix: rename basket_id to end with 'BEAR' "
                f"(USD-bear spread) or 'BULL' (USD-bull spread), or set "
                f"bidirectional=true and use 'BIDIR' suffix."
            )


def _instantiate_rule(
    rule_cfg: dict[str, Any],
    factor_column: str | None = None,
    *,
    run_id: str = "",
    directive_id: str = "",
    basket_id: str = "",
):
    """Construct a RecycleRule instance from the directive's recycle_rule block.

    Adding a new rule = adding a new branch here + entry in
    governance/recycle_rules/registry.yaml.

    Identity kwargs (`run_id`, `directive_id`, `basket_id`) are threaded into
    H2_recycle@1 AND H2_recycle@3 — both opt into the 1.3.0-basket per-bar
    ledger telemetry contract. H2_recycle@2 still ignores them (no schema
    field today; would be added if @2 ever needs ledger emission).

    Supported rules:
      H2_recycle@1            — the validated H2 strategy (Variant G +
                                $2k harvest + compression gate on adds)
                                + 1.3.0-basket per-bar telemetry emitter
      H2_recycle@2            — @1 + loser-leg lot cap (rejected by S04
                                research as it disables compounding;
                                directives may still reference it)
      H2_recycle@3            — @2 + generalized cross-pair PnL via
                                USD-anchored reference rates (Phase B
                                non-USD universe support); 1.3.0-basket
                                emitter wired 2026-05-16
      H2_recycle@4            — @1 + bump-and-liquidate mechanic
                                (multi-window champion, 2026-05-16).
                                After N=switch_n consecutive same-loser
                                adds, fires a one-time (N+1)*add_lot bump
                                to the winner, enters HOLD mode, and
                                liquidates on retrace_pct retrace from
                                winner peak via the soft_reset_basket
                                primitive. Restarts a fresh sub-basket
                                in the same window. 10-window matrix:
                                10/10 survival, max DD halved 120%→60%.
                                See research §5.4b.
      H2_recycle@5            — Trend-follow pyramid (inverse-H2; H3
                                hypothesis 2026-05-17). Pyramids WINNER
                                each $10 of new loss on LOSER (loser
                                held at 0.01 as tripwire). Exits on
                                loser recovery from trough via
                                soft_reset_basket. Per-cycle loss
                                bounded at ~$10 by design.
                                Hypothesis: H3_TREND_FOLLOW_V1.
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
        _validate_recycle_rule_params(H2RecycleRule, params, name, version)
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
            factor_operator=str(params.get("factor_operator", ">=")),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H2_recycle" and version == 5:
        _validate_recycle_rule_params(H2RecycleRuleV5, params, name, version)
        # v5 = trend-follow pyramid (inverse-H2; H3 design). Pyramids
        # WINNER each $10 of new loss on LOSER; loser held at 0.01 as
        # tripwire. Exits on loser recovery from trough via
        # BasketRunner.soft_reset_basket. New params: pyramid_increment_usd,
        # exit_recovery_usd, hard_floor_loss_usd. Inverted regime gate
        # by default (factor_operator='<=' blocks pyramid in chop). The
        # basket_runner attribute is populated by BasketRunner.__init__'s
        # back-ref injection at attach time.
        return H2RecycleRuleV5(
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
            factor_min=float(params.get("factor_min", 5.0)),
            factor_operator=str(params.get("factor_operator", "<=")),
            pyramid_increment_usd=float(params.get("pyramid_increment_usd", 10.0)),
            exit_recovery_usd=float(params.get("exit_recovery_usd", 10.0)),
            hard_floor_loss_usd=float(params.get("hard_floor_loss_usd", -10.0)),
            # Correlation gate (2026-05-17): OFF by default to preserve
            # parity with all existing V5 directives. Enable per-directive
            # by setting correlation_enabled: true in the recycle_rule.params.
            correlation_enabled=bool(params.get("correlation_enabled", False)),
            correlation_entry_low=float(params.get("correlation_entry_low", -0.70)),
            correlation_entry_high=float(params.get("correlation_entry_high", -0.20)),
            correlation_exit_low=float(params.get("correlation_exit_low", -0.85)),
            correlation_exit_high=float(params.get("correlation_exit_high", -0.05)),
            correlation_use_1h=bool(params.get("correlation_use_1h", True)),
            correlation_use_4h=bool(params.get("correlation_use_4h", True)),
            correlation_persistence_4h_bars=int(params.get("correlation_persistence_4h_bars", 0)),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H2_recycle" and version == 4:
        _validate_recycle_rule_params(H2RecycleRuleV4, params, name, version)
        # v4 = v1 + bump-and-liquidate mechanic. New params: switch_n,
        # retrace_pct. Consumes BasketRunner.soft_reset_basket (Phase B
        # primitive). The rule's `basket_runner` attribute is populated
        # by BasketRunner.__init__'s back-ref injection — we leave it
        # unset here; basket_pipeline._dispatch wires the rule onto the
        # runner before the run loop, and the injection fires at that
        # point.
        return H2RecycleRuleV4(
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
            factor_min=float(params.get("factor_min", 5.0)),
            factor_operator=str(params.get("factor_operator", ">=")),
            switch_n=int(params.get("switch_n", 5)),
            retrace_pct=float(params.get("retrace_pct", 0.30)),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H2_recycle" and version == 3:
        _validate_recycle_rule_params(H2RecycleRuleV3, params, name, version)
        # v3 = v2 + generalized cross-pair PnL math. Supports any FX pair
        # whose currencies are in {USD, EUR, GBP, AUD, NZD, JPY, CHF, CAD}.
        # Requires basket_data_loader to populate usd_ref_<PAIR>_close columns.
        # Phase B (2026-05-16): opted into 1.3.0-basket per_bar_records
        # contract — identity kwargs threaded so the parquet ledger emit at
        # basket close labels rows correctly.
        return H2RecycleRuleV3(
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
            factor_operator=str(params.get("factor_operator", ">=")),
            max_leg_lot=(
                float(params["max_leg_lot"])
                if params.get("max_leg_lot") is not None else None
            ),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H2_recycle" and version == 2:
        _validate_recycle_rule_params(H2RecycleRuleV2, params, name, version)
        # v2 = v1 + loser-leg lot cap. New param: max_leg_lot (None = disabled).
        return H2RecycleRuleV2(
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
            factor_operator=str(params.get("factor_operator", ">=")),
            max_leg_lot=(
                float(params["max_leg_lot"])
                if params.get("max_leg_lot") is not None else None
            ),
        )

    if name == "H3_spread" and version == 1:
        _validate_recycle_rule_params(H3SpreadV1Rule, params, name, version)
        _validate_basket_id_convention(basket_id, params, name, version)
        # H3_spread@1 (2026-05-18): LONG-SHORT pair-spread basket rule.
        # Manages a USD-directional spread (one leg long, other short) with
        # signal-triggered entry (via SpreadCrossLegStrategy), basket-level
        # pyramid + adverse stop + reverse-cross / time-stop exits. Distinct
        # from H2_recycle@1-5 (long-long baskets). Inherits H2RecycleRule
        # for parquet+events machinery but overrides apply() entirely.
        return H3SpreadV1Rule(
            pyramid_level_pcts=tuple(params.get("pyramid_level_pcts", (0.15, 0.30))),
            pyramid_add_lot=float(params.get("pyramid_add_lot", 0.05)),
            adverse_stop_pct=float(params.get("adverse_stop_pct", 0.0020)),
            time_stop_bars=int(params.get("time_stop_bars", 288)),
            reverse_cross_column=str(params.get("reverse_cross_column", "cross_side")),
            entry_direction=int(params.get("entry_direction", +1)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            trail_arm_floating_usd=float(params.get("trail_arm_floating_usd", 0.0)),
            trail_retrace_pct=float(params.get("trail_retrace_pct", 0.0)),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H3_spread" and version == 2:
        _validate_recycle_rule_params(H3SpreadV2Rule, params, name, version)
        _validate_basket_id_convention(basket_id, params, name, version)
        # H3_spread@2 (2026-05-19): bounded-exposure + harvest scale-out
        # with optional delayed-harvest window. @1 with three-phase pyramid
        # lifecycle: ACCUMULATE up to max_exposure_multiple * initial_lot,
        # optionally HOLD at cap for `harvest_delay_levels` additional
        # threshold crossings, then HARVEST scale-out on subsequent
        # crossings until LIQUIDATE_HARVEST_COMPLETE or another exit
        # (adverse / reverse-cross / time) fires. Threshold spacing
        # generalized to a single step (pyramid_threshold_step_pct) so the
        # harvest phase can fire indefinitely above the cap.
        # `harvest_start_after_extra_pyramids=0` (default) preserves the
        # original @2 immediate-harvest behavior byte-equivalently.
        # Backward-compat: the param was originally named
        # `harvest_delay_levels` (S02/S03 directives in completed/). The
        # new name takes precedence; old name is the replay-safe fallback.
        delay_param = params.get(
            "harvest_start_after_extra_pyramids",
            params.get("harvest_delay_levels", 0),
        )
        return H3SpreadV2Rule(
            max_exposure_multiple=float(params.get("max_exposure_multiple", 3.0)),
            pyramid_threshold_step_pct=float(params.get("pyramid_threshold_step_pct", 0.15)),
            harvest_start_after_extra_pyramids=int(delay_param),
            harvest_keeps_core=bool(params.get("harvest_keeps_core", False)),
            bidirectional=bool(params.get("bidirectional", False)),
            vol_neutral_sizing=bool(params.get("vol_neutral_sizing", False)),
            vol_neutral_window=int(params.get("vol_neutral_window", 200)),
            pyramid_add_lot=float(params.get("pyramid_add_lot", 0.05)),
            adverse_stop_pct=float(params.get("adverse_stop_pct", 0.0020)),
            time_stop_bars=int(params.get("time_stop_bars", 288)),
            reverse_cross_column=str(params.get("reverse_cross_column", "cross_side")),
            entry_direction=int(params.get("entry_direction", +1)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            trail_arm_floating_usd=float(params.get("trail_arm_floating_usd", 0.0)),
            trail_retrace_pct=float(params.get("trail_retrace_pct", 0.0)),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H3_spread" and version == 3:
        _validate_recycle_rule_params(H3SpreadV3Rule, params, name, version)
        _validate_basket_id_convention(basket_id, params, name, version)
        # H3_spread@3 (2026-05-22): @2 + extreme-z take-profit exit +
        # ARMED-for-reentry phase for multi-leg trend capture within a
        # single macro regime. Inherits ALL @2 mechanics (harvest,
        # keep_core, bidirectional, macro filter wiring) and adds:
        #   - extreme_z_threshold (mechanic A): cycle liquidates when
        #     cycle_dir * diff > threshold (LIQUIDATE_EXTREME_Z, priority
        #     between ADVERSE and TRAIL).
        #   - reentry_z_threshold (mechanic B): after EXTREME_Z, transitions
        #     to ARMED_FOR_REENTRY; re-enters when 0 < cycle_dir * diff <
        #     threshold AND cross_side/htf_direction still aligned;
        #     aborts on cross/macro flip or per-regime cap.
        # All @3 params default off -> byte-equivalent to @2 (regression-
        # tested in tests/test_h3_spread_v3.py).
        # Same delay_param backward-compat as @2.
        delay_param = params.get(
            "harvest_start_after_extra_pyramids",
            params.get("harvest_delay_levels", 0),
        )
        # Optional @3 params: None when not set (preserves byte-equivalence)
        extreme_z_param = params.get("extreme_z_threshold")
        reentry_z_param = params.get("reentry_z_threshold")
        # Regime-gate params (2026-05-23 charter): both must be either
        # None or set. v3's __post_init__ raises if partial.
        regime_gate_lookback_param = params.get("regime_gate_lookback_bars")
        regime_gate_threshold_param = params.get("regime_gate_flip_threshold")
        return H3SpreadV3Rule(
            # @3 additions
            extreme_z_threshold=(
                float(extreme_z_param) if extreme_z_param is not None else None
            ),
            reentry_z_threshold=(
                float(reentry_z_param) if reentry_z_param is not None else None
            ),
            reentry_macro_check=bool(params.get("reentry_macro_check", True)),
            reentry_cross_check=bool(params.get("reentry_cross_check", True)),
            reentry_max_per_regime=int(params.get("reentry_max_per_regime", 3)),
            regime_gate_lookback_bars=(
                int(regime_gate_lookback_param)
                if regime_gate_lookback_param is not None else None
            ),
            regime_gate_flip_threshold=(
                float(regime_gate_threshold_param)
                if regime_gate_threshold_param is not None else None
            ),
            # @2 inheritance
            max_exposure_multiple=float(params.get("max_exposure_multiple", 3.0)),
            pyramid_threshold_step_pct=float(params.get("pyramid_threshold_step_pct", 0.15)),
            harvest_start_after_extra_pyramids=int(delay_param),
            harvest_keeps_core=bool(params.get("harvest_keeps_core", False)),
            bidirectional=bool(params.get("bidirectional", False)),
            vol_neutral_sizing=bool(params.get("vol_neutral_sizing", False)),
            vol_neutral_window=int(params.get("vol_neutral_window", 200)),
            # @1 inheritance
            pyramid_add_lot=float(params.get("pyramid_add_lot", 0.05)),
            adverse_stop_pct=float(params.get("adverse_stop_pct", 0.0020)),
            time_stop_bars=int(params.get("time_stop_bars", 288)),
            reverse_cross_column=str(params.get("reverse_cross_column", "cross_side")),
            entry_direction=int(params.get("entry_direction", +1)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            trail_arm_floating_usd=float(params.get("trail_arm_floating_usd", 0.0)),
            trail_retrace_pct=float(params.get("trail_retrace_pct", 0.0)),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "cointegration_meanrev_v1_2" and version == 1:
        _validate_recycle_rule_params(CointegrationMeanRevV1_2Rule, params, name, version)
        # COINTREV v1.2 (2026-05-24): trigger-driven β-weighted spread.
        # Reads cointegration_triggers (auto-joined onto leg.df by
        # basket_data_loader when basket.cointegration_join.lookback_days
        # is set on the directive). Two-bar leg ↔ rule protocol approves
        # each proposal, β-sizes lots via _compute_neutral_basket, and
        # exits on mean-reversion / regime-degradation / time-stop.
        # The rule discovers its shared CointTriggerArmedState from the
        # leg strategies at first apply() — basket_pipeline doesn't
        # construct the state itself (run_pipeline owns leg construction).
        return CointegrationMeanRevV1_2Rule(
            min_gap_days_between_triggers=int(params.get("min_gap_days_between_triggers", 5)),
            exit_z=float(params.get("exit_z", 1.0)),
            time_stop_bars=int(params.get("time_stop_bars", 60)),
            regime_exit_states=tuple(params.get("regime_exit_states", ("breaking", "broken"))),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            default_initial_lot=float(params.get("default_initial_lot", 0.01)),
            trigger_column=str(params.get("trigger_column", "coint_trigger")),
            regime_column=str(params.get("regime_column", "coint_regime")),
            zscore_column=str(params.get("zscore_column", "coint_current_zscore")),
            beta_column=str(params.get("beta_column", "coint_beta_at_trigger")),
            direction_column=str(params.get("direction_column", "coint_direction")),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "pine_ratio_zrev_v1" and version == 1:
        _validate_recycle_rule_params(PineRatioZRevRule, params, name, version)
        # Pine port (2026-05-24): ratio-hedged z_r reversal, always-in-market.
        # Preserved follow-on arc #2 from cointegration_meanrev_v1_2 retirement.
        # Computes z_r per-bar from both legs' close prices via
        # indicators.stats.ratio_hedged_spread_zscore (does NOT read the
        # cointegration_triggers ledger). The rule attaches signal columns
        # to both legs' DataFrames on first apply(). Same shared-state
        # auto-discovery pattern as cointegration_meanrev_v1_2.
        return PineRatioZRevRule(
            n_window=int(params.get("n_window", 100)),
            n_meta=int(params.get("n_meta", 100)),
            z_entry=float(params.get("z_entry", 2.0)),
            entry_mode=str(params.get("entry_mode", "centered")),
            hedge_lock_at_entry=bool(params.get("hedge_lock_at_entry", True)),
            always_in_market=bool(params.get("always_in_market", True)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            default_initial_lot=float(params.get("default_initial_lot", 0.01)),
            target_notional_per_leg_usd=float(params.get("target_notional_per_leg_usd", 10000.0)),
            sizing_mode=str(params.get("sizing_mode", "notional")),
            beta_cap_lo=float(params.get("beta_cap_lo", 0.25)),
            beta_cap_hi=float(params.get("beta_cap_hi", 4.0)),
            target_risk_usd=float(params.get("target_risk_usd", 1000.0)),
            atr_window=int(params.get("atr_window", 14)),
            coint_beta_column=str(params.get("coint_beta_column", "coint_hedge_ratio")),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "pine_ratio_zrev_v1_zcross" and version == 1:
        _validate_recycle_rule_params(PineRatioZRevRuleZCross, params, name, version)
        # Zero-crossing exit variant of pine_ratio_zrev_v1 (2026-05-31).
        # Same entries / hedge lock / sizing / warmup. ONLY exit differs:
        # liquidate on first zero-cross of z_active (sign change between
        # consecutive bars). Strategy goes FLAT after exit; next +/-z_entry
        # cross opens a fresh cycle. Recycle event tag: LIQUIDATE_EQUILIBRIUM.
        # always_in_market inherited but functionally ignored.
        return PineRatioZRevRuleZCross(
            n_window=int(params.get("n_window", 100)),
            n_meta=int(params.get("n_meta", 100)),
            z_entry=float(params.get("z_entry", 2.0)),
            entry_mode=str(params.get("entry_mode", "centered")),
            hedge_lock_at_entry=bool(params.get("hedge_lock_at_entry", True)),
            always_in_market=bool(params.get("always_in_market", True)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            default_initial_lot=float(params.get("default_initial_lot", 0.01)),
            target_notional_per_leg_usd=float(params.get("target_notional_per_leg_usd", 10000.0)),
            sizing_mode=str(params.get("sizing_mode", "notional")),
            beta_cap_lo=float(params.get("beta_cap_lo", 0.25)),
            beta_cap_hi=float(params.get("beta_cap_hi", 4.0)),
            target_risk_usd=float(params.get("target_risk_usd", 1000.0)),
            atr_window=int(params.get("atr_window", 14)),
            coint_beta_column=str(params.get("coint_beta_column", "coint_hedge_ratio")),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "pine_ratio_zrev_v1_zband" and version == 1:
        _validate_recycle_rule_params(PineRatioZRevRuleZBand, params, name, version)
        # Equilibrium-band exit variant of pine_ratio_zrev_v1 (2026-06-01).
        # Same entries / hedge lock / sizing / warmup. ONLY exit differs:
        # liquidate on first bar where |z_active| <= z_exit (default 1.0).
        # Strategy goes FLAT after exit; next +/-z_entry cross opens a fresh
        # cycle. Recycle event tag: LIQUIDATE_BAND_REVERT.
        # always_in_market inherited but functionally ignored.
        return PineRatioZRevRuleZBand(
            n_window=int(params.get("n_window", 100)),
            n_meta=int(params.get("n_meta", 100)),
            z_entry=float(params.get("z_entry", 2.0)),
            z_exit=float(params.get("z_exit", 1.0)),
            entry_mode=str(params.get("entry_mode", "centered")),
            hedge_lock_at_entry=bool(params.get("hedge_lock_at_entry", True)),
            always_in_market=bool(params.get("always_in_market", True)),
            initial_notional_usd=float(params.get("initial_notional_usd", 1000.0)),
            default_initial_lot=float(params.get("default_initial_lot", 0.01)),
            target_notional_per_leg_usd=float(params.get("target_notional_per_leg_usd", 10000.0)),
            sizing_mode=str(params.get("sizing_mode", "notional")),
            beta_cap_lo=float(params.get("beta_cap_lo", 0.25)),
            beta_cap_hi=float(params.get("beta_cap_hi", 4.0)),
            target_risk_usd=float(params.get("target_risk_usd", 1000.0)),
            atr_window=int(params.get("atr_window", 14)),
            coint_beta_column=str(params.get("coint_beta_column", "coint_hedge_ratio")),
            run_id=run_id,
            directive_id=directive_id,
            basket_id=basket_id,
        )

    if name == "H2_v7_compression" and version == 1:
        _validate_recycle_rule_params(H2CompressionRecycleRule, params, name, version)
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
                        run_id: str = "",
                        directive_id: str = "",
                        ) -> BasketRunResult:
    """Run a basket directive end-to-end through BasketRunner + rules.

    Args:
      directive:              parsed directive dict (must contain `basket:` block)
      leg_data:               {symbol: OHLC DataFrame} for each leg
      leg_strategies:         {symbol: StrategyProtocol instance} for each leg
      recycle_registry_path:  governance/recycle_rules/registry.yaml; defaults
                              to the canonical location under REAL_REPO_ROOT.
      run_id:                 12-char hex run identifier (from generate_run_id).
                              Threaded into the rule for per-bar ledger rows.
      directive_id:           directive name (e.g., "90_PORT_H2_5M_RECYCLE_S03_V1_P00").
                              Threaded into the rule for per-bar ledger rows.

    Returns:
      BasketRunResult — call .to_mps_row() for the MPS-compatible payload.
      For H2_recycle@1, also carries `per_bar_records` + `summary_stats`
      (1.3.0-basket schema). For other rules, those fields are empty.
    """
    # Schema sanity (Phase 1 schema check) — defensive; pipeline already runs it.
    schema_errors = validate_basket_block(
        directive,
        recycle_registry_path=recycle_registry_path,
    )
    if schema_errors:
        raise ValueError("basket_pipeline: directive failed schema check:\n  - " + "\n  - ".join(schema_errors))

    block = directive["basket"]
    rule = _instantiate_rule(
        block["recycle_rule"],
        run_id=run_id,
        directive_id=directive_id,
        basket_id=block["basket_id"],
    )

    legs = _legs_from_directive(directive, leg_data, leg_strategies)
    # Warmup contract (2026-05-30): rule declares its own data dependency via
    # required_warmup_bars (Protocol extension). The runner mutes leg signals
    # and rule.apply during the first N bars. Default 0 via getattr fallback
    # preserves byte-equivalence for rules that don't implement the method.
    # The data loader at the call site (run_pipeline._load_basket_leg_inputs)
    # uses the SAME rule.required_warmup_bars() value to pre-extend leg.df —
    # both consumers read from a single source of truth, no drift possible.
    rule_warmup = int(getattr(rule, "required_warmup_bars", lambda: 0)())
    runner = BasketRunner(legs=legs, rules=[rule], warmup_bars=rule_warmup)
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
        # 1.3.0-basket additions — getattr fallback covers V2/V3 rules until
        # they opt into the per_bar_records contract (see _instantiate_rule).
        per_bar_records=list(getattr(rule, "per_bar_records", [])),
        summary_stats=dict(getattr(rule, "summary_stats", {})),
    )


__all__ = ["BasketRunResult", "run_basket_pipeline"]
