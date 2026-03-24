"""Pre-execution workflow: migration + directive identity finalization."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

import yaml

from tools.directive_schema import normalize_signature


def _json_safe_for_hash(obj):
    if isinstance(obj, dict):
        return {k: _json_safe_for_hash(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe_for_hash(v) for v in obj]
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            return obj
    return obj


def directive_signature_hash(path: Path) -> str | None:
    """Return short signature hash used for migration identity matching."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sig = normalize_signature(_json_safe_for_hash(payload))
        canonical = json.dumps(sig, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
    except Exception:
        return None


def find_directive_path(active_dir: Path, directive_id: str) -> Path | None:
    """Locate active directive by stem or with .txt extension."""
    candidates = [active_dir / directive_id, active_dir / f"{directive_id}.txt"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_directive_id_by_signature(active_dir: Path, sig_hash: str | None) -> str | None:
    """Resolve current directive ID by matching short signature hash in active/."""
    if not sig_hash:
        return None

    matches: list[str] = []
    for path in active_dir.glob("*.txt"):
        if directive_signature_hash(path) == sig_hash:
            matches.append(path.stem)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        # Prefer a single namespaced directive when both legacy and namespaced
        # files share the same signature (idempotent migration residue).
        namespaced = [
            token
            for token in matches
            if re.fullmatch(r"(C_)?\d{2}_.+_S\d{2}_V\d+_P\d{2}(?:__[A-Z0-9]+)?", token)
        ]
        if len(namespaced) == 1:
            return namespaced[0]

    return None


def run_auto_namespace_migration(
    *,
    python_exe: str,
    active_dir: Path,
    run_command: Callable[[list[str], str], bool],
) -> None:
    """Run authoritative namespace migration on active directives."""
    cmd = [
        python_exe,
        "tools/convert_promoted_directives.py",
        "--source-dir",
        str(active_dir),
        "--rename-strategies",
    ]
    run_command(cmd, "Auto Namespace Migration")


def prepare_single_directive_for_execution(
    *,
    directive_id: str,
    active_dir: Path,
    python_exe: str,
    run_command: Callable[[list[str], str], bool],
) -> str:
    """
    Resolve one directive through migration and return finalized identity.
    Execution must start only after this returns.
    """
    pre_path = find_directive_path(active_dir, directive_id)
    pre_hash = directive_signature_hash(pre_path) if pre_path else None

    run_auto_namespace_migration(
        python_exe=python_exe,
        active_dir=active_dir,
        run_command=run_command,
    )

    if pre_hash:
        migrated_id = resolve_directive_id_by_signature(active_dir, pre_hash)
        if migrated_id and migrated_id != directive_id:
            print(f"[AUTO-MIGRATE] Directive renamed: {directive_id} -> {migrated_id}")
            return migrated_id

    return directive_id


def prepare_batch_directives_for_execution(
    *,
    active_dir: Path,
    python_exe: str,
    run_command: Callable[[list[str], str], bool],
) -> list[Path]:
    """
    Finalize directive identities for batch mode and return active directive list.
    """
    run_auto_namespace_migration(
        python_exe=python_exe,
        active_dir=active_dir,
        run_command=run_command,
    )
    return sorted(active_dir.glob("*.txt"))

