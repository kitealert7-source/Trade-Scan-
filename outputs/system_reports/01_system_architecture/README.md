# Architectural Documentation Guide

To understand the TradeScan system architecture, reading the documents in this directory is highly recommended. Please follow this specific order to build context from high-level boundaries down to low-level implementation details:

1. `SYSTEM_SURFACE_MAP.md` — System boundaries, architecture overview, capital profiles, and 25 codified invariants.
2. `pipeline_flow.md` — Full-stage execution flow including Steps 7–10 (Capital, Robustness, Formatting).
3. `capability_map_analysis.md` — Specific stage capabilities, infrastructure components, and skill candidates.
4. `SYSTEM_ENTRYPOINTS.md` — Operational and governance entrypoints with authority classifications.
5. `PIPELINE_INVARIANTS.md` — Hard system invariants, determinism guarantees, and resolved soft spots.
6. `REPOSITORY_AUTHORITY_MAP.md` — Deep-dive on directory and file authority across all layers.

---
**Last Updated**: 2026-03-23 | All documents at **Version 2.0.0**
