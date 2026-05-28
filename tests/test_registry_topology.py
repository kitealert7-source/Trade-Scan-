"""Topology guard + chokepoint behavior for authoritative run-registry writes.

Invariant (SHARD_REGISTRY_PLAN.md §7): every worker-side / per-run write of
run_registry.json routes through system_registry.record_run(). The persist
primitive _save_registry_atomic() may be called ONLY from record_run (the
chokepoint) + a small allowlist of PARENT-side whole-registry rebuilders. A new
call site -- especially in a worker/per-directive path -- silently fragments the
write topology and breaks parallel correctness. This test fails CI on drift.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Files allowed to call _save_registry_atomic directly:
#   system_registry.py  -> record_run (the chokepoint) + reconcile_registry
#   cleanup_reconciler  -> parent-side cleanup whole-registry rebuild
#   filter_strategies   -> parent-side promotion whole-registry rebuild
#   run_pipeline        -> gate_registry_consistency (parent startup drift-fix)
_ALLOW = {
    "tools/system_registry.py",
    "tools/cleanup_reconciler.py",
    "tools/filter_strategies.py",
    "tools/run_pipeline.py",
}

# Worker / per-directive modules that MUST persist run-state only via record_run.
_WORKER_MODULES = [
    "tools/orchestration/stage_symbol_execution.py",
    "tools/basket_runner.py",
    "tools/basket_pipeline.py",
    "tools/recycle_strategies.py",
    "tools/orchestration/pipeline_orchestrator.py",
]


def _count_calls(text: str) -> int:
    n = len(re.findall(r"_save_registry_atomic\s*\(", text))
    if "def _save_registry_atomic" in text:
        n -= 1
    return n


def test_registry_persist_only_from_allowlist():
    offenders = {}
    for py in (_REPO / "tools").rglob("*.py"):
        rel = str(py.relative_to(_REPO)).replace("\\", "/")
        if "tests/" in rel:
            continue
        n = _count_calls(py.read_text(encoding="utf-8"))
        if n > 0 and rel not in _ALLOW:
            offenders[rel] = n
    assert not offenders, (
        f"_save_registry_atomic called outside the allowlist: {offenders}. "
        f"Route worker-side run-state writes through system_registry.record_run().")


def test_worker_modules_never_persist_registry_directly():
    for rel in _WORKER_MODULES:
        p = _REPO / rel
        if p.exists():
            assert "_save_registry_atomic(" not in p.read_text(encoding="utf-8"), (
                f"{rel} must not call _save_registry_atomic directly — use record_run().")


def test_run_pipeline_has_single_parent_side_persist():
    # Exactly one direct persist (gate_registry_consistency, parent startup). A
    # second is almost certainly a re-introduced worker-side inline writer.
    rp = (_REPO / "tools" / "run_pipeline.py").read_text(encoding="utf-8")
    n = _count_calls(rp)
    assert n == 1, (
        f"run_pipeline.py has {n} _save_registry_atomic call(s); expected exactly 1 "
        f"(gate_registry_consistency). A new one is likely a worker-side inline "
        f"writer — route it through record_run().")


def test_record_run_shard_mode_writes_shard(tmp_path, monkeypatch):
    import tools.system_registry as sr
    monkeypatch.setenv("TS_REGISTRY_SHARD_DIR", str(tmp_path / "sh"))
    sr.record_run({"run_id": "RID1", "tier": "basket", "status": "BASKET_COMPLETE",
                   "directive_hash": "d", "basket_id": "AB"})
    import json
    shard = tmp_path / "sh" / "RID1.json"
    assert shard.exists()
    assert json.loads(shard.read_text(encoding="utf-8"))["status"] == "BASKET_COMPLETE"


def test_record_run_requires_run_id(monkeypatch):
    import pytest
    import tools.system_registry as sr
    monkeypatch.setenv("TS_REGISTRY_SHARD_DIR", "")  # ensure no shard side effects
    with pytest.raises(ValueError, match="run_id"):
        sr.record_run({"status": "complete"})
