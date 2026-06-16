"""comparison_schema.py -- single source of truth for the `comparison` ledger.

A `comparison` row is the smallest deployable provenance unit: an append-only,
immutable record that TWO SPECIFIC RUNS were compared to support a decision
("is left preferred over right, for this reason?"). It is NOT an experiment, an
arm graph, or a verdict -- just the pairwise comparison that a deployment claim
rests on, plus a self-certification of whether that comparison was apples-to-apples.

CERTIFICATION (computed at write time from each run's cointegration_sheet row,
the witnesses promoted earlier this session):
  - data_match        <- effective_input_sha256(left) vs (right)   [same effective input data]
  - engine_match      <- (engine_version, engine_abi) left vs right [same engine STAMP -- see note]
  - directive_differs <- directive_sha256(left) != (right)          [the intended directive delta]
  - comparable        <- yes iff all three == yes; no if any == no; else indeterminate

TRI-STATE BY DESIGN: a missing witness yields `indeterminate`, NEVER `yes`. Absence
of evidence must not read as evidence of comparability -- the exact failure mode this
audit exists to prevent.

SCOPE (do NOT grow this into a research platform):
  - engine_match compares the STAMP, which can mislabel ([[engine-identity-is-compute-not-stamp]]);
    it means "same recorded engine", not "same imported compute". Compute-fingerprint is a
    separate, deferred axis.
  - It CERTIFIES; it does NOT gate/block. Enforcement is a separate later decision.
  - It does NOT record "which is better" (that is the operator's call, carried in
    comparison_reason) -- no verdict logic here.
  - Certification is scoped to cointegration runs (where the witnesses live).
"""
from __future__ import annotations

SCHEMA_VERSION = "comparison-1.0"
PRIMARY_KEY = "comparison_id"

# Append-only; additive at the right edge only (mirrors the ledger invariant).
COMPARISON_COLUMNS = [
    "comparison_id",       # PK: deterministic sha256(left_run_id|right_run_id|comparison_reason)
    "left_run_id",
    "right_run_id",
    "comparison_reason",   # free-text decision context (e.g. "deployability: BBK25 vs FXD25")
    "data_match",          # yes | no | indeterminate  (effective_input_sha256 L vs R)
    "engine_match",        # yes | no | indeterminate  ((engine_version, engine_abi) L vs R; STAMP)
    "directive_differs",   # yes | no | indeterminate  (directive_sha256 L != R)
    "comparable",          # yes | no | indeterminate  (all three yes / any no / else)
    "created_at",
]

# All columns are TEXT (no REAL/numeric); the tri-state fields are enum-like strings.
COMPARISON_NUMERIC_COLUMNS: set[str] = set()

__all__ = [
    "SCHEMA_VERSION",
    "PRIMARY_KEY",
    "COMPARISON_COLUMNS",
    "COMPARISON_NUMERIC_COLUMNS",
]
