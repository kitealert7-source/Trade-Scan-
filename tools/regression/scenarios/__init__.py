"""Regression scenarios — one module per layer.

Each module exports:
    def run(tmp_dir: Path, baseline_dir: Path, budget) -> list[Result]

Modules are auto-discovered by `runner.discover_scenarios`. No central
registration. Add a new scenario by dropping a file here + a
`baselines/<scenario_name>/` folder.
"""
