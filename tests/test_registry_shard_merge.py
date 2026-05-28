"""Tests for the shard-merge run registry (SHARD_REGISTRY_PLAN.md).

Covers: conflict-free fold, uniqueness HARD FAIL (cross-shard + vs-base),
idempotent re-merge (incl. partial-crash convergence), post-merge integrity,
write-once shards, sequential-mode preservation.
"""
import hashlib
import json

import pytest

from tools.orchestration.registry_merge import (
    MANIFEST_NAME, RegistryMergeError, merge_shards, write_batch_manifest,
)


def _entry(run_id, status="complete", directive="dir1"):
    return {"run_id": run_id, "tier": "sandbox", "status": status,
            "created_at": "2026-01-01T00:00:00Z", "directive_hash": directive,
            "artifact_hash": None}


def _shard(d, run_id, **kw):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run_id}.json").write_text(json.dumps(_entry(run_id, **kw)), encoding="utf-8")


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_merge_basic_fold_and_completion_marker(tmp_path):
    reg = tmp_path / "run_registry.json"
    reg.write_text(json.dumps({"R0": _entry("R0")}), encoding="utf-8")
    sd = tmp_path / "shards"
    write_batch_manifest(sd, batch_id="B1", expected_run_ids=["R1", "R2"],
                         worker_count=2, max_parallel=2)
    _shard(sd, "R1"); _shard(sd, "R2")
    m = merge_shards(sd, registry_path=reg)
    out = json.loads(reg.read_text(encoding="utf-8"))
    assert set(out) == {"R0", "R1", "R2"}
    assert m["merge_completed"] is True
    assert m["merged_run_count"] == 3 and m["shard_count"] == 2
    assert m["merged_registry_sha256"] == _sha(reg)
    assert m["missing_expected_run_ids"] == []
    # shards deleted, manifest preserved
    assert not [f for f in sd.glob("*.json") if f.name != MANIFEST_NAME]
    assert (sd / MANIFEST_NAME).exists()


def test_merge_duplicate_run_id_across_shards_hard_fails(tmp_path):
    reg = tmp_path / "run_registry.json"; reg.write_text("{}", encoding="utf-8")
    sd = tmp_path / "shards"; sd.mkdir()
    (sd / "a.json").write_text(json.dumps(_entry("DUP", "complete")), encoding="utf-8")
    (sd / "b.json").write_text(json.dumps(_entry("DUP", "failed")), encoding="utf-8")
    with pytest.raises(RegistryMergeError, match="duplicate run_id"):
        merge_shards(sd, registry_path=reg)
    assert json.loads(reg.read_text(encoding="utf-8")) == {}      # base untouched
    assert (sd / "a.json").exists() and (sd / "b.json").exists()  # shards intact


def test_merge_vs_base_differing_payload_hard_fails(tmp_path):
    reg = tmp_path / "run_registry.json"
    reg.write_text(json.dumps({"R1": _entry("R1", "complete")}), encoding="utf-8")
    sd = tmp_path / "shards"
    _shard(sd, "R1", status="failed")  # same run_id, different payload
    with pytest.raises(RegistryMergeError, match="(?i)differing payload"):
        merge_shards(sd, registry_path=reg)


def test_merge_idempotent_when_already_completed(tmp_path):
    reg = tmp_path / "run_registry.json"; reg.write_text("{}", encoding="utf-8")
    sd = tmp_path / "shards"
    write_batch_manifest(sd, batch_id="B", expected_run_ids=["R1"], worker_count=1, max_parallel=2)
    _shard(sd, "R1")
    merge_shards(sd, registry_path=reg)
    sha1 = _sha(reg)
    m2 = merge_shards(sd, registry_path=reg)  # re-run: no-op
    assert m2["merge_completed"] is True
    assert _sha(reg) == sha1  # registry unchanged


def test_merge_converges_after_partial_crash(tmp_path):
    # Simulate a crash AFTER the registry was written but BEFORE marking complete
    # and BEFORE deleting shards: base already holds the entry (identical), the
    # shard is still present, manifest not completed. Re-merge must converge.
    reg = tmp_path / "run_registry.json"
    reg.write_text(json.dumps({"R1": _entry("R1")}), encoding="utf-8")
    sd = tmp_path / "shards"
    write_batch_manifest(sd, batch_id="B", expected_run_ids=["R1"], worker_count=1, max_parallel=2)
    (sd / "R1.json").write_text(json.dumps(_entry("R1")), encoding="utf-8")  # identical to base
    m = merge_shards(sd, registry_path=reg)
    assert m["merge_completed"] is True
    assert json.loads(reg.read_text(encoding="utf-8")) == {"R1": _entry("R1")}


def test_write_run_shard_is_write_once(tmp_path):
    from tools.system_registry import _write_run_shard
    sd = tmp_path / "s"
    _write_run_shard(sd, _entry("R1", "complete"))
    _write_run_shard(sd, _entry("R1", "failed"))  # must be refused
    assert json.loads((sd / "R1.json").read_text(encoding="utf-8"))["status"] == "complete"


def test_log_run_to_registry_shard_mode_writes_shard(tmp_path, monkeypatch):
    import tools.system_registry as sr
    monkeypatch.setenv("TS_REGISTRY_SHARD_DIR", str(tmp_path / "shards"))
    sr.log_run_to_registry("RX", "no_trades", "dirX")  # no_trades -> no artifact check
    shard = tmp_path / "shards" / "RX.json"
    assert shard.exists()
    assert json.loads(shard.read_text(encoding="utf-8"))["status"] == "no_trades"
