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

## Per-symbol ledger names (canonical-stem derivation)

The `master_filter` ledger stores **per-symbol** runs with an appended `_<SYMBOL>` suffix (e.g. `69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00_SPX500`), and a rerun-of-a-rerun target can carry an embedded `__E###` too — sometimes both, in either order. `prepare` must **not** rotate on that ledger handle directly: a stem like `..._P00__E001_SPX500` is non-parseable (→ `classifier_gate` matches on an empty model token and cross-diffs an unrelated family → phantom SIGNAL) and rotation doubles the suffix (`..._SPX500__E001` → `NAMESPACE_IDENTITY_MISMATCH` at Stage -0.30).

So `prepare` derives a **canonical base stem** before rotating:

1. Prefer the source capsule's own `test.strategy` (the immutable namespace base anchor).
2. Otherwise peel trailing `__E###` and `_<TOKEN>` chunks until `parse_strategy_name` accepts the remainder with an **empty** `symbol_suffix`.
3. Basket / non-conforming ids (never namespace-structured) pass through unchanged (trailing `__E###` stripped only).

The derivation is **idempotent** — `canonical(canonical(x)) == canonical(x)` — which is the guard against future suffix explosions. All per-symbol clones of one class-token idea reduce to the same base stem and therefore **share** one `__E###` sequence.

```
Ledger target: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00_SPX500   (per-symbol row)
Canonical stem: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00          (peels _SPX500)
Rerun output:  INBOX/69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00__E001.txt
                 test.strategy: 69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00
                 test.name:     69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00__E001
```

(Fix + regression tests landed 2026-07-02 — see the Friction log.)
