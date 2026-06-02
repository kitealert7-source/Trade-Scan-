"""Single source of truth for run-manifest artifact verification.

A run's ``manifest.json`` records an ``artifacts`` map of
``{relative_name: sha256}``. Verifying those declared hashes against the
on-disk files happens in two independent callers:

  * ``run_pipeline.verify_manifest_integrity`` — the pipeline STARTUP GATE
    (fail-CLOSED: raises ``PipelineAdmissionPause`` on any problem so corrupt
    data cannot propagate);
  * ``system_preflight.PreflightCheck._check_runs`` — the standalone
    DIAGNOSTIC (counts failures and reports RUNS RED/GREEN).

Historically each caller INLINED the verification loop. When PR #1
(commit ``3f9dc9e``, basket per-run code snapshot) split the artifact
contract, the fix was ported to the gate but NOT to the diagnostic — so
preflight false-RED'd 2962 healthy basket runs ("failed manifest hash
verification") while the real pipeline passed them. That is instance #6 of
the recurring mechanism-port gap (auto-memory ``feedback_mechanism_port_check``).

This module collapses the per-artifact loop into ONE place so the two callers
can never disagree on the contract again. Both import ``verify_run_artifacts``.

THE CONTRACT — two splits, applied per artifact entry:
  * PATH BASIS — ``basket_code/*`` snapshots live at the run-folder ROOT
    (``runs/<rid>/basket_code/...``); every other artifact lives under
    ``data/`` (``runs/<rid>/data/<name>``).
  * HASH BASIS — ``basket_code/*`` entries record LF-canonical sha256
    (``basket_provenance`` uses ``canonical_sha256`` so the recorded hash is
    stable across OS line-end rendering / git ``core.autocrlf``); all other
    artifacts are raw binary files (CSV, parquet) where raw byte sha256 is
    correct and line-end normalization would be unsafe.

Regression tests:
  * ``tests/test_manifest_verification.py``          — this module (unit, front line)
  * ``tests/test_manifest_integrity_basket_path.py`` — the gate (integration)
  * ``tests/test_preflight_basket_manifest_path.py`` — the diagnostic (integration)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_BASKET_CODE_PREFIX = "basket_code/"


def artifact_path(run_folder: Path, name: str) -> Path:
    """Resolve a manifest artifact key to its on-disk path (PATH BASIS)."""
    if name.startswith(_BASKET_CODE_PREFIX):
        return run_folder / name
    return run_folder / "data" / name


def artifact_hash(path: Path, name: str) -> str:
    """Hash an on-disk artifact per its contract (HASH BASIS).

    ``basket_code/*`` → LF-canonical sha256 (matches ``basket_provenance.py``);
    everything else → raw byte sha256. Returns a lowercase hex digest.
    """
    if name.startswith(_BASKET_CODE_PREFIX):
        # Local import: keeps verify_engine_integrity's heavy transitive deps
        # (pandas, engine-version resolution at module load) off this module's
        # import path, so a lightweight caller (system_preflight) stays cheap.
        from tools.verify_engine_integrity import canonical_sha256
        return canonical_sha256(path).lower()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run_artifacts(run_folder: Path, artifacts: dict) -> list[str]:
    """Verify a run's declared artifacts against the on-disk files.

    Parameters
    ----------
    run_folder:
        The ``runs/<rid>`` directory.
    artifacts:
        The manifest's ``artifacts`` map (``{name: expected_sha256}``).

    Returns
    -------
    list[str]
        Human-readable problem descriptions WITHOUT a run-id prefix — one per
        missing-or-mismatched artifact (all are collected; the function does
        not stop at the first). An empty list means every declared artifact is
        present and hash-matched. Callers add their own run context and decide
        policy (raise vs. count vs. report).
    """
    problems: list[str] = []
    for name, expected in artifacts.items():
        path = artifact_path(run_folder, name)
        if not path.exists():
            problems.append(f"Missing artifact {name}")
            continue
        if artifact_hash(path, name) != expected:
            problems.append(f"Hash mismatch for {name}")
    return problems
