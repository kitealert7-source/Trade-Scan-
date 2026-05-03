"""Phase 4 - Classifier Gate tests.

Covers tools/classifier_gate.py evaluate() — verdict logic for first-of-kind,
UNCLASSIFIABLE, SIGNAL-without-bump, indicator-hash drift, PARAMETER, COSMETIC,
and same-basename re-run exclusion.

All tests synthesize directives and indicator modules under a tmp_path; no
production directives or indicators are touched.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.classifier_gate import evaluate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIRECTIVE_TEMPLATE = textwrap.dedent("""\
    test:
      name: {name}
      family: STR
      strategy: {name}
      version: 1
      broker: OctaFx
      timeframe: 1h
      start_date: '2024-01-02'
      end_date: '2026-03-20'
      research_mode: true
      signal_version: {sv}
      description: "{desc}"

    symbols:
      - {symbol}

    indicators:
    {indicators_block}

    execution_rules:
      stop_loss:
        atr_multiplier: {atr}
      take_profit:
        atr_multiplier: 3.0
""")


def _write_indicator(root: Path, dotted: str, primitive: str) -> Path:
    rel = Path(*dotted.split("."))
    path = (root / rel).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Include an __init__.py in each dir so Python recognises packages
    # (not strictly needed for tokenize-based hashing, but kept tidy).
    cur = root
    for part in dotted.split(".")[:-1]:
        cur = cur / part
        init = cur / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
    path.write_text(
        textwrap.dedent(f"""\
            SIGNAL_PRIMITIVE = "{primitive}"
            PIVOT_SOURCE = "none"
            def run():
                return 0
        """),
        encoding="utf-8",
    )
    return path


def _write_directive(
    directory: Path,
    name: str,
    *,
    sv: int = 1,
    indicators: list[str] | None = None,
    atr: float = 1.5,
    desc: str = "test",
    symbol: str = "USDJPY",
) -> Path:
    inds = indicators or ["indicators.volatility.atr", "indicators.structure.choch"]
    block = "\n".join(f"  - {i}" for i in inds)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.txt"
    path.write_text(
        _DIRECTIVE_TEMPLATE.format(
            name=name, sv=sv, indicators_block=block,
            atr=atr, desc=desc, symbol=symbol,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def sandbox(tmp_path: Path) -> dict:
    root = tmp_path / "repo"
    root.mkdir()
    # Minimal indicator shims — primitives are irrelevant to the gate logic,
    # but the modules must exist at the resolved dotted path.
    _write_indicator(root, "indicators.volatility.atr", "wilder_rma_tr")
    _write_indicator(root, "indicators.structure.choch", "rolling_max_proxy")
    _write_indicator(root, "indicators.structure.choch_v2", "pivot_k3")
    prior_dir = root / "prior"
    inbox = root / "inbox"
    return {"root": root, "prior_dir": prior_dir, "inbox": inbox}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pass_when_no_prior(sandbox):
    cur = _write_directive(
        sandbox["inbox"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, symbol="USDJPY",
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],  # empty — no priors
    )
    assert v.verdict == "PASS"
    assert v.prior_directive is None
    assert v.classification == "N/A"


def test_block_when_signal_change_without_sv_bump(sandbox):
    prior = _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",  # different stem
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "BLOCK"
    assert v.classification == "SIGNAL"
    assert "signal_version=1" in v.reason
    assert v.prior_directive == prior.stem


def test_pass_when_signal_change_with_sv_bump(sandbox):
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=2, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS"
    assert v.classification == "SIGNAL"


def test_pass_on_parameter_only_diff(sandbox):
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=1.5,
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=2.0,
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS"
    assert v.classification == "PARAMETER"


def test_pass_on_cosmetic_only_diff(sandbox):
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, desc="alpha",
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, desc="beta",
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS"
    assert v.classification == "COSMETIC"


def test_same_stem_prior_excluded_rerun_case(sandbox):
    # Prior and current share basename => re-run scenario; should NOT compare.
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur = _write_directive(
        sandbox["inbox"], "11_STR_FX_1H_CHOCH_S01_V1_P00",  # same stem
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS"
    assert v.prior_directive is None  # excluded by stem
    assert v.classification == "N/A"


def test_block_on_indicator_hash_drift_without_sv_bump(sandbox):
    # Same indicator imports; but injected lookup returns a DIFFERENT prior
    # aggregate hash than the current one. Should BLOCK.
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=1.5,
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=1.5,  # PARAMETER-equivalent: identical params
    )

    def _fake_lookup(stem: str) -> str:
        return "deadbeef" * 8  # fake old hash, guaranteed != current

    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
        prior_indicators_hash_lookup=_fake_lookup,
    )
    assert v.verdict == "BLOCK"
    assert "hash changed" in v.reason
    assert v.details.get("indicator_hash_delta_detected") is True


def test_engine_rerun_narrows_to_same_timeframe_and_sweep(sandbox):
    """ENGINE-category reruns must restrict the baseline search to priors
    sharing (family, timeframe, sweep). When BOTH a same-identity prior and
    a structurally-distant sibling exist, the same-identity prior must win
    — even if the distant sibling has a more recent mtime.

    Scenario:
      * 15M/S01 prior (wide match only; distant) — written FIRST, then its
        mtime bumped by rewriting it LAST so it sorts first under the old
        wide-match logic.
      * 30M/S02 prior (same-identity) with only numeric (ATR) differences.
      * Current: ENGINE-rerun 30M/S02 with one numeric tweak.
    Without narrowing: 15M/S01 would be picked (more recent) → SIGNAL diff
    from indicator delta → BLOCK. With narrowing: 30M/S02 is picked →
    PARAMETER diff → PASS.
    """
    import os
    import time

    # Same-identity prior — written first.
    same_id = _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_30M_CHOCH_S02_V1_P00",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    # Wide-but-wrong prior — written second, and touched again below to force
    # the most-recent mtime (would be picked under the old wide-only logic).
    wrong_prior = _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_15M_CHOCH_S01_V1_P05",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    # Force wrong_prior to have a strictly-newer mtime than same_id.
    now = time.time()
    os.utime(str(same_id), (now - 10, now - 10))
    os.utime(str(wrong_prior), (now, now))

    # Current: ENGINE rerun, 30M/S02, numeric-only diff vs same-identity prior.
    name = "22_CONT_FX_30M_CHOCH_S02_V1_P03"
    block = "\n".join(
        f"  - {i}" for i in
        ("indicators.volatility.atr", "indicators.structure.choch")
    )
    body = _DIRECTIVE_TEMPLATE.format(
        name=name, sv=1, indicators_block=block,
        atr=1.7,  # differs from same-identity prior's 1.5 → PARAMETER diff
        desc="engine-rerun verification", symbol="EURUSD",
    )
    body = body.replace(
        "  signal_version: 1",
        (
            "  signal_version: 1\n"
            "  repeat_override_reason: '[RERUN:ENGINE@2026-04-16 "
            "origin=directive-clone strategy=22_CONT_FX_30M_CHOCH_S02_V1_P03] "
            "engine-only rerun to validate invariance post v1.5.6 freeze'"
        ),
    )
    sandbox["inbox"].mkdir(parents=True, exist_ok=True)
    cur = sandbox["inbox"] / f"{name}.txt"
    cur.write_text(body, encoding="utf-8")

    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    # Narrowing must pick the 30M/S02 prior despite the 15M/S01 prior being
    # more recent. PARAMETER diff → PASS.
    assert v.verdict == "PASS", f"unexpected BLOCK: {v.reason}"
    assert v.prior_directive == "22_CONT_FX_30M_CHOCH_S02_V1_P00", (
        f"narrowing failed — picked {v.prior_directive} instead of same-identity prior"
    )
    assert v.classification == "PARAMETER"


def test_engine_rerun_falls_back_to_wide_when_no_same_identity_prior(sandbox):
    """Fallback path: per the user directive, if no same-identity prior
    exists the wide (MODEL, ASSET_CLASS) match set is used. This preserves
    the classifier's ability to catch drift when the rerun is the first
    of its (family, TF, sweep) — a conservative default.
    """
    _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_15M_CHOCH_S01_V1_P05",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    name = "22_CONT_FX_30M_CHOCH_S02_V1_P03"
    block = "\n".join(
        f"  - {i}" for i in
        ("indicators.volatility.atr", "indicators.structure.choch")
    )
    body = _DIRECTIVE_TEMPLATE.format(
        name=name, sv=1, indicators_block=block,
        atr=1.5, desc="engine-rerun verification", symbol="EURUSD",
    )
    body = body.replace(
        "  signal_version: 1",
        (
            "  signal_version: 1\n"
            "  repeat_override_reason: '[RERUN:ENGINE@2026-04-16 "
            "origin=directive-clone strategy=22_CONT_FX_30M_CHOCH_S02_V1_P03] "
            "engine-only rerun to validate invariance post v1.5.6 freeze'"
        ),
    )
    sandbox["inbox"].mkdir(parents=True, exist_ok=True)
    cur = sandbox["inbox"] / f"{name}.txt"
    cur.write_text(body, encoding="utf-8")

    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    # No same-identity prior → fall back to wide → pick the 15M/S01 prior.
    # Only cosmetic diffs → PASS.
    assert v.verdict == "PASS"
    assert v.prior_directive == "22_CONT_FX_15M_CHOCH_S01_V1_P05"
    assert v.classification == "COSMETIC"


def test_structural_narrowing_active_without_override_reason(sandbox):
    """Sweep-scoping contract (2026-05-03): structural narrowing is ALWAYS
    active for structured directive names — not opt-in via ENGINE override
    reason. A structurally-distant prior (different timeframe, different
    sweep) is excluded from the candidate set, so the current directive
    is treated as first-of-kind in its own sweep slot.

    Replaces the legacy test_engine_rerun_narrowing_disabled_without_override_reason
    which encoded the old opt-in contract — see
    governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md.
    """
    _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_15M_CHOCH_S01_V1_P05",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    # No override reason on current directive — narrowing still applies.
    cur = _write_directive(
        sandbox["inbox"], "22_CONT_FX_30M_CHOCH_S02_V1_P03",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    # Structurally-distant prior (15M/S01 vs 30M/S02) excluded → first-of-kind.
    assert v.verdict == "PASS"
    assert v.classification == "N/A"
    assert v.prior_directive is None


def test_engine_rerun_still_matches_same_identity_prior(sandbox):
    """Positive path: when a same-(family, timeframe, sweep) prior exists,
    ENGINE-rerun narrowing must still select it. Ensures the fix doesn't
    over-suppress legitimate comparisons.
    """
    # Prior with the SAME structural identity as current.
    _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_30M_CHOCH_S02_V1_P00",
        sv=1, atr=1.5,
    )
    # Current: same TF + sweep, different P-tag, ENGINE override, numeric diff.
    name = "22_CONT_FX_30M_CHOCH_S02_V1_P03"
    block = "\n".join(
        f"  - {i}" for i in
        ("indicators.volatility.atr", "indicators.structure.choch")
    )
    body = _DIRECTIVE_TEMPLATE.format(
        name=name, sv=1, indicators_block=block,
        atr=1.7, desc="engine-rerun verification", symbol="EURUSD",
    )
    body = body.replace(
        "  signal_version: 1",
        (
            "  signal_version: 1\n"
            "  repeat_override_reason: '[RERUN:ENGINE@2026-04-16 "
            "origin=directive-clone strategy=22_CONT_FX_30M_CHOCH_S02_V1_P03] "
            "engine-only rerun to validate invariance post v1.5.6 freeze'"
        ),
    )
    sandbox["inbox"].mkdir(parents=True, exist_ok=True)
    cur = sandbox["inbox"] / f"{name}.txt"
    cur.write_text(body, encoding="utf-8")

    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    # Same-identity prior selected → PARAMETER diff (atr 1.5 → 1.7) → PASS.
    assert v.verdict == "PASS"
    assert v.prior_directive == "22_CONT_FX_30M_CHOCH_S02_V1_P00"
    assert v.classification == "PARAMETER"


def test_pass_when_indicator_hash_matches_and_no_signal_change(sandbox):
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=1.5,
    )
    cur = _write_directive(
        sandbox["inbox"], "12_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, atr=1.6,  # numeric diff only
    )

    # Lookup returns the same aggregate hash that the current directive produces.
    from tools.indicator_hasher import aggregate_indicator_hash
    modules = ["indicators.volatility.atr", "indicators.structure.choch"]
    expected, _ = aggregate_indicator_hash(modules, project_root=sandbox["root"])

    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
        prior_indicators_hash_lookup=lambda _stem: expected,
    )
    assert v.verdict == "PASS"
    assert v.classification == "PARAMETER"


# ---------------------------------------------------------------------------
# Sweep-scoping contract (2026-05-03)
# ---------------------------------------------------------------------------
# Five new cases proving prior-matching is scoped by sweep slot for
# structured directive names. See:
#   governance/SOP/CLASSIFIER_GATE_SCOPING_2026_05_03.md
#   governance/SOP/CLASSIFIER_GATE_SCOPING_PLAN_2026_05_03.md


def test_cross_sweep_parallel_exploration_passes(sandbox):
    """S03 vs S04 with different indicator sets at the same sv should PASS:
    parallel exploration, not lineage. Core unblocker for multi-architecture
    batch sweeps (NEWSBRK A1+A2, ZREV multi-arch, etc.)."""
    _write_indicator(sandbox["root"], "indicators.structure.pre_event_range", "compression_box")
    _write_indicator(sandbox["root"], "indicators.structure.highest_high", "rolling_max")
    _write_indicator(sandbox["root"], "indicators.structure.lowest_low", "rolling_min")
    _write_directive(
        sandbox["prior_dir"], "64_BRK_IDX_5M_NEWSBRK_S04_V1_P00",
        sv=1,
        indicators=["indicators.volatility.atr", "indicators.structure.highest_high", "indicators.structure.lowest_low"],
        symbol="NAS100",
    )
    cur = _write_directive(
        sandbox["inbox"], "64_BRK_IDX_15M_NEWSBRK_S03_V1_P00",
        sv=1,
        indicators=["indicators.volatility.atr", "indicators.structure.pre_event_range"],
        symbol="NAS100",
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS", f"cross-sweep should PASS, got: {v.reason}"
    assert v.prior_directive is None
    assert v.classification == "N/A"


def test_within_sweep_signal_change_still_blocks_without_sv_bump(sandbox):
    """Within the SAME sweep slot, SIGNAL indicator change without sv bump
    must still BLOCK. Within-sweep discipline preserved."""
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur_block = _write_directive(
        sandbox["inbox"], "11_STR_FX_1H_CHOCH_S01_V1_P01",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v = evaluate(
        cur_block,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "BLOCK", f"within-sweep SIGNAL @ same sv must BLOCK, got: {v.reason}"
    assert v.classification == "SIGNAL"
    cur_block.unlink()
    cur_pass = _write_directive(
        sandbox["inbox"], "11_STR_FX_1H_CHOCH_S01_V1_P01",
        sv=2, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v2 = evaluate(
        cur_pass,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v2.verdict == "PASS", f"within-sweep SIGNAL with sv bump should PASS, got: {v2.reason}"


def test_engine_rerun_narrowing_unchanged(sandbox):
    """ENGINE rerun semantics must not regress. Distant-sweep sibling must
    NOT be picked as the prior; same-stem completed copy IS the baseline."""
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S02_V1_P00",
        sv=5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    completed = sandbox["root"] / "completed"
    _write_directive(
        completed, "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1,
        indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    sandbox["inbox"].mkdir(parents=True, exist_ok=True)
    rerun_path = sandbox["inbox"] / "11_STR_FX_1H_CHOCH_S01_V1_P00.txt"
    rerun_path.write_text(
        _DIRECTIVE_TEMPLATE.format(
            name="11_STR_FX_1H_CHOCH_S01_V1_P00",
            sv=1,
            indicators_block="\n".join(
                f"  - {i}" for i in ["indicators.volatility.atr", "indicators.structure.choch"]
            ),
            atr=1.5, desc="engine rerun", symbol="USDJPY",
        ).replace(
            "research_mode: true",
            "research_mode: true\n  repeat_override_reason: \"[RERUN:ENGINE@2026-05-03 origin=test strategy=11_STR_FX_1H_CHOCH_S01_V1_P00] engine v1.5.8a parity\"",
        ),
        encoding="utf-8",
    )
    v = evaluate(
        rerun_path,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"], completed],
    )
    assert v.verdict == "PASS", f"ENGINE rerun against same-stem baseline should PASS, got: {v.reason}"
    assert v.prior_directive == "11_STR_FX_1H_CHOCH_S01_V1_P00"


def test_unstructured_legacy_name_first_of_kind_pass(sandbox):
    """Defensive: directives whose strategy.name doesn't match the structured
    sweep pattern produce empty MODEL_TOKEN, so they never match any prior
    bucket and always return first-of-kind PASS. The new narrowing logic
    must not break this path — it's reached BEFORE narrowing applies."""
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur = _write_directive(
        sandbox["inbox"], "MY_HAND_ROLLED_TEST",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
    )
    assert v.verdict == "PASS", f"unstructured legacy name → first-of-kind PASS, got: {v.reason}"
    assert v.classification == "N/A"
    assert v.prior_directive is None


def test_same_sweep_silent_hash_drift_blocks(sandbox):
    """Highest-risk failure mode: silent internal logic drift in an
    indicator module that doesn't change its import path. Same sweep slot,
    identical imports, identical sv, but prior's recorded aggregate hash
    differs from current — Rule 3 must still BLOCK."""
    _write_directive(
        sandbox["prior_dir"], "11_STR_FX_1H_CHOCH_S01_V1_P00",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    cur = _write_directive(
        sandbox["inbox"], "11_STR_FX_1H_CHOCH_S01_V1_P01",
        sv=1, indicators=["indicators.volatility.atr", "indicators.structure.choch"],
    )
    v = evaluate(
        cur,
        project_root=sandbox["root"],
        search_dirs=[sandbox["prior_dir"]],
        prior_indicators_hash_lookup=lambda _stem: "deadbeef" * 8,
    )
    assert v.verdict == "BLOCK", f"silent indicator-hash drift within same sweep must BLOCK, got: {v.reason}"
    assert v.details.get("indicator_hash_delta_detected") is True, \
        "Rule 3 must fire (indicator_hash_delta_detected=True) on silent drift"


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
