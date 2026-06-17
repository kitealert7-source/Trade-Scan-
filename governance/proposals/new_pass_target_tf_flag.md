# Proposal: `new_pass.py --target-tf <TF>` flag

**Status:** AWAITING APPROVAL  
**Priority:** STRATEGIC  
**Invariant 6 gate:** plan + explicit human approval required before any edit to `tools/`  
**Origin:** session-retro 2026-06-17 (F4 — cross-TF clone always leaves `timeframe` attr wrong)

---

## Problem

`tools/new_pass.py` clones `strategy.py` verbatim and only rewrites the `name` attribute.
The `timeframe` class attribute (e.g. `timeframe = "1h"` on ~line 32) is left unchanged.
For any cross-TF clone this is always wrong and always causes `Timeframe Mismatch` at
preflight, requiring a manual hand-edit before `--rehash` can succeed.

Confirmed 2026-06-17: 1H → 30M clone (`27_MR_XAUUSD_30M_PINBAR_S01_V1_P06`); the
`timeframe = "1h"` line was not updated, preflight failed, required hand-edit.

---

## Proposed change

Add an optional `--target-tf <TF>` flag to `new_pass.py`. When supplied, after cloning
`strategy.py`, rewrite the `timeframe = "..."` line to the supplied value before writing
the file. Without the flag, behaviour is unchanged (backwards compatible).

**File to change:** `tools/new_pass.py`

**Approach:**

1. Parse `--target-tf` as an optional argument (e.g. `"30m"`, `"15m"`, `"4h"`).
2. After cloning `strategy.py` content into memory, apply a single regex substitution:
   ```python
   import re
   content = re.sub(
       r'^(\s*timeframe\s*=\s*)["\'].*?["\']',
       rf'\g<1>"{target_tf}"',
       content,
       count=1,
       flags=re.MULTILINE,
   )
   ```
3. Write the substituted content to the new pass file.
4. Log the substitution so the operator sees: `[new_pass] timeframe rewritten: "1h" → "30m"`.

**Hash / sweep-registry side-effects:** none. `--rehash` is still required after scaffolding
(unchanged). The timeframe rewrite happens before `--rehash`, so the hash is computed over
the corrected file.

**No AST required** — `timeframe = "..."` is a simple class attribute assignment on a
single line; the regex is unambiguous within any standard strategy.py layout.

---

## Test case to add

`tests/test_new_pass.py` (or the existing new_pass test file):

```python
def test_target_tf_rewrites_timeframe(tmp_path):
    # scaffold a clone with --target-tf 30m
    # assert strategy.py contains timeframe = "30m"
    # assert original source strategy.py is unchanged
```

---

## Approval checklist (before implementation)

- [ ] Human approval of this plan
- [ ] Confirm no other strategy.py field needs updating for cross-TF clones
- [ ] Confirm regex handles both single and double quote variants
- [ ] Test case reviewed and approved
