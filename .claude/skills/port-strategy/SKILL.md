---
name: port-strategy
description: Build a new strategy.py + directive (incl. Pine→Trade_Scan ports) without rediscovering build-time gotchas
---

## When to use

Read this skill **before** writing any new `strategies/<id>/strategy.py` or `backtest_directives/INBOX/<id>.txt`. It covers the build phase. Once the directive is admitted, hand off to **execute-directives** for the Golden Path.

This is a complement to `execute-directives`, not a replacement. `execute-directives` covers what happens after `run_pipeline.py` is invoked. This skill covers what must be true *for that invocation to succeed*.

---

## Where to work (read first)

- **Worktrees are first-class for both code edits AND pipeline runs** as of commit `2c316e3` (2026-05-08). `governance/preflight.py` now resolves `PROJECT_ROOT` via `config.path_authority.REAL_REPO_ROOT`, so DATA_GATE finds `data_root/` on the real repo regardless of where the script is invoked from. Run `python tools/run_pipeline.py <ID>` from your worktree directly — no mirror dance needed.
- **Main repo is also fine** — choose based on whether you want git isolation for the work, not based on what the work is.
- **NEVER `mklink /J`** to bridge `data_root/` into a worktree. Hard prohibition (see CLAUDE.md → 2026-05-07 incident). The path_authority patch removes any reason you'd want one.

If you discover any other tool deriving root from `Path(__file__).parent.parent` and breaking under a worktree, the fix pattern is one line: `from config.path_authority import REAL_REPO_ROOT as PROJECT_ROOT`. Don't add a junction; patch the offender.

---

## Pre-build checklist (run before writing anything)

1. **Token validation.** Read `governance/namespace/token_dictionary.yaml` and confirm:
   - `family` token exists in the `family:` list
   - `model` token exists in the `model:` list (no guessing — common wrong guess: `VOLEXPAND` ≠ valid; correct is `VOLEXP`)
   - `class` token exists in `class:` list
   - If not found, check `aliases.model` before stopping.

2. **Idea entry.** If `idea_id` is new, append a block to `governance/namespace/idea_registry.yaml`:
   ```yaml
     '66':
       family: BRK
       title: "<short description>"
       class: structure_logic
       regime: trend
       role: entry_edge
       instruments: XAUUSD
       status: active
   ```

3. **Sweep registry stub.** `new_pass.py --rehash` cannot bootstrap a brand-new idea. Manually add a stub block to `governance/namespace/sweep_registry.yaml` *before* running `new_pass.py`:
   ```yaml
     '66':
       next_sweep: 2
       sweeps:
         S01:
           directive_name: <DIRECTIVE_ID>
           signature_hash: '0000000000000000'
           signature_hash_full: '0000000000000000000000000000000000000000000000000000000000000000'
           reserved_at_utc: '<UTC_TIMESTAMP>'
           patches: {}
   ```
   Use `'0000000000000000'` (16 hex zeros) — NOT the literal word `placeholder`. `new_pass.py --rehash` rewrites the real hash later.

4. **Date range.** Check the latest available bar for the symbol/timeframe in `data_root/MASTER_DATA/<SYMBOL>_OCTAFX_MASTER/RESEARCH/`. The `start_date` must be **strictly less** than the first available bar's timestamp — DATA_GATE compares timestamps, not dates. If the first bar lands at `2025-08-21T08:00:00`, `start_date: "2025-08-21"` (which normalizes to midnight) FAILS. Use `start_date: "2025-08-22"` (or earlier than 2025-08-21 if data goes that far back). The error to watch for: `missing start: 2025-08-21 -> 2025-08-21`.

5. **Indicator separation.** Any indicator logic must live in `indicators/<category>/<name>.py` as an importable module. Inline computation inside `prepare_indicators` is rejected by Stage-0.5 Inline Indicator Detection. If the indicator doesn't exist yet, write it under `indicators/` first.

---

## strategy.py contract (mandatory invariants)

1. **`atr` is required.** Every strategy must add `df["atr"] = atr(df, 14)` in `prepare_indicators` even if the strategy logic doesn't use it. The engine pulls `ctx.require('atr')` for trade metadata at every fill — missing it crashes Stage 1 with `AUTHORITATIVE_INDICATOR_MISSING: 'atr'`. Standard pattern:
   ```python
   from indicators.volatility.atr import atr
   ...
   def prepare_indicators(self, df):
       # ... your indicators ...
       df["atr"] = atr(df, 14)
       return df
   ```
   Add `"indicators.volatility.atr"` to both the STRATEGY_SIGNATURE `indicators` list AND the directive's `indicators:` list.

2. **STRATEGY_SIGNATURE `indicators` list ≡ directive `indicators:` list** (exact match). The semantic validator (Stage-0.5) compares the two — any drift fails admission.

3. **`repeat_override_reason` lives in the directive only.** Put it under the directive's `test:` block. **Do NOT put it inside `STRATEGY_SIGNATURE`** — the semantic validator will reject the mismatch.

4. **Hash auto-managed.** Don't hand-edit `# --- SIGNATURE HASH: ... ---`. `new_pass.py --rehash` (or the auto-consistency gate) writes it. Manual edits create drift.

5. **REQUIRED_CAPABILITIES + REQUIRED_CONTRACT_IDS.** Module-level lists at the bottom of strategy.py — copy from a recent strategy of the same family.

6. **Stop-contract awareness (Pine ports especially).** If you compute `stop_price` and `tp_price` inside `check_entry` from the signal-bar close, and execution_timing is `next_bar_open`, expect the Stage-0.56 Stop Contract Guard to print **WARN**. That's expected for ports of Pine strategies that approximate next-open with close. To make it disappear, return only `signal` from `check_entry` and let the engine compute SL/TP from the actual fill price using the directive's ATR multiplier — but that *changes the strategy semantics*, so prefer WARN over silent edge drift.

---

## Directive contract

- `test.name`, `test.strategy`, and the directive filename stem must all be the namespaced ID.
- `start_date` / `end_date` quoted strings (`"2025-08-22"`).
- `indicators:` list must match strategy.py's STRATEGY_SIGNATURE indicators.
- For 1D timeframes: add `session_reset: none` under `trade_management` (default `utc_day` clears pending entries → 0 trades).
- For Pine ports with broker translation: include OctaFX-specific risks in `notes:` (cross-broker tick divergence, lot-size convention).

---

## Bootstrap dance (canonical order)

```bash
# 0. (one-time) idea_registry.yaml + sweep_registry.yaml stub edited manually
# 1. Write strategies/<ID>/strategy.py
# 2. Write backtest_directives/INBOX/<ID>.txt

# 3. Hash + approve
python tools/new_pass.py --rehash <DIRECTIVE_ID>
# This: computes directive hash, writes signature hash into strategy.py,
# writes strategy.py.approved marker, regenerates tools_manifest.json,
# moves directive INBOX → INBOX (or restores from completed/ if needed)

# 4. Run
python tools/run_pipeline.py <DIRECTIVE_ID>     # invoke from main repo OR worktree (post-2c316e3)
```

---

## Recovery from a failed run

A failed pipeline run leaves debris. Clean it before retry:

1. **Orphan strategy dir in TradeScan_State.** A failed run creates `TradeScan_State/strategies/<ID>/` with only `engine_resolution.json` (no `strategy.py`, no `deployable/`, no `portfolio_evaluation/`). The startup guardrail flags this as `Untracked directory`. Delete it:
   ```powershell
   Remove-Item -Recurse -Force "C:\Users\faraw\Documents\TradeScan_State\strategies\<ID>"
   ```
   The next pipeline run recreates it from scratch.

2. **Directive state.** `reset_directive.py <ID> --reason "<why>"` clears FAILED → INITIALIZED. But this is **blocked** if `strategy.py` mtime is newer than `strategy.py.approved` mtime ("logic change after approval"). Two options:
   - If the change is genuinely a fix (e.g. adding mandatory `atr`): run `new_pass.py --rehash` instead — it auto-restores the directive from `completed/` to INBOX, cleans stale state, updates the approved marker, and is safe to re-run the pipeline immediately. No `reset_directive.py` needed.
   - If the change is a logic change: don't reset — create a new V2 directive.

3. **Old INBOX leftovers.** If the directive is still in `INBOX/` from a prior partial run, `new_pass.py --rehash` handles it. If you see "directive not found", check `INBOX_backup/`, `active/`, `active_backup/`, `completed/`.

---

## Quality-gate calibration (what to expect)

After Stage-4, the strategy is FAIL/WATCH/CORE per `Master_Portfolio_Sheet.xlsx`. Headline thresholds:

| Gate | FAIL trigger | WATCH floor | CORE floor |
|---|---|---|---|
| Trades | < 50 | ≥ 50 | ≥ 200 |
| Net PnL | ≤ 0 | > 0 | > 1000 |
| SQN (single-asset) | < 2.0 | ≥ 2.0 | ≥ 2.5 |
| Edge quality (portfolio) | < 0.08 | ≥ 0.08 | ≥ 0.12 |
| Trade density | < 50 | ≥ 50 | — |

A profitable strategy can still FAIL on quality. Common P00 misses:
- SQN < 2.0 (most common — Pine ports often land here).
- Top-5 trade concentration > 50% (tail-dependent).
- Longest flat period > 60 days (regime-conditional edge).
- Single-year sub-period PF < 1.0 inside an overall PF > 1.10 strategy.

P01+ should target the largest single weak cell from the report's `Edge Decomposition`, not stack filters. See `feedback_promote_quality_gate.md` and `feedback_decomposition_workflow.md` in memory.

---

## Pine port specifics

- **WR is the most reliable port-equivalence check** (broker-data-invariant). PnL and trade count diverge across brokers (OctaFX vs OANDA tick streams differ).
- **Trade count typically 20–30% lower on OctaFX** vs OANDA for the same logic on XAUUSD 5m — different tick streams, different intra-bar resolution.
- **Stop-contract WARN is expected** for ports that compute SL/TP from signal-bar close (next-bar-open fills). Don't try to "fix" it without understanding the trade-off — the alternative (engine ATR-multiple SL) changes the strategy.
- **Gap-safeguard is mandatory** for breakout-class ports. Without `risk <= 0 → return None` in `check_entry`, gap bars produce stops on the wrong side of entry → STOP CONTRACT VIOLATION at Stage-1.

---

## Failure-mode quick lookup

| Symptom | Cause | Fix |
|---|---|---|
| `AUTHORITATIVE_INDICATOR_MISSING: 'atr'` | strategy.py doesn't add `df["atr"]` | Add ATR import + `df["atr"] = atr(df, 14)` |
| `DATA_RANGE_INSUFFICIENT` with `missing start: <date> -> <date>` | start_date timestamp issue | Use start_date strictly before first available bar |
| `Untracked directory: <ID>` from startup guardrail | Orphan TradeScan_State dir from failed run | `Remove-Item` the orphan dir |
| `EXPERIMENT_DISCIPLINE` reset blocked | strategy.py mtime > approved marker mtime | Use `new_pass.py --rehash` instead of `reset_directive.py` |
| `Indicator Set Match` fails Stage-0.5 | Directive `indicators:` ≠ STRATEGY_SIGNATURE `indicators` | Sync both lists |
| `SWEEP_IDEA_UNREGISTERED` | New idea not in sweep_registry.yaml | Add stub block manually before `new_pass.py --rehash` |
| Stage-0.5 semantic mismatch on `repeat_override_reason` | Field present in STRATEGY_SIGNATURE | Remove from strategy.py — directive `test:` block only |

---

## Cross-references

- **Run-phase workflow:** `.claude/skills/execute-directives/SKILL.md`
- **Re-run / refresh:** `.claude/skills/rerun-backtest/SKILL.md`
- **Pre-promote quality:** `feedback_promote_quality_gate.md` (memory)
- **Post-P00 next-step logic:** `feedback_decomposition_workflow.md` (memory)
- **Path/encoding rules:** project `CLAUDE.md` "Path & Encoding Rules" section
- **Worktree hard prohibition:** project `CLAUDE.md` "Worktree & Junction Safety" section
