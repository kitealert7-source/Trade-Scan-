"""
[DEPRECATED] Unified Robustness Evaluation CLI.
This script has been consolidated into the versioned engine under tools/robustness.
Please use `python tools/robustness/cli.py` directly in the future.
"""
import sys

def main():
    print("[DEPRECATION WARNING] evaluate_robustness.py is deprecated and will be removed in v3.0.", file=sys.stderr)
    print("[DEPRECATION WARNING] Redirecting to tools.robustness.cli.main()...\n", file=sys.stderr)
    
    from tools.robustness.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
