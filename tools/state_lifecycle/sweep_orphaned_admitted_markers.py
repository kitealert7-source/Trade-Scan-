"""One-shot sweep of orphaned .txt.admitted sentinels in backtest_directives/completed/.

Background — admission (run_pipeline.admit_directive) creates each
<id>.txt.admitted as a 0-byte sentinel via `marker_path.touch()` alongside
the <id>.txt. The 2026-05-22 pipeline-state-cleanup moved 274 .txt files
to quarantine without their sidecar markers (the scan globbed *.txt only;
fixed in commit 0933560). That left orphaned markers in completed/ — files
that look like "truncated directives" but were never directive content
themselves.

This tool quarantines those orphans to a dated subdirectory under
../TradeScan_State/quarantine/<ts>_admitted_orphan_sweep/ and emits a
manifest with per-marker provenance (original path, quarantine destination,
size, mtime, sha256) for deterministic reconstruction if ever needed.

Default mode is dry-run. Pass --execute to commit the moves.

Scope: only orphan markers in backtest_directives/completed/. Paired
markers (with surviving <id>.txt sibling) are untouched — those are
handled by lineage_pruner's quarantine sweep (Step 1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE

DEFAULT_DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives" / "completed"
DEFAULT_QUARANTINE_ROOT = TRADE_SCAN_STATE / "quarantine"
SIDECAR_SUFFIX = ".txt.admitted"


def find_orphan_markers(directives_dir: Path) -> list[Path]:
    """Return .txt.admitted files in directives_dir whose <id>.txt sibling is missing."""
    if not directives_dir.exists():
        return []
    orphans: list[Path] = []
    for marker in sorted(directives_dir.glob(f"*{SIDECAR_SUFFIX}")):
        if not marker.is_file():
            continue
        sibling = marker.with_name(marker.name[: -len(".admitted")])
        if not sibling.exists():
            orphans.append(marker)
    return orphans


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_entry(marker: Path, dest: Path) -> dict:
    stat = marker.stat()
    return {
        "original_path": str(marker.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "quarantine_destination": str(dest).replace("\\", "/"),
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": _sha256(marker),
    }


def sweep_orphan_markers(
    directives_dir: Path,
    quarantine_root: Path,
    *,
    execute: bool,
    timestamp: str | None = None,
) -> dict:
    """Find and (optionally) move orphan markers, returning the manifest dict.

    Manifest is written to disk only when execute=True. Dry-run returns the
    same dict structure with `executed: false` and prospective destinations.
    """
    ts = timestamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sweep_dir = quarantine_root / f"{ts}_admitted_orphan_sweep"
    markers_dir = sweep_dir / "markers"

    orphans = find_orphan_markers(directives_dir)
    entries: list[dict] = []
    moved = 0
    skipped: list[dict] = []

    if execute and orphans:
        markers_dir.mkdir(parents=True, exist_ok=True)

    for marker in orphans:
        dest = markers_dir / marker.name
        try:
            entry = _manifest_entry(marker, dest)
        except FileNotFoundError:
            skipped.append({"path": str(marker), "reason": "vanished_before_hash"})
            continue
        entries.append(entry)
        if execute:
            try:
                shutil.move(str(marker), str(dest))
                moved += 1
            except Exception as exc:
                skipped.append({"path": str(marker), "reason": f"move_failed: {exc}"})

    manifest = {
        "tool": "sweep_orphaned_admitted_markers",
        "tool_version": "1",
        "timestamp_utc": ts,
        "directives_dir": str(directives_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "quarantine_sweep_dir": str(sweep_dir).replace("\\", "/"),
        "executed": execute,
        "orphans_found": len(orphans),
        "moved": moved,
        "skipped": skipped,
        "entries": entries,
    }

    if execute and orphans:
        manifest_path = sweep_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path).replace("\\", "/")

    return manifest


def _print_summary(manifest: dict, *, preview_lines: int = 10) -> None:
    mode = "EXECUTE" if manifest["executed"] else "DRY-RUN"
    print(f"[sweep_orphans] mode={mode}  ts={manifest['timestamp_utc']}")
    print(f"[sweep_orphans] scanned: {manifest['directives_dir']}")
    print(f"[sweep_orphans] orphans found: {manifest['orphans_found']}")
    if manifest["executed"]:
        print(f"[sweep_orphans] moved: {manifest['moved']}")
        if manifest["skipped"]:
            print(f"[sweep_orphans] skipped: {len(manifest['skipped'])}")
        if "manifest_path" in manifest:
            print(f"[sweep_orphans] manifest: {manifest['manifest_path']}")
    else:
        print(f"[sweep_orphans] would move to: {manifest['quarantine_sweep_dir']}/markers/")
    if manifest["entries"]:
        shown = manifest["entries"][:preview_lines]
        print(f"[sweep_orphans] preview ({len(shown)} of {len(manifest['entries'])}):")
        for e in shown:
            print(f"  {e['sha256'][:12]}  {e['size_bytes']:>4}B  {e['original_path']}")
        if len(manifest["entries"]) > preview_lines:
            print(f"  ... and {len(manifest['entries']) - preview_lines} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Commit the moves. Default is dry-run.",
    )
    parser.add_argument(
        "--directives-dir",
        type=Path,
        default=DEFAULT_DIRECTIVES_DIR,
        help=f"Directory to scan. Default: {DEFAULT_DIRECTIVES_DIR}",
    )
    parser.add_argument(
        "--quarantine-root",
        type=Path,
        default=DEFAULT_QUARANTINE_ROOT,
        help=f"Quarantine root. Default: {DEFAULT_QUARANTINE_ROOT}",
    )
    args = parser.parse_args(argv)

    manifest = sweep_orphan_markers(
        directives_dir=args.directives_dir,
        quarantine_root=args.quarantine_root,
        execute=args.execute,
    )
    _print_summary(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
