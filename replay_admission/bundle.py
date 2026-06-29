"""Replay Admission — ExperimentBundle (Phase 1, read-only).

The immutable unit Replay Admission consumes. A (single-asset) bundle is a directory —
a `runs/<run_id>/` folder, or a hand-assembled dir — holding:

    strategy.py               REQUIRED — the compiled authority
    experiment.json           OPTIONAL — Phase 4 emits it on every run; until then the
                              experiment definition is recovered from directive.txt / CLI
    indicators_manifest.json  present on post-2026-06-29 runs (forward-path snapshotting);
    indicators_snapshot/        ABSENT on legacy/pre-snapshot runs (backfill descoped)
    directive.txt             OPTIONAL — provenance + experiment-config recovery source

Basket bundles (the `backtests/<dir>/` capsule + `RECYCLE_RULE_SOURCE.py`) execute through
the basket dispatch route, NOT `StageRunner` — out of v1 scope (Replay v1 = single-asset /
StageRunner). See `governance/SOP/EXECUTION_CAPSULE_CONTRACT.md` for the capsule layout.

Read-only: this module locates members + composes the Phase-0 Admission Contract
(`replay_admission.contract`). No writes, no `PipelineStateManager`, no pipeline coupling
(that is Phase 2). Design: REPLAY_ADMISSION_DESIGN_2026-06-29.md (FROZEN v1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from replay_admission.contract import ContractResult, REPO_ROOT, verify_experiment

_STRATEGY = "strategy.py"
_EXPERIMENT = "experiment.json"
_DIRECTIVE = "directive.txt"
_MANIFEST = "indicators_manifest.json"
_SNAPSHOT_DIR = "indicators_snapshot"


@dataclass
class ExperimentBundle:
    """Located members of a replayable bundle. `strategy_py` is the only guaranteed member;
    the rest are present-or-None depending on the bundle's vintage/source."""
    root: Path
    strategy_py: Path
    experiment_json: Optional[Path] = None
    indicators_manifest: Optional[Path] = None
    indicators_snapshot_dir: Optional[Path] = None
    directive_txt: Optional[Path] = None

    @property
    def has_indicator_provenance(self) -> bool:
        return self.indicators_manifest is not None


def is_bundle(path) -> bool:
    """True if `path` is a directory replayable as a single-asset bundle: it has
    `strategy.py` AND at least one experiment-definition source on disk (`experiment.json`
    or `directive.txt`). (Explicit CLI args are a replay-time fallback, not a property of
    the directory, so they don't make a bare strategy.py dir a 'bundle'.)"""
    p = Path(path)
    if not (p / _STRATEGY).is_file():
        return False
    return (p / _EXPERIMENT).is_file() or (p / _DIRECTIVE).is_file()


def load_bundle(path) -> ExperimentBundle:
    """Locate the bundle members under `path`. Requires `strategy.py`; all else optional."""
    p = Path(path)
    sp = p / _STRATEGY
    if not sp.is_file():
        raise FileNotFoundError(f"not a bundle: no {_STRATEGY} in {p}")

    def _opt(name: str) -> Optional[Path]:
        f = p / name
        return f if f.is_file() else None

    snap = p / _SNAPSHOT_DIR
    return ExperimentBundle(
        root=p,
        strategy_py=sp,
        experiment_json=_opt(_EXPERIMENT),
        indicators_manifest=_opt(_MANIFEST),
        indicators_snapshot_dir=snap if snap.is_dir() else None,
        directive_txt=_opt(_DIRECTIVE),
    )


def experiment_from_directive(directive_path) -> Optional[dict]:
    """Recover an experiment-config dict from a directive's YAML (symbols + test block).

    Used as the 'recovered' source when a bundle has `directive.txt` but no `experiment.json`
    (the common legacy run-folder shape). This READS the directive for its provenance fields
    (symbols / window / broker / timeframe) — it does NOT execute, canonicalize, or provision
    it. Returns None if the file is missing/unparseable."""
    p = Path(directive_path)
    if not p.is_file():
        return None
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    test = data.get("test") or {}
    if not isinstance(test, dict):
        test = {}
    return {
        "symbols": data.get("symbols") or test.get("symbols") or [],
        "broker": test.get("broker") or data.get("broker"),
        "timeframe": test.get("timeframe") or data.get("timeframe"),
        "start_date": test.get("start_date") or data.get("start_date"),
        "end_date": test.get("end_date") or data.get("end_date"),
    }


def verify_bundle(bundle, *, cli=None, recovered=None, repo_root=REPO_ROOT) -> ContractResult:
    """Run the Phase-0 Admission Contract over a bundle (path or `ExperimentBundle`).

    Resolves the experiment definition in order — `experiment.json` → explicit `cli` →
    `recovered` (auto-derived from `directive.txt` when present and nothing else was given) —
    and, when the bundle carries an `indicators_manifest.json`, verifies the live indicators
    against it (fail-loud on drift, via the chip's `verify_indicator_manifest`). When the
    manifest is ABSENT (legacy / pre-snapshot bundle), records a WARNING — the replay would
    run against CURRENT indicators, unverified — rather than blocking."""
    if isinstance(bundle, (str, Path)):
        bundle = load_bundle(bundle)

    # Auto-recover the experiment-config from the directive only if nothing better was given.
    if bundle.experiment_json is None and cli is None and recovered is None and bundle.directive_txt:
        recovered = experiment_from_directive(bundle.directive_txt)

    manifest = None
    if bundle.indicators_manifest is not None:
        manifest = json.loads(bundle.indicators_manifest.read_text(encoding="utf-8"))

    res = verify_experiment(
        bundle.root,
        experiment_json=bundle.experiment_json,
        cli=cli,
        recovered=recovered,
        indicator_manifest=manifest,
        repo_root=repo_root,
    )

    if manifest is None:
        res.warnings.append(
            "indicator provenance absent (legacy / pre-snapshot bundle) — replay would run "
            "against CURRENT indicators, unverified"
        )
    return res
