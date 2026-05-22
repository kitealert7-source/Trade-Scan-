# SYSTEM_STATE Manual Section Persistence — Audit

**Date:** 2026-05-12
**Trigger:** Today's session-close closing snapshot wiped a Manual section that the operator had added 30 minutes earlier (5 broader-pytest failure notes). The session-close SKILL says "entries here persist". The behavior contradicts the doc.

## Q1. Where is SYSTEM_STATE.md fully regenerated?

**`tools/system_introspection.py`, line 962:**
```python
output_path.write_text(markdown, encoding="utf-8")
```

The script computes `markdown` in `main()` (line 960) from a pure function of system signals — it never reads the existing file. The write is a full overwrite.

`render_markdown` (called at line 960) builds the entire file from scratch, including a static template for the Known Issues section. See lines 919–924:

```python
lines.append("### Manual (deferred TDs, operational context)")
lines.append("<!-- Add tech-debt items, deferred work, and operational caveats here. "
             "Auto-detected entries above regenerate on each run; entries here persist. -->")
if not auto_lines:
    lines.append("- (none)")
lines.append("")
```

That comment — written into the file every run — is the explicit doc/code contradiction: it says "entries here persist" but the surrounding code unconditionally overwrites the file.

## Q2. Where is the Manual section currently destroyed?

Same point — line 962. The destruction is immediate and unconditional. The script makes zero attempt to read the prior file's contents.

The docstring of `collect_known_issues()` (lines 522–523) reinforces the broken contract:

> Manual entries (deferred TDs, operational context) still live in a separate subsection that's preserved across regeneration.

The contract is documented in *two* places (the SKILL and this docstring) but implemented in zero places.

## Q3. Marker / header pattern to reuse?

**Yes — the canonical header is stable:**

```
### Manual (deferred TDs, operational context)
```

Verified in the live file and in the renderer source (line 919). Three-hash heading because Manual is a subsection under `## Known Issues`. The HTML comment immediately below it can serve as a robust opening anchor (it's distinctive enough to grep for):

```
<!-- Add tech-debt items, deferred work, and operational caveats here. Auto-detected entries above regenerate on each run; entries here persist. -->
```

The Manual section is currently always the **last** section in the file — Known Issues is the final `##`-level section in the renderer's section order. So extraction is straightforward: take from the `### Manual` line through end-of-file.

The renderer has no enforcement of "last position" — but reordering would mean changing many lines. The extractor should be defensive anyway: extract from `### Manual` through the next `##`-level heading OR EOF, whichever comes first.

## Fix shape (preferred, per user spec)

Add a small helper that runs BEFORE the `write_text` call:

1. **If the target path doesn't exist** → no Manual to preserve. Regenerate normally with the default template.
2. **If the target file exists with exactly one `### Manual (...)` block** → extract verbatim from the `### Manual` line to the end of that block (next `##` heading or EOF). Inject into the regenerated markdown at the same anchor, replacing the default template.
3. **If the target file exists with two or more `### Manual (...)` blocks** → fail closed. Raise with a clear error: "SYSTEM_STATE.md has N Manual sections (expected 0 or 1). Resolve manually before regenerating."
4. **If the target file exists but has no `### Manual (...)`** → no Manual to preserve. Regenerate normally.

This is a single-purpose preservation pass. It does NOT touch:
- Auto-detected section content
- Any non-Known-Issues section
- Section ordering
- `render_markdown` logic for everything else

The default template (the HTML comment + optional `- (none)` line) still gets emitted when there's nothing to preserve.

## Test cases (Phase 4)

| # | Scenario | Expectation |
|---|---|---|
| 1 | Manual section with custom bullets exists | Survives regen byte-for-byte (from `### Manual` to next `##` / EOF) |
| 2 | No prior SYSTEM_STATE.md file | Regen succeeds with default Manual template (current behavior preserved) |
| 3 | SYSTEM_STATE.md with two `### Manual (...)` blocks | Regen raises with explicit error, does NOT write any output |
| 4 | Snapshot fields (Engine, Pipeline Queue, etc.) | Unchanged by the fix (only Manual section affected) |

## Hard constraints (echoed from user)

- Do not change snapshot content.
- Do not change auto-detected sections.
- Do not reorder existing sections.
- Do not modify session-close logic.
- Manual section is the *only* surface this fix touches.

## Doc impact

`SKILL.md` already says "entries here persist". The code change makes the doc accurate. **No doc edit needed** after the fix.

The docstring at `collect_known_issues:522-523` also already says "preserved across regeneration". Same story — code change makes it accurate.

## Risk

- **Surface is tiny.** ~30 LOC for the extractor + replacement. No interaction with the data-collection code.
- **Failure mode is fail-closed.** If extraction is ambiguous (two Manual blocks), the regen aborts with a clear error rather than silently picking one.
- **Reversibility.** If the fix misbehaves, deleting the extractor function restores prior behavior immediately.

## Where the fix lands

`tools/system_introspection.py` only. Surface area:
- 1 new helper function (~25 LOC): `_preserve_manual_section(target_path, regenerated_markdown) -> str`
- 1 line added to `main()` near line 960–962: call helper between `render_markdown` and `write_text`.

Total: ~30 LOC, single file, no schema or hook changes.
