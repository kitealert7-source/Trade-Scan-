#!/usr/bin/env python
"""promote_engine.py -- make engine promotions and freeze-amendments SMOOTH.

Two operations that today are a hand-edited marathon across ~13 surfaces:

  --restamp <vN>
      You edited an engine source file (e.g. a stage2_compiler bug fix). Recompute
      the LF-NORMALIZED manifest file_hashes, re-sync the vault copy, and verify
      integrity. Kills the CRLF-vs-LF hash gotcha + the "manifest now stale" drift
      that bites every engine edit.

  --promote <vNEW>
      Flip the canonical engine from the CURRENT authority to <vNEW> across every
      identity surface (authority x2, registry, basket import + self-check,
      convergence-test literals), freeze + vault <vNEW>, rehash the ABI, regen the
      guard manifest, and run the convergence gate. Does NOT commit -- review the
      diff first. --dry-run shows the plan without editing.

  --verify <vN>
      Run engine integrity + the convergence gate + abi_audit. No edits.

Encodes the v1.5.11 promotion's hard-won gotchas so the next one can't trip them:
LF-normalized hashes (tools/verify_engine_integrity.canonical_sha256), the
basket_runner load-time self-check literal, the registry active_engine +
rollback roles, the convergence-gate version literals, the vault sync. The
convergence gate is the
final INDEPENDENT verifier -- it caught a mid-edit partial flip during v1.5.11.

ASCII-only output (Windows console); utf-8 on all file I/O. Protected infra
(Invariant #6): this tool EDITS engine selection surfaces but never commits.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_engine_integrity import canonical_sha256

ERE = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
VAULT = PROJECT_ROOT / "vault" / "engines" / "Universal_Research_Engine"
ENGINE_FILES = [
    "__init__.py", "contract.json", "engine_manifest.json", "evaluate_bar.py",
    "execution_emitter_stage1.py", "execution_loop.py", "main.py", "stage2_compiler.py",
]
HASHED_FILES = [f for f in ENGINE_FILES if f != "engine_manifest.json"]


def _dotted(vN: str) -> str:
    return vN.lstrip("v").replace("_", ".")


def _say(msg: str) -> None:
    print(f"  {msg}")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def _replace_once(path: Path, old: str, new: str, *, required: int = 1, dry: bool = False) -> bool:
    """Replace `old` with `new` in `path`, asserting it appears exactly `required`
    times (fail-loud on drift -- a silent no-op is how a partial flip hides)."""
    txt = _read(path)
    n = txt.count(old)
    if n != required:
        raise SystemExit(
            f"[FAIL] {path.relative_to(PROJECT_ROOT)}: expected {required} occurrence(s) "
            f"of:\n    {old!r}\n  but found {n}. Refusing to edit (drift or already flipped)."
        )
    if dry:
        _say(f"would edit {path.relative_to(PROJECT_ROOT)}: {old!r} -> {new!r}")
        return True
    _write(path, txt.replace(old, new))
    _say(f"edited {path.relative_to(PROJECT_ROOT)}")
    return True


# --------------------------------------------------------------------------- #
# Manifest re-stamp (LF hashes) + vault sync -- the engine-edit consistency fix
# --------------------------------------------------------------------------- #

def restamp_manifest(vN: str, *, freeze_date: str | None = None, promote: bool = False,
                     dry: bool = False) -> list[str]:
    d = ERE / vN
    man_path = d / "engine_manifest.json"
    if not man_path.exists():
        raise SystemExit(f"[FAIL] no manifest at {man_path}")
    man = json.loads(_read(man_path))
    changed: list[str] = []
    new_hashes = {f: canonical_sha256(d / f).upper() for f in HASHED_FILES}
    old_hashes = man.get("file_hashes", {})
    for f, h in new_hashes.items():
        if old_hashes.get(f, "").upper() != h:
            changed.append(f)
    man["file_hashes"] = new_hashes
    if promote:
        man["engine_status"] = "FROZEN"
        man["vaulted"] = True
        man["freeze_date"] = freeze_date
        man["promotion_date"] = freeze_date
    if dry:
        if changed:
            _say(f"would re-stamp {len(changed)} hash(es): {', '.join(changed)}")
        else:
            _say("hashes already current (no re-stamp needed)")
        return changed
    _write(man_path, json.dumps(man, indent=4) + "\n")
    _say(f"re-stamped manifest ({len(changed)} hash change(s): {', '.join(changed) or 'none'})")
    return changed


def sync_vault(vN: str, *, dry: bool = False) -> None:
    src, dst = ERE / vN, VAULT / vN
    if dry:
        _say(f"would sync vault {dst.relative_to(PROJECT_ROOT)} (8 files)")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for f in ENGINE_FILES:
        dst_f = dst / f
        dst_f.write_bytes((src / f).read_bytes())
    # Verify byte-parity (LF-normalized) so a vault drift can't slip through.
    bad = [f for f in ENGINE_FILES if canonical_sha256(src / f) != canonical_sha256(dst / f)]
    if bad:
        raise SystemExit(f"[FAIL] vault sync mismatch: {bad}")
    _say(f"vault synced + byte-verified ({dst.relative_to(PROJECT_ROOT)})")


# --------------------------------------------------------------------------- #
# Verification (the independent gate)
# --------------------------------------------------------------------------- #

def _run(cmd: list[str], label: str) -> bool:
    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    ok = r.returncode == 0
    _say(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        sys.stdout.write(r.stdout[-1500:])
        sys.stderr.write(r.stderr[-1500:])
    return ok


def verify(vN: str) -> bool:
    py = sys.executable
    results = [
        _run([py, "tools/verify_engine_integrity.py", "--mode", "strict"], "engine integrity (LF hashes)"),
        _run([py, "tools/abi_audit.py", "--pre-commit"], "abi_audit (all ABIs)"),
        _run([py, "-m", "pytest", "tests/test_engine_identity_convergence.py",
              f"tests/test_engine_abi_{vN}.py", "-q"], "convergence gate + ABI identity"),
    ]
    return all(results)


# --------------------------------------------------------------------------- #
# Full promotion flip (every identity surface)
# --------------------------------------------------------------------------- #

def current_canonical() -> str:
    from config.engine_authority import CANONICAL_SINGLE_ASSET_ENGINE
    return CANONICAL_SINGLE_ASSET_ENGINE


def flip_surfaces(vOLD: str, vNEW: str, freeze_date: str, *, dry: bool) -> None:
    dOLD, dNEW = _dotted(vOLD), _dotted(vNEW)

    _say("[1/8] freeze ENGINE_STATUS")
    _replace_once(ERE / vNEW / "execution_loop.py",
                  'ENGINE_STATUS     = "EXPERIMENTAL"', 'ENGINE_STATUS     = "FROZEN"',
                  required=1, dry=dry)

    _say("[2/8] engine_authority pointers")
    auth = PROJECT_ROOT / "config" / "engine_authority.py"
    _replace_once(auth, f'CANONICAL_ENGINE_ABI = "engine_abi.{vOLD}"',
                  f'CANONICAL_ENGINE_ABI = "engine_abi.{vNEW}"', required=1, dry=dry)
    _replace_once(auth, f'CANONICAL_SINGLE_ASSET_ENGINE = "{vOLD}"',
                  f'CANONICAL_SINGLE_ASSET_ENGINE = "{vNEW}"', required=1, dry=dry)

    _say("[3/8] basket_runner import + self-check")
    br = PROJECT_ROOT / "tools" / "basket_runner.py"
    _replace_once(br, f"from engine_abi.{vOLD} import (", f"from engine_abi.{vNEW} import (",
                  required=1, dry=dry)
    _replace_once(br, f'ENGINE_ABI == "engine_abi.{vOLD}"', f'ENGINE_ABI == "engine_abi.{vNEW}"',
                  required=1, dry=dry)

    _say("[4/8] convergence-test literals")
    ct = PROJECT_ROOT / "tests" / "test_engine_identity_convergence.py"
    _replace_once(ct, f"from engine_abi.{vOLD} import ENGINE_VERSION",
                  f"from engine_abi.{vNEW} import ENGINE_VERSION", required=1, dry=dry)
    _replace_once(ct, f'ENGINE_ABI == "engine_abi.{vOLD}"', f'ENGINE_ABI == "engine_abi.{vNEW}"',
                  required=1, dry=dry)
    _replace_once(ct, f'ENGINE_VERSION) == "{dOLD}"', f'ENGINE_VERSION) == "{dNEW}"',
                  required=1, dry=dry)
    if f'"{vNEW}": "{dNEW}"' not in _read(ct):
        _replace_once(ct, f'"{vOLD}": "{dOLD}"]', f'"{vOLD}": "{dOLD}", "{vNEW}": "{dNEW}"]',
                      required=1, dry=dry)

    _say("[5/8] registry active_engine (canonical) + rollback roles")
    flip_registry(vOLD, vNEW, freeze_date, dry=dry)

    _say("[6/8] freeze manifest + LF-hash re-stamp")
    restamp_manifest(vNEW, freeze_date=freeze_date, promote=True, dry=dry)

    _say("[7/8] vault snapshot")
    sync_vault(vNEW, dry=dry)

    _say("[8/8] abi rehash + guard regen")
    if dry:
        _say("would: abi_audit --rehash + generate_guard_manifest")
    else:
        _run([sys.executable, "tools/abi_audit.py", "--rehash", "--abi-version", vNEW], "abi rehash")
        _run([sys.executable, "tools/generate_guard_manifest.py"], "guard manifest regen")


def flip_registry(vOLD: str, vNEW: str, freeze_date: str, *, dry: bool) -> None:
    """Update the registry's two named roles: active_engine (canonical) = vNEW,
    and rollback = the prior canonical (vOLD). The registry is METADATA naming
    the canonical + rollback engines, NOT a candidate list -- the engines{} map
    was retired in the engine consolidation (2026-06-30) and runtime engine
    selection is forbidden (tools/engine_resolver validates the canonical engine,
    it never selects among versions)."""
    reg_path = PROJECT_ROOT / "config" / "engine_registry.json"
    reg = json.loads(_read(reg_path))
    reg["active_engine"] = vNEW
    reg["rollback"] = vOLD
    reg["freeze_date"] = freeze_date
    reg.pop("engines", None)  # candidate-list map retired (consolidation 2026-06-30)
    if dry:
        _say(f"would set active_engine={vNEW} (canonical), rollback={vOLD}")
        return
    _write(reg_path, json.dumps(reg, indent=2) + "\n")
    _say(f"registry: active_engine={vNEW} (canonical); rollback={vOLD}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Smooth engine promotion / freeze re-stamp.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--restamp", metavar="vN", help="re-stamp manifest hashes + vault after an engine edit")
    g.add_argument("--promote", metavar="vNEW", help="flip canonical to vNEW across all surfaces")
    g.add_argument("--verify", metavar="vN", help="run integrity + convergence gate + abi_audit")
    ap.add_argument("--freeze-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, edit nothing")
    args = ap.parse_args()
    freeze_date = args.freeze_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.verify:
        print(f"[VERIFY] {args.verify}")
        return 0 if verify(args.verify) else 1

    if args.restamp:
        vN = args.restamp
        print(f"[RESTAMP] {vN}{' (dry-run)' if args.dry_run else ''}")
        restamp_manifest(vN, dry=args.dry_run)
        sync_vault(vN, dry=args.dry_run)
        if args.dry_run:
            return 0
        ok = verify(vN)
        print(f"[RESTAMP] {'OK -- review the diff, then commit.' if ok else 'FAILED -- see above.'}")
        return 0 if ok else 1

    # --promote
    vNEW = args.promote
    vOLD = current_canonical()
    if vOLD == vNEW:
        raise SystemExit(f"[FAIL] {vNEW} is already the canonical engine.")
    print(f"[PROMOTE] {vOLD} -> {vNEW}  (freeze_date={freeze_date}){' (dry-run)' if args.dry_run else ''}")
    print("  NOTE: byte-identical trades are the CALLER's responsibility (run the parity")
    print("        harness before promoting). This tool flips identity surfaces + verifies.")
    flip_surfaces(vOLD, vNEW, freeze_date, dry=args.dry_run)
    if args.dry_run:
        print("[PROMOTE] dry-run complete -- no files changed.")
        return 0
    ok = verify(vNEW)
    print(f"[PROMOTE] {'OK -- review the diff, then commit.' if ok else 'GATE FAILED -- see above; fix or revert.'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
