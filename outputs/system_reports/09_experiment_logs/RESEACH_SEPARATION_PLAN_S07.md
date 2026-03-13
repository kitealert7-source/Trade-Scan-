# Finalizing Research Separation & Trial Run

This plan aligns the orchestration layer with the new `STATE_ROOT` infrastructure and establishes a protocol for manual strategy approval before final verification.

## User Review Required

> [!IMPORTANT]
> **Strategy Approval Protocol**: Per your request, please review and approve the minimal logic implemented for the `01_MR_FX_1H_ULTC_REGFILT_S07_V1_P00` trial run. This logic is a placeholder designed to fire signals for verification purposes.

### Proposed Strategy Logic (`strategies/01_MR_FX_1H_ULTC_REGFILT_S07_V1_P00/strategy.py`)

```python
    def prepare_indicators(self, df):
        df['atr'] = atr(df, window=14)
        df['volatility_regime'] = volatility_regime(df['atr'], window=100)['regime']
        
        uc = ultimate_c_percent(df)
        df['ultimate_c_percent'] = uc['ultimate_c']
        df['ultimate_signal'] = uc['ultimate_signal']
        
        return df

    def check_entry(self, ctx):
        if not self.filter_stack.allow_trade(ctx):
            return None
        
        row = ctx.row
        # Minimal mean-reversion logic using Ultimate C
        if row.get('ultimate_c_percent', 50) > 80:
             return {"signal": -1}
        if row.get('ultimate_c_percent', 50) < 20:
             return {"signal": 1}
             
        return None
```

## Proposed Changes

### Orchestration Layer

#### [MODIFY] [stage_symbol_execution.py](file:///c:/Users/faraw/Documents/Trade_Scan/tools/orchestration/stage_symbol_execution.py)

Redirect all Stage-1/2/3 artifact checks and outputs to the external `TradeScan_State` hierarchy.

- Redirect `summary_csv` to `SANDBOX_DIR`.
- Redirect Stage-1 artifact check to `RUNS_DIR / rid / "data"`.
- Redirect Stage-2 artifact check to `RUNS_DIR / rid / "data"`.
- Use `MASTER_FILTER_PATH` for Stage-3 validation.

## Verification Plan

### Automated Verification
1.  **State Reset**: Deep purge of `TradeScan_State`.
2.  **Trial Execution**: `python tools/run_pipeline.py 01_MR_FX_1H_ULTC_REGFILT_S07_V1_P00.txt`.
3.  **Boundary Check**: Confirm log: `[ORCHESTRATOR] Candidate generation complete. Pipeline stopping at research boundary.`
4.  **Artifact Audit**:
    - `TradeScan_State/runs/<run_id>/data/results_tradelevel.csv` (Verified exist)
    - `TradeScan_State/sandbox/Strategy_Master_Filter.xlsx` (Verified exist)
    - `TradeScan_State/candidates/Filtered_Strategies_Passed.xlsx` (Verified exist)
