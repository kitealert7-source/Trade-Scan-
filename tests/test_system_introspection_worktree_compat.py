"""Regression coverage for tools/system_introspection.py worktree fixes.

Covers the two bugs surfaced 2026-05-04 mid-session:

  Bug 1 — Engine status hardcoded to a single canonical version
          (`if version == "v1_5_6": status = "FROZEN"` else "LEGACY"),
          which silently mislabeled v1.5.7 / v1.5.8 / any successor
          engine as LEGACY despite the manifest reading FROZEN. Fix:
          read engine_status from the manifest itself.

  Bug 2 — STATE_ROOT / TS_EXECUTION / DRY_RUN_VAULT used the naive
          `PROJECT_ROOT.parent / name` form, which from a worktree
          (`Trade_Scan/.claude/worktrees/<n>/`) resolved to
          `.claude/worktrees/<sibling>` — non-existent for real
          siblings, but a real *stale* `TradeScan_State/` was left
          inside `.claude/worktrees/` from prior sessions and shadowed
          the correct path on naive walk-up. Fix: anchor on the real
          Trade_Scan repo root via `.git.is_dir()` marker, then take
          its parent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import system_introspection as si


# ---------------------------------------------------------------------------
# Bug 1 — Engine status from manifest
# ---------------------------------------------------------------------------


def _seed_engine(tmp_path: Path, version: str, manifest_payload: dict | None) -> tuple[Path, Path]:
    """Lay down an engine_dev/<version>/engine_manifest.json and a
    config/engine_registry.json under tmp_path, return their paths."""
    engine_root = tmp_path / "engine_dev" / "universal_research_engine"
    eng_dir = engine_root / version
    eng_dir.mkdir(parents=True)
    if manifest_payload is not None:
        (eng_dir / "engine_manifest.json").write_text(
            json.dumps(manifest_payload), encoding="utf-8"
        )
    registry = tmp_path / "config" / "engine_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"active_engine": version}), encoding="utf-8")
    return engine_root, registry


class TestEngineStatusFromManifest:

    def test_frozen_status_read_from_v1_5_8_manifest(self, tmp_path, monkeypatch):
        """v1.5.8's manifest declares engine_status='FROZEN'. Pre-fix,
        the introspection's hardcoded `version == 'v1_5_6'` check
        labelled it LEGACY. After fix, the manifest is the source of
        truth — status must be FROZEN."""
        engine_root, registry = _seed_engine(
            tmp_path,
            version="v1_5_8",
            manifest_payload={
                "engine_status": "FROZEN",
                "engine_version": "v1_5_8",
                "vaulted": True,
                "freeze_date": "2026-04-20",
            },
        )
        monkeypatch.setattr(si, "ENGINE_ROOT", engine_root)
        monkeypatch.setattr(si, "ENGINE_REGISTRY", registry)

        result = si.collect_engine()

        assert result["status"] == "FROZEN", (
            f"Engine status must come from manifest's engine_status field, "
            f"not from a version-name match. Got {result['status']!r}, "
            f"expected 'FROZEN'. See tools/system_introspection.py:115-128."
        )
        assert result["version_raw"] == "v1_5_8"
        assert result["manifest"] == "VALID"

    def test_arbitrary_successor_version_not_legacy(self, tmp_path, monkeypatch):
        """A future engine version (e.g., v9_9_9) with manifest
        engine_status='FROZEN' must be reported as FROZEN, not as
        LEGACY just because its version name isn't recognised. This
        is the future-proofing assertion."""
        engine_root, registry = _seed_engine(
            tmp_path,
            version="v9_9_9",
            manifest_payload={"engine_status": "FROZEN"},
        )
        monkeypatch.setattr(si, "ENGINE_ROOT", engine_root)
        monkeypatch.setattr(si, "ENGINE_REGISTRY", registry)

        assert si.collect_engine()["status"] == "FROZEN"

    def test_missing_engine_status_field_falls_back_to_legacy(
        self, tmp_path, monkeypatch
    ):
        """Pre-v1_5_7 manifests lacked engine_status. For those, the
        fallback is LEGACY — surfaces the missing metadata without
        masking it."""
        engine_root, registry = _seed_engine(
            tmp_path,
            version="v1_5_5",
            manifest_payload={"engine_version": "v1_5_5"},  # no engine_status
        )
        monkeypatch.setattr(si, "ENGINE_ROOT", engine_root)
        monkeypatch.setattr(si, "ENGINE_REGISTRY", registry)

        assert si.collect_engine()["status"] == "LEGACY"

    def test_no_registry_yields_unknown(self, tmp_path, monkeypatch):
        """If config/engine_registry.json is missing, version is
        UNKNOWN and status follows."""
        registry = tmp_path / "config" / "engine_registry.json"  # not created
        monkeypatch.setattr(si, "ENGINE_REGISTRY", registry)
        monkeypatch.setattr(si, "ENGINE_ROOT", tmp_path / "nonexistent")

        result = si.collect_engine()
        assert result["version_raw"] == "UNKNOWN"
        assert result["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Bug 2 — Worktree-safe sibling resolution
# ---------------------------------------------------------------------------


def _seed_worktree_layout(base: Path) -> tuple[Path, Path, Path]:
    """Lay down a Trade_Scan main repo (with `.git/` as a dir), a
    worktree under `.claude/worktrees/<n>/` (with `.git` as a *file*
    pointing at the gitdir), and a sibling repo `TradeScan_State` at
    `base`. Also drop a STALE `TradeScan_State/` inside
    `.claude/worktrees/` to assert the resolver doesn't naively pick
    the first match it finds when walking up.
    Returns (main_repo, worktree_dir, real_sibling)."""
    main_repo = base / "Trade_Scan"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()  # real gitdir: marker for the resolver
    worktrees_root = main_repo / ".claude" / "worktrees"
    worktrees_root.mkdir(parents=True)
    worktree_dir = worktrees_root / "session-x"
    worktree_dir.mkdir()
    (worktree_dir / ".git").write_text(
        f"gitdir: {main_repo / '.git' / 'worktrees' / 'session-x'}\n",
        encoding="utf-8",
    )
    real_sibling = base / "TradeScan_State"
    real_sibling.mkdir()
    # Stale leftover that the naive walk-up would have picked first.
    stale = worktrees_root / "TradeScan_State"
    stale.mkdir()
    return main_repo, worktree_dir, real_sibling


class TestSiblingResolverWorktreeSafe:

    def test_finds_real_repo_root_from_worktree(self, tmp_path, monkeypatch):
        """From a worktree dir, `_find_trade_scan_root` walks up and
        stops at the dir whose `.git` is a directory (the real repo
        root) — NOT at intermediate dirs like `.claude/worktrees/`."""
        main_repo, worktree_dir, _real_sibling = _seed_worktree_layout(tmp_path)

        monkeypatch.setattr(si, "PROJECT_ROOT", worktree_dir)
        resolved = si._find_trade_scan_root()

        assert resolved == main_repo, (
            f"Expected real repo root {main_repo}, got {resolved}. "
            f"Marker is `.git.is_dir()` — see "
            f"tools/system_introspection.py:_find_trade_scan_root."
        )

    def test_finds_real_repo_root_from_main(self, tmp_path, monkeypatch):
        """From the main repo dir directly, resolver returns it on
        iteration 0."""
        main_repo, _worktree_dir, _real_sibling = _seed_worktree_layout(tmp_path)

        monkeypatch.setattr(si, "PROJECT_ROOT", main_repo)
        assert si._find_trade_scan_root() == main_repo

    def test_resolve_sibling_skips_stale_worktree_leftover(
        self, tmp_path, monkeypatch
    ):
        """The exact bug we hit mid-session: a stale `TradeScan_State/`
        inside `.claude/worktrees/` from prior sessions. The naive
        walk-up resolver returned this stale dir on iter 1 and
        introspection silently read 0 rows from it. The fix anchors
        on the real repo root so we always land at the correct
        sibling."""
        main_repo, worktree_dir, real_sibling = _seed_worktree_layout(tmp_path)
        stale = main_repo / ".claude" / "worktrees" / "TradeScan_State"
        assert stale.exists(), "fixture must seed the stale leftover"

        monkeypatch.setattr(si, "PROJECT_ROOT", worktree_dir)
        # Recompute _TRADE_SCAN_ROOT under the patched PROJECT_ROOT so
        # _resolve_sibling reads the correct anchor.
        monkeypatch.setattr(si, "_TRADE_SCAN_ROOT", si._find_trade_scan_root())

        resolved = si._resolve_sibling("TradeScan_State")
        assert resolved == real_sibling, (
            f"Resolver picked the stale leftover {stale} instead of the real "
            f"sibling {real_sibling}. The whole point of the fix is to skip "
            f"stale dirs inside `.claude/worktrees/` by anchoring on "
            f"`.git.is_dir()`."
        )
        assert resolved != stale

    def test_resolve_sibling_main_repo_unchanged(self, tmp_path, monkeypatch):
        """From the main repo, sibling resolves to the parent —
        same as the simple `PROJECT_ROOT.parent / name` form would
        have produced. No regression for the common case."""
        main_repo, _worktree_dir, real_sibling = _seed_worktree_layout(tmp_path)

        monkeypatch.setattr(si, "PROJECT_ROOT", main_repo)
        monkeypatch.setattr(si, "_TRADE_SCAN_ROOT", si._find_trade_scan_root())

        assert si._resolve_sibling("TradeScan_State") == real_sibling
