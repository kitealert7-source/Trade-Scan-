"""indicator_imports.py — enumerate the `indicators.*` modules a strategy
(or basket recycle rule) imports, transitively.

Single source of truth for the question *"which indicator modules does this
.py depend on?"*. Used by `tools/run_indicator_snapshot.py` to capture every
indicator module whose code participates in a backtest, so a run is faithfully
reproducible even after the live `indicators/` registry evolves.

Design notes
------------
* **AST / text based — never imports the target.** Works on archived snapshot
  files that may not be importable under the current environment, and on basket
  recycle rules (which are not `Strategy` classes).
* **Resolution convention** matches `tools/strategy_provisioner._generate_import_lines`
  and `tools/semantic_validator.py`: an indicator import names the FULL dotted
  module path, e.g. ``from indicators.volatility.atr import atr``. We also
  tolerate ``from indicators.volatility import atr`` (submodule via package) and
  ``import indicators.volatility.atr``. A candidate is kept only if it resolves
  to a real ``.py`` file under ``project_root`` — so package imports like
  ``indicators.volatility`` (a directory) are skipped, and ``__init__.py``
  re-export machinery is never pulled in.
* **Transitive.** After scanning the entry file, each discovered indicator file
  is itself scanned for further ``indicators.*`` imports (e.g.
  ``atr_percentile`` -> ``atr``), so the full set of indicator code that runs is
  captured, not just the strategy's direct imports.
* **Relative imports (``from .x import y``) are ignored** — within the
  ``indicators/`` tree they appear only in ``__init__.py`` package re-exports
  (verified 2026-06-29), which this scanner never visits because packages don't
  resolve to a ``.py`` file. Leaf indicator modules use absolute paths for their
  cross-indicator dependencies.
"""
from __future__ import annotations

import ast
from pathlib import Path

INDICATOR_PREFIX = "indicators"

__all__ = ["extract_imported_indicator_modules", "module_to_file"]


def module_to_file(module: str, project_root) -> Path | None:
    """Resolve a dotted ``indicators.*`` module to its ``.py`` file, or None.

    Returns None when the dotted path does not point at an on-disk file (e.g. it
    names a package directory, or the module does not exist) — the caller treats
    "resolves to a real file" as the membership test.
    """
    if not module or not (
        module == INDICATOR_PREFIX or module.startswith(INDICATOR_PREFIX + ".")
    ):
        return None
    rel = Path(*module.split(".")).with_suffix(".py")
    candidate = Path(project_root) / rel
    return candidate if candidate.is_file() else None


def _candidates_from_source(source: str) -> set[str]:
    """Return candidate dotted module strings referenced by ``indicators.*``
    imports in one source file. Candidates are not yet resolved to files.
    """
    candidates: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A snapshot that can't be parsed yields no candidates rather than
        # crashing the caller; the snapshot writer surfaces an empty manifest.
        return candidates

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Skip relative imports (level > 0) — see module docstring.
            if getattr(node, "level", 0):
                continue
            mod = node.module or ""
            if mod == INDICATOR_PREFIX or mod.startswith(INDICATOR_PREFIX + "."):
                # `from indicators.x.y import z` -> module is indicators.x.y
                # `from indicators.x import y`    -> y may be submodule indicators.x.y
                candidates.add(mod)
                for alias in node.names:
                    candidates.add(f"{mod}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == INDICATOR_PREFIX or name.startswith(INDICATOR_PREFIX + "."):
                    candidates.add(name)
    return candidates


def extract_imported_indicator_modules(source_file, project_root) -> set[str]:
    """Enumerate the ``indicators.*`` modules imported by ``source_file``,
    transitively.

    Parameters
    ----------
    source_file : str | Path
        Path to the ``.py`` whose indicator dependencies we want (a strategy's
        ``strategy.py`` or a basket recycle rule).
    project_root : str | Path
        Repo root used to resolve dotted module paths to files. Pass the SAME
        root the run imports indicators from, so the captured set matches what
        actually executed.

    Returns
    -------
    set[str]
        Dotted module paths (e.g. ``"indicators.volatility.atr"``) that resolve
        to a real ``.py`` file under ``project_root``. Empty if the file is
        missing/unparseable or imports no indicators.
    """
    source_file = Path(source_file)
    project_root = Path(project_root)
    if not source_file.is_file():
        return set()

    resolved: set[str] = set()
    scanned_files: set[Path] = set()

    pending: list[str] = [source_file.read_text(encoding="utf-8")]
    scanned_files.add(source_file.resolve())

    while pending:
        src = pending.pop()
        for cand in _candidates_from_source(src):
            if cand in resolved:
                continue
            mod_file = module_to_file(cand, project_root)
            if mod_file is None:
                continue  # package dir or non-existent — not a captured module
            resolved.add(cand)
            rf = mod_file.resolve()
            if rf not in scanned_files:
                scanned_files.add(rf)
                pending.append(mod_file.read_text(encoding="utf-8"))

    return resolved
