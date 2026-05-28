"""Directive -> recycle_rule.name binding gate (admission-time).

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task A.
Phase A1: warn-only on unknown patterns; mismatch + ambiguity hard reject.
Phase A2 (later commit): flip governance/namespace/directive_rule_binding.yaml
meta.strict_unknown to true.

Comparison semantics:
  - rule_name equality is EXACT, case-sensitive. No silent lowercase.
  - Ambiguity (>1 pattern match) is a registry-hygiene failure, not a
    precedence question. Reject with both patterns named.
  - Directives without recycle_rule.name (non-basket) are out of scope —
    gate is a no-op.

Telemetry: every WARN appends a JSONL line to
  outputs/system_reports/namespace/unknown_rule_bindings_<YYYY-MM-DD>.jsonl
with directive_path, directive_name, observed_rule_name, candidate_fragment,
match_class ('unknown' or 'legacy'), and timestamp_utc.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from config.path_authority import REAL_REPO_ROOT

REGISTRY_PATH = REAL_REPO_ROOT / "governance" / "namespace" / "directive_rule_binding.yaml"
TELEMETRY_DIR = REAL_REPO_ROOT / "outputs" / "system_reports" / "namespace"

TF_TOKENS = ("5M", "15M", "30M", "1H", "4H", "1D")


class RuleBindingGateError(Exception):
    """Raised when admission must be rejected by the rule-binding gate."""


@dataclass(frozen=True)
class _BindingMatch:
    pattern: str
    rule_name: str | None  # None for legacy_patterns
    section: str           # 'bindings' or 'legacy_patterns'


def _extract_candidate_fragment(directive_id: str) -> str | None:
    """Return substring after a TF token, stripped of the trailing __E suffix."""
    head = directive_id.split("__E", 1)[0]
    for tf in TF_TOKENS:
        marker = f"_{tf}_"
        idx = head.find(marker)
        if idx != -1:
            return head[idx + len(marker):]
    return None


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise RuleBindingGateError(
            f"directive_rule_binding registry missing at {REGISTRY_PATH}"
        )
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def _find_matches(directive_id: str, registry: dict) -> list[_BindingMatch]:
    matches: list[_BindingMatch] = []
    for entry in (registry.get("bindings") or []):
        if re.search(entry["pattern"], directive_id):
            matches.append(
                _BindingMatch(
                    pattern=entry["pattern"],
                    rule_name=entry["rule_name"],
                    section="bindings",
                )
            )
    for entry in (registry.get("legacy_patterns") or []):
        if re.search(entry["pattern"], directive_id):
            matches.append(
                _BindingMatch(
                    pattern=entry["pattern"],
                    rule_name=None,
                    section="legacy_patterns",
                )
            )
    return matches


def _load_directive_rule_name(directive_path: Path) -> str | None:
    data = yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}
    rr = data.get("recycle_rule") or {}
    name = rr.get("name")
    return name.strip() if isinstance(name, str) else None


def _emit_telemetry(
    *,
    directive_path: Path,
    observed_rule_name: str | None,
    candidate_fragment: str | None,
    match_class: str,
) -> None:
    now = datetime.now(timezone.utc)
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    out = TELEMETRY_DIR / f"unknown_rule_bindings_{now.strftime('%Y-%m-%d')}.jsonl"
    payload = {
        "timestamp_utc": now.isoformat(),
        "directive_path": str(directive_path),
        "directive_name": directive_path.stem,
        "observed_rule_name": observed_rule_name,
        "candidate_fragment": candidate_fragment,
        "match_class": match_class,
    }
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def check_directive_rule_binding(directive_path: Path) -> None:
    """Gate entry point. Raise RuleBindingGateError to reject admission.

    Behaviors:
      - Directive YAML has no recycle_rule.name field -> no-op (non-basket).
      - Multiple registry patterns match directive_id -> hard reject.
      - Single binding match + YAML rule_name mismatch -> hard reject.
      - Single binding match + YAML rule_name equal -> admit.
      - Single legacy_patterns match -> WARN + telemetry, admit.
      - No match + meta.strict_unknown=true -> hard reject (Phase A2).
      - No match + meta.strict_unknown=false -> WARN + telemetry, admit (Phase A1).
    """
    registry = _load_registry()
    strict_unknown = bool((registry.get("meta") or {}).get("strict_unknown"))

    directive_id = directive_path.stem
    observed = _load_directive_rule_name(directive_path)
    if observed is None:
        return

    matches = _find_matches(directive_id, registry)

    if len(matches) > 1:
        patterns = " | ".join(m.pattern for m in matches)
        raise RuleBindingGateError(
            f"[RULE_BINDING_GATE] AMBIGUOUS directive '{directive_id}' "
            f"matches multiple registry patterns: {patterns}. "
            f"Ambiguity is a registry-hygiene failure. Refine patterns in "
            f"governance/namespace/directive_rule_binding.yaml."
        )

    if len(matches) == 1:
        m = matches[0]
        if m.section == "bindings":
            if observed != m.rule_name:
                raise RuleBindingGateError(
                    f"[RULE_BINDING_GATE] MISMATCH directive '{directive_id}' "
                    f"matches pattern '{m.pattern}' which expects "
                    f"recycle_rule.name='{m.rule_name}', "
                    f"but YAML declares recycle_rule.name='{observed}'. "
                    f"Comparison is exact (case-sensitive)."
                )
            return

        fragment = _extract_candidate_fragment(directive_id)
        _emit_telemetry(
            directive_path=directive_path,
            observed_rule_name=observed,
            candidate_fragment=fragment,
            match_class="legacy",
        )
        print(
            f"[RULE_BINDING_GATE][WARN] LEGACY pattern detected: directive "
            f"'{directive_id}' matches legacy pattern '{m.pattern}' "
            f"(fragment={fragment!r}, observed_rule_name={observed!r}). "
            f"Suggested remediation: legacy pattern detected; explicit "
            f"binding decision required before Phase A2 strict mode."
        )
        return

    if strict_unknown:
        raise RuleBindingGateError(
            f"[RULE_BINDING_GATE] UNKNOWN pattern for directive "
            f"'{directive_id}': no entry in directive_rule_binding registry. "
            f"Add explicit binding if intentional."
        )
    fragment = _extract_candidate_fragment(directive_id)
    _emit_telemetry(
        directive_path=directive_path,
        observed_rule_name=observed,
        candidate_fragment=fragment,
        match_class="unknown",
    )
    print(
        f"[RULE_BINDING_GATE][WARN] UNKNOWN pattern for directive "
        f"'{directive_id}' (fragment={fragment!r}, "
        f"observed_rule_name={observed!r}). "
        f"Phase A1: admitting with warn. Add to registry before Phase A2."
    )
