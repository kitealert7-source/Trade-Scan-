"""
directive_utils.py
Shared directive loading and key access helpers.

Authority: Raw YAML file is the single source of truth.
No normalization.
No mutation.
No inference.
"""

import yaml
from pathlib import Path


def load_directive_yaml(path: Path) -> dict:
    """
    Load directive YAML deterministically.
    No transformation.
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_key_ci(d: dict, key: str):
    """
    Case-insensitive key lookup.
    Returns value or None.
    Does not modify input.
    """
    if not isinstance(d, dict):
        return None
    for k in d.keys():
        if k.lower() == key.lower():
            return d[k]
    return None
