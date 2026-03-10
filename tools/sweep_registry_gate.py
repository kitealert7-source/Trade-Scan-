"""
Phase-2 Sweep Registry Gate.

Rules:
1. Sweep SNN must be unique per idea_id.
2. If sweep exists, it must match same directive + same signature hash (idempotent).
3. If sweep does not exist, reserve it atomically via gate authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.directive_schema import normalize_signature
from tools.namespace_gate import validate_namespace
from tools.pipeline_utils import parse_directive


NAMESPACE_ROOT = PROJECT_ROOT / "governance" / "namespace"
SWEEP_REGISTRY_PATH = NAMESPACE_ROOT / "sweep_registry.yaml"
SWEEP_LOCK_PATH = NAMESPACE_ROOT / "sweep_registry.lock"


class SweepRegistryError(ValueError):
    """Raised for sweep registry failures."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SweepRegistryError(f"Missing registry file: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SweepRegistryError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SweepRegistryError(f"Expected mapping YAML: {path}")
    return payload


def _write_yaml_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    tmp_path.write_text(data, encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def _acquire_lock(lock_path: Path, timeout_sec: float = 10.0, poll_sec: float = 0.1) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"pid={os.getpid()} ts={_now_utc()}".encode("utf-8"))
            return fd
        except FileExistsError:
            if time.time() >= deadline:
                raise SweepRegistryError(
                    f"SWEEP_LOCK_TIMEOUT: Could not acquire lock: {lock_path}"
                )
            time.sleep(poll_sec)


def _release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _hash_signature(directive_path: Path) -> str:
    parsed = parse_directive(directive_path)
    signature = normalize_signature(parsed)
    canonical = json.dumps(signature, sort_keys=True, ensure_ascii=True)
    return __import__("hashlib").sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _compute_next_sweep(sweeps: dict[str, Any]) -> int:
    """
    Backward-compatible informational counter:
    next_sweep = max(existing sweep id) + 1
    """
    max_seen = 0
    for k in sweeps.keys():
        m = re.fullmatch(r"S(\d{2})", str(k).upper().strip())
        if m:
            max_seen = max(max_seen, int(m.group(1)))
    return max_seen + 1


def _normalize_sweep_key(requested_sweep: str | None) -> str | None:
    if not requested_sweep:
        return None
    token = str(requested_sweep).strip().upper()
    if token.startswith("S"):
        token = token[1:]
    if not token.isdigit():
        raise SweepRegistryError(
            f"Invalid requested sweep token: '{requested_sweep}'"
        )
    num = int(token)
    if num < 0 or num > 99:
        raise SweepRegistryError(
            f"Requested sweep out of range (0-99): '{requested_sweep}'"
        )
    return f"S{num:02d}"


def _strip_sweep_segment(name: str) -> str:
    """
    Normalize directive lineage by removing _SNN segment when present.
    Handles optional run-context suffix (e.g. __E152) after the P-token.
    Example:
      02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S04_V1_P00        -> 02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_V1_P00
      02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_S04_V1_P00__E152  -> 02_VOL_XAUUSD_1H_VOLEXP_TRENDFILT_V1_P00__E152
    """
    token = str(name).strip()
    return re.sub(r"_S\d{2}(?=_V\d+_P\d{2}(?:__[A-Z0-9]+)?$)", "", token)


def _is_same_lineage(existing_name: str, incoming_name: str) -> bool:
    if existing_name == incoming_name:
        return True
    return _strip_sweep_segment(existing_name) == _strip_sweep_segment(incoming_name)


def _is_patch_sibling(existing_name: str, incoming_name: str) -> bool:
    """True if incoming is a patch of the same sweep (same SXX base, different _PNN).

    NOTE: SNN must NOT be stripped here. Stripping SNN (via _strip_sweep_segment)
    would make S07_V1_P00 and S08_V1_P00 appear identical, producing false positives.
    Patch siblings must share the same sweep number — only PNN (and optional run suffix)
    is stripped before comparison.
    """
    base_existing = re.sub(r"_P\d{2}(?:__[A-Z0-9]+)?$", "", existing_name)
    base_incoming = re.sub(r"_P\d{2}(?:__[A-Z0-9]+)?$", "", incoming_name)
    return base_existing == base_incoming and existing_name != incoming_name


def _patch_key_from_name(name: str) -> str | None:
    m = re.search(r"_P(\d{2})(?:__[A-Z0-9]+)?$", name)
    return f"P{m.group(1)}" if m else None


def reserve_sweep_identity(
    idea_id: str,
    directive_name: str,
    signature_hash: str,
    requested_sweep: str | None = None,
    auto_advance: bool = True,
) -> dict[str, str]:
    """Reserve/validate sweep by identity payload (no directive parsing)."""
    idea_id = str(idea_id).strip()
    directive_name = str(directive_name).strip()
    signature_hash = str(signature_hash).strip()
    requested_key = _normalize_sweep_key(requested_sweep)

    if not idea_id or not re.fullmatch(r"\d{2}", idea_id):
        raise SweepRegistryError(
            f"Invalid idea_id '{idea_id}'. Expected two digits."
        )
    if not directive_name:
        raise SweepRegistryError("directive_name is required.")
    if not signature_hash:
        raise SweepRegistryError("signature_hash is required.")

    lock_fd = _acquire_lock(SWEEP_LOCK_PATH)
    try:
        registry = _load_yaml(SWEEP_REGISTRY_PATH)
        ideas = registry.get("ideas", {})
        if not isinstance(ideas, dict):
            raise SweepRegistryError(
                "Invalid sweep_registry.yaml: expected top-level 'ideas' mapping."
            )

        idea_block = ideas.get(idea_id)
        if not isinstance(idea_block, dict):
            raise SweepRegistryError(
                f"SWEEP_IDEA_UNREGISTERED: idea_id='{idea_id}' missing from sweep_registry.yaml"
            )

        # Current canonical key is 'sweeps'. Accept legacy 'allocated' for compatibility.
        sweeps = idea_block.get("sweeps", idea_block.get("allocated", {}))
        if not isinstance(sweeps, dict):
            raise SweepRegistryError(
                f"Invalid sweeps mapping for idea_id='{idea_id}'"
            )

        # Global idempotency check for this identity across existing sweep slots.
        for key, payload in sweeps.items():
            if not isinstance(payload, dict):
                continue
            existing_name = str(payload.get("directive_name", "")).strip()
            existing_hash = str(payload.get("signature_hash", "")).strip()
            if _is_same_lineage(existing_name, directive_name) and existing_hash == signature_hash:
                # Auto-heal legacy entry name format to current directive_name.
                if existing_name != directive_name:
                    payload["directive_name"] = directive_name
                    sweeps[key] = payload
                    idea_block["sweeps"] = sweeps
                    ideas[idea_id] = idea_block
                    registry["ideas"] = ideas
                    _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                if requested_key and key != requested_key:
                    raise SweepRegistryError(
                        "SWEEP_IDEMPOTENCY_MISMATCH: "
                        f"identity already allocated at '{key}', requested '{requested_key}'."
                    )
                return {
                    "status": "idempotent",
                    "idea_id": idea_id,
                    "sweep": key,
                    "strategy_name": directive_name,
                    "signature_hash": signature_hash,
                }
            # Check patches stored under this sweep slot for idempotency.
            for p_data in payload.get("patches", {}).values():
                if not isinstance(p_data, dict):
                    continue
                if p_data.get("directive_name") == directive_name and p_data.get("signature_hash") == signature_hash:
                    return {
                        "status": "idempotent",
                        "idea_id": idea_id,
                        "sweep": key,
                        "strategy_name": directive_name,
                        "signature_hash": signature_hash,
                    }

        # Reserve specific requested sweep (used by namespace directives in pipeline)
        if requested_key:
            existing = sweeps.get(requested_key)
            if isinstance(existing, dict):
                existing_directive = str(existing.get("directive_name", "")).strip()
                existing_hash = str(existing.get("signature_hash", "")).strip()
                if _is_same_lineage(existing_directive, directive_name) and existing_hash == signature_hash:
                    # Auto-heal legacy entry name format to current directive_name.
                    if existing_directive != directive_name:
                        existing["directive_name"] = directive_name
                        sweeps[requested_key] = existing
                        idea_block["sweeps"] = sweeps
                        ideas[idea_id] = idea_block
                        registry["ideas"] = ideas
                        _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                    return {
                        "status": "idempotent",
                        "idea_id": idea_id,
                        "sweep": requested_key,
                        "strategy_name": directive_name,
                        "signature_hash": signature_hash,
                    }
                # Check if incoming is a patch sibling of the existing sweep owner.
                if _is_patch_sibling(existing_directive, directive_name):
                    patch_key = _patch_key_from_name(directive_name)
                    patches = existing.get("patches", {})
                    if not isinstance(patches, dict):
                        patches = {}
                    if patch_key in patches:
                        existing_patch = patches[patch_key]
                        if existing_patch.get("signature_hash") != signature_hash:
                            raise SweepRegistryError(
                                f"PATCH_COLLISION: idea_id='{idea_id}' sweep='{requested_key}' "
                                f"patch='{patch_key}' already registered with a different hash."
                            )
                        return {
                            "status": "idempotent",
                            "idea_id": idea_id,
                            "sweep": requested_key,
                            "strategy_name": directive_name,
                            "signature_hash": signature_hash,
                        }
                    patches[patch_key] = {
                        "directive_name": directive_name,
                        "signature_hash": signature_hash,
                        "reserved_at_utc": _now_utc(),
                    }
                    existing["patches"] = patches
                    sweeps[requested_key] = existing
                    idea_block["sweeps"] = sweeps
                    ideas[idea_id] = idea_block
                    registry["ideas"] = ideas
                    _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                    return {
                        "status": "reserved",
                        "idea_id": idea_id,
                        "sweep": requested_key,
                        "strategy_name": directive_name,
                        "signature_hash": signature_hash,
                    }
                raise SweepRegistryError(
                    "SWEEP_COLLISION: "
                    f"idea_id='{idea_id}' sweep='{requested_key}' already allocated to "
                    f"directive='{existing_directive}' hash='{existing_hash}'."
                )
            if not auto_advance:
                raise SweepRegistryError(
                    f"SWEEP_NOT_RESERVED: idea_id='{idea_id}' sweep='{requested_key}' is unallocated."
                )
            sweep_key = requested_key
        else:
            if not auto_advance:
                raise SweepRegistryError(
                    "SWEEP_NOT_RESERVED: identity has no existing allocation."
                )
            next_num = int(idea_block.get("next_sweep", _compute_next_sweep(sweeps)))
            while f"S{next_num:02d}" in sweeps:
                next_num += 1
            sweep_key = f"S{next_num:02d}"

        sweeps[sweep_key] = {
            "directive_name": directive_name,
            "signature_hash": signature_hash,
            "reserved_at_utc": _now_utc(),
        }
        idea_block["sweeps"] = sweeps
        # Keep next_sweep for compatibility/observability (not a gate condition).
        idea_block["next_sweep"] = _compute_next_sweep(sweeps)
        ideas[idea_id] = idea_block
        registry["ideas"] = ideas
        _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)

        return {
            "status": "reserved",
            "idea_id": idea_id,
            "sweep": sweep_key,
            "strategy_name": directive_name,
            "signature_hash": signature_hash,
        }
    finally:
        _release_lock(lock_fd, SWEEP_LOCK_PATH)


def reserve_sweep(
    directive_path: str | Path,
    auto_advance: bool = True,
) -> dict[str, str]:
    d_path = Path(directive_path)
    if not d_path.exists():
        raise SweepRegistryError(f"Directive not found: {d_path}")

    ns = validate_namespace(d_path)
    idea_id = ns["idea_id"]
    strategy_name = ns["strategy_name"]
    sweep_num = int(ns["sweep"])
    signature_hash = _hash_signature(d_path)
    return reserve_sweep_identity(
        idea_id=idea_id,
        directive_name=strategy_name,
        signature_hash=signature_hash,
        requested_sweep=f"S{sweep_num:02d}",
        auto_advance=auto_advance,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-2 Sweep Registry Gate")
    parser.add_argument("directive_path", nargs="?", help="Path to directive YAML (.txt) file")
    parser.add_argument("--idea-id", help="Two-digit idea ID for identity mode.")
    parser.add_argument("--directive-name", help="Directive/base namespace identity.")
    parser.add_argument("--signature-hash", help="Signature hash for idempotency identity.")
    parser.add_argument("--requested-sweep", help="Optional explicit sweep token, e.g. S01.")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate existing reservation only (no new reservation).",
    )
    args = parser.parse_args()

    identity_mode = any(
        [args.idea_id, args.directive_name, args.signature_hash, args.requested_sweep]
    )
    if identity_mode and (not args.idea_id or not args.directive_name or not args.signature_hash):
        print(
            "[SWEEP_GATE] FAIL: Identity mode requires --idea-id, --directive-name, "
            "and --signature-hash."
        )
        return 1
    if not identity_mode and not args.directive_path:
        print("[SWEEP_GATE] FAIL: directive_path is required unless identity mode is used.")
        return 1

    try:
        if identity_mode:
            result = reserve_sweep_identity(
                idea_id=args.idea_id,
                directive_name=args.directive_name,
                signature_hash=args.signature_hash,
                requested_sweep=args.requested_sweep,
                auto_advance=not args.check_only,
            )
        else:
            result = reserve_sweep(
                args.directive_path,
                auto_advance=not args.check_only,
            )
    except SweepRegistryError as exc:
        print(f"[SWEEP_GATE] FAIL: {exc}")
        return 1
    except Exception as exc:
        print(f"[SWEEP_GATE] FAIL: Unexpected error: {exc}")
        return 1

    print(
        "[SWEEP_GATE] PASS: "
        f"status={result['status']} "
        f"idea={result['idea_id']} "
        f"sweep={result['sweep']} "
        f"directive={result['strategy_name']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
