# Trade_Scan

Research pipeline: directive → backtest → deployable strategy.

**Before doing anything, read `AGENT.md`.** It contains the full failure playbook and all 25 system invariants.

---

## Role

- Runs human-directed backtests against RESEARCH-grade data
- Validates strategies through capital simulation and broker-cost modeling
- Produces `PORTFOLIO_COMPLETE` strategies consumed by TS_Execution
- **No execution authority. No live trading. No automation.**

## Entry Point

```bash
python tools/run_pipeline.py <DIRECTIVE_ID>
```

Place directives in `backtest_directives/INBOX/` before running.

## Pipeline Stages (brief)

| Stage | Tool | Output |
|---|---|---|
| −0.25 → −0.35 | Canonicalization + Governance gates | Validated directive |
| 0 | `exec_preflight.py` | Strategy provisioned to TradeScan_State |
| 0.5 – 0.75 | Semantic + dry-run validation | Hollow/crash check |
| 1 | `run_stage1.py` | Trade results → `TradeScan_State/runs/` |
| 2 – 3 | `stage2/3_compiler.py` | AK reports + Master Filter append |
| 4 | `portfolio_evaluator.py` | Equity curve + portfolio ledger |
| 7 – 10 | Reports + Capital wrapper + Robustness | Deployable artifacts |

## Sibling Repositories

| Repo | Relationship |
|---|---|
| `../TradeScan_State` | **All pipeline output goes here** — runs, backtests, strategies, ledgers |
| `../TS_Execution` | Reads `strategies/` and engine code from this repo for live trading |

## Path Authority

`config/state_paths.py` defines every output path to TradeScan_State. Never hardcode paths elsewhere.

## Key Files

| File | Purpose |
|---|---|
| `AGENT.md` | Failure playbook + invariants — **mandatory first read** |
| `SYSTEM_STATE.md` | Current system health snapshot |
| `RESEARCH_MEMORY.md` | Accumulated research findings + disproven approaches |
| `backtest_directives/INBOX/` | Place directives here to queue |
| `config/state_paths.py` | Authoritative output path definitions |
