"""Register a sweep stub via the canonical API (collision-safe).

Use this instead of direct YAML edits to `governance/namespace/sweep_registry.yaml`.
Direct YAML edits bypass collision detection and have caused silent data loss
(INFRA-NEWS-009: a manual stub for idea 22 sweep S13 silently overwrote the
pre-existing 30M directive's claim on the same slot).

Usage:
    python tools/register_sweep_stub.py <idea_id> <directive_name> [--slot SXX]

Examples:
    # Auto-pick next free slot:
    python tools/register_sweep_stub.py 64 64_BRK_IDX_30M_NEWSBRK_S99_V1_P00

    # Reserve a specific slot (HARD_FAILs on collision):
    python tools/register_sweep_stub.py 22 22_CONT_FX_15M_RSIAVG_TRENDFILT_S15_V1_P00 --slot S15

The stub uses placeholder hashes that are auto-replaced by the
auto-consistency gate on the first real run of the directive.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.sweep_registry_gate import (
    reserve_sweep_identity,
    SweepRegistryError,
)

PLACEHOLDER_HASH = "0" * 64  # Auto-consistency replaces on first real run.


def main() -> int:
    p = argparse.ArgumentParser(description="Register a sweep stub (collision-safe).")
    p.add_argument("idea_id", help="Two-digit idea identifier, e.g. '64'")
    p.add_argument("directive_name", help="Full structured directive name (no .txt)")
    p.add_argument("--slot", default=None,
                   help="Specific slot SXX. Omit to auto-pick next free slot.")
    args = p.parse_args()

    try:
        result = reserve_sweep_identity(
            idea_id=args.idea_id,
            directive_name=args.directive_name,
            signature_hash=PLACEHOLDER_HASH,
            requested_sweep=args.slot,
            auto_advance=True,
        )
    except SweepRegistryError as e:
        # The error message includes next-free-slot suggestion when available.
        print(f"REGISTRATION_FAILED: {e}", file=sys.stderr)
        return 2

    print(
        f"OK: idea={result['idea_id']} sweep={result['sweep']} "
        f"directive={result['strategy_name']} status={result['status']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
