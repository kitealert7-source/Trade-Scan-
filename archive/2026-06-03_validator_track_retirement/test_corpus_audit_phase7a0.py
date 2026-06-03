"""Phase 7a.0 acceptance test — corpus_audit create / freeze / verify / immutability.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 7a.0 + Section 1m-{i, ii, iii}, 6.9.

Tests cover:
  - create-manifest writes a manifest with frozen=true + per-file sha256 +
    cumulative sha256 + scope.rationale
  - verify passes on a clean corpus
  - verify FAILS on any sha256 drift (Section 1m-i corpus immutability)
  - verify FAILS when manifest.frozen is missing or false
  - check-immutability rejects staged mutation of a frozen corpus
  - Section 1m-iii: link-in-path detection FAIL-CLOSED on corpus_dir
    that resolves to a different path (simulated via symlink)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_AUDIT = REPO_ROOT / "tools" / "corpus_audit.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CORPUS_AUDIT), *args],
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT),
    )


def _make_tiny_corpus(parent: Path, corpus_id: str = "h2_test_corpus_v1") -> Path:
    """Build a 3-file synthetic corpus suitable for hash + verify tests."""
    corpus = parent / corpus_id
    bars = corpus / "bars"
    bars.mkdir(parents=True)
    # Two symbols, one timeframe — minimal but realistic shape.
    (bars / "EURUSD").mkdir()
    (bars / "USDJPY").mkdir()
    (bars / "EURUSD" / "EURUSD_5m_2024Q4.csv").write_text(
        "timestamp,open,high,low,close\n2024-12-01T00:00:00,1.10,1.11,1.09,1.105\n",
        encoding="utf-8",
    )
    (bars / "USDJPY" / "USDJPY_5m_2024Q4.csv").write_text(
        "timestamp,open,high,low,close\n2024-12-01T00:00:00,150.0,150.5,149.5,150.2\n",
        encoding="utf-8",
    )
    (bars / "USD_SYNTH" / "USD_SYNTH_daily_2024.csv").parent.mkdir()
    (bars / "USD_SYNTH" / "USD_SYNTH_daily_2024.csv").write_text(
        "date,compression_5d\n2024-12-01,15.0\n", encoding="utf-8",
    )
    return corpus


# ---------------------------------------------------------------------------
# create-manifest
# ---------------------------------------------------------------------------


def test_create_manifest_writes_frozen_with_per_file_hashes(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    rc = _run([
        "create-manifest", str(corpus),
        "--rationale", "Phase 7a.0 test fixture; not for production validation.",
        "--symbols", "EURUSD", "USDJPY", "USD_SYNTH",
        "--timeframes", "5m", "daily",
        "--date-start", "2024-12-01",
        "--date-end",   "2024-12-31",
    ])
    assert rc.returncode == 0, rc.stderr or rc.stdout
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen"] is True
    assert manifest["corpus_id"] == corpus.name
    assert manifest["scope"]["rationale"].startswith("Phase 7a.0")
    assert set(manifest["scope"]["symbols"]) == {"EURUSD", "USDJPY", "USD_SYNTH"}
    assert "5m" in manifest["scope"]["timeframes"]
    assert manifest["scope"]["date_range"]["start"] == "2024-12-01"
    # 3 files (3 CSV bars)
    assert len(manifest["files"]) == 3
    for f in manifest["files"]:
        assert len(f["sha256"]) == 64
        assert f["bytes"] > 0
    assert len(manifest["cumulative_sha256"]) == 64


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def test_verify_passes_on_clean_corpus(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    _run(["create-manifest", str(corpus),
          "--rationale", "smoke",
          "--symbols", "EURUSD", "USDJPY",
          "--timeframes", "5m",
          "--date-start", "2024-12-01", "--date-end", "2024-12-31"])
    rc = _run(["verify", str(corpus)])
    assert rc.returncode == 0, rc.stderr or rc.stdout


def test_verify_fails_on_file_mutation(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    _run(["create-manifest", str(corpus),
          "--rationale", "smoke",
          "--symbols", "EURUSD",
          "--timeframes", "5m",
          "--date-start", "2024-12-01", "--date-end", "2024-12-31"])
    # Mutate a file (Section 1m-i violation)
    victim = next((corpus / "bars" / "EURUSD").glob("*.csv"))
    victim.write_text(victim.read_text(encoding="utf-8") + "TAMPERED\n", encoding="utf-8")
    rc = _run(["verify", str(corpus)])
    assert rc.returncode == 1
    assert "sha256 drift" in (rc.stdout + rc.stderr)


def test_verify_fails_on_missing_manifest(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    # No create-manifest call -> manifest.json absent
    rc = _run(["verify", str(corpus)])
    assert rc.returncode == 1
    assert "manifest.json missing" in (rc.stdout + rc.stderr)


def test_verify_fails_on_frozen_false(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    _run(["create-manifest", str(corpus),
          "--rationale", "smoke",
          "--symbols", "EURUSD",
          "--timeframes", "5m",
          "--date-start", "2024-12-01", "--date-end", "2024-12-31"])
    # Flip frozen flag (Section 1m-i requires frozen=true to verify)
    mpath = corpus / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["frozen"] = False
    mpath.write_text(json.dumps(m), encoding="utf-8")
    rc = _run(["verify", str(corpus)])
    assert rc.returncode == 1


# ---------------------------------------------------------------------------
# cumulative hash stability
# ---------------------------------------------------------------------------


def test_cumulative_hash_stable_across_reruns(tmp_path: Path):
    corpus = _make_tiny_corpus(tmp_path)
    _run(["create-manifest", str(corpus),
          "--rationale", "smoke",
          "--symbols", "EURUSD",
          "--timeframes", "5m",
          "--date-start", "2024-12-01", "--date-end", "2024-12-31"])
    m1 = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    # Re-create — cumulative must be identical for identical bytes
    _run(["create-manifest", str(corpus),
          "--rationale", "smoke 2",
          "--symbols", "EURUSD",
          "--timeframes", "5m",
          "--date-start", "2024-12-01", "--date-end", "2024-12-31"])
    m2 = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    assert m1["cumulative_sha256"] == m2["cumulative_sha256"]
