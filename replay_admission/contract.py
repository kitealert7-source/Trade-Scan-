"""Replay Admission — Admission Contract (Phase 0, read-only).

Answers one question: *"is this a valid, executable experiment?"* — before any
ExperimentContext is materialized or any stage runs. Pure validation: NO writes,
NO pipeline state, NO StageRunner coupling.

Design: outputs/system_reports/01_system_architecture/REPLAY_ADMISSION_DESIGN_2026-06-29.md (FROZEN v1).

Minimal contract:
  Required : strategy.py (valid STRATEGY_SIGNATURE markers)
             an experiment definition (normalized to ExperimentConfig from
                 experiment.json | explicit CLI | recovered artifacts)
             indicators resolve (the strategy's indicators.* imports exist)
  Optional : directive.txt, original run_id, original hashes (provenance only)

NOTE (chip task_0abbf64c): indicator HASH-DRIFT verification against a saved
snapshot/manifest is deferred to the indicator-snapshot work. Phase 0 verifies
only *resolvability* (module files exist); `verify_indicator_provenance` is the
seam where drift-detection plugs in once the manifest format lands.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Read-only contract validates the LOCAL tree it lives in (cf. gate-tools-validate-local-tree).
REPO_ROOT = Path(__file__).resolve().parent.parent

_SIG_START = "# --- STRATEGY SIGNATURE START ---"
_SIG_END = "# --- STRATEGY SIGNATURE END ---"


@dataclass
class ExperimentConfig:
    """Normalized experiment definition (the single internal form of all 3 sources)."""
    symbols: list[str]
    broker: str
    timeframe: str
    start_date: str
    end_date: str
    cost_model: str = "spread_charged"
    capital_profile: Optional[str] = None

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not self.symbols:
            errs.append("experiment: no symbols")
        for f in ("broker", "timeframe", "start_date", "end_date"):
            if not getattr(self, f):
                errs.append(f"experiment: missing {f}")
        return errs


@dataclass
class ContractResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    experiment: Optional[ExperimentConfig] = None
    experiment_source: Optional[str] = None  # experiment.json | explicit | recovered
    strategy_hash: Optional[str] = None
    indicators: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# strategy.py inspection (mirrors tools.orchestration.pre_execution; kept local
# so Phase 0 has zero orchestration coupling).
# --------------------------------------------------------------------------- #
def extract_signature(strategy_py: Path) -> Optional[dict]:
    """Parse the STRATEGY_SIGNATURE dict out of a strategy.py. None if absent/invalid."""
    content = Path(strategy_py).read_text(encoding="utf-8")
    m = re.search(
        rf"{re.escape(_SIG_START)}\s+STRATEGY_SIGNATURE\s*=\s*(\{{.*?\}})\s+{re.escape(_SIG_END)}",
        content,
        re.DOTALL,
    )
    if not m:
        return None
    raw = m.group(1).replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def strategy_signature_hash(sig: dict) -> str:
    """Stable hash of the behavioral signature (provenance anchor)."""
    return hashlib.sha256(json.dumps(sig, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def resolve_indicators(sig: dict, repo_root: Path = REPO_ROOT) -> tuple[list[str], list[str]]:
    """Enumerate the strategy's indicators.* modules and check each resolves to a file.

    Returns (modules, errors). Resolvability only — hash-drift detection is the
    chip's domain (see module docstring / verify_indicator_provenance)."""
    mods = [m for m in (sig.get("indicators") or []) if isinstance(m, str)]
    errors: list[str] = []
    for mod in mods:
        if not mod.startswith("indicators."):
            errors.append(f"indicator not under indicators/: {mod}")
            continue
        rel = Path(*mod.split(".")).with_suffix(".py")
        if not (repo_root / rel).exists():
            errors.append(f"indicator unresolved: {mod} (expected {rel})")
    return mods, errors


def verify_indicator_provenance(sig: dict, manifest: Optional[dict] = None) -> list[str]:
    """SEAM for chip task_0abbf64c. When a snapshot manifest is supplied, recompute
    live indicator hashes and return a non-empty error list on ANY drift (fail loud).
    Until the manifest format lands, this is a no-op (resolvability is checked separately)."""
    if not manifest:
        return []
    # Deferred: implement against the indicators_manifest.json the chip defines.
    return []


# --------------------------------------------------------------------------- #
# experiment definition normalization
# --------------------------------------------------------------------------- #
def normalize_experiment(
    *,
    experiment_json: Optional[Path] = None,
    cli: Optional[dict] = None,
    recovered: Optional[dict] = None,
) -> tuple[Optional[ExperimentConfig], Optional[str], list[str]]:
    """Resolve an ExperimentConfig from the first available source.

    Order (records `experiment_source`): experiment.json -> explicit CLI -> recovered.
    Returns (config | None, source | None, errors)."""
    data: Optional[dict] = None
    source: Optional[str] = None

    if experiment_json is not None and Path(experiment_json).exists():
        data = json.loads(Path(experiment_json).read_text(encoding="utf-8"))
        source = "experiment.json"
    elif cli:
        data = cli
        source = "explicit"
    elif recovered:
        data = recovered
        source = "recovered"

    if data is None:
        return None, None, [
            "experiment: no definition (experiment.json | CLI | recovered all absent)"
        ]

    try:
        cfg = ExperimentConfig(
            symbols=list(data.get("symbols") or []),
            broker=data.get("broker") or "OctaFX",
            timeframe=data.get("timeframe") or data.get("tf") or "",
            start_date=str(data.get("start_date") or data.get("start") or ""),
            end_date=str(data.get("end_date") or data.get("end") or ""),
            cost_model=data.get("cost_model") or "spread_charged",
            capital_profile=data.get("capital_profile"),
        )
    except Exception as e:  # malformed shape
        return None, source, [f"experiment: malformed definition: {e}"]

    return cfg, source, cfg.validate()


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #
def verify_experiment(
    strategy_dir,
    *,
    experiment_json: Optional[Path] = None,
    cli: Optional[dict] = None,
    recovered: Optional[dict] = None,
    indicator_manifest: Optional[dict] = None,
    repo_root: Path = REPO_ROOT,
) -> ContractResult:
    """Verify a (strategy.py + experiment definition) pair is an admissible experiment.

    Read-only. Returns a ContractResult; `ok` is True only when every Required check passes."""
    strategy_dir = Path(strategy_dir)
    errors: list[str] = []
    warnings: list[str] = []

    sp = strategy_dir / "strategy.py"
    if not sp.exists():
        return ContractResult(ok=False, errors=[f"strategy.py not found in {strategy_dir}"])

    sig = extract_signature(sp)
    if sig is None:
        errors.append("strategy.py: missing or invalid STRATEGY_SIGNATURE markers")

    strat_hash = strategy_signature_hash(sig) if sig else None

    indicators, ind_errs = resolve_indicators(sig or {}, repo_root=repo_root)
    errors.extend(ind_errs)
    errors.extend(verify_indicator_provenance(sig or {}, indicator_manifest))

    cfg, source, exp_errs = normalize_experiment(
        experiment_json=experiment_json, cli=cli, recovered=recovered
    )
    errors.extend(exp_errs)

    return ContractResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        experiment=cfg,
        experiment_source=source,
        strategy_hash=strat_hash,
        indicators=indicators,
    )
