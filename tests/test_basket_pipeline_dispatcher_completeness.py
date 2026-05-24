"""Static dispatcher-completeness contract test.

Companion to tests/test_basket_pipeline_param_validation.py — the validator
catches typos and unknown YAML keys at runtime; this test catches the
*opposite* silent-drop class statically: a rule dataclass field exists,
but the dispatcher's kwargs construction in basket_pipeline._instantiate_rule
silently doesn't forward it.

That's exactly the bug we hit 2026-05-24 with vol_neutral_sizing: the param
WAS on the H3SpreadV2Rule dataclass, the directive YAML correctly set it
to true, the validator (had it existed) would have accepted it — but the
dispatcher's kwargs list didn't mention it. The experiment ran with the
default value silently.

Design (kept deliberately simple, per the 2026-05-24 architecture
discussion):

  1. AST-parse `_instantiate_rule` to extract the set of keyword arguments
     passed to each rule class's constructor.
  2. For each rule class, derive the set of public configurable dataclass
     fields (non-private, non-runtime).
  3. Assert: every configurable field is EITHER forwarded by the dispatcher
     OR explicitly listed in _DISPATCHER_EXEMPTIONS with a documented reason.

The exemption table is hand-maintained and reviewed in PRs. That's the
point — explicit dispatcher wiring + explicit exemptions = governance
clarity. The alternative (auto-forward via introspection) was rejected
because it obscures what's actually being passed.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

import tools.basket_pipeline as bp
from tools.recycle_rules import (
    CointegrationMeanRevV1_2Rule,
    H2CompressionRecycleRule,
    H2RecycleRule,
    H2RecycleRuleV2,
    H2RecycleRuleV3,
    H2RecycleRuleV4,
    H2RecycleRuleV5,
    H3SpreadV1Rule,
    H3SpreadV2Rule,
    H3SpreadV3Rule,
    PineRatioZRevRule,
)


# ---------------------------------------------------------------------------
# Exemption tables
# ---------------------------------------------------------------------------

# Fields NOT settable via directive YAML on ANY rule. Universal because the
# concept is the same on every rule (mutable runtime state + runtime back-
# references + class metadata).
_UNIVERSAL_EXEMPT = frozenset({
    # Mutable runtime state (populated during apply() / emit()):
    "harvested", "harvested_total_usd",
    "exit_reason", "exit_ts",
    "recycle_events", "per_bar_records",
    "realized_total", "summary_stats",
    # Back-reference injected by BasketRunner.__init__:
    "basket_runner",
    # Class-level metadata (set as dataclass defaults; not per-instance
    # configurable from YAML — version is read from rule_cfg["version"]
    # at dispatch time, but the field itself isn't a kwarg):
    "name", "version",
})

# Fields treated as runtime-only across all dispatchers.
_RUNTIME_ONLY = frozenset({"run_id", "directive_id", "basket_id"})

# Per-rule exemptions. Each entry MUST include a reason — review-quality
# rationale that explains why the field shouldn't be forwarded from YAML.
# When you add a new dataclass field to a rule, you either wire it through
# the dispatcher (preferred) OR add it here with a reason. The test will
# fail if you do neither.
_DISPATCHER_EXEMPTIONS: dict[str, dict[str, str]] = {
    "H2RecycleRule": {},
    "H2RecycleRuleV2": {},
    "H2RecycleRuleV3": {},
    "H2RecycleRuleV4": {},
    "H2RecycleRuleV5": {
        "correlation_column_1h": (
            "Internal default column name; basket_data_loader writes "
            "'fx_corr_1h' as the standard column. Not user-tunable in current "
            "registry."
        ),
        "correlation_column_4h": (
            "Internal default column name; basket_data_loader writes "
            "'fx_corr_4h' as the standard column. Not user-tunable in current "
            "registry."
        ),
    },
    "H2CompressionRecycleRule": {
        # H2_v7_compression@1 is the deprecated misimplementation that refuses
        # to instantiate via _instantiate_rule. Dispatcher has no forwarding
        # kwargs at all. Exempting all configurable fields preserves the
        # "this rule cannot run from YAML" contract.
        "factor_column": "Deprecated H2_v7_compression@1; rule refuses dispatch",
        "harvest_threshold_usd": "Deprecated H2_v7_compression@1; rule refuses dispatch",
        "stake_usd": "Deprecated H2_v7_compression@1; rule refuses dispatch",
        "threshold": "Deprecated H2_v7_compression@1; rule refuses dispatch",
    },
    # H3 family inherits from H2RecycleRule (via H3SpreadV1Rule's class
    # hierarchy). The H2 fields exist on the dataclass but are HARDCODED in
    # H3SpreadV1Rule.__post_init__ — H3 strategies don't use the compression
    # factor gate, the leverage/freeze logic, etc. Exempting these is correct.
    "H3SpreadV1Rule": {
        "add_lot": "Inherited from H2RecycleRule; hardcoded in H3.__post_init__",
        "trigger_usd": "Inherited from H2; hardcoded in H3.__post_init__",
        "harvest_target_usd": "Inherited from H2; hardcoded in H3.__post_init__",
        "factor_column": "Inherited from H2; H3 has no compression-factor gate",
        "factor_min": "Inherited from H2; unused on H3",
        "factor_operator": "Inherited from H2; unused on H3",
        "leverage": "Inherited from H2; hardcoded in H3.__post_init__",
        "equity_floor_usd": "Inherited from H2; hardcoded in H3.__post_init__",
        "starting_equity": "Derived from initial_notional_usd on H3",
        "dd_freeze_frac": "Inherited from H2; hardcoded in H3.__post_init__",
        "margin_freeze_frac": "Inherited from H2; hardcoded in H3.__post_init__",
        "time_stop_days": "Inherited from H2; H3 uses time_stop_bars instead",
    },
    "H3SpreadV2Rule": {
        # All H3V1 exemptions inherited unchanged:
        "add_lot": "Inherited from H2RecycleRule via H3V1; hardcoded in __post_init__",
        "trigger_usd": "Inherited; hardcoded in __post_init__",
        "harvest_target_usd": "Inherited; hardcoded in __post_init__",
        "factor_column": "Inherited; H3 has no compression-factor gate",
        "factor_min": "Inherited; unused on H3",
        "factor_operator": "Inherited; unused on H3",
        "leverage": "Inherited; hardcoded in __post_init__",
        "equity_floor_usd": "Inherited; hardcoded in __post_init__",
        "starting_equity": "Derived from initial_notional_usd",
        "dd_freeze_frac": "Inherited; hardcoded in __post_init__",
        "margin_freeze_frac": "Inherited; hardcoded in __post_init__",
        "time_stop_days": "Inherited; H3 uses time_stop_bars",
        # V2-specific:
        "pyramid_level_pcts": (
            "Legacy V1 schema; V2's __post_init__ writes a sentinel "
            "single-element tuple just to satisfy parent validation. Superseded "
            "by pyramid_threshold_step_pct (a single arithmetic-progression "
            "step rather than a finite list)."
        ),
    },
    "H3SpreadV3Rule": {
        # Same as V2 (via inheritance chain V3 -> V2 -> V1 -> H2RecycleRule):
        "add_lot": "Inherited from H2 via H3V1/V2; hardcoded in __post_init__",
        "trigger_usd": "Inherited; hardcoded in __post_init__",
        "harvest_target_usd": "Inherited; hardcoded in __post_init__",
        "factor_column": "Inherited; H3 has no compression-factor gate",
        "factor_min": "Inherited; unused on H3",
        "factor_operator": "Inherited; unused on H3",
        "leverage": "Inherited; hardcoded in __post_init__",
        "equity_floor_usd": "Inherited; hardcoded in __post_init__",
        "starting_equity": "Derived from initial_notional_usd",
        "dd_freeze_frac": "Inherited; hardcoded in __post_init__",
        "margin_freeze_frac": "Inherited; hardcoded in __post_init__",
        "time_stop_days": "Inherited; H3 uses time_stop_bars",
        "pyramid_level_pcts": "Inherited from V2; legacy V1 schema, superseded by pyramid_threshold_step_pct",
    },
    "CointegrationMeanRevV1_2Rule": {
        # Same H2 inheritance exemptions:
        "add_lot": "Inherited from H2; hardcoded in __post_init__",
        "trigger_usd": "Inherited; hardcoded in __post_init__",
        "harvest_target_usd": "Inherited; hardcoded in __post_init__",
        "factor_column": "Inherited; COINTREV has no compression-factor gate",
        "factor_min": "Inherited; unused",
        "factor_operator": "Inherited; unused",
        "leverage": "Inherited; hardcoded in __post_init__",
        "equity_floor_usd": "Inherited; hardcoded in __post_init__",
        "starting_equity": "Derived from initial_notional_usd",
        "dd_freeze_frac": "Inherited; hardcoded in __post_init__",
        "margin_freeze_frac": "Inherited; hardcoded in __post_init__",
        "time_stop_days": "Inherited; COINTREV uses time_stop_bars",
        # COINTREV-specific:
        "shared_armed_state": (
            "Auto-discovered from leg.strategy.armed_state at first apply(); "
            "explicit injection is unit-test convenience only. Production flow "
            "doesn't pass it through YAML."
        ),
    },
    "PineRatioZRevRule": {
        # Same H2 inheritance exemptions:
        "add_lot": "Inherited from H2; hardcoded in __post_init__",
        "trigger_usd": "Inherited; hardcoded in __post_init__",
        "harvest_target_usd": "Inherited; hardcoded in __post_init__",
        "factor_column": "Inherited; Pine has no compression-factor gate",
        "factor_min": "Inherited; unused",
        "factor_operator": "Inherited; unused",
        "leverage": "Inherited; hardcoded in __post_init__",
        "equity_floor_usd": "Inherited; hardcoded in __post_init__",
        "starting_equity": "Derived from initial_notional_usd",
        "dd_freeze_frac": "Inherited; hardcoded in __post_init__",
        "margin_freeze_frac": "Inherited; hardcoded in __post_init__",
        "time_stop_days": "Inherited; Pine uses always-in-market with no time stop",
        # Pine-specific:
        "shared_armed_state": (
            "Auto-discovered from leg.strategy.armed_state at first apply(); "
            "explicit injection is unit-test convenience only."
        ),
        "signal_column": (
            "Internal column name; default 'pine_zrev_signal' matches the "
            "indicator output. Not user-tunable in current registry."
        ),
        "r_bar_column": (
            "Internal column name; default 'pine_zrev_r_bar' matches the "
            "indicator output. Not user-tunable in current registry."
        ),
    },
}


_ALL_RULES = [
    H2RecycleRule, H2RecycleRuleV2, H2RecycleRuleV3, H2RecycleRuleV4,
    H2RecycleRuleV5, H2CompressionRecycleRule,
    H3SpreadV1Rule, H3SpreadV2Rule, H3SpreadV3Rule,
    CointegrationMeanRevV1_2Rule, PineRatioZRevRule,
]


def _extract_dispatcher_kwargs_by_rule() -> dict[str, set[str]]:
    """AST-parse _instantiate_rule. Return {rule_class_name: {kwarg_name, ...}}.

    Walks every Call node whose function is a known rule class name and
    collects the keyword arg names. Aggregates across all dispatch branches
    (e.g., if a rule were referenced in multiple branches, all kwargs would
    be unioned — irrelevant here because each rule has one dispatch branch).
    """
    src = inspect.getsource(bp._instantiate_rule)
    tree = ast.parse(src)
    out: dict[str, set[str]] = {}
    rule_names = {c.__name__ for c in _ALL_RULES}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in rule_names
        ):
            kw = {k.arg for k in node.keywords if k.arg is not None}
            out.setdefault(node.func.id, set()).update(kw)
    return out


def _public_configurable_fields(rule_cls: type) -> set[str]:
    """Public (non-private, non-runtime) dataclass fields on a rule."""
    return {
        f.name for f in dataclasses.fields(rule_cls)
        if not f.name.startswith("_") and f.name not in _RUNTIME_ONLY
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_cls", _ALL_RULES, ids=lambda c: c.__name__)
def test_dispatcher_forwards_or_exempts_every_configurable_field(rule_cls):
    """The core completeness contract.

    Every public configurable dataclass field on a rule must be either
    forwarded by the dispatcher's kwargs (preferred) or explicitly listed
    in _DISPATCHER_EXEMPTIONS with a documented reason.

    Catches the 2026-05-24 silent-drop bug class: vol_neutral_sizing was
    added to the H3SpreadV2Rule dataclass but the dispatcher kwargs in
    _instantiate_rule didn't forward it. Setting it in the directive YAML
    was silently no-op'd; the experiment APPEARED to run with the new
    param but actually used the default.

    If this test fails after adding a new field, either:
      (a) Add the field to the dispatcher's kwargs construction (preferred
          for any user-tunable parameter).
      (b) Add the field to _DISPATCHER_EXEMPTIONS[<rule_name>] with a
          short reason explaining why it's not user-settable from YAML
          (use for internal state, hardcoded inherited fields, etc.).
    """
    cls_name = rule_cls.__name__
    declared = _public_configurable_fields(rule_cls)
    forwarded = _extract_dispatcher_kwargs_by_rule().get(cls_name, set()) - _RUNTIME_ONLY
    per_rule_exempt = set(_DISPATCHER_EXEMPTIONS.get(cls_name, {}).keys())
    accepted = forwarded | _UNIVERSAL_EXEMPT | per_rule_exempt
    missing = declared - accepted
    assert not missing, (
        f"\n{cls_name}: dispatcher does not forward configurable field(s): "
        f"{sorted(missing)}\n"
        f"  Each missing field must be either:\n"
        f"    (a) added to the dispatcher's kwargs construction in\n"
        f"        tools/basket_pipeline.py:_instantiate_rule for {cls_name}, OR\n"
        f"    (b) added to _DISPATCHER_EXEMPTIONS[{cls_name!r}] in this test\n"
        f"        with a reason explaining why it's not user-settable.\n"
        f"  Forwarded by dispatcher: {sorted(forwarded)}\n"
        f"  Already exempt (universal): {sorted(_UNIVERSAL_EXEMPT)}\n"
        f"  Already exempt (per-rule): {sorted(per_rule_exempt)}\n"
        f"  This test catches the silent-no-op class — see 2026-05-24 "
        f"vol_neutral_sizing dispatcher bug."
    )


@pytest.mark.parametrize("rule_cls", _ALL_RULES, ids=lambda c: c.__name__)
def test_no_stale_exemptions_in_dispatcher_table(rule_cls):
    """Exemptions must refer to fields that actually exist on the rule.
    Catches stale entries left behind after a field rename or removal."""
    cls_name = rule_cls.__name__
    all_dataclass_fields = {f.name for f in dataclasses.fields(rule_cls)}
    exempt = set(_DISPATCHER_EXEMPTIONS.get(cls_name, {}).keys())
    stale = exempt - all_dataclass_fields
    assert not stale, (
        f"\n{cls_name}: stale entries in _DISPATCHER_EXEMPTIONS: {sorted(stale)}\n"
        f"  These field names do not exist on the rule dataclass. Most likely\n"
        f"  the field was renamed or removed. Remove the stale entry from\n"
        f"  the exemption table."
    )


@pytest.mark.parametrize("rule_cls", _ALL_RULES, ids=lambda c: c.__name__)
def test_no_redundant_exemptions_in_dispatcher_table(rule_cls):
    """A field that IS forwarded by the dispatcher must not also be exempt.
    Redundant exemptions mislead future devs about which fields are user-
    settable."""
    cls_name = rule_cls.__name__
    forwarded = _extract_dispatcher_kwargs_by_rule().get(cls_name, set())
    exempt = set(_DISPATCHER_EXEMPTIONS.get(cls_name, {}).keys())
    redundant = forwarded & exempt
    assert not redundant, (
        f"\n{cls_name}: redundant entries in _DISPATCHER_EXEMPTIONS: {sorted(redundant)}\n"
        f"  These fields ARE forwarded by the dispatcher's kwargs. The\n"
        f"  exemption is misleading — remove it."
    )


def test_universal_exempt_fields_actually_exist_on_at_least_one_rule():
    """Sanity check: each _UNIVERSAL_EXEMPT name must appear on at least
    one rule's dataclass. Catches typos in the universal list itself."""
    all_fields_across_rules = set()
    for cls in _ALL_RULES:
        all_fields_across_rules |= {f.name for f in dataclasses.fields(cls)}
    bogus = _UNIVERSAL_EXEMPT - all_fields_across_rules
    assert not bogus, (
        f"_UNIVERSAL_EXEMPT contains names not present on any rule: {sorted(bogus)}\n"
        f"  Either fix the typo or remove the entry."
    )


def test_all_dispatched_rules_appear_in_completeness_table():
    """Every rule we know about appears in _DISPATCHER_EXEMPTIONS (even if
    its entry is an empty dict). Catches new rules that someone added to
    tools/recycle_rules without registering them in this test."""
    in_table = set(_DISPATCHER_EXEMPTIONS.keys())
    expected = {c.__name__ for c in _ALL_RULES}
    missing = expected - in_table
    assert not missing, (
        f"Rules missing from _DISPATCHER_EXEMPTIONS table: {sorted(missing)}\n"
        f"  Add an entry (even {{}}) so future schema drift fails loudly."
    )
