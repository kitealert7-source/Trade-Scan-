"""
test_directive_queue_health.py

Unit tests for _check_directive_queue_health() in tools/system_introspection.py.

Two failure modes covered:
1. Stale INBOX entry — directive PORTFOLIO_COMPLETE still in INBOX
2. Stranded directive — repeated FAILs, or idle attempt > 24h

Plus negative cases: clean state, single FAIL, fresh idle, no state file,
malformed state file. Also reproduces the 2026-05-06 V1_P00 incident shape.

Run:
    python -m pytest tools/tests/test_directive_queue_health.py -v
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect INBOX_DIR and RUNS_DIR to per-test fixture dirs."""
    inbox = tmp_path / "INBOX"
    runs = tmp_path / "runs"
    inbox.mkdir()
    runs.mkdir()

    import tools.system_introspection as si
    monkeypatch.setattr(si, "INBOX_DIR", inbox)
    monkeypatch.setattr(si, "RUNS_DIR", runs)
    return {"inbox": inbox, "runs": runs, "module": si}


def _write_directive(inbox: Path, directive_id: str) -> None:
    (inbox / f"{directive_id}.txt").write_text("test:\n  name: x\n", encoding="utf-8")


def _write_state(
    runs: Path,
    directive_id: str,
    attempts: dict,
    latest: str,
    last_updated: str,
) -> None:
    d = runs / directive_id
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "directive_id": directive_id,
        "latest_attempt": latest,
        "attempts": attempts,
        "last_updated": last_updated,
    }
    (d / "directive_state.json").write_text(json.dumps(state), encoding="utf-8")


# ─── Stale INBOX detection ──────────────────────────────────────────────


def test_stale_portfolio_complete_in_inbox(env):
    """Directive PORTFOLIO_COMPLETE in INBOX -> flagged stale."""
    _write_directive(env["inbox"], "FOO_V1_P00")
    _write_state(
        env["runs"], "FOO_V1_P00",
        attempts={"attempt_01": {"status": "PORTFOLIO_COMPLETE"}},
        latest="attempt_01",
        last_updated="2026-05-05T12:00:00+00:00",
    )

    result = env["module"]._check_directive_queue_health()
    assert "FOO_V1_P00" in result["stale_inbox"]
    assert result["stranded"] == []


def test_multiple_stale_entries(env):
    """Multiple PORTFOLIO_COMPLETE directives all flagged."""
    for did in ("A_V1_P00", "B_V1_P00", "C_V1_P00"):
        _write_directive(env["inbox"], did)
        _write_state(
            env["runs"], did,
            attempts={"attempt_01": {"status": "PORTFOLIO_COMPLETE"}},
            latest="attempt_01",
            last_updated="2026-05-05T12:00:00+00:00",
        )

    result = env["module"]._check_directive_queue_health()
    assert sorted(result["stale_inbox"]) == ["A_V1_P00", "B_V1_P00", "C_V1_P00"]


# ─── Stranded detection ─────────────────────────────────────────────────


def test_stranded_repeat_failures(env):
    """Two consecutive FAILED attempts -> flagged stranded."""
    _write_directive(env["inbox"], "BAR_V1_P00")
    _write_state(
        env["runs"], "BAR_V1_P00",
        attempts={
            "attempt_01": {"status": "FAILED"},
            "attempt_02": {"status": "FAILED"},
            "attempt_03": {"status": "INITIALIZED"},
        },
        latest="attempt_03",
        last_updated=datetime.now(timezone.utc).isoformat(),  # fresh idle
    )

    result = env["module"]._check_directive_queue_health()
    matching = [s for s in result["stranded"] if s["directive_id"] == "BAR_V1_P00"]
    assert matching, "expected BAR_V1_P00 in stranded"
    assert matching[0]["fail_count"] >= 2


def test_stranded_idle_over_24h(env):
    """INITIALIZED with last_updated > 24h -> flagged stranded."""
    _write_directive(env["inbox"], "BAZ_V1_P00")
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    _write_state(
        env["runs"], "BAZ_V1_P00",
        attempts={"attempt_01": {"status": "INITIALIZED"}},
        latest="attempt_01",
        last_updated=old,
    )

    result = env["module"]._check_directive_queue_health()
    matching = [s for s in result["stranded"] if s["directive_id"] == "BAZ_V1_P00"]
    assert matching, "expected BAZ_V1_P00 stranded by idle"
    assert matching[0]["latest_status"] == "INITIALIZED"


def test_v1p00_actual_case(env):
    """Reproduce the V1_P00 incident: 2 FAILs + idle attempt_03."""
    did = "65_BRK_XAUUSD_15M_PSBRK_S01_V1_P00"
    _write_directive(env["inbox"], did)
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    _write_state(
        env["runs"], did,
        attempts={
            "attempt_01": {"status": "FAILED"},
            "attempt_02": {"status": "FAILED"},
            "attempt_03": {"status": "INITIALIZED"},
        },
        latest="attempt_03",
        last_updated=old,
    )

    result = env["module"]._check_directive_queue_health()
    matching = [s for s in result["stranded"] if s["directive_id"] == did]
    assert matching, "V1_P00 historical case should be flagged"
    assert matching[0]["fail_count"] >= 2


# ─── Negative / robustness cases ────────────────────────────────────────


def test_clean_state_not_flagged(env):
    """Single FAIL + fresh INITIALIZED -> not flagged."""
    _write_directive(env["inbox"], "OK_V1_P00")
    _write_state(
        env["runs"], "OK_V1_P00",
        attempts={
            "attempt_01": {"status": "FAILED"},
            "attempt_02": {"status": "INITIALIZED"},
        },
        latest="attempt_02",
        last_updated=datetime.now(timezone.utc).isoformat(),
    )

    result = env["module"]._check_directive_queue_health()
    assert "OK_V1_P00" not in result["stale_inbox"]
    assert all(s["directive_id"] != "OK_V1_P00" for s in result["stranded"])


def test_no_state_file_skipped(env):
    """Directive in INBOX without state file (fresh new) -> not flagged."""
    _write_directive(env["inbox"], "NEW_V1_P00")

    result = env["module"]._check_directive_queue_health()
    assert result["stale_inbox"] == []
    assert result["stranded"] == []


def test_malformed_state_silently_skipped(env):
    """Malformed JSON in state file -> skipped, not raised."""
    _write_directive(env["inbox"], "BAD_V1_P00")
    state_dir = env["runs"] / "BAD_V1_P00"
    state_dir.mkdir(parents=True)
    (state_dir / "directive_state.json").write_text("not json{", encoding="utf-8")

    result = env["module"]._check_directive_queue_health()
    assert result["stale_inbox"] == []
    assert result["stranded"] == []


def test_empty_attempts_skipped(env):
    """State file with empty attempts dict -> skipped."""
    _write_directive(env["inbox"], "EMPTY_V1_P00")
    _write_state(
        env["runs"], "EMPTY_V1_P00",
        attempts={},
        latest="",
        last_updated="2026-05-05T12:00:00+00:00",
    )

    result = env["module"]._check_directive_queue_health()
    assert "EMPTY_V1_P00" not in result["stale_inbox"]
    assert all(s["directive_id"] != "EMPTY_V1_P00" for s in result["stranded"])


def test_inbox_missing_returns_empty(tmp_path, monkeypatch):
    """If INBOX_DIR doesn't exist (worktree), function returns empty result."""
    runs = tmp_path / "runs"
    runs.mkdir()

    import tools.system_introspection as si
    monkeypatch.setattr(si, "INBOX_DIR", tmp_path / "MISSING_INBOX")
    monkeypatch.setattr(si, "RUNS_DIR", runs)

    result = si._check_directive_queue_health()
    assert result == {"stale_inbox": [], "stranded": []}


def test_fresh_idle_not_flagged(env):
    """INITIALIZED with last_updated < 24h -> not flagged."""
    _write_directive(env["inbox"], "FRESH_V1_P00")
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_state(
        env["runs"], "FRESH_V1_P00",
        attempts={"attempt_01": {"status": "INITIALIZED"}},
        latest="attempt_01",
        last_updated=recent,
    )

    result = env["module"]._check_directive_queue_health()
    assert all(s["directive_id"] != "FRESH_V1_P00" for s in result["stranded"])


def test_directive_not_in_inbox_skipped(env):
    """A directive with stale state but no INBOX file -> not flagged.

    Scope is INBOX-pending only — completed/ entries shouldn't surface.
    """
    # State file exists but no INBOX entry
    _write_state(
        env["runs"], "NOT_IN_INBOX",
        attempts={"attempt_01": {"status": "PORTFOLIO_COMPLETE"}},
        latest="attempt_01",
        last_updated="2026-05-05T12:00:00+00:00",
    )

    result = env["module"]._check_directive_queue_health()
    assert "NOT_IN_INBOX" not in result["stale_inbox"]
    assert all(s["directive_id"] != "NOT_IN_INBOX" for s in result["stranded"])


def test_z_suffix_iso8601_parsed(env):
    """`Z` UTC suffix in last_updated parses correctly."""
    _write_directive(env["inbox"], "ZSUF_V1_P00")
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _write_state(
        env["runs"], "ZSUF_V1_P00",
        attempts={"attempt_01": {"status": "INITIALIZED"}},
        latest="attempt_01",
        last_updated=old,
    )

    result = env["module"]._check_directive_queue_health()
    matching = [s for s in result["stranded"] if s["directive_id"] == "ZSUF_V1_P00"]
    assert matching, "Z-suffix ISO timestamp should still flag idle"
