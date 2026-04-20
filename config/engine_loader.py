import json
import os
from pathlib import Path

__all__ = ["get_active_engine"]


def get_active_engine() -> str:
    """Load the active engine version from config/engine_registry.json.

    Honours the ENGINE_VERSION_OVERRIDE env var — when set, returns it
    verbatim (after normalising dots to underscores) so the same lever
    controls both the loaded engine module and the reported version.
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
        return active_engine
    except Exception as e:
        raise RuntimeError(f"Failed to parse engine registry: {e}")
