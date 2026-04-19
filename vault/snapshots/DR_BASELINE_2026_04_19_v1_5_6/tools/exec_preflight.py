import sys
import os
import argparse
from pathlib import Path

# --- ENCODING BOOTSTRAP ---
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from governance.preflight import run_preflight
from tools.directive_utils import load_directive_yaml, get_key_ci
from tools.pipeline_utils import get_engine_version


ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = get_engine_version()
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives" / "active_backup"


def emit_directive_advisories(directive_path: Path) -> None:
    """Print non-blocking advisories for known silent-zero traps.

    Current checks:
      - 1D timeframe + unset `trade_management.session_reset`. The engine
        default is `utc_day`, which clears pending entries at day-close and
        commonly produces 0-trade backtests with no error. Recommend setting
        `session_reset: none`.
    """
    try:
        data = load_directive_yaml(directive_path)
    except Exception:
        return  # governance/preflight.py will surface the parse error

    test_block = get_key_ci(data, "test") or {}
    tf_raw = get_key_ci(test_block, "timeframe") or get_key_ci(data, "timeframe") or ""
    tf = str(tf_raw).strip().lower()
    if tf not in {"1d", "d1", "1day"}:
        return

    tm = get_key_ci(data, "trade_management") or {}
    session_reset = get_key_ci(tm, "session_reset")
    if session_reset is None:
        print(
            "[ADVISORY] 1D directive without `trade_management.session_reset` set. "
            "Engine default `utc_day` clears pending entries at day-close and "
            "commonly produces 0-trade backtests. Recommend adding "
            "`session_reset: none` under `trade_management` (and mirroring in "
            "STRATEGY_SIGNATURE). See memory/feedback: 1D Strategy Engine "
            "Constraint."
        )


def resolve_directive(directive_id: str | None) -> Path:
    """
    Resolve directive path.

    If directive_id provided:
        - Locate that specific directive inside active/
    Else:
        - Fallback to legacy mode (expect exactly 1 active directive)
    """

    if directive_id:
        # Normalize extension
        if directive_id.endswith(".txt"):
            directive_id = directive_id[:-4]

        active_dir = PROJECT_ROOT / "backtest_directives" / "INBOX"
        candidates = [
            DIRECTIVES_DIR / directive_id,
            DIRECTIVES_DIR / f"{directive_id}.txt",
            active_dir / directive_id,
            active_dir / f"{directive_id}.txt",
        ]

        for path in candidates:
            if path.exists():
                return path

        print(f"[FATAL] Directive '{directive_id}' not found in INBOX folder.")
        sys.exit(1)

    # Legacy single-directive mode
    txt_files = list(DIRECTIVES_DIR.glob("*.txt"))
    if len(txt_files) != 1:
        print(f"[FATAL] Expected exactly 1 active directive, found {len(txt_files)}")
        sys.exit(1)

    return txt_files[0]


def main():
    parser = argparse.ArgumentParser(description="Run Preflight Checks")
    parser.add_argument(
        "directive",
        nargs="?",
        help="Optional directive ID (e.g., IDX28). If omitted, expects exactly one active directive."
    )
    args = parser.parse_args()

    directive_path = resolve_directive(args.directive)

    print(f"Running Preflight on: {directive_path.name}")

    emit_directive_advisories(directive_path)

    # Strict mode -- all integrity checks mandatory
    decision, explanation, scope = run_preflight(
        str(directive_path),
        ENGINE_NAME,
        ENGINE_VERSION,
    )

    print("-" * 60)
    print(f"DECISION: {decision}")
    print("-" * 60)
    print(f"Explanation: {explanation}")

    if decision == "ALLOW_EXECUTION":
        sys.exit(0)
    elif decision in ("ADMISSION_GATE", "AWAITING_HUMAN_APPROVAL"):
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
