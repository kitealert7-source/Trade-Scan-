"""research_metrics.py -- governance for the cointegration ledger's metrics_json.

Loads governance/research_metrics_registry.yaml and validates a metrics_json
payload against it. This is the mechanism that keeps `metrics_json` a governed,
flat, typed, namespaced key-value store rather than a hidden schema.

Contract enforced by validate_metrics_json():
  - None / "" / {} payload is allowed (no extras).
  - Every key must be registered AND first_class:false.
  - Values must be scalars of the registered type (float|int|str|bool);
    nesting (dict/list) is rejected.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from config.path_authority import REAL_REPO_ROOT

REGISTRY_PATH = REAL_REPO_ROOT / "governance" / "research_metrics_registry.yaml"

# Registered type -> acceptable Python types. float accepts int (widening).
_PY_TYPES: dict[str, tuple[type, ...]] = {
    "float": (int, float),
    "int": (int,),
    "str": (str,),
    "bool": (bool,),
}


class MetricsRegistryError(ValueError):
    """Raised when a metrics_json payload violates the registry contract."""


def load_registry(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return {key: entry} from the registry YAML. Empty registry -> {}."""
    p = path or REGISTRY_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = data.get("metrics") or []
    reg: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = e.get("key")
        if key:
            reg[key] = e
    return reg


def validate_metrics_json(
    payload: Any,
    *,
    registry: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Raise MetricsRegistryError if `payload` violates the registry contract.

    Accepts a dict, a JSON string, or None/"" (empty -> no-op). Scalar-only,
    registered-keys-only, type-checked, no first_class keys in the blob.
    """
    if payload is None or payload == "":
        return
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MetricsRegistryError(f"metrics_json is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        raise MetricsRegistryError(
            f"metrics_json must be a flat JSON object, got {type(payload).__name__}"
        )

    reg = registry if registry is not None else load_registry()
    for key, val in payload.items():
        entry = reg.get(key)
        if entry is None:
            raise MetricsRegistryError(
                f"unknown metric key '{key}' -- register it in "
                f"research_metrics_registry.yaml before emitting it"
            )
        if entry.get("first_class"):
            raise MetricsRegistryError(
                f"'{key}' is first_class (a typed column); it must not appear "
                f"in metrics_json"
            )
        if isinstance(val, (dict, list)):
            raise MetricsRegistryError(
                f"metric '{key}' must be a scalar; nesting is not allowed"
            )
        expected = entry.get("type")
        py = _PY_TYPES.get(expected)
        if py is None:
            raise MetricsRegistryError(
                f"registry type '{expected}' for '{key}' is invalid "
                f"(use float|int|str|bool)"
            )
        # bool is a subclass of int -- reject bool where a number is expected.
        if expected in ("int", "float") and isinstance(val, bool):
            raise MetricsRegistryError(f"metric '{key}' expected {expected}, got bool")
        if not isinstance(val, py):
            raise MetricsRegistryError(
                f"metric '{key}' expected {expected}, got {type(val).__name__}"
            )


__all__ = ["MetricsRegistryError", "REGISTRY_PATH", "load_registry", "validate_metrics_json"]
