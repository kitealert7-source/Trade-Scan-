"""Canonical engine-name authority for Trade_Scan (selection layer).

The SINGLE place that names the canonical engine for every Trade_Scan execution
path (single-asset + basket). This module holds ONLY name constants + a
normalizer; it imports NO engine.

Compute-binding by VERIFICATION, not dispatch: the real compute is the static
``from engine_abi.v1_5_9 import (...)`` at tools/basket_runner.py:38 (basket) and
the dynamically-imported module in tools/run_stage1.run_engine_logic
(single-asset). This module only declares the EXPECTED identity; a fail-closed
convergence gate
(tests/test_engine_identity_convergence.py::test_selection_surfaces_converge_on_authority)
proves every selection surface names the same module the real compute uses, and
that the name resolves to that module's own ENGINE_VERSION. The authority NEVER
resolves, dispatches, or returns an engine.

SCOPE: Trade_Scan-internal. This does NOT govern the TS_Execution live ABI, which
is independently pinned to v1_5_9.

Doctrine: engine_identity_is_compute_not_stamp.
Design: outputs/system_reports/01_system_architecture/UNIFIED_ENGINE_AUTHORITY_PLAN.md.

Stdlib-only by contract (so config/ never pulls engine_abi/engine_dev into its
dependency graph, and the basket import stays AST-visible). DO NOT import any
engine module here.
"""
import re

__all__ = [
    "CANONICAL_ENGINE_ABI",
    "CANONICAL_SINGLE_ASSET_ENGINE",
    "CANONICAL_ENGINE_VERSION_DOTTED",
    "CANONICAL_SINGLE_ASSET_VERSION_DOTTED",
    "DRYRUN_CONTEXTVIEW_ENGINE",
    "DRYRUN_CONTEXTVIEW_WAIVER",
    "normalize_engine_token",
]


def _version_digits(token: str) -> list:
    """Extract [major, minor, patch] digit strings from a recognized engine
    token: 'engine_abi.v1_5_9', 'v1_5_9', 'v1_5_10', '1.5.9', 'v1.5.9'.

    NOTE: expects a bare engine token, not a full module path. For a dotted
    module path (e.g. 'engine_dev.universal_research_engine.v1_5_6.execution_loop')
    extract the 'vN_N_N' segment first (re.search(r'v\\d+_\\d+_\\d+', path)).
    """
    t = token.strip()
    if t.startswith("engine_abi."):
        t = t[len("engine_abi."):]
    t = t.lstrip("vV")
    nums = [p for p in re.split(r"[._]", t) if p.isdigit()]
    if not nums:
        raise ValueError(f"unrecognized engine token: {token!r}")
    return nums


def normalize_engine_token(token: str, style: str = "underscore") -> str:
    """Normalize any engine token to one canonical convention.

    style="underscore" -> "v1_5_8"  (matches config.engine_loader.get_active_engine)
    style="dotted"     -> "1.5.8"   (matches tools.pipeline_utils.get_engine_version)

    The ONE place dotted/underscored conversion lives, so the single-asset
    selectors draw their non-override value from a single source.
    """
    nums = _version_digits(token)
    if style == "underscore":
        return "v" + "_".join(nums)
    if style == "dotted":
        return ".".join(nums)
    raise ValueError(f"unknown style {style!r} (want 'underscore' or 'dotted')")


# --- The TWO switches for the whole system (today). A staged convergence
#     (UNIFIED_ENGINE_AUTHORITY_PLAN.md §4) flips these; the gate proves neither
#     silently diverges from the real compute. ---
CANONICAL_ENGINE_ABI = "engine_abi.v1_5_9"           # basket compute ABI
CANONICAL_SINGLE_ASSET_ENGINE = "v1_5_8"             # single-asset engine

# Derived dotted forms (parsed from the two switches above — never hand-set).
CANONICAL_ENGINE_VERSION_DOTTED = normalize_engine_token(CANONICAL_ENGINE_ABI, "dotted")               # "1.5.9"
CANONICAL_SINGLE_ASSET_VERSION_DOTTED = normalize_engine_token(CANONICAL_SINGLE_ASSET_ENGINE, "dotted")  # "1.5.8"

# --- Graft-(g) waiver: the dryrun structural surface, intentionally outside the
#     authority. tools/strategy_dryrun_validator.py imports ContextView from this
#     engine for a pure structural dry-run (NOT the run engine). It is deliberately
#     pinned and is NOT part of canonical-engine selection. The convergence gate
#     asserts the dryrun import still names DRYRUN_CONTEXTVIEW_ENGINE AND that this
#     waiver is present, so the surface cannot silently drift unnoticed. ---
DRYRUN_CONTEXTVIEW_ENGINE = "v1_5_6"
DRYRUN_CONTEXTVIEW_WAIVER = True  # WAIVER: dryrun ContextView pinned to v1_5_6 by design
