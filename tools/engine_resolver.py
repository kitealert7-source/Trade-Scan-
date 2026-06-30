"""
Engine resolver — canonical-engine VALIDATOR (not a selector).

Pure function. No side effects other than a structured WARNING log when a
strategy declares a stale contract_id whitelist (advisory, non-blocking).
Deterministic for identical inputs.

Consolidation 2026-06-30 (ENGINE_CONSOLIDATION_PLAN_2026-06-29.md, Phase 3):
**inverted from SELECTION to VALIDATION.** There is exactly ONE canonical
compute engine (``config.engine_authority.CANONICAL_SINGLE_ASSET_ENGINE``), so
the runtime never asks *"which engine?"* — only *"is the canonical engine valid
for this run?"*. Runtime engine selection is FORBIDDEN: this module does NOT
enumerate ``engine_dev/`` or ``vault/engines/`` and never chooses among versions
(the old min-semver tie-break + NEWER_ENGINE_AVAILABLE visibility are gone).

Validation model
----------------
The canonical engine ships an ``engine_manifest.json`` (+ ``contract.json``)
declaring its capabilities and I/O contract. For a run we assert:

  1. F8 — contract integrity: ``manifest.contract_id == sha256(contract.json)``
     (LF-normalized canonical hash, same as the manifest writers).
  2. F9 — the canonical engine is FROZEN.
  3. F9 — the canonical engine's capabilities cover the strategy's
     ``required_capabilities`` (exact OR via the catalog ``compatible_with``
     map). v1.5.11 is the capability superset, so this holds for every current
     strategy; a real miss is a genuine wiring/contract fault and fails loud.
  4. Contract whitelist (ADVISORY, non-blocking — consolidation 2026-06-30):
     if the canonical engine's ``contract_id`` is NOT in the strategy's declared
     ``required_contract_ids``, log a WARNING and flag ``contract_whitelist_ok =
     False`` in the result, but PROCEED. In a single-engine world the whitelist
     only ever pinned *which of several* engine contracts a strategy accepted;
     with one canonical engine the binding question is the capability check (F9)
     plus the downstream F11 runtime-shape gate in governance.preflight, which
     reads ``contract.json`` from the returned ``engine_path``. Strategies that
     still declare an older engine's contract_id are therefore tolerated (their
     stale whitelist is surfaced, not enforced). See the plan's Phase 3 + the
     operator decision "Advisory whitelist".

Failure codes mirror the hardening plan's F-series and are never swallowed.
F10 (EXPERIMENTAL-only candidates) is retired — there is nothing to select
among, so an EXPERIMENTAL canonical engine simply fails F9 ("not FROZEN").

Doctrine: engine_identity_is_compute_not_stamp.
"""
import json
import logging
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# R1 hashing-site unification: contract_id integrity must use the same
# LF-normalized canonical hash as the manifest writers (run_pipeline,
# generate_guard_manifest, generate_engine_manifest, governance.preflight).
# Raw hashlib.sha256(read_bytes()) here caused TD-002 contract_id
# false-failures on Windows CRLF contract.json files.
# See tests/test_fvg_session_infra_regressions.py::R1.
from tools.verify_engine_integrity import canonical_sha256  # noqa: E402

ENGINE_DEV_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
CATALOG_PATH = PROJECT_ROOT / "governance" / "capability_catalog.yaml"

logger = logging.getLogger(__name__)


class EngineResolverError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"[{code}] {detail}")
        self.code = code
        self.detail = detail


def _sha256_file(path: Path) -> str:
    return "sha256:" + canonical_sha256(path)


def _load_compat_map() -> dict:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = yaml.safe_load(f)["capabilities"]
    return {
        token: set((spec or {}).get("compatible_with") or [])
        for token, spec in catalog.items()
    }


def _engine_satisfies(engine_caps: set, required: set, compat_map: dict) -> bool:
    """
    Required ⊆ engine_caps, allowing explicit compatibility mapping.

    For each required token r: engine_caps must contain r directly, OR
    contain some token e whose compatible_with list explicitly includes r.
    """
    for r in required:
        if r in engine_caps:
            continue
        if any(r in compat_map.get(e, set()) for e in engine_caps):
            continue
        return False
    return True


def _load_canonical_manifest() -> dict:
    """Load ONLY the canonical engine's manifest — no enumeration.

    The canonical engine is named by config.engine_authority (the single
    selection authority; it imports no engine). We deliberately do NOT iterate
    engine_dev/ or vault/engines/: runtime engine selection is forbidden
    (consolidation 2026-06-30), so there is nothing to choose among.
    """
    from config.engine_authority import CANONICAL_SINGLE_ASSET_ENGINE

    engine_dir = ENGINE_DEV_ROOT / CANONICAL_SINGLE_ASSET_ENGINE
    mpath = engine_dir / "engine_manifest.json"
    if not mpath.exists():
        raise EngineResolverError(
            "F9",
            f"canonical engine {CANONICAL_SINGLE_ASSET_ENGINE} has no "
            f"engine_manifest.json at {mpath}",
        )
    with open(mpath, encoding="utf-8") as f:
        m = json.load(f)
    m["_path"] = engine_dir
    m["_manifest_path"] = mpath
    return m


def resolve_engine(required_capabilities, required_contract_ids) -> dict:
    """
    Validate that the CANONICAL engine satisfies the declared requirements.

    Single-engine VALIDATOR (consolidation 2026-06-30) — never enumerates or
    selects. Returns dict:
        {engine_version, engine_path, contract_id,
         contract_whitelist_ok, declared_contract_ids}.
    Raises EngineResolverError(code) on every hard-failure path (F8/F9).

    The contract whitelist is advisory (non-blocking): contract_whitelist_ok is
    False when the canonical contract_id is not in required_contract_ids, and a
    WARNING is logged, but resolution still succeeds.
    """
    required_caps = set(required_capabilities)
    required_contracts = set(required_contract_ids)
    compat_map = _load_compat_map()

    m = _load_canonical_manifest()  # the ONE engine; no enumeration
    version = m.get("engine_version")

    # F8 — canonical contract integrity (manifest contract_id == sha256(contract.json)).
    contract_path = m["_path"] / "contract.json"
    if not contract_path.exists():
        raise EngineResolverError(
            "F8", f"canonical engine {version} has no contract.json at {contract_path}"
        )
    actual = _sha256_file(contract_path)
    declared = m.get("contract_id")
    if declared != actual:
        raise EngineResolverError(
            "F8",
            f"canonical engine {version} contract_id mismatch: "
            f"manifest={declared} actual={actual}",
        )

    # F9 — the canonical engine must be FROZEN (EXPERIMENTAL never runs; F10 retired).
    if m.get("engine_status") != "FROZEN":
        raise EngineResolverError(
            "F9",
            f"canonical engine {version} is not FROZEN "
            f"(engine_status={m.get('engine_status')!r})",
        )

    # F9 — capability satisfaction: canonical must cover the required capabilities.
    if not _engine_satisfies(set(m.get("capabilities") or []), required_caps, compat_map):
        raise EngineResolverError(
            "F9",
            f"canonical engine {version} does not satisfy "
            f"required_capabilities={sorted(required_caps)} "
            f"(engine capabilities={sorted(m.get('capabilities') or [])})",
        )

    # Contract whitelist — ADVISORY (non-blocking). A stale declaration (an older
    # engine's contract_id, e.g. a strategy authored against v1.5.6/v1.5.8) is
    # surfaced, not enforced: the real binding is the capability check above plus
    # the F11 runtime-shape gate in governance.preflight.
    contract_whitelist_ok = declared in required_contracts
    if not contract_whitelist_ok:
        logger.warning(json.dumps({
            "event": "STALE_CONTRACT_WHITELIST",
            "canonical_engine": version,
            "canonical_contract_id": declared,
            "declared_contract_ids": sorted(required_contracts),
            "note": "strategy required_contract_ids does not include the canonical "
                    "engine contract_id; proceeding (advisory, single-engine model)",
        }))

    return {
        "engine_version": version,
        "engine_path": str(m["_path"]),
        "contract_id": declared,
        "contract_whitelist_ok": contract_whitelist_ok,
        "declared_contract_ids": sorted(required_contracts),
    }
