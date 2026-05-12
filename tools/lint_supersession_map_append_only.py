"""Pre-commit lint — enforce the append-only invariant on
`governance/supersession_map.yaml`.

The file's own header documents the invariant:

    Invariants:
      - Append-only. Never edit or remove a mapping once published.
      - ...

But nothing actually gates that today. A silent edit or deletion would
cause `tools/report/family_renderer.py`, `tools/family_report.py`, and
`tools/ledger_db.py` to resolve old directive IDs to themselves instead
of canonical successors — wrong cross-time report references that no
admission gate catches. Detection lag could be weeks.

This lint runs at pre-commit time:

  - When the supersession map is staged, compare the staged blob to
    HEAD. Block on key deletion or existing-key mutation. Allow new-key
    append. Allow identical (no-op).
  - When the supersession map is NOT staged, do nothing.

Per `outputs/GOVERNANCE_DRIFT_PREVENTION_PLAN.md` Patch 4.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH_REL = "governance/supersession_map.yaml"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def _is_map_staged() -> bool:
    """True iff the supersession map is in the staged change set."""
    result = _git("diff", "--cached", "--name-only")
    staged = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return MAP_PATH_REL in staged


def _read_blob(ref_or_index: str) -> str | None:
    """Read a blob via `git show <ref>:<path>` or `git show :<path>` for
    the index. Returns None if the blob doesn't exist (e.g., file not in
    HEAD because it's brand new).
    """
    result = _git("show", f"{ref_or_index}:{MAP_PATH_REL}")
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_supersessions(yaml_text: str | None) -> dict[str, dict[str, Any]]:
    """Return the `supersessions:` block as a dict of {old_id: entry}.

    Empty/None text → empty dict. Malformed YAML → propagates (the
    encoding/parse lints handle structural YAML errors separately).
    """
    if not yaml_text:
        return {}
    import yaml
    data = yaml.safe_load(yaml_text) or {}
    raw = data.get("supersessions") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        out[k] = v if isinstance(v, dict) else {}
    return out


def _diff_maps(
    head: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str, Any, Any]]]:
    """Return (deleted_keys, mutated_field_changes).

    `mutated_field_changes` is a list of (key, field_name, old_value,
    new_value) tuples — each represents one field on an existing key
    that changed value, which violates append-only.
    """
    deleted = sorted(set(head) - set(new))
    mutations: list[tuple[str, str, Any, Any]] = []
    for key in sorted(set(head) & set(new)):
        head_entry = head[key]
        new_entry = new[key]
        # Field-level diff — both removal and change count as mutation.
        all_fields = set(head_entry) | set(new_entry)
        for field in sorted(all_fields):
            ov = head_entry.get(field)
            nv = new_entry.get(field)
            if ov != nv:
                mutations.append((key, field, ov, nv))
    return deleted, mutations


def check_staged() -> int:
    """Pre-commit mode — compare staged blob to HEAD."""
    if not _is_map_staged():
        return 0  # nothing to verify

    head_yaml = _read_blob("HEAD")
    new_yaml = _read_blob("")  # `git show :path` == staged blob
    head_map = _parse_supersessions(head_yaml)
    new_map = _parse_supersessions(new_yaml)

    # File-level deletion (no longer in working tree).
    if head_yaml is not None and new_yaml is None:
        print("")
        print("[supersession-map] BLOCKED -- the file is being deleted.")
        print("  governance/supersession_map.yaml is append-only -- it cannot be")
        print("  removed. Restore the file before committing.")
        return 1

    deleted, mutations = _diff_maps(head_map, new_map)
    if not deleted and not mutations:
        return 0

    print("")
    print("[supersession-map] BLOCKED -- append-only invariant violated:")
    print("")
    if deleted:
        print(f"  {len(deleted)} mapping(s) DELETED (forbidden):")
        for k in deleted:
            print(f"    - {k}")
        print("")
    if mutations:
        print(f"  {len(mutations)} field mutation(s) on existing mapping(s) (forbidden):")
        for key, field, ov, nv in mutations:
            print(f"    - {key}.{field}: {ov!r} -> {nv!r}")
        print("")
    print("  governance/supersession_map.yaml is append-only. New mappings may")
    print("  be added, but existing mappings must never be deleted or mutated.")
    print("  See the file header for the documented invariant.")
    print("")
    print("  If a published mapping is genuinely wrong, the resolution is a")
    print("  new mapping (chain forward), not an edit. See")
    print("  outputs/GOVERNANCE_DRIFT_PREVENTION_PLAN.md Section 2.6.")
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Enforce append-only on governance/supersession_map.yaml."
    )
    p.add_argument("--staged", action="store_true",
                   help="Compare staged blob to HEAD (pre-commit mode).")
    args = p.parse_args(argv)
    if args.staged:
        return check_staged()
    # Future modes (e.g., --check against working tree) would go here.
    # For now the only consumer is the pre-commit hook.
    return check_staged()


if __name__ == "__main__":
    sys.exit(main())
