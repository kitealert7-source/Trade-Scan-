#!/usr/bin/env python
"""Invariant #11 enforcement -- Protected Infrastructure approval gate (commit-msg hook).

Blocks a commit that stages files under a protected directory unless the commit
message carries an operator-approval trailer:

    Protected-Infra-Approved: <one-line reason / who approved>

Protected dirs: tools/  engines/  engine_dev/  governance/  .claude/skills/
Exempt (auto-regenerated DATA, not infra logic -- they commit per-phase and gating
them would block routine pipeline runs): tools_manifest.json + the namespace registries.

Honest about what this is: a DELIBERATE-ACKNOWLEDGMENT gate + audit trail, NOT cryptographic
enforcement. An agent generates its own commit, so it could add the trailer without real
approval. The value is (a) catching an *accidental* protected edit at commit time and
(b) recording WHY every protected change was made -- `git log --grep Protected-Infra-Approved`.
See AGENT.md invariant #11 and
outputs/system_reports/04_governance_and_guardrails/INVARIANT_ENFORCEMENT_MAP_2026-07-01.md.

ASCII-only output (Windows cp1252 console safe).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROTECTED_PREFIXES = ("tools/", "engines/", "engine_dev/", "governance/", ".claude/skills/")
EXEMPT = {
    "tools/tools_manifest.json",
    "governance/namespace/sweep_registry.yaml",
    "governance/namespace/idea_registry.yaml",
}
TOKEN_RE = re.compile(r"^\s*Protected-Infra-Approved:\s*\S.*$", re.MULTILINE)


def _staged_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True,
        ).stdout
    except OSError:
        return []  # fail-open: never block a commit on an infrastructure error
    return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def main(argv: list[str]) -> int:
    protected = [
        f for f in _staged_files()
        if f.startswith(PROTECTED_PREFIXES) and f not in EXEMPT
    ]
    if not protected:
        return 0

    msg = ""
    if len(argv) > 1:
        try:
            msg = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            msg = ""

    token = TOKEN_RE.search(msg)
    if token:
        reason = token.group(0).split(":", 1)[1].strip()
        print(f"[protected-infra] OK -- {len(protected)} protected file(s) approved: {reason}")
        return 0

    sys.stderr.write(
        "\n[protected-infra] COMMIT BLOCKED -- Invariant #11 (Protected Infrastructure).\n"
        f"  {len(protected)} staged file(s) under a protected directory:\n"
    )
    for f in protected[:12]:
        sys.stderr.write(f"    - {f}\n")
    if len(protected) > 12:
        sys.stderr.write(f"    ... (+{len(protected) - 12} more)\n")
    sys.stderr.write(
        "\n  Protected infra requires an implementation plan + explicit operator approval.\n"
        "  If the operator approved this change, record it -- add a trailer line to the\n"
        "  commit message and re-commit:\n\n"
        "      Protected-Infra-Approved: <one-line reason / who approved>\n\n"
        "  (audit trail: git log --grep Protected-Infra-Approved)\n\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
