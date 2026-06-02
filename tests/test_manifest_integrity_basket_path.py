"""Guard the basket-vs-single-strategy artifact contract in
`verify_manifest_integrity`.

Regression for the 2026-06-02 PR #1 (commit `3f9dc9e`, "basket: per-run
code snapshot") that introduced TWO contract splits the pre-existing
startup integrity checker did not honor:

  * **Path basis** — `basket_code/...` entries live at run_folder root
    (``runs/<rid>/basket_code/...``); single-strategy entries (e.g.
    ``results_tradelevel.csv``) live under ``data/``. Pre-fix the checker
    resolved everything under ``data/`` and reported the basket_code/*
    entries Missing.
  * **Hash basis** — `basket_code/*` entries record canonical (LF-normalized)
    sha256 (basket_provenance uses ``canonical_sha256`` for cross-OS
    stability under git ``core.autocrlf``); ``data/*`` entries are raw
    binary artifacts (CSV, parquet) where raw byte sha256 is correct.
    Pre-fix the checker used raw sha256 for everything, so on a Windows
    checkout where the snapshot on disk has CRLF (preserved by
    ``shutil.copy2``) the raw hash mismatches the declared LF-canonical
    hash. Both bugs land on the same startup gate: first invocation reports
    Missing, post-path-fix it reports Hash mismatch — and the gate fatals
    every subsequent run after the first basket run. They must be resolved
    together.

The contract this test locks in:

  * Single-strategy artifacts (e.g. ``results_tradelevel.csv``) → resolved
    under ``data/``, hashed raw bytes.
  * Basket snapshot artifacts (``basket_code/*``) → resolved at run_folder
    root, hashed LF-canonical (matches ``basket_provenance.py``).

Tests cover happy paths for both modes (separately and combined), the
CRLF-on-disk-with-LF-hash live regression case (the bug the pilot caught),
the missing-file and hash-mismatch failure paths for basket_code/ (the
fix must NOT silently swallow real failures), and symmetric coverage for
the data/ contract (single-strategy missing-file still fatals).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# `tools/run_pipeline.py` is a script, not a package module — load it via
# importlib (same pattern as ``test_manifest_hash_guard.py``).
_spec = importlib.util.spec_from_file_location(
    "run_pipeline_mod",
    PROJECT_ROOT / "tools" / "run_pipeline.py",
)
_run_pipeline = importlib.util.module_from_spec(_spec)
sys.modules["run_pipeline_mod"] = _run_pipeline
_spec.loader.exec_module(_run_pipeline)

verify_manifest_integrity = _run_pipeline.verify_manifest_integrity
PipelineAdmissionPause = _run_pipeline.PipelineAdmissionPause


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write(p: Path, body: bytes) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return _sha256(body)


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    """Temporary runs/ tree with module-level ``RUNS_DIR`` swapped in."""
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(_run_pipeline, "RUNS_DIR", runs)
    return runs


def _seed_run(runs_root: Path, rid: str, *, artifacts: dict[str, bytes],
              basket_code_files: dict[str, bytes] | None = None,
              corrupt: str | None = None) -> Path:
    """Build runs/<rid>/ with a manifest + the data/ + basket_code/ files.

    ``artifacts`` -> non-basket-code files (relative paths get written under
    ``data/`` to match the single-strategy contract).
    ``basket_code_files`` -> entries written under run_folder/basket_code/.
    ``corrupt`` -> when set to one of the manifest keys, overwrite that file
    with tampered bytes AFTER hashing for the manifest, so a hash mismatch
    surfaces.
    """
    run_dir = runs_root / rid
    run_dir.mkdir()
    declared: dict[str, str] = {}

    for rel, body in artifacts.items():
        h = _write(run_dir / "data" / rel, body)
        declared[rel] = h

    for rel, body in (basket_code_files or {}).items():
        h = _write(run_dir / "basket_code" / rel, body)
        declared[f"basket_code/{rel}"] = h

    if corrupt is not None:
        # Tamper post-hash so verify sees a mismatch, not "missing".
        if corrupt.startswith("basket_code/"):
            (run_dir / corrupt).write_bytes(b"TAMPERED")
        else:
            (run_dir / "data" / corrupt).write_bytes(b"TAMPERED")

    manifest = {
        "run_id": rid,
        "artifacts": declared,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return run_dir


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_single_strategy_artifact_under_data_passes(runs_root):
    """Pre-PR-#1 contract: ``results_tradelevel.csv`` lives under ``data/``."""
    _seed_run(runs_root, "single_run_0001",
              artifacts={"results_tradelevel.csv": b"a,b\n1,2\n"})
    # No raise = pass.
    verify_manifest_integrity(PROJECT_ROOT)


def test_basket_code_artifact_at_run_root_passes(runs_root):
    """PR #1 contract: ``basket_code/*`` lives at run_folder root, NOT data/.

    This is the exact case that fataled the 2026-06-02 pilot's second
    startup. Pre-fix the integrity checker resolved the basket_code/*
    manifest entries under data/ and reported them missing; post-fix it
    resolves them at run_folder root and they're found.
    """
    _seed_run(
        runs_root, "basket_run_0001",
        artifacts={"results_tradelevel.csv": b"a,b\n1,2\n"},
        basket_code_files={
            "recycle_rules/pine_ratio_zrev_v1.py": b"# rule v1\n",
            "recycle_strategies.py": b"# strategies\n",
        },
    )
    verify_manifest_integrity(PROJECT_ROOT)


def test_both_modes_coexist_passes(runs_root):
    """A runs/ tree containing both a single-strategy run and a basket run
    must pass cleanly — the contract split is per-entry, not per-run."""
    _seed_run(runs_root, "single_run_0002",
              artifacts={"results_tradelevel.csv": b"x\n"})
    _seed_run(
        runs_root, "basket_run_0002",
        artifacts={"results_tradelevel.csv": b"y\n"},
        basket_code_files={"recycle_strategies.py": b"# bs\n"},
    )
    verify_manifest_integrity(PROJECT_ROOT)


def test_basket_code_crlf_on_disk_matches_lf_canonical_hash(runs_root):
    """The exact live regression the 2026-06-02 pilot surfaced on Windows.

    ``basket_provenance.snapshot_basket_code`` records the LF-canonical
    sha256 of each source file but writes the on-disk snapshot via
    ``shutil.copy2`` — a byte-exact copy. On a Windows git checkout with
    ``core.autocrlf=true`` the source (and hence the snapshot) carries
    CRLF line endings, so the raw byte sha256 of the on-disk file does
    NOT equal the LF-canonical hash in the manifest. Pre-fix the
    integrity checker raw-hashed everything and reported "Hash mismatch"
    on every basket run after the first one. Post-fix it LF-normalizes
    basket_code/* entries before hashing and matches cleanly.
    """
    import hashlib as _h
    # CRLF on-disk body; LF-canonical hash in manifest — mismatch case.
    crlf_body = b"line1\r\nline2\r\nline3\r\n"
    lf_canon_hash = _h.sha256(b"line1\nline2\nline3\n").hexdigest()
    raw_hash = _h.sha256(crlf_body).hexdigest()
    assert raw_hash != lf_canon_hash, "test premise"

    rid = "basket_run_crlf"
    run_dir = runs_root / rid
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "data" / "results_tradelevel.csv").write_bytes(b"x\n")
    (run_dir / "basket_code" / "recycle_rules").mkdir(parents=True)
    (run_dir / "basket_code" / "recycle_rules" / "rule.py").write_bytes(crlf_body)
    manifest = {
        "run_id": rid,
        "artifacts": {
            "results_tradelevel.csv": _h.sha256(b"x\n").hexdigest(),
            "basket_code/recycle_rules/rule.py": lf_canon_hash,
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    # Post-fix: must pass. Pre-fix: would have fataled with Hash mismatch.
    verify_manifest_integrity(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Failure paths — the fix must NOT swallow real integrity failures
# ---------------------------------------------------------------------------


def test_missing_basket_code_file_still_fatals(runs_root):
    """If the basket_code/* file truly is absent on disk, the gate must
    still fatal. Otherwise the path-split fix would silently accept any
    basket-snapshot drift."""
    run_dir = _seed_run(
        runs_root, "basket_run_0003",
        artifacts={"results_tradelevel.csv": b"x\n"},
        basket_code_files={"recycle_strategies.py": b"# bs\n"},
    )
    # Remove the file after the manifest was written.
    (run_dir / "basket_code" / "recycle_strategies.py").unlink()
    with pytest.raises(PipelineAdmissionPause):
        verify_manifest_integrity(PROJECT_ROOT)


def test_basket_code_hash_mismatch_still_fatals(runs_root):
    """Content drift on a basket_code/* file must surface as a hash mismatch,
    not be silently accepted by the new path-split branch."""
    _seed_run(
        runs_root, "basket_run_0004",
        artifacts={"results_tradelevel.csv": b"x\n"},
        basket_code_files={"recycle_strategies.py": b"# bs\n"},
        corrupt="basket_code/recycle_strategies.py",
    )
    with pytest.raises(PipelineAdmissionPause):
        verify_manifest_integrity(PROJECT_ROOT)


def test_missing_single_strategy_file_still_fatals(runs_root):
    """Regression-guard symmetry: the data/ path must still fatal on missing.
    Prevents a future refactor from moving the basket logic up far enough to
    accidentally drop the data/ check."""
    run_dir = _seed_run(runs_root, "single_run_0003",
                        artifacts={"results_tradelevel.csv": b"x\n"})
    (run_dir / "data" / "results_tradelevel.csv").unlink()
    with pytest.raises(PipelineAdmissionPause):
        verify_manifest_integrity(PROJECT_ROOT)


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
