import json
from pathlib import Path

__all__ = ["get_active_engine"]


def get_active_engine() -> str:
    """Load the active engine version from config/engine_registry.json."""
    # Assuming this file is in config/, the registry is in the same directory
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
