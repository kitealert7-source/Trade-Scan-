import yaml
import subprocess
import argparse
import sys
from pathlib import Path

try:
    from tools.system_logging.pipeline_failure_logger import log_pipeline_failure as _log_failure
except Exception:
    _log_failure = None

SKILLS_ROOT = Path(".skills")


def discover_skills():
    skills = {}
    if not SKILLS_ROOT.exists():
        return skills
        
    for skill_file in SKILLS_ROOT.glob("*/skill.yaml"):
        with open(skill_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        skills[data["name"]] = {
            "config": data,
            "path": skill_file.parent
        }
    return skills


def run_skill(skill_name, **kwargs):
    skills = discover_skills()

    if skill_name not in skills:
        raise ValueError(f"Skill '{skill_name}' not found")

    skill = skills[skill_name]["config"]

    if skill["entrypoint"]["type"] != "python":
        raise ValueError("Only python entrypoints supported")

    script = skill["entrypoint"]["script"]

    args = []
    # Build list of arguments mapping cleanly to the underlying script
    for key in skill.get("inputs", []):
        if key not in kwargs or kwargs[key] is None:
            raise ValueError(f"Missing required input: {key}")
            
        # The underlying script expects pure positional for the directive/strategy, 
        # and --flags for execution parameters
        if key == "strategy":
            args.insert(0, str(kwargs[key]))
        else:
            args.append(f"--{key}")
            args.append(str(kwargs[key]))

    # Use sys.executable (not "python") so the child process uses the same
    # interpreter as the parent — matters in venvs and on Windows where the
    # PATH may resolve "python" to a different install. Matches the convention
    # used elsewhere in the codebase (e.g. filter_strategies.py).
    cmd = [sys.executable, script] + args

    print(f"[SKILL] Executing {skill_name}: {' '.join(cmd)}")

    try:
        # Capture output for crash diagnostics
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Stream stdout explicitly since we captured it
        if result.stdout:
            sys.stdout.write(result.stdout)
            
        # Anti-masking diagnostics: persist a self-contained crash bundle whenever the
        # worker looks failed OR empty -- non-zero exit, OR (for a run_id run) no run dir
        # / no data dir / no trade log. Previously only a non-zero exit wrote a crash log,
        # so an exit-0-but-empty worker (the governed NO_TRADES false-negative) left no
        # trace at all. Bundle = crash_trace.log + worker_stdout/stderr/command.txt so the
        # next failure is self-contained without re-running.
        _rid = kwargs.get("run_id")
        if _rid:
            from config.state_paths import RUNS_DIR
            run_dir = RUNS_DIR / str(_rid)
            data_dir = run_dir / "data"
            trade_log = data_dir / "results_tradelevel.csv"
            failed_or_empty = (
                result.returncode != 0
                or not run_dir.exists()
                or not data_dir.exists()
                or not trade_log.exists()
            )
            if failed_or_empty and run_dir.exists():
                from datetime import datetime, timezone
                cmd_str = " ".join(cmd)
                (run_dir / "worker_command.txt").write_text(cmd_str + "\n", encoding="utf-8")
                (run_dir / "worker_stdout.log").write_text(result.stdout or "", encoding="utf-8")
                (run_dir / "worker_stderr.log").write_text(result.stderr or "", encoding="utf-8")
                with open(run_dir / "crash_trace.log", "w", encoding="utf-8") as f:
                    f.write(f"[{datetime.now(timezone.utc).isoformat()}] WORKER FAILED-OR-EMPTY\n")
                    f.write(f"Command: {cmd_str}\n")
                    f.write(f"Exit Code: {result.returncode}\n")
                    f.write(f"run_dir={run_dir.exists()} data_dir={data_dir.exists()} "
                            f"trade_log={trade_log.exists()}\n")
                    f.write("-" * 80 + "\nSTDOUT:\n" + (result.stdout or "") + "\n")
                    f.write("-" * 80 + "\nSTDERR:\n" + (result.stderr or "") + "\n")
                print(f"[DIAG] Worker failed-or-empty for run {_rid} -- self-contained "
                      f"diagnostics in {run_dir} (crash_trace.log + worker_stdout/stderr/command).")

        if result.returncode != 0:

            # Centralized failure log
            if _log_failure:
                _log_failure(
                    directive_id=str(kwargs.get("strategy", "UNKNOWN")),
                    run_id=str(kwargs.get("run_id")) if kwargs.get("run_id") else None,
                    stage="SYMBOL_EXECUTION",
                    error_type="ENGINE_CRASH",
                    message=f"Exit code {result.returncode}: {(result.stderr or result.stdout or '').strip()[:300]}",
                )

            # Print stderr to console so it's still visible
            if result.stderr:
                sys.stderr.write(result.stderr)

            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
    except Exception as e:
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help"]:
        print("Usage: python tools/skill_loader.py <skill_name> [args]")
        print("\nAvailable skills:")
        skills = discover_skills()
        for s_name, s_data in skills.items():
            print(f"  {s_name}: {s_data['config'].get('description', '').splitlines()[0] if s_data['config'].get('description') else ''}")
        sys.exit(1)

    skill_name = sys.argv[1]
    skills = discover_skills()
    
    if skill_name not in skills:
        print(f"Error: Skill '{skill_name}' not found")
        sys.exit(1)
        
    skill_config = skills[skill_name]["config"]
    
    # Dynamically build parser based on skill inputs
    parser = argparse.ArgumentParser(
        prog=f"python tools/skill_loader.py {skill_name}",
        description=skill_config.get("description", "")
    )
    
    # We already consumed sys.argv[1] manually, so we don't add parameter for skill_name
    for input_name in skill_config.get("inputs", []):
        parser.add_argument(f"--{input_name}", required=True, help=f"Skill input: {input_name}")
        
    # Parse remaining arguments
    args = parser.parse_args(sys.argv[2:])
    
    # Convert args namespace to dict and run
    kwargs = vars(args)
    run_skill(skill_name, **kwargs)
