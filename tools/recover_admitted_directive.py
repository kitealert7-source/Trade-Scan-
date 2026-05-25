"""Recover a directive's canonical content by id.

Lookup order: live (any backtest_directives subdir) -> quarantine
(TradeScan_State/quarantine/*/directives/) -> git history. Returns
provenance for whichever source wins.

Usage:
  python tools/recover_admitted_directive.py <DIRECTIVE_ID>
  python tools/recover_admitted_directive.py <DIRECTIVE_ID> --json
  python tools/recover_admitted_directive.py <DIRECTIVE_ID> --write [--dest PATH]

--json emits a single-line machine-readable record with source_type,
recovered_path, sha256, size_bytes, line_count, and (for git recoveries)
commit_sha + blob_sha + commit_timestamp_utc — for governance automation.

--write commits the recovered bytes to backtest_directives/completed/<id>.txt
(or --dest if supplied). Refuses to overwrite an existing non-empty file
unless --force.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE

LIVE_SUBDIRS = ("INBOX", "active", "active_backup", "completed", "archive")
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
QUARANTINE_ROOT = TRADE_SCAN_STATE / "quarantine"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def find_live(directive_id: str, directives_root: Path = DIRECTIVES_ROOT) -> Path | None:
    for sub in LIVE_SUBDIRS:
        candidate = directives_root / sub / f"{directive_id}.txt"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def find_quarantine(directive_id: str, quarantine_root: Path = QUARANTINE_ROOT) -> Path | None:
    """Return the most recent quarantined copy by parent timestamp prefix, else None."""
    if not quarantine_root.exists():
        return None
    hits: list[Path] = []
    for sweep_dir in quarantine_root.iterdir():
        if not sweep_dir.is_dir():
            continue
        candidate = sweep_dir / "directives" / f"{directive_id}.txt"
        if candidate.is_file() and candidate.stat().st_size > 0:
            hits.append(candidate)
    if not hits:
        return None
    return max(hits, key=lambda p: p.parent.parent.name)


def find_git(
    directive_id: str,
    project_root: Path = PROJECT_ROOT,
    live_subdirs: tuple[str, ...] = LIVE_SUBDIRS,
) -> dict | None:
    """Return provenance dict for newest non-empty git blob, else None."""
    candidate_paths = [f"backtest_directives/{sub}/{directive_id}.txt" for sub in live_subdirs]

    seen: set[str] = set()
    commits: list[tuple[str, int, str]] = []
    for rel in candidate_paths:
        rc, out, _ = _git(["log", "--all", "--format=%H %ct", "--", rel], cwd=project_root)
        if rc != 0 or not out.strip():
            continue
        for line in out.strip().splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            sha, ts = parts[0], int(parts[1])
            if sha in seen:
                continue
            seen.add(sha)
            commits.append((sha, ts, rel))

    commits.sort(key=lambda c: c[1], reverse=True)

    for sha, ts, rel in commits:
        rc, content, _ = _git(["show", f"{sha}:{rel}"], cwd=project_root)
        if rc != 0 or not content or not content.strip():
            continue
        blob_sha = _git_blob_sha(sha, rel, cwd=project_root)
        return {
            "content": content,
            "source_path": rel,
            "commit_sha": sha,
            "blob_sha": blob_sha,
            "commit_timestamp_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        }
    return None


def _git(args: list[str], *, cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(
        ["git", *args],
        capture_output=True, text=True, cwd=str(cwd),
        encoding="utf-8", errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def _git_blob_sha(commit_sha: str, rel_path: str, *, cwd: Path) -> str | None:
    rc, out, _ = _git(["rev-parse", f"{commit_sha}:{rel_path}"], cwd=cwd)
    if rc == 0:
        return out.strip()
    return None


def recover_directive(
    directive_id: str,
    *,
    project_root: Path = PROJECT_ROOT,
    state_root: Path = TRADE_SCAN_STATE,
) -> dict | None:
    """Return the first successful recovery's provenance, or None if all sources fail."""
    directives_root = project_root / "backtest_directives"
    quarantine_root = state_root / "quarantine"

    live = find_live(directive_id, directives_root)
    if live is not None:
        content = live.read_text(encoding="utf-8")
        data = content.encode("utf-8")
        try:
            rel = str(live.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            rel = str(live)
        return {
            "directive_id": directive_id,
            "source_type": "live",
            "recovered_path": rel,
            "size_bytes": len(data),
            "sha256": _sha256(data),
            "line_count": _line_count(content),
            "content": content,
        }

    q = find_quarantine(directive_id, quarantine_root)
    if q is not None:
        content = q.read_text(encoding="utf-8")
        data = content.encode("utf-8")
        try:
            rel = str(q.relative_to(state_root)).replace("\\", "/")
            rel = f"TradeScan_State/{rel}"
        except ValueError:
            rel = str(q)
        return {
            "directive_id": directive_id,
            "source_type": "quarantine",
            "recovered_path": rel,
            "size_bytes": len(data),
            "sha256": _sha256(data),
            "line_count": _line_count(content),
            "content": content,
        }

    g = find_git(directive_id, project_root)
    if g is not None:
        content = g["content"]
        data = content.encode("utf-8")
        return {
            "directive_id": directive_id,
            "source_type": "git",
            "recovered_path": g["source_path"],
            "size_bytes": len(data),
            "sha256": _sha256(data),
            "line_count": _line_count(content),
            "commit_sha": g["commit_sha"],
            "blob_sha": g["blob_sha"],
            "commit_timestamp_utc": g["commit_timestamp_utc"],
            "content": content,
        }

    return None


def _print_human(provenance: dict) -> None:
    print(f"directive_id:    {provenance['directive_id']}")
    print(f"source_type:     {provenance['source_type']}")
    print(f"recovered_path:  {provenance['recovered_path']}")
    print(f"size_bytes:      {provenance['size_bytes']}")
    print(f"line_count:      {provenance['line_count']}")
    print(f"sha256:          {provenance['sha256']}")
    if provenance["source_type"] == "git":
        print(f"commit_sha:      {provenance['commit_sha']}")
        print(f"blob_sha:        {provenance['blob_sha']}")
        print(f"commit_ts_utc:   {provenance['commit_timestamp_utc']}")


def _print_json(provenance: dict) -> None:
    payload = {k: v for k, v in provenance.items() if k != "content"}
    print(json.dumps(payload))


def _write_restored(
    provenance: dict,
    *,
    dest: Path,
    force: bool,
) -> None:
    if dest.exists() and dest.stat().st_size > 0 and not force:
        raise SystemExit(
            f"[recover_admitted_directive] refusing to overwrite non-empty {dest} "
            "(pass --force to override)"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(provenance["content"], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directive_id", help="Directive id (filename stem without .txt)")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable JSON output (one line, no `content` field).")
    parser.add_argument("--write", action="store_true",
                        help="Write recovered content to backtest_directives/completed/<id>.txt.")
    parser.add_argument("--dest", type=Path, default=None,
                        help="Custom destination path (with --write).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite non-empty destination with --write.")
    args = parser.parse_args(argv)

    provenance = recover_directive(
        args.directive_id,
        project_root=PROJECT_ROOT,
        state_root=TRADE_SCAN_STATE,
    )
    if provenance is None:
        msg = {"directive_id": args.directive_id, "source_type": None,
               "error": "not_found_in_live_quarantine_or_git"}
        if args.json:
            print(json.dumps(msg))
        else:
            print(f"[recover_admitted_directive] {args.directive_id}: NOT FOUND "
                  f"in live, quarantine, or git history")
        return 2

    if args.write:
        dest = args.dest if args.dest is not None else (
            PROJECT_ROOT / "backtest_directives" / "completed" / f"{args.directive_id}.txt"
        )
        _write_restored(provenance, dest=dest, force=args.force)
        provenance["written_to"] = str(dest).replace("\\", "/")

    if args.json:
        _print_json(provenance)
    else:
        _print_human(provenance)
        if "written_to" in provenance:
            print(f"written_to:      {provenance['written_to']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
