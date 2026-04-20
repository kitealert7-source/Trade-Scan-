"""
tools/sync_multisymbol_strategy.py

Sync per-symbol strategy copies from a base strategy.py.

Source of truth: strategies/<BASE_ID>/strategy.py
Targets:        strategies/<BASE_ID>_<S>/strategy.py  (for each symbol S)

Only the `name = "..."` line is modified. Everything else is a verbatim copy of the base.
No partial edits. Always full overwrite.

Usage:
    # Sync (overwrites per-symbol copies):
    python tools/sync_multisymbol_strategy.py <BASE_ID> <SYM1> [<SYM2> ...]

    # Check only (no writes, non-zero exit if drift detected):
    python tools/sync_multisymbol_strategy.py --check <BASE_ID> <SYM1> [<SYM2> ...]

Example:
    python tools/sync_multisymbol_strategy.py 15_MR_FX_15M_ASRANGE_SESSFILT_S03_V1_P02 AUDUSD NZDUSD AUDNZD
    python tools/sync_multisymbol_strategy.py --check 15_MR_FX_15M_ASRANGE_SESSFILT_S03_V1_P02 AUDUSD NZDUSD AUDNZD
"""

import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"

# Matches:  name = "some_strategy_id"
# Handles leading whitespace (class attribute indentation).
_NAME_LINE_RE = re.compile(r'^(\s*name\s*=\s*")[^"]*(")')


def _normalize(lines: list[str]) -> list[str]:
    """Replace the value of the name field with a sentinel for comparison."""
    return [_NAME_LINE_RE.sub(r'\g<1>__NAME__\2', line) for line in lines]


def check_symbol(base_id: str, symbol: str) -> bool:
    """
    Compare base vs per-symbol copy, ignoring the name line.
    Returns True if in sync, False if drift detected.
    Exits with code 2 on missing files.
    """
    base_path = STRATEGIES_DIR / base_id / "strategy.py"
    target_path = STRATEGIES_DIR / f"{base_id}_{symbol}" / "strategy.py"

    if not base_path.exists():
        print(f"[ERROR] Base not found: {base_path}", file=sys.stderr)
        sys.exit(2)

    if not target_path.exists():
        print(f"[DRIFT] {base_id}_{symbol}: target file missing")
        return False

    base_lines = base_path.read_text(encoding="utf-8").splitlines(keepends=True)
    target_lines = target_path.read_text(encoding="utf-8").splitlines(keepends=True)

    if _normalize(base_lines) != _normalize(target_lines):
        print(f"[DRIFT] {base_id}_{symbol}: content differs from base")
        return False

    return True


def sync_symbol(base_id: str, symbol: str) -> None:
    """
    Overwrite per-symbol strategy.py from base, changing only the name field.
    Target folder must already exist. Never creates folders.
    """
    base_path = STRATEGIES_DIR / base_id / "strategy.py"
    target_path = STRATEGIES_DIR / f"{base_id}_{symbol}" / "strategy.py"
    new_name = f"{base_id}_{symbol}"

    if not base_path.exists():
        print(f"[ERROR] Base not found: {base_path}", file=sys.stderr)
        sys.exit(2)

    if not target_path.parent.exists():
        print(f"[ERROR] Target folder missing: {target_path.parent}", file=sys.stderr)
        print(f"        Create the folder first: strategies/{base_id}_{symbol}/", file=sys.stderr)
        sys.exit(2)

    base_lines = base_path.read_text(encoding="utf-8").splitlines(keepends=True)

    new_lines = []
    replaced = False
    for line in base_lines:
        if _NAME_LINE_RE.match(line):
            new_lines.append(_NAME_LINE_RE.sub(f'\\g<1>{new_name}\\2', line))
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        print(f"[ERROR] No 'name = \"...\"' line found in {base_path}", file=sys.stderr)
        sys.exit(2)

    target_path.write_text("".join(new_lines), encoding="utf-8")
    print(f"[SYNCED] {target_path.relative_to(PROJECT_ROOT)}")


def main() -> None:
    args = sys.argv[1:]
    check_only = "--check" in args
    args = [a for a in args if a != "--check"]

    if len(args) < 2:
        print(
            "Usage: python tools/sync_multisymbol_strategy.py [--check] <BASE_ID> <SYM1> [<SYM2> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    base_id = args[0]
    symbols = args[1:]

    if check_only:
        drift = False
        for sym in symbols:
            if not check_symbol(base_id, sym):
                drift = True
        if drift:
            sys.exit(1)
        print(f"[OK] {base_id}: all {len(symbols)} per-symbol copies in sync")
        sys.exit(0)
    else:
        for sym in symbols:
            sync_symbol(base_id, sym)
        print(f"[DONE] Synced {len(symbols)} symbol(s) from base: {base_id}")


if __name__ == "__main__":
    main()
