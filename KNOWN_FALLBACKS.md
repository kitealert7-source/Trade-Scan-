# KNOWN_FALLBACKS.md

Legacy fallback code paths that are **not authoritative** — superseded by a primary,
read-from-source path but deliberately left in place as a safety net. Each is a
**candidate for deletion after several successful runs** confirm the primary path
covers every case.

| Symbol | File | What it was | Superseded by | Status |
|---|---|---|---|---|
| `_HYPOTHESIS_MAP` | `tools/generate_strategy_card.py` | Hardcoded per-model-token hypothesis prose (SPKFADE, RSIAVG, …) used to fill the card's `## Hypothesis` section. | The directive's own `description:` / `notes:` (read by `_directive_description`, preferred in `_hypothesis`). | **Legacy fallback** — only used when a directive has no notes AND the model token is in the map. Candidate for deletion. |
| `_ENTRY_FALLBACK` | `tools/generate_strategy_card.py` | Hardcoded per-model-token entry/testing-logic prose used in the card's `## Testing Logic` section. | The directive's own notes (`_directive_description`) for Testing Logic; `render_active_logic` for Active Logic. | **Legacy fallback** — same class of hardcoded-template defect that `render_active_logic` retired for Active Logic. Candidate for deletion. |

## Context

On **2026-06-21** the Active-Logic builders in `generate_strategy_card.py` and
`basket_report.py` were unified onto a single hardcoding-free renderer
(`tools/active_logic_renderer.py`, locked by `tests/test_render_active_logic.py`). That
fix removed the `_logic_lines` RSIAVG template that mislabeled every non-RSIAVG strategy
(e.g. IBS shown as `rsi_avg_pullback | RSI(2) avg < 25`).

The two maps above are the **same class of defect** in the card's *Hypothesis* and
*Testing Logic* sections. They were left in place (operator decision) as fallbacks rather
than retired in the same change, to keep that change atomic and scoped. They are now
behind the directive's own notes, so for any directive that carries `notes:` they are
never reached.

## Deletion criteria

Retire each map once several pipeline runs confirm the primary (notes-driven) path
populates Hypothesis/Testing Logic correctly for all live strategy families — i.e. no
directive is silently falling back to invented prose. At that point, delete the map and
its `_hypothesis` / Testing-Logic fallback branch, and replace a missing-notes case with
an explicit `[no hypothesis declared in directive]` marker (honest absence, not invented).
