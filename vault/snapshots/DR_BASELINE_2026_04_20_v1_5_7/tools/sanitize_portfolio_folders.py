"""One-shot migration: rename legacy PF_* portfolio folders to the canonical
format emitted by tools.portfolio_core.build_portfolio_name.

Canonical: PF_<HEX12>_<ID><FAMILY>_<ASSET_CLASS>_<SYMBOL>[_P<NN>]

The legacy HEX12 is preserved verbatim (it's the stable identity of the
composite; regenerating it from child-folder metadata would change the hash
because per-folder run_id sets differ from the parent's). Only the suffix is
rebuilt, with asset_class injected between <ID><FAMILY> and <SYMBOL>.

Safety:
  - Dry-run by default. `--apply` to actually rename.
  - Skips folders already canonical, skips bare hashes (no identity to derive),
    skips experimental namespaces (R05_EXEC_PROFILES_*), skips collisions.
  - Logs the full rename map to outputs/logs/portfolio_folder_sanitize_<ts>.json.
  - Atomic: uses os.replace.

Usage:
    python tools/sanitize_portfolio_folders.py                    # dry run
    python tools/sanitize_portfolio_folders.py --apply            # rename
    python tools/sanitize_portfolio_folders.py --root <dir>       # non-default
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.asset_classification import parse_strategy_name
from tools.portfolio_core.deterministic import (
    _assemble_canonical_portfolio_name,
    parse_portfolio_name,
)

DEFAULT_BACKTESTS_ROOT = PROJECT_ROOT.parent / "TradeScan_State" / "backtests"
LOG_DIR = PROJECT_ROOT / "outputs" / "logs"
MIGRATION_MANIFEST_NAME = "_migration_manifest.json"

_HEX12_PREFIX_RE = re.compile(r"^PF_(?P<hex>[0-9A-F]{12})(?:_|$)")
_EXPERIMENTAL_MARKERS = ("_R05_EXEC_PROFILES_", "_R0")


def _classify_legacy(folder_name: str) -> str:
    """Return a short shape tag for logging. Non-exhaustive — just enough to
    dispatch migration decisions."""
    if parse_portfolio_name(folder_name) is not None:
        return "ALREADY_CANONICAL"
    if not _HEX12_PREFIX_RE.match(folder_name):
        return "NOT_PF"
    parts = folder_name.split("_")
    if len(parts) == 2:
        return "BARE_HASH"
    if any(m in folder_name for m in _EXPERIMENTAL_MARKERS):
        return "EXPERIMENTAL"
    return "LEGACY_SUFFIXED"


def _identity_from_strategy_name(strat_name: str, symbol_hint: str | None = None) -> dict | None:
    fields = parse_strategy_name(strat_name)
    if not fields:
        return None
    return {
        "directive_id": fields["idea_id"],
        "family": fields["family"],
        "slot3": fields["symbol"],   # SLOT-3 in the strategy name
        "symbol": str(symbol_hint or fields.get("symbol_suffix") or fields["symbol"]).upper(),
        "patch_id": fields["param_set"],  # already 'P<NN>'
    }


def _derive_identity_from_metadata(folder: Path) -> dict | None:
    """Read folder/metadata/run_metadata.json and parse strategy_name into
    identity tokens. Returns None if the metadata is missing or unparseable."""
    meta_path = folder / "metadata" / "run_metadata.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    strat_name = str(meta.get("strategy_name", "")).strip()
    if not strat_name:
        return None
    return _identity_from_strategy_name(strat_name, symbol_hint=meta.get("symbol"))


def _derive_identity_from_trade_csv(folder: Path) -> dict | None:
    """Fallback for composite PF_* folders (NON_PIPELINE_ARTIFACT) which lack a
    root run_metadata.json but carry per-row strategy_name in results_tradelevel.csv.

    Reads the first row only. If multiple distinct strategies co-exist in the
    same composite, returns None (ambiguous — caller treats as opaque)."""
    csv_path = folder / "raw" / "results_tradelevel.csv"
    if not csv_path.exists():
        return None
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            first = next(reader, None)
            if first is None:
                return None
            # Scan up to 500 rows to check for ambiguity (multi-strategy composites)
            strat_names = {str(first.get("strategy_name", "")).strip()}
            symbols = {str(first.get("symbol", "")).strip()}
            for i, row in enumerate(reader):
                if i >= 500:
                    break
                strat_names.add(str(row.get("strategy_name", "")).strip())
                symbols.add(str(row.get("symbol", "")).strip())
    except Exception:
        return None

    strat_names.discard("")
    symbols.discard("")
    if len(strat_names) != 1 or not strat_names:
        return None  # ambiguous or empty
    strat_name = next(iter(strat_names))
    symbol_hint = next(iter(symbols)) if len(symbols) == 1 else None
    return _identity_from_strategy_name(strat_name, symbol_hint=symbol_hint)


def _plan_rename(folder: Path) -> dict:
    """Plan what to do with one folder. Returns a dict with action + reason.

    Bucketing (for the migration manifest):
      - Bucket A (recoverable=true): identity derived from structured metadata
        or from per-row strategy_name in results_tradelevel.csv. Safe to migrate.
      - Bucket B (recoverable=false): LEGACY_OPAQUE. No identity signal
        available. Must NOT be renamed; flag for downstream exclusion.
    """
    name = folder.name
    shape = _classify_legacy(name)

    if shape == "ALREADY_CANONICAL":
        return {"folder": name, "action": "skip", "reason": "already_canonical",
                "recoverable": True, "identity_source": "canonical_name"}
    if shape == "BARE_HASH":
        return {"folder": name, "action": "skip", "reason": "bare_hash_no_identity",
                "recoverable": False, "identity_source": None,
                "legacy_tag": "LEGACY_OPAQUE"}
    if shape == "EXPERIMENTAL":
        return {"folder": name, "action": "skip", "reason": "experimental_namespace",
                "recoverable": False, "identity_source": None,
                "legacy_tag": "LEGACY_OPAQUE"}
    if shape == "NOT_PF":
        return {"folder": name, "action": "skip", "reason": "not_pf_prefix",
                "recoverable": False, "identity_source": None}

    # LEGACY_SUFFIXED — derive identity
    m = _HEX12_PREFIX_RE.match(name)
    if not m:
        return {"folder": name, "action": "skip", "reason": "hex_prefix_not_found",
                "recoverable": False, "identity_source": None}
    legacy_hex = f"PF_{m.group('hex')}"

    identity = _derive_identity_from_metadata(folder)
    identity_source = "metadata" if identity else None
    if identity is None:
        identity = _derive_identity_from_trade_csv(folder)
        if identity is not None:
            identity_source = "trade_csv"

    if identity is None:
        return {"folder": name, "action": "manual_review",
                "reason": "cannot_derive_identity_from_metadata_or_trade_csv",
                "recoverable": False, "identity_source": None,
                "legacy_tag": "LEGACY_OPAQUE"}

    try:
        canonical = _assemble_canonical_portfolio_name(
            hex_id=legacy_hex,
            directive_id=identity["directive_id"],
            family=identity["family"],
            slot3=identity["slot3"],
            symbol=identity["symbol"],
            patch_id=identity["patch_id"],
        )
    except ValueError as exc:
        return {"folder": name, "action": "manual_review",
                "reason": f"format_error: {exc}",
                "recoverable": False, "identity_source": identity_source}

    if canonical == name:
        return {"folder": name, "action": "skip", "reason": "already_matches_canonical",
                "recoverable": True, "identity_source": identity_source}

    # Trade-CSV-derived identity: classify as recoverable but do NOT auto-rename.
    # User requires a deliberate second pass; these carry weaker provenance than
    # root-metadata folders (composites, no directive_id linkage at root level).
    if identity_source == "trade_csv":
        return {
            "folder": name,
            "action": "manual_review",
            "reason": "recoverable_via_trade_csv_awaits_approval",
            "target_candidate": canonical,
            "identity": identity,
            "recoverable": True,
            "identity_source": "trade_csv",
        }

    return {
        "folder": name,
        "action": "rename",
        "target": canonical,
        "reason": "legacy_shape_upgraded_to_canonical",
        "identity": identity,
        "recoverable": True,
        "identity_source": "metadata",
    }


def _run(root: Path, apply: bool) -> dict:
    if not root.exists():
        raise SystemExit(f"[sanitize] backtests root not found: {root}")

    entries = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("PF_"))
    plans = [_plan_rename(p) for p in entries]

    # Collision check: no two sources may produce the same target.
    target_to_source: dict[str, str] = {}
    for plan in plans:
        if plan["action"] != "rename":
            continue
        t = plan["target"]
        if t in target_to_source:
            plan["action"] = "manual_review"
            plan["reason"] = f"collision_with_{target_to_source[t]}"
        elif (root / t).exists():
            plan["action"] = "manual_review"
            plan["reason"] = "target_exists_on_disk"
        else:
            target_to_source[t] = plan["folder"]

    counts = {"rename": 0, "skip": 0, "manual_review": 0}
    for plan in plans:
        counts[plan["action"]] = counts.get(plan["action"], 0) + 1

    # Perform renames
    renames_done = 0
    if apply:
        for plan in plans:
            if plan["action"] != "rename":
                continue
            src = root / plan["folder"]
            dst = root / plan["target"]
            try:
                os.replace(src, dst)
                plan["renamed"] = True
                renames_done += 1
            except OSError as exc:
                plan["action"] = "manual_review"
                plan["reason"] = f"os_replace_failed: {exc}"

    # Bucket classification for downstream consumers (aggregation, comparison).
    buckets = {"recoverable": 0, "opaque": 0, "canonical": 0}
    for plan in plans:
        if plan["action"] == "skip" and plan["reason"] == "already_canonical":
            buckets["canonical"] += 1
        elif plan.get("recoverable") is True:
            buckets["recoverable"] += 1
        else:
            buckets["opaque"] += 1

    log = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "apply": apply,
        "counts": counts,
        "buckets": buckets,
        "renames_executed": renames_done,
        "plans": plans,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"portfolio_folder_sanitize_{int(datetime.now(timezone.utc).timestamp())}.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    log["log_path"] = str(log_path)

    # Migration manifest — audit layer co-located with the backtests root.
    # Entry shape: {old_name, status, recoverable, identity_source, notes, target}
    manifest_path = root / MIGRATION_MANIFEST_NAME
    manifest_entries = []
    for plan in plans:
        notes = plan.get("reason", "")
        if plan.get("legacy_tag") == "LEGACY_OPAQUE":
            notes = f"LEGACY_OPAQUE: {notes}"
        entry = {
            "old_name": plan["folder"],
            "status": plan["action"],  # rename | skip | manual_review
            "recoverable": bool(plan.get("recoverable", False)),
            "identity_source": plan.get("identity_source"),
            "notes": notes,
        }
        # Prefer the actual rename target; otherwise surface the candidate
        # (for trade_csv recoverables awaiting approval).
        if "target" in plan:
            entry["target"] = plan["target"]
        elif "target_candidate" in plan:
            entry["target_candidate"] = plan["target_candidate"]
        manifest_entries.append(entry)

    manifest = {
        "schema_version": "1.0",
        "generated_utc": log["timestamp_utc"],
        "apply": apply,
        "source_root": str(root),
        "buckets": buckets,
        "entries": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log["manifest_path"] = str(manifest_path)
    return log


def _format_summary(log: dict) -> str:
    b = log.get("buckets", {})
    lines = [
        f"[sanitize] root={log['root']} apply={log['apply']}",
        f"[sanitize] counts: rename={log['counts'].get('rename',0)} "
        f"skip={log['counts'].get('skip',0)} "
        f"manual_review={log['counts'].get('manual_review',0)}",
        f"[sanitize] buckets: canonical={b.get('canonical',0)} "
        f"recoverable={b.get('recoverable',0)} "
        f"opaque(LEGACY_OPAQUE)={b.get('opaque',0)}",
        f"[sanitize] renames_executed={log['renames_executed']}",
        f"[sanitize] log: {log['log_path']}",
        f"[sanitize] manifest: {log.get('manifest_path','<none>')}",
    ]
    # Show first 10 renames + first 5 manual reviews
    renames = [p for p in log["plans"] if p["action"] == "rename"][:10]
    manuals = [p for p in log["plans"] if p["action"] == "manual_review"][:5]
    if renames:
        lines.append("")
        lines.append("  RENAME MAP (first 10):")
        for p in renames:
            lines.append(f"    {p['folder']}  ->  {p['target']}")
    if manuals:
        lines.append("")
        lines.append("  MANUAL REVIEW (first 5):")
        for p in manuals:
            lines.append(f"    {p['folder']}  [{p['reason']}]")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually rename. Default is dry-run.")
    parser.add_argument("--root", type=Path, default=DEFAULT_BACKTESTS_ROOT,
                        help="Backtests root (default: ../TradeScan_State/backtests)")
    args = parser.parse_args()

    log = _run(args.root, apply=args.apply)
    print(_format_summary(log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
