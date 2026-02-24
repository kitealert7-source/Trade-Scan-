# Release Gate Checklist

All listed tests **MUST** pass before merging pipeline changes.

## Required Test Suites

| Test File | Coverage |
|---|---|
| `tests/test_directive_parser.py` | Duplicate key detection, collision detection, nested YAML |
| `tests/test_pipeline_state_machine.py` | FSM forward path, backward rejection, verify_state, initialize reset |
| `tests/test_resume_fsm.py` | Resume backward transition rejection, preflight skip set, directive FSM forward-only |
| `tests/test_resume_artifacts.py` | Summary CSV deletion guard, resume artifact preservation |

## Verification Commands

```bash
python -m unittest tests.test_directive_parser tests.test_pipeline_state_machine tests.test_resume_fsm tests.test_resume_artifacts -v
```

## Pass Criteria

- **All tests pass** (exit code 0)
- **No warnings** in test output (excluding PowerShell stderr redirection)
- **Run IDs unchanged** after any pipeline_utils modification
