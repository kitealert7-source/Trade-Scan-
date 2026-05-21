"""Surgically remove dead child run_ids from PORTFOLIO_COMPLETE directive_state.json files.

Why this exists: lineage_pruner.verify_referential_integrity bails when any keep_run is
missing from disk. PORTFOLIO_COMPLETE directives whose child runs/<rid>/ folders have been
quarantined or lost still carry the dead rids in attempts[latest].run_ids, so they enter
keep_runs and trip the integrity check. This tool cleans those references in-place with
full audit, unblocking lineage_pruner without touching live runs or non-PORTFOLIO_COMPLETE
attempts.

Companion to:
    - lineage_pruner.py        — purges orphan runs/backtests/portfolios (downstream of this).
    - repair_integrity.py      — repairs Excel ledger row footprints (different scope).
    - directive_reconciler.py  — handles directive .txt lifecycle (different scope).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.path_authority import TRADE_SCAN_STATE as STATE_ROOT
from tools.state_lifecycle.lineage_pruner import execution_pid_exists

RUNS_DIR = STATE_ROOT / "runs"
SANDBOX_DIR = STATE_ROOT / "sandbox"
BACKTESTS_DIR = STATE_ROOT / "backtests"
LOGS_DIR = STATE_ROOT / "logs"


def _is_run_alive(rid: str, runs_dir: Path, sandbox_dir: Path, backtests_dir: Path) -> bool:
    """Mirror lineage_pruner.verify_referential_integrity's triple-check.

    A run is ALIVE if any of these footprints exist:
      - runs/<rid>/  (native dir)
      - sandbox/<rid>/  (sandbox dir)
      - backtests/<rid>.json  (legacy backtest artifact)
      - runs/<rid>/run_state.json  (native state file)
      - sandbox/<rid>/run_state.json  (sandbox state file)
    """
    if (runs_dir / rid).exists() or (sandbox_dir / rid).exists():
        return True
    if (backtests_dir / f"{rid}.json").exists():
        return True
    if (runs_dir / rid / "run_state.json").exists():
        return True
    if (sandbox_dir / rid / "run_state.json").exists():
        return True
    return False


def _classify_directive(
    data: dict,
    runs_dir: Path,
    sandbox_dir: Path,
    backtests_dir: Path,
) -> tuple[bool, list[str], list[str]]:
    """Decide whether the directive is in scope and return (in_scope, run_ids_before, dead).

    In scope iff latest_attempt's status == PORTFOLIO_COMPLETE OR protected: true.
    Mirrors lineage_pruner._collect_portfolio_complete_runs scope.
    """
    latest_key = data.get("latest_attempt", "attempt_01")
    attempts = data.get("attempts") or {}
    attempt = attempts.get(latest_key) or {}
    status = attempt.get("status")
    is_protected = bool(data.get("protected", False))
    in_scope = is_protected or status == "PORTFOLIO_COMPLETE"
    run_ids_before = list(attempt.get("run_ids") or [])
    if not in_scope:
        return False, run_ids_before, []
    dead = [
        rid for rid in run_ids_before
        if not _is_run_alive(rid, runs_dir, sandbox_dir, backtests_dir)
    ]
    return True, run_ids_before, dead


def _atomic_write(path: Path, payload: dict) -> None:
    """Write payload as indented JSON via tmp + fsync + os.replace."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(path))


def scan(
    runs_dir: Path = RUNS_DIR,
    sandbox_dir: Path = SANDBOX_DIR,
    backtests_dir: Path = BACKTESTS_DIR,
) -> list[dict]:
    """Walk runs/<dir>/directive_state.json and emit a change record per in-scope dir.

    Each record has fields:
      directive_id, file_path (str, relative to STATE_ROOT.parent),
      attempt_key, run_ids_before, dead_run_ids, run_ids_after, status, protected
    """
    if not runs_dir.exists():
        return []
    records: list[dict] = []
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir():
            continue
        ds = d / "directive_state.json"
        if not ds.exists():
            continue
        try:
            data = json.loads(ds.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        in_scope, run_ids_before, dead = _classify_directive(
            data, runs_dir, sandbox_dir, backtests_dir
        )
        if not in_scope or not dead:
            continue
        latest_key = data.get("latest_attempt", "attempt_01")
        attempt = (data.get("attempts") or {}).get(latest_key, {})
        records.append({
            "directive_id": data.get("directive_id", d.name),
            "file_path": str(ds),
            "attempt_key": latest_key,
            "status": attempt.get("status"),
            "protected": bool(data.get("protected", False)),
            "run_ids_before": run_ids_before,
            "dead_run_ids": dead,
            "run_ids_after": [r for r in run_ids_before if r not in dead],
        })
    return records


def apply_record(record: dict, now_iso: str, runs_dir: Path) -> None:
    """Mutate one directive_state.json file per the change record (atomic write).

    runs_dir scope guard: refuses to write outside the configured runs_dir so a
    misconfigured caller cannot accidentally mutate production. See the
    2026-05-21 incident (default-arg vs monkeypatch mismatch in scan()).
    """
    path = Path(record["file_path"]).resolve()
    runs_dir_resolved = runs_dir.resolve()
    try:
        path.relative_to(runs_dir_resolved)
    except ValueError as exc:
        raise RuntimeError(
            f"refuse to mutate {path} — outside configured runs_dir {runs_dir_resolved}"
        ) from exc
    data = json.loads(path.read_text(encoding="utf-8"))
    latest_key = record["attempt_key"]
    attempts = data.get("attempts") or {}
    attempt = attempts.get(latest_key)
    if attempt is None:
        raise RuntimeError(f"latest_attempt {latest_key!r} missing in {path}")
    attempt["run_ids"] = list(record["run_ids_after"])
    data["last_updated"] = now_iso
    _atomic_write(path, data)


def write_audit_log(
    audit_path: Path,
    mode: str,
    records: Iterable[dict],
    scan_total: int,
) -> Path:
    """Write the audit log JSON (always — dry-run and execute alike)."""
    records = list(records)
    total_dead = sum(len(r["dead_run_ids"]) for r in records)
    payload = {
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "mode": mode,
        "directives_scanned": scan_total,
        "directives_with_dead_children": len(records),
        "dead_run_ids_removed_total": total_dead,
        "changes": records,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(audit_path, payload)
    return audit_path


def _count_directives(runs_dir: Path) -> int:
    if not runs_dir.exists():
        return 0
    return sum(1 for d in runs_dir.iterdir() if d.is_dir() and (d / "directive_state.json").exists())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--execute", action="store_true",
        help="Apply mutations. Without this flag, runs in dry-run mode (default).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Explicit dry-run (default behaviour). Mutually exclusive with --execute.",
    )
    parser.add_argument(
        "--audit-log", type=Path, default=None,
        help="Override audit log path. Default: TradeScan_State/logs/reconcile_portfolio_complete_<UTC ts>.json",
    )
    parser.add_argument(
        "--force-unlock", action="store_true",
        help="Bypass TS_Execution safety check. Use only when certain TS_Execution is not running.",
    )
    args = parser.parse_args(argv)

    if args.dry_run and args.execute:
        print("[ERROR] --dry-run and --execute are mutually exclusive.")
        return 2

    if args.force_unlock:
        print("[WARN] --force-unlock: bypassing TS_Execution safety check.")
    elif execution_pid_exists():
        print("[BLOCK] TS_Execution is running")
        return 1

    mode = "EXECUTE" if args.execute else "DRY_RUN"
    print(f"--- reconcile_portfolio_complete ({mode}) ---")
    scan_total = _count_directives(RUNS_DIR)
    records = scan(RUNS_DIR, SANDBOX_DIR, BACKTESTS_DIR)
    total_dead = sum(len(r["dead_run_ids"]) for r in records)
    print(f"Directives scanned:               {scan_total}")
    print(f"Directives with dead children:    {len(records)}")
    print(f"Dead run_ids to remove:           {total_dead}")

    if args.audit_log is not None:
        audit_path = args.audit_log
    else:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        audit_path = LOGS_DIR / f"reconcile_portfolio_complete_{ts}.json"

    if mode == "EXECUTE":
        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
        print(f"[EXECUTE] Mutating {len(records)} directive_state.json files...")
        for rec in records:
            apply_record(rec, now_iso, RUNS_DIR)
        print(f"[EXECUTE] Done.")
    else:
        print("[DRY_RUN] No changes applied. Use --execute to mutate.")

    write_audit_log(audit_path, mode, records, scan_total)
    print(f"Audit log: {audit_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
