"""Test-suite fixtures / config.

Sandbox the intent_injector hook's side-effect writes (logs + state) to a
per-worker temp dir. `.claude/hooks/intent_injector.py` writes four fixed-name
files under its state root — `intent_matches.jsonl`, `last_intent.json`,
`pending_skill_expectations.json`, `violations.jsonl`. The `test_intent_injector_*`
tests spawn the hook (subprocess + in-process) and read those files back. Pointed
at the real repo paths they (a) race when run in parallel — concurrent workers
append to one shared log and the readback finds the wrong record — and (b) pollute
the real operational logs with synthetic test records.

Setting `INTENT_INJECTOR_STATE_ROOT` to a per-worker temp dir gives each xdist
worker its own copy, so those tests are fully isolated (and parallel-safe) and the
real `.claude/logs` + `.claude/state` are never touched by the suite. The hook and
the tests both resolve their state paths from this env var (default = repo root,
so production is unchanged).

`pytest_configure` runs on every worker before collection, so the env var is set
before the hook module is imported (in-process) and before any subprocess spawn.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def pytest_configure(config) -> None:
    # `workerinput` is present only on xdist workers; "main" covers serial runs.
    worker = getattr(config, "workerinput", {}).get("workerid", "main")
    root = Path(tempfile.gettempdir()) / f"ts_intent_state_{worker}_{os.getpid()}"
    os.environ["INTENT_INJECTOR_STATE_ROOT"] = str(root)
