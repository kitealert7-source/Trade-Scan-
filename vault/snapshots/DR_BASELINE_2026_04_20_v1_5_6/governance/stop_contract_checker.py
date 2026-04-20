"""
stop_contract_checker.py — Pre-Admission SL/TP Contract Guard

Authority: SOP_TESTING (Stage-0.56, adjacent to semantic_coverage_checker)
Purpose:
    Prevent the signal-bar-close vs. next-bar-open stop/tp mismatch that
    produces STOP CONTRACT VIOLATION at Stage-1.

Rule:
    If a directive sets `order_placement.execution_timing == "next_bar_open"`
    AND the generated `strategy.py` returns `stop_price` or `tp_price` from
    `check_entry`, the stop is computed at signal-bar close but applied
    against an entry price that arrives one bar later. On gap bars this
    produces stops on the wrong side of the entry (long stop >= entry).

    Correct pattern: strategy omits `stop_price`/`tp_price` and lets the
    engine fallback compute them from the actual fill price using the
    directive's ATR multiplier.

Mode resolution (explicit precedence):
    1. directive field  `test.stop_contract_guard: warn|block`  (authoritative)
    2. env var          STOP_CONTRACT_GUARD_BLOCK=1 → block
    3. default          warn

    WARN prints a banner and continues. BLOCK raises RuntimeError.

Audit:
    Every invocation — PASS, WARN, or BLOCK — appends a JSONL row to
    `governance/stop_contract_audit.jsonl` and prints a machine-readable
    stdout line of the form:

        [STOP_CONTRACT_RISK] directive=<id> strategy=<id> risk=0|1 mode=warn|block

    This allows post-hoc queries like "which strategies still carry risk?"
    without re-parsing the banner text.

Invocation:
    tools/orchestration/stage_preflight.py calls check_stop_contract()
    right after check_semantic_coverage() when the directive is admitted.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import parse_directive


_VIOLATION_KEYS = ("stop_price", "tp_price")
_VALID_MODES = ("warn", "block")
_AUDIT_PATH = PROJECT_ROOT / "governance" / "stop_contract_audit.jsonl"


def _resolve_mode(parsed: dict) -> str:
    """
    Resolve guard mode with explicit precedence:

        1. directive field  test.stop_contract_guard  (authoritative, audit-visible)
        2. env var          STOP_CONTRACT_GUARD_BLOCK=1 → 'block'
        3. default          'warn'

    Invalid directive values fall back to the env/default chain with a warning.
    """
    test_block = parsed.get("test") or {}
    if isinstance(test_block, dict):
        raw = test_block.get("stop_contract_guard")
        if raw is not None:
            mode = str(raw).strip().lower()
            if mode in _VALID_MODES:
                return mode
            print(
                f"[STOP_CONTRACT_GUARD] WARNING: invalid directive value "
                f"test.stop_contract_guard={raw!r}; falling back to env/default."
            )

    if os.environ.get("STOP_CONTRACT_GUARD_BLOCK") == "1":
        return "block"
    return "warn"


def _emit_audit(record: dict) -> None:
    """Append one JSONL row to governance/stop_contract_audit.jsonl (best-effort)."""
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as e:
        print(f"[STOP_CONTRACT_GUARD] WARNING: audit write failed: {e}")


def _directive_uses_next_bar_open(parsed: dict) -> bool:
    """True if the directive declares next_bar_open execution timing."""
    op = parsed.get("order_placement") or {}
    if isinstance(op, dict) and str(op.get("execution_timing", "")).lower() == "next_bar_open":
        return True
    # Also check nested execution_rules.order_placement (signature shape)
    exr = parsed.get("execution_rules") or {}
    if isinstance(exr, dict):
        inner = exr.get("order_placement") or {}
        if isinstance(inner, dict) and str(inner.get("execution_timing", "")).lower() == "next_bar_open":
            return True
    return False


def _strategy_returns_stop_or_tp(strategy_path: str) -> set[str]:
    """
    Return the subset of {'stop_price','tp_price'} that appear as string keys
    in a Dict literal inside the `check_entry` method's Return statements.

    Conservative: only inspects `check_entry` (not helper methods). Missing or
    syntactically unparseable strategy.py → empty set (no false positives).
    """
    try:
        source = Path(strategy_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return set()

    offenders: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "check_entry":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Return) or not isinstance(sub.value, ast.Dict):
                continue
            for key in sub.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if key.value in _VIOLATION_KEYS:
                        offenders.add(key.value)
    return offenders


def check_stop_contract(directive_path: str, strategy_path: str) -> bool:
    """
    Pre-admission guard.

    Returns:
        True  — no violation (either not applicable or contract is clean).
        False — violation detected in WARN mode (pipeline continues).

    Raises:
        RuntimeError("STOP_CONTRACT_VIOLATION: ...") when resolved mode is
        'block' and a violation is detected.

    Side effects (always, regardless of outcome):
        - Prints a machine-readable stdout line:
              [STOP_CONTRACT_RISK] directive=<id> strategy=<id> risk=0|1 mode=<mode>
        - Appends one JSONL row to governance/stop_contract_audit.jsonl.
    """
    parsed = parse_directive(Path(directive_path))
    mode = _resolve_mode(parsed)
    directive_id = Path(directive_path).stem
    strategy_id = Path(strategy_path).parent.name

    applicable = _directive_uses_next_bar_open(parsed)
    offenders: set[str] = (
        _strategy_returns_stop_or_tp(strategy_path) if applicable else set()
    )
    risk = 1 if offenders else 0

    # Machine-readable flag — single stable line, easy to grep from run logs.
    print(
        f"[STOP_CONTRACT_RISK] directive={directive_id} strategy={strategy_id} "
        f"risk={risk} mode={mode}"
    )

    # Persistent JSONL audit row (append-only).
    _emit_audit({
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "directive": directive_id,
        "strategy": strategy_id,
        "execution_timing_next_bar_open": applicable,
        "offenders": sorted(offenders),
        "risk": risk,
        "mode": mode,
    })

    if risk == 0:
        return True

    banner = [
        "",
        "=" * 66,
        "[STOP_CONTRACT_GUARD] SIGNAL-BAR vs NEXT-BAR-OPEN MISMATCH",
        "=" * 66,
        f"  Directive        : {Path(directive_path).name}",
        f"  Strategy         : {strategy_id}",
        f"  execution_timing : next_bar_open",
        f"  Offending keys   : {', '.join(sorted(offenders))}",
        f"  Mode             : {mode.upper()}",
        "",
        "  The strategy computes stop/tp against the signal-bar close, but the",
        "  engine fills the entry one bar later at next_bar_open. On gap bars",
        "  this produces stops on the wrong side of entry price and trips",
        "  STOP CONTRACT VIOLATION at Stage-1.",
        "",
        "  FIX: remove 'stop_price' and 'tp_price' from the check_entry return",
        "       dict. Let the engine compute SL/TP from the actual fill price",
        "       using the directive's ATR multiplier fallback.",
        "=" * 66,
        "",
    ]
    for line in banner:
        print(line)

    if mode == "block":
        raise RuntimeError(
            f"STOP_CONTRACT_VIOLATION: strategy returns {sorted(offenders)} "
            f"under next_bar_open execution (mode=block)."
        )
    return False
