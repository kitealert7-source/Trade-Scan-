import json
import os
from pathlib import Path

__all__ = ["get_active_engine"]


def get_active_engine() -> str:
    """Return the active single-asset engine version, underscored (e.g. "v1_5_8").

    The engine_registry.json ``active_engine`` field remains the selector; its
    value is normalised through the single config.engine_authority normalizer so
    the dotted/underscored conventions share one source. The convergence gate
    (test_selection_surfaces_converge_on_authority) asserts the registry's
    active_engine == config.engine_authority.CANONICAL_SINGLE_ASSET_ENGINE, so
    selection and the authority can never silently diverge (compute-binding by
    verification -- UNIFIED_ENGINE_AUTHORITY_PLAN.md §2c).

    Honours the ENGINE_VERSION_OVERRIDE env var — when set, returns it
    verbatim (after normalising dots to underscores) so the same lever
    controls both the loaded engine module and the reported version. The
    override is single-asset-only; baskets stay override-inert.
    """
    override = os.environ.get("ENGINE_VERSION_OVERRIDE", "").strip()
    if override:
        # Accept "v1_5_8", "1.5.8", "v1.5.8" — normalise to "v1_5_8"
        tok = override if override.startswith("v") else f"v{override}"
        return tok.replace(".", "_")

    reg_path = Path(__file__).parent / "engine_registry.json"

    if not reg_path.exists():
        raise FileNotFoundError(f"Engine registry missing: {reg_path}")

    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            registry_data = json.load(f)
        active_engine = registry_data.get("active_engine")
        if not active_engine:
            raise ValueError("Field 'active_engine' missing in registry.")
    except Exception as e:
        raise RuntimeError(f"Failed to parse engine registry: {e}")

    from config.engine_authority import normalize_engine_token
    return normalize_engine_token(active_engine, "underscore")
