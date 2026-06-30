"""
Phase-1 Namespace Governance Gate.

Enforces:
1. Strategy naming pattern.
2. Token dictionary membership.
3. Alias normalization (no alias token allowed in committed names).
4. filename == test.name; test.name == test.strategy OR test.strategy + '__<RUN_SUFFIX>'.
5. Idea registry existence + FAMILY match.

Run suffix convention: a /rerun-backtest variant carries a run-context suffix of the form
__[A-Z0-9]+ (e.g. __E152, __ROBUST, __MC1000) on BOTH the filename and test.name, to
distinguish re-runs under different engines or configurations without creating new sweep
registry entries. test.strategy stays at the base (the stable namespace identity); the
filename tracks test.name. See .claude/skills/rerun-backtest/SKILL.md "Variant Naming Rule".
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
from tools.basket_schema import is_basket_directive, validate_basket_block
from config.asset_classification import parse_strategy_name

NAMESPACE_ROOT = PROJECT_ROOT / "governance" / "namespace"
IDEA_REGISTRY_PATH = NAMESPACE_ROOT / "idea_registry.yaml"
TOKEN_DICTIONARY_PATH = NAMESPACE_ROOT / "token_dictionary.yaml"
SWEEP_REGISTRY_PATH = NAMESPACE_ROOT / "sweep_registry.yaml"
RECYCLE_REGISTRY_PATH = PROJECT_ROOT / "governance" / "recycle_rules" / "registry.yaml"


def _validate_recycle_rule_code_hash(parsed: dict) -> list[str]:
    """Compare the directive's recycle-rule module hash to the pinned hash in
    rule_code_hashes.yaml. Returns a list of error strings ([] = ok).

    Soft-skip (returns []) when the sidecar is absent or the provenance module
    is unavailable, so a missing pin never blocks admission — the gate only
    catches *accidental* drift (an edited rule whose version was not bumped and
    whose hash was not re-blessed). A present-but-unknown rule or a hash
    mismatch is a hard error.
    """
    try:
        from tools.basket_provenance import (
            load_recycle_rule_hashes,
            recycle_rule_code_sha256,
        )
    except Exception:
        return []  # provenance module unavailable — do not block admission

    pinned = load_recycle_rule_hashes()
    if not pinned:
        return []  # sidecar absent/empty — soft skip

    rule = (parsed.get("basket") or {}).get("recycle_rule") or {}
    name = rule.get("name")
    if not name:
        return []  # rule presence is validated by basket_schema, not here
    version = int(rule.get("version", 1))
    key = f"{name}@{version}"

    expected = pinned.get(key)
    if expected is None:
        return [
            f"recycle_rule {key} has no pinned code hash in "
            f"rule_code_hashes.yaml. Register + hash it via "
            f"`python tools/generate_recycle_rule_hashes.py`."
        ]
    try:
        actual = recycle_rule_code_sha256(name, version)
    except Exception as exc:
        return [f"cannot hash recycle_rule {key}: {exc}"]
    if actual != expected:
        return [
            f"recycle_rule {key} code hash {actual[:12]} != pinned "
            f"{expected[:12]} — the rule's code changed without a version bump. "
            f"Bump the rule version (append-only) for a behavior change, or if "
            f"this is an intended in-place fix rehash via "
            f"`python tools/generate_recycle_rule_hashes.py`."
        ]
    return []

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

    # Governed identity (reconciles the namespace contract with /rerun-backtest):
    #   * test.strategy is the immutable namespace BASE anchor.
    #   * test.name is the base OR base + a '__<RUN_SUFFIX>' run-context tag that
    #     /rerun-backtest rotates per variant (e.g. __E152, __ROBUST, __MC1000).
    #   * the filename always tracks test.name — a rotated rerun variant carries
    #     the suffix on BOTH the filename and test.name while test.strategy stays
    #     at the base (see .claude/skills/rerun-backtest/SKILL.md "Variant Naming
    #     Rule"). So the filename is matched against test.name, not test.strategy.
    if test_name != test_strategy:
        suffix = test_name[len(test_strategy):]
        if not test_name.startswith(test_strategy) or not _RUN_SUFFIX_RE.fullmatch(suffix):
            raise NamespaceValidationError(
                "NAMESPACE_IDENTITY_MISMATCH: test.name must equal test.strategy or "
                "test.strategy + '__<RUN_SUFFIX>' where RUN_SUFFIX is [A-Z0-9]+. "
                f"Found test.strategy='{test_strategy}', test.name='{test_name}'."
            )

    if file_stem != test_name:
        raise NamespaceValidationError(
            "NAMESPACE_IDENTITY_MISMATCH: Require filename == test.name. "
            f"Found filename='{file_stem}', test.name='{test_name}'."
        )

    return file_stem, test_name, test_strategy


def _format_identity(identity: tuple[str, str, str, str]) -> str:
    """Render an identity tuple as 'FAMILY MODEL SYMBOL TIMEFRAME' for diagnostics."""
    family, model, symbol, timeframe = identity
    return f"{family} {model} {symbol} {timeframe}"


def _registered_identity_set(
    idea_id: str,
    sweep_registry_path: Path | None = None,
) -> set[tuple[str, str, str, str]]:
    """Return the SET of identity tuples (family, model, symbol, timeframe) already
    registered under ``idea_id`` in the sweep registry.

    The set is sourced from the ``directive_name`` values filed under the idea
    (sweep owners + their patches), parsed with the SAME parser the classifier
    gate uses (config.asset_classification.parse_strategy_name). Legacy or
    unparseable names are skipped rather than raising -- this guard never blocks
    on a name it cannot read.

    Returns an empty set when the registry is absent, the idea has no entries, or
    nothing filed under it parses.
    """
    path = sweep_registry_path or SWEEP_REGISTRY_PATH
    if not path.exists():
        return set()
    try:
        registry = _load_yaml(path)
    except NamespaceValidationError:
        return set()  # unreadable registry -- soft skip; never block on it
    # Reuse the canonical sweeps+patches traversal so a registry schema change is
    # absorbed in one place (tools.sweep_registry_gate.get_all_allocated_names).
    from tools.sweep_registry_gate import get_all_allocated_names

    identities: set[tuple[str, str, str, str]] = set()
    for name in get_all_allocated_names(registry):
        parsed = parse_strategy_name(name)
        if not parsed or parsed.get("idea_id") != idea_id:
            continue
        identities.add(
            (parsed["family"], parsed["model"], parsed["symbol"], parsed["timeframe"])
        )
    return identities


def _check_identity_registered(
    idea_id: str,
    current_identity: tuple[str, str, str, str],
    sweep_registry_path: Path | None = None,
) -> None:
    """EARLY identity guard -- fail at lint / pre-provision time when a directive
    reuses an ``idea_id`` for an identity that idea_id does not already own.

    An idea_id OWNS a SET of already-registered identity tuples
    (family, model, symbol, timeframe) -- its **registered identity set**. The
    sweep registry is treated as append-only and forward-only:

      * Existing registered tuples are IMMUTABLE and always valid (grandfathered).
        This check governs NEW registrations only; it never rewrites or
        invalidates a legacy allocation. (26 idea_ids legitimately own >1 tuple --
        e.g. idea 42 = 20 FX LIQSWEEP pairs -- and every one keeps passing on
        re-run because it self-matches its own registered tuple.)
      * A tuple NOT in the set cannot be added to an existing idea_id -> FAIL;
        allocate a new sequential idea_id.
      * An empty set (fresh idea_id) -> PASS; the idea establishes its first
        identity here.

    This is the EARLY twin of classifier_gate.py's late IDENTITY_CHANGE verdict --
    the same rule, but sourced from the registry so it fires before
    strategy_provisioner.py scaffolds anything. classifier_gate.py is left
    unchanged; this is an additive earlier surface.
    """
    registered = _registered_identity_set(idea_id, sweep_registry_path)
    if not registered or current_identity in registered:
        return
    listing = "\n".join("  " + _format_identity(t) for t in sorted(registered))
    raise NamespaceValidationError(
        f"NAMESPACE_IDENTITY_NOT_REGISTERED: Identity tuple not registered under "
        f"idea_id '{idea_id}'.\n\n"
        f"Registered identities:\n{listing}\n\n"
        f"Current:\n  {_format_identity(current_identity)}\n\n"
        f"Action:\n  Allocate a new sequential idea_id "
        f"(identity (family, model, symbol, timeframe) is immutable within an idea_id)."
    )


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
    # SYSTEM INVARIANT: MODEL must not contain "FILT", FILTER must end with "FILT".
    # This boundary enables unambiguous optional-token parsing downstream.
    # See governance/namespace/token_dictionary.yaml for full rationale.
    if "FILT" in model:
        raise NamespaceValidationError(
            f"INVARIANT_VIOLATION: MODEL token '{model}' contains 'FILT'. "
            f"MODEL tokens must never contain 'FILT' — this is reserved for FILTER tokens."
        )
    filter_token = ""
    if m.group("filter"):
        filter_token = _normalize_with_alias(
            "FILTER", m.group("filter"), allowed_filters, filter_aliases
        )
        if not filter_token.endswith("FILT"):
            raise NamespaceValidationError(
                f"INVARIANT_VIOLATION: FILTER token '{filter_token}' does not end with 'FILT'. "
                f"All FILTER tokens must end with 'FILT'."
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

    # EARLY identity guard: the directive's full identity tuple must already belong
    # to this idea_id's registered identity set, else a new sequential idea_id must
    # be allocated. Fires at lint / pre-provision time -- the early twin of
    # classifier_gate.py's late IDENTITY_CHANGE verdict. See _check_identity_registered.
    _check_identity_registered(idea_id, (family, model, symbol, timeframe))

    # Basket-directive guard (Plan Phase 1):
    #   * if model == RECYCLE, the directive MUST contain a `basket:` block.
    #   * if a `basket:` block is present, validate it.
    #   * the basket.basket_id MUST equal the SYMBOL slot of the filename.
    has_basket = is_basket_directive(parsed)
    if model == "RECYCLE" and not has_basket:
        raise NamespaceValidationError(
            "NAMESPACE_BASKET_REQUIRED: model='RECYCLE' but directive has no "
            "top-level `basket:` block. RECYCLE strategies are multi-leg by "
            "construction and require the basket schema (legs[], recycle_rule, "
            "optional regime_gate)."
        )
    if has_basket:
        basket_errors = validate_basket_block(
            parsed,
            recycle_registry_path=RECYCLE_REGISTRY_PATH,
            name_symbol_slot=symbol,
        )
        if basket_errors:
            raise NamespaceValidationError(
                "NAMESPACE_BASKET_INVALID:\n  - " + "\n  - ".join(basket_errors)
            )

        # Recycle-rule code-integrity gate: the rule's actual module-file hash
        # must match the pin in governance/recycle_rules/rule_code_hashes.yaml.
        # Catches a rule whose CODE changed without a version bump + rehash,
        # making the registry's append-only "version is part of the basket
        # strategy hash" guarantee mechanical instead of convention-only.
        rule_hash_errors = _validate_recycle_rule_code_hash(parsed)
        if rule_hash_errors:
            raise NamespaceValidationError(
                "NAMESPACE_RECYCLE_RULE_CODE_DRIFT:\n  - "
                + "\n  - ".join(rule_hash_errors)
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
        "is_basket": "yes" if has_basket else "no",
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
