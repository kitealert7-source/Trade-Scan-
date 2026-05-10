"""
event_log.py — Append-only governance event log for durable state changes.

One log for every write that mutates authoritative state:
    - run_registry.json mutations (status / directive_hash / tier changes)
    - portfolio.yaml writes (promote, disable, lifecycle transitions)
    - directive_state.json transitions (FSM state changes)
    - destructive reconciler actions (purge, quarantine, invalidate)

Why: before this module, post-hoc forensics required tailing stdout across
multiple tools and cross-referencing filesystem mtimes. The FAKEBREAK P01/P02
incident (2026-04-09) was diagnosable only because reset_audit_log.csv
happened to capture one leg of the failure chain. This generalizes that
pattern so every durable write is recoverable from a single file.

Design:
    - Append-only JSONL at governance/events.jsonl.
    - One line per event, UTC ISO timestamp, structured fields.
    - Logging failures NEVER crash the caller (observational layer must not
      degrade availability of the system it observes).
    - No read API here — grep / jq / pandas is the consumer.

Usage:
    from tools.event_log import log_event
    log_event(
        action="REGISTRY_UPSERT",
        target="run_id:abc123",
        actor="log_run_to_registry",
        before={"status": "sandbox"},
        after={"status": "complete", "directive_hash": "..."},
        reason="pipeline complete",
    )
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENTS_LOG_PATH = PROJECT_ROOT / "governance" / "events.jsonl"


def log_event(
    action: str,
    target: str,
    *,
    actor: str | None = None,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    """Append one event to governance/events.jsonl.

    Args:
        action: Uppercase verb describing the mutation.
            Canonical values:
              REGISTRY_UPSERT, REGISTRY_STATUS_CHANGE, REGISTRY_DIRECTIVE_HEAL
              PORTFOLIO_YAML_ADD, PORTFOLIO_YAML_REMOVE
              DIRECTIVE_STATE_TRANSITION
              DIRECTIVE_PURGE, RUN_QUARANTINE, RUN_INVALIDATE
              INVARIANT_VIOLATION, INVARIANT_HEAL
              TRANSACTION_START, TRANSACTION_COMMIT, TRANSACTION_FAILED
        target: What was mutated — typically "run_id:<id>", "directive:<id>",
            or "portfolio_yaml:<strategy_id>". Free-form, indexable by grep.
        actor: Function / script that performed the mutation. Inferred from
            the call site if None.
        before: Snapshot of the relevant fields before mutation. Omit if
            inapplicable (e.g. pure additions).
        after: Snapshot after mutation. Omit if inapplicable (e.g. deletions).
        reason: Short human-readable reason — especially important for
            destructive actions (PURGE, INVALIDATE, QUARANTINE).
        **extra: Any additional context fields, flattened into the record.

    Never raises. Failure to write the event log (disk full, permission
    error, ...) prints to stderr but does not propagate — the system it
    observes must remain available.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
    }
    if actor is not None:
        record["actor"] = actor
    if before is not None:
        record["before"] = before
    if after is not None:
        record["after"] = after
    if reason is not None:
        record["reason"] = reason
    if extra:
        # Avoid clobbering canonical keys with extra kwargs.
        for k, v in extra.items():
            if k not in record:
                record[k] = v

    try:
        EVENTS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
        # Append in text mode; OS append is atomic for lines under PIPE_BUF on
        # POSIX, and on Windows we accept the small multi-writer risk because
        # event_log is not in the critical path.
        with open(EVENTS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:  # pragma: no cover — observational layer
        # Never propagate — failure here must not block the write it observes.
        sys.stderr.write(
            f"[event_log] WARNING: failed to append event "
            f"(action={action!r}, target={target!r}): {exc}\n"
        )
