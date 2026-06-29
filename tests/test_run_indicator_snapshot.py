"""Indicator snapshot — every run carries the indicator modules it imports.

A backtest's behavior = strategy.py + directive + the indicator modules the
strategy imports. The pipeline snapshots the first two per run; this captures
the third (indicators_manifest.json + source copies) so a run stays faithfully
reproducible after the live indicators/ registry evolves, and drift fails loud.

Covers: tools/indicator_imports.py (transitive AST scan) and
tools/run_indicator_snapshot.py (manifest + source copies + fail-loud verify).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from tools.indicator_imports import (  # noqa: E402
    extract_imported_indicator_modules,
    module_to_file,
)
from tools.run_indicator_snapshot import (  # noqa: E402
    INDICATOR_MANIFEST_NAME,
    INDICATOR_SNAPSHOT_DIRNAME,
    IndicatorDriftError,
    IndicatorSnapshotError,
    build_indicator_manifest,
    require_indicator_snapshot,
    snapshot_indicators,
    verify_indicator_manifest,
    verify_indicator_snapshot,
)


# ── Hermetic fixture: a tiny indicators/ tree with a transitive dependency ──


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal repo: strategy.py imports alpha; alpha imports beta (transitive).

    Returns (project_root, strategy_py).
    """
    root = tmp_path / "repo"
    ind = root / "indicators" / "cat"
    ind.mkdir(parents=True)
    (root / "indicators" / "__init__.py").write_text("", encoding="utf-8")
    (root / "indicators" / "cat" / "__init__.py").write_text("", encoding="utf-8")

    # beta: leaf, no indicator imports.
    (ind / "beta.py").write_text(
        "def beta(s):\n    return s\n", encoding="utf-8"
    )
    # alpha: imports beta (absolute) -> transitive capture must follow.
    (ind / "alpha.py").write_text(
        "from indicators.cat.beta import beta\n\ndef alpha(s):\n    return beta(s)\n",
        encoding="utf-8",
    )
    # gamma: not imported by the strategy (must NOT be captured).
    (ind / "gamma.py").write_text("def gamma(s):\n    return s\n", encoding="utf-8")

    # registry: alpha registered, beta NOT registered (exercises in_registry).
    (root / "indicators" / "INDICATOR_REGISTRY.yaml").write_text(
        "registry_version: 99\n"
        "indicators:\n"
        "  alpha:\n"
        "    module_path: indicators.cat.alpha\n",
        encoding="utf-8",
    )

    strat_dir = root / "strategies" / "S01"
    strat_dir.mkdir(parents=True)
    strategy_py = strat_dir / "strategy.py"
    strategy_py.write_text(
        "from indicators.cat.alpha import alpha\n"
        "import numpy as np\n\n"
        "class Strategy:\n    name = 'S01'\n",
        encoding="utf-8",
    )
    return root, strategy_py


# ── Scanner: tools/indicator_imports.py ─────────────────────────────────────


def test_scanner_captures_direct_and_transitive(fake_repo):
    root, strategy_py = fake_repo
    mods = extract_imported_indicator_modules(strategy_py, root)
    assert mods == {"indicators.cat.alpha", "indicators.cat.beta"}
    # gamma is never imported — must not appear.
    assert "indicators.cat.gamma" not in mods


def test_scanner_handles_plain_import_form(tmp_path):
    root = tmp_path / "repo"
    (root / "indicators" / "cat").mkdir(parents=True)
    (root / "indicators" / "cat" / "delta.py").write_text("x = 1\n", encoding="utf-8")
    src = tmp_path / "s.py"
    src.write_text("import indicators.cat.delta\n", encoding="utf-8")
    assert extract_imported_indicator_modules(src, root) == {"indicators.cat.delta"}


def test_scanner_handles_from_package_import_submodule(tmp_path):
    root = tmp_path / "repo"
    (root / "indicators" / "cat").mkdir(parents=True)
    (root / "indicators" / "cat" / "eps.py").write_text("x = 1\n", encoding="utf-8")
    src = tmp_path / "s.py"
    # `from indicators.cat import eps` -> submodule indicators.cat.eps resolves.
    src.write_text("from indicators.cat import eps\n", encoding="utf-8")
    assert extract_imported_indicator_modules(src, root) == {"indicators.cat.eps"}


def test_scanner_ignores_non_indicator_and_unresolved(tmp_path):
    root = tmp_path / "repo"
    (root / "indicators").mkdir(parents=True)
    src = tmp_path / "s.py"
    src.write_text(
        "import numpy as np\n"
        "from engines.filter_stack import FilterStack\n"
        "from indicators.cat.ghost import ghost\n",  # not on disk -> skipped
        encoding="utf-8",
    )
    assert extract_imported_indicator_modules(src, root) == set()


def test_scanner_missing_and_unparseable_return_empty(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert extract_imported_indicator_modules(tmp_path / "nope.py", root) == set()
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")  # syntax error
    assert extract_imported_indicator_modules(bad, root) == set()


def test_module_to_file_rejects_package_dir(fake_repo):
    root, _ = fake_repo
    # A package directory must not resolve to a file.
    assert module_to_file("indicators.cat", root) is None
    assert module_to_file("indicators.cat.alpha", root) is not None


# ── Manifest: tools/run_indicator_snapshot.build_indicator_manifest ─────────


def test_manifest_shape_hashes_and_registry(fake_repo):
    root, strategy_py = fake_repo
    m = build_indicator_manifest(strategy_py, root)
    assert m["schema_version"] == 1
    assert m["registry_version"] == 99
    assert m["retro_captured"] is False
    assert m["module_count"] == 2
    by_mod = {e["module"]: e for e in m["modules"]}
    assert set(by_mod) == {"indicators.cat.alpha", "indicators.cat.beta"}
    # alpha registered, beta not.
    assert by_mod["indicators.cat.alpha"]["in_registry"] is True
    assert by_mod["indicators.cat.beta"]["in_registry"] is False
    # hash matches the live file; file path nests under the snapshot dir.
    import hashlib

    live_alpha = (root / "indicators" / "cat" / "alpha.py").read_bytes()
    assert by_mod["indicators.cat.alpha"]["sha256"] == hashlib.sha256(live_alpha).hexdigest()
    assert by_mod["indicators.cat.alpha"]["file"] == (
        f"{INDICATOR_SNAPSHOT_DIRNAME}/indicators/cat/alpha.py"
    )
    # modules are sorted (deterministic manifest).
    assert [e["module"] for e in m["modules"]] == sorted(e["module"] for e in m["modules"])


def test_manifest_retro_flag(fake_repo):
    root, strategy_py = fake_repo
    m = build_indicator_manifest(strategy_py, root, retro_captured=True)
    assert m["retro_captured"] is True


# ── Snapshot writer: manifest file + source copies + write-once ─────────────


def test_snapshot_writes_manifest_and_source_copies(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"

    summary = snapshot_indicators(target, strategy_py, root)
    assert summary["written"] is True
    assert summary["module_count"] == 2

    manifest_path = target / INDICATOR_MANIFEST_NAME
    assert manifest_path.is_file()
    # Source copies landed, byte-identical to the live modules.
    for rel in ("indicators/cat/alpha.py", "indicators/cat/beta.py"):
        copied = target / INDICATOR_SNAPSHOT_DIRNAME / rel
        assert copied.is_file()
        assert copied.read_bytes() == (root / rel).read_bytes()


def test_snapshot_is_write_once(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"
    first = snapshot_indicators(target, strategy_py, root)
    assert first["written"] is True

    # Mutate a live module, then re-snapshot write-once: manifest must NOT change.
    (root / "indicators" / "cat" / "alpha.py").write_text(
        "from indicators.cat.beta import beta\n\ndef alpha(s):\n    return beta(s) + 1\n",
        encoding="utf-8",
    )
    second = snapshot_indicators(target, strategy_py, root)
    assert second["written"] is False
    # Verify still passes against the ORIGINAL snapshot only if we point at the
    # original source — here the manifest is unchanged, proving write-once.
    manifest = json.loads((target / INDICATOR_MANIFEST_NAME).read_text(encoding="utf-8"))
    import hashlib

    # The stored hash is the pre-mutation hash (write-once preserved it).
    orig_alpha_now = (root / "indicators" / "cat" / "alpha.py").read_bytes()
    stored = {e["module"]: e["sha256"] for e in manifest["modules"]}
    assert stored["indicators.cat.alpha"] != hashlib.sha256(orig_alpha_now).hexdigest()


def test_snapshot_refresh_when_not_write_once(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "strategies" / "S01"
    snapshot_indicators(target, strategy_py, root, write_once=False)
    (root / "indicators" / "cat" / "alpha.py").write_text(
        "from indicators.cat.beta import beta\n\ndef alpha(s):\n    return beta(s) + 2\n",
        encoding="utf-8",
    )
    refreshed = snapshot_indicators(target, strategy_py, root, write_once=False)
    assert refreshed["written"] is True
    # The refreshed snapshot now verifies clean against live.
    assert verify_indicator_snapshot(target, root)["verified"] is True


def test_snapshot_missing_source_returns_none(fake_repo, tmp_path):
    root, _ = fake_repo
    assert snapshot_indicators(tmp_path / "t", tmp_path / "nope.py", root) is None


# ── require_*: fail-loud enforcement ────────────────────────────────────────


def test_require_succeeds_then_raises_when_missing(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"
    snap = require_indicator_snapshot(target, strategy_py, root)
    assert snap["module_count"] == 2
    assert (target / INDICATOR_MANIFEST_NAME).is_file()

    with pytest.raises(IndicatorSnapshotError):
        require_indicator_snapshot(target, tmp_path / "does_not_exist.py", root)
    with pytest.raises(IndicatorSnapshotError):
        require_indicator_snapshot(target, None, root)


# ── verify: the fail-loud drift contract ────────────────────────────────────


def test_verify_passes_when_clean(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"
    snapshot_indicators(target, strategy_py, root)
    summary = verify_indicator_snapshot(target, root)
    assert summary["verified"] is True
    assert summary["module_count"] == 2
    assert summary["registry_version"] == 99


def test_verify_fails_loud_on_hash_drift(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"
    snapshot_indicators(target, strategy_py, root)

    # A live indicator changes its logic AFTER the snapshot — the core scenario.
    (root / "indicators" / "cat" / "beta.py").write_text(
        "def beta(s):\n    return s * -1  # silently changed!\n", encoding="utf-8"
    )
    with pytest.raises(IndicatorDriftError) as exc:
        verify_indicator_snapshot(target, root)
    assert "indicators.cat.beta" in str(exc.value)
    assert "HASH DRIFT" in str(exc.value)


def test_verify_fails_loud_on_deleted_module(fake_repo, tmp_path):
    root, strategy_py = fake_repo
    target = tmp_path / "runs" / "RUN1"
    snapshot_indicators(target, strategy_py, root)
    (root / "indicators" / "cat" / "alpha.py").unlink()
    with pytest.raises(IndicatorDriftError) as exc:
        verify_indicator_snapshot(target, root)
    assert "MISSING live module" in str(exc.value)


def test_verify_raises_when_manifest_absent(tmp_path):
    with pytest.raises(IndicatorDriftError):
        verify_indicator_snapshot(tmp_path, tmp_path)


def test_verify_manifest_returns_error_list_for_contract_hook(fake_repo, tmp_path):
    # Non-raising list[str] form consumed by replay_admission.contract's
    # verify_indicator_provenance hook (empty == clean, non-empty == drift).
    root, strategy_py = fake_repo
    manifest = build_indicator_manifest(strategy_py, root)
    assert verify_indicator_manifest(manifest, root) == []
    (root / "indicators" / "cat" / "beta.py").write_text("def beta(s):\n    return 0\n", encoding="utf-8")
    errs = verify_indicator_manifest(manifest, root)
    assert len(errs) == 1 and "indicators.cat.beta" in errs[0]


# ── Real-repo smoke: the scanner works on an actual provisioned strategy ─────


_SAMPLE_STRATEGY = (
    REPO_ROOT
    / "strategies"
    / "22_CONT_FX_15M_RSIAVG_TRENDFILT_S07_V1_P01_GBPUSD"
    / "strategy.py"
)


def test_real_strategy_smoke():
    if not _SAMPLE_STRATEGY.is_file():
        pytest.skip("sample strategy not present in this checkout")
    mods = extract_imported_indicator_modules(_SAMPLE_STRATEGY, REPO_ROOT)
    assert "indicators.momentum.rsi" in mods
    assert "indicators.volatility.atr" in mods


# ── Integration: the provisioner's real indicator co-location helper ─────────


def test_provisioner_colocate_indicators_real_strategy(tmp_path):
    import shutil

    from tools.strategy_provisioner import _colocate_indicators_with_strategy

    if not _SAMPLE_STRATEGY.is_file():
        pytest.skip("sample strategy not present in this checkout")
    sdir = tmp_path / "S01"
    sdir.mkdir()
    shutil.copy2(_SAMPLE_STRATEGY, sdir / "strategy.py")

    _colocate_indicators_with_strategy(sdir, sdir / "strategy.py")

    manifest = json.loads((sdir / INDICATOR_MANIFEST_NAME).read_text(encoding="utf-8"))
    mods = {e["module"] for e in manifest["modules"]}
    assert "indicators.momentum.rsi" in mods
    assert "indicators.volatility.atr" in mods
    # The freshly-written snapshot verifies clean against the live tree.
    assert verify_indicator_snapshot(sdir, REPO_ROOT)["verified"] is True


# ── Wiring guards: the mandatory snapshot calls stay wired into the pipeline ──
# Cheap source-scan regression guards (cf. the warmup-block invariant test):
# a full provision/stage-1 run needs the untracked directive corpus + engine, so
# we lock the call sites in place rather than re-run the pipeline (out of scope).


def test_run_stage1_wires_indicator_snapshot():
    src = (REPO_ROOT / "tools" / "run_stage1.py").read_text(encoding="utf-8")
    assert "from tools.run_indicator_snapshot import require_indicator_snapshot" in src
    assert "require_indicator_snapshot(target_dir, snapshot_file, PROJECT_ROOT)" in src


def test_provisioner_wires_indicator_snapshot():
    src = (REPO_ROOT / "tools" / "strategy_provisioner.py").read_text(encoding="utf-8")
    assert "_colocate_indicators_with_strategy(strategy_dir, strategy_file)" in src
    # Wired in BOTH provision branches (create + update).
    assert src.count("_colocate_indicators_with_strategy(strategy_dir, strategy_file)") == 2


# ── Basket path: capsule snapshots indicators imported by the recycle rule ───


def test_basket_capsule_indicator_snapshot_real_rule(tmp_path):
    rule = REPO_ROOT / "tools" / "recycle_rules" / "pine_ratio_zrev_v1_zcross_hflm.py"
    if not rule.is_file():
        pytest.skip("recycle rule not present in this checkout")
    out = tmp_path / "capsule"
    out.mkdir()
    summary = snapshot_indicators(out, rule, REPO_ROOT, write_once=False)
    assert summary["module_count"] >= 1
    manifest = json.loads((out / INDICATOR_MANIFEST_NAME).read_text(encoding="utf-8"))
    mods = {e["module"] for e in manifest["modules"]}
    assert "indicators.trend.hurst_rs" in mods
    assert verify_indicator_snapshot(out, REPO_ROOT)["verified"] is True


def test_basket_report_wires_indicator_snapshot():
    src = (REPO_ROOT / "tools" / "basket_report.py").read_text(encoding="utf-8")
    assert "from tools.run_indicator_snapshot import snapshot_indicators" in src
    assert "indicators_manifest.json" in src
