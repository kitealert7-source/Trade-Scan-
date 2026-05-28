"""Methodology-citation admission gate (Task D).

Plan: outputs/system_reports/04_governance_and_guardrails/ENFORCEMENT_PLAN_2026-05-27.md Task D.
Pattern family: rule_binding_gate (namespace) + window_validity_gate.

THE GATE ANSWERS EXACTLY ONE QUESTION:
    "Does every slug in this directive's `methodology_citations` exist in the
     repo-local methodology registry?"

Trigger: presence of a non-empty `methodology_citations` field is the opt-in.
  - field absent (or empty)        -> gate no-op
  - field present + all slugs known -> admit
  - field present + any unknown slug -> hard reject

Validation target: governance/methodology/methodology_registry.yaml ONLY.
NO coupling to ~/.claude auto-memory, no harness-derived paths, no filesystem
traversal outside the repo. Deterministic, CI-stable, worktree-safe.

DELIBERATELY OUT OF SCOPE (do not add): semantic parsing of citation content,
citation-quality ranking, dependency graphs, mandatory universal rollout,
auto-memory mirroring. The registry holds slug identifiers only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from config.path_authority import REAL_REPO_ROOT

REGISTRY_PATH = REAL_REPO_ROOT / "governance" / "methodology" / "methodology_registry.yaml"


class MethodologyCitationGateError(Exception):
    """Raised when admission must be rejected by the methodology-citation gate."""


def _load_admissible_slugs() -> set[str]:
    if not REGISTRY_PATH.exists():
        raise MethodologyCitationGateError(
            f"methodology registry missing at {REGISTRY_PATH}"
        )
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    slugs: set[str] = set()
    for entry in data.get("citations") or []:
        slug = entry.get("slug") if isinstance(entry, dict) else None
        if isinstance(slug, str) and slug.strip():
            slugs.add(slug.strip())
    return slugs


def check_methodology_citations(directive_path: Path) -> None:
    """Gate entry point. Raise MethodologyCitationGateError to reject admission.

    No-op unless the directive declares a non-empty `methodology_citations`.
    """
    data = yaml.safe_load(directive_path.read_text(encoding="utf-8")) or {}
    cites = data.get("methodology_citations")
    if cites is None:
        return  # opt-in field absent — gate does not apply

    # Accept a bare string as a single citation; reject other shapes loudly.
    if isinstance(cites, str):
        cites = [cites]
    if not isinstance(cites, list):
        raise MethodologyCitationGateError(
            f"[METHODOLOGY_CITATION_GATE] directive '{directive_path.stem}' has a "
            f"malformed methodology_citations field (expected a list of slug "
            f"strings, got {type(cites).__name__})."
        )

    cited = [str(c).strip() for c in cites if str(c).strip()]
    if not cited:
        return  # present but empty — nothing to validate

    admissible = _load_admissible_slugs()
    unknown = [c for c in cited if c not in admissible]
    if unknown:
        raise MethodologyCitationGateError(
            f"[METHODOLOGY_CITATION_GATE] directive '{directive_path.stem}' cites "
            f"unknown methodology slug(s) {unknown} — not in "
            f"governance/methodology/methodology_registry.yaml. "
            f"Admissible slugs: {sorted(admissible)}. Add the slug to the "
            f"registry if the citation is intentional."
        )
