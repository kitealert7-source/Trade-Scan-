---
name: format-excel-ledgers
description: Format both FSP (Filtered_Strategies_Passed.xlsx) and MPS (Master_Portfolio_Sheet.xlsx) using format_excel_artifact.py — no arguments needed
---

# /format-excel-ledgers — Excel Ledger Formatter

Applies strict styling, column ordering, number formatting, and filter pre-selection to both pipeline ledger sheets in one pass. No arguments required — paths are resolved from `config.state_paths`.

> **Presentation-layer only.** No data mutation. Safe to run at any time.

> **Invariant #32 — viewing layer only.** The MPS/FSP column set is defined in CODE, not in the workbook. NEVER hand-add a column to the xlsx: `ledger_db.py --export-mps` (and this formatter's regenerate path) rebuild the tabs wholesale from the DB and silently WIPE any manually-added column (the `spans`/`fragment_count` loss, 2026-06-15). To add/change a displayed column, edit the code-defined projections under `tools/portfolio/*_view.py` (e.g. `cointegration_view.py`, `trade_candidates_view.py`), then re-run this skill.

---

## When to Run

- After any pipeline run that appends rows to FSP or MPS
- After `filter_strategies.py`, `reconcile_portfolio_master_sheet.py`, or `portfolio_evaluator.py`
- Whenever either sheet looks unformatted after a write

---

## Step 1: Format FSP (Filtered_Strategies_Passed.xlsx)

// turbo

```bash
python -c "import subprocess,sys; from config.state_paths import CANDIDATE_FILTER_PATH; r=subprocess.run(['python','tools/format_excel_artifact.py','--file',str(CANDIDATE_FILTER_PATH),'--profile','strategy']); sys.exit(r.returncode)"
```

Expected output ends with: `[SUCCESS] Formatting complete.`

What this applies:
- Sort by `return_dd_ratio` descending + auto-rank column
- Column reorder per `STRATEGY_COLUMN_ORDER`
- Number formats (currency, %, float, int) per `FORMAT_MAP`
- Pre-filter: `candidate_status = CORE / LIVE` (FAIL rows hidden)
- Hyperlinks on `strategy` column → `../backtests/<strategy>/`
- Freeze pane at A2, auto-filter on all columns

If this step fails — **STOP**. Do not proceed to MPS.

---

## Step 2: Format MPS (Master_Portfolio_Sheet.xlsx)

// turbo

```bash
python -c "import subprocess,sys; from config.state_paths import STRATEGIES_DIR; mps=STRATEGIES_DIR/'Master_Portfolio_Sheet.xlsx'; r=subprocess.run(['python','tools/format_excel_artifact.py','--file',str(mps),'--profile','portfolio']); sys.exit(r.returncode)"
```

Expected output ends with: `[SUCCESS] Formatting complete.`

What this applies (both `Portfolios` and `Single-Asset Composites` tabs):
- Sort by `return_dd_ratio` descending + auto-rank column
- Column reorder per `PORTFOLIO_COLUMN_ORDER` / `SINGLE_ASSET_COLUMN_ORDER`
- Number formats per `FORMAT_MAP`
- Pre-filter: `portfolio_status = CORE / WATCH` (FAIL rows hidden)
- Hyperlinks on `portfolio_id` column
- Portfolio composition comments on column A
- Freeze pane at B2, auto-filter on all columns
- Notes sheet auto-generated (classification rules + glossary)

If this step fails — report the error. FSP is already formatted; MPS is the only outstanding item.

---

## Step 3: Report

Confirm to the human:

| Sheet | Path | Result |
|-------|------|--------|
| FSP | `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` | SUCCESS / FAILED |
| MPS | `TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx` | SUCCESS / FAILED |

---

## Related Files

| File | Purpose |
|------|---------|
| `tools/format_excel_artifact.py` | The formatter — all styling logic lives here |
| `config/state_paths.py` | Path authority for FSP (`CANDIDATE_FILTER_PATH`) and MPS (`STRATEGIES_DIR`) |
| `tools/filter_strategies.py` | Writes FSP — run formatter after |
| `tools/reconcile_portfolio_master_sheet.py` | Writes MPS — run formatter after |
| `tools/portfolio_evaluator.py` | Writes MPS — run formatter after |
| `tools/portfolio/cointegration_view.py` | Code-defined column projection for the cointegration MPS tab — edit here to add/remove a displayed column (never the xlsx) |
| `tools/portfolio/trade_candidates_view.py` | Code-defined column projection for the trade-candidates tab |

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
