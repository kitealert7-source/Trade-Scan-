"""promote_gate — governance classification + gate threshold stability.

Choke-point 1: `_infer_archetype` classifies every strategy into an
archetype bucket. Any drift silently reshapes the live portfolio composition.

Choke-point 2: `_QG_THRESHOLDS` is the 6-metric quality gate's cutoff
table. Any silent edit to these values changes which strategies pass
promotion without a governance record.

Scenario: run `_infer_archetype` against 12 canonical strategy IDs and
snapshot the full `_QG_THRESHOLDS` dict; compare both to frozen goldens.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.promote.metadata import _infer_archetype
from tools.promote.quality_gate import _QG_THRESHOLDS
from tools.regression.compare import compare_json
from tools.regression.runner import Result


# Canonical strategy IDs — cover every archetype prefix + an UNKNOWN.
_ARCHETYPE_CASES = [
    "02_VOL_IDX_1D_VOLEXP_S00_V1_P00",
    "03_TREND_XAUUSD_1H_BOS_S01_V1_P00",
    "33_TREND_BTCUSD_1H_IMPULSE_S02_V1_P00",
    "11_REV_XAUUSD_1H_PINBAR_S01_V1_P00",
    "27_MR_XAUUSD_15M_SMI_S02_V1_P00",
    "23_RSI_XAUUSD_1H_MEANREV_S01_V1_P00",
    "17_REV_XAUUSD_1H_LORB_S01_V1_P00",
    "18_REV_XAUUSD_1H_BREAKOUT_S01_V1_P00",
    "12_STR_FX_30M_RSIAVG_S01_V1_P00",
    "15_MR_FX_1H_ULTC_S01_V1_P00",
    "22_CONT_FX_1H_MOMENTUM_S01_V1_P00",
    "35_PA_GER40_15M_PATTERN_S01_V1_P00",
    "99_UNKNOWN_FAMILY_S01_V1_P00",  # must return UNKNOWN
]


def run(tmp_dir: Path, baseline_dir: Path, budget) -> list[Result]:
    # --- archetype inference -------------------------------------------------
    archetypes = {sid: _infer_archetype(sid) for sid in _ARCHETYPE_CASES}
    arch_path = tmp_dir / "archetype_inference.json"
    arch_path.write_text(json.dumps(archetypes, indent=2, sort_keys=True), encoding="utf-8")

    # --- quality gate thresholds snapshot ------------------------------------
    thresh_path = tmp_dir / "quality_gate_thresholds.json"
    thresh_path.write_text(
        json.dumps(_QG_THRESHOLDS, indent=2, sort_keys=True), encoding="utf-8"
    )

    # Candidates for --update-baseline
    cand_root = tmp_dir / "golden_candidate"
    cand_root.mkdir(parents=True, exist_ok=True)
    (cand_root / "archetype_inference.json").write_text(
        json.dumps(archetypes, indent=2, sort_keys=True), encoding="utf-8")
    (cand_root / "quality_gate_thresholds.json").write_text(
        json.dumps(_QG_THRESHOLDS, indent=2, sort_keys=True), encoding="utf-8")

    # --- compare --------------------------------------------------------------
    results: list[Result] = []
    for artifact in ("archetype_inference.json", "quality_gate_thresholds.json"):
        got = tmp_dir / artifact
        golden = baseline_dir / "golden" / artifact
        passed, diff = compare_json(got, golden)
        results.append(Result(
            scenario="promote_gate",
            artifact=artifact,
            passed=passed,
            diff=diff,
        ))
    return results
