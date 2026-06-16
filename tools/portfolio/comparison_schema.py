"""comparison_schema.py -- single source of truth for the `comparison` ledger.

A `comparison` row is the smallest deployable provenance unit and it is EVIDENCE:
its very EXISTENCE certifies that two SPECIFIC runs were a valid, apples-to-apples
basis for a deployment decision. There is no status column to read -- the row is
only allowed to exist when the comparison is sound.

  comparison row EXISTS   ->  deployment evidence exists
  comparison row ABSENT   ->  deployment evidence does not exist

A row is REFUSED (the writer raises; no row is written) unless BOTH runs are
*certified* and the comparison is sound. "Certified run" means exactly:
  - is_current = 1     (the authoritative run, not a superseded/stale one), AND
  - witness-complete   (effective_input_sha256, engine_version, engine_abi,
                        directive_sha256 all present -- no NULLs).
"Sound comparison" means:
  - same effective input data   (effective_input_sha256 left == right),
  - same engine                 ((engine_version, engine_abi) left == right, STAMP),
  - the intended directive delta (directive_sha256 left != right).

Invalid evidence is NOT representable -- there is no `comparable=no` /
`indeterminate` row. Operational telemetry about refused attempts, if ever wanted,
belongs elsewhere; it must not weaken the meaning of this evidence table.

SCOPE (do NOT grow this into a research platform / a gate):
  - engine equality is the STAMP, not the imported compute
    ([[engine-identity-is-compute-not-stamp]]) -- "same recorded engine".
  - It records evidence; it does NOT block deployment (no gate, no workflow).
  - It does NOT record "which is better" -- that is the operator's call, carried
    in comparison_reason.
  - Evidence is scoped to cointegration runs (where the witnesses live).
"""
from __future__ import annotations

SCHEMA_VERSION = "comparison-2.0"   # 2.0: refusal-based evidence (existence = certification)
PRIMARY_KEY = "comparison_id"

# Append-only; additive at the right edge only.
COMPARISON_COLUMNS = [
    "comparison_id",       # PK: deterministic sha256(left_run_id|right_run_id|comparison_reason)
    "left_run_id",
    "right_run_id",
    "comparison_reason",   # free-text decision context (e.g. "deployability: BBK25 vs FXD25")
    "created_at",
]

# All columns are TEXT (no REAL/numeric).
COMPARISON_NUMERIC_COLUMNS: set[str] = set()

__all__ = [
    "SCHEMA_VERSION",
    "PRIMARY_KEY",
    "COMPARISON_COLUMNS",
    "COMPARISON_NUMERIC_COLUMNS",
]
