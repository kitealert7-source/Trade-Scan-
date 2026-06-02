"""
Guard-Layer Manifest Generator

Usage:
  python tools/generate_guard_manifest.py

Authority: AGENT.md — Protected Infrastructure Policy
Purpose: Compute canonical (LF-normalized) SHA-256 hashes for all Critical
         Guard Set files and write tools/tools_manifest.json.

Hashing: delegates to tools.verify_engine_integrity.canonical_sha256 so
         the same single LF-normalized implementation is used by both
         tools-manifest generation and integrity verification. Eliminates
         Windows CRLF false-failures on tools integrity (autocrlf=true
         checks out CRLF; canonical hash strips CR before hashing).

WARNING: This tool must ONLY be executed by a human operator OR by an
         agent acting on an explicit, scoped, in-session human
         authorization. Unauthorized manifest updates constitute a
         governance violation.
"""

import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TOOLS_ROOT = PROJECT_ROOT / "tools"
MANIFEST_PATH = TOOLS_ROOT / "tools_manifest.json"

sys.path.insert(0, str(PROJECT_ROOT))
from tools.verify_engine_integrity import canonical_sha256  # noqa: E402

# Critical Guard Set — files that constitute the governance boundary.
#
# Inclusion criterion: a tool belongs here iff it is LOADED DURING a pipeline
# run AND its correctness determines backtest / gating-decision integrity — so
# that a silent (unreviewed) change must freeze execution until a human
# re-blesses the manifest (the startup hash check in
# run_pipeline.verify_tools_timestamp_guard).
#
# Intentionally NOT guarded:
#   * Operator-driven cleanup tools that never run inside a pipeline
#     (lineage_pruner, directive_reconciler). They are covered by the
#     Protected-Infrastructure approval doctrine (AGENT.md #11) + their own
#     regression tests; guarding them would only couple unrelated cleanup
#     edits to pipeline availability.
#   * Per-experiment mechanics with their own governance: per-symbol
#     strategies/<id>/strategy.py (namespace_gate + SIGNATURE_HASH) and
#     tools/recycle_rules/* (governance/recycle_rules/registry.yaml).
GUARD_FILES = [
    # ── Single-strategy pipeline spine ──
    "run_pipeline.py",
    "run_stage1.py",
    "semantic_validator.py",
    "directive_schema.py",
    "strategy_provisioner.py",
    "exec_preflight.py",
    "strategy_dryrun_validator.py",
    "pipeline_utils.py",
    "portfolio_evaluator.py",
    "format_excel_artifact.py",
    "cleanup_reconciler.py",
    "run_portfolio_analysis.py",
    "skill_loader.py",
    "orchestration/runner.py",
    "system_logging/pipeline_failure_logger.py",
    # Manifest artifact-integrity contract: single source of truth for the
    # basket_code-vs-data/ PATH + HASH rule, shared by the startup gate
    # verify_manifest_integrity AND the system_preflight diagnostic. A silent
    # change to this rule could let corrupt run artifacts pass the gate, so an
    # unreviewed edit must freeze execution until the manifest is re-blessed.
    "manifest_verification.py",
    # ── Basket execution path (added 2026-06-01; dispatched by
    #    run_pipeline._try_basket_dispatch). The basket analogue of the
    #    single-strategy spine: orchestrator + engine + leg-data loader +
    #    admission validator. The per-basket mechanics (tools/recycle_rules/*)
    #    stay out under the per-experiment exclusion above. ──
    "basket_pipeline.py",
    "basket_runner.py",
    "basket_data_loader.py",
    "basket_schema.py",
]


def compute_sha256(filepath: Path) -> str:
    """Compute canonical (LF-normalized) SHA-256 hash of a file.

    Delegates to verify_engine_integrity.canonical_sha256 — single source
    of truth. Returns uppercase hex digest matching what the integrity
    verifier expects."""
    return canonical_sha256(filepath).upper()


def main():
    print("=" * 60)
    print("GUARD-LAYER MANIFEST GENERATOR")
    print("=" * 60)

    file_hashes = {}
    missing = []

    for filename in GUARD_FILES:
        filepath = TOOLS_ROOT / filename
        if not filepath.exists():
            missing.append(filename)
            print(f"  [MISS] {filename}")
            continue

        file_hash = compute_sha256(filepath)
        file_hashes[filename] = file_hash
        print(f"  [HASH] {filename}: {file_hash[:16]}...")

    if missing:
        print(f"\n[WARN] {len(missing)} file(s) not found. Manifest will be incomplete.")

    now_utc = datetime.now(timezone.utc)
    manifest = {
        "generated_at": now_utc.isoformat(),
        "file_hashes": file_hashes,
    }

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

    print(f"\n[DONE] Manifest written to {MANIFEST_PATH}")
    print(f"[INFO] {len(file_hashes)} files hashed.")
    print(f"[INFO] Generated at: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}")


if __name__ == "__main__":
    main()
