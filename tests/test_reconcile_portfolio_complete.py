"""Tests for tools/state_lifecycle/reconcile_portfolio_complete.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.state_lifecycle.reconcile_portfolio_complete import (
    _is_run_alive,
    apply_record,
    scan,
    write_audit_log,
)


def _make_fake_state(tmp_path: Path) -> tuple[Path, Path, Path]:
    runs = tmp_path / "runs"
    sandbox = tmp_path / "sandbox"
    backtests = tmp_path / "backtests"
    for d in (runs, sandbox, backtests):
        d.mkdir(parents=True, exist_ok=True)
    return runs, sandbox, backtests


def _alive_run(runs: Path, rid: str) -> None:
    d = runs / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "run_state.json").write_text("{}", encoding="utf-8")


def _write_directive_state(
    runs: Path, directive_id: str, payload: dict
) -> Path:
    d = runs / directive_id
    d.mkdir(parents=True, exist_ok=True)
    ds = d / "directive_state.json"
    ds.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ds


def test_is_run_alive_requires_folder_and_state(tmp_path):
    """Matches lineage_pruner.verify_referential_integrity: BOTH gates required."""
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    # alive: folder + run_state.json
    (runs / "aaaa").mkdir()
    (runs / "aaaa" / "run_state.json").write_text("{}", encoding="utf-8")
    assert _is_run_alive("aaaa", runs, sandbox, backtests) is True
    # alive: sandbox folder + run_state.json
    (sandbox / "bbbb").mkdir()
    (sandbox / "bbbb" / "run_state.json").write_text("{}", encoding="utf-8")
    assert _is_run_alive("bbbb", runs, sandbox, backtests) is True
    # alive: folder + legacy backtests JSON
    (runs / "cccc").mkdir()
    (backtests / "cccc.json").write_text("{}", encoding="utf-8")
    assert _is_run_alive("cccc", runs, sandbox, backtests) is True
    # DEAD: folder present but no state JSON anywhere
    (runs / "dddd").mkdir()
    assert _is_run_alive("dddd", runs, sandbox, backtests) is False
    # DEAD: BT JSON present but no folder (lineage_pruner integrity case)
    (backtests / "eeee.json").write_text("{}", encoding="utf-8")
    assert _is_run_alive("eeee", runs, sandbox, backtests) is False
    # DEAD: nothing
    assert _is_run_alive("zzzz", runs, sandbox, backtests) is False


def test_scan_emits_record_with_dead_child(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _alive_run(runs, "alive001")
    _write_directive_state(runs, "X_DIRECTIVE_1", {
        "directive_id": "X_DIRECTIVE_1",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["INITIALIZED", "PORTFOLIO_COMPLETE"],
                "run_ids": ["alive001", "dead0001"],
                "run_id": "alive001",
            }
        },
        "last_updated": "2026-04-01T00:00:00+00:00",
        "protected": True,
    })
    records = scan(runs, sandbox, backtests)
    assert len(records) == 1
    rec = records[0]
    assert rec["directive_id"] == "X_DIRECTIVE_1"
    assert rec["dead_run_ids"] == ["dead0001"]
    assert rec["run_ids_after"] == ["alive001"]
    assert rec["status"] == "PORTFOLIO_COMPLETE"
    assert rec["protected"] is True


def test_scan_protected_without_portfolio_complete_status_in_scope(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _write_directive_state(runs, "X_PROTECTED_OTHER", {
        "directive_id": "X_PROTECTED_OTHER",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "SOME_OTHER_STATUS",
                "history": ["INITIALIZED"],
                "run_ids": ["deadprotected"],
            }
        },
        "protected": True,
    })
    records = scan(runs, sandbox, backtests)
    assert len(records) == 1
    assert records[0]["dead_run_ids"] == ["deadprotected"]


def test_scan_skips_non_portfolio_complete_and_unprotected(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _write_directive_state(runs, "X_INCOMPLETE", {
        "directive_id": "X_INCOMPLETE",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "RUN_INCOMPLETE",
                "history": ["INITIALIZED"],
                "run_ids": ["deadnotscoped"],
            }
        },
        "protected": False,
    })
    assert scan(runs, sandbox, backtests) == []


def test_scan_skips_when_all_children_alive(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _alive_run(runs, "alive001")
    _alive_run(runs, "alive002")
    _write_directive_state(runs, "X_HEALTHY", {
        "directive_id": "X_HEALTHY",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["PORTFOLIO_COMPLETE"],
                "run_ids": ["alive001", "alive002"],
            }
        },
        "protected": True,
    })
    assert scan(runs, sandbox, backtests) == []


def test_apply_record_mutates_only_latest_attempt(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _alive_run(runs, "alive001")
    payload = {
        "directive_id": "X_TWO_ATTEMPTS",
        "latest_attempt": "attempt_02",
        "attempts": {
            "attempt_01": {
                "status": "RUN_INCOMPLETE",
                "history": ["INITIALIZED", "RUN_INCOMPLETE"],
                "run_ids": ["dead_in_a1"],
                "run_id": "dead_in_a1",
            },
            "attempt_02": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["INITIALIZED", "PORTFOLIO_COMPLETE"],
                "run_ids": ["alive001", "dead_in_a2"],
                "run_id": "alive001",
            },
        },
        "last_updated": "2026-04-01T00:00:00+00:00",
        "protected": True,
    }
    ds = _write_directive_state(runs, "X_TWO_ATTEMPTS", payload)

    records = scan(runs, sandbox, backtests)
    assert len(records) == 1
    apply_record(records[0], "2026-05-21T12:00:00+00:00", runs)

    after = json.loads(ds.read_text(encoding="utf-8"))
    # latest attempt cleaned
    assert after["attempts"]["attempt_02"]["run_ids"] == ["alive001"]
    # sibling attempt untouched
    assert after["attempts"]["attempt_01"]["run_ids"] == ["dead_in_a1"]
    assert after["attempts"]["attempt_01"]["status"] == "RUN_INCOMPLETE"
    # informational fields preserved
    assert after["attempts"]["attempt_02"]["run_id"] == "alive001"
    assert after["attempts"]["attempt_02"]["history"] == [
        "INITIALIZED", "PORTFOLIO_COMPLETE",
    ]
    assert after["protected"] is True
    assert after["last_updated"] == "2026-05-21T12:00:00+00:00"


def test_apply_record_empties_run_ids_when_all_dead(tmp_path):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _write_directive_state(runs, "X_ALL_DEAD", {
        "directive_id": "X_ALL_DEAD",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["PORTFOLIO_COMPLETE"],
                "run_ids": ["dead001", "dead002"],
                "run_id": "dead001",
            }
        },
        "protected": True,
    })

    records = scan(runs, sandbox, backtests)
    assert len(records) == 1
    apply_record(records[0], "2026-05-21T12:00:00+00:00", runs)

    after = json.loads(
        (runs / "X_ALL_DEAD" / "directive_state.json").read_text(encoding="utf-8")
    )
    assert after["attempts"]["attempt_01"]["run_ids"] == []
    # run_id singular intentionally not cleared (audit-only field)
    assert after["attempts"]["attempt_01"]["run_id"] == "dead001"


def test_write_audit_log_shape(tmp_path):
    audit = tmp_path / "audit.json"
    records = [
        {
            "directive_id": "X_DIRECTIVE_1",
            "file_path": "fake.json",
            "attempt_key": "attempt_01",
            "status": "PORTFOLIO_COMPLETE",
            "protected": True,
            "run_ids_before": ["a", "b"],
            "dead_run_ids": ["b"],
            "run_ids_after": ["a"],
        }
    ]
    out = write_audit_log(audit, "DRY_RUN", records, scan_total=10)
    assert out == audit
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["mode"] == "DRY_RUN"
    assert payload["directives_scanned"] == 10
    assert payload["directives_with_dead_children"] == 1
    assert payload["dead_run_ids_removed_total"] == 1
    assert payload["changes"][0]["dead_run_ids"] == ["b"]


def test_dry_run_does_not_mutate_directive_state(tmp_path, monkeypatch):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _alive_run(runs, "alive001")
    ds = _write_directive_state(runs, "X_DRY", {
        "directive_id": "X_DRY",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["PORTFOLIO_COMPLETE"],
                "run_ids": ["alive001", "dead_dry"],
                "run_id": "alive001",
            }
        },
        "last_updated": "2026-04-01T00:00:00+00:00",
        "protected": True,
    })
    original = ds.read_text(encoding="utf-8")

    # Drive main() via monkeypatched module constants + skip the PID check.
    import tools.state_lifecycle.reconcile_portfolio_complete as mod
    monkeypatch.setattr(mod, "RUNS_DIR", runs)
    monkeypatch.setattr(mod, "SANDBOX_DIR", sandbox)
    monkeypatch.setattr(mod, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(mod, "execution_pid_exists", lambda: False)

    rc = mod.main(["--dry-run"])
    assert rc == 0
    # directive file byte-identical
    assert ds.read_text(encoding="utf-8") == original


def test_execute_writes_audit_log_to_custom_path(tmp_path, monkeypatch):
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    _alive_run(runs, "alive001")
    _write_directive_state(runs, "X_EXEC", {
        "directive_id": "X_EXEC",
        "latest_attempt": "attempt_01",
        "attempts": {
            "attempt_01": {
                "status": "PORTFOLIO_COMPLETE",
                "history": ["PORTFOLIO_COMPLETE"],
                "run_ids": ["alive001", "dead_exec"],
                "run_id": "alive001",
            }
        },
        "protected": True,
    })
    audit = tmp_path / "audit.json"

    import tools.state_lifecycle.reconcile_portfolio_complete as mod
    monkeypatch.setattr(mod, "RUNS_DIR", runs)
    monkeypatch.setattr(mod, "SANDBOX_DIR", sandbox)
    monkeypatch.setattr(mod, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(mod, "execution_pid_exists", lambda: False)

    rc = mod.main(["--execute", "--audit-log", str(audit)])
    assert rc == 0
    after = json.loads(
        (runs / "X_EXEC" / "directive_state.json").read_text(encoding="utf-8")
    )
    assert after["attempts"]["attempt_01"]["run_ids"] == ["alive001"]
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["mode"] == "EXECUTE"
    assert payload["directives_with_dead_children"] == 1


def test_dry_run_and_execute_mutually_exclusive(tmp_path, monkeypatch, capsys):
    import tools.state_lifecycle.reconcile_portfolio_complete as mod
    monkeypatch.setattr(mod, "execution_pid_exists", lambda: False)
    rc = mod.main(["--dry-run", "--execute"])
    assert rc == 2


def test_apply_record_refuses_paths_outside_runs_dir(tmp_path):
    """Regression: 2026-05-21 incident — buggy default args let apply_record
    mutate production paths even when callers thought they were using a
    sandboxed runs_dir. The scope guard refuses any path not under the
    configured runs_dir."""
    runs, sandbox, backtests = _make_fake_state(tmp_path)
    elsewhere = tmp_path / "not_runs"
    elsewhere.mkdir()
    foreign = elsewhere / "stray_directive_state.json"
    foreign.write_text(json.dumps({
        "directive_id": "stray",
        "latest_attempt": "attempt_01",
        "attempts": {"attempt_01": {"status": "PORTFOLIO_COMPLETE", "run_ids": ["x"]}},
    }), encoding="utf-8")
    original_bytes = foreign.read_bytes()

    record = {
        "directive_id": "stray",
        "file_path": str(foreign),
        "attempt_key": "attempt_01",
        "status": "PORTFOLIO_COMPLETE",
        "protected": False,
        "run_ids_before": ["x"],
        "dead_run_ids": ["x"],
        "run_ids_after": [],
    }
    with pytest.raises(RuntimeError, match="outside configured runs_dir"):
        apply_record(record, "2026-05-21T12:00:00+00:00", runs)
    # Foreign file byte-identical — guard fired before any write.
    assert foreign.read_bytes() == original_bytes
