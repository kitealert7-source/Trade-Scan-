"""
Phase-1 Namespace Governance Gate.

Enforces:
1. Strategy naming pattern.
2. Token dictionary membership.
3. Alias normalization (no alias token allowed in committed names).
4. filename == test.strategy (strict); test.name == filename OR filename + '__<RUN_SUFFIX>'.
5. Idea registry existence + FAMILY match.

Run suffix convention: test.name may carry a run-context suffix of the form __[A-Z0-9]+
(e.g. __E152, __ROBUST, __MC1000) to distinguish re-runs under different engines or
configurations without creating new sweep registry entries. The directive filename and
test.strategy remain the stable namespace identity.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import parse_directive

NAMESPACE_ROOT = PROJECT_ROOT / "governance" / "namespace"
IDEA_REGISTRY_PATH = NAMESPACE_ROOT / "idea_registry.yaml"
TOKEN_DICTIONARY_PATH = NAMESPACE_ROOT / "token_dictionary.yaml"

NAME_PATTERN = re.compile(
    r"^(?P<clone>C_)?"
    r"(?P<idea_id>\d{2})_"
    r"(?P<family>[A-Z0-9]+)_"
    r"(?P<symbol>[A-Z0-9]+)_"
    r"(?P<timeframe>[A-Z0-9]+)_"
    r"(?P<model>[A-Z0-9]+)"
    r"(?:_(?P<filter>[A-Z0-9]+))?_"
    r"S(?P<sweep>\d{2})_"
    r"V(?P<variant>\d+)_"
    r"P(?P<parent>\d{2})"
    r"(?:__(?P<run_suffix>[A-Z0-9]+))?$"
)

# Validated suffix format for run-context tags in test.name (e.g. __E152, __ROBUST).
_RUN_SUFFIX_RE = re.compile(r"^__[A-Z0-9]+$")


class NamespaceValidationError(ValueError):
    """Raised when directive namespace governance fails."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise NamespaceValidationError(f"Missing governance file: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise NamespaceValidationError(f"Invalid YAML: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise NamespaceValidationError(f"Expected mapping YAML: {path}")
    return payload


def _norm_token(token: str) -> str:
    return str(token).strip().upper()


def _normalize_with_alias(
    domain: str,
    token: str,
    allowed: set[str],
    aliases: dict[str, str],
) -> str:
    raw = _norm_token(token)
    normalized = aliases.get(raw, raw)
    if normalized not in allowed:
        raise NamespaceValidationError(
            f"NAMESPACE_TOKEN_INVALID: {domain}='{raw}' not in allowed set "
            f"{sorted(allowed)}"
        )
    if raw != normalized:
        raise NamespaceValidationError(
            f"NAMESPACE_ALIAS_FORBIDDEN: {domain}='{raw}' maps to '{normalized}'. "
            f"Use canonical token in directive name."
        )
    return normalized


def _extract_name_fields(parsed_directive: dict[str, Any], directive_path: Path) -> tuple[str, str, str]:
    test_block = parsed_directive.get("test")
    if not isinstance(test_block, dict):
        raise NamespaceValidationError("Directive missing required 'test' block.")

    file_stem = directive_path.stem
    test_name = str(test_block.get("name", "")).strip()
    test_strategy = str(test_block.get("strategy", "")).strip()

    if not file_stem or not test_name or not test_strategy:
        raise NamespaceValidationError(
            "NAMESPACE_IDENTITY_MISSING: filename stem, test.name, and test.strategy "
            "must all be present."
        )

    # filename must always equal test.strategy (stable namespace identity).
    if file_stem != test_strategy:
        raise NamespaceValidationError(
            "NAMESPACE_IDENTITY_MISMATCH: Require filename == test.strategy. "
            f"Found filename='{file_stem}', test.strategy='{test_strategy}'."
        )

    # test.name must equal filename exactly, OR filename + '__<RUN_SUFFIX>'
    # where RUN_SUFFIX matches [A-Z0-9]+ (e.g. __E152, __ROBUST, __MC1000).
    if test_name != file_stem:
        suffix = test_name[len(file_stem):]
        if not _RUN_SUFFIX_RE.fullmatch(suffix):
            raise NamespaceValidationError(
                "NAMESPACE_IDENTITY_MISMATCH: test.name must equal filename or "
                "filename + '__<RUN_SUFFIX>' where RUN_SUFFIX is [A-Z0-9]+. "
                f"Found filename='{file_stem}', test.name='{test_name}'."
            )

    return file_stem, test_name, test_strategy


def validate_namespace(directive_path: str | Path) -> dict[str, str]:
    d_path = Path(directive_path)
    if not d_path.exists():
        raise NamespaceValidationError(f"Directive not found: {d_path}")

    parsed = parse_directive(d_path)
    strategy_name, _, _ = _extract_name_fields(parsed, d_path)

    m = NAME_PATTERN.fullmatch(strategy_name)
    if not m:
        raise NamespaceValidationError(
            "NAMESPACE_PATTERN_INVALID: Expected "
            "<ID>_<FAMILY>_<SYMBOL>_<TF>_<MODEL>[_<FILTER>]_S<NN>_V<N>_P<NN> "
            "with optional 'C_' clone prefix."
        )

    idea_registry = _load_yaml(IDEA_REGISTRY_PATH)
    token_dict = _load_yaml(TOKEN_DICTIONARY_PATH)

    allowed_families = {_norm_token(v) for v in token_dict.get("family", [])}
    allowed_models = {_norm_token(v) for v in token_dict.get("model", [])}
    allowed_filters = {_norm_token(v) for v in token_dict.get("filter", [])}
    allowed_timeframes = {_norm_token(v) for v in token_dict.get("timeframe", [])}

    aliases = token_dict.get("aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}

    family_aliases = {
        _norm_token(k): _norm_token(v)
        for k, v in (aliases.get("family", {}) or {}).items()
    }
    model_aliases = {
        _norm_token(k): _norm_token(v)
        for k, v in (aliases.get("model", {}) or {}).items()
    }
    filter_aliases = {
        _norm_token(k): _norm_token(v)
        for k, v in (aliases.get("filter", {}) or {}).items()
    }
    timeframe_aliases = {
        _norm_token(k): _norm_token(v)
        for k, v in (aliases.get("timeframe", {}) or {}).items()
    }

    idea_id = m.group("idea_id")
    family = _normalize_with_alias(
        "FAMILY", m.group("family"), allowed_families, family_aliases
    )
    model = _normalize_with_alias(
        "MODEL", m.group("model"), allowed_models, model_aliases
    )
    filter_token = ""
    if m.group("filter"):
        filter_token = _normalize_with_alias(
            "FILTER", m.group("filter"), allowed_filters, filter_aliases
        )
    timeframe = _normalize_with_alias(
        "TF", m.group("timeframe"), allowed_timeframes, timeframe_aliases
    )
    symbol = _norm_token(m.group("symbol"))

    ideas_block = idea_registry.get("ideas", {})
    if not isinstance(ideas_block, dict):
        raise NamespaceValidationError(
            "Invalid idea_registry.yaml: expected top-level 'ideas' mapping."
        )

    idea_rec = ideas_block.get(idea_id)
    if not isinstance(idea_rec, dict):
        raise NamespaceValidationError(
            f"IDEA_ID_UNREGISTERED: idea_id='{idea_id}' not found in idea_registry.yaml"
        )

    reg_family = _norm_token(idea_rec.get("family", ""))
    if reg_family != family:
        raise NamespaceValidationError(
            "IDEA_FAMILY_MISMATCH: "
            f"idea_id='{idea_id}' registered family='{reg_family}', name family='{family}'."
        )
    for field in ("class", "regime", "role"):
        value = str(idea_rec.get(field, "")).strip()
        if not value:
            raise NamespaceValidationError(
                f"IDEA_METADATA_MISSING: idea_id='{idea_id}' missing required field '{field}'."
            )

    return {
        "strategy_name": strategy_name,
        "idea_id": idea_id,
        "family": family,
        "symbol": symbol,
        "timeframe": timeframe,
        "model": model,
        "filter": filter_token,
        "sweep": m.group("sweep"),
        "variant": m.group("variant"),
        "parent": m.group("parent"),
        "is_clone": "yes" if m.group("clone") else "no",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase-1 Namespace Governance Gate")
    parser.add_argument("directive_path", help="Path to directive YAML (.txt) file")
    args = parser.parse_args()

    try:
        details = validate_namespace(args.directive_path)
    except NamespaceValidationError as exc:
        print(f"[NAMESPACE_GATE] FAIL: {exc}")
        return 1
    except Exception as exc:  # defensive
        print(f"[NAMESPACE_GATE] FAIL: Unexpected error: {exc}")
        return 1

    print(
        "[NAMESPACE_GATE] PASS: "
        f"{details['strategy_name']} | "
        f"ID={details['idea_id']} FAMILY={details['family']} "
        f"SYMBOL={details['symbol']} TF={details['timeframe']} "
        f"MODEL={details['model']} "
        f"FILTER={details['filter'] or 'NONE'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
