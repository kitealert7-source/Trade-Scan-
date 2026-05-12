"""Pre-commit lint — block adding an indicator module without a registry entry.

Process (2026-05-12 governance):
  1. Author writes `indicators/<category>/<name>.py`.
  2. Author updates `indicators/INDICATOR_REGISTRY.yaml` with an entry whose
     `module_path` matches the dotted path of the new file.
  3. Author stages BOTH files together.
  4. This hook fires: if any added `.py` under `indicators/` is missing
     from the staged registry → commit blocked.
  5. Stage-0.5 (`tools/semantic_validator.py`) provides the runtime defence
     at directive admission. This hook is the earlier defence so drift
     never lands in the first place.

Scope: only `git diff --cached --diff-filter=A` (ADDED). Modifications and
deletions are not enforced here — modifying a registered indicator does
not require a registry change, and deletions require a governance
decision that is out of scope for an automated lint.

Run modes:
  - `--staged`   scan only staged ADDED files (pre-commit hook mode).
  - `--check`    scan the full disk vs working-tree registry (ad-hoc).
  - default      same as --check.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH_REL = "indicators/INDICATOR_REGISTRY.yaml"


def _load_registry_module_paths_from_staged() -> set[str]:
    """Return module_path set from the STAGED version of the registry.

    Reads `git show :indicators/INDICATOR_REGISTRY.yaml` so a registry
    update that is unstaged in the working tree but absent from the
    index is correctly treated as missing.
    """
    try:
        result = subprocess.run(
            ["git", "show", f":{REGISTRY_PATH_REL}"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        )
    except subprocess.CalledProcessError:
        # Not present in index (e.g., fresh repo) — treat as empty.
        return set()
    return _parse_registry_module_paths(result.stdout)


def _load_registry_module_paths_from_disk() -> set[str]:
    """Read working-tree registry — used by --check (non-staged) mode."""
    path = PROJECT_ROOT / REGISTRY_PATH_REL
    if not path.exists():
        return set()
    return _parse_registry_module_paths(path.read_text(encoding="utf-8"))


def _parse_registry_module_paths(yaml_text: str) -> set[str]:
    import yaml
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        # Malformed YAML — treat as empty. The encoding/parse lints
        # surface YAML errors separately.
        return set()
    entries = data.get("indicators") or {}
    out: set[str] = set()
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        mp = entry.get("module_path")
        if isinstance(mp, str) and mp:
            out.add(mp)
    return out


def _staged_added_indicator_files() -> list[Path]:
    """Return list of newly-added `indicators/*.py` paths in the index."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only",
         "--diff-filter=A"],
        capture_output=True, text=True, encoding="utf-8",
    )
    out: list[Path] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        p = Path(line)
        if not _is_indicator_module(p):
            continue
        out.append(p)
    return out


def _is_indicator_module(path: Path) -> bool:
    """True iff `path` is a candidate indicator module file under
    `indicators/<category>/<name>.py` (excluding `__init__.py`).
    """
    if path.suffix != ".py":
        return False
    if path.name == "__init__.py":
        return False
    parts = path.parts
    if not parts or parts[0] != "indicators":
        return False
    # Expect indicators/<cat>/<name>.py — at least 3 parts.
    return len(parts) >= 3


def _disk_indicator_modules() -> list[Path]:
    """Return all indicator module paths under `indicators/` in the working
    tree. Used by --check mode for ad-hoc full-disk audit.
    """
    root = PROJECT_ROOT / "indicators"
    if not root.exists():
        return []
    out: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(PROJECT_ROOT)
        if _is_indicator_module(rel):
            out.append(rel)
    return out


def _dotted_module_path(rel_path: Path) -> str:
    """`indicators/momentum/rsi.py` → `indicators.momentum.rsi`."""
    return ".".join(rel_path.with_suffix("").parts)


def check(staged: bool) -> int:
    """Return 0 on pass, 1 on violations. Prints details to stdout."""
    if staged:
        candidate_files = _staged_added_indicator_files()
        if not candidate_files:
            # Nothing of interest staged — pass quickly.
            return 0
        registered = _load_registry_module_paths_from_staged()
    else:
        candidate_files = _disk_indicator_modules()
        registered = _load_registry_module_paths_from_disk()

    missing: list[tuple[str, Path]] = []
    for rel in candidate_files:
        dotted = _dotted_module_path(rel)
        if dotted not in registered:
            missing.append((dotted, rel))

    if not missing:
        if staged:
            print(f"[indicator-registry-sync] Staged additions ({len(candidate_files)}) all registered.")
        else:
            print(f"[indicator-registry-sync] Disk <-> registry parity verified ({len(candidate_files)} modules).")
        return 0

    print("")
    print("[indicator-registry-sync] BLOCKED -- indicator module(s) added "
          "without a matching registry entry:")
    print("")
    for dotted, rel in missing:
        # Always render path with forward slashes (git-style) for
        # cross-platform consistency. Windows-native backslashes look
        # noisy in commit-block messages and break grep-friendly logs.
        print(f"  {rel.as_posix()}  ->  needs `module_path: {dotted}` in "
              f"`{REGISTRY_PATH_REL}`")
    print("")
    print("  Process: every new indicator file must have a registry entry")
    print("           in the SAME commit. Stage-0.5 admission depends on the")
    print("           registry being authoritative.")
    print("")
    print("  Fix:     run `python tools/indicator_registry_sync.py "
          "--add-stubs`")
    print("           then `git add indicators/INDICATOR_REGISTRY.yaml`.")
    print("")
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Block adding indicator modules without a registry entry."
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true",
                      help="Scan only staged ADDED files (pre-commit mode).")
    mode.add_argument("--check", action="store_true",
                      help="Scan full disk vs working-tree registry (ad-hoc).")
    args = p.parse_args(argv)
    return check(staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
