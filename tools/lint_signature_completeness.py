"""
Lint: every behavior-affecting class-level constant in strategy.py must
appear (by literal value) in STRATEGY_SIGNATURE.

WHY THIS EXISTS
---------------
The strategy signature hash is computed from STRATEGY_SIGNATURE alone. If a
parameter that affects strategy behavior is held in a class constant
(e.g. ``_BE_TRIGGER_R = 1.0``) but NOT mirrored in STRATEGY_SIGNATURE, then
two strategies with different values for that constant will produce
**identical signature hashes** despite behaving differently. The classifier,
sweep registry, and idea gate all key off that hash — collisions corrupt
research conclusions.

Concrete recurrence: idea 66 P00..P03 each shipped with ``_BE_TRIGGER_R``
hidden in the class body. Different values would have produced the same
registry entry. P04 surfaced ``be_trigger_r`` into the signature; this lint
prevents the next omission.

WHAT IS CHECKED
---------------
For each ``Strategy`` class found in a strategy.py:
  - Collect every class-level assignment whose target is a Name matching
    ``_[A-Z][A-Z0-9_]*`` and whose value is a literal int / float / bool /
    str (or simple negation of an int/float).
  - Extract STRATEGY_SIGNATURE (a dict assigned at class level).
  - For every collected constant, require its **value** to appear somewhere
    in the signature — recursive walk of dict values + list elements + tuple
    elements, matched by ``==``. The constant *name* is not required — only
    the value, since that's what the hash captures.

If a constant legitimately should NOT be in the signature (e.g. a fixed
warmup-bar count that's part of the engine contract, not a tunable), append
an inline comment ``# signature-exempt: <reason>``. The reason MUST be
non-empty.

EXIT CODES
----------
  0 — clean
  1 — at least one violation in --check mode
  2 — argparse / IO error

CLI
---
    # Lint specific files
    python tools/lint_signature_completeness.py path/to/strategy.py [more ...]

    # Lint every strategy under strategies/
    python tools/lint_signature_completeness.py --all

    # Baseline survey: never fail, just report
    python tools/lint_signature_completeness.py --all --report

    # Verbose: print exempt constants too
    python tools/lint_signature_completeness.py --all --report -v
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = REPO_ROOT / "strategies"

CONST_NAME_RE = re.compile(r"^_[A-Z][A-Z0-9_]*$")
EXEMPT_RE = re.compile(r"#\s*signature-exempt\s*:\s*(\S.*?)\s*$")


def _is_simple_literal(node: ast.AST) -> bool:
    """Literal int/float/bool/str, or unary-minus of int/float."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, bool, str))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant) and isinstance(
            node.operand.value, (int, float)
        )
    return False


def _literal_value(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -node.operand.value
    raise ValueError(f"Not a simple literal: {ast.dump(node)}")


def _ast_to_python(node: ast.AST):
    """Recursively convert a literal-ish AST node to Python for value matching.

    Handles dicts, lists, tuples, sets, simple literals. Returns a sentinel
    object for anything else (so it never matches).
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        try:
            return -_ast_to_python(node.operand)
        except Exception:
            return _Unmatchable
    if isinstance(node, ast.Dict):
        return {
            _ast_to_python(k): _ast_to_python(v)
            for k, v in zip(node.keys, node.values)
        }
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ast_to_python(e) for e in node.elts]
    if isinstance(node, ast.Set):
        return {_ast_to_python(e) for e in node.elts}
    return _Unmatchable


class _UnmatchableType:
    def __repr__(self):
        return "<unmatchable>"

    def __eq__(self, other):
        return False

    def __hash__(self):
        return 0


_Unmatchable = _UnmatchableType()


def _walk_values(obj):
    """Yield every scalar value found anywhere in a dict/list/tuple/set tree."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_values(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _walk_values(v)
    else:
        yield obj


def _value_in_signature(value, sig: dict) -> bool:
    for v in _walk_values(sig):
        # Strict equality, but with bool/int distinction respected
        if type(v) == type(value) and v == value:
            return True
    return False


def _line_exempt_reason(source_lines: list[str], lineno: int) -> str | None:
    """Return the exempt reason if the line carries `# signature-exempt: <reason>`."""
    if lineno < 1 or lineno > len(source_lines):
        return None
    line = source_lines[lineno - 1]
    m = EXEMPT_RE.search(line)
    if m:
        reason = m.group(1).strip()
        return reason if reason else None
    return None


def _find_strategy_class(tree: ast.AST) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Strategy":
            return node
    return None


def _extract_signature_dict(strategy_class: ast.ClassDef) -> dict | None:
    for node in strategy_class.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STRATEGY_SIGNATURE":
                    py = _ast_to_python(node.value)
                    return py if isinstance(py, dict) else None
    return None


def lint_file(strategy_py: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (violations, exempt) for a single strategy.py.

    violations: list of human-readable violation strings.
    exempt: list of (constant_name, reason) tuples (for verbose mode).
    """
    source = strategy_py.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(strategy_py))
    except SyntaxError as exc:
        return ([f"{strategy_py}: SYNTAX ERROR: {exc}"], [])

    cls = _find_strategy_class(tree)
    if cls is None:
        return ([f"{strategy_py}: NO `Strategy` class found"], [])

    sig = _extract_signature_dict(cls)
    if sig is None:
        return (
            [f"{strategy_py}: STRATEGY_SIGNATURE not found or not a literal dict"],
            [],
        )

    violations: list[str] = []
    exempt: list[tuple[str, str]] = []

    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not CONST_NAME_RE.match(target.id):
            continue
        if not _is_simple_literal(node.value):
            # Skip non-literal class assignments (e.g. computed defaults)
            continue
        value = _literal_value(node.value)
        reason = _line_exempt_reason(source_lines, node.lineno)
        if reason is not None:
            exempt.append((target.id, reason))
            continue
        if _value_in_signature(value, sig):
            continue
        violations.append(
            f"{strategy_py}:{node.lineno}: HIDDEN_CONSTANT "
            f"{target.id} = {value!r} not present in STRATEGY_SIGNATURE. "
            f"Add it to the signature OR mark `# signature-exempt: <reason>`."
        )

    return (violations, exempt)


def _staged_strategy_files() -> list[Path]:
    """Return staged strategies/*/strategy.py paths (for pre-commit use)."""
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return []
    paths: list[Path] = []
    for line in out.splitlines():
        line = line.strip()
        # Match strategies/<id>/strategy.py only — skip auxiliary files
        # under the strategy folder.
        if not line:
            continue
        norm = line.replace("\\", "/")
        if norm.startswith("strategies/") and norm.endswith("/strategy.py"):
            p = REPO_ROOT / norm
            if p.exists():
                paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("paths", nargs="*", help="strategy.py paths to lint")
    p.add_argument("--all", action="store_true", help="Lint every strategies/*/strategy.py")
    p.add_argument(
        "--staged",
        action="store_true",
        help="Lint only staged strategies/*/strategy.py files (for pre-commit hook).",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="Never fail; just print findings (baseline survey mode).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    targets: list[Path] = []
    if args.all:
        targets.extend(sorted(STRATEGIES_DIR.glob("*/strategy.py")))
    if args.staged:
        targets.extend(_staged_strategy_files())
    targets.extend(Path(s) for s in args.paths)

    if not targets:
        if args.staged:
            # Pre-commit with no staged strategy.py: silent success.
            return 0
        p.error("no targets — pass paths or --all or --staged")
        return 2

    total_violations = 0
    total_files_with_violations = 0
    total_exempt = 0
    for path in targets:
        if not path.exists():
            print(f"{path}: NOT FOUND", file=sys.stderr)
            total_violations += 1
            continue
        violations, exempt = lint_file(path)
        total_exempt += len(exempt)
        if violations:
            total_files_with_violations += 1
            total_violations += len(violations)
            for v in violations:
                print(v)
        if args.verbose and exempt:
            for name, reason in exempt:
                print(f"{path}: EXEMPT {name} -- {reason}")

    if args.verbose or args.report:
        print(
            f"\nSummary: {total_violations} violations across "
            f"{total_files_with_violations} files; {total_exempt} exempt; "
            f"{len(targets)} files scanned."
        )

    if args.report:
        return 0
    return 1 if total_violations else 0


if __name__ == "__main__":
    sys.exit(main())
