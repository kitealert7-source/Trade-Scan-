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


# ── Auto-Consistency Gate ──────────────────────────────────────────────────
# Runs before admission. Detects hash drift between directive, strategy.py,
# and sweep_registry — auto-fixes all three to be consistent. Also ensures
# the approved marker is fresh so EXPERIMENT_DISCIPLINE never fires.
# This is the pipeline-integrated equivalent of `new_pass.py --rehash`.

def _extract_signature_from_strategy(strategy_py: Path) -> dict | None:
    """Extract STRATEGY_SIGNATURE dict from strategy.py via JSON parsing."""
    content = strategy_py.read_text(encoding="utf-8")
    start_marker = "# --- STRATEGY SIGNATURE START ---"
    end_marker = "# --- STRATEGY SIGNATURE END ---"
    m = re.search(
        rf"{re.escape(start_marker)}\s+STRATEGY_SIGNATURE\s*=\s*(\{{.*?\}})\s+{re.escape(end_marker)}",
        content,
        re.DOTALL,
    )
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _format_sig_canonical(sig: dict) -> str:
    """Format STRATEGY_SIGNATURE exactly as provisioner would."""
    sig_json = json.dumps(sig, indent=4, sort_keys=True)
    return (
        sig_json
        .replace(": true", ": True")
        .replace(": false", ": False")
        .replace(": null", ": None")
    )


def _hash_sig_dict(sig: dict) -> str:
    """16-char hex hash of STRATEGY_SIGNATURE — matches strategy_provisioner."""
    canonical = json.dumps(sig, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _directive_full_hash(directive_path: Path) -> tuple[str, str]:
    """Return (short_hash, full_hash) matching sweep_registry_gate._hash_signature."""
    from tools.sweep_registry_gate import _hash_signature
    full = _hash_signature(directive_path)
    return full[:16], full


def _update_sweep_registry_hash(
    strategy_name: str, short_hash: str, full_hash: str, project_root: Path
) -> bool:
    """Update sweep_registry.yaml entry for this strategy with new hashes. Returns True if changed."""
    registry_path = project_root / "governance" / "namespace" / "sweep_registry.yaml"
    if not registry_path.exists():
        return False

    content = registry_path.read_text(encoding="utf-8")
    if strategy_name not in content:
        return False

    # Find the directive_name line for this strategy and update hashes in its block
    lines = content.split("\n")
    changed = False
    i = 0
    while i < len(lines):
        if f"directive_name: {strategy_name}" in lines[i]:
            # Found the entry — update the next signature_hash lines
            for j in range(i + 1, min(i + 5, len(lines))):
                if "signature_hash_full:" in lines[j]:
                    old_val = lines[j].split(":", 1)[1].strip().strip("'\"")
                    if old_val != full_hash:
                        indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                        lines[j] = f"{indent}signature_hash_full: {full_hash}"
                        changed = True
                elif "signature_hash:" in lines[j] and "full" not in lines[j]:
                    old_val = lines[j].split(":", 1)[1].strip().strip("'\"")
                    if old_val != short_hash:
                        indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                        lines[j] = f"{indent}signature_hash: {short_hash}"
                        changed = True
            break
        i += 1

    if changed:
        registry_path.write_text("\n".join(lines), encoding="utf-8")
    return changed


def enforce_signature_consistency(
    directive_id: str,
    project_root: Path,
    active_dir: Path,
) -> None:
    """
    Auto-consistency gate: ensures directive hash, strategy.py signature hash,
    sweep registry entry, and approved marker are all consistent and fresh.

    Runs automatically before admission — eliminates the need for manual
    `new_pass.py --rehash` after edits. Idempotent: no-ops when everything
    is already consistent.

    Does NOT clean stale run state (that remains the responsibility of
    `new_pass.py --rehash` or `reset_directive.py` for intentional re-runs).
    """
    strategies_dir = project_root / "strategies"
    strategy_py = strategies_dir / directive_id / "strategy.py"
    directive_path = active_dir / f"{directive_id}.txt"

    # Both files must exist — otherwise other guardrails handle the error
    if not strategy_py.exists() or not directive_path.exists():
        return

    actions = []

    # ── 1. Compute current directive hash ──
    try:
        short_hash, full_hash = _directive_full_hash(directive_path)
    except Exception:
        return  # Can't compute hash — let downstream checks handle it

    # ── 2. Update sweep registry if hash drifted ──
    if _update_sweep_registry_hash(directive_id, short_hash, full_hash, project_root):
        actions.append(f"sweep_registry hash -> {short_hash}")

    # ── 3. Canonicalize strategy.py signature + hash comment ──
    sig = _extract_signature_from_strategy(strategy_py)
    if sig is not None:
        sig_hash = _hash_sig_dict(sig)
        content = strategy_py.read_text(encoding="utf-8")
        original_content = content

        # Re-format signature block to provisioner-canonical form
        start_marker = "# --- STRATEGY SIGNATURE START ---"
        end_marker = "# --- STRATEGY SIGNATURE END ---"
        canonical_sig = _format_sig_canonical(sig)
        new_block = f"{start_marker}\n    STRATEGY_SIGNATURE = {canonical_sig}\n    {end_marker}"
        pattern = re.compile(
            rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL
        )
        content = pattern.sub(new_block, content, count=1)

        # Update or inject hash comment
        hash_line = f"# --- SIGNATURE HASH: {sig_hash} ---"
        hash_re = re.compile(r"# --- SIGNATURE HASH: [0-9a-f]{16} ---")
        if hash_re.search(content):
            content = hash_re.sub(hash_line, content, count=1)
        else:
            content = content.replace(
                end_marker, f"{end_marker}\n    {hash_line}", 1
            )

        if content != original_content:
            strategy_py.write_text(content, encoding="utf-8")
            actions.append(f"strategy.py canonical hash -> {sig_hash}")

    # ── 4. Ensure approved marker endorses current strategy.py (hash-based) ──
    # The marker stores sha256(strategy.py). It's refreshed when:
    #   (a) the marker is missing, or
    #   (b) it lacks a stored sha256 (legacy format — upgrade in place), or
    #   (c) the stored sha256 does not match the current file hash.
    # Byte-identical rewrites (provisioner, --rehash) leave the hash unchanged,
    # so this gate becomes a true content check — mtime is irrelevant.
    from tools.approval_marker import (
        compute_strategy_hash,
        read_approved_marker,
        write_approved_marker,
    )

    approved_marker = strategy_py.with_name("strategy.py.approved")
    current_hash = compute_strategy_hash(strategy_py)
    existing = read_approved_marker(approved_marker)

    if existing is None:
        needs_approval = True
        refresh_reason = "created"
    elif not existing.has_hash:
        needs_approval = True
        refresh_reason = "upgraded to hash-based"
    elif existing.strategy_sha256 != current_hash:
        needs_approval = True
        refresh_reason = f"hash {current_hash[:12]}"
    else:
        needs_approval = False
        refresh_reason = ""

    if needs_approval:
        write_approved_marker(approved_marker, current_hash)
        actions.append(f"approved marker refreshed ({refresh_reason})")

    # ── 5. Regenerate tools manifest if sweep registry was updated ──
    if any("sweep_registry" in a for a in actions):
        try:
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "tools/generate_guard_manifest.py"],
                capture_output=True, text=True, cwd=str(project_root), timeout=30,
            )
            if result.returncode == 0:
                actions.append("tools manifest regenerated")
        except Exception:
            pass  # Non-fatal — manifest check downstream will catch it

    # ── Report ──
    if actions:
        print(f"[AUTO-CONSISTENCY] {directive_id}: {' | '.join(actions)}")
    else:
        print(f"[AUTO-CONSISTENCY] {directive_id}: all hashes consistent (OK)")

