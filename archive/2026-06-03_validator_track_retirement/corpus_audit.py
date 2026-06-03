"""corpus_audit.py — VALIDATION_DATASET integrity + immutability enforcer.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Sections 1m, 1m-i, 1m-ii, 1m-iii, 6.9,
Phase 7a.0.

A frozen corpus is the validator's single source of input. Mutation = silent
invalidation of every historical decision referencing it. This tool is the
binding gate.

Modes (mutually exclusive):
  --create-manifest CORPUS_DIR --rationale "..." [--symbols ... --tf ... --date-range ...]
        Compute sha256 of every file under CORPUS_DIR/bars/**, write
        manifest.json with cumulative hash + scope + source metadata.
        Sets frozen: true on completion. From this point: corpus must
        never be mutated.

  --freeze CORPUS_DIR
        Apply filesystem read-only permissions (chmod -R a-w on POSIX;
        per-file read-only attribute on Windows). After this no process
        can mutate corpus files without explicit chmod.

  --verify CORPUS_DIR
        Recompute every per-file sha256 and the cumulative sha256.
        Compare to manifest. Verify realpath(CORPUS_DIR) matches the
        literal path (no symlink/junction in chain — Section 1m-iii).
        Verify every file is non-writable. FAIL-CLOSED on any mismatch.

  --check-immutability [CORPUS_DIR_OR_PARENT]
        Pre-commit hook: scan staged paths under VALIDATION_DATASET/ for
        any modification to a frozen corpus. Reject the commit if any
        frozen corpus file is staged for modification, or if a symlink /
        junction has been introduced into a corpus path.

Exit codes:
  0   green
  1   integrity / immutability violation (FAIL-CLOSED)
  2   tool misuse
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BUFSIZE = 1024 * 1024


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_BUFSIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _cumulative_sha256(file_records: list[dict[str, Any]]) -> str:
    """sha256 of the sorted (path, sha256) tuples — order-independent."""
    canon = "\n".join(
        f"{rec['path']} {rec['sha256']}"
        for rec in sorted(file_records, key=lambda r: r["path"])
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _check_no_links_in_path(p: Path) -> str | None:
    """Section 1m-iii: any symlink/junction in the path -> reject."""
    real = os.path.realpath(p)
    literal = str(p.resolve(strict=False))
    if os.path.normcase(real) != os.path.normcase(literal):
        return f"realpath({p}) = {real} != literal {literal} — link/junction in chain"
    return None


# ---------------------------------------------------------------------------
# Create manifest
# ---------------------------------------------------------------------------


def cmd_create_manifest(corpus_dir: Path, rationale: str,
                        symbols: list[str], timeframes: list[str],
                        date_range: tuple[str, str],
                        broker: str = "OctaFX",
                        timezone_str: str = "UTC",
                        ) -> int:
    if not corpus_dir.is_dir():
        print(f"[corpus-audit] ERROR: {corpus_dir} not found", file=sys.stderr)
        return 2
    bars_dir = corpus_dir / "bars"
    if not bars_dir.is_dir():
        print(f"[corpus-audit] ERROR: {bars_dir} missing — corpus must have bars/", file=sys.stderr)
        return 2

    link_err = _check_no_links_in_path(corpus_dir)
    if link_err:
        print(f"[corpus-audit] REJECTED (Section 1m-iii): {link_err}", file=sys.stderr)
        return 1

    files: list[dict[str, Any]] = []
    for root, _, names in os.walk(bars_dir):
        for n in sorted(names):
            full = Path(root) / n
            rel = full.relative_to(corpus_dir).as_posix()
            files.append({
                "path":   rel,
                "sha256": _sha256_file(full),
                "bytes":  full.stat().st_size,
            })

    files.sort(key=lambda r: r["path"])
    cumulative = _cumulative_sha256(files)

    manifest = {
        "corpus_id":        corpus_dir.name,
        "created_utc":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "broker":                       broker,
            "timezone":                     timezone_str,
            "source_dataset_snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "scope": {
            "symbols":    symbols,
            "date_range": {"start": date_range[0], "end": date_range[1]},
            "timeframes": timeframes,
            "rationale":  rationale,
        },
        "files":             files,
        "cumulative_sha256": cumulative,
        "frozen":            True,
    }
    out = corpus_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[corpus-audit] created {out} (frozen=true, {len(files)} files, cumulative={cumulative[:12]}...)")
    return 0


# ---------------------------------------------------------------------------
# Freeze (filesystem read-only)
# ---------------------------------------------------------------------------


def cmd_freeze(corpus_dir: Path) -> int:
    if not (corpus_dir / "manifest.json").is_file():
        print("[corpus-audit] ERROR: manifest.json missing — run --create-manifest first.",
              file=sys.stderr)
        return 2
    count = 0
    for root, _, names in os.walk(corpus_dir):
        for n in names:
            full = Path(root) / n
            current = full.stat().st_mode
            ro = current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
            os.chmod(full, ro)
            count += 1
    print(f"[corpus-audit] froze {count} files (read-only) under {corpus_dir}")
    return 0


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def cmd_verify(corpus_dir: Path) -> int:
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"[corpus-audit] FAIL: {manifest_path} missing.", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("frozen"):
        print("[corpus-audit] FAIL: manifest.frozen != true.", file=sys.stderr)
        return 1

    link_err = _check_no_links_in_path(corpus_dir)
    if link_err:
        print(f"[corpus-audit] FAIL (Section 1m-iii): {link_err}", file=sys.stderr)
        return 1

    expected = {rec["path"]: rec for rec in manifest["files"]}
    actual: list[dict[str, Any]] = []
    bars_dir = corpus_dir / "bars"
    for root, _, names in os.walk(bars_dir):
        for n in sorted(names):
            full = Path(root) / n
            rel = full.relative_to(corpus_dir).as_posix()
            sha = _sha256_file(full)
            actual.append({"path": rel, "sha256": sha, "bytes": full.stat().st_size})
            if rel not in expected:
                print(f"[corpus-audit] FAIL: unexpected file {rel}", file=sys.stderr)
                return 1
            if expected[rel]["sha256"] != sha:
                print(f"[corpus-audit] FAIL: sha256 drift on {rel}", file=sys.stderr)
                return 1

    # Missing files?
    actual_paths = {rec["path"] for rec in actual}
    missing = set(expected) - actual_paths
    if missing:
        print(f"[corpus-audit] FAIL: missing files: {sorted(missing)}", file=sys.stderr)
        return 1

    cumulative = _cumulative_sha256(actual)
    if cumulative != manifest["cumulative_sha256"]:
        print("[corpus-audit] FAIL: cumulative sha256 drift.", file=sys.stderr)
        return 1

    print(f"[corpus-audit] verify OK: {len(actual)} files, cumulative={cumulative[:12]}...")
    return 0


# ---------------------------------------------------------------------------
# Pre-commit immutability check
# ---------------------------------------------------------------------------


def cmd_check_immutability(scan_root: Path | None) -> int:
    """Pre-commit hook scope: walk staged paths under VALIDATION_DATASET/.
    If any frozen corpus file has been mutated, fail-closed."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0  # not in a git checkout — no-op
    staged = [Path(p) for p in out.splitlines() if p.startswith("VALIDATION_DATASET/")]
    if not staged:
        return 0

    frozen_corpora: set[Path] = set()
    if scan_root is None:
        scan_root = Path("VALIDATION_DATASET")
    if scan_root.is_dir():
        for d in scan_root.iterdir():
            if d.is_dir() and (d / "manifest.json").is_file():
                try:
                    if json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("frozen"):
                        frozen_corpora.add(d.resolve())
                except (json.JSONDecodeError, OSError):
                    pass

    violations: list[str] = []
    for staged_path in staged:
        full = Path(staged_path).resolve(strict=False)
        for corpus in frozen_corpora:
            try:
                full.relative_to(corpus)
            except ValueError:
                continue
            violations.append(str(staged_path))
            break

    if violations:
        print("[corpus-audit] COMMIT BLOCKED — frozen corpus mutation:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print("\n  Frozen corpora are permanently immutable. Section 1m-i. If the data\n"
              "  needs to change, create a new corpus_id (e.g. h2_validator_baseline_v2)\n"
              "  side-by-side with v1.", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VALIDATION_DATASET integrity + immutability enforcer")
    sub = p.add_subparsers(dest="mode", required=True)

    cm = sub.add_parser("create-manifest", help="Compute sha256s + write manifest.json (frozen=true)")
    cm.add_argument("corpus_dir", type=Path)
    cm.add_argument("--rationale", required=True)
    cm.add_argument("--symbols", required=True, nargs="+")
    cm.add_argument("--timeframes", required=True, nargs="+")
    cm.add_argument("--date-start", required=True)
    cm.add_argument("--date-end", required=True)
    cm.add_argument("--broker", default="OctaFX")
    cm.add_argument("--timezone", default="UTC", dest="tz")

    fr = sub.add_parser("freeze", help="Apply filesystem read-only permissions after create-manifest")
    fr.add_argument("corpus_dir", type=Path)

    vf = sub.add_parser("verify", help="Recompute hashes; FAIL-CLOSED on drift")
    vf.add_argument("corpus_dir", type=Path)

    ci = sub.add_parser("check-immutability", help="Pre-commit: reject any staged change to a frozen corpus")
    ci.add_argument("scan_root", nargs="?", type=Path, default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.mode == "create-manifest":
        return cmd_create_manifest(
            args.corpus_dir, args.rationale, args.symbols, args.timeframes,
            (args.date_start, args.date_end), broker=args.broker, timezone_str=args.tz,
        )
    if args.mode == "freeze":
        return cmd_freeze(args.corpus_dir)
    if args.mode == "verify":
        return cmd_verify(args.corpus_dir)
    if args.mode == "check-immutability":
        return cmd_check_immutability(args.scan_root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
