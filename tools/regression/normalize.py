"""Normalization primitives for regression comparisons.

Removes benign non-determinism (timestamps, project-root paths, set iteration)
so goldens stay stable across runs and machines. Fields that are meant to be
strict (metrics, IDs, gates) are never touched here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Project root — populated lazily so importing this module does not assume
# a specific working directory.
_PROJECT_ROOT: str | None = None


def project_root_str() -> str:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        _PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
    return _PROJECT_ROOT


# --------------------------------------------------------------------------
# Timestamp patterns — match the common shapes emitted by the pipeline
# --------------------------------------------------------------------------
_ISO_TS = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_DATE_ONLY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_UNIX_MS = re.compile(r"\b1[6-9]\d{11}\b")  # 13-digit ms timestamps 2022+


def normalize_text(text: str, *, strip_dates: bool = False) -> str:
    """Normalize a free-form text blob (markdown, stdout, logs).

    Replaces timestamps, absolute project paths, and optionally bare dates.
    Collapses trailing whitespace on each line.
    """
    if not text:
        return text
    out = text
    out = out.replace(project_root_str(), "<PROJECT_ROOT>")
    out = out.replace(project_root_str().replace("\\", "/"), "<PROJECT_ROOT>")
    out = _ISO_TS.sub("<TS>", out)
    out = _UNIX_MS.sub("<TS_MS>", out)
    if strip_dates:
        out = _DATE_ONLY.sub("<DATE>", out)
    # Collapse trailing whitespace per line, normalize line endings.
    lines = [ln.rstrip() for ln in out.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# JSON / dict normalization
# --------------------------------------------------------------------------
# Keys whose values are set-like (order-insensitive) and should be sorted
# before comparison. Extend when new fields surface.
SET_LIKE_KEYS = frozenset({
    "constituent_run_ids",
    "unique_hashes",
    "run_ids",
    "source_run_ids",
    "symbols",
})

# Keys whose values are wall-clock timestamps and should be masked.
TIMESTAMP_KEYS = frozenset({
    "generated_at",
    "timestamp",
    "ts",
    "created_at",
    "written_at",
    "promoted_at",
})


def normalize_json(obj: Any) -> Any:
    """Recursively normalize a JSON-like object for comparison.

    - Timestamp-keyed values -> "<TS>"
    - Set-like lists sorted
    - Strings normalized via normalize_text()
    - Dicts traversed (keys preserved; comparison is key-based, not positional)
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in TIMESTAMP_KEYS and isinstance(v, (str, int, float)):
                out[k] = "<TS>"
            elif k in SET_LIKE_KEYS and isinstance(v, list):
                out[k] = sorted(normalize_json(item) for item in v)
            else:
                out[k] = normalize_json(v)
        return out
    if isinstance(obj, list):
        return [normalize_json(item) for item in obj]
    if isinstance(obj, str):
        # Don't touch short strings — only scrub things that look like paths/ts.
        return normalize_text(obj)
    return obj
