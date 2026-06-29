"""run_indicator_snapshot.py — co-locate the imported indicator modules with
each run, so a backtest is faithfully reproducible.

A backtest's behavior is determined by three things: ``strategy.py`` (logic +
params), the directive (run config), and the **indicator modules the strategy
imports**. The pipeline already snapshots the first two per run; this module
snapshots the third — the previously-missing leg of the stool
(``outputs/system_reports/08_pipeline_audit/INDICATOR_SNAPSHOT_GAP_2026-06-29.md``).

It does two things, mirroring how ``strategy.py`` is both hashed and copied:

1. ``indicators_manifest.json`` — for each imported ``indicators.*`` module:
   module id + content hash (sha256) + registry membership, plus the registry
   version. Enables cheap drift detection: at replay/verification, recompute the
   live hashes and **fail loud** on any mismatch (never silently run a drifted
   indicator).
2. Source copies of those indicator ``.py`` files under ``indicators_snapshot/``
   — so a drifted experiment can still be reproduced bit-exactly after the live
   module changes.

The imported set is enumerated transitively by ``tools/indicator_imports.py``
(AST/text based — works on archived snapshots and basket recycle rules alike).

Parallel to ``tools/run_directive_snapshot.py`` (the directive snapshot) and the
``strategy.py`` snapshot. Used at every forward write point where those two are
written: the stage-1 run folder, the strategy provisioner, the basket capsule.

CLI (operator / future CI use)::

    python tools/run_indicator_snapshot.py verify <snapshot_dir> [--project-root DIR]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

# Allow standalone CLI use (`python tools/run_indicator_snapshot.py verify ...`):
# ensure the repo root is importable so `tools.*` / `config.*` resolve. No-op
# when imported normally (the caller already has the root on sys.path).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.indicator_imports import extract_imported_indicator_modules  # noqa: E402

INDICATOR_MANIFEST_NAME = "indicators_manifest.json"
INDICATOR_SNAPSHOT_DIRNAME = "indicators_snapshot"
MANIFEST_SCHEMA_VERSION = 1


class IndicatorSnapshotError(RuntimeError):
    """Raised by ``require_indicator_snapshot`` when the mandatory co-location of
    a strategy's indicator modules fails — so the rule can never be silently
    skipped at a write point where the source is definitionally available."""


class IndicatorDriftError(RuntimeError):
    """Raised by ``verify_indicator_snapshot`` when a live indicator module no
    longer matches the snapshotted hash (or has vanished) — i.e. the experiment
    is no longer reproducible against the live ``indicators/`` registry."""


def _sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_registry(project_root: Path):
    """Return the parsed indicator registry dict, or ``{}`` if unavailable.

    Tolerant by design: the snapshot is best-effort metadata, not an admission
    gate (``tools/semantic_validator.py`` owns the hard registry enforcement), so
    a missing/unparseable registry yields ``registry_version=None`` and
    ``in_registry=False`` rather than aborting the run.
    """
    reg = Path(project_root) / "indicators" / "INDICATOR_REGISTRY.yaml"
    if not reg.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _registry_module_paths(registry: dict) -> set[str]:
    paths: set[str] = set()
    for _name, entry in (registry.get("indicators") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("module_path"), str):
            paths.add(entry["module_path"])
    return paths


def build_indicator_manifest(source_py, project_root, *, retro_captured: bool = False) -> dict:
    """Build the indicator manifest dict for ``source_py`` (no files written).

    ``source_py`` is the ``.py`` whose indicator imports define the experiment
    (a ``strategy.py`` or a basket recycle rule). ``project_root`` must be the
    root the run imports indicators from, so hashes match what executed.
    """
    project_root = Path(project_root)
    registry = _read_registry(project_root)
    registered = _registry_module_paths(registry)

    modules = sorted(extract_imported_indicator_modules(source_py, project_root))
    mod_entries = []
    for module in modules:
        rel = Path(*module.split(".")).with_suffix(".py")
        abs_path = project_root / rel
        mod_entries.append(
            {
                "module": module,
                "file": f"{INDICATOR_SNAPSHOT_DIRNAME}/{rel.as_posix()}",
                "sha256": _sha256_file(abs_path),
                "in_registry": module in registered,
            }
        )

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": "run_indicator_snapshot",
        "source_file": Path(source_py).name,
        "registry_version": registry.get("registry_version"),
        "retro_captured": retro_captured,
        "module_count": len(mod_entries),
        "modules": mod_entries,
    }


def snapshot_indicators(
    target_dir,
    source_py,
    project_root,
    *,
    write_once: bool = True,
    retro_captured: bool = False,
) -> dict | None:
    """Write ``indicators_manifest.json`` + copy each imported module's source
    into ``target_dir/indicators_snapshot/`` and return a small summary dict.

    Returns None if ``source_py`` is missing. Write-once: if the manifest
    already exists it is NOT overwritten (mirrors Snapshot Immutability) and
    ``written=False`` is returned. Pass ``write_once=False`` at refreshable
    write points (the provisioner, which re-runs per re-provision).
    """
    target_dir = Path(target_dir)
    source_py = Path(source_py)
    project_root = Path(project_root)
    if not source_py.is_file():
        return None

    dest_manifest = target_dir / INDICATOR_MANIFEST_NAME
    if dest_manifest.exists() and write_once:
        existing = json.loads(dest_manifest.read_text(encoding="utf-8"))
        return {
            "manifest": INDICATOR_MANIFEST_NAME,
            "module_count": existing.get("module_count", 0),
            "written": False,
        }

    manifest = build_indicator_manifest(source_py, project_root, retro_captured=retro_captured)

    target_dir.mkdir(parents=True, exist_ok=True)
    for entry in manifest["modules"]:
        src = project_root / Path(*entry["module"].split(".")).with_suffix(".py")
        dst = target_dir / entry["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)  # byte-exact copy, mirrors the strategy.py snapshot

    dest_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest": INDICATOR_MANIFEST_NAME,
        "module_count": manifest["module_count"],
        "written": True,
    }


def require_indicator_snapshot(
    target_dir, source_py, project_root, *, write_once: bool = True
) -> dict:
    """MANDATORY co-location: the source ``.py`` MUST be present and snapshotable.

    Use at write points where the source is definitionally available (stage-1's
    just-copied ``strategy.py`` snapshot, the provisioner's written
    ``strategy.py``, the basket capsule's ``RECYCLE_RULE_SOURCE.py``). Raises
    ``IndicatorSnapshotError`` if the source is missing or the snapshot fails, so
    a run/provision CANNOT complete while silently dropping its indicator
    provenance (Fail-Fast, Invariant #1). Returns the summary dict on success.
    """
    if not source_py or not Path(source_py).is_file():
        raise IndicatorSnapshotError(
            f"indicator co-location is mandatory but the source .py is missing: {source_py!r}"
        )
    snap = snapshot_indicators(target_dir, source_py, project_root, write_once=write_once)
    if snap is None:  # only reachable if the file vanished mid-call
        raise IndicatorSnapshotError(f"indicator co-location failed for {source_py!r}")
    return snap


def verify_indicator_manifest(manifest: dict, project_root) -> list[str]:
    """Return drift error strings (empty list == clean) for a manifest dict.

    For each recorded module, recompute the sha256 of the corresponding LIVE
    module under ``project_root`` and collect an error string for any module that
    is missing or whose hash differs. Does NOT raise — returns the error list.

    The ``list[str]`` (empty == ok) convention matches
    ``replay_admission.contract.verify_indicator_provenance`` so the Replay
    Admission Phase-0 contract can consume this directly (it left that hook
    explicitly deferred to "the indicators_manifest.json the chip defines").
    """
    project_root = Path(project_root)
    errors: list[str] = []
    for entry in manifest.get("modules", []):
        module = entry["module"]
        expected = entry["sha256"]
        live = project_root / Path(*module.split(".")).with_suffix(".py")
        if not live.is_file():
            errors.append(f"{module}: MISSING live module (snapshot sha {expected[:12]})")
            continue
        actual = _sha256_file(live)
        if actual != expected:
            errors.append(
                f"{module}: HASH DRIFT (snapshot {expected[:12]} != live {actual[:12]})"
            )
    return errors


def verify_indicator_snapshot(snapshot_dir, project_root=None) -> dict:
    """Recompute live indicator hashes and FAIL LOUD on any drift.

    Reads ``snapshot_dir/indicators_manifest.json`` and, for each recorded
    module, recomputes the sha256 of the corresponding LIVE module under
    ``project_root``. Raises ``IndicatorDriftError`` listing every module that is
    missing or whose hash differs. Returns a summary dict when everything
    matches.

    ``project_root`` defaults to the real repo root (``config.path_authority``)
    — the canonical home of the live ``indicators/`` registry, resolved correctly
    even from a worktree. This is the verification the Replay Admission contract
    runs before re-executing a bundle (see REPLAY_ADMISSION_DESIGN_2026-06-29);
    ``verify_indicator_manifest`` is the non-raising, manifest-dict form that
    contract's ``verify_indicator_provenance`` hook can call.
    """
    snapshot_dir = Path(snapshot_dir)
    manifest_path = snapshot_dir / INDICATOR_MANIFEST_NAME
    if not manifest_path.is_file():
        raise IndicatorDriftError(
            f"no {INDICATOR_MANIFEST_NAME} found in {snapshot_dir} — cannot verify "
            f"indicator reproducibility (snapshot missing)."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if project_root is None:
        from config.path_authority import REAL_REPO_ROOT

        project_root = REAL_REPO_ROOT

    drift = verify_indicator_manifest(manifest, project_root)
    if drift:
        raise IndicatorDriftError(
            f"indicator drift vs snapshot {manifest_path}:\n  "
            + "\n  ".join(drift)
            + "\nThe snapshotted experiment is no longer reproducible against the live "
            "indicators/ registry. Reproduce from indicators_snapshot/ source copies, "
            "or re-run as a new experiment."
        )

    return {
        "verified": True,
        "module_count": manifest.get("module_count", 0),
        "registry_version": manifest.get("registry_version"),
        "retro_captured": manifest.get("retro_captured", False),
    }


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="fail loud if live indicators drifted from the snapshot")
    v.add_argument("snapshot_dir", help="a run/strategy/capsule dir containing indicators_manifest.json")
    v.add_argument("--project-root", default=None, help="root holding the live indicators/ (default: real repo)")
    args = ap.parse_args(argv)

    if args.cmd == "verify":
        try:
            summary = verify_indicator_snapshot(args.snapshot_dir, args.project_root)
        except IndicatorDriftError as exc:
            print(f"[INDICATOR-DRIFT] {exc}")
            return 1
        print(
            f"[INDICATOR-OK] {args.snapshot_dir}: {summary['module_count']} module(s) match "
            f"(registry_version={summary['registry_version']}"
            + (", retro-captured" if summary["retro_captured"] else "")
            + ")"
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main())
