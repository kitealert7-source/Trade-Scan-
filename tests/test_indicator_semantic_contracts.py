"""Phase 3 - Semantic Contract Enforcement (CI-only, static validation).

Rules (all failures are hard):
  1. Every indicator module REFERENCED by any directive in
     backtest_directives/ (INBOX, active, active_backup, completed, archive)
     must define SIGNAL_PRIMITIVE (non-empty string).
  2. If the module filename contains "choch", it must declare a primitive.
     This is the most drift-prone family and gets explicit coverage.
  3. Declared primitive / implementation consistency:
       - primitive == "pivot_k3" or "structure_gated"
           => module MUST import from indicators.structure.swing_pivots
       - primitive == "rolling_max_proxy"
           => module must NOT import swing_pivots (definitional contrast
              with pivot-based primitives).
  4. PIVOT_SOURCE, when present, must be one of the allowed tokens.
  5. PIVOT_SOURCE consistency:
       - primitive in {"pivot_k3", "structure_gated"} => PIVOT_SOURCE must
         be "swing_pivots_k3" (or other explicit pivot source).
       - primitive == "rolling_max_proxy" => PIVOT_SOURCE must be "none".

NOTE: These checks are intentionally static (AST / text). No runtime hooks,
no pipeline changes, no output-invariant checks.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDICATORS_ROOT = PROJECT_ROOT / "indicators"
DIRECTIVE_ROOTS = [
    PROJECT_ROOT / "backtest_directives" / "INBOX",
    PROJECT_ROOT / "backtest_directives" / "active",
    PROJECT_ROOT / "backtest_directives" / "active_backup",
    PROJECT_ROOT / "backtest_directives" / "completed",
    PROJECT_ROOT / "backtest_directives" / "archive",
]

# Allowed tokens (extend as new primitives are introduced).
_ALLOWED_PRIMITIVES = {
    "rolling_max_proxy",
    "pivot_k3",
    "structure_gated",
    "rolling_max", "rolling_min",
    "rolling_range_mean",
    "rsi_threshold", "rsi_extreme_band",
    "zscore_synthetic",
    "wilder_rma_tr",
    "atr_rolling_percentile", "atr_percentile_regime",
    "kaufman_efficiency_ratio",
    "kalman_filter_slope",
    "linear_regression_slope", "linear_regression_slope_htf",
    "trend_persistence_count",
    "session_range_breakout",
    # --- TD-003 (2026-05-05): legacy indicators brought under contract ---
    # Already declared by indicator authors; allowlist was the gap.
    "macd_multidim",                  # MACD line + signal + histogram
    "rsi_smoothed_threshold",         # smoothed RSI with threshold gate
    "adx_wilder_trend_strength",      # Wilder's ADX trend-strength scalar
    "ema_cross",                      # EMA fast/slow cross
    "gma_slope_flip",                 # Gaussian MA slope sign-flip
    "hurst_rs_persistence",           # Hurst R/S persistence regime
    "wilder_rma_tr_floored",          # ATR with absolute floor (dollar / pip)
    "bar_hl_range",                   # high − low per-bar range
    # --- Newly added to legacy indicators in TD-003 ---
    "momentum_roc",                   # rate-of-change percent
    "adx_trend_strength",             # non-Wilder ADX (sibling of adx_wilder)
    "hull_moving_average",            # HMA value
    "close_sign_run",                 # bar_sign + signed run-length
    "consecutive_close_streak",       # strict-inequality consecutive close streak
    "prev_bar_breakout",              # close vs previous bar high/low
    "rolling_zscore",                 # rolling z-score (generic, distinct from synthetic)
}
_ALLOWED_PIVOT_SOURCES = {"none", "swing_pivots_k3"}
_PIVOT_PRIMITIVES = {"pivot_k3", "structure_gated"}


def _referenced_indicator_modules() -> set[str]:
    """Scan every directive .txt under DIRECTIVE_ROOTS, return the set of
    dotted indicator module paths referenced via `indicators:` lists."""
    mods: set[str] = set()
    for root in DIRECTIVE_ROOTS:
        if not root.exists():
            continue
        for p in root.glob("*.txt"):
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                # Unparseable directives are the canonicalizer's problem, not ours.
                continue
            if not isinstance(doc, dict):
                continue
            inds = doc.get("indicators") or []
            for m in inds:
                if isinstance(m, str) and m.startswith("indicators."):
                    mods.add(m)
    return mods


def _module_to_path(module: str) -> Path:
    return PROJECT_ROOT / Path(*module.split(".")).with_suffix(".py")


def _imports_swing_pivots(path: Path) -> bool:
    """Static detection of `from indicators.structure.swing_pivots import ...`
    or `import indicators.structure.swing_pivots`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("indicators.structure.swing_pivots"):
                return True
        elif isinstance(node, ast.Import):
            for n in node.names:
                if n.name.startswith("indicators.structure.swing_pivots"):
                    return True
    return False


@pytest.fixture(scope="module")
def referenced_modules() -> set[str]:
    mods = _referenced_indicator_modules()
    assert mods, "No indicator modules found in any directive — test scope is empty."
    return mods


def test_referenced_indicators_declare_signal_primitive(referenced_modules):
    """Every indicator used by any directive must declare SIGNAL_PRIMITIVE."""
    missing = []
    for mod in sorted(referenced_modules):
        path = _module_to_path(mod)
        if not path.exists():
            missing.append((mod, "module file not found"))
            continue
        try:
            imported = importlib.import_module(mod)
        except Exception as e:
            missing.append((mod, f"import failed: {e}"))
            continue
        sp = getattr(imported, "SIGNAL_PRIMITIVE", None)
        if not isinstance(sp, str) or not sp.strip():
            missing.append((mod, "missing or empty SIGNAL_PRIMITIVE"))
            continue
        if sp not in _ALLOWED_PRIMITIVES:
            missing.append((mod, f"SIGNAL_PRIMITIVE={sp!r} not in allowlist"))
    assert not missing, f"Semantic contract violations:\n  " + "\n  ".join(
        f"{m}: {r}" for m, r in missing
    )


def test_choch_family_must_declare_primitive():
    """Any indicator module whose filename contains 'choch' must declare
    SIGNAL_PRIMITIVE — regardless of whether it's currently referenced."""
    missing = []
    for path in INDICATORS_ROOT.rglob("*.py"):
        if "choch" not in path.name.lower():
            continue
        text = path.read_text(encoding="utf-8")
        if not re.search(r"^\s*SIGNAL_PRIMITIVE\s*=", text, re.MULTILINE):
            missing.append(str(path.relative_to(PROJECT_ROOT)))
    assert not missing, (
        "CHOCH-family modules missing SIGNAL_PRIMITIVE:\n  " + "\n  ".join(missing)
    )


def test_pivot_based_primitives_import_swing_pivots(referenced_modules):
    """pivot_k3 / structure_gated primitives must import swing_pivots."""
    offenders = []
    for mod in sorted(referenced_modules):
        path = _module_to_path(mod)
        if not path.exists():
            continue
        try:
            imported = importlib.import_module(mod)
        except Exception:
            continue
        sp = getattr(imported, "SIGNAL_PRIMITIVE", "")
        if sp in _PIVOT_PRIMITIVES:
            if not _imports_swing_pivots(path):
                offenders.append(
                    f"{mod} declares SIGNAL_PRIMITIVE={sp!r} but does not "
                    f"import indicators.structure.swing_pivots"
                )
    assert not offenders, "Pivot-primitive contract violations:\n  " + "\n  ".join(offenders)


def test_rolling_max_proxy_must_not_import_swing_pivots(referenced_modules):
    """rolling_max_proxy is definitionally non-pivot; importing swing_pivots
    indicates a mismatch between declared primitive and implementation."""
    offenders = []
    for mod in sorted(referenced_modules):
        path = _module_to_path(mod)
        if not path.exists():
            continue
        try:
            imported = importlib.import_module(mod)
        except Exception:
            continue
        sp = getattr(imported, "SIGNAL_PRIMITIVE", "")
        if sp == "rolling_max_proxy" and _imports_swing_pivots(path):
            offenders.append(
                f"{mod} declares rolling_max_proxy but imports swing_pivots - "
                f"primitive/implementation mismatch"
            )
    assert not offenders, "\n  ".join(offenders)


def test_pivot_source_token_and_consistency(referenced_modules):
    """PIVOT_SOURCE must be in the allowlist and must be consistent with the
    declared SIGNAL_PRIMITIVE."""
    offenders = []
    for mod in sorted(referenced_modules):
        try:
            imported = importlib.import_module(mod)
        except Exception:
            continue
        sp = getattr(imported, "SIGNAL_PRIMITIVE", None)
        ps = getattr(imported, "PIVOT_SOURCE", None)
        if ps is None:
            continue  # Optional field.
        if ps not in _ALLOWED_PIVOT_SOURCES:
            offenders.append(f"{mod}: PIVOT_SOURCE={ps!r} not in allowlist")
            continue
        if sp in _PIVOT_PRIMITIVES and ps == "none":
            offenders.append(
                f"{mod}: primitive={sp!r} but PIVOT_SOURCE='none' - inconsistent"
            )
        if sp == "rolling_max_proxy" and ps != "none":
            offenders.append(
                f"{mod}: primitive='rolling_max_proxy' but PIVOT_SOURCE={ps!r} - inconsistent"
            )
    assert not offenders, "PIVOT_SOURCE contract violations:\n  " + "\n  ".join(offenders)


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
