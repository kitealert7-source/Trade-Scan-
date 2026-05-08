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
from tools.pipeline_utils import parse_directive
from tools.system_registry import _load_registry


NAMESPACE_ROOT = PROJECT_ROOT / "governance" / "namespace"
SWEEP_REGISTRY_PATH = NAMESPACE_ROOT / "sweep_registry.yaml"
SWEEP_LOCK_PATH = NAMESPACE_ROOT / "sweep_registry.lock"


class SweepRegistryError(ValueError):
    """Raised for sweep registry failures."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_namespace_info(path: Path) -> dict[str, str]:
    """Extract namespace info assuming gate validation has already occurred."""
    name = path.stem
    m = re.match(r"^(\d{2})_.*_S(\d{2})", name)
    if not m:
        raise SweepRegistryError(f"Filename missing SNN prefix or idea ID: {name}")
    return {
        "idea_id": m.group(1),
        "strategy_name": name,
        "sweep": m.group(2)
    }


def _can_reclaim_sweep(directive_name: str) -> bool:
    """
    Check if a sweep slot allocated to `directive_name` can be reclaimed.
    Reclaim is allowed if ALL existing runs for this directive are in a
    non-terminal failure state (failed, invalid, aborted, interrupted).
    If ANY run is 'complete', reclaim is blocked to preserve successful research.
    Note: If no runs exist, reclaim is allowed.
    """
    reg = _load_registry()
    runs_for_directive = [
        data for data in reg.values()
        if data.get("directive_hash") == directive_name
    ]
    
    if not runs_for_directive:
        return True

    valid_failures = {"failed", "invalid", "aborted", "interrupted"}
    for r in runs_for_directive:
        status = r.get("status", "unknown").lower()
        if status == "complete":
            return False
        if status not in valid_failures:
            return False
            
    return True


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


def get_all_allocated_names(registry: dict[str, Any]) -> set[str]:
    """Return all directive names currently allocated in the sweep registry.

    Traverses sweeps and their nested patches using the canonical schema so
    that run_pipeline.py and any other consumer share a single traversal path.
    Schema changes only need to be updated here.
    """
    allocated: set[str] = set()
    ideas = registry.get("ideas", {})
    if not isinstance(ideas, dict):
        return allocated
    for idea_data in ideas.values():
        if not isinstance(idea_data, dict):
            continue
        sweeps = idea_data.get("sweeps", idea_data.get("allocated", {}))
        if not isinstance(sweeps, dict):
            continue
        for sweep_data in sweeps.values():
            if not isinstance(sweep_data, dict):
                continue
            d_name = sweep_data.get("directive_name")
            if d_name:
                allocated.add(d_name)
            patches = sweep_data.get("patches", {})
            if isinstance(patches, dict):
                for patch_data in patches.values():
                    if isinstance(patch_data, dict):
                        p_name = patch_data.get("directive_name")
                        if p_name:
                            allocated.add(p_name)
    return allocated


def _write_yaml_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    tmp_path.write_text(data, encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def _is_lock_stale(lock_path: Path) -> bool:
    """Return True if the lock file exists but the owning process is no longer alive.

    Uses a Windows-compatible check: ``os.kill(pid, 0)`` raises PermissionError
    on Windows for *any* existing process (unlike POSIX where it succeeds for
    same-user processes), so we cannot distinguish "alive but different user"
    from "alive, same user".  Instead we use ``ctypes.windll`` / ``OpenProcess``
    when available, falling back to the POSIX ``os.kill`` path on Linux/macOS.
    """
    try:
        content = lock_path.read_text(encoding="utf-8")
        m = re.search(r"pid=(\d+)", content)
        if not m:
            return False  # Cannot parse PID — treat as live (safe default)
        pid = int(m.group(1))
        return not _is_pid_alive(pid)
    except Exception:
        return False  # Unknown error — treat as live (safe default)


def _is_pid_alive(pid: int) -> bool:
    """Cross-platform process existence check."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle == 0:
                return False  # Cannot open → process does not exist
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True  # Cannot determine — treat as alive (safe default)
    else:
        # POSIX: signal 0 checks existence without sending a real signal
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Exists but we can't signal it


def _acquire_lock(lock_path: Path, timeout_sec: float = 10.0, poll_sec: float = 0.1) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    stale_cleared = False  # Only attempt stale-lock removal once per acquire call

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"pid={os.getpid()} ts={_now_utc()}".encode("utf-8"))
            return fd
        except FileExistsError:
            # On first contention, check whether the lock belongs to a dead process.
            if not stale_cleared and _is_lock_stale(lock_path):
                try:
                    lock_path.unlink(missing_ok=True)
                    stale_cleared = True
                    print(f"[LOCK] Cleared stale lock from dead process: {lock_path}")
                    continue  # Retry immediately without sleeping
                except Exception:
                    pass  # If unlink fails, fall through to normal timeout path
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
    # normalize_signature() intentionally excludes `timeframe` (non-behavioral
    # for strategy logic). Include it here so same-logic patches on different
    # timeframes produce distinct sweep hashes and don't collide in new_pass.py.
    tf = str(parsed.get("timeframe") or parsed.get("Timeframe") or "").lower().strip()
    if tf:
        signature["__sweep_tf__"] = tf
    canonical = json.dumps(signature, sort_keys=True, ensure_ascii=True)
    return __import__("hashlib").sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_signature_hash(token: str) -> str:
    h = str(token).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{64}", h):
        raise SweepRegistryError(
            f"Invalid signature_hash '{token}'. Expected 16 or 64 hex characters."
        )
    return h


def _is_zero_stub(hash_str: str) -> bool:
    """True if hash is the canonical placeholder (all zeros, 16 or 64 chars).

    Manual bootstrap of a new idea/patch entry uses '0' * 16 (or 64) as a
    placeholder until the first --rehash computes the real hash. Treating
    the placeholder as auto-replaceable avoids the 2-round PATCH_COLLISION
    dance that would otherwise fire on the first real registration.
    """
    h = str(hash_str).strip().lower()
    return bool(re.fullmatch(r"0{16}|0{64}", h))


def _hashes_match(existing_hash: str, incoming_hash: str) -> bool:
    a = _normalize_signature_hash(existing_hash)
    b = _normalize_signature_hash(incoming_hash)
    if a == b:
        return True
    # Backward compatibility: legacy 16-char hashes match 64-char prefix.
    if len(a) == 16 and len(b) == 64:
        return b.startswith(a)
    if len(a) == 64 and len(b) == 16:
        return a.startswith(b)
    return False


def _hash_for_storage(incoming_hash: str) -> tuple[str, str]:
    normalized = _normalize_signature_hash(incoming_hash)
    if len(normalized) == 64:
        return normalized, normalized[:16]
    return normalized, normalized


def _get_stored_hash(payload: dict[str, Any]) -> str:
    """Read the stored directive content hash from a registry payload.

    Field-name history: this hash was originally stored under the misleading
    name `signature_hash` (it actually hashes directive content, not the
    strategy's STRATEGY_SIGNATURE dict — that's a different thing computed
    by FilterStack). Renamed to `directive_hash` 2026-05-08; reads accept
    either name so legacy entries continue to work until they are next
    written through this module.
    """
    full = str(
        payload.get("directive_hash_full")
        or payload.get("signature_hash_full")
        or ""
    ).strip().lower()
    if full:
        return full
    return str(
        payload.get("directive_hash")
        or payload.get("signature_hash")
        or ""
    ).strip().lower()


def _write_hash_fields(payload: dict[str, Any], stored_short: str, stored_hash: str) -> None:
    """Write directive content hash to a registry payload.

    Phase 1 rename (2026-05-08): writes both the canonical `directive_hash`
    [_full] keys AND the legacy `signature_hash[_full]` keys. Dual-write
    keeps existing tooling/tests that read the legacy keys functional while
    new readers get the canonical name. Phase 2 (planned) drops the legacy
    write after a one-shot data migration of sweep_registry.yaml.
    """
    payload["directive_hash"] = stored_short
    payload["signature_hash"] = stored_short  # legacy alias — Phase-1 dual-write
    if len(stored_hash) == 64:
        payload["directive_hash_full"] = stored_hash
        payload["signature_hash_full"] = stored_hash  # legacy alias
    else:
        payload.pop("directive_hash_full", None)
        payload.pop("signature_hash_full", None)


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


def _strip_timeframe_segment(name: str) -> str:
    """Remove the timeframe token (e.g. ``_5M``, ``_15M``, ``_1H``, ``_1D``) from
    a directive name.

    Anchored to the canonical S/V/P tail — ``_<TF>_<MODEL>[_<FILTER>...]_S\\d{2}_V\\d+``
    optionally followed by ``_P\\d{2}[__SUFFIX]`` — so a TF-shaped substring
    elsewhere in the name (symbols like ``SPX500`` etc.) is never touched.
    """
    return re.sub(
        r"_\d+[MHDW](?=(?:_[A-Z][A-Z0-9]*)+_S\d{2}_V\d+(?:_P\d{2}(?:__[A-Z0-9]+)?)?$)",
        "",
        str(name).strip(),
    )


def _is_patch_sibling(existing_name: str, incoming_name: str) -> bool:
    """True if incoming is a patch of the same sweep (same SXX base, different _PNN).

    NOTE: SNN must NOT be stripped here. Stripping SNN (via _strip_sweep_segment)
    would make S07_V1_P00 and S08_V1_P00 appear identical, producing false positives.
    Patch siblings must share the same sweep number — only PNN (and optional run suffix)
    is stripped before comparison.

    TF segment IS stripped: cross-timeframe families (e.g. the PSBRK V4 sweep with
    a 15M parent and 5M children under the same idea/sweep) are intentionally
    treated as patch siblings of one sweep slot. Hash-level discrimination still
    holds — _hash_signature folds timeframe in, so distinct TFs produce distinct
    hashes, and PATCH_COLLISION fires if two children with the same _PNN but
    different hashes are ever registered.
    """
    base_existing = re.sub(r"_P\d{2}(?:__[A-Z0-9]+)?$", "", existing_name)
    base_incoming = re.sub(r"_P\d{2}(?:__[A-Z0-9]+)?$", "", incoming_name)
    base_existing = _strip_timeframe_segment(base_existing)
    base_incoming = _strip_timeframe_segment(base_incoming)
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
    signature_hash = _normalize_signature_hash(signature_hash)
    stored_hash, stored_short = _hash_for_storage(signature_hash)
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
            existing_hash = _get_stored_hash(payload)
            if _is_same_lineage(existing_name, directive_name) and _hashes_match(existing_hash, signature_hash):
                # TD-004 ordering invariant — validate the slot-key match
                # BEFORE the auto-heal mutation below. The heal writes the
                # incoming directive_name + hashes onto the existing slot's
                # payload. If the requested_key is different from the
                # existing slot key, that write corrupts the existing slot
                # (its directive_name is now silently rewritten to a
                # different sweep's name) — caught mid-FVG-session 2026-05-04
                # when running S02 against a registry where S01 had a
                # transiently-matching hash.
                if requested_key and key != requested_key:
                    raise SweepRegistryError(
                        "SWEEP_IDEMPOTENCY_MISMATCH: "
                        f"identity already allocated at '{key}', requested '{requested_key}'."
                    )
                # Auto-heal legacy entry name format to current directive_name.
                # Safe because the requested_key matches the existing slot's
                # key (verified above) — this slot is the one being
                # (re-)reserved, mutating it is correct.
                if existing_name != directive_name or not _get_stored_hash(payload):
                    payload["directive_name"] = directive_name
                    _write_hash_fields(payload, stored_short, stored_hash)
                    sweeps[key] = payload
                    idea_block["sweeps"] = sweeps
                    ideas[idea_id] = idea_block
                    registry["ideas"] = ideas
                    _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                return {
                    "status": "idempotent",
                    "idea_id": idea_id,
                    "sweep": key,
                    "strategy_name": directive_name,
                    "directive_hash": signature_hash,
                    "signature_hash": signature_hash,  # legacy alias
                }
            # Check patches stored under this sweep slot for idempotency.
            for p_data in payload.get("patches", {}).values():
                if not isinstance(p_data, dict):
                    continue
                p_hash = _get_stored_hash(p_data)
                if p_data.get("directive_name") == directive_name and _hashes_match(p_hash, signature_hash):
                    return {
                        "status": "idempotent",
                        "idea_id": idea_id,
                        "sweep": key,
                        "strategy_name": directive_name,
                        "directive_hash": signature_hash,
                        "signature_hash": signature_hash,  # legacy alias
                    }

        # Reserve specific requested sweep (used by namespace directives in pipeline)
        if requested_key:
            existing = sweeps.get(requested_key)
            if isinstance(existing, dict):
                existing_directive = str(existing.get("directive_name", "")).strip()
                existing_hash = _get_stored_hash(existing)
                if _is_same_lineage(existing_directive, directive_name) and _hashes_match(existing_hash, signature_hash):
                    # Auto-heal legacy entry name format to current directive_name.
                    if existing_directive != directive_name or not _get_stored_hash(existing):
                        existing["directive_name"] = directive_name
                        _write_hash_fields(existing, stored_short, stored_hash)
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
                        "directive_hash": signature_hash,
                        "signature_hash": signature_hash,  # legacy alias
                    }
                # Check if incoming is a patch sibling of the existing sweep owner.
                if _is_patch_sibling(existing_directive, directive_name):
                    patch_key = _patch_key_from_name(directive_name)
                    patches = existing.get("patches", {})
                    if not isinstance(patches, dict):
                        patches = {}
                    if patch_key in patches:
                        existing_patch = patches[patch_key]
                        existing_patch_hash = _get_stored_hash(existing_patch)
                        # Auto-replace zero-stub placeholders on first real
                        # registration. Bootstrap workflow seeds a new patch
                        # entry with '0' * 16 before the directive hash exists;
                        # the first --rehash then provides the real hash. Without
                        # this branch the user has to manually overwrite the
                        # stub and re-run, paying the round-trip every new pass.
                        if _is_zero_stub(existing_patch_hash):
                            existing_patch["directive_name"] = directive_name
                            _write_hash_fields(existing_patch, stored_short, stored_hash)
                            existing_patch["reserved_at_utc"] = _now_utc()
                            patches[patch_key] = existing_patch
                            existing["patches"] = patches
                            sweeps[requested_key] = existing
                            idea_block["sweeps"] = sweeps
                            ideas[idea_id] = idea_block
                            registry["ideas"] = ideas
                            _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                            return {
                                "status": "stub_replaced",
                                "idea_id": idea_id,
                                "sweep": requested_key,
                                "strategy_name": directive_name,
                                "signature_hash": signature_hash,
                            }
                        if not _hashes_match(existing_patch_hash, signature_hash):
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
                    patch_payload = {
                        "directive_name": directive_name,
                        "reserved_at_utc": _now_utc(),
                    }
                    _write_hash_fields(patch_payload, stored_short, stored_hash)
                    patches[patch_key] = patch_payload
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
                        "directive_hash": signature_hash,
                        "signature_hash": signature_hash,  # legacy alias
                    }
                # Reclaim Logic
                if existing_directive == directive_name:
                    if _can_reclaim_sweep(directive_name):
                        # Attempt tracking
                        attempt = existing.get("attempt", 1) + 1
                        existing["attempt"] = attempt
                        _write_hash_fields(existing, stored_short, stored_hash)

                        sweeps[requested_key] = existing
                        idea_block["sweeps"] = sweeps
                        ideas[idea_id] = idea_block
                        registry["ideas"] = ideas
                        _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)
                        print(f"SWEEP_RECLAIM | directive={directive_name} | attempt={attempt} | previous_status=FAILED")
                        return {
                            "status": "reclaimed",
                            "idea_id": idea_id,
                            "sweep": requested_key,
                            "strategy_name": directive_name,
                            "signature_hash": signature_hash,
                        }
                    else:
                        raise SweepRegistryError(
                            "SWEEP_IDEMPOTENCY_MISMATCH: "
                            f"idea_id='{idea_id}' sweep='{requested_key}' cannot reclaim slot for "
                            f"directive='{directive_name}' because a COMPLETE run exists."
                        )

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

        new_slot = {
            "directive_name": directive_name,
            "reserved_at_utc": _now_utc(),
        }
        _write_hash_fields(new_slot, stored_short, stored_hash)
        sweeps[sweep_key] = new_slot
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


def update_sweep_signature_hash(
    idea_id: str,
    directive_name: str,
    signature_hash: str,
) -> dict[str, str]:
    """Lock-protected, exact-identity hash update for an existing sweep entry.

    INFRA-AUDIT C3+M5 closure 2026-05-03. Replaces direct YAML writes in
    callers (previously: tools/orchestration/pre_execution.py:227 used
    string substitution + write_text(), no lock, with substring matching
    on directive_name that could corrupt the wrong sweep slot when names
    shared a prefix).

    Walks the registry by EXACT directive_name match across sweep entries
    AND patch entries. Acquires the canonical sweep_registry lock before
    any read-modify-write. Returns {"status", "idea_id", "sweep",
    "patch"?, "directive_name", "signature_hash"}. Raises
    SweepRegistryError if no exact match found.

    Idempotent: if the recorded hash already matches the new hash, returns
    {"status": "unchanged"} without rewriting.
    """
    idea_id = str(idea_id).strip()
    directive_name = str(directive_name).strip()
    signature_hash = _normalize_signature_hash(signature_hash)
    stored_hash, stored_short = _hash_for_storage(signature_hash)

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
        idea_block = ideas.get(idea_id) if isinstance(ideas, dict) else None
        if not isinstance(idea_block, dict):
            raise SweepRegistryError(
                f"SWEEP_IDEA_UNREGISTERED: idea_id='{idea_id}' missing from "
                "sweep_registry.yaml"
            )
        sweeps = idea_block.get("sweeps", idea_block.get("allocated", {}))
        if not isinstance(sweeps, dict):
            raise SweepRegistryError(
                f"Invalid sweeps mapping for idea_id='{idea_id}'"
            )

        # Exact match scan: sweep owner OR patch entry. NO substring.
        target_path: tuple[str, str | None] | None = None
        for sweep_key, sweep_data in sweeps.items():
            if not isinstance(sweep_data, dict):
                continue
            if str(sweep_data.get("directive_name", "")).strip() == directive_name:
                target_path = (sweep_key, None)
                break
            for patch_key, patch_data in sweep_data.get("patches", {}).items():
                if not isinstance(patch_data, dict):
                    continue
                if str(patch_data.get("directive_name", "")).strip() == directive_name:
                    target_path = (sweep_key, patch_key)
                    break
            if target_path:
                break

        if target_path is None:
            raise SweepRegistryError(
                f"SWEEP_NOT_FOUND: directive_name='{directive_name}' has no "
                f"existing entry in idea_id='{idea_id}'. Use reserve_sweep_identity "
                "to allocate first."
            )

        sweep_key, patch_key = target_path
        node = sweeps[sweep_key] if patch_key is None else sweeps[sweep_key]["patches"][patch_key]
        existing_hash = _get_stored_hash(node)
        if _hashes_match(existing_hash, signature_hash):
            return {
                "status": "unchanged",
                "idea_id": idea_id,
                "sweep": sweep_key,
                "patch": patch_key,
                "directive_name": directive_name,
                "signature_hash": signature_hash,
            }

        _write_hash_fields(node, stored_short, stored_hash)
        idea_block["sweeps"] = sweeps
        ideas[idea_id] = idea_block
        registry["ideas"] = ideas
        _write_yaml_atomic(SWEEP_REGISTRY_PATH, registry)

        return {
            "status": "updated",
            "idea_id": idea_id,
            "sweep": sweep_key,
            "patch": patch_key,
            "directive_name": directive_name,
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

    ns = _extract_namespace_info(d_path)
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
