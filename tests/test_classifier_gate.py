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


def test_engine_rerun_returns_first_of_kind_when_no_same_identity_prior(sandbox):
    """ENGINE rerun contract (per classifier_gate.py:265-274 comment block):
    when narrowing to same-identity (family/TF/sweep) priors yields an empty
    set, the gate intentionally does NOT fall back to the wide (MODEL,
    ASSET_CLASS) match. Comparing an ENGINE rerun against a structurally
    different prior would surface diffs that predate and are irrelevant to
    the engine-only change, producing UNCLASSIFIABLE noise that gates a
    legitimate rerun.

    Conservative correct response: treat as first-of-kind PASS. The engine
    integrity tool already protects byte-equivalence at the engine level;
    cross-structure classifier comparison is not the right tool for that.

    Contract was changed deliberately during admission stabilization
    (commit 153c027) — the prior wide-fallback behavior surfaced false
    positives on engine reruns. This test now asserts the new contract.
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
    # No same-identity (30M/S02) prior exists in search_dirs (only 15M/S01
    # is seeded). Per the new contract, the gate does NOT fall back to wide;
    # it returns first-of-kind PASS with no prior baseline.
    assert v.verdict == "PASS"
    assert v.prior_directive is None, (
        f"Expected first-of-kind PASS (prior=None) per the new ENGINE-rerun "
        f"contract, got prior_directive={v.prior_directive!r}. If the "
        f"contract was reverted to wide-fallback, see classifier_gate.py "
        f"lines 265-274 — the comment block there explains why fallback "
        f"was disabled and must be revisited together with this test."
    )
    assert "first-of-kind" in v.reason.lower()


def test_engine_rerun_narrowing_disabled_without_override_reason(sandbox):
    """Sanity check: the narrowing path must NOT activate for directives
    that carry no ENGINE override reason. A structurally-distant prior
    with a SIGNAL-level indicator diff must still be selected (and block)
    as before. Ensures the new code path is opt-in via override reason.
    """
    _write_directive(
        sandbox["prior_dir"], "22_CONT_FX_15M_CHOCH_S01_V1_P05",
        sv=1, atr=1.5,
        indicators=["indicators.volatility.atr", "indicators.structure.choch_v2"],
    )
    # No override reason on current directive.
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
    # No narrowing → wide 15M/S01 prior picked → SIGNAL diff → BLOCK on SV.
    assert v.verdict == "BLOCK"
    assert v.classification == "SIGNAL"
    assert v.prior_directive == "22_CONT_FX_15M_CHOCH_S01_V1_P05"


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


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
