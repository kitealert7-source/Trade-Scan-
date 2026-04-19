"""
indicator_hasher.py - Semantic content hashing for indicator modules (Phase 4).

Computes a stable hash of an indicator module's source code that ignores
cosmetic noise (comments, blank lines, whitespace). Two modules with
identical logic but different formatting will hash to the same digest.

Used by:
  - The Phase 4 classifier gate: detects "same indicator import, different
    code" — i.e., silent logic changes that bypass SIGNAL_PRIMITIVE +
    signal_version because the directive structure is unchanged.
  - run_summary writer: persists an aggregate `indicators_content_hash`
    per run so prior runs' indicator code fingerprint is queryable.

Design: tokenize with the `tokenize` module, drop COMMENT / NL / NEWLINE /
INDENT / DEDENT / ENCODING tokens, concatenate the remainder, sha256.
This is cheap, deterministic, and stable across whitespace changes.
"""

from __future__ import annotations

import hashlib
import io
import tokenize
from pathlib import Path
from typing import Iterable

# Tokens that carry no logical meaning - dropping them makes the hash
# stable under reformatting, comment edits, and blank-line insertion.
_COSMETIC_TOKENS = frozenset({
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
})


def compute_indicator_hash(module_path: Path) -> str:
    """Return sha256 of the semantic token stream of a Python module.

    Returns an empty string if the module cannot be read or tokenized.
    """
    try:
        source = module_path.read_bytes()
    except OSError:
        return ""
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source).readline))
    except tokenize.TokenizeError:
        # Fall back to raw-bytes hash on tokenization failure so we still
        # detect any change - just without the cosmetic-tolerance guarantee.
        return hashlib.sha256(source).hexdigest()

    h = hashlib.sha256()
    for tok in tokens:
        if tok.type in _COSMETIC_TOKENS:
            continue
        # (type, string) is sufficient - positions are cosmetic.
        h.update(f"{tok.type}:{tok.string}\x00".encode("utf-8"))
    return h.hexdigest()


def resolve_module_path(dotted: str, project_root: Path) -> Path:
    """Convert 'indicators.structure.choch_v3' -> <root>/indicators/structure/choch_v3.py."""
    return project_root / Path(*dotted.split(".")).with_suffix(".py")


def aggregate_indicator_hash(
    modules: Iterable[str],
    project_root: Path,
) -> tuple[str, dict[str, str]]:
    """Compute per-module hashes + a single aggregate hash for a list of modules.

    Args:
        modules: iterable of dotted module paths (e.g. ['indicators.volatility.atr', ...]).
        project_root: repository root.

    Returns:
        (aggregate_hash, per_module_hashes_dict)
        aggregate_hash is sha256 of the sorted "<dotted>=<per_module_hash>" lines.
        Missing / unreadable modules contribute an empty string, still included
        in the sort so absence is itself reflected in the aggregate.
    """
    per_module: dict[str, str] = {}
    for mod in modules:
        path = resolve_module_path(mod, project_root)
        per_module[mod] = compute_indicator_hash(path)

    items = sorted(per_module.items())
    joined = "\n".join(f"{k}={v}" for k, v in items)
    aggregate = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return aggregate, per_module


def _main() -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Semantic hash of indicator modules.")
    p.add_argument("modules", nargs="+", help="Dotted module paths to hash.")
    p.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = p.parse_args()

    aggregate, per_module = aggregate_indicator_hash(args.modules, args.project_root)
    print(json.dumps(
        {"aggregate": aggregate, "per_module": per_module},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
