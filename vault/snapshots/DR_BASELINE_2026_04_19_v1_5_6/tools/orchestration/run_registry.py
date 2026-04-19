"""Persistent run registry helpers for directive execution planning/claiming."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_STATES = {"PLANNED", "RUNNING", "COMPLETE", "FAILED", "ABORTED"}
STATE_TRANSITIONS = {
    "PLANNED": {"RUNNING", "FAILED", "ABORTED"},
    "RUNNING": {"PLANNED", "COMPLETE", "FAILED", "ABORTED"},
    "COMPLETE": {"FAILED"},
    "FAILED": {"PLANNED"},
    "ABORTED": set(), # Terminal state
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_registry(directive_id: str) -> dict:
    return {
        "version": 1,
        "directive_id": directive_id,
        "updated_at": _utc_now(),
        "runs": [],
    }


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@contextmanager
def _registry_lock(path: Path, timeout_s: float = 15.0):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - start >= timeout_s:
                raise TimeoutError(f"Timeout waiting for registry lock: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def load_registry(path: Path, directive_id: str | None = None) -> dict:
    if not path.exists():
        if directive_id is None:
            raise FileNotFoundError(f"Run registry not found: {path}")
        return _default_registry(directive_id)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "runs" not in data or not isinstance(data["runs"], list):
        raise RuntimeError(f"Invalid run registry format: {path}")
    if directive_id is not None and data.get("directive_id") not in (None, directive_id):
        raise RuntimeError(
            f"Run registry directive mismatch: expected {directive_id}, found {data.get('directive_id')}"
        )
    return data


def ensure_registry(path: Path, directive_id: str, planned_runs: list[dict]) -> list[dict]:
    """
    Merge planner output into run registry.

    Keeps existing state for known run_ids; new run_ids start at PLANNED.
    """
    with _registry_lock(path):
        reg = load_registry(path, directive_id=directive_id)
        existing_by_id = {r.get("run_id"): r for r in reg["runs"] if r.get("run_id")}

        merged: list[dict] = []
        for run in planned_runs:
            run_id = run["run_id"]
            existing = existing_by_id.get(run_id)
            if existing is not None:
                state = existing.get("state", "PLANNED")
                if state not in REGISTRY_STATES:
                    state = "PLANNED"
                merged.append(
                    {
                        "run_id": run_id,
                        "strategy": run["strategy"],
                        "symbol": run["symbol"],
                        "state": state,
                        "attempts": int(existing.get("attempts", 0)),
                        "last_error": existing.get("last_error"),
                        "updated_at": existing.get("updated_at", _utc_now()),
                    }
                )
            else:
                merged.append(
                    {
                        "run_id": run_id,
                        "strategy": run["strategy"],
                        "symbol": run["symbol"],
                        "state": "PLANNED",
                        "attempts": 0,
                        "last_error": None,
                        "updated_at": _utc_now(),
                    }
                )

        reg["directive_id"] = directive_id
        reg["runs"] = merged
        reg["updated_at"] = _utc_now()
        _write_atomic(path, reg)
        return merged


def list_runs(path: Path, directive_id: str) -> list[dict]:
    reg = load_registry(path, directive_id=directive_id)
    return list(reg["runs"])


def requeue_running_runs(path: Path, directive_id: str) -> int:
    with _registry_lock(path):
        reg = load_registry(path, directive_id=directive_id)
        count = 0
        for run in reg["runs"]:
            if run.get("state") == "RUNNING":
                run["state"] = "PLANNED"
                run["updated_at"] = _utc_now()
                count += 1
        if count:
            reg["updated_at"] = _utc_now()
            _write_atomic(path, reg)
        return count


def claim_next_planned_run(path: Path, directive_id: str) -> dict | None:
    with _registry_lock(path):
        reg = load_registry(path, directive_id=directive_id)
        for run in reg["runs"]:
            if run.get("state") == "PLANNED":
                run["state"] = "RUNNING"
                run["attempts"] = int(run.get("attempts", 0)) + 1
                run["updated_at"] = _utc_now()
                run["last_error"] = None
                reg["updated_at"] = _utc_now()
                _write_atomic(path, reg)
                return dict(run)
        return None


def update_run_state(
    path: Path,
    directive_id: str,
    run_id: str,
    new_state: str,
    *,
    last_error: str | None = None,
    termination_reason: str | None = None,
) -> None:
    if new_state not in REGISTRY_STATES:
        raise RuntimeError(f"Invalid registry state: {new_state}")

    with _registry_lock(path):
        reg = load_registry(path, directive_id=directive_id)
        for run in reg["runs"]:
            if run.get("run_id") != run_id:
                continue
            old_state = run.get("state", "PLANNED")
            if old_state != new_state and new_state not in STATE_TRANSITIONS.get(old_state, set()):
                raise RuntimeError(f"Illegal run registry transition: {run_id} {old_state} -> {new_state}")
            run["state"] = new_state
            run["updated_at"] = _utc_now()
            run["last_error"] = last_error
            if termination_reason is not None:
                run["termination_reason"] = termination_reason
            reg["updated_at"] = _utc_now()
            _write_atomic(path, reg)
            return
    raise RuntimeError(f"Run id not found in registry: {run_id}")
