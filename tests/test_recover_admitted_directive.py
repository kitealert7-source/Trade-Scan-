"""Regression tests for tools/recover_admitted_directive.py.

Source precedence covered: live wins over quarantine, quarantine wins over
git, git is used as last resort, not-found returns None. Also covers the
JSON output schema, the --write file-creation path, and the
refuse-to-overwrite guard.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import recover_admitted_directive as rad


def _build_tree(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "Trade_Scan"
    state = tmp_path / "TradeScan_State"
    (project / "backtest_directives" / "INBOX").mkdir(parents=True)
    (project / "backtest_directives" / "active").mkdir(parents=True)
    (project / "backtest_directives" / "active_backup").mkdir(parents=True)
    (project / "backtest_directives" / "completed").mkdir(parents=True)
    (state / "quarantine").mkdir(parents=True)
    return project, state


def test_find_live_picks_completed(tmp_path):
    project, _ = _build_tree(tmp_path)
    txt = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    txt.write_text("test:\n  name: X\n", encoding="utf-8")

    hit = rad.find_live("X_S01_V1_P00", directives_root=project / "backtest_directives")

    assert hit == txt


def test_find_live_skips_empty_file(tmp_path):
    project, _ = _build_tree(tmp_path)
    empty = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    empty.touch()

    hit = rad.find_live("X_S01_V1_P00", directives_root=project / "backtest_directives")

    assert hit is None


def test_find_quarantine_picks_most_recent_sweep(tmp_path):
    _, state = _build_tree(tmp_path)
    old = state / "quarantine" / "20260501T000000Z_cleanup" / "directives"
    new = state / "quarantine" / "20260522_191517_cleanup" / "directives"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "X_S01_V1_P00.txt").write_text("old content\n", encoding="utf-8")
    (new / "X_S01_V1_P00.txt").write_text("new content\n", encoding="utf-8")

    hit = rad.find_quarantine("X_S01_V1_P00", quarantine_root=state / "quarantine")

    assert hit is not None
    assert hit.read_text(encoding="utf-8") == "new content\n"


def test_find_quarantine_returns_none_when_missing(tmp_path):
    _, state = _build_tree(tmp_path)
    hit = rad.find_quarantine("MISSING_S01_V1_P00", quarantine_root=state / "quarantine")
    assert hit is None


def test_recover_prefers_live_over_quarantine(tmp_path):
    project, state = _build_tree(tmp_path)
    live = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    live.write_text("live wins\n", encoding="utf-8")
    quar_dir = state / "quarantine" / "20260522_cleanup" / "directives"
    quar_dir.mkdir(parents=True)
    (quar_dir / "X_S01_V1_P00.txt").write_text("quarantine loses\n", encoding="utf-8")

    result = rad.recover_directive(
        "X_S01_V1_P00",
        project_root=project,
        state_root=state,
    )

    assert result["source_type"] == "live"
    assert result["content"] == "live wins\n"


def test_recover_falls_back_to_quarantine_when_live_missing(tmp_path):
    project, state = _build_tree(tmp_path)
    quar_dir = state / "quarantine" / "20260522_cleanup" / "directives"
    quar_dir.mkdir(parents=True)
    (quar_dir / "X_S01_V1_P00.txt").write_text("from quarantine\n", encoding="utf-8")

    result = rad.recover_directive(
        "X_S01_V1_P00",
        project_root=project,
        state_root=state,
    )

    assert result["source_type"] == "quarantine"
    assert result["content"] == "from quarantine\n"
    assert result["recovered_path"].startswith("TradeScan_State/quarantine/")


def test_recover_returns_none_when_all_sources_empty(tmp_path):
    project, state = _build_tree(tmp_path)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-q",
                    "-m", "init", "--no-gpg-sign"], check=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "PATH": __import__("os").environ.get("PATH", "")})

    result = rad.recover_directive(
        "NEVER_EXISTED_S01_V1_P00",
        project_root=project,
        state_root=state,
    )

    assert result is None


def test_recover_from_git_history(tmp_path):
    project, state = _build_tree(tmp_path)
    import os

    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "commit.gpgsign", "false"], check=True)
    target = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    target.write_text("git-stored content\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", str(target)], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-q", "-m", "add directive",
                    "--no-gpg-sign"], check=True, env=env)
    target.unlink()

    result = rad.recover_directive(
        "X_S01_V1_P00",
        project_root=project,
        state_root=state,
    )

    assert result is not None
    assert result["source_type"] == "git"
    assert result["content"] == "git-stored content\n"
    assert "commit_sha" in result and len(result["commit_sha"]) == 40
    assert "blob_sha" in result and len(result["blob_sha"]) == 40
    assert result["commit_timestamp_utc"].endswith("+00:00")


def test_recover_provenance_schema(tmp_path):
    project, state = _build_tree(tmp_path)
    live = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    live.write_text("line1\nline2\nline3\n", encoding="utf-8")

    result = rad.recover_directive("X_S01_V1_P00", project_root=project, state_root=state)

    required = {"directive_id", "source_type", "recovered_path",
                "size_bytes", "sha256", "line_count", "content"}
    assert required <= set(result)
    assert result["line_count"] == 3
    assert result["size_bytes"] == len("line1\nline2\nline3\n".encode("utf-8"))
    assert len(result["sha256"]) == 64


def test_main_json_output_omits_content(tmp_path, monkeypatch, capsys):
    project, state = _build_tree(tmp_path)
    live = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    live.write_text("yaml content\n", encoding="utf-8")
    monkeypatch.setattr(rad, "PROJECT_ROOT", project)
    monkeypatch.setattr(rad, "TRADE_SCAN_STATE", state)
    monkeypatch.setattr(rad, "DIRECTIVES_ROOT", project / "backtest_directives")
    monkeypatch.setattr(rad, "QUARANTINE_ROOT", state / "quarantine")

    rc = rad.main(["X_S01_V1_P00", "--json"])
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert rc == 0
    assert "content" not in payload
    assert payload["source_type"] == "live"
    assert payload["directive_id"] == "X_S01_V1_P00"


def test_main_write_creates_file(tmp_path, monkeypatch, capsys):
    project, state = _build_tree(tmp_path)
    quar_dir = state / "quarantine" / "20260522_cleanup" / "directives"
    quar_dir.mkdir(parents=True)
    (quar_dir / "X_S01_V1_P00.txt").write_text("from quarantine\n", encoding="utf-8")
    monkeypatch.setattr(rad, "PROJECT_ROOT", project)
    monkeypatch.setattr(rad, "TRADE_SCAN_STATE", state)
    monkeypatch.setattr(rad, "DIRECTIVES_ROOT", project / "backtest_directives")
    monkeypatch.setattr(rad, "QUARANTINE_ROOT", state / "quarantine")

    dest = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    rc = rad.main(["X_S01_V1_P00", "--write", "--dest", str(dest)])

    assert rc == 0
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "from quarantine\n"


def test_main_write_refuses_overwrite_without_force(tmp_path, monkeypatch):
    project, state = _build_tree(tmp_path)
    quar_dir = state / "quarantine" / "20260522_cleanup" / "directives"
    quar_dir.mkdir(parents=True)
    (quar_dir / "X_S01_V1_P00.txt").write_text("from quarantine\n", encoding="utf-8")
    dest = project / "backtest_directives" / "completed" / "X_S01_V1_P00.txt"
    dest.write_text("existing\n", encoding="utf-8")
    monkeypatch.setattr(rad, "PROJECT_ROOT", project)
    monkeypatch.setattr(rad, "TRADE_SCAN_STATE", state)
    monkeypatch.setattr(rad, "DIRECTIVES_ROOT", project / "backtest_directives")
    monkeypatch.setattr(rad, "QUARANTINE_ROOT", state / "quarantine")

    with pytest.raises(SystemExit):
        rad.main(["X_S01_V1_P00", "--write", "--dest", str(dest)])

    assert dest.read_text(encoding="utf-8") == "existing\n"


def test_main_not_found_returns_2(tmp_path, monkeypatch, capsys):
    project, state = _build_tree(tmp_path)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    monkeypatch.setattr(rad, "PROJECT_ROOT", project)
    monkeypatch.setattr(rad, "TRADE_SCAN_STATE", state)
    monkeypatch.setattr(rad, "DIRECTIVES_ROOT", project / "backtest_directives")
    monkeypatch.setattr(rad, "QUARANTINE_ROOT", state / "quarantine")

    rc = rad.main(["MISSING_S01_V1_P00", "--json"])
    payload = json.loads(capsys.readouterr().out.strip())

    assert rc == 2
    assert payload["source_type"] is None
    assert "error" in payload
