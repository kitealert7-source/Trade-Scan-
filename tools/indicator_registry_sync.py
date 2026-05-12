"""Indicator registry sync — operator helper.

The 2026-05-12 governance sync wired `indicators/INDICATOR_REGISTRY.yaml`
into Stage-0.5 as the authoritative allowlist (see commit `5a354db`).
This script is the operator's interface for keeping the registry in
sync with disk:

  python tools/indicator_registry_sync.py --list
      Show drift: modules on disk not in registry, and vice versa.

  python tools/indicator_registry_sync.py --check
      Same as --list, but exits 1 if any drift exists. Suitable for CI.

  python tools/indicator_registry_sync.py --add-stubs
      For every module on disk that is missing from the registry,
      append a governance-sync stub entry (module_path + category +
      registered_at). Bumps `registry_version`. Idempotent.

  python tools/indicator_registry_sync.py --add-stub <module_path>
      Add a stub for one specific dotted module path (e.g.
      `indicators.structure.foo`). Useful inside a feature branch
      that's adding one new indicator. Idempotent.

This script does NOT delete registry entries. Unused ≠ invalid; pruning
is governance policy, not enforcement. Stabilize first, prune later.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "indicators" / "INDICATOR_REGISTRY.yaml"
INDICATORS_ROOT = PROJECT_ROOT / "indicators"


def _load_registry() -> dict:
    import yaml
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"Registry not found at {REGISTRY_PATH}")
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def _write_registry(data: dict) -> None:
    import yaml
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, sort_keys=False, default_flow_style=False,
            allow_unicode=True, width=120,
        )


def _registered_module_paths(reg: dict) -> set[str]:
    entries = reg.get("indicators") or {}
    out: set[str] = set()
    for entry in entries.values():
        if isinstance(entry, dict) and isinstance(entry.get("module_path"), str):
            out.add(entry["module_path"])
    return out


def _disk_module_paths() -> set[str]:
    out: set[str] = set()
    for p in INDICATORS_ROOT.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        rel = p.relative_to(PROJECT_ROOT).with_suffix("")
        out.add(".".join(rel.parts))
    return out


def _drift_report() -> tuple[set[str], set[str]]:
    reg = _load_registry()
    registered = _registered_module_paths(reg)
    on_disk = _disk_module_paths()
    return on_disk - registered, registered - on_disk


def _dotted_to_name(dotted: str) -> tuple[str, str]:
    """`indicators.momentum.rsi_smoothed` → (`rsi_smoothed`, `momentum`)."""
    parts = dotted.split(".")
    if len(parts) < 3 or parts[0] != "indicators":
        raise ValueError(f"Not a valid indicator dotted path: {dotted}")
    return parts[-1], parts[1]


def _make_stub(dotted: str, today: str) -> dict:
    """Construct the minimum-viable registry entry for an unregistered
    indicator. Mirrors the form used by the 2026-05-12 sync.
    """
    _, category = _dotted_to_name(dotted)
    return {
        "module_path": dotted,
        "category": category,
        "registered_at": today,
        "notes": (
            "Stub entry added via indicator_registry_sync — module_path "
            "verified; rich metadata (function_name, input_requirements, "
            "output_columns, etc.) to be backfilled."
        ),
    }


def _bump_version(reg: dict, change_note: str, today: str) -> None:
    new_version = (reg.get("registry_version") or 0) + 1
    reg["registry_version"] = new_version
    reg["generated_at"] = (
        datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    )
    gu = reg.setdefault("governance_updates", {})
    gu[f"version_{new_version}"] = {
        "date": today,
        "changes": [change_note],
    }


def cmd_list() -> int:
    on_disk_not_registered, in_registry_not_on_disk = _drift_report()
    print(f"Registry: {REGISTRY_PATH}")
    print(f"On disk, NOT in registry: {len(on_disk_not_registered)}")
    for p in sorted(on_disk_not_registered):
        print(f"  {p}")
    print(f"In registry, NOT on disk: {len(in_registry_not_on_disk)}")
    for p in sorted(in_registry_not_on_disk):
        print(f"  {p}")
    return 0


def cmd_check() -> int:
    on_disk_not_registered, in_registry_not_on_disk = _drift_report()
    if not on_disk_not_registered and not in_registry_not_on_disk:
        print("[indicator-registry-sync] OK -- disk <-> registry in sync.")
        return 0
    cmd_list()
    print("")
    print("[indicator-registry-sync] DRIFT DETECTED. Run --add-stubs to "
          "register missing modules.")
    return 1


def cmd_add_stubs() -> int:
    reg = _load_registry()
    registered = _registered_module_paths(reg)
    on_disk = _disk_module_paths()
    missing = sorted(on_disk - registered)
    if not missing:
        print("[indicator-registry-sync] Nothing to do -- all disk modules registered.")
        return 0

    today = datetime.date.today().isoformat()
    entries = reg.setdefault("indicators", {})
    for dotted in missing:
        name = dotted.split(".")[-1]
        # Collision-safe key (name + category) so re-runs don't clobber.
        key = name if name not in entries else f"{name}__{dotted.split('.')[1]}"
        entries[key] = _make_stub(dotted, today)

    _bump_version(
        reg,
        f"indicator_registry_sync: {len(missing)} stub entries added.",
        today,
    )
    _write_registry(reg)
    print(f"[indicator-registry-sync] Added {len(missing)} stub entries. "
          f"Bumped registry to v{reg['registry_version']}.")
    for dotted in missing:
        print(f"  + {dotted}")
    return 0


def cmd_add_stub(dotted: str) -> int:
    if not dotted.startswith("indicators."):
        print(f"[indicator-registry-sync] ERROR: {dotted!r} must start with "
              "`indicators.`")
        return 2
    # Verify the file exists — otherwise we'd register a phantom.
    rel = Path(*dotted.split(".")).with_suffix(".py")
    if not (PROJECT_ROOT / rel).exists():
        print(f"[indicator-registry-sync] ERROR: file not found at "
              f"{PROJECT_ROOT / rel}. Create the module before registering.")
        return 2
    reg = _load_registry()
    registered = _registered_module_paths(reg)
    if dotted in registered:
        print(f"[indicator-registry-sync] Already registered: {dotted}")
        return 0

    today = datetime.date.today().isoformat()
    entries = reg.setdefault("indicators", {})
    name = dotted.split(".")[-1]
    key = name if name not in entries else f"{name}__{dotted.split('.')[1]}"
    entries[key] = _make_stub(dotted, today)
    _bump_version(
        reg,
        f"indicator_registry_sync: 1 stub entry added ({dotted}).",
        today,
    )
    _write_registry(reg)
    print(f"[indicator-registry-sync] Added stub for {dotted}. "
          f"Bumped registry to v{reg['registry_version']}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="Show drift, exit 0.")
    g.add_argument("--check", action="store_true",
                   help="Show drift, exit 1 if any.")
    g.add_argument("--add-stubs", action="store_true",
                   help="Auto-register every disk module missing from registry.")
    g.add_argument("--add-stub", metavar="DOTTED_PATH",
                   help="Add one specific module by dotted path.")
    args = p.parse_args(argv)
    if args.list:
        return cmd_list()
    if args.check:
        return cmd_check()
    if args.add_stubs:
        return cmd_add_stubs()
    if args.add_stub:
        return cmd_add_stub(args.add_stub)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
