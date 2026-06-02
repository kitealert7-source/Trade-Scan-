"""Guard the basket-vs-single-strategy artifact contract in
``system_preflight.PreflightCheck._check_runs``.

Sibling of ``test_manifest_integrity_basket_path.py`` (which locks the same
contract on the *authoritative* startup gate ``run_pipeline.
verify_manifest_integrity``). PR #1 (commit ``3f9dc9e``, "basket: per-run
code snapshot") fixed the gate + added that test, but did NOT port the fix
to the standalone preflight diagnostic — so ``_check_runs`` kept the
pre-PR-#1 logic and false-RED'd 2962 healthy runs ("N runs failed manifest
hash verification") while the real pipeline passed them. This test is the
missing other half of that mechanism port.

The contract (identical to the authoritative gate):
  * Single-strategy artifacts (e.g. ``results_tradelevel.csv``) → resolved
    under ``data/``, hashed raw bytes.
  * Basket snapshot artifacts (``basket_code/*``) → resolved at run_folder
    root, hashed LF-canonical (matches ``basket_provenance.py``).

Coverage: happy paths for both modes (separately + combined), the
CRLF-on-disk-with-LF-canonical-hash Windows regression, and the
missing-file / hash-mismatch failure paths for BOTH bases — the path-split
must not silently swallow real corruption.

NOTE: ``_check_runs`` skips any run dir whose name contains ``_`` (reserved
for non-canonical containers), so every test run-id here is underscore-free.
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

# `tools/system_preflight.py` is a script, not a package module — load it via
# importlib (same pattern as ``test_manifest_integrity_basket_path.py``).
_spec = importlib.util.spec_from_file_location(
    "system_preflight_mod",
    PROJECT_ROOT / "tools" / "system_preflight.py",
)
_preflight = importlib.util.module_from_spec(_spec)
sys.modules["system_preflight_mod"] = _preflight
_spec.loader.exec_module(_preflight)

PreflightCheck = _preflight.PreflightCheck

# The manifest writer hashes basket_code/* with canonical (LF-normalized)
# sha256; use the same function to declare expected hashes so the test
# reflects the real contract rather than assuming canonical == raw.
from tools.verify_engine_integrity import canonical_sha256  # noqa: E402


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write(p: Path, body: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    """Temporary runs/ tree with module-level ``RUNS_DIR`` swapped in."""
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(_preflight, "RUNS_DIR", runs)
    return runs


def _seed_run(runs_root: Path, rid: str, *, artifacts: dict[str, bytes],
              basket_code_files: dict[str, bytes] | None = None,
              corrupt: str | None = None,
              drop: str | None = None) -> Path:
    """Build runs/<rid>/ with data/ + basket_code/ + manifest.json + run_state.

    ``artifacts``           → files written under ``data/`` (single-strategy).
    ``basket_code_files``   → files written under ``basket_code/`` (run root);
                              declared hash uses canonical_sha256 to match the
                              real manifest writer.
    ``corrupt``             → manifest key whose on-disk file is overwritten
                              with tampered bytes AFTER hashing (hash mismatch).
    ``drop``                → manifest key whose on-disk file is deleted AFTER
                              the manifest is written (missing artifact).
    """
    run_dir = runs_root / rid
    run_dir.mkdir()
    # data/ must exist for the Step-2 RUN_INCOMPLETE check to pass even when
    # `artifacts` is empty.
    (run_dir / "data").mkdir(exist_ok=True)
    declared: dict[str, str] = {}

    for rel, body in artifacts.items():
        _write(run_dir / "data" / rel, body)
        declared[rel] = _sha256(body)

    for rel, body in (basket_code_files or {}).items():
        path = run_dir / "basket_code" / rel
        _write(path, body)
        declared[f"basket_code/{rel}"] = canonical_sha256(path).lower()

    if corrupt is not None:
        target = (run_dir / corrupt if corrupt.startswith("basket_code/")
                  else run_dir / "data" / corrupt)
        target.write_bytes(b"TAMPERED")

    if drop is not None:
        target = (run_dir / drop if drop.startswith("basket_code/")
                  else run_dir / "data" / drop)
        target.unlink()

    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": rid, "artifacts": declared}, indent=2),
        encoding="utf-8",
    )
    (run_dir / "run_state.json").write_text(
        json.dumps({"run_id": rid, "status": "COMPLETE"}), encoding="utf-8"
    )
    return run_dir


def _runs_status(pc: PreflightCheck) -> str:
    """Single RUNS status emitted by ``_check_runs`` (GREEN/RED)."""
    runs = pc.results.get("RUNS", [])
    assert runs, "RUNS check emitted no report"
    return runs[0][0]


def _runs_msg(pc: PreflightCheck) -> str:
    return pc.results.get("RUNS", [("", "")])[0][1]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_single_strategy_artifact_under_data_passes(runs_root):
    """Pre-PR-#1 contract: ``results_tradelevel.csv`` lives under ``data/``."""
    _seed_run(runs_root, "single0001",
              artifacts={"results_tradelevel.csv": b"a,b\n1,2\n"})
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "GREEN"


def test_basket_code_artifact_at_run_root_passes(runs_root):
    """PR #1 contract: ``basket_code/*`` lives at run_folder root, NOT data/.

    The exact 2962-run false-RED this fix resolves: pre-fix preflight
    resolved basket_code/* under data/ and counted every basket run corrupt.
    """
    _seed_run(
        runs_root, "basket0001",
        artifacts={"results_tradelevel.csv": b"a,b\n1,2\n"},
        basket_code_files={
            "recycle_rules/pine_ratio_zrev_v1.py": b"# rule v1\n",
            "recycle_strategies.py": b"# strategies\n",
        },
    )
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "GREEN", _runs_msg(pc)


def test_both_modes_coexist_passes(runs_root):
    """A runs/ tree with both a single-strategy and a basket run must pass —
    the contract split is per-entry, not per-run."""
    _seed_run(runs_root, "single0002",
              artifacts={"results_tradelevel.csv": b"x\n"})
    _seed_run(runs_root, "basket0002",
              artifacts={"results_tradelevel.csv": b"y\n"},
              basket_code_files={"recycle_strategies.py": b"# bs\n"})
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "GREEN", _runs_msg(pc)


def test_basket_code_crlf_on_disk_matches_lf_canonical_hash(runs_root):
    """The live Windows regression: CRLF snapshot on disk, LF-canonical hash
    in manifest. Pre-fix preflight raw-hashed it and reported corrupt; post-fix
    it canonicalizes basket_code/* before hashing and matches cleanly."""
    crlf_body = b"line1\r\nline2\r\nline3\r\n"
    lf_canon_hash = _sha256(b"line1\nline2\nline3\n")
    assert _sha256(crlf_body) != lf_canon_hash, "test premise"

    rid = "basketcrlf"
    run_dir = runs_root / rid
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "data" / "results_tradelevel.csv").write_bytes(b"x\n")
    _write(run_dir / "basket_code" / "recycle_rules" / "rule.py", crlf_body)
    (run_dir / "manifest.json").write_text(
        json.dumps({
            "run_id": rid,
            "artifacts": {
                "results_tradelevel.csv": _sha256(b"x\n"),
                "basket_code/recycle_rules/rule.py": lf_canon_hash,
            },
        }, indent=2),
        encoding="utf-8",
    )
    (run_dir / "run_state.json").write_text("{}", encoding="utf-8")
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "GREEN", _runs_msg(pc)


# ---------------------------------------------------------------------------
# Failure paths — the fix must NOT swallow real corruption
# ---------------------------------------------------------------------------


def test_missing_basket_code_file_is_red(runs_root):
    """A truly-absent basket_code/* file must still count corrupt → RED."""
    _seed_run(runs_root, "basket0003",
              artifacts={"results_tradelevel.csv": b"x\n"},
              basket_code_files={"recycle_strategies.py": b"# bs\n"},
              drop="basket_code/recycle_strategies.py")
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "RED"
    assert "manifest hash verification" in _runs_msg(pc)


def test_basket_code_hash_mismatch_is_red(runs_root):
    """Content drift on a basket_code/* file must surface as corrupt → RED,
    not be silently accepted by the new path-split branch."""
    _seed_run(runs_root, "basket0004",
              artifacts={"results_tradelevel.csv": b"x\n"},
              basket_code_files={"recycle_strategies.py": b"# bs\n"},
              corrupt="basket_code/recycle_strategies.py")
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "RED"
    assert "manifest hash verification" in _runs_msg(pc)


def test_missing_single_strategy_file_is_red(runs_root):
    """Symmetry guard: the data/ path must still flag a missing artifact, so a
    future refactor can't drop the data/ check while fixing basket_code."""
    _seed_run(runs_root, "single0003",
              artifacts={"results_tradelevel.csv": b"x\n"},
              drop="results_tradelevel.csv")
    pc = PreflightCheck()
    pc._check_runs()
    assert _runs_status(pc) == "RED"


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
