"""STRATEGY_SIGNATURE flatten + diff helpers for family report lineage.

Wrapper-first per FAMILY_REPORT_IMPLEMENTATION_PLAN.md Rule 4: this module
duplicates the inline `_flatten`, `_extract_sig`, and `_diff` helpers from
``tools/generate_strategy_card.py:33-113`` rather than extracting them. The
original implementation stays untouched in the first release.

Function bodies are byte-equivalent to the originals; unit tests pin both
copies against the same fixture inputs so any future divergence is
detectable.

Public surface (used by `tools/report/family_renderer.py`):
  - flatten_signature(strategy_py_path) -> dict[str, Any]
  - diff_signatures(prev_sig, curr_sig) -> list[tuple[key, prev_val, curr_val]]
  - parse_strategy_name(name) -> (prefix, sweep, version, pass_n) | None
  - extract_signature_from_source(source: str) -> dict
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


# Mirrors `_SKIP_KEYS` and `_SKIP_VAL_KEYS` in `tools/generate_strategy_card.py:27-28`.
_SKIP_KEYS = {"indicators", "signature_version"}
_SKIP_VAL_KEYS = {"type", "condition"}


def _flatten(obj, prefix: str = "", out: dict | None = None) -> dict:
    """Recursively flatten STRATEGY_SIGNATURE into {dotted.key: value}.

    Byte-equivalent to `_flatten` in `tools/generate_strategy_card.py:33-46`.
    """
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS or k in _SKIP_VAL_KEYS:
                continue
            fk = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _flatten(v, fk, out)
            elif not isinstance(v, list):
                out[fk] = v
    return out


def parse_strategy_name(name: str) -> tuple[str, int, int, int] | None:
    """Return (prefix, sweep, version, pass_n) parsed from a strategy id.

    Byte-equivalent to `_parse_name` in `tools/generate_strategy_card.py:49-52`.
    """
    m = re.search(r"^(.*?)_S(\d+)_V(\d+)_P(\d+)$", name)
    return (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def extract_signature_from_source(source: str) -> dict:
    """Extract STRATEGY_SIGNATURE dict from `strategy.py` source.

    Byte-equivalent to `_extract_sig` in `tools/generate_strategy_card.py:90-102`.
    """
    m = re.search(
        r"# --- STRATEGY SIGNATURE START ---\s*(.*?)\s*# --- STRATEGY SIGNATURE END ---",
        source, re.DOTALL,
    )
    if not m:
        return {}
    text = re.sub(r"^STRATEGY_SIGNATURE\s*=\s*", "", m.group(1).strip())
    try:
        return ast.literal_eval(text)
    except Exception:
        return {}


def flatten_signature(strategy_py_path: Path) -> dict[str, Any]:
    """Read a strategy.py and return its flattened signature dict.

    Returns ``{}`` if the file is missing or the signature can't be parsed.
    """
    try:
        source = Path(strategy_py_path).read_text(encoding="utf-8")
    except Exception:
        return {}
    sig = extract_signature_from_source(source)
    return _flatten(sig)


def diff_signatures(prev_sig: dict, curr_sig: dict) -> list[tuple[str, str, str]]:
    """Return [(key, prev_val, curr_val)] for each changed/added/removed field.

    Inputs may be raw signatures (will be flattened) or already-flattened dicts.

    Byte-equivalent to `_diff` in `tools/generate_strategy_card.py:105-113`.
    """
    p = _flatten(prev_sig) if _looks_nested(prev_sig) else dict(prev_sig)
    c = _flatten(curr_sig) if _looks_nested(curr_sig) else dict(curr_sig)
    rows: list[tuple[str, str, str]] = []
    for k in sorted(set(p) | set(c)):
        pv, cv = p.get(k, "—"), c.get(k, "—")
        if pv != cv:
            rows.append((k, str(pv), str(cv)))
    return rows


def _looks_nested(d) -> bool:
    """Heuristic: a raw signature has nested dicts, a flattened one doesn't."""
    if not isinstance(d, dict):
        return False
    return any(isinstance(v, dict) for v in d.values())
