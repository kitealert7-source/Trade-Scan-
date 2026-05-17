# Manual Rerun Lifecycle (fallback)

Use this sequence when `rerun_backtest.py` is unavailable. For the
tool-driven happy path see [`../SKILL.md`](../SKILL.md).

The safe manual sequence for ENGINE or DATA_FRESH reruns:

```
1. EDIT directive (completed/)
   - Add test.repeat_override_reason (≥50 chars, machine-scannable prefix)
   - Update test.end_date to latest available
   - For ENGINE: no other changes needed
   - For SIGNAL: also bump signal_version and remove ENGINE_OWNED indicators

2. RESET directive state (if PORTFOLIO_COMPLETE)
   python tools/reset_directive.py <ID> --reason "<why>"

3. COPY to INBOX
   cp backtest_directives/completed/<ID>.txt backtest_directives/INBOX/

4. TOUCH approved marker (if strategy.py was modified)
   touch strategies/<ID>/strategy.py.approved

5. UPDATE sweep registry (if directive hash changed due to indicator removal)
   Use _write_yaml_atomic directly — do NOT use new_pass.py --rehash for
   patches that already exist (it creates duplicate YAML keys).

6. RUN pipeline
   python tools/run_pipeline.py <STRATEGY_ID>
   - First run may pause at EXPERIMENT_DISCIPLINE if provisioner patches strategy.py
   - If so: touch approved again, then run again (second run bypasses via baseline age)

7. FINALIZE
   - Mark old run_id as superseded in master_filter (is_current=0)
   - Set is_current=1 on new run_id
   - Or use: python tools/rerun_backtest.py finalize --old-run-id <old> --new-run-id <new> --reason "<why>"
```
