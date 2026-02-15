import sys
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from governance.preflight import run_preflight


ENGINE_NAME = "Universal_Research_Engine"
ENGINE_VERSION = "1.2.0"
DIRECTIVES_DIR = PROJECT_ROOT / "backtest_directives" / "active"


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

        candidates = [
            DIRECTIVES_DIR / directive_id,
            DIRECTIVES_DIR / f"{directive_id}.txt",
        ]

        for path in candidates:
            if path.exists():
                return path

        print(f"[FATAL] Directive '{directive_id}' not found in active folder.")
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

    # Vault check permanently disabled (workspace-only model)
    decision, explanation, scope = run_preflight(
        str(directive_path),
        ENGINE_NAME,
        ENGINE_VERSION,
        skip_vault_check=True
    )

    print("-" * 60)
    print(f"DECISION: {decision}")
    print("-" * 60)
    print(f"Explanation: {explanation}")

    if decision == "ALLOW_EXECUTION":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
