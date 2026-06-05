"""CHOCH-family semantic-contract guard (static, indicators/-scoped).

The directive-scanning contract that formerly lived here — every directive-
DECLARED indicator must declare a valid SIGNAL_PRIMITIVE / PIVOT_SOURCE — was
migrated 2026-06-05 into `tools/semantic_validator.py`. It now runs at ADMISSION
/ pre-backtest on the directive's declared indicators (the point where the
decision is made), instead of re-scanning ~6,963 completed directives at commit
time (which only ever rediscovered ATR and cost ~23s). Coverage equivalence was
proven before retirement. See `tests/test_semantic_validator_contract.py` and
memory `project_semantic_contract_gate_migration`.

Retained here: only the standalone CHOCH guard. CHOCH is the most drift-prone
indicator family, so a fast static check that every choch module declares
SIGNAL_PRIMITIVE — regardless of whether any directive currently references it —
is cheap insurance that does not depend on the directive corpus.
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDICATORS_ROOT = PROJECT_ROOT / "indicators"


def test_choch_family_must_declare_primitive():
    """Any indicator module whose filename contains 'choch' must declare
    SIGNAL_PRIMITIVE — regardless of whether it's currently referenced."""
    missing = []
    for path in INDICATORS_ROOT.rglob("*.py"):
        if "choch" not in path.name.lower():
            continue
        text = path.read_text(encoding="utf-8")
        if not re.search(r"^\s*SIGNAL_PRIMITIVE\s*=", text, re.MULTILINE):
            missing.append(str(path.relative_to(PROJECT_ROOT)))
    assert not missing, (
        "CHOCH-family modules missing SIGNAL_PRIMITIVE:\n  " + "\n  ".join(missing)
    )
