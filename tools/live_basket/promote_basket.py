"""promote_basket.py — Phase C: automate the promotion-artifact assembly.

Reproduces, from (directive + run receipt + promotion timestamp), the exact
vault + descriptor + history artifacts that were previously HAND-built for
CADJPYUSDCHF / CHFJPYEURUSD / EURJPYGBPJPY. Golden-tested against those exemplars
(tests/.../test_promote_basket.py): the generated descriptor and vault meta must
match the committed artifacts.

SCOPE — Phase C ONLY: refresh -> vault -> descriptor -> history -> verify.
This tool does NOT touch the supervision registry, account assignment, rate
budget, or the daemon. That is Phase D (TS_Execution). The C/D split mirrors the
repo boundary: Trade_Scan owns PROMOTION ARTIFACTS; TS_Execution owns DEPLOYMENT.
If you find yourself adding registry/account/poll logic here, STOP and split it
back into onboard_basket.py.

    # reproduce/inspect without touching anything real:
    python tools/live_basket/promote_basket.py --directive-id <ID> --run-id <ID> --dry-run
    # real promotion (writes strategy_pool/ + DRY_RUN_VAULT/):
    python tools/live_basket/promote_basket.py --directive-id <ID> --run-id <ID>
    # refresh first, then promote (auto-detects the new run_id):
    python tools/live_basket/promote_basket.py --directive-id <ID> --refresh
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

_TS_ROOT = Path(__file__).resolve().parents[2]            # .../Trade_Scan
if str(_TS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TS_ROOT))

from tools.pipeline_utils import parse_directive          # noqa: E402

_DOCS = _TS_ROOT.parent                                   # shared root (TradeScan_State + DRY_RUN_VAULT siblings)
_TRADESCAN_STATE = _DOCS / "TradeScan_State"
_DIRECTIVES = _TS_ROOT / "backtest_directives" / "completed"
_RUNS = _TRADESCAN_STATE / "runs"
_STRATEGY_POOL = _TRADESCAN_STATE / "strategy_pool"
_DRY_RUN_VAULT = _DOCS / "DRY_RUN_VAULT"
_BROKER_SPECS = _TS_ROOT / "data_access" / "broker_specs"

# Fixed descriptor constants — the COINTREV_V3 recycle family (matches the 3 exemplars).
RECYCLE_RULE = "pine_ratio_zrev_v1_zcross"
RECYCLE_RULE_VERSION = 1
SIZING_MODE = "granular_parity"
DEFAULT_LOT = 0.01
LIFECYCLE = "PROMOTED"


# --------------------------------------------------------------------------- #
# Derivation (pure)
# --------------------------------------------------------------------------- #
def directive_path(directive_id: str) -> Path:
    p = _DIRECTIVES / f"{directive_id}.txt"
    if not p.is_file():
        raise SystemExit(f"directive not found: {p}")
    return p


def derive_legs(dpath: Path):
    """[(symbol, direction)] from the directive — leg1 long, leg2 short (the spread
    convention the producer and all 3 exemplars use)."""
    legs = parse_directive(dpath)["basket"]["legs"]
    if len(legs) != 2:
        raise SystemExit(f"basket has {len(legs)} legs; promote_basket supports exactly 2")
    return [(legs[0]["symbol"], "long"), (legs[1]["symbol"], "short")]


def _legs_block(legs):
    return [{"symbol": s, "direction": d, "lot": DEFAULT_LOT} for s, d in legs]


def vault_id_for(run_id: str, promoted_at: str) -> str:
    return f"DRY_RUN_{promoted_at[:10].replace('-', '_')}__{run_id[:8]}"


def _default_note(window_mode: str, override_reason: str | None) -> str:
    if window_mode == "recorded":
        return ("OPERATOR-AUTHORIZED OVERRIDE (recorded window). "
                + (override_reason or "")).strip()
    return ("Provenance-complete refresh run (refresh_cointegration.py). "
            "broker_spec + leg_data sha256 in manifest.")


def build_descriptor(basket_id, directive_id, run_id, legs, promoted_at, vault_id, note):
    return {
        "basket_id": basket_id,
        "lifecycle": LIFECYCLE,
        "vault_ref": vault_id,
        "run_id": run_id,
        "directive_id": directive_id,
        "promoted_at": promoted_at,
        "recycle_rule": RECYCLE_RULE,
        "recycle_rule_version": RECYCLE_RULE_VERSION,
        "sizing_mode": SIZING_MODE,
        "legs": _legs_block(legs),
        "notes": note,
    }


def build_meta(manifest, basket_id, directive_id, run_id, legs, promoted_at, vault_id):
    return {
        "vault_id": vault_id,
        "basket_id": basket_id,
        "run_id": run_id,
        "directive_id": directive_id,
        "promoted_at": promoted_at,
        "execution_mode": manifest.get("execution_mode", "basket"),
        "engine_version": manifest.get("engine_version"),
        "recycle_rule": RECYCLE_RULE,
        "recycle_rule_version": RECYCLE_RULE_VERSION,
        "sizing_mode": SIZING_MODE,
        "legs": _legs_block(legs),
        "input_provenance": manifest["input_provenance"],
    }


def build_history_event(run_id, vault_id, directive_id, promoted_at, note):
    return {
        "event": "PROMOTED",
        "timestamp": promoted_at,
        "run_id": run_id,
        "vault_ref": vault_id,
        "directive_id": directive_id,
        "note": note,
    }


# --------------------------------------------------------------------------- #
# Vault assembly + verification
# --------------------------------------------------------------------------- #
def _broker_spec_dir(symbols) -> Path:
    if _BROKER_SPECS.is_dir():
        for d in sorted(_BROKER_SPECS.iterdir()):
            if d.is_dir() and all((d / f"{s}.yaml").is_file() for s in symbols):
                return d
    return _BROKER_SPECS / "OctaFx"


def assemble_vault(vault_dir: Path, run_dir: Path, dpath: Path, legs, meta) -> None:
    (vault_dir / "run_snapshot").mkdir(parents=True, exist_ok=True)
    (vault_dir / "broker_specs_snapshot").mkdir(parents=True, exist_ok=True)
    (vault_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.copy2(dpath, vault_dir / "directive.txt")
    for f in ("manifest.json", "run_state.json"):
        if (run_dir / f).is_file():
            shutil.copy2(run_dir / f, vault_dir / "run_snapshot" / f)
    res = run_dir / "data" / "results_tradelevel.csv"
    if res.is_file():
        shutil.copy2(res, vault_dir / "run_snapshot" / "results_tradelevel.csv")
    if (run_dir / "basket_code").is_dir():
        shutil.copytree(run_dir / "basket_code", vault_dir / "basket_code", dirs_exist_ok=True)
    bdir = _broker_spec_dir([s for s, _ in legs])
    for s, _ in legs:
        if (bdir / f"{s}.yaml").is_file():
            shutil.copy2(bdir / f"{s}.yaml", vault_dir / "broker_specs_snapshot" / f"{s}.yaml")


def verify_descriptor(path: Path) -> None:
    """Structural verification — the descriptor must parse and carry the fields the
    live producer reads. (derive_basket_config is the deeper check for a REAL
    promotion, once the descriptor sits in strategy_pool/.)"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"basket_id", "lifecycle", "vault_ref", "run_id", "directive_id",
                "recycle_rule", "sizing_mode", "legs"}
    missing = required - set(d)
    if missing:
        raise SystemExit(f"descriptor verify FAILED: missing {sorted(missing)}")
    if len(d["legs"]) != 2 or {l["direction"] for l in d["legs"]} != {"long", "short"}:
        raise SystemExit("descriptor verify FAILED: legs must be exactly one long + one short")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _utcnow() -> str:
    return _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _latest_run_for(basket_id: str) -> str:
    """Newest run dir whose manifest basket_id matches — used after --refresh."""
    cands = []
    for d in (_RUNS.iterdir() if _RUNS.is_dir() else []):
        mf = d / "manifest.json"
        if mf.is_file():
            try:
                if json.loads(mf.read_text(encoding="utf-8")).get("basket_id") == basket_id:
                    cands.append((mf.stat().st_mtime, d.name))
            except Exception:
                pass
    if not cands:
        raise SystemExit(f"no run receipt found for basket {basket_id!r}")
    return max(cands)[1]


def run_refresh(directive_id: str, window_mode: str, reason: str) -> None:
    """Thin wrapper over the existing refresh tool (Phase C step 1). Not golden-
    tested (it needs MT5/the pipeline); the assembled artifacts ARE.

    refresh_cointegration.py requires --category + --reason. current-window
    refreshes are DATA_FRESH (re-pin to today's cointegrated span); recorded-window
    refreshes are ENGINE (an operator override of the current-span gate)."""
    category = "ENGINE" if window_mode == "recorded" else "DATA_FRESH"
    cmd = [sys.executable, str(_TS_ROOT / "tools" / "refresh_cointegration.py"),
           directive_id, "--category", category, "--reason", reason,
           "--window-mode", window_mode]
    print(f"  PROMOTE_REFRESH  {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(_TS_ROOT))


def promote(directive_id, run_id=None, *, now=None, window_mode="current",
            override_reason=None, note=None, dry_run=True, out_dir=None, refresh=False):
    """Assemble vault + descriptor + history from a run receipt. Returns the paths.

    dry_run=True writes to a staging dir (touches nothing real). Real promotion
    writes strategy_pool/<BASKET>/ and DRY_RUN_VAULT/<vault_id>/<BASKET>/."""
    dpath = directive_path(directive_id)
    legs = derive_legs(dpath)
    basket_id = "".join(s for s, _ in legs)
    if refresh and run_id is None:
        reason = (override_reason
                  or f"Promote {basket_id}: refresh to current 252d cointegrated window")
        run_refresh(directive_id, window_mode, reason)
        run_id = _latest_run_for(basket_id)
    if run_id is None:
        raise SystemExit("--run-id required (or pass --refresh to create one)")
    run_dir = _RUNS / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    now = now or _utcnow()
    vault_id = vault_id_for(run_id, now)
    note = note or _default_note(window_mode, override_reason)

    descriptor = build_descriptor(basket_id, directive_id, run_id, legs, now, vault_id, note)
    meta = build_meta(manifest, basket_id, directive_id, run_id, legs, now, vault_id)
    history = build_history_event(run_id, vault_id, directive_id, now, note)

    if dry_run:
        base = Path(out_dir) if out_dir else (_DOCS / "_promote_staging" / basket_id)
        if base.exists() and out_dir is None:   # only auto-clear our own default staging
            shutil.rmtree(base)
        pool_dir = base / "strategy_pool" / basket_id
        vault_dir = base / "DRY_RUN_VAULT" / vault_id / basket_id
        history_mode = "w"
    else:
        pool_dir = _STRATEGY_POOL / basket_id
        vault_dir = _DRY_RUN_VAULT / vault_id / basket_id
        history_mode = "a"          # append: never clobber prior promotion history

    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / "descriptor.json").write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    with open(pool_dir / "history.jsonl", history_mode, encoding="utf-8") as f:
        f.write(json.dumps(history) + "\n")
    assemble_vault(vault_dir, run_dir, dpath, legs, meta)
    verify_descriptor(pool_dir / "descriptor.json")

    return {
        "basket_id": basket_id, "vault_id": vault_id, "dry_run": dry_run,
        "descriptor": pool_dir / "descriptor.json",
        "history": pool_dir / "history.jsonl",
        "meta": vault_dir / "meta.json",
        "vault_dir": vault_dir,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase C: assemble basket promotion artifacts")
    ap.add_argument("--directive-id", required=True)
    ap.add_argument("--run-id", default=None, help="existing run receipt (or use --refresh)")
    ap.add_argument("--refresh", action="store_true", help="run refresh_cointegration first")
    ap.add_argument("--window-mode", default="current", choices=["current", "recorded"])
    ap.add_argument("--override-reason", default=None)
    ap.add_argument("--note", default=None)
    ap.add_argument("--now", default=None, help="promotion timestamp (ISO Z); default now")
    ap.add_argument("--dry-run", action="store_true", help="stage only; touch nothing real")
    ap.add_argument("--out-dir", default=None, help="dry-run staging dir")
    a = ap.parse_args(argv)
    r = promote(a.directive_id, a.run_id, now=a.now, window_mode=a.window_mode,
                override_reason=a.override_reason, note=a.note, dry_run=a.dry_run,
                out_dir=a.out_dir, refresh=a.refresh)
    print("=" * 60)
    print(f"  {'DRY-RUN (staged)' if r['dry_run'] else 'PROMOTED'}  basket={r['basket_id']}  vault={r['vault_id']}")
    print(f"  descriptor: {r['descriptor']}")
    print(f"  history:    {r['history']}")
    print(f"  vault meta: {r['meta']}")
    if r["dry_run"]:
        print("  (nothing real was written; registry/daemon untouched — that is Phase D)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
