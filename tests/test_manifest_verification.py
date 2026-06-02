"""Unit tests for tools.manifest_verification — the single source of truth for
run-manifest artifact verification (the basket_code-vs-data/ PATH + HASH
contract), shared by run_pipeline.verify_manifest_integrity (startup gate) and
system_preflight._check_runs (diagnostic).

This is the FRONT-LINE guard: the two callers now delegate the per-artifact
loop here, so the contract cannot desync between them. If a future edit breaks
the path or hash rule, this test fails first (and both integration tests —
test_manifest_integrity_basket_path.py / test_preflight_basket_manifest_path.py
— fail with it). Background: the 2026-06-02 false-RED of 2962 healthy basket
runs (auto-memory feedback_mechanism_port_check, instance #6).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.manifest_verification import (  # noqa: E402
    artifact_hash,
    artifact_path,
    verify_run_artifacts,
)


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write(p: Path, body: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


# ---------------------------------------------------------------------------
# PATH BASIS
# ---------------------------------------------------------------------------


def test_artifact_path_data_under_data_dir(tmp_path):
    run = tmp_path / "run"
    assert artifact_path(run, "results_tradelevel.csv") == run / "data" / "results_tradelevel.csv"


def test_artifact_path_basket_code_at_run_root(tmp_path):
    run = tmp_path / "run"
    assert artifact_path(run, "basket_code/recycle_strategies.py") == run / "basket_code" / "recycle_strategies.py"
    # NOT under data/ — the exact contract the 2026-06-02 bug got wrong.
    assert artifact_path(run, "basket_code/recycle_strategies.py") != run / "data" / "basket_code" / "recycle_strategies.py"


# ---------------------------------------------------------------------------
# HASH BASIS
# ---------------------------------------------------------------------------


def test_artifact_hash_data_is_raw_bytes(tmp_path):
    p = tmp_path / "data" / "a.csv"
    _write(p, b"x,y\r\n1,2\r\n")  # CRLF preserved — raw hashing must NOT normalize
    assert artifact_hash(p, "a.csv") == _sha256(b"x,y\r\n1,2\r\n")


def test_artifact_hash_basket_code_is_lf_canonical(tmp_path):
    p = tmp_path / "basket_code" / "rule.py"
    _write(p, b"line1\r\nline2\r\n")  # CRLF on disk
    # basket_code is LF-canonicalized before hashing -> matches the LF form.
    assert artifact_hash(p, "basket_code/rule.py") == _sha256(b"line1\nline2\n")


# ---------------------------------------------------------------------------
# verify_run_artifacts — happy paths
# ---------------------------------------------------------------------------


def test_empty_artifacts_is_clean(tmp_path):
    assert verify_run_artifacts(tmp_path, {}) == []


def test_data_artifact_present_and_matched(tmp_path):
    body = b"a,b\n1,2\n"
    _write(tmp_path / "data" / "results_tradelevel.csv", body)
    assert verify_run_artifacts(tmp_path, {"results_tradelevel.csv": _sha256(body)}) == []


def test_basket_code_artifact_at_root_matched(tmp_path):
    body = b"# rule v1\n"  # LF -> canonical == raw
    _write(tmp_path / "basket_code" / "recycle_rules" / "pine_ratio_zrev_v1.py", body)
    arts = {"basket_code/recycle_rules/pine_ratio_zrev_v1.py": _sha256(body)}
    assert verify_run_artifacts(tmp_path, arts) == []


def test_basket_code_crlf_on_disk_matches_lf_canonical(tmp_path):
    """The exact live Windows regression: CRLF snapshot on disk, LF-canonical
    hash in the manifest. Must verify clean."""
    crlf = b"line1\r\nline2\r\nline3\r\n"
    lf_hash = _sha256(b"line1\nline2\nline3\n")
    assert _sha256(crlf) != lf_hash, "test premise"
    _write(tmp_path / "basket_code" / "recycle_rules" / "rule.py", crlf)
    assert verify_run_artifacts(tmp_path, {"basket_code/recycle_rules/rule.py": lf_hash}) == []


def test_both_modes_coexist_clean(tmp_path):
    _write(tmp_path / "data" / "results_tradelevel.csv", b"x\n")
    _write(tmp_path / "basket_code" / "recycle_strategies.py", b"# bs\n")
    arts = {
        "results_tradelevel.csv": _sha256(b"x\n"),
        "basket_code/recycle_strategies.py": _sha256(b"# bs\n"),
    }
    assert verify_run_artifacts(tmp_path, arts) == []


# ---------------------------------------------------------------------------
# verify_run_artifacts — failure paths (must not be swallowed)
# ---------------------------------------------------------------------------


def test_missing_data_artifact_reported(tmp_path):
    problems = verify_run_artifacts(tmp_path, {"results_tradelevel.csv": _sha256(b"x")})
    assert problems == ["Missing artifact results_tradelevel.csv"]


def test_missing_basket_code_artifact_reported(tmp_path):
    problems = verify_run_artifacts(tmp_path, {"basket_code/recycle_strategies.py": _sha256(b"x")})
    assert problems == ["Missing artifact basket_code/recycle_strategies.py"]


def test_data_hash_mismatch_reported(tmp_path):
    _write(tmp_path / "data" / "a.csv", b"actual")
    problems = verify_run_artifacts(tmp_path, {"a.csv": _sha256(b"expected-different")})
    assert problems == ["Hash mismatch for a.csv"]


def test_basket_code_hash_mismatch_reported(tmp_path):
    _write(tmp_path / "basket_code" / "rule.py", b"# actual\n")
    problems = verify_run_artifacts(tmp_path, {"basket_code/rule.py": _sha256(b"# different\n")})
    assert problems == ["Hash mismatch for basket_code/rule.py"]


def test_basket_code_present_at_root_not_found_under_data(tmp_path):
    """Regression for the precise bug: a basket_code file present at the run
    root must verify clean even if nothing exists under data/basket_code/.
    The pre-fix checker looked under data/ and reported it Missing."""
    body = b"# bs\n"
    _write(tmp_path / "basket_code" / "recycle_strategies.py", body)
    # Deliberately leave data/ empty.
    assert verify_run_artifacts(tmp_path, {"basket_code/recycle_strategies.py": _sha256(body)}) == []


def test_multiple_problems_all_collected(tmp_path):
    """verify_run_artifacts collects ALL problems (the gate wants the full
    list), it does not stop at the first."""
    _write(tmp_path / "data" / "present_but_wrong.csv", b"actual")
    arts = {
        "present_but_wrong.csv": _sha256(b"expected"),       # hash mismatch
        "absent.csv": _sha256(b"x"),                          # missing (data)
        "basket_code/gone.py": _sha256(b"x"),                # missing (basket_code)
    }
    problems = verify_run_artifacts(tmp_path, arts)
    assert set(problems) == {
        "Hash mismatch for present_but_wrong.csv",
        "Missing artifact absent.csv",
        "Missing artifact basket_code/gone.py",
    }


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
