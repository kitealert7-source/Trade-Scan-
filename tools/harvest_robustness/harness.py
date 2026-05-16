"""Harvest Robustness Harness — orchestrator.

Reads sections.yaml, runs each section's script via subprocess (scripts
live under tools/harvest_robustness/modules/), captures stdout/stderr, and
collates into one markdown report. The harness is self-contained — no
runtime dependency on tmp/.

Future plug-in module support: a section can declare `kind: python_callable`
plus `module:` and `function:` instead of `script:`. The harness will
import the module and call the function, expecting it to return a string.
Not implemented in MVP — only stdout_capture is supported.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from tools.harvest_robustness import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECTIONS_YAML = Path(__file__).resolve().parent / "sections.yaml"


def load_sections(yaml_path: Path = SECTIONS_YAML) -> list[dict[str, Any]]:
    """Load section config from yaml. Returns list of section dicts in order."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return data.get("sections", [])


def filter_sections(sections: list[dict], ids: list[str] | None, tags: list[str] | None) -> list[dict]:
    """Filter sections by --sections (id whitelist) or --tags (tag whitelist).
    Both None = include all."""
    if not ids and not tags:
        return sections
    out = []
    for s in sections:
        if ids and s.get("id") in ids:
            out.append(s)
        elif tags and any(t in s.get("tags", []) for t in tags):
            out.append(s)
    return out


def run_stdout_capture(script_relpath: str, project_root: Path) -> tuple[str, str, int, float]:
    """Run script via subprocess from project root. Returns (stdout, stderr, exitcode, elapsed_s)."""
    script_path = project_root / script_relpath
    if not script_path.exists():
        return ("", f"[harness] ERROR: script not found at {script_path}", 127, 0.0)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # 10 min per section
        )
        elapsed = time.time() - t0
        return (result.stdout, result.stderr, result.returncode, elapsed)
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return ("", f"[harness] TIMEOUT after {elapsed:.0f}s", 124, elapsed)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        return ("", f"[harness] EXCEPTION: {exc}", 1, elapsed)


def render_section(section: dict, stdout: str, stderr: str, exitcode: int, elapsed_s: float) -> str:
    """Render one section as markdown."""
    title = section.get("title", section.get("id", "(untitled)"))
    description = section.get("description", "").strip()
    script = section.get("script", "(no script)")
    tags = section.get("tags", [])
    status_emoji = "OK" if exitcode == 0 else "FAIL"
    out = [
        f"## {title}",
        "",
        f"*{description}*" if description else "",
        "",
        f"`script: {script}` | exit={exitcode} | runtime={elapsed_s:.1f}s | status={status_emoji} | tags=[{', '.join(tags)}]",
        "",
    ]
    if stdout.strip():
        out.append("```")
        out.append(stdout.rstrip())
        out.append("```")
        out.append("")
    if stderr.strip():
        out.append("**stderr:**")
        out.append("```")
        out.append(stderr.rstrip())
        out.append("```")
        out.append("")
    out.append("")
    return "\n".join(out)


def run_harness(
    sections_subset: list[str] | None = None,
    tags_subset: list[str] | None = None,
    output_dir: Path | None = None,
    label: str = "default",
) -> Path:
    """Run all (or filtered) sections, write consolidated report. Returns report path."""
    sections = load_sections()
    if sections_subset or tags_subset:
        sections = filter_sections(sections, sections_subset, tags_subset)
    if not sections:
        raise SystemExit("No sections to run after filtering.")

    timestamp = datetime.now()
    output_dir = output_dir or (PROJECT_ROOT / "outputs" / "harvest_robustness")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"REPORT_{label}_{timestamp.strftime('%Y%m%d_%H%M%S')}.md"

    header = [
        f"# HARVEST ROBUSTNESS REPORT — {label}",
        "",
        f"Engine: Harvest Robustness Harness v{__version__}  |  Generated: {timestamp.isoformat(timespec='seconds')}",
        "",
        f"Sections run: {len(sections)}  |  Source config: `tools/harvest_robustness/sections.yaml`",
        "",
        "This report is produced by the harvest robustness harness, which orchestrates",
        "analysis scripts from `tools/harvest_robustness/modules/` and collates their",
        "stdout into one document. Each section below was generated by an independent",
        "script — see the `script:` line in each section header for the source. Update",
        "sections by editing the named script directly; add new sections by appending",
        "to `sections.yaml`.",
        "",
        "---",
        "",
    ]

    parts = ["\n".join(header)]
    print(f"[harness] running {len(sections)} section(s) -> {report_path}")
    for i, section in enumerate(sections, 1):
        kind = section.get("kind", "stdout_capture")
        sid = section.get("id", f"sec_{i}")
        print(f"[harness] [{i}/{len(sections)}] {sid} ({kind})...", flush=True)
        if kind == "stdout_capture":
            stdout, stderr, exitcode, elapsed = run_stdout_capture(
                section["script"], PROJECT_ROOT
            )
        else:
            stdout, stderr, exitcode, elapsed = (
                "",
                f"[harness] unsupported kind: {kind}",
                1,
                0.0,
            )
        parts.append(render_section(section, stdout, stderr, exitcode, elapsed))
        status_str = "ok" if exitcode == 0 else f"FAIL exit={exitcode}"
        print(f"[harness]    -> {status_str} ({elapsed:.1f}s)", flush=True)

    parts.append("---\n\n## Trailer\n")
    parts.append(f"Harness ran {len(sections)} sections; total wall time: ")
    parts.append(f"completed at {datetime.now().isoformat(timespec='seconds')}.")

    report_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"[harness] DONE. report: {report_path}")
    return report_path
