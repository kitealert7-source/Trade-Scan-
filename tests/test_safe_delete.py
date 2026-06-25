"""Tests for tools/state_lifecycle/safe_delete.py — Windows-safe deletion.

The junction test is the load-bearing one: it proves safe_rmtree removes a
junction as a *link* and never follows it into the target (the 2026-05-07
data-loss class). The basic / read-only / missing tests cover the everyday path.
"""
from __future__ import annotations

import os
import stat
import subprocess

import pytest

from tools.state_lifecycle.safe_delete import safe_rmtree, is_reparse_point


def test_safe_rmtree_basic(tmp_path):
    d = tmp_path / "tree"
    (d / "a" / "b").mkdir(parents=True)
    (d / "a" / "f.txt").write_text("x", encoding="utf-8")
    (d / "a" / "b" / "g.txt").write_text("y", encoding="utf-8")
    assert safe_rmtree(d) is True
    assert not d.exists()


def test_safe_rmtree_readonly_file(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    f = d / "ro.txt"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, stat.S_IREAD)  # read-only — bare rmtree would raise PermissionError
    assert safe_rmtree(d) is True
    assert not d.exists()


def test_safe_rmtree_missing_path_is_noop(tmp_path):
    assert safe_rmtree(tmp_path / "does_not_exist") is True


def test_safe_rmtree_does_not_follow_junction(tmp_path):
    """Delete a container holding a junction; the junction TARGET must survive."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "important.txt").write_text("KEEP ME", encoding="utf-8")

    container = tmp_path / "container"
    container.mkdir()
    link = container / "link_to_target"

    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"could not create NTFS junction: {r.stderr.strip() or r.stdout.strip()}")

    assert is_reparse_point(link), "junction should be a reparse point"

    # Delete the CONTAINER (junction inside). safe_rmtree must drop the link only.
    assert safe_rmtree(container) is True
    assert not container.exists()

    # The crux: the junction's target and its contents are untouched.
    assert target.exists(), "junction target was followed and deleted — DATA LOSS"
    assert (target / "important.txt").read_text(encoding="utf-8") == "KEEP ME"


def test_safe_rmtree_root_junction_removes_link_only(tmp_path):
    """When the path itself IS a junction, remove the link, spare the target."""
    target = tmp_path / "t2"
    target.mkdir()
    (target / "data.txt").write_text("data", encoding="utf-8")
    link = tmp_path / "j2"

    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip("could not create NTFS junction")

    assert safe_rmtree(link) is True
    assert not link.exists()
    assert target.exists() and (target / "data.txt").exists()
