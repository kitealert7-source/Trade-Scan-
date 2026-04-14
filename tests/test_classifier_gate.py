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
