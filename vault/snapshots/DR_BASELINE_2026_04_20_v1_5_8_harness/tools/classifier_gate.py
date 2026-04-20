"""
classifier_gate.py — Phase 4 Admission Pre-Check.

Purpose
-------
Given the current directive, compare it against the most recent *prior*
directive for the same (MODEL, ASSET_CLASS) pair and decide whether
admission should proceed.

This gate combines two lightweight, fully mechanical signals:

  1. Structural delta via `directive_diff_classifier.classify_diff`
     (SIGNAL / PARAMETER / COSMETIC / UNCLASSIFIABLE).
  2. Aggregate indicator content hash via `indicator_hasher`
     (semantic, cosmetic-tolerant sha256 of the imported indicator modules).

Verdict rules (evaluated in order; first BLOCK wins)
---------------------------------------------------
  * If no prior directive exists for (MODEL, ASSET_CLASS) -> PASS (first-of-kind).
  * If classification == UNCLASSIFIABLE                    -> BLOCK.
  * If classification == SIGNAL and signal_version has NOT
    strictly increased beyond the prior maximum               -> BLOCK.
  * If the aggregate indicator content hash differs from the
    prior run's recorded hash AND signal_version is unchanged -> BLOCK.
  * Otherwise                                                 -> PASS.

This module is deliberately:
  - Pure: no pipeline mutation, no I/O beyond reading directives/indicator code
          and (optionally) looking up prior hashes through an injected callback.
  - Additive: the admission controller calls it; downstream stages are unchanged.
  - Fail-closed: any ambiguity that the classifier marks UNCLASSIFIABLE blocks.

CLI
---
    python tools/classifier_gate.py backtest_directives/INBOX/<NEW>.txt

Useful for manual pre-flight of a directive before submitting to the pipeline.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.directive_diff_classifier import classify_diff
from tools.indicator_hasher import aggregate_indicator_hash
from tools.pipeline_utils import parse_directive
from config.asset_classification import (
    classify_asset,
    infer_asset_class_from_symbols,
    parse_strategy_name,
    MixedAssetClassError,
    UnknownSymbolError,
)

# Prefix injected by tools/rerun_backtest.py for ENGINE-category reruns.
# Shape: [RERUN:ENGINE@YYYY-MM-DD origin=... strategy=...] <user reason>
_RERUN_ENGINE_PREFIX_RE = re.compile(r"^\[RERUN:ENGINE@", re.IGNORECASE)

# Default directories scanned when discovering prior directives.
# Order is informational only — all are unioned.
_DEFAULT_PRIOR_DIRS: tuple[Path, ...] = (
    PROJECT_ROOT / "backtest_directives" / "completed",
    PROJECT_ROOT / "backtest_directives" / "active_backup",
    PROJECT_ROOT / "backtest_directives" / "active",
)


@dataclass(frozen=True)
class GateVerdict:
    verdict: str  # "PASS" | "BLOCK"
    reason: str
    classification: str  # SIGNAL / PARAMETER / COSMETIC / UNCLASSIFIABLE / N/A
    prior_directive: str | None
    prior_max_signal_version: int | None
    current_signal_version: int
    current_indicators_hash: str
    prior_indicators_hash: str | None
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "classification": self.classification,
            "prior_directive": self.prior_directive,
            "prior_max_signal_version": self.prior_max_signal_version,
            "current_signal_version": self.current_signal_version,
            "current_indicators_hash": self.current_indicators_hash,
            "prior_indicators_hash": self.prior_indicators_hash,
            "details": self.details,
        }


def _safe_int(v: Any, default: int = 1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _extract_identity(directive: dict) -> tuple[str, str, int]:
    """Return (MODEL_token, ASSET_CLASS, signal_version) for a parsed directive."""
    strategy_name = str(directive.get("strategy") or directive.get("name") or "")
    parsed = parse_strategy_name(strategy_name) if strategy_name else None
    model = str((parsed or {}).get("model", "")).upper()

    symbols = directive.get("symbols") or []
    try:
        asset_class = infer_asset_class_from_symbols([str(s) for s in symbols])
    except (MixedAssetClassError, UnknownSymbolError, ValueError):
        asset_class = classify_asset(strategy_name)
    asset_class = str(asset_class or "").upper()

    sv = _safe_int(directive.get("signal_version"), default=1)
    return model, asset_class, sv


def _iter_prior_directives(dirs: Iterable[Path]) -> list[Path]:
    """Yield every .txt directive under the given directories (deduplicated by path)."""
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*.txt"):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
    return out


def _find_prior_matches(
    current_path: Path,
    current_model: str,
    current_asset_class: str,
    search_dirs: Iterable[Path],
    *,
    allow_same_stem: bool = False,
) -> list[tuple[Path, dict, int]]:
    """Return prior directives matching (model, asset_class), each as
    (path, parsed_dict, signal_version). Excludes the current directive by path.
    Sorted by mtime descending (most recent first).

    allow_same_stem: when True (ENGINE reruns), the completed/ copy of the
    source directive is included so it can serve as the comparison baseline.
    The exact-path exclusion still applies; only the same-stem exclusion is
    lifted, preventing a directive from comparing against itself while still
    allowing the source directive to be the prior.
    """
    current_resolved = current_path.resolve()
    current_stem = current_path.stem
    matches: list[tuple[Path, dict, int, float]] = []
    for path in _iter_prior_directives(search_dirs):
        if path.resolve() == current_resolved:
            continue
        # Same basename => this is the same directive at a different lifecycle
        # location (e.g. completed/ copy of a re-run from INBOX). For ENGINE
        # reruns the completed/ copy IS the valid source baseline; lift the
        # exclusion so the cosmetic-only delta (end_date + repeat_override_reason)
        # is what the classifier sees.  For all other runs keep the exclusion so
        # a directive never "compares against itself".
        if path.stem == current_stem and not allow_same_stem:
            continue
        try:
            parsed = parse_directive(path)
        except Exception:
            continue
        m, ac, sv = _extract_identity(parsed)
        if m == current_model and ac == current_asset_class:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            matches.append((path, parsed, sv, mtime))
    matches.sort(key=lambda t: t[3], reverse=True)
    return [(p, d, sv) for (p, d, sv, _m) in matches]


def _is_engine_rerun(directive: dict) -> bool:
    """True when this directive carries an ENGINE-category override reason.

    Detects the prefix injected by tools/rerun_backtest.py for the ENGINE
    category: ``[RERUN:ENGINE@<date> origin=... strategy=...] <reason>``.
    Any other override reason (SIGNAL / PARAMETER / DATA_FRESH / BUG_FIX)
    returns False — only ENGINE reruns expect the engine-only-change
    invariance that justifies narrowing.
    """
    test_block = directive.get("test") or {}
    if not isinstance(test_block, dict):
        return False
    reason = test_block.get("repeat_override_reason") or ""
    if not isinstance(reason, str):
        return False
    return bool(_RERUN_ENGINE_PREFIX_RE.match(reason.strip()))


def _extract_structural_identity(directive: dict) -> dict | None:
    """Return {family, timeframe, sweep} parsed from the directive's strategy
    name. Returns None if the strategy name is unstructured (PF_ hash or
    non-conforming), in which case narrowing should not be attempted.
    """
    strategy_name = str(directive.get("strategy") or directive.get("name") or "")
    if not strategy_name:
        return None
    parsed = parse_strategy_name(strategy_name)
    if not parsed:
        return None
    return {
        "family":    str(parsed.get("family", "")).upper(),
        "timeframe": str(parsed.get("timeframe", "")).upper(),
        "sweep":     str(parsed.get("sweep", "")).upper(),
    }


def _find_prior_matches_narrowed(
    current_path: Path,
    current_directive: dict,
    current_model: str,
    current_asset_class: str,
    search_dirs: Iterable[Path],
) -> list[tuple[Path, dict, int]]:
    """Wrapper around _find_prior_matches that restricts the candidate set to
    priors sharing the same structural identity (family, timeframe, sweep)
    when the current directive is an ENGINE-category rerun.

    Rationale: engine-only reruns expect full invariance of the directive.
    Comparing against a structurally-distant sibling (different timeframe or
    sweep variant) produces spurious UNCLASSIFIABLE verdicts on legitimate
    filter/regime differences that were never part of the engine upgrade.

    Falls back to the wide (model, asset_class) match set when:
      * the override reason is not an ENGINE rerun, or
      * the current strategy name is unstructured, or
      * the narrowed set is empty (nothing comparable exists yet).
    """
    engine_rerun = _is_engine_rerun(current_directive)
    wide = _find_prior_matches(
        current_path, current_model, current_asset_class, search_dirs,
        allow_same_stem=engine_rerun,
    )
    if not wide:
        return wide
    if not engine_rerun:
        return wide
    cur_id = _extract_structural_identity(current_directive)
    if cur_id is None:
        return wide
    narrowed: list[tuple[Path, dict, int]] = []
    for path, parsed, sv in wide:
        pid = _extract_structural_identity(parsed)
        if pid is None:
            continue
        if (pid["family"] == cur_id["family"]
                and pid["timeframe"] == cur_id["timeframe"]
                and pid["sweep"] == cur_id["sweep"]):
            narrowed.append((path, parsed, sv))
    # For ENGINE reruns: if the same-structure prior set is empty, there is
    # no structurally comparable baseline → treat as first-of-kind (PASS).
    # Do NOT fall back to the wide set; comparing an ENGINE rerun against a
    # structurally different strategy (different family/TF/sweep) always
    # produces UNCLASSIFIABLE verdicts for differences that predate the
    # engine upgrade and are irrelevant to the engine-only change.
    if engine_rerun:
        return narrowed  # empty list → evaluate() will PASS as first-of-kind
    return narrowed if narrowed else wide


def evaluate(
    directive_path: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    search_dirs: Iterable[Path] | None = None,
    prior_indicators_hash_lookup: Callable[[str], str | None] | None = None,
) -> GateVerdict:
    """Run the classifier gate against a directive file.

    Args:
        directive_path: Path to the current directive .txt (YAML).
        project_root: Repo root used to resolve indicator module paths.
        search_dirs: Directories scanned for prior matching directives.
            Defaults to backtest_directives/{completed,active_backup,active}.
        prior_indicators_hash_lookup: Optional callable
            (prior_directive_stem) -> prior aggregate indicators hash string.
            When None, prior-hash comparison is skipped (verdict still considers
            classification + signal_version rules).

    Returns:
        GateVerdict (verdict in {"PASS", "BLOCK"}, plus diagnostic details).
    """
    dirs = tuple(search_dirs) if search_dirs is not None else _DEFAULT_PRIOR_DIRS

    current = parse_directive(directive_path)
    cur_model, cur_asset, cur_sv = _extract_identity(current)

    # Always compute current aggregate indicator hash (cheap; useful in both branches).
    cur_indicators = [
        m for m in (current.get("indicators") or []) if isinstance(m, str)
    ]
    cur_hash, cur_per_module = aggregate_indicator_hash(
        cur_indicators, project_root=project_root
    )

    priors = _find_prior_matches_narrowed(
        directive_path, current, cur_model, cur_asset, dirs
    )

    if not priors:
        return GateVerdict(
            verdict="PASS",
            reason=(
                f"No prior directive found for MODEL={cur_model!r}, "
                f"ASSET_CLASS={cur_asset!r}; first-of-kind."
            ),
            classification="N/A",
            prior_directive=None,
            prior_max_signal_version=None,
            current_signal_version=cur_sv,
            current_indicators_hash=cur_hash,
            prior_indicators_hash=None,
            details={
                "model": cur_model,
                "asset_class": cur_asset,
                "per_module_hashes": cur_per_module,
            },
        )

    # Most recent prior drives classification; max SV across all priors
    # drives the signal_version monotonicity check.
    prior_path, prior_parsed, _prior_sv = priors[0]
    prior_max_sv = max(sv for (_p, _d, sv) in priors)

    classification_result = classify_diff(
        prior_parsed, current, project_root=project_root
    )
    classification = classification_result["classification"]

    prior_hash: str | None = None
    if prior_indicators_hash_lookup is not None:
        try:
            prior_hash = prior_indicators_hash_lookup(prior_path.stem)
        except Exception:
            prior_hash = None

    def _build(
        verdict: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> GateVerdict:
        details: dict[str, Any] = {
            "model": cur_model,
            "asset_class": cur_asset,
            "classifier": classification_result,
            "per_module_hashes": cur_per_module,
        }
        if extra:
            details.update(extra)
        return GateVerdict(
            verdict=verdict,
            reason=reason,
            classification=classification,
            prior_directive=prior_path.stem,
            prior_max_signal_version=prior_max_sv,
            current_signal_version=cur_sv,
            current_indicators_hash=cur_hash,
            prior_indicators_hash=prior_hash,
            details=details,
        )

    # Rule 1: UNCLASSIFIABLE is always fail-closed.
    if classification == "UNCLASSIFIABLE":
        return _build(
            "BLOCK",
            (
                "Delta vs prior directive "
                f"{prior_path.stem!r} is UNCLASSIFIABLE "
                f"({classification_result['reason']}). Fail-closed: add a "
                f"signal_version bump or reshape the directive so the delta "
                f"is mechanically classifiable."
            ),
        )

    # Rule 2: SIGNAL change requires signal_version to strictly exceed prior max.
    if classification == "SIGNAL" and cur_sv <= prior_max_sv:
        return _build(
            "BLOCK",
            (
                f"Classifier marks change as SIGNAL "
                f"({classification_result['reason']}), but signal_version={cur_sv} "
                f"is not > prior max signal_version={prior_max_sv}. "
                f"Bump signal_version to >= {prior_max_sv + 1} and re-run."
            ),
        )

    # Rule 3: indicator content hash changed silently (same SV).
    if (
        prior_hash is not None
        and prior_hash != ""
        and prior_hash != cur_hash
        and cur_sv <= prior_max_sv
    ):
        return _build(
            "BLOCK",
            (
                f"Indicator content hash changed (prior={prior_hash[:12]}, "
                f"current={cur_hash[:12]}) but signal_version={cur_sv} was not "
                f"incremented beyond prior max={prior_max_sv}. Silent logic "
                f"change in an indicator module is disallowed — bump "
                f"signal_version to >= {prior_max_sv + 1}."
            ),
            extra={"indicator_hash_delta_detected": True},
        )

    # Allow PARAMETER, COSMETIC, or SIGNAL-with-proper-bump through.
    return _build(
        "PASS",
        (
            f"Delta vs prior {prior_path.stem!r} is {classification}. "
            f"signal_version={cur_sv} (prior max={prior_max_sv}). "
            f"Admission proceeds."
        ),
    )


def _main() -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Classifier gate pre-check.")
    p.add_argument("directive", type=Path)
    p.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
    )
    args = p.parse_args()

    verdict = evaluate(args.directive, project_root=args.project_root)
    print(json.dumps(verdict.as_dict(), indent=2, default=str))
    return 0 if verdict.verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(_main())
