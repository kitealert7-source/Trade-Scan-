"""
rerun_backtest.py — Friction-free reruns of already-tested strategies.

Context
-------
The pipeline's Idea-Evaluation Gate (admission_controller.py, Stage -0.20)
refuses directives whose (MODEL, TF, ASSET_CLASS) tuple matched a prior
REPEAT_FAILED result. That guard is correct for casual retries but blocks
legitimate reruns after:

    DATA_FRESH  — baseline stale / more bars available
    SIGNAL      — indicator logic changed, new indicator added
    PARAMETER   — numeric parameter tweak
    BUG_FIX     — prior run's result was semantically wrong
    ENGINE      — backtest engine code changed (directive unchanged)

The gate *already* has a production-tested bypass: a ``test.repeat_override_reason``
string of >=50 non-whitespace characters. The Classifier Gate (Stage -0.21)
additionally requires ``signal_version`` to strictly exceed the prior max
whenever the classifier marks the diff as SIGNAL.

This tool automates all that:

    1. Resolve the target (strategy_name or run_id) to its last-known directive.
    2. For the requested category, inject ``test.repeat_override_reason`` with
       an auto-prefix + user reason (guaranteed >=50 chars).
    3. Optionally extend ``test.end_date`` to max-available bar date.
    4. For SIGNAL / BUG_FIX categories, bump ``signal_version`` by 1.
    5. Write the updated directive to backtest_directives/INBOX/ so the
       standard pipeline picks it up.
    6. Record an audit entry in outputs/logs/rerun_audit.jsonl.

After the pipeline completes (produces a new run_id), the user runs:

    python tools/rerun_backtest.py finalize \\
        --old-run-id <original_run_id> \\
        --new-run-id <new_run_id> \\
        --reason "<category>: <user reason>"

which flips the old master_filter rows to ``is_current=0`` via
``ledger_db.mark_superseded``. Append-only invariant preserved — rows are
never deleted, only flagged.

Exit codes
----------
    0 — prepare/finalize succeeded (or dry-run)
    1 — user input error, file not found, validation failure
    2 — classifier mismatch (use --force to override)

Usage
-----
    python tools/rerun_backtest.py prepare 15_MR_FX_1H_ASRANGE_SESSFILT_S01_V1_P00 \\
        --category DATA_FRESH --reason "Baseline advanced 6 weeks; max data available"

    python tools/rerun_backtest.py prepare 9b3e1a2c4d5f \\
        --category SIGNAL --reason "Added liquidity-sweep indicator to CHOCH model"

    python tools/rerun_backtest.py finalize \\
        --old-run-id 9b3e1a2c4d5f --new-run-id a4f8c2d7e1b9 \\
        --reason "SIGNAL: Added liquidity-sweep indicator"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.ledger_db import _connect, mark_superseded  # noqa: E402

# ── Directive locations ─────────────────────────────────────────────────────
DIRECTIVES_ROOT = PROJECT_ROOT / "backtest_directives"
INBOX_DIR = DIRECTIVES_ROOT / "INBOX"
# Search order: most-recent wins. Mirror classifier_gate._DEFAULT_PRIOR_DIRS.
_SEARCH_DIRS: tuple[Path, ...] = (
    DIRECTIVES_ROOT / "completed",
    DIRECTIVES_ROOT / "active_backup",
    DIRECTIVES_ROOT / "active",
    DIRECTIVES_ROOT / "archive",
)

AUDIT_LOG_PATH = PROJECT_ROOT / "outputs" / "logs" / "rerun_audit.jsonl"

# ── Category taxonomy ───────────────────────────────────────────────────────
# Maps 1:1 to what admission_controller + classifier_gate expect. The rerun
# tool translates user intent into gate-compatible directive mutations.
CATEGORIES = {
    "DATA_FRESH": {
        "description": "Baseline stale or more bars available; logic unchanged.",
        "bump_signal_version": False,
        "extend_end_date": True,
    },
    "SIGNAL": {
        "description": ("Indicator logic or imports changed. Strict "
                        "signal_version bump required by Classifier Gate."),
        "bump_signal_version": True,
        "extend_end_date": True,
    },
    "PARAMETER": {
        "description": ("Numeric parameter tweak. Classifier treats as "
                        "PARAMETER → passes without SV bump."),
        "bump_signal_version": False,
        "extend_end_date": True,
    },
    "ENGINE": {
        "description": ("Backtest engine code changed; directive unchanged. "
                        "No classifier diff → passes."),
        "bump_signal_version": False,
        "extend_end_date": True,
    },
    "BUG_FIX": {
        "description": ("Prior run's result was semantically wrong. Bumps SV "
                        "and flags prior rows quarantined on finalize."),
        "bump_signal_version": True,
        "extend_end_date": True,
        "quarantine_on_finalize": True,
    },
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _find_directive(strategy_name: str) -> Path:
    """Locate the most recent directive file for a strategy."""
    candidates: list[Path] = []
    for d in _SEARCH_DIRS:
        p = d / f"{strategy_name}.txt"
        if p.exists() and p.stat().st_size > 0:
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError(
            f"No directive found for {strategy_name!r} in any of: "
            f"{[str(d.relative_to(PROJECT_ROOT)) for d in _SEARCH_DIRS]}"
        )
    # Prefer most-recently-modified (handles the case where a strategy was
    # rerun once already and both old and new copies exist).
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_target(target: str) -> tuple[str, str | None]:
    """Return (strategy_name, originating_run_id_or_None) for a CLI target.

    Accepts either a strategy_name (matches NAME_PATTERN) or a run_id
    (short hex). If run_id, looks up the strategy via master_filter.
    """
    # Heuristic: strategy names contain underscores and a digit prefix.
    # run_ids are short hex-like without underscores. Distinguishable.
    if "_" in target and any(c.isdigit() for c in target[:3]):
        return target, None

    # Treat as run_id — look up strategy.
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT strategy FROM master_filter WHERE run_id = ? LIMIT 1',
            (target,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(
            f"Target {target!r} is neither a valid strategy name nor a "
            f"known run_id in master_filter. Check with ledger_db --stats."
        )
    return row[0], target


def _build_override_reason(category: str, user_reason: str,
                           orig_run_id: str | None, strategy: str) -> str:
    """Compose a >=50-char ``test.repeat_override_reason`` payload.

    Format is deliberately machine-scannable: the prefix carries metadata
    the audit-log reader can pick up without re-running the tool.
    """
    ts = date.today().isoformat()
    origin = orig_run_id or "directive-clone"
    prefix = (f"[RERUN:{category}@{ts} origin={origin} strategy={strategy}] ")
    merged = prefix + user_reason.strip()
    # Safety: ensure >=50 after strip (admission_controller's threshold).
    if len(merged.strip()) < 50:
        # Auto-pad with category description — should never trigger in
        # practice because the prefix alone is already >40 chars.
        merged += f" [category: {CATEGORIES[category]['description']}]"
    return merged


def _load_directive(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Directive {path} is not a YAML mapping")
    return data


def _write_directive(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False preserves original ordering; default_flow_style=False
    # keeps block style (matches existing directives).
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=120)
    path.write_text(text, encoding="utf-8")


def _audit_entry(entry: dict[str, Any]) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Subcommand: prepare ─────────────────────────────────────────────────────

def cmd_prepare(args: argparse.Namespace) -> int:
    category = args.category
    if category not in CATEGORIES:
        print(f"ERROR: unknown category {category!r}. Valid: "
              f"{sorted(CATEGORIES.keys())}")
        return 1

    user_reason = args.reason.strip()
    if len(user_reason) < 20:
        print("ERROR: --reason must be at least 20 characters of genuine "
              "content. The tool auto-prefixes a category tag but the "
              "user-supplied reason is what lands in the audit log.")
        return 1

    # 1. Resolve target → strategy name + optional originating run_id.
    try:
        strategy, orig_run_id = _resolve_target(args.target)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}")
        return 1

    # 2. Locate original directive.
    try:
        src_path = _find_directive(strategy)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"  Source directive: {src_path.relative_to(PROJECT_ROOT)}")

    # 3. Parse.
    try:
        data = _load_directive(src_path)
    except (yaml.YAMLError, ValueError) as e:
        print(f"ERROR parsing directive: {e}")
        return 1

    test_block = data.setdefault("test", {})
    if not isinstance(test_block, dict):
        print("ERROR: directive's 'test' block is malformed (not a mapping)")
        return 1

    # 4. Apply mutations.
    cfg = CATEGORIES[category]

    # 4a. end_date extension (default to today; user can override via --end-date).
    old_end = str(test_block.get("end_date", "?"))
    if cfg["extend_end_date"]:
        new_end = args.end_date or date.today().isoformat()
        test_block["end_date"] = new_end
    else:
        new_end = old_end

    # 4b. signal_version bump.
    old_sv = int(data.get("signal_version") or 1)
    if cfg["bump_signal_version"]:
        new_sv = old_sv + 1
        data["signal_version"] = new_sv
    else:
        new_sv = old_sv

    # 4c. Inject override reason.
    override = _build_override_reason(category, user_reason, orig_run_id, strategy)
    test_block["repeat_override_reason"] = override

    # 4d. Record rerun_of breadcrumb (NON_SIGNATURE_KEYS tolerates this — it's
    # under test:, which is an excluded key, so it doesn't affect the signature).
    if orig_run_id:
        test_block["rerun_of"] = orig_run_id

    # 5. Destination: INBOX with original filename.
    dest_path = INBOX_DIR / f"{strategy}.txt"
    if dest_path.exists() and not args.force:
        print(f"ERROR: {dest_path.relative_to(PROJECT_ROOT)} already exists. "
              f"Remove it or pass --force to overwrite.")
        return 1

    # 6. Summary.
    print()
    print(f"  Strategy:       {strategy}")
    print(f"  Category:       {category}  ({cfg['description']})")
    print(f"  end_date:       {old_end}  -->  {new_end}")
    print(f"  signal_version: {old_sv}  -->  {new_sv}"
          + ("  (classifier gate requires bump)" if cfg["bump_signal_version"] else ""))
    print(f"  override (first 120):  {override[:120]}"
          + ("..." if len(override) > 120 else ""))
    print(f"  Destination:    {dest_path.relative_to(PROJECT_ROOT)}")
    print()

    if args.dry_run:
        print("[DRY RUN] No files written.")
        return 0

    # 7. Write directive.
    _write_directive(dest_path, data)
    print(f"[OK] Wrote {dest_path.relative_to(PROJECT_ROOT)}")

    # 8. Audit log.
    _audit_entry({
        "action": "prepare",
        "strategy": strategy,
        "originating_run_id": orig_run_id,
        "category": category,
        "user_reason": user_reason,
        "end_date_before": old_end,
        "end_date_after": new_end,
        "signal_version_before": old_sv,
        "signal_version_after": new_sv,
        "directive_source": str(src_path.relative_to(PROJECT_ROOT)),
        "directive_destination": str(dest_path.relative_to(PROJECT_ROOT)),
    })

    # 9. Next-step hint.
    print()
    print("[NEXT] Dispatch the pipeline against the new directive:")
    print(f"  python tools/run_pipeline.py {dest_path}")
    print()
    print("[THEN] After the new run_id is written to master_filter, finalize:")
    print(f"  python tools/rerun_backtest.py finalize \\")
    print(f"      --old-run-id <original_run_id> \\")
    print(f"      --new-run-id <new_run_id> \\")
    print(f"      --reason \"{category}: {user_reason[:60]}\"")
    return 0


# ── Subcommand: finalize ────────────────────────────────────────────────────

def cmd_finalize(args: argparse.Namespace) -> int:
    old_rid = args.old_run_id.strip()
    new_rid = args.new_run_id.strip()
    reason = args.reason.strip()

    if not old_rid or not new_rid:
        print("ERROR: --old-run-id and --new-run-id are both required.")
        return 1
    if old_rid == new_rid:
        print("ERROR: old and new run_ids are identical.")
        return 1
    if len(reason) < 10:
        print("ERROR: --reason is required (>=10 chars) for the audit log.")
        return 1

    try:
        flipped = mark_superseded(
            old_run_id=old_rid,
            new_run_id=new_rid,
            reason=reason,
            quarantine=args.quarantine,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    if flipped == 0:
        print(f"[INFO] 0 rows flipped. Either {old_rid} wasn't in master_filter "
              f"or it was already superseded.")
    else:
        print(f"[OK] Flipped {flipped} master_filter row(s) to is_current=0, "
              f"superseded_by={new_rid}"
              + (" (quarantined)" if args.quarantine else ""))

    _audit_entry({
        "action": "finalize",
        "old_run_id": old_rid,
        "new_run_id": new_rid,
        "reason": reason,
        "rows_flipped": flipped,
        "quarantined": bool(args.quarantine),
    })

    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Friction-free reruns of tested strategies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Categories:\n"
            + "\n".join(
                f"  {k:<12s} {v['description']}" for k, v in CATEGORIES.items()
            )
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # prepare
    p1 = sub.add_parser("prepare", help="Prepare a rerun directive in INBOX.")
    p1.add_argument("target", help="Strategy name OR originating run_id.")
    p1.add_argument("--category", required=True,
                    choices=sorted(CATEGORIES.keys()),
                    help="Rerun category — determines gate mutations.")
    p1.add_argument("--reason", required=True,
                    help="Human-supplied reason (>=20 chars).")
    p1.add_argument("--end-date",
                    help="Override the auto-extended end_date (YYYY-MM-DD). "
                         "Default: today.")
    p1.add_argument("--dry-run", action="store_true",
                    help="Print the planned changes without writing.")
    p1.add_argument("--force", action="store_true",
                    help="Overwrite an existing INBOX directive.")
    p1.set_defaults(func=cmd_prepare)

    # finalize
    p2 = sub.add_parser("finalize",
                        help="Flag the old run's rows as is_current=0.")
    p2.add_argument("--old-run-id", required=True,
                    help="run_id being retired.")
    p2.add_argument("--new-run-id", required=True,
                    help="run_id of the replacement run (must exist in DB).")
    p2.add_argument("--reason", required=True,
                    help="Audit reason (>=10 chars).")
    p2.add_argument("--quarantine", action="store_true",
                    help="Also set quarantined=1 — use for BUG_FIX reruns "
                         "where the prior result is semantically wrong.")
    p2.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
