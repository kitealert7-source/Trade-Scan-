"""Strict-validation tests for basket_pipeline._instantiate_rule.

Added 2026-05-24 after a silent-no-op experiment confused the
vol_neutral_sizing test. The dispatcher had silently dropped the new param
because its kwargs construction didn't forward it. These tests ensure
that future silent-drop bugs of the same class fail loudly.

What the validator catches:
  1. Typos in directive YAML (e.g., `vol_neutral_seizing` instead of
     `vol_neutral_sizing`).
  2. Params that exist on the rule's dataclass but aren't wired through
     the dispatcher's explicit kwargs (the bug we hit).
  3. Stale params left in directives after a rule schema change.

What it deliberately accepts:
  - Params consumed by external surfaces (leg strategy in run_pipeline.py,
    macro/regime data loader in basket_data_loader.py) via the
    _EXTERNAL_CONSUMER_PARAMS allowlist.
  - Documented aliases via _RULE_PARAM_ALIASES.
"""
from __future__ import annotations

import dataclasses

import pytest

from tools.basket_pipeline import _RUNTIME_ONLY_FIELDS, _instantiate_rule
from tools.recycle_rules import RULE_CLASSES


# ---------- Happy paths --------------------------------------------------

def test_validation_accepts_h3v2_with_known_params():
    """All canonical H3_spread@2 params accepted without error."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "bidirectional": True,
            "vol_neutral_sizing": True,
            "vol_neutral_window": 200,
            "max_exposure_multiple": 3.0,
            "pyramid_threshold_step_pct": 0.15,
            "adverse_stop_pct": 0.002,
            "time_stop_bars": 288,
            "entry_delay_bars": 8,  # external (leg strategy)
            "macro_direction_timeframe": "4h",  # external (data loader)
        },
    }
    # Must not raise.
    _instantiate_rule(rule_cfg)


def test_validation_accepts_h3v3_with_known_params():
    """All canonical H3_spread@3 params (including @2 inheritance) accepted."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 3,
        "params": {
            "bidirectional": True,
            "vol_neutral_sizing": True,
            "extreme_z_threshold": 5.0,
            "reentry_z_threshold": 1.0,
            "max_exposure_multiple": 3.0,
            "entry_delay_bars": 8,
            "macro_warmup_days": 120,
            "macro_z_window": 60,
        },
    }
    _instantiate_rule(rule_cfg)


def test_validation_accepts_documented_alias():
    """harvest_delay_levels is a documented alias for
    harvest_start_after_extra_pyramids — must not raise."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "harvest_delay_levels": 5,  # legacy alias
        },
    }
    _instantiate_rule(rule_cfg)


# ---------- Failure paths (the real regression value) --------------------

def test_validation_rejects_typo_in_directive_yaml():
    """Typo'd param name fails loudly."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {
            "vol_neutral_seizing": True,  # typo for vol_neutral_sizing
        },
    }
    with pytest.raises(ValueError) as exc:
        _instantiate_rule(rule_cfg)
    assert "recycle_rule.params validation failed" in str(exc.value)
    assert "vol_neutral_seizing" in str(exc.value)


def test_validation_rejects_unknown_param_with_helpful_message():
    """Unknown param produces a diagnostic that lists valid params."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"made_up_param_name": 42},
    }
    with pytest.raises(ValueError) as exc:
        _instantiate_rule(rule_cfg)
    msg = str(exc.value)
    # Includes the unknown param name
    assert "made_up_param_name" in msg
    # Includes a hint about what's valid
    assert "Rule dataclass fields" in msg
    assert "External-consumer params" in msg
    # Includes the historical context
    assert "2026-05-24" in msg


def test_validation_rejects_dispatcher_bug_class():
    """REGRESSION: this is exactly the bug we hit today. If a future PR
    adds a param to a rule's dataclass but forgets to wire it through the
    dispatcher's kwargs, this validator must still let it through (because
    the dataclass field IS valid) — but the dispatcher would simply not
    forward it. So this test verifies the validator's positive case for
    a NEW dataclass field, then the SEPARATE behavioral test
    (test_basket_leg_invariants.test_leg_direction_immutable_through_cycle
    and similar) verifies the param actually takes effect.

    The validator's job is the *negative* half — catch typos and stale
    params. The dispatcher-forwarding bug is caught by behavioral tests on
    the param (e.g., the post-fix sizing test on h3_spread). Together they
    eliminate the silent-no-op class."""
    # vol_neutral_sizing was the silent-drop bug today; it IS on the
    # H3SpreadV2Rule dataclass, so the validator accepts it. The behavioral
    # proof (param actually applies) is the integration test (see
    # 2026-05-24 dispatcher fix commit + the S21 vol-neutral re-run).
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"vol_neutral_sizing": True},
    }
    _instantiate_rule(rule_cfg)  # must not raise


def test_validation_rejects_runtime_only_field_in_yaml():
    """Runtime-only fields like run_id must not be settable from YAML."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"run_id": "ATTEMPTED_OVERRIDE"},
    }
    with pytest.raises(ValueError, match="run_id"):
        _instantiate_rule(rule_cfg)


def test_validation_rejects_private_field_in_yaml():
    """Private (_-prefixed) fields must not be settable from YAML."""
    rule_cfg = {
        "name": "H3_spread",
        "version": 2,
        "params": {"_basket_open": True},
    }
    with pytest.raises(ValueError, match="_basket_open"):
        _instantiate_rule(rule_cfg)


# ---------- Wiring (not just validation) --------------------------------
# Regression guard for the 2026-06-15 silent-no-op: adaptive_width/bb_k/bb_m
# PASSED validation (they are known dataclass fields) but the pine constructor
# branches dropped them, so a BB-adaptive directive ran as a FIXED z_entry band
# across a full 994-pair corpus before the gap was caught. Validation-acceptance
# is necessary but NOT sufficient — these assert the value reaches the rule.

@pytest.mark.parametrize("rule_name", [
    "pine_ratio_zrev_v1",
    "pine_ratio_zrev_v1_zcross",
    "pine_ratio_zrev_v1_zband",
    "pine_ratio_zrev_v1_zopp",
])
def test_pine_adaptive_band_params_are_wired(rule_name):
    """adaptive_width/bb_k/bb_m must flow through _instantiate_rule to the rule
    instance (not silently default), and warmup must become adaptive-aware."""
    rule_cfg = {
        "name": rule_name,
        "version": 1,
        "params": {
            "n_window": 30,
            "entry_mode": "absolute",
            "z_entry": 2.0,
            "adaptive_width": True,
            "bb_k": 2.5,
            "bb_m": 20,
        },
    }
    rule = _instantiate_rule(rule_cfg)
    assert rule.adaptive_width is True, f"{rule_name}: adaptive_width not wired"
    assert rule.bb_k == 2.5, f"{rule_name}: bb_k silently defaulted (not wired)"
    assert rule.bb_m == 20, f"{rule_name}: bb_m not wired"
    # warmup must gain the +bb_m cushion once adaptive (2*n_window + bb_m).
    assert rule.required_warmup_bars() == 2 * 30 + 20


# ---------- META-TEST: every directive-settable field is wired -----------
# Generalizes test_pine_adaptive_band_params_are_wired (the 2026-06-15
# adaptive_width/bb_k/bb_m silent-no-op) to EVERY rule the dispatcher builds.
#
# The bug class: a param is added to a rule's dataclass — and the validator
# accepts it because it IS a known dataclass field — but _instantiate_rule's
# constructor branch never forwards it. A directive setting the param passes
# validation yet silently runs with the dataclass default. Unit tests that
# construct the rule directly bypass the dispatcher and miss this entirely;
# only the dispatcher path exposes it. On 2026-06-15 a full 994-pair
# "BB-adaptive" corpus ran as a plain FIXED z-entry band for exactly this
# reason (fixed in 374b061a).
#
# Strategy: for each dispatched rule, compute the set of DIRECTIVE-SETTABLE
# dataclass fields, then capture exactly which kwargs _instantiate_rule passes
# to that rule's constructor (via an __init__ spy — value-independent, so no
# __post_init__ / cross-field-constraint fragility) and assert every settable
# field is among them. A NEW unwired param lands in `settable` (it is in no
# deny-set) but not in `wired`, so the test fails loudly and names the field.

# Deprecated rules _instantiate_rule REFUSES to construct (it raises instead of
# returning an instance) — there is no constructor branch to verify.
_DEPRECATED_RULES = frozenset({("H2_v7_compression", 1)})

# Drive parametrization straight off the dispatch table so a newly-wired rule
# is covered automatically (test_meta_test_covers_every_dispatched_rule guards
# the invariant).
_DISPATCHED_RULES = sorted(set(RULE_CLASSES) - _DEPRECATED_RULES)

# Base H2RecycleRule machinery inherited by every rule: per-run accounting /
# output fields + runtime-injected handles. None is a directive param.
_OUTPUT_AND_RUNTIME_FIELDS = frozenset({
    "name", "version",                            # registry identity (class defaults)
    "realized_total", "harvested_total_usd", "harvested",
    "exit_reason", "exit_ts", "recycle_events",   # per-run accounting / output
    "per_bar_records", "summary_stats",           # 1.3.0-basket ledger output
    "basket_runner",                              # back-ref injected by BasketRunner
    "shared_armed_state",                         # injected by the leg strategies
})

# Base H2 financial knobs. Directive-settable + wired ONLY for the H2_recycle
# family (the rules that actually run the Variant-G recycle mechanic). Every
# other family inherits H2RecycleRule purely for its parquet/events machinery
# (see each registry description) and leaves these fields vestigial + UNWIRED.
_H2_FINANCIAL_PARAMS = frozenset({
    "trigger_usd", "add_lot", "starting_equity", "harvest_target_usd",
    "equity_floor_usd", "time_stop_days", "dd_freeze_frac",
    "margin_freeze_frac", "leverage", "factor_column", "factor_min",
    "factor_operator",
})

# Per-rule fields that exist on the dataclass but are deliberately NOT exposed
# as directive params: internal column-name constants the rule attaches itself,
# or params made vestigial by a later version. Each entry is a conscious
# "do not wire" decision — a genuinely-new CONFIG param must NOT be added here
# (that would hide exactly the bug this meta-test exists to catch).
_INTERNAL_OR_VESTIGIAL_BY_RULE: dict[tuple[str, int], frozenset[str]] = {
    # @5 reads its correlation series by fixed column name; only the
    # thresholds/toggles are directive-settable (and wired).
    ("H2_recycle", 5): frozenset({"correlation_column_1h", "correlation_column_4h"}),
    # @2/@3 generalized @1's discrete pyramid_level_pcts list into the single
    # pyramid_threshold_step_pct knob; the inherited list field is vestigial.
    ("H3_spread", 2): frozenset({"pyramid_level_pcts"}),
    ("H3_spread", 3): frozenset({"pyramid_level_pcts"}),
    # signal_column / r_bar_column name the columns the pine rule attaches to
    # each leg DataFrame; they are internal, not directive knobs. The exit
    # variants add their own exit-flag column name (zcross_/zband_) likewise.
    ("pine_ratio_zrev_v1", 1): frozenset({"signal_column", "r_bar_column"}),
    ("pine_ratio_zrev_v1_zcross", 1): frozenset({"signal_column", "r_bar_column", "zcross_column"}),
    ("pine_ratio_zrev_v1_zband", 1): frozenset({"signal_column", "r_bar_column", "zband_column"}),
    ("pine_ratio_zrev_v1_zopp", 1): frozenset({"signal_column", "r_bar_column"}),
    # 2026-06-08 branch additions: same column-name pattern as the originals.
    ("pine_ratio_zrev_v1_zcross_zavg", 1): frozenset({"signal_column", "r_bar_column", "zcross_column", "zavg_column"}),
    ("pine_ratio_zrev_v1_zcross_hf", 1): frozenset({"signal_column", "r_bar_column", "zcross_column", "hurst_column"}),
    ("pine_ratio_zrev_v1_zcross_hl", 1): frozenset({"signal_column", "r_bar_column", "zcross_column", "hl_column"}),
    ("pine_ratio_zrev_v1_zcross_lm", 1): frozenset({"signal_column", "r_bar_column", "zcross_column", "lm_column"}),
    ("pine_ratio_zrev_v1_zcross_hflm", 1): frozenset({"signal_column", "r_bar_column", "zcross_column", "hurst_column", "lm_column"}),
    ("pine_ratio_zrev_v1_zstop", 1): frozenset({"signal_column", "r_bar_column", "zcross_column"}),
    ("pine_ratio_zrev_v1_session_window", 1): frozenset({"signal_column", "r_bar_column", "zcross_column"}),
}


# Rules that call _require_param() for a mandatory directive param need that
# param supplied when _capture_wired_kwargs() calls _instantiate_rule() with
# an otherwise-empty params dict. Values are arbitrary sentinels — the test
# only captures kwarg NAMES, not values.
_REQUIRED_PARAMS_FOR_WIRING_TEST: dict[tuple[str, int], dict] = {
    ("pine_ratio_zrev_v1", 1):                  {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross", 1):           {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross_zavg", 1):      {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross_hf", 1):        {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross_hl", 1):        {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross_lm", 1):        {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zcross_hflm", 1):      {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zstop", 1):            {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_session_window", 1):   {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zband", 1):            {"z_entry": 2.0},
    ("pine_ratio_zrev_v1_zopp", 1):             {"z_entry": 2.0},
}


def _directive_settable_fields(name: str, version: int, cls: type) -> set[str]:
    """Fields a directive's recycle_rule.params is meant to set for this rule.

    All public dataclass fields MINUS: identity args (run_id/directive_id/
    basket_id), base output/runtime machinery, this rule's internal/vestigial
    fields, and — for non-H2_recycle families — the vestigially-inherited H2
    financial knobs.
    """
    fields = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
    fields -= _RUNTIME_ONLY_FIELDS          # run_id / directive_id / basket_id
    fields -= _OUTPUT_AND_RUNTIME_FIELDS
    fields -= _INTERNAL_OR_VESTIGIAL_BY_RULE.get((name, version), frozenset())
    if name != "H2_recycle":                # H2 financials are live only for H2_recycle@*
        fields -= _H2_FINANCIAL_PARAMS
    return fields


def _capture_wired_kwargs(name: str, version: int, cls: type) -> set[str]:
    """Return the kwarg names _instantiate_rule forwards to this rule's ctor.

    Spies on the rule class __init__ so we observe exactly what the dispatcher
    branch passes — independent of param values or __post_init__ — then
    restores the original __init__. Called with minimal required params so any
    _require_param() gates pass; the dispatcher then supplies all remaining
    kwargs from its own defaults. Required params are named in
    _REQUIRED_PARAMS_FOR_WIRING_TEST — add an entry there for any new rule
    that adds a _require_param() gate (the sentinel value is irrelevant; only
    the kwarg NAME is captured).
    """
    captured: dict[str, object] = {}
    original_init = cls.__init__

    def _spy(self, *args, **kwargs):
        captured["kwargs"] = set(kwargs)
        captured["args"] = args

    minimal_params = _REQUIRED_PARAMS_FOR_WIRING_TEST.get((name, version), {})
    cls.__init__ = _spy
    try:
        _instantiate_rule({"name": name, "version": version, "params": minimal_params})
    finally:
        cls.__init__ = original_init

    assert not captured.get("args"), (
        f"{name}@{version}: _instantiate_rule passes POSITIONAL args to the rule "
        f"constructor ({captured.get('args')!r}); this meta-test assumes "
        f"keyword-only construction. Update the spy if that convention changed."
    )
    return captured.get("kwargs", set())  # type: ignore[return-value]


def test_meta_test_covers_every_dispatched_rule():
    """Coverage guard: the parametrized wiring test must iterate EVERY rule the
    dispatcher constructs (RULE_CLASSES minus deprecated). Adding a branch to
    _instantiate_rule without it appearing in RULE_CLASSES — or leaving a stale
    deny-set entry after a rule is removed/renamed — fails here."""
    assert set(_DISPATCHED_RULES) == set(RULE_CLASSES) - _DEPRECATED_RULES
    for key in _INTERNAL_OR_VESTIGIAL_BY_RULE:
        assert key in RULE_CLASSES, (
            f"stale _INTERNAL_OR_VESTIGIAL_BY_RULE entry {key!r}: no such rule "
            f"in RULE_CLASSES (remove or fix after the rename/removal)."
        )


def test_deprecated_rules_do_not_construct():
    """The deprecation exclusion is honest: _instantiate_rule must REFUSE to
    build each excluded rule, so there is genuinely no constructor branch to
    verify. If a deprecated rule is ever wired, this fails — move it out of
    _DEPRECATED_RULES and into coverage."""
    for name, version in _DEPRECATED_RULES:
        with pytest.raises(NotImplementedError):
            _instantiate_rule({"name": name, "version": version, "params": {}})


@pytest.mark.parametrize("name,version", _DISPATCHED_RULES)
def test_every_directive_settable_field_is_wired(name, version):
    """META-TEST (generalizes test_pine_adaptive_band_params_are_wired): every
    directive-settable dataclass field must be forwarded by this rule's
    _instantiate_rule constructor branch. Catches the silent-no-op class where
    a param passes validation (it is a known dataclass field) but the
    dispatcher drops it — the 2026-06-15 adaptive_width/bb_k/bb_m bug that ran a
    994-pair corpus as a FIXED z-entry band."""
    cls = RULE_CLASSES[(name, version)]
    settable = _directive_settable_fields(name, version, cls)
    wired = _capture_wired_kwargs(name, version, cls)
    missing = settable - wired
    assert not missing, (
        f"{name}@{version} ({cls.__name__}): directive-settable dataclass "
        f"field(s) {sorted(missing)} are NOT forwarded by _instantiate_rule's "
        f"constructor branch. A directive setting them would pass validation "
        f"but silently run with the dataclass default (the 2026-06-15 "
        f"adaptive_width silent-no-op class). Fix: forward them in the "
        f"constructor call in tools/basket_pipeline.py::_instantiate_rule. If a "
        f"field is genuinely internal/vestigial for THIS rule (a column-name "
        f"constant the rule attaches itself, or a param superseded by a later "
        f"version), add it to _INTERNAL_OR_VESTIGIAL_BY_RULE with a justifying "
        f"comment instead."
    )
