# Related Files

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

| File                           | Location                                         |
|--------------------------------|--------------------------------------------------|
| Artifact snapshot — **look first** | `TradeScan_State/backtests/<directive_name>/` — `DIRECTIVE_SOURCE.txt` + `RECYCLE_RULE_SOURCE.py` (basket) + `raw/` |
| Artifact snapshot — run_id companion | `TradeScan_State/runs/<run_id>/` — `directive.txt` + `strategy.py` \| `basket_code/` + `manifest.json` (sha256) |
| Baseline resolver (`is_current`) | `tools/resolve_baseline.py`                    |
| Rerun tool                     | `tools/rerun_backtest.py`                        |
| Ledger DB + mark_superseded    | `tools/ledger_db.py`                             |
| Idea Gate (Stage -0.20)        | `tools/orchestration/admission_controller.py`   |
| Classifier Gate (Stage -0.21)  | `tools/classifier_gate.py`                      |
| Directive signature schema     | `tools/directive_schema.py`                     |
| Audit log                      | `outputs/logs/rerun_audit.jsonl`                 |
| Overrides audit (Idea Gate)    | `governance/idea_gate_overrides.csv`             |
