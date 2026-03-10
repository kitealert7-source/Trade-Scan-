# Engine Freeze Record — Universal Research Engine v1.5.2

Engine Version: v1.5.2
Freeze Date: 2026-03-10
ENGINE_STATUS: FROZEN

---

## Execution Guarantees

| Guarantee | Detail |
|---|---|
| next_bar_open entry | Signal on bar N → fill at bar N+1 `open` |
| OHLC stop enforcement | SL triggers when bar range touches stop_price (SL priority over TP) |
| Gap-aware fills | Stop/TP outside bar range → fill at `bar_open`, not stop/tp price |
| Centralized exit resolver | `resolve_exit()` handles SL → TP; strategy exits handled by caller |
| Strategy-controlled trade limits | `max_trades_per_session` from `STRATEGY_SIGNATURE.trade_management`; `None` = unlimited |
| Session reset | `session_reset` mode: `utc_day` (default) or `none` |
| Entry diagnostics | `entry_reference_price`, `entry_slippage`, `entry_reason` (optional per trade) |
| Exit diagnostics | `exit_source` (`STOP`/`TP`/`TIME_EXIT`/`SIGNAL_EXIT`), `stop_source` (`STRATEGY`/`ENGINE_FALLBACK`) |

---

## Hardening History

| Version | Change |
|---|---|
| v1.5.0 | `resolve_exit()`, gap-aware fills, next_bar_open model, session guard (1/day hardcoded), exit_source + stop_source |
| v1.5.1 | Trade management generalized: `max_trades_per_session` from `STRATEGY_SIGNATURE`, `session_reset` modes |
| v1.5.2 | Entry diagnostics: optional `entry_reference_price`, `entry_slippage`, `entry_reason` per trade |

---

## Integrity Verification

Self-test tool: `tools/verify_engine_integrity.py` (strict mode)

```bash
python tools/verify_engine_integrity.py --mode strict
```

Expected outcome:
- Hash Verification: 5 engine files match manifest
- Tools Integrity: 12 critical tools match manifest
- Core test: Long and Short executed correctly
- Session limit test: max=2 blocks 3rd signal
- Unlimited session test: all 3 signals execute
- Entry diagnostics test: reference_price, slippage, reason all correct

Engine manifest: `engine_dev/universal_research_engine/v1_4_0/engine_manifest.json`
Root-of-trust: `vault/root_of_trust.json`

---

## Post-Freeze Rule

**The execution layer is locked.**

Any modification to execution behavior MUST:
1. Increment the engine version (e.g., v1.6.0)
2. Pass full integrity verification under the new version
3. Re-run all active strategies to produce new results
4. Create a new freeze record

Research backtests run after this freeze are reproducible against this exact execution model.
