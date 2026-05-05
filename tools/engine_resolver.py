"""
Engine resolver — capability + contract driven engine selection.

Pure function. No side effects other than a structured INFO log when
newer compatible engines exist alongside the selected one. Deterministic
for identical inputs.

Contract model
--------------
Each engine directory ships an optional contract.json declaring its I/O
surface. engine_manifest.json.contract_id MUST equal sha256(contract.json).
Engines without a contract.json are silently filtered out — they cannot
participate in capability resolution until the migration has annotated
them.

Selection policy
----------------
  1. Collect manifests under engine_dev/ and vault/engines/.
  2. Self-verify: manifest.contract_id == sha256(contract.json). Mismatch
     raises EngineResolverError("F8").
  3. Filter by status == FROZEN. EXPERIMENTAL engines are eliminated here
     and never resurrected.
  4. Filter by capability: engine capabilities must cover the required
     set. Capability match is exact OR explicit via the catalog's
     compatible_with mapping. No transitive or implicit compatibility.
  5. Filter by contract_id: engine contract_id must be in the strategy's
     declared required_contract_ids whitelist.
  6. If no FROZEN candidates: raise F9. If only EXPERIMENTAL candidates
     satisfy the cap + contract filters, raise F10 with their versions
     enumerated.
  7. Tie-break: lowest semantic version wins (principle of least change).
  8. Newer-version visibility: if other candidates have higher versions,
     emit INFO log "NEWER_ENGINE_AVAILABLE" with the list. Selection
     unchanged.

Failure codes mirror the hardening plan's F-series and are never
swallowed.
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
VAULT_ENGINE_ROOT = PROJECT_ROOT / "vault" / "engines" / "Universal_Research_Engine"
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


def _semver_key(version: str) -> tuple:
    """Normalize 'v1_5_7' / '1.5.7' / 'v1.5.7' to (1, 5, 7)."""
    parts = version.lstrip("vV").replace("_", ".").split(".")
    return tuple(int(p) for p in parts if p.isdigit())


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


def _load_all_manifests() -> list:
    manifests = []
    for root in (ENGINE_DEV_ROOT, VAULT_ENGINE_ROOT):
        if not root.exists():
            continue
        for engine_dir in sorted(root.iterdir()):
            if not engine_dir.is_dir():
                continue
            mpath = engine_dir / "engine_manifest.json"
            if not mpath.exists():
                continue
            with open(mpath, encoding="utf-8") as f:
                m = json.load(f)
            m["_path"] = engine_dir
            m["_manifest_path"] = mpath
            manifests.append(m)
    return manifests


def resolve_engine(required_capabilities, required_contract_ids) -> dict:
    """
    Resolve the minimal FROZEN engine satisfying the declared requirements.

    Returns dict: {engine_version, engine_path, contract_id}.
    Raises EngineResolverError(code) on every failure path.
    """
    required_caps = set(required_capabilities)
    required_contracts = set(required_contract_ids)
    compat_map = _load_compat_map()
    manifests = _load_all_manifests()

    for m in manifests:
        contract_path = m["_path"] / "contract.json"
        if not contract_path.exists():
            continue
        actual = _sha256_file(contract_path)
        declared = m.get("contract_id")
        if declared != actual:
            raise EngineResolverError(
                "F8",
                f"engine {m.get('engine_version')} contract_id mismatch: "
                f"manifest={declared} actual={actual}",
            )

    frozen = [m for m in manifests if m.get("engine_status") == "FROZEN"]
    experimental = [m for m in manifests if m.get("engine_status") == "EXPERIMENTAL"]

    def _cap_ok(m):
        return _engine_satisfies(set(m.get("capabilities") or []), required_caps, compat_map)

    def _contract_ok(m):
        return m.get("contract_id") in required_contracts

    candidates = [m for m in frozen if _cap_ok(m) and _contract_ok(m)]
    experimental_candidates = [m for m in experimental if _cap_ok(m) and _contract_ok(m)]

    if not candidates:
        if experimental_candidates:
            raise EngineResolverError(
                "F10",
                f"only EXPERIMENTAL engines satisfy requirements; "
                f"experimental_candidates="
                f"{[m.get('engine_version') for m in experimental_candidates]}",
            )
        raise EngineResolverError(
            "F9",
            f"no FROZEN engine satisfies "
            f"required_capabilities={sorted(required_caps)} "
            f"required_contract_ids={sorted(required_contracts)}",
        )

    candidates.sort(key=lambda m: _semver_key(m["engine_version"]))
    selected = candidates[0]
    selected_key = _semver_key(selected["engine_version"])

    newer = [
        m["engine_version"]
        for m in candidates
        if _semver_key(m["engine_version"]) > selected_key
    ]
    if newer:
        logger.info(json.dumps({
            "event": "NEWER_ENGINE_AVAILABLE",
            "selected": selected["engine_version"],
            "newer_candidates": newer,
        }))

    return {
        "engine_version": selected["engine_version"],
        "engine_path": str(selected["_path"]),
        "contract_id": selected["contract_id"],
    }
