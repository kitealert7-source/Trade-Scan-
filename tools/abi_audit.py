"""abi_audit.py — Triple-gate enforcer for engine_abi manifests.

Single tool, three modes, all fail-closed:
  --pre-commit   Block commits when manifest drifts from package or consumers.
  --ci           Full PR check; updates last_verified_commit / _utc on success.
  --rehash       Recompute and stamp manifest_sha256 after a deliberate manual edit.
  --dead-exports Informational audit: consumer_count==0 or stale last_verified.

Requires --abi-version <ver> (currently only v1_5_9 — v1_5_3 retired in
plan v11). The CLI keeps `--abi-version` plural-capable so re-introducing a
parallel ABI later doesn't require a tool rewrite. Plan: H2_ENGINE_PROMOTION_PLAN.md
Section 1l, 6.8, Phase 0a Step 4.

Invariants checked:
  1. manifest_sha256 matches the recomputed sha256 of the canonical
     (manifest_sha256-stripped) YAML serialization.
  2. For every export: consumer_count == len(consumed_by).
  3. For every export: each `consumed_by` entry resolves to a real file
     that imports the export, either via `from engine_abi.<ver> import <name>`
     (post-migration form) or `from <source_module> import <name>`
     (pre-migration form). Either is acceptable.
  4. engine_abi.<ver>.__all__ equals [e.name for e in exports] in order.
  5. (--ci only) last_verified_commit + last_verified_utc updated for each
     export that newly verifies, then re-stamped manifest_sha256.

Exit codes:
  0   all gates green
  1   drift detected (FAIL-CLOSED)
  2   tool misuse (bad args, missing manifest, etc.)
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config.path_authority import REAL_REPO_ROOT, TS_EXECUTION  # noqa: E402

_GOVERNANCE_DIR = REAL_REPO_ROOT / "governance"
_ABI_PKG_DIR = REAL_REPO_ROOT / "engine_abi"

_SUPPORTED_ABIS = ("v1_5_9",)

# Maps the leading segment of a `consumed_by` dotted path to a filesystem root.
_REPO_ROOTS = {
    "Trade_Scan": REAL_REPO_ROOT,
    "TS_Execution": TS_EXECUTION,
}


# ---------------------------------------------------------------------------
# Manifest IO + canonical hash
# ---------------------------------------------------------------------------


def _manifest_path(abi_version: str) -> Path:
    return _GOVERNANCE_DIR / f"engine_abi_{abi_version}_manifest.yaml"


def _load_manifest(abi_version: str) -> dict[str, Any]:
    path = _manifest_path(abi_version)
    if not path.is_file():
        _die(2, f"manifest not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _dump_manifest(abi_version: str, manifest: dict[str, Any]) -> None:
    path = _manifest_path(abi_version)
    # Preserve the existing file header (comment lines before the YAML root).
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    header_lines: list[str] = []
    for line in original.splitlines():
        if line.strip().startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    header = "\n".join(header_lines)
    if header and not header.endswith("\n"):
        header += "\n"
    body = yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False)
    path.write_text(header + body, encoding="utf-8")


def _canonical_hash(manifest: dict[str, Any]) -> str:
    """sha256 of canonical YAML serialization minus the manifest_sha256 field."""
    stripped = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    canon = yaml.safe_dump(stripped, sort_keys=False, default_flow_style=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Consumer-path verification
# ---------------------------------------------------------------------------


def _resolve_consumer_path(consumer_dotted: str) -> Path | None:
    parts = consumer_dotted.split(".")
    if not parts:
        return None
    repo_key = parts[0]
    if repo_key not in _REPO_ROOTS:
        return None
    repo_root = _REPO_ROOTS[repo_key]
    if repo_root is None or not Path(repo_root).exists():
        return None
    sub = "/".join(parts[1:])
    return Path(repo_root) / f"{sub}.py"


def _consumer_imports(consumer_path: Path, export_name: str,
                      abi_version: str, source_module: str) -> bool:
    """True if consumer file imports export_name via ABI or legacy form.

    Accepts any of:
      from engine_abi.<ver> import <name>
      from engine_abi.<ver> import <name> as <alias>
      from engine_abi.<ver> import (..., <name>, ...)
      from <source_module> import <name>          (legacy form)
      from <source_module> import <name> as <alias>
      from <source_module> import (..., <name>, ...)
      from engine_abi import <ver> [as ...]        (then `<ver>.<name>` access)
      import engine_abi.<ver> [as ...]             (then `<alias>.<name>` access)

    AST parsing is the source of truth — handles parenthesized multi-line
    imports natively. Falls back to False on syntax errors (which is itself
    a real problem the audit should report).
    """
    if not consumer_path.is_file():
        return False
    try:
        text = consumer_path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False

    abi_module = f"engine_abi.{abi_version}"
    # Aliases of the abi sub-module that, when present, mean later `alias.<export>`
    # access is implicit consumption (e.g., `from engine_abi import v1_5_9 as abi`).
    sub_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                if mod == abi_module and alias.name == export_name:
                    return True
                if mod == source_module and alias.name == export_name:
                    return True
                if mod == "engine_abi" and alias.name == abi_version:
                    sub_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == abi_module:
                    sub_aliases.add(alias.asname or abi_version)

    if not sub_aliases:
        return False

    # Look for any attribute access of the form `<alias>.<export_name>` on a
    # known sub_alias. This catches `abi.evaluate_bar` after
    # `from engine_abi import v1_5_9 as abi`.
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == export_name:
            base = node.value
            if isinstance(base, ast.Name) and base.id in sub_aliases:
                return True
    return False


# ---------------------------------------------------------------------------
# Package __all__ check
# ---------------------------------------------------------------------------


def _package_all(abi_version: str) -> list[str] | None:
    init_path = _ABI_PKG_DIR / abi_version / "__init__.py"
    if not init_path.is_file():
        return None
    text = init_path.read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[([^\]]+)\]", text)
    if not m:
        return None
    body = m.group(1)
    return [tok.strip().strip("'\"") for tok in body.split(",") if tok.strip()]


# ---------------------------------------------------------------------------
# Verification core
# ---------------------------------------------------------------------------


def _verify(manifest: dict[str, Any], abi_version: str, *,
            require_hash_match: bool) -> list[str]:
    errors: list[str] = []

    # (1) manifest_sha256
    expected = _canonical_hash(manifest)
    stored = manifest.get("manifest_sha256")
    if require_hash_match and stored != expected:
        errors.append(
            f"manifest_sha256 mismatch: stored={stored!r} expected={expected!r}. "
            f"Run `python tools/abi_audit.py --rehash --abi-version {abi_version}`."
        )

    exports = manifest.get("exports", [])

    # (2) consumer_count == len(consumed_by) per export
    for e in exports:
        cb = e.get("consumed_by", []) or []
        cc = e.get("consumer_count")
        if cc != len(cb):
            errors.append(
                f"export {e.get('name')!r}: consumer_count={cc} but "
                f"len(consumed_by)={len(cb)}."
            )

    # (3) each consumed_by entry imports the export from ABI or source
    for e in exports:
        name = e.get("name")
        src = e.get("source_module", "")
        for consumer in e.get("consumed_by", []) or []:
            cpath = _resolve_consumer_path(consumer)
            if cpath is None:
                errors.append(
                    f"export {name!r}: consumed_by={consumer!r} has no resolvable "
                    f"filesystem path (unknown repo prefix?)."
                )
                continue
            if not cpath.is_file():
                errors.append(
                    f"export {name!r}: consumed_by={consumer!r} -> {cpath} "
                    f"does not exist."
                )
                continue
            if not _consumer_imports(cpath, name, abi_version, src):
                errors.append(
                    f"export {name!r}: consumed_by={consumer!r} -> {cpath} "
                    f"does not import {name!r} from engine_abi.{abi_version} or {src}."
                )

    # (4) package __all__ matches manifest exports
    pkg_all = _package_all(abi_version)
    declared = [e["name"] for e in exports]
    if pkg_all is None:
        errors.append(
            f"engine_abi/{abi_version}/__init__.py: __all__ not parseable."
        )
    elif pkg_all != declared:
        errors.append(
            f"engine_abi.{abi_version} __all__ != manifest exports.\n"
            f"  __all__:  {pkg_all}\n"
            f"  manifest: {declared}"
        )

    return errors


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------


def _mode_rehash(abi_version: str) -> int:
    manifest = _load_manifest(abi_version)
    manifest["manifest_sha256"] = _canonical_hash(manifest)
    _dump_manifest(abi_version, manifest)
    print(
        f"[abi-audit] rehashed manifest engine_abi_{abi_version}_manifest.yaml -> "
        f"{manifest['manifest_sha256']}"
    )
    return 0


def _mode_check(abi_version: str, *, label: str,
                update_verified: bool) -> int:
    manifest = _load_manifest(abi_version)
    errors = _verify(manifest, abi_version, require_hash_match=True)
    if errors:
        print(f"[abi-audit {label}] FAIL-CLOSED engine_abi.{abi_version}:")
        for e in errors:
            print(f"  - {e}")
        return 1
    if update_verified:
        head = _git_head_sha()
        now_utc = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for e in manifest["exports"]:
            e["last_verified_commit"] = head
            e["last_verified_utc"] = now_utc
        manifest["manifest_sha256"] = _canonical_hash(manifest)
        _dump_manifest(abi_version, manifest)
        print(
            f"[abi-audit {label}] OK engine_abi.{abi_version} "
            f"(last_verified updated to {head[:7]}@{now_utc})"
        )
    else:
        print(f"[abi-audit {label}] OK engine_abi.{abi_version}")
    return 0


def _mode_dead_exports(abi_version: str, *, stale_days: int) -> int:
    manifest = _load_manifest(abi_version)
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    orphans: list[str] = []
    stale: list[str] = []
    for e in manifest.get("exports", []):
        name = e.get("name")
        cc = e.get("consumer_count", 0)
        if cc == 0:
            orphans.append(name)
        ts = e.get("last_verified_utc")
        if ts:
            try:
                t = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=_dt.timezone.utc
                )
                if (now - t).days > stale_days:
                    stale.append(f"{name} (last_verified={ts})")
            except ValueError:
                stale.append(f"{name} (unparseable last_verified_utc={ts!r})")
    print(f"[abi-audit dead-exports] engine_abi.{abi_version}")
    print(f"  orphans (consumer_count==0):  {orphans or 'none'}")
    print(f"  stale (> {stale_days}d unverified): {stale or 'none'}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_head_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REAL_REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def _die(code: int, msg: str) -> None:
    print(f"[abi-audit] {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="engine_abi triple-gate enforcer")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pre-commit", action="store_true",
                   help="Pre-commit hook mode (verify-only, no manifest writes)")
    g.add_argument("--ci", action="store_true",
                   help="CI mode (verify + update last_verified_* on success)")
    g.add_argument("--rehash", action="store_true",
                   help="Recompute and stamp manifest_sha256 after a manual edit")
    g.add_argument("--dead-exports", action="store_true",
                   help="Informational: list orphan + stale exports")
    p.add_argument("--abi-version", required=False, default=None,
                   choices=list(_SUPPORTED_ABIS),
                   help="ABI version to operate on (default: all)")
    p.add_argument("--stale-days", type=int, default=90,
                   help="Threshold for --dead-exports staleness (default 90)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    versions = (args.abi_version,) if args.abi_version else _SUPPORTED_ABIS
    rc = 0
    for v in versions:
        if args.rehash:
            rc |= _mode_rehash(v)
        elif args.pre_commit:
            rc |= _mode_check(v, label="pre-commit", update_verified=False)
        elif args.ci:
            rc |= _mode_check(v, label="ci", update_verified=True)
        elif args.dead_exports:
            rc |= _mode_dead_exports(v, stale_days=args.stale_days)
    return rc


if __name__ == "__main__":
    sys.exit(main())
