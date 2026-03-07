import yaml
import subprocess
import argparse
import sys
from pathlib import Path

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

    subprocess.run(cmd, check=True)


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
