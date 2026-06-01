"""basket_provenance.py — per-run code snapshot for basket directives.

Brings basket runs to provenance parity with single-strategy runs. A
single-strategy run snapshots its strategy.py into runs/<run_id>/strategy.py
(write-once; Snapshot Immutability, AGENT.md #4) so the run record pins the
exact code that executed. Basket runs instead import their leg strategies
(tools/recycle_strategies.py) and recycle rule (tools/recycle_rules/<rule>.py)
live from tools/, so without a snapshot a past basket run cannot be reproduced
once that shared code changes — the run records only `rule_name@version`, a
symbolic reference whose code can drift.

This module copies the EXACT leg-strategy + rule source files that executed
(resolved via inspect.getsourcefile) into runs/<run_id>/basket_code/,
write-once, with a code_manifest.json recording each file's canonical
(LF-normalized) sha256 + rule_name@version + the leg-strategy class names.

Scope: provenance only — a record of what ran. It does NOT change execution
(the run still imports live, unlike the single-strategy load-from-snapshot
path). Home: the run folder (prunable). Per operator direction 2026-06-01,
per-run provenance belongs in the prunable run folder, NOT DRY_RUN_VAULT,
which is a curated store for promotable artifacts only.
"""
from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

from tools.recycle_rules import rule_class_for
from tools.verify_engine_integrity import canonical_sha256


SNAPSHOT_DIRNAME = "basket_code"
MANIFEST_NAME = "code_manifest.json"


class BasketProvenanceError(RuntimeError):
    """Raised when a write-once basket_code snapshot would be overwritten by
    different code (snapshot drift / tamper-evidence)."""


def _rel_under_tools(src: Path, project_root: Path) -> str:
    """Path of a source file relative to tools/ (so recycle_rules/<x>.py keeps
    its subdir), else the bare filename if it lives outside tools/."""
    try:
        return src.resolve().relative_to((project_root / "tools").resolve()).as_posix()
    except Exception:
        return src.name


def collect_basket_source_files(rule_name: str, rule_version, leg_strategies,
                                *, project_root) -> dict[str, Path]:
    """Resolve the unique source files that defined the executed rule + leg
    strategies. Returns {relpath_under_tools: absolute Path}, rule first.
    Resolution failures are skipped (provenance is best-effort, never fatal).
    """
    project_root = Path(project_root)
    files: dict[str, Path] = {}

    try:
        rule_cls = rule_class_for(rule_name, int(rule_version))
        rsrc = inspect.getsourcefile(rule_cls)
        if rsrc:
            p = Path(rsrc)
            files[_rel_under_tools(p, project_root)] = p
    except Exception:
        pass

    for strat in (leg_strategies or {}).values():
        try:
            ssrc = inspect.getsourcefile(type(strat))
            if ssrc:
                p = Path(ssrc)
                files[_rel_under_tools(p, project_root)] = p
        except Exception:
            continue

    return files


def snapshot_basket_code(run_dir, *, rule_name: str, rule_version,
                         leg_strategies, project_root) -> dict:
    """Write runs/<run_id>/basket_code/ with the executed source files +
    code_manifest.json, then return the manifest dict.

    Write-once: if the snapshot already exists, verify its recorded hashes
    match the current code and return the prior manifest; raise
    BasketProvenanceError on any drift (mirrors Snapshot Immutability).
    """
    run_dir = Path(run_dir)
    project_root = Path(project_root)
    snap_dir = run_dir / SNAPSHOT_DIRNAME
    manifest_path = snap_dir / MANIFEST_NAME

    files = collect_basket_source_files(
        rule_name, rule_version, leg_strategies, project_root=project_root,
    )
    hashes = {rel: canonical_sha256(src).lower() for rel, src in files.items()}
    classes = sorted({type(s).__name__ for s in (leg_strategies or {}).values()})
    manifest = {
        "rule": f"{rule_name}@{rule_version}",
        "rule_name": rule_name,
        "rule_version": int(rule_version),
        "leg_strategy_classes": classes,
        "files": hashes,  # relpath under tools/ -> canonical (LF) sha256
    }

    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("files") != hashes:
            raise BasketProvenanceError(
                f"basket_code snapshot drift in {snap_dir}: existing manifest "
                f"hashes do not match current code. A run folder's code "
                f"snapshot is write-once (Snapshot Immutability)."
            )
        return prior

    snap_dir.mkdir(parents=True, exist_ok=True)
    for rel, src in files.items():
        dest = snap_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)  # exact byte copy, mirrors the strategy.py snapshot
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
