"""
tools/diagnostics — The Diagnostic Contract (Phase 1)

A single structured object that every gate speaks when it blocks, so a failure
communicates not just *that* it happened, but *why*, *why it surfaced here*,
*how to fix it*, and *what to do next* — and so failures become queryable
analytics (`GROUP BY category`) instead of log-text mining.

Design philosophy (operator-confirmed):

    Diagnostic            <- THE canonical contract object (payload)
          |
          +-- render()        ......... single human-facing output path
          +-- wrapped by GateError ... transport for gates w/o a domain exception
          +-- carried by CanonicalizationError / PipelineAdmissionPause / ...

The **Diagnostic is the contract**; exceptions merely *transport* it. A gate
supplies ONLY `code` + `context`; everything else (category, error, cause,
why_now, source, remedy, next_action, auto_fixable, severity, doc_ref) lives in
ONE catalog (`governance/diagnostics/catalog.yaml`), keyed by the namespaced
`code`. Gates contain no explanatory prose.

Full design: outputs/system_reports/04_governance_and_guardrails/
DIAGNOSTIC_CONTRACT_PROPOSAL_2026-06-30.md
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "Category",
    "NextAction",
    "Severity",
    "Diagnostic",
    "GateError",
    "UnknownDiagnosticCode",
    "render",
    "load_catalog",
    "validate_catalog",
    "catalog_path",
    "REQUIRED_CATALOG_FIELDS",
]


# ---------------------------------------------------------------------------
# Closed vocabularies (the contract's enums)
# ---------------------------------------------------------------------------
class Category(str, enum.Enum):
    IDENTITY = "IDENTITY"
    NAMESPACE = "NAMESPACE"
    SCHEMA = "SCHEMA"
    ENGINE = "ENGINE"
    EXECUTION = "EXECUTION"
    DATA = "DATA"
    GOVERNANCE = "GOVERNANCE"
    FSM = "FSM"


class NextAction(str, enum.Enum):
    STOP_AND_REQUEST_APPROVAL = "stop_and_request_approval"
    RETRY_AFTER_AUTOFIX = "retry_after_autofix"
    CONTINUE = "continue"
    ABORT_DIRECTIVE = "abort_directive"


class Severity(str, enum.Enum):
    ERROR = "error"
    WARN = "warn"


_VALID_CATEGORIES = {c.value for c in Category}
_VALID_NEXT_ACTIONS = {n.value for n in NextAction}
_VALID_SEVERITIES = {s.value for s in Severity}

# Fields a catalog entry MUST define, non-empty (auto_fixable must be a bool).
# `next_action_note` is intentionally optional.
REQUIRED_CATALOG_FIELDS = (
    "category",
    "error",
    "cause",
    "why_now",
    "source",
    "remedy",
    "next_action",
    "auto_fixable",
    "severity",
    "doc_ref",
)


class UnknownDiagnosticCode(KeyError):
    """Raised when a Diagnostic code is not registered in the catalog."""


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def catalog_path() -> Path:
    """Path to the catalog in the LOCAL tree.

    Resolved relative to this file (NOT REAL_REPO_ROOT) so that, in a worktree,
    the gate validates the worktree's own catalog — the same fail-closed posture
    the path/encoding lint gates use for in-tree governance data.
    """
    return Path(__file__).resolve().parents[2] / "governance" / "diagnostics" / "catalog.yaml"


def load_catalog(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Read and parse the diagnostic catalog. No caching — only read on failure
    paths, never a hot loop, so re-reading is free and avoids stale-cache bugs."""
    p = Path(path) if path is not None else catalog_path()
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Diagnostic catalog must be a mapping: {p}")
    return data


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems with the catalog (empty == valid).

    Collects ALL problems rather than failing fast, so CI reports every issue at
    once. Enforces: required fields present + non-empty, valid category /
    next_action / severity, auto_fixable is a bool, and the namespaced-code
    convention (`<subsystem>.<CODE>`).
    """
    errors: list[str] = []
    for code, entry in catalog.items():
        if not isinstance(entry, dict):
            errors.append(f"{code}: entry is not a mapping")
            continue
        if "." not in str(code):
            errors.append(f"{code}: code must be namespaced as '<subsystem>.<CODE>'")
        for fname in REQUIRED_CATALOG_FIELDS:
            if fname not in entry:
                errors.append(f"{code}: missing required field '{fname}'")
                continue
            val = entry[fname]
            if fname == "auto_fixable":
                if not isinstance(val, bool):
                    errors.append(
                        f"{code}: auto_fixable must be a bool, got {type(val).__name__}"
                    )
            elif val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"{code}: field '{fname}' is empty")
        cat = entry.get("category")
        if cat not in _VALID_CATEGORIES:
            errors.append(f"{code}: invalid category {cat!r} (valid: {sorted(_VALID_CATEGORIES)})")
        na = entry.get("next_action")
        if na not in _VALID_NEXT_ACTIONS:
            errors.append(
                f"{code}: invalid next_action {na!r} (valid: {sorted(_VALID_NEXT_ACTIONS)})"
            )
        sev = entry.get("severity")
        if sev not in _VALID_SEVERITIES:
            errors.append(f"{code}: invalid severity {sev!r} (valid: {sorted(_VALID_SEVERITIES)})")
    return errors


# ---------------------------------------------------------------------------
# Safe templating  (catalog prose may reference {context} keys)
# ---------------------------------------------------------------------------
class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # leave unknown placeholders visible
        return "{" + key + "}"


def _safe_format(template: Any, context: dict[str, Any]) -> Any:
    if not isinstance(template, str) or "{" not in template:
        return template
    try:
        return template.format_map(_SafeDict(context or {}))
    except Exception:
        # A malformed template must never crash a gate's failure path.
        return template


# ---------------------------------------------------------------------------
# The contract object
# ---------------------------------------------------------------------------
@dataclass
class Diagnostic:
    """The canonical diagnostic payload.

    Gate usage (the ONLY prose-free path):
        Diagnostic(code="canonicalizer.UNKNOWN_NESTED_KEY",
                   context={"block_name": ..., "unknown": [...]})

    When only `code` (+`context`) is supplied, the catalog fields are resolved
    and templated against `context` on construction. Passing `category`
    explicitly bypasses catalog resolution (used by unit tests to exercise the
    renderer in isolation).
    """

    code: str
    context: dict[str, Any] = field(default_factory=dict)
    # Catalog-resolved fields (None => resolve from catalog in __post_init__):
    category: str | None = None
    error: str | None = None
    cause: str | None = None
    why_now: str | None = None
    source: str | None = None
    remedy: str | None = None
    next_action: str | None = None
    auto_fixable: bool | None = None
    severity: str | None = None
    doc_ref: str | None = None
    next_action_note: str | None = None

    def __post_init__(self) -> None:
        if self.category is None:  # gate-mode: fill prose/metadata from the catalog
            self._resolve_from_catalog()
        self._validate()

    def _resolve_from_catalog(self) -> None:
        catalog = load_catalog()
        if self.code not in catalog:
            raise UnknownDiagnosticCode(
                f"Diagnostic code {self.code!r} is not registered in {catalog_path()}"
            )
        entry = catalog[self.code]
        ctx = self.context or {}
        self.category = entry.get("category")
        self.error = _safe_format(entry.get("error", ""), ctx)
        self.cause = _safe_format(entry.get("cause", ""), ctx)
        self.why_now = _safe_format(entry.get("why_now", ""), ctx)
        self.source = _safe_format(entry.get("source", ""), ctx)
        self.remedy = _safe_format(entry.get("remedy", ""), ctx)
        self.next_action = entry.get("next_action")
        self.auto_fixable = entry.get("auto_fixable")
        self.severity = entry.get("severity")
        self.doc_ref = entry.get("doc_ref")
        note = entry.get("next_action_note")
        self.next_action_note = _safe_format(note, ctx) if note else None

    def _validate(self) -> None:
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"Diagnostic {self.code}: invalid category {self.category!r}"
            )
        if self.next_action not in _VALID_NEXT_ACTIONS:
            raise ValueError(
                f"Diagnostic {self.code}: invalid next_action {self.next_action!r}"
            )
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Diagnostic {self.code}: invalid severity {self.severity!r}"
            )


# ---------------------------------------------------------------------------
# Transport (one of several; the Diagnostic is the contract, this just carries it)
# ---------------------------------------------------------------------------
class GateError(Exception):
    """Generic transport for a Diagnostic raised by a gate that has no domain
    exception of its own. The Diagnostic is the contract; this exception merely
    carries it and renders through the single output path.

    Gates that DO have a domain exception (e.g. CanonicalizationError) or a
    control-flow exception (e.g. PipelineAdmissionPause) attach the Diagnostic to
    that exception instead of replacing it — keeping the contract independent of
    exception type.
    """

    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(render(diagnostic))


# ---------------------------------------------------------------------------
# Renderer — the single human-facing output path
# ---------------------------------------------------------------------------
_LABEL_WIDTH = 11  # widest label is "NEXT ACTION"
_VALUE_INDENT = " " * (_LABEL_WIDTH + 3)  # continuation lines align under the value
# ASCII markers, NOT emoji: render() output is print()ed to the Windows cp1252
# console; a non-ASCII glyph would raise UnicodeEncodeError and crash the gate
# (a decision change). The value is in the structure, not the icon.
_SEVERITY_ICON = {"error": "[X]", "warn": "[!]"}


def _humanize_next_action(value: str | None) -> str:
    if not value:
        return str(value)
    return value.replace("_", "-").capitalize()


def _emit(lines: list[str], label: str, value: Any) -> None:
    text = "" if value is None else str(value)
    parts = text.split("\n")
    lines.append(f"{label.ljust(_LABEL_WIDTH)} : {parts[0]}")
    for cont in parts[1:]:
        lines.append(f"{_VALUE_INDENT}{cont}")


def render(diag: Diagnostic) -> str:
    """Render a Diagnostic to the boxed, label-aligned block (ASCII, console-safe)."""
    icon = _SEVERITY_ICON.get(diag.severity or "error", "[X]")
    lines: list[str] = [
        f"{icon} {diag.code}   [category: {diag.category}] [severity: {diag.severity}]"
    ]
    _emit(lines, "ERROR", diag.error)
    _emit(lines, "CAUSE", diag.cause)
    _emit(lines, "WHY NOW", diag.why_now)
    _emit(lines, "SOURCE", diag.source)
    _emit(lines, "REMEDY", diag.remedy)
    next_action = _humanize_next_action(diag.next_action)
    if diag.next_action_note:
        next_action = f"{next_action}   ({diag.next_action_note})"
    _emit(lines, "NEXT ACTION", next_action)
    _emit(lines, "AUTO-FIX", "Yes" if diag.auto_fixable else "No")
    _emit(lines, "DOC_REF", diag.doc_ref)
    return "\n".join(lines)
