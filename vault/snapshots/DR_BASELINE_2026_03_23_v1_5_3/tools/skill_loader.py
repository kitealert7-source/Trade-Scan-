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
        with open(skill_file, "r") as f:
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

    cmd = ["python", script] + args

    print(f"[SKILL] Executing {skill_name}: {' '.join(cmd)}")

    try:
        # Capture output for crash diagnostics
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Stream stdout explicitly since we captured it
        if result.stdout:
            sys.stdout.write(result.stdout)
            
        if result.returncode != 0:
            # Fix 2: Persist Engine Crash Tracebacks
            if "run_id" in kwargs:
                from config.state_paths import RUNS_DIR
                run_dir = RUNS_DIR / str(kwargs["run_id"])
                if run_dir.exists():
                    from datetime import datetime, timezone
                    crash_log = run_dir / "crash_trace.log"
                    with open(crash_log, "w", encoding="utf-8") as f:
                        f.write(f"[{datetime.now(timezone.utc).isoformat()}] FATAL CRASH\n")
                        f.write(f"Command: {' '.join(cmd)}\n")
                        f.write(f"Exit Code: {result.returncode}\n")
                        f.write("-" * 80 + "\n")
                        f.write("STDOUT:\n")
                        f.write(result.stdout + "\n")
                        f.write("-" * 80 + "\n")
                        f.write("STDERR:\n")
                        f.write(result.stderr + "\n")
                    print(f"[FATAL] Engine crashed. Full traceback saved to: {crash_log}")

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
