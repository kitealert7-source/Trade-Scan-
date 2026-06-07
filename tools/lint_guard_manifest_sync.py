#!/usr/bin/env python3
"""
Pre-commit guard: tools_manifest.json must be regenerated AND restaged
whenever a Critical-Guard-Set tool changes in the same commit.

Why this exists
---------------
Editing a guarded tool (run_pipeline.py, pipeline_utils.py, the basket
spine, ...) without regenerating tools/tools_manifest.json does NOT fail at
commit time today -- it surfaces LATER, at run_pipeline.py startup, where
verify_tools_timestamp_guard hard-blocks with "Tool content hash mismatch
...". That block is correct but lands far from the edit, mid-task. This
lint moves the signal to commit time so the fix (regen + git add) is one
paste away and in-context.

It is the commit-time twin of the engine_abi gate (abi_audit --pre-commit)
and of the runtime tools-manifest guard. CHECK ONLY -- it never mutates a
file (no auto-regen): a guarded change without a matching restaged manifest
is reported and the commit is blocked. The human runs the regen.

Detection (strict: STAGED content, not the working tree)
--------------------------------------------------------
For each changed guarded tool, the *staged* blob (`git show :<path>`) is
canonical-hashed and compared to the hash recorded in the *staged*
tools_manifest.json. Comparing staged blobs -- not the on-disk working tree
-- is what catches the "regenerated the manifest but forgot to `git add`
it" case: the working tree looks self-consistent, yet the commit captures a
stale manifest that breaks a fresh checkout / CI / the runtime guard.

The guarded-tool list is imported from generate_guard_manifest.GUARD_FILES
(single source of truth -- no second copy of the list).

Scope: only guarded tools changed *in this commit* are checked. A stale
manifest entry for an unchanged guarded tool is the runtime guard's job.

Usage:  python tools/lint_guard_manifest_sync.py --staged
Exit:   0 = OK / nothing to check ; 1 = guarded tool out of sync.
        Infrastructure errors (no git, unreadable index, ...) fail OPEN
        (warn to stderr, exit 0) so this gate never blocks a commit for a
        reason unrelated to its job; the runtime guard remains the backstop.

Authority: AGENT.md -- Protected Infrastructure Policy. Reference: pipeline
gotcha #5 (regen tools_manifest after any tool change).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.generate_guard_manifest import GUARD_FILES  # noqa: E402

MANIFEST_REL = "tools/tools_manifest.json"
TOOLS_PREFIX = "tools/"


def _canonical_sha256_bytes(data: bytes) -> str:
    """LF-normalized sha256 (lowercase hex) of *data*.

    Mirrors tools.verify_engine_integrity.canonical_sha256 but operates on
    bytes (a git index blob) so this pre-commit lint stays dependency-light
    and unit-testable without writing a temp file. The CRLF->LF normalization
    makes the result identical to the manifest hash regardless of whether the
    blob is stored LF (autocrlf) or CRLF. Pinned to the authoritative hasher
    by test_lint_guard_manifest_sync.py::test_canonical_hash_matches_
    authoritative -- if the canonical definition ever diverges there, that
    test fails and forces this to follow.
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def check_staged(
    staged_paths: list[str],
    read_staged_blob: Callable[[str], bytes],
    guard_files: list[str] | None = None,
) -> list[str]:
    """Pure core. Return a list of human-readable problems ([] == OK).

    staged_paths     : repo-relative paths (forward slashes) in the staged set.
    read_staged_blob : path -> staged (index) bytes for that path.
    """
    guard_files = guard_files if guard_files is not None else GUARD_FILES
    staged = set(staged_paths)

    # guarded repo-path -> manifest key (the key IS the GUARD_FILES entry).
    changed = [(f"{TOOLS_PREFIX}{g}", g) for g in guard_files
               if f"{TOOLS_PREFIX}{g}" in staged]
    if not changed:
        return []

    if MANIFEST_REL not in staged:
        return [
            f"{path}: guarded tool changed but {MANIFEST_REL} is not staged"
            for path, _ in changed
        ]

    try:
        manifest = json.loads(read_staged_blob(MANIFEST_REL).decode("utf-8"))
        recorded = {k: (v or "").upper()
                    for k, v in manifest.get("file_hashes", {}).items()}
    except Exception as e:  # noqa: BLE001 -- any parse failure is a real fault
        return [f"{MANIFEST_REL}: staged manifest unreadable ({e})"]

    problems: list[str] = []
    for path, key in changed:
        actual = _canonical_sha256_bytes(read_staged_blob(path)).upper()
        rec = recorded.get(key)
        if rec is None:
            problems.append(f"{path}: not present in staged {MANIFEST_REL}")
        elif rec != actual:
            problems.append(
                f"{path}: staged hash {actual[:12]}... != "
                f"manifest {rec[:12]}..."
            )
    return problems


# --- git plumbing (thin wrappers; failures bubble to main's fail-open) ----

def _git_staged_paths() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        cwd=PROJECT_ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _git_read_staged_blob(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f":{path}"],
        cwd=PROJECT_ROOT, capture_output=True, check=True,
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-commit: a changed guarded tool requires a restaged "
                    "tools_manifest.json."
    )
    parser.add_argument("--staged", action="store_true",
                        help="Check the staged change set (the only mode).")
    args = parser.parse_args(argv)
    if not args.staged:
        parser.error("only --staged mode is supported")

    try:
        staged = _git_staged_paths()
        problems = check_staged(staged, _git_read_staged_blob)
    except Exception as e:  # fail OPEN -- never block a commit on tooling error
        sys.stderr.write(
            f"[guard-manifest][WARN] sync check skipped (tooling error: {e})\n"
        )
        return 0

    if not problems:
        return 0

    sys.stderr.write(
        "[guard-manifest] COMMIT BLOCKED -- guarded tool(s) changed without a "
        "matching tools_manifest.json:\n"
    )
    for p in problems:
        sys.stderr.write(f"    - {p}\n")
    sys.stderr.write(
        "\nThe run_pipeline startup guard would hard-block the next pipeline "
        "run.\nFix:\n"
        "    python tools/generate_guard_manifest.py\n"
        "    git add tools/tools_manifest.json\n"
        "then re-commit.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
