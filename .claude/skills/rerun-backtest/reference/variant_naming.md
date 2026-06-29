# Variant Naming Rule (__E### rotation)

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

A rerun lands as a **new directive variant** of the same family — same `test.strategy` (the base stem), but a freshly allocated `__E###` suffix on the filename and `test.name`. The Idea Gate (-0.20) still bypasses on `test.repeat_override_reason`; the suffix is what satisfies `verify_directive_uniqueness_guard` at `run_pipeline.py:505`, which refuses to re-execute a directive_id already in the registry.

Example:

```
Source:        90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E002.txt
                 test.strategy: 90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100   (base, no suffix)
                 test.name:     90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E002
Rerun output:  INBOX/90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E003.txt
                 test.strategy: 90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100   (unchanged)
                 test.name:     90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E003
```

`reset_directive.py` is **not** required for `__E###`-rotated reruns — the new variant has a distinct directive_id, so PORTFOLIO_COMPLETE on the prior variant doesn't block it. The state file is keyed by filename stem, and the stem now differs.
