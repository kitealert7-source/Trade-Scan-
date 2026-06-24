#!/usr/bin/env python3
"""
PostToolUse hook -- after Write/Edit to sensitive paths, emit a reminder
steering the agent to the follow-up workflow (vault push, manifest
regen, registry refresh, etc.).

Coverage (highest-risk first):
  engine_dev/**                  -> update-vault + engine_registry refresh
  config/engine_registry.json    -> manifest regen + verify_engine_integrity
  config/*.yaml|*.json           -> manifest / guard refresh
  governance/namespace/**        -> sweep_registry_gate + namespace_gate
  governance/preflight.py        -> system_preflight smoke
  tools/** (guarded + drifted)   -> regen tools_manifest (check_guard_drift)
  strategies/**/portfolio.yaml   -> portfolio_evaluator revalidation
  strategies/Master_Portfolio_Sheet.xlsx -> append-only ledger warning

Reads stdin JSON per hook contract:
  { "tool_name": "Write"|"Edit"|"MultiEdit",
    "tool_input": {"file_path": "...", ...}, ... }

Writes reminder text to stdout. Always exits 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path


TRIGGER_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = REPO_ROOT / ".claude" / "logs" / "post_write.jsonl"
STATE_PATH = REPO_ROOT / ".claude" / "state" / "last_intent.json"


def _log(record: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _file_category(rel: str) -> str:
    r = rel.replace("\\", "/").lower()
    if r.startswith("engine_dev/"):                return "engine"
    if r == "config/engine_registry.json":         return "engine"
    if r.startswith("governance/namespace/"):      return "governance"
    if r == "governance/preflight.py":             return "governance"
    if r.startswith("tools/"):                     return "tools"
    if r.endswith("portfolio.yaml"):               return "portfolio"
    if r.endswith(("master_portfolio_sheet.xlsx",
                   "strategy_master_filter.xlsx")):return "ledger"
    if r.startswith("strategies/"):                return "strategy"
    if r.startswith("config/"):                    return "config"
    if r.startswith(("engines/", "execution_engine/", "indicators/")):
        return "core_logic"
    return "other"


def _read_last_intent() -> dict | None:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None

# Silent-logic-mutation guard: edits to core logic files that look
# harmless but can drift invariants without triggering the path-
# specific rules above.
_CORE_LOGIC_RE = re.compile(
    r"(^|/)(strategies/|engines/|engine_dev/|execution_engine/|"
    r"indicators/|risk/|capital|portfolio_evaluator|stage[_-]?[0-9]+"
    r"|check_entry|execution_loop|filter_stack|regime).*\.py$",
    re.IGNORECASE,
)


def _guard_drift_reminder(rel: str) -> str | None:
    """Precise, drift-confirmed warning for a guarded-tool edit.

    Replaces the old unconditional "tools/ modified -> regen" banner, which
    fired on EVERY tools/ file (guarded or not, drifted or not) and so was easy
    to ignore -- the 3x-recurring manifest miss on 2026-06-24. Returns a
    file-specific message ONLY when the edited tool is guarded AND its on-disk
    hash now differs from tools_manifest.json; otherwise None (quiet -- a
    non-guarded or already-in-sync tools/ edit needs no manifest action).

    Delegates to tools.check_guard_drift.find_drift, which is deliberately
    dependency-light (no pandas) so it is cheap enough to run on every
    guarded-tool edit. Any import / runtime hiccup -> None: a hook must never
    fail the edit it follows.
    """
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from tools.check_guard_drift import find_drift

        drifted = {
            d["file"].replace("\\", "/").lower()
            for d in find_drift(project_root=REPO_ROOT)
            if d["status"] == "DRIFT"
        }
    except Exception:
        return None
    if not drifted:
        return None

    key = rel.replace("\\", "/").lower()
    if key.startswith("tools/"):
        key = key[len("tools/"):]
    if key not in drifted:
        return None  # tools/ file edited, but unguarded or already in sync

    others = len(drifted) - 1
    extra = (
        f"\n  ({others} other guarded tool(s) also drift -- "
        "`python tools/check_guard_drift.py` lists them.)"
        if others > 0
        else ""
    )
    return (
        "[GUARD DRIFT -- guarded tool edited, tools_manifest.json now stale]\n"
        f"  tools/{key} no longer matches its recorded hash.\n"
        "  The next pipeline run WILL hard-fail at startup until you regen:\n"
        "    python tools/generate_guard_manifest.py\n"
        "    git add tools/tools_manifest.json\n"
        f"  Verify clean: python tools/check_guard_drift.py{extra}\n"
    )


def _reminder_for(rel: str) -> str | None:
    r = rel.replace("\\", "/").lower()

    if r.startswith("engine_dev/"):
        return (
            "[POST-WRITE REMINDER -- engine_dev/ modified]\n"
            "If this is an engine build, bump, or promote:\n"
            "  1. Invoke `/update-vault` to push the engine + snapshot.\n"
            "  2. Update config/engine_registry.json (status, version, hash).\n"
            "  3. Run `python tools/verify_engine_integrity.py`.\n"
            "Skipping these left v1.5.6 unvaulted for days -- do not repeat.\n"
        )

    if r == "config/engine_registry.json":
        return (
            "[POST-WRITE REMINDER -- engine_registry.json modified]\n"
            "Required follow-ups:\n"
            "  1. `python tools/verify_engine_integrity.py`\n"
            "  2. Confirm canonical pointer + FROZEN flag are still correct.\n"
            "  3. If a new version was added, invoke `/update-vault`.\n"
        )

    if r.startswith("config/") and (r.endswith(".yaml") or r.endswith(".json")):
        return (
            "[POST-WRITE REMINDER -- config/ modified]\n"
            "Run `python tools/system_preflight.py` before the next pipeline call.\n"
        )

    if r.startswith("governance/namespace/"):
        return (
            "[POST-WRITE REMINDER -- governance/namespace/ modified]\n"
            "Required follow-ups before directive admission:\n"
            "  1. `python tools/sweep_registry_gate.py <any active directive>`\n"
            "  2. `python tools/namespace_gate.py <any active directive>`\n"
            "  3. If sweep_registry.yaml hashes changed, use "
            "`python tools/new_pass.py --rehash <NAME>` -- never hand-edit.\n"
        )

    if r == "governance/preflight.py":
        return (
            "[POST-WRITE REMINDER -- governance/preflight.py modified]\n"
            "This file is protected infrastructure. Required:\n"
            "  1. `python tools/system_preflight.py` (smoke).\n"
            "  2. Dry-run one directive through Stage-0 before shipping.\n"
        )

    if r.startswith("tools/"):
        # Drift-aware (was: unconditional regen banner on every tools/ edit).
        # Only a guarded tool that ACTUALLY drifts raises a signal now.
        return _guard_drift_reminder(rel)

    if r.endswith("/portfolio.yaml") or r.endswith("portfolio.yaml"):
        return (
            "[POST-WRITE REMINDER -- portfolio.yaml modified]\n"
            "Revalidate via `python tools/portfolio_evaluator.py <RUN_ID>` "
            "for the affected strategy. Do NOT hand-edit the Master Portfolio Sheet.\n"
        )

    if r.endswith("master_portfolio_sheet.xlsx") or r.endswith("strategy_master_filter.xlsx"):
        return (
            "[POST-WRITE REMINDER -- append-only ledger touched]\n"
            "WARNING: these ledgers are append-only. If rows were deleted/overwritten, "
            "restore from git immediately and use the proper reset workflow "
            "(`python tools/reset_directive.py <ID>`).\n"
        )

    if _CORE_LOGIC_RE.search(r):
        return (
            "[POST-WRITE REMINDER -- core logic modified]\n"
            "File touches strategy / execution / risk / capital / indicator logic.\n"
            "Verify before shipping:\n"
            "  1. Backtest re-run on an affected directive.\n"
            "  2. No invariant drift (regime, capital, fill model).\n"
            "  3. check_entry() replay test if signal logic changed.\n"
            "  4. Results artifacts updated (Master Filter, MPS).\n"
            "Silent logic mutation is the single highest-risk edit class.\n"
        )

    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool not in TRIGGER_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or payload.get("input") or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
        or ""
    )
    if not file_path:
        return 0

    # Normalize to repo-relative
    repo_root = Path(__file__).resolve().parents[2]
    try:
        rel = str(Path(file_path).resolve().relative_to(repo_root))
    except Exception:
        rel = str(file_path)

    msg = _reminder_for(rel)
    category = _file_category(rel)
    last_intent = _read_last_intent() or {}
    expected_cat = last_intent.get("expected_file_category")
    last_id = last_intent.get("intent_id")

    misclassified = bool(
        last_id and expected_cat
        and category not in ("other",)
        and category != expected_cat
    )

    _log({
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "tool": tool,
        "file_rel": rel,
        "file_category": category,
        "reminder_fired": bool(msg),
        "last_intent_id": last_id,
        "last_intent_expected_cat": expected_cat,
        "misclassified": misclassified,
    })

    if msg:
        sys.stdout.write(msg)
    if misclassified:
        sys.stdout.write(
            f"\n[MISCLASSIFICATION FLAG] Prior prompt routed to "
            f"`{last_id}` (expected category `{expected_cat}`) but this "
            f"write targets category `{category}`. Possible wrong-intent "
            f"routing -- review before continuing.\n"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
