"""basket_schema.py — Multi-leg basket directive schema validator.

Plan ref: H2_ENGINE_PROMOTION_PLAN.md Phase 1 (Section 8).

Single source of truth for what a basket directive looks like. Consumed by:
  - tools/namespace_gate.py  -- structural validation at directive admission
  - governance/preflight.py  -- additional check at preflight gate
  - tools/basket_runner.py   -- Phase 2 (runtime — reads same schema)

Schema (basket directives are detected by presence of top-level `basket:` block):

  basket:
    basket_id: H2                      # required; uppercase + digits; matches symbol slot in directive name
    legs:                              # required; >= 2 legs
      - symbol: EURUSD                 # required; appears in active asset universe
        lot: 0.02                      # required; > 0
        direction: long                # required; long | short
      - symbol: USDJPY
        lot: 0.01
        direction: short
    initial_stake_usd: 1000.0          # optional (rule may default)
    harvest_threshold_usd: 2000.0      # optional (rule may default)
    recycle_rule:                      # required
      name: H2_v7_compression          # required; must exist in governance/recycle_rules/registry.yaml
      version: 1                       # required; must match registry entry
      params:                          # optional override; merged over registry defaults
        compression_5d_threshold: 10.0
    regime_gate:                       # optional
      factor: USD_SYNTH.compression_5d
      operator: '>='
      value: 10

The validator returns a list of strings. Empty list = valid. Non-empty =
each entry is one human-readable failure to display to the user.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_VALID_DIRECTIONS = {"long", "short"}
_VALID_OPERATORS = {">", ">=", "<", "<=", "==", "!="}
_BASKET_ID_RE = re.compile(r"^[A-Z][A-Z0-9]+$")


def is_basket_directive(directive: dict[str, Any]) -> bool:
    """True if the directive contains a top-level `basket:` block."""
    return isinstance(directive, dict) and "basket" in directive


def _load_recycle_registry(registry_path: Path) -> dict[str, dict[str, Any]]:
    """Index recycle_rules registry by (name, version) -> rule dict."""
    if not registry_path.is_file():
        return {}
    with open(registry_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    by_name: dict[str, dict[str, Any]] = {}
    for rule in data.get("rules", []) or []:
        n = rule.get("name")
        v = rule.get("version")
        if n is None or v is None:
            continue
        by_name[f"{n}@{v}"] = rule
    return by_name


def validate_basket_block(directive: dict[str, Any],
                          recycle_registry_path: Path | None = None,
                          name_symbol_slot: str | None = None
                          ) -> list[str]:
    """Validate the `basket:` block of a directive.

    Args:
      directive: full parsed directive dict
      recycle_registry_path: path to governance/recycle_rules/registry.yaml;
        when None or missing, recycle_rule.name validation is best-effort.
      name_symbol_slot: the SYMBOL token parsed from the directive filename;
        when given, must equal basket.basket_id.

    Returns:
      List of error strings (empty if valid).
    """
    errors: list[str] = []

    block = directive.get("basket")
    if not isinstance(block, dict):
        return ["BASKET_SCHEMA: top-level `basket:` block is missing or not a mapping."]

    # basket_id
    bid = block.get("basket_id")
    if not isinstance(bid, str) or not _BASKET_ID_RE.fullmatch(bid):
        errors.append(
            f"BASKET_SCHEMA: basket.basket_id must be UPPER[A-Z0-9]+, got {bid!r}."
        )
    elif name_symbol_slot is not None and bid != name_symbol_slot:
        errors.append(
            f"BASKET_SCHEMA: basket.basket_id={bid!r} must equal the SYMBOL "
            f"slot in the directive filename ({name_symbol_slot!r})."
        )

    # legs
    legs = block.get("legs")
    if not isinstance(legs, list) or len(legs) < 2:
        errors.append(
            f"BASKET_SCHEMA: basket.legs must be a list with at least 2 entries "
            f"(got {type(legs).__name__} len={len(legs) if isinstance(legs, list) else '-'})."
        )
    else:
        seen_symbols: set[str] = set()
        for idx, leg in enumerate(legs):
            if not isinstance(leg, dict):
                errors.append(f"BASKET_SCHEMA: legs[{idx}] is not a mapping.")
                continue
            sym = leg.get("symbol")
            lot = leg.get("lot")
            direction = leg.get("direction")
            if not isinstance(sym, str) or not sym:
                errors.append(f"BASKET_SCHEMA: legs[{idx}].symbol is missing or empty.")
            elif sym in seen_symbols:
                errors.append(f"BASKET_SCHEMA: legs[{idx}].symbol={sym!r} is duplicated.")
            else:
                seen_symbols.add(sym)
            if not isinstance(lot, (int, float)) or float(lot) <= 0:
                errors.append(f"BASKET_SCHEMA: legs[{idx}].lot must be > 0, got {lot!r}.")
            if direction not in _VALID_DIRECTIONS:
                errors.append(
                    f"BASKET_SCHEMA: legs[{idx}].direction must be one of "
                    f"{sorted(_VALID_DIRECTIONS)}, got {direction!r}."
                )

    # initial_stake_usd / harvest_threshold_usd (optional but if present, positive)
    for key in ("initial_stake_usd", "harvest_threshold_usd"):
        if key in block:
            v = block[key]
            if not isinstance(v, (int, float)) or float(v) <= 0:
                errors.append(f"BASKET_SCHEMA: basket.{key} must be > 0 when present, got {v!r}.")

    # recycle_rule
    rule = block.get("recycle_rule")
    if not isinstance(rule, dict):
        errors.append("BASKET_SCHEMA: basket.recycle_rule must be a mapping.")
    else:
        rn = rule.get("name")
        rv = rule.get("version")
        if not isinstance(rn, str) or not rn:
            errors.append("BASKET_SCHEMA: basket.recycle_rule.name is missing.")
        if not isinstance(rv, int) or rv < 1:
            errors.append(
                f"BASKET_SCHEMA: basket.recycle_rule.version must be int >= 1, got {rv!r}."
            )
        if recycle_registry_path is not None and isinstance(rn, str) and isinstance(rv, int):
            registry = _load_recycle_registry(recycle_registry_path)
            key = f"{rn}@{rv}"
            if not registry:
                errors.append(
                    f"BASKET_SCHEMA: governance/recycle_rules/registry.yaml is missing or empty; "
                    f"cannot validate recycle_rule {key!r}."
                )
            elif key not in registry:
                errors.append(
                    f"BASKET_SCHEMA: recycle_rule {key!r} is not registered. "
                    f"Add it to governance/recycle_rules/registry.yaml first."
                )
        rp = rule.get("params")
        if rp is not None and not isinstance(rp, dict):
            errors.append("BASKET_SCHEMA: basket.recycle_rule.params must be a mapping when present.")

    # regime_gate (optional)
    gate = block.get("regime_gate")
    if gate is not None:
        if not isinstance(gate, dict):
            errors.append("BASKET_SCHEMA: basket.regime_gate must be a mapping when present.")
        else:
            f = gate.get("factor")
            op = gate.get("operator")
            val = gate.get("value")
            if not isinstance(f, str) or "." not in f:
                errors.append(
                    f"BASKET_SCHEMA: basket.regime_gate.factor must be 'NAMESPACE.field' form, got {f!r}."
                )
            if op not in _VALID_OPERATORS:
                errors.append(
                    f"BASKET_SCHEMA: basket.regime_gate.operator must be one of "
                    f"{sorted(_VALID_OPERATORS)}, got {op!r}."
                )
            if not isinstance(val, (int, float, str)):
                errors.append(
                    f"BASKET_SCHEMA: basket.regime_gate.value must be number or string, got {type(val).__name__}."
                )

    return errors


__all__ = ["is_basket_directive", "validate_basket_block"]
