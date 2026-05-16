"""Harvest Robustness — analysis modules.

Each module is a standalone analysis script invoked by the harness
(tools/harvest_robustness/harness.py) via subprocess. Scripts produce
their results on stdout; the harness captures and collates them.

Migrated from tmp/ on 2026-05-16 to make the harness self-contained.
Module logic is unchanged; only path-derivation lines were updated to
reflect the new file location.
"""
