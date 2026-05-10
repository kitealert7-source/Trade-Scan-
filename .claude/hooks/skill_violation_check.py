#!/usr/bin/env python3
"""
Skill violation check -- closes the loop when a hard intent fires but
the agent never invokes (or invokes the wrong) `/skill`.

Events:

  PreToolUse  (all tools)
    - tool_name == "Skill"
        match  -> skill_satisfied
        mismatch -> wrong_skill_used  + [ROUTING ERROR] inline
    - otherwise (tool fires while pending):
        grace window -> silent:
          * SAFE_READONLY tools (Read/Glob/Grep/...) count but don't warn
          * up to 2 non-mutating tools allowed before the warning
        breach -> single [ENFORCEMENT WARNING], escalates to
          [LIKELY VIOLATION] if a mutating tool ran AND >=2 tools ran.

  Stop  (agent turn ends)
    - Any still-pending expectation -> hard_violation event logged.

Hook never raises; always exits 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECT_PATH = REPO_ROOT / ".claude" / "state" / "pending_skill_expectations.json"
VIOLATION_LOG = REPO_ROOT / ".claude" / "logs" / "violations.jsonl"

# Tiered tool classification for the grace window:
SAFE_READONLY = {
    "Read", "Glob", "Grep", "ToolSearch", "WebFetch", "WebSearch",
    "NotebookRead", "BashOutput", "Monitor", "LS", "TaskOutput",
}
MUTATING = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
GRACE_TOOL_LIMIT = 2   # up to 2 non-mutating tools before we warn


def _log(record: dict) -> None:
    try:
        VIOLATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with VIOLATION_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_state() -> dict:
    try:
        if EXPECT_PATH.exists():
            return json.loads(EXPECT_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"turn_ts": None, "expectations": []}


def _write_state(state: dict) -> None:
    try:
        EXPECT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPECT_PATH.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def _pending(state: dict) -> list[dict]:
    return [e for e in state.get("expectations", [])
            if e.get("status") == "pending"]


def _handle_pretooluse(payload: dict) -> str:
    state = _read_state()
    pending = _pending(state)
    if not pending:
        return ""

    tool = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or payload.get("input") or {}

    # -- Skill tool: either satisfies or is the wrong skill --
    if tool == "Skill":
        invoked = str(tool_input.get("skill") or "").strip()
        satisfied = False
        for exp in state["expectations"]:
            if exp.get("status") == "pending" and exp.get("must_skill") == invoked:
                exp["status"] = "satisfied"
                exp["satisfied_ts"] = _dt.datetime.utcnow().isoformat() + "Z"
                satisfied = True
                _log({
                    "ts": exp["satisfied_ts"],
                    "event": "skill_satisfied",
                    "intent_id": exp.get("intent_id"),
                    "must_skill": exp.get("must_skill"),
                    "tools_before_skill": exp.get("tools_before_skill", 0),
                    "mutating_before_skill": exp.get("mutating_before_skill", 0),
                })
        _write_state(state)
        if satisfied:
            return ""
        # Wrong skill invoked while an expectation was pending.
        expected = [e.get("must_skill") for e in pending]
        _log({
            "ts": _dt.datetime.utcnow().isoformat() + "Z",
            "event": "wrong_skill_used",
            "invoked_skill": invoked,
            "expected_skills": expected,
            "pending_intents": [e.get("intent_id") for e in pending],
        })
        return (
            f"\n[ROUTING ERROR] Expected `/{expected[0]}` (intent "
            f"`{pending[0].get('intent_id')}`), got `/{invoked}`. "
            f"The wrong skill was invoked -- rollback and call the "
            f"correct one.\n"
        )

    # -- Non-skill tool: apply grace window --
    is_mutating = tool in MUTATING
    is_readonly = tool in SAFE_READONLY

    first_mutate = False
    fresh_breach = False
    likely_violation = False

    for exp in state["expectations"]:
        if exp.get("status") != "pending":
            continue
        mut = int(exp.get("mutating_before_skill", 0))
        total = int(exp.get("tools_before_skill", 0))
        if is_mutating and mut == 0:
            first_mutate = True
        if is_mutating:
            mut += 1
        total += 1
        exp["mutating_before_skill"] = mut
        exp["tools_before_skill"] = total

        breach = is_mutating or (total > GRACE_TOOL_LIMIT)
        if breach and not exp.get("warned"):
            fresh_breach = True
            exp["warned"] = True
        if mut >= 1 and total >= 2:
            likely_violation = True

    _write_state(state)

    _log({
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "event": "tool_before_skill",
        "tool": tool,
        "mutating": is_mutating,
        "readonly_tier": is_readonly,
        "first_mutate": first_mutate,
        "pending": [{"intent_id": e.get("intent_id"),
                     "must_skill": e.get("must_skill"),
                     "tools_before_skill": e.get("tools_before_skill"),
                     "mutating_before_skill": e.get("mutating_before_skill")}
                    for e in _pending(state)],
    })

    if not fresh_breach:
        return ""

    skills = ", ".join(f"/{e.get('must_skill')}" for e in _pending(state))
    if likely_violation:
        return (
            f"\n[LIKELY VIOLATION] A mutating tool (`{tool}`) ran before "
            f"the required skill ({skills}). Stop, invoke the skill, "
            f"and let it drive the mutation. Continuing without it will "
            f"log a hard violation at turn end.\n"
        )
    return (
        f"\n[ENFORCEMENT WARNING] `/{_pending(state)[0].get('must_skill')}` "
        f"is still pending. You've exceeded the grace window "
        f"(>{GRACE_TOOL_LIMIT} tools or mutating tool fired) -- invoke "
        f"the skill before continuing.\n"
    )


def _handle_stop(payload: dict) -> str:
    state = _read_state()
    pending = _pending(state)
    out = ""
    if pending:
        for exp in pending:
            _log({
                "ts": _dt.datetime.utcnow().isoformat() + "Z",
                "event": "hard_violation",
                "intent_id": exp.get("intent_id"),
                "must_skill": exp.get("must_skill"),
                "tools_before_skill": exp.get("tools_before_skill", 0),
                "mutating_before_skill": exp.get("mutating_before_skill", 0),
                "turn_ts": state.get("turn_ts"),
            })
        skills = ", ".join(f"/{e.get('must_skill')}" for e in pending)
        out = (
            f"\n[HARD ENFORCEMENT VIOLATION -- LOGGED] Turn ended without "
            f"invoking required skill(s): {skills}. Review "
            f".claude/logs/violations.jsonl.\n"
        )
    _write_state({"turn_ts": state.get("turn_ts"), "expectations": []})
    return out


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    event = (payload.get("hook_event_name")
             or payload.get("event")
             or ("PreToolUse" if payload.get("tool_name") else "Stop"))

    try:
        if event == "Stop":
            out = _handle_stop(payload)
        else:
            out = _handle_pretooluse(payload)
    except Exception:
        return 0

    if out:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
