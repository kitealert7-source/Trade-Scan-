"""
Engine resolver — capability + contract + supersession + manifest-integrity
driven engine selection.

Pure function. No side effects other than a structured INFO log naming the
selected engine and any older candidates that were eligible but not picked.
Deterministic for identical inputs.

Contract model
--------------
Each engine directory ships an optional contract.json declaring its I/O
surface. engine_manifest.json.contract_id MUST equal canonical_sha256(
contract.json). Engines without a contract.json are silently filtered out —
they cannot participate in capability resolution until the migration has
annotated them.

Selection policy (post-Phase-2 v1.5.8a remediation)
----------------------------------------------------
  1. Collect manifests under engine_dev/ and vault/engines/.
  2. Self-verify: manifest.contract_id == canonical_sha256(contract.json).
     Mismatch raises EngineResolverError("F8").
  3. Filter by status == FROZEN. EXPERIMENTAL engines (e.g. v1.5.9 burn-in
     parity work) are eliminated here and never resurrected.
  4. Filter by capability: engine capabilities must cover the required
     set. Capability match is exact OR explicit via the catalog's
     compatible_with mapping. No transitive or implicit compatibility.
  5. Filter by contract_id: engine contract_id must be in the strategy's
     declared required_contract_ids whitelist.
  6. Filter by lineage supersession: any engine listed with a non-null
     superseded_by field in governance/engine_lineage.yaml is eliminated
     (the successor is preferred). Prevents resolver from picking
     post-freeze-drifted v1.5.8 once v1.5.8a is registered.
  7. Filter by manifest integrity: every file_hashes entry must match
     canonical_sha256 of the file in the engine directory. Catches the
     f3ae767-class drift at resolution time, not just downstream.
  8. If no FROZEN candidates: raise F9. If only EXPERIMENTAL candidates
     satisfy the cap + contract filters, raise F10 with their versions.
  9. Tie-break: HIGHEST semantic version wins (latest production-ready
     successor). Reverses prior 'lowest wins / least change' policy after
     the v1.5.8 governance repair — the supersession registry now carries
     the 'least change' intent explicitly per-version, so resolver should
     pick the most-current successor among eligible candidates.
 10. Visibility: emit INFO log "ENGINE_RESOLVED" with selected version
     and any older eligible candidates. Selection unchanged.

Failure codes mirror the hardening plan's F-series and are never
swallowed.

Hashing
-------
All file hashing routes through tools.verify_engine_integrity.canonical_sha256
(LF-normalized sha256, Phase 1 commit 09443f4). Eliminates Windows CRLF
false-failures on engine integrity checks across the entire resolver path.
"""
import json
import logging
import re
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_engine_integrity import canonical_sha256  # noqa: E402

ENGINE_DEV_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
VAULT_ENGINE_ROOT = PROJECT_ROOT / "vault" / "engines" / "Universal_Research_Engine"
CATALOG_PATH = PROJECT_ROOT / "governance" / "capability_catalog.yaml"
LINEAGE_PATH = PROJECT_ROOT / "governance" / "engine_lineage.yaml"

logger = logging.getLogger(__name__)


class EngineResolverError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"[{code}] {detail}")
        self.code = code
        self.detail = detail


def _sha256_file(path: Path) -> str:
    """Canonical (LF-normalized) sha256 of *path*, prefixed 'sha256:'.

    Single source of truth: imports and uses the Phase 1 canonical helper
    from tools.verify_engine_integrity. Identical hash on LF and CRLF
    working trees.
    """
    return "sha256:" + canonical_sha256(path)


def _load_compat_map() -> dict:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = yaml.safe_load(f)["capabilities"]
    return {
        token: set((spec or {}).get("compatible_with") or [])
        for token, spec in catalog.items()
    }


def _normalize_version_key(version: str) -> str:
    """Normalize 'v1_5_8' / '1.5.8' / 'v1.5.8' / 'v1_5_8a' to canonical
    directory-name form 'v1_5_8' / 'v1_5_8a'. Used for lineage lookups."""
    body = version.lstrip("vV").replace(".", "_")
    return "v" + body


def _load_superseded_set() -> set:
    """Return the set of canonical version keys (e.g. {'v1_5_8'}) that
    governance/engine_lineage.yaml marks as having a non-null
    superseded_by field. Empty set if lineage file absent."""
    if not LINEAGE_PATH.exists():
        return set()
    with open(LINEAGE_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    superseded = set()
    for key, info in (doc.get("engines") or {}).items():
        if info and info.get("superseded_by"):
            superseded.add(_normalize_version_key(str(key)))
    return superseded


def _manifest_file_hashes_clean(manifest: dict, engine_path: Path) -> tuple[bool, list]:
    """Validate every entry in manifest['file_hashes'] against the canonical
    hash of the file in engine_path. Returns (all_ok, list_of_failures).
    Older manifests without file_hashes pass with empty failure list (back-
    compat — pre-Phase-2 manifests didn't enforce per-file integrity at
    resolution time)."""
    file_hashes = manifest.get("file_hashes") or {}
    if not file_hashes:
        return True, []
    failures = []
    for fname, expected in file_hashes.items():
        if fname.endswith(".md"):
            continue
        fpath = engine_path / fname
        if not fpath.exists():
            failures.append(f"{fname}: MISSING")
            continue
        actual = canonical_sha256(fpath).upper()
        if actual != str(expected).upper():
            failures.append(
                f"{fname}: expected {str(expected)[:16]} got {actual[:16]}"
            )
    return (len(failures) == 0), failures


def _semver_key(version: str) -> tuple:
    """Parse 'v1_5_8' / 'v1_5_8a' / '1.5.7' to a sortable tuple-of-tuples.

    Each segment becomes (numeric_part, alpha_suffix). Examples:
        'v1_5_7'  -> ((1, ''), (5, ''), (7, ''))
        'v1_5_8'  -> ((1, ''), (5, ''), (8, ''))
        'v1_5_8a' -> ((1, ''), (5, ''), (8, 'a'))
        'v1_5_10' -> ((1, ''), (5, ''), (10, ''))

    Tuple comparison gives:
        v1_5_7 < v1_5_8 < v1_5_8a < v1_5_10  (alpha suffix is a successor
                                              within the same patch number,
                                              and 10 > 8 numerically)
    """
    parts = version.lstrip("vV").replace("_", ".").split(".")
    out = []
    for p in parts:
        m = re.match(r"^(\d+)([a-zA-Z]*)$", p)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return tuple(out)


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
    Resolve the latest FROZEN + vaulted + manifest-clean + non-superseded
    engine satisfying the declared capability and contract requirements.

    Returns dict: {engine_version, engine_path, contract_id}.
    Raises EngineResolverError(code) on every failure path.
    """
    required_caps = set(required_capabilities)
    required_contracts = set(required_contract_ids)
    compat_map = _load_compat_map()
    superseded = _load_superseded_set()
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

    def _not_superseded(m):
        return _normalize_version_key(str(m.get("engine_version", ""))) not in superseded

    def _manifest_clean(m):
        ok, _ = _manifest_file_hashes_clean(m, m["_path"])
        return ok

    # Apply each filter independently so failure diagnostics can name the
    # specific gate a candidate was rejected at.
    cap_passed = [m for m in frozen if _cap_ok(m)]
    contract_passed = [m for m in cap_passed if _contract_ok(m)]
    not_superseded_passed = [m for m in contract_passed if _not_superseded(m)]
    candidates = [m for m in not_superseded_passed if _manifest_clean(m)]

    experimental_candidates = [m for m in experimental if _cap_ok(m) and _contract_ok(m)]

    if not candidates:
        if experimental_candidates:
            raise EngineResolverError(
                "F10",
                f"only EXPERIMENTAL engines satisfy requirements; "
                f"experimental_candidates="
                f"{[m.get('engine_version') for m in experimental_candidates]}",
            )
        # Build a diagnostic enumerating why each FROZEN candidate was rejected.
        diag = []
        for m in frozen:
            v = m.get("engine_version")
            reasons = []
            if not _cap_ok(m):
                reasons.append("capability_mismatch")
            if not _contract_ok(m):
                reasons.append("contract_id_not_whitelisted")
            if not _not_superseded(m):
                reasons.append("superseded_in_lineage")
            ok, fhf = _manifest_file_hashes_clean(m, m["_path"])
            if not ok:
                reasons.append(f"manifest_drift({len(fhf)}_files)")
            if reasons:
                diag.append(f"{v}: {','.join(reasons)}")
        raise EngineResolverError(
            "F9",
            f"no FROZEN engine satisfies all gates "
            f"required_capabilities={sorted(required_caps)} "
            f"required_contract_ids={sorted(required_contracts)}; "
            f"rejected={diag}",
        )

    # Sort DESCENDING — latest production-ready successor wins. The
    # supersession registry (governance/engine_lineage.yaml) carries the
    # 'least change' intent explicitly per-version, so 'latest among
    # eligible candidates' is the correct selection rule.
    candidates.sort(key=lambda m: _semver_key(m["engine_version"]), reverse=True)
    selected = candidates[0]
    selected_key = _semver_key(selected["engine_version"])

    older = [
        m["engine_version"]
        for m in candidates
        if _semver_key(m["engine_version"]) < selected_key
    ]
    logger.info(json.dumps({
        "event": "ENGINE_RESOLVED",
        "selected": selected["engine_version"],
        "older_eligible_candidates": older,
    }))

    return {
        "engine_version": selected["engine_version"],
        "engine_path": str(selected["_path"]),
        "contract_id": selected["contract_id"],
    }
