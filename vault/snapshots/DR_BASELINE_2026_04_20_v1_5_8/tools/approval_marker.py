"""
Approval marker read/write + hash-based validation.

Replaces the old pure-mtime EXPERIMENT_DISCIPLINE semantics: the marker now
stores a sha256 of strategy.py, and "approved" means the file's current hash
equals the stored hash. mtime is irrelevant — byte-identical rewrites by the
provisioner, `new_pass.py --rehash`, or reset flows no longer trip the gate.

Marker format (line-based, backward compatible):
    approved: 2026-04-17T16:51:42.280736+00:00
    strategy_sha256: <hex>

Legacy markers (timestamp only, no hash) are accepted when strategy.py mtime
is not newer than the marker — preserving the previous behavior for one grace
cycle. The Auto-Consistency Gate upgrades them on the next pipeline pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ApprovalMarker:
    approved_at: Optional[datetime]
    strategy_sha256: Optional[str]

    @property
    def has_hash(self) -> bool:
        return self.strategy_sha256 is not None


def compute_strategy_hash(strategy_py: Path) -> str:
    """sha256 hex of strategy.py's raw bytes."""
    return hashlib.sha256(strategy_py.read_bytes()).hexdigest()


def read_approved_marker(marker_path: Path) -> Optional[ApprovalMarker]:
    """Parse marker file. Returns None if missing; fields default to None if absent."""
    if not marker_path.exists():
        return None
    approved_at: Optional[datetime] = None
    strategy_sha: Optional[str] = None
    try:
        for raw_line in marker_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "approved":
                try:
                    approved_at = datetime.fromisoformat(value)
                except ValueError:
                    approved_at = None
            elif key == "strategy_sha256":
                strategy_sha = value.lower() or None
    except Exception:
        return ApprovalMarker(approved_at=None, strategy_sha256=None)
    return ApprovalMarker(approved_at=approved_at, strategy_sha256=strategy_sha)


def write_approved_marker(marker_path: Path, strategy_sha256: str) -> None:
    """Write marker with current timestamp and the strategy's sha256 hash."""
    ts = datetime.now(tz=timezone.utc).isoformat()
    marker_path.write_text(
        f"approved: {ts}\nstrategy_sha256: {strategy_sha256}\n",
        encoding="utf-8",
    )


def is_approval_current(strategy_py: Path, marker_path: Path) -> bool:
    """
    True iff the approval marker endorses the current strategy.py contents.

    - Primary: marker has a sha256 and it equals the current file's sha256.
    - Legacy fallback: marker has no sha256 (old format) -> accept iff
      strategy.py mtime is not newer than the marker's mtime.
    - Returns False if the marker is missing, unreadable, or clearly stale.
    """
    if not strategy_py.exists() or not marker_path.exists():
        return False
    marker = read_approved_marker(marker_path)
    if marker is None:
        return False
    if marker.has_hash:
        try:
            return compute_strategy_hash(strategy_py) == marker.strategy_sha256
        except Exception:
            return False
    # Legacy marker: fall back to mtime comparison (transitional behavior).
    try:
        return strategy_py.stat().st_mtime <= marker_path.stat().st_mtime
    except Exception:
        return False
