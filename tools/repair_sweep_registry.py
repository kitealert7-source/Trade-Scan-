#!/usr/bin/env python3
"""repair_sweep_registry.py -- sanctioned, human-approved repair for sweep-registry DRIFT.

DRIFT = a registry slot occupied by an entry whose directive_name's intrinsic
coordinates contradict the slot it is filed under (mis-filed corruption), as
opposed to a genuine COLLISION (a real signature conflict at the *correct*
coordinates). The sweep gate (tools/sweep_registry_gate.py) now distinguishes the
two and emits REGISTRY_DRIFT pointing here.

This tool DETECTS and EXPLAINS drift, and -- ONLY with an explicit --apply -- repairs
a drifted PATCH slot by removing the mis-filed entry, so the gate re-registers the
legitimate owner on its next run. It NEVER mutates automatically and is NEVER invoked
by the gate. It edits only governance/namespace/sweep_registry.yaml (the namespace
registry); the append-only ledger and run provenance are NOT touched.

    Detect (--scan)  ->  Explain (--dry-run, default)  ->  [human runs --apply]  ->  Repair

Sweep-OWNER drift is detected/explained but NOT auto-repaired (the slot may own patch
children -- escalate for manual review). Patch-slot drift is the repairable case.

Usage:
    python tools/repair_sweep_registry.py --scan
    python tools/repair_sweep_registry.py --idea 22 --sweep S02 --patch P02            # dry-run
    python tools/repair_sweep_registry.py --idea 22 --sweep S02 --patch P02 --apply
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sweep_registry_gate import (  # noqa: E402
    SWEEP_REGISTRY_PATH,
    SWEEP_LOCK_PATH,
    _load_yaml,
    _write_yaml_atomic,
    _acquire_lock,
    _release_lock,
    _slot_drift,
)
from tools.system_registry import _get_directive_first_execution_timestamp  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"


def _sweeps_of(idea_block):
    """Return the sweeps mapping (current 'sweeps' key, legacy 'allocated')."""
    if not isinstance(idea_block, dict):
        return {}
    s = idea_block.get("sweeps", idea_block.get("allocated", {}))
    return s if isinstance(s, dict) else {}


def _iter_slots(registry):
    """Yield (idea, sweep, patch|None, directive_name) for every slot in the registry."""
    ideas = registry.get("ideas", {})
    if not isinstance(ideas, dict):
        return
    for idea, idea_block in ideas.items():
        for sweep, sdata in _sweeps_of(idea_block).items():
            if not isinstance(sdata, dict):
                continue
            yield (idea, sweep, None, str(sdata.get("directive_name", "")).strip())
            patches = sdata.get("patches", {})
            if isinstance(patches, dict):
                for patch, pdata in patches.items():
                    if isinstance(pdata, dict):
                        yield (idea, sweep, patch, str(pdata.get("directive_name", "")).strip())


def cmd_scan(registry):
    drift = []
    for idea, sweep, patch, name in _iter_slots(registry):
        is_d, actual = _slot_drift(name, idea, sweep, patch)
        if is_d:
            drift.append((idea, sweep, patch, name, actual))
    if not drift:
        print("[SCAN] No sweep-registry drift detected.")
        return 0
    print(f"[SCAN] {len(drift)} drifted slot(s) -- slot <- occupant (occupant's own coords):")
    for idea, sweep, patch, name, actual in sorted(drift):
        slot = f"{idea}/{sweep}/{patch}" if patch else f"{idea}/{sweep} (owner)"
        kind = "patch" if patch else "OWNER"
        print(f"  [{kind:5}] {slot:24} <- '{name}'  own=({actual[0]}/{actual[1]}/{actual[2]})")
    print("\nExplain/repair one slot at a time (patch-slot drift is repairable):")
    print("  python tools/repair_sweep_registry.py --idea <I> --sweep <SNN> --patch <PNN> [--apply]")
    return 0


def _is_fs_orphan(directive_name: str) -> bool:
    """True when the reservation is a TRUE orphan: no strategy folder AND no run history.

    Both conditions are required:
      * ``strategies/<name>/`` is gone (no backing strategy code), AND
      * the run registry has no non-zero-artifact run for this directive_id.

    The second guard is the safety rail. A strategy whose folder was pruned but
    which DID run leaves real provenance -- releasing its reservation would erase
    namespace history. Those are NOT orphans (route via ``repair_integrity`` /
    ``retire_runs``). A true orphan is a never-realised concept: a failed-attempt
    lock with no folder and no runs, holding a SIGNATURE IDEMPOTENCY lock that
    blocks fresh registration of the concept (``SWEEP_IDEMPOTENCY_MISMATCH``).
    Distinct from DRIFT (a mis-filed but present strategy). Run provenance itself
    is never touched here -- only the namespace reservation.
    """
    if not directive_name:
        return False
    if (STRATEGIES_DIR / directive_name).exists():
        return False
    return _get_directive_first_execution_timestamp(directive_name) is None


def cmd_scan_orphans(registry):
    orphans = []
    for idea, sweep, patch, name in _iter_slots(registry):
        if _is_fs_orphan(name):
            orphans.append((idea, sweep, patch, name))
    if not orphans:
        print("[SCAN-ORPHANS] No FS-orphan reservations (every slot has a strategy folder).")
        return 0
    print(f"[SCAN-ORPHANS] {len(orphans)} reservation(s) whose strategy folder is gone:")
    for idea, sweep, patch, name in sorted(orphans):
        slot = f"{idea}/{sweep}/{patch}" if patch else f"{idea}/{sweep} (owner)"
        print(f"  {slot:26} <- '{name}'  (no strategies/{name}/)")
    print("\nRelease one at a time (frees the slot + its signature idempotency lock):")
    print("  python tools/repair_sweep_registry.py --release --idea <I> --sweep <SNN> [--patch <PNN>] --apply")
    return 0


def cmd_release_orphan(registry, idea, sweep, patch, apply):
    """Release a single FS-orphan reservation (the strategy folder is gone).

    Refuses if the strategy folder still exists (LIVE reservation) or if a
    sweep-owner still has patch children (would orphan them). Backup + lock +
    atomic write, mirroring the drift-repair path. Ledger/run history untouched.
    """
    sweeps = _sweeps_of(registry.get("ideas", {}).get(idea, {}))
    sdata = sweeps.get(sweep)
    if not isinstance(sdata, dict):
        print(f"[ERROR] slot {idea}/{sweep} not found in registry.")
        return 2
    if patch:
        patches = sdata.get("patches", {})
        entry = patches.get(patch) if isinstance(patches, dict) else None
        if not isinstance(entry, dict):
            print(f"[ERROR] patch slot {idea}/{sweep}/{patch} not found in registry.")
            return 2
        kind = "patch"
    else:
        entry = sdata
        kind = "sweep-owner"

    name = str(entry.get("directive_name", "")).strip()
    slot = f"{idea}/{sweep}" + (f"/{patch}" if patch else "")
    folder_exists = bool(name) and (STRATEGIES_DIR / name).exists()

    print(f"[TARGET] {kind} reservation {slot}")
    print(f"  directive_name  : {name or '(empty)'}")
    print(f"  strategy folder : strategies/{name}/  ->  {'EXISTS' if folder_exists else 'MISSING'}")

    if not _is_fs_orphan(name):
        if folder_exists:
            print("[REFUSE] strategy folder still exists -- LIVE reservation, not an orphan. Not releasing. "
                  "Delete the strategy folder first only if you truly intend to retire it.")
        else:
            print("[REFUSE] reservation has RUN HISTORY (real provenance) though its folder is gone -- not an "
                  "orphan. Releasing would erase namespace history; route via repair_integrity / retire_runs.")
        return 1

    if kind == "sweep-owner":
        patches = sdata.get("patches", {})
        if isinstance(patches, dict) and patches:
            print(f"[REFUSE] sweep-owner {slot} still has patch children {sorted(patches)} -- releasing "
                  "would orphan them. Release/retire the patches first.")
            return 1

    print(f"\n[PLAN] release orphan {kind} reservation {slot} -- frees the slot and its signature "
          "idempotency lock so the concept can be re-registered fresh. Run-registry history untouched.")
    if not apply:
        print("\n[DRY-RUN] no changes written. Re-run with --apply to release.")
        return 0

    backup = SWEEP_REGISTRY_PATH.with_name(SWEEP_REGISTRY_PATH.name + ".bak_orphanrelease")
    shutil.copy(SWEEP_REGISTRY_PATH, backup)
    fd = _acquire_lock(SWEEP_LOCK_PATH)
    try:
        reg = _load_yaml(SWEEP_REGISTRY_PATH)  # re-read under lock
        _sw = _sweeps_of(reg.get("ideas", {}).get(idea, {}))
        if patch:
            removed = _sw.get(sweep, {}).get("patches", {}).pop(patch, None)
        else:
            removed = _sw.pop(sweep, None)
        if removed is None:
            print(f"[NO-OP] {slot} no longer present (already released?).")
            return 0
        _write_yaml_atomic(SWEEP_REGISTRY_PATH, reg)
    finally:
        _release_lock(fd, SWEEP_LOCK_PATH)

    print(f"[APPLIED] released orphan reservation {slot} (was '{name}'). Backup: {backup.name}")
    print("Next: the concept's signature is now free to register at a fresh slot.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Detect/explain/repair sweep-registry DRIFT (human-approved; never automatic)."
    )
    ap.add_argument("--scan", action="store_true", help="list every drifted slot (read-only)")
    ap.add_argument("--scan-orphans", action="store_true",
                    help="list reservations whose strategy folder is gone (read-only)")
    ap.add_argument("--release", action="store_true",
                    help="release an FS-orphan reservation at --idea/--sweep[/--patch] "
                         "(default: dry-run; add --apply)")
    ap.add_argument("--idea", help="target idea id, e.g. 22")
    ap.add_argument("--sweep", help="target sweep slot, e.g. S02")
    ap.add_argument("--patch", help="target patch slot, e.g. P02 (omit for sweep-owner)")
    ap.add_argument("--apply", action="store_true",
                    help="perform the repair (default: dry-run / explain only)")
    args = ap.parse_args()

    registry = _load_yaml(SWEEP_REGISTRY_PATH)

    if args.scan:
        return cmd_scan(registry)

    if args.scan_orphans:
        return cmd_scan_orphans(registry)

    if not (args.idea and args.sweep):
        ap.error("provide --scan / --scan-orphans, OR --idea and --sweep (optionally --patch) to target a slot.")

    idea, sweep = str(args.idea), str(args.sweep)
    patch = str(args.patch) if args.patch else None

    if args.release:
        return cmd_release_orphan(registry, idea, sweep, patch, apply=args.apply)

    sweeps = _sweeps_of(registry.get("ideas", {}).get(idea, {}))
    sdata = sweeps.get(sweep)
    if not isinstance(sdata, dict):
        print(f"[ERROR] slot {idea}/{sweep} not found in registry.")
        return 2

    if patch:
        patches = sdata.get("patches", {})
        entry = patches.get(patch) if isinstance(patches, dict) else None
        if not isinstance(entry, dict):
            print(f"[ERROR] patch slot {idea}/{sweep}/{patch} not found in registry.")
            return 2
        kind = "patch"
    else:
        entry = sdata
        kind = "sweep-owner"

    name = str(entry.get("directive_name", "")).strip()
    is_drifted, actual = _slot_drift(name, idea, sweep, patch)
    slot = f"{idea}/{sweep}" + (f"/{patch}" if patch else "")

    print(f"[TARGET] {kind} slot {slot}")
    print(f"  occupant directive_name : {name or '(empty)'}")
    print(f"  occupant's own coords   : idea={actual[0]} sweep={actual[1]} patch={actual[2]}")
    print(f"  this slot's coords      : idea={idea} sweep={sweep} patch={patch}")

    if not is_drifted:
        print("[OK] NOT drifted -- the occupant's coordinates match the slot (internally "
              "consistent, not corruption). Nothing for this tool to repair. If a run hit a "
              "hash conflict at this slot, that is a genuine COLLISION (real signature change) "
              "-- resolve via /rerun-backtest (declared rerun) or namespace review.")
        return 1

    print("[DRIFT CONFIRMED] occupant is mis-filed -- its coordinates contradict the slot.")

    if kind == "sweep-owner":
        print("[REFUSE] sweep-OWNER drift is NOT auto-repaired by this tool (the slot may own "
              "patch children). Escalate for manual review. Patch-slot drift is repairable here "
              "via --patch.")
        return 1

    print(f"\n[PLAN] remove the mis-filed patch entry '{patch}' (occupant '{name}') from sweep "
          f"'{idea}/{sweep}'. On the next run of the legitimate {idea}/{sweep}/{patch} directive "
          f"the gate re-registers the slot correctly. Ledger + provenance untouched.")

    if not args.apply:
        print("\n[DRY-RUN] no changes written. Re-run with --apply to perform the repair.")
        return 0

    backup = SWEEP_REGISTRY_PATH.with_name(SWEEP_REGISTRY_PATH.name + ".bak_driftrepair")
    shutil.copy(SWEEP_REGISTRY_PATH, backup)
    fd = _acquire_lock(SWEEP_LOCK_PATH)
    try:
        reg = _load_yaml(SWEEP_REGISTRY_PATH)  # re-read under lock
        _patches = _sweeps_of(reg.get("ideas", {}).get(idea, {})).get(sweep, {}).get("patches", {})
        removed = _patches.pop(patch, None)
        if removed is None:
            print(f"[NO-OP] patch {idea}/{sweep}/{patch} no longer present (already repaired?).")
            return 0
        _write_yaml_atomic(SWEEP_REGISTRY_PATH, reg)
    finally:
        _release_lock(fd, SWEEP_LOCK_PATH)

    print(f"[APPLIED] removed drifted patch entry {idea}/{sweep}/{patch} (was '{name}'). "
          f"Backup: {backup.name}")
    print("Next: run the legitimate directive; the gate will re-register the slot cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
