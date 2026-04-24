"""
Observation-only event recorder for convexity research probes.

Consumed by strategies that want to record intrabar events (e.g. adverse
excursion crossing a threshold) without performing file I/O in strategy
code, which the semantic validator forbids.

Writes append-only CSV rows to a file under the project `tmp/` directory.
Header is written lazily on first call per-file. Exceptions are swallowed
so that an instrumentation failure can never break a research run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


_HEADER_BY_PATH: dict[str, bool] = {}


def record_event(csv_path: Path | str, header: str, row: Iterable) -> None:
    """Append one event row to csv_path. Writes header on first call per path."""
    try:
        p = Path(csv_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        key = str(p.resolve())
        need_header = key not in _HEADER_BY_PATH and (
            not p.exists() or p.stat().st_size == 0
        )
        with p.open("a", encoding="utf-8") as f:
            if need_header:
                f.write(header.rstrip("\n") + "\n")
            f.write(",".join("" if x is None else str(x) for x in row) + "\n")
        _HEADER_BY_PATH[key] = True
    except Exception:
        # Observation layer must never break a run.
        pass
