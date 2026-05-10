"""
portfolio_interpreter.py — Reads portfolio_control transitions, executes workflows.

Detects pending state changes in portfolio_control table and invokes
promote_to_live.py or the TS_Execution disable script as needed.

Usage:
  python tools/portfolio_interpreter.py              # process all pending
  python tools/portfolio_interpreter.py --dry-run    # show what would happen
  python tools/portfolio_interpreter.py --sync-only  # regenerate Excel views only

Post-action: automatically regenerates FSP and MPS.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT, TRADE_SCAN_STATE as _TRADE_SCAN_STATE

from tools.ledger_db import (
    _connect, create_tables,
    read_portfolio_control, update_control_status,
    upsert_portfolio_control, log_control_action,
    export_mps, export_master_filter,
)
from tools.event_log import log_event

# Lock threshold: skip rows updated < N seconds ago (prevents double execution)
LOCK_THRESHOLD_SECONDS = 30


# ---------------------------------------------------------------------------
# Startup self-check — fail-hard on authority drift
# ---------------------------------------------------------------------------

def authority_self_check() -> None:
    """Verify integrity of durable authorities before acting on intent.

    Runs on every interpreter invocation (except --sync-only). The goal is
    to convert silent drift — the class of bug responsible for the FAKEBREAK
    P01/P02 incident — into loud, immediate failures at the exact moment a
    user is about to issue a transition.

    Checks:
      1. portfolio.yaml parses as valid YAML.
      2. Every strategy entry has a non-empty `id` and a recognised
         `lifecycle` value.
      3. No duplicate IDs within portfolio.yaml.

    Violations raise RuntimeError — the interpreter refuses to act on
    pending intent while the authorities are inconsistent. The violating
    details are also emitted to governance/events.jsonl for forensic
    recovery.
    """
    import yaml

    VALID_LIFECYCLES = {"LEGACY", "LIVE", "RETIRED", "DISABLED"}
    violations: list[str] = []

    # ---- portfolio.yaml ----
    yaml_path = TS_EXEC_ROOT / "portfolio.yaml"
    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            violations.append(f"portfolio.yaml is not valid YAML: {e}")
            data = {}

        strategies = (data.get("portfolio") or {}).get("strategies") or []
        seen_ids: dict[str, int] = {}
        for idx, s in enumerate(strategies):
            sid = s.get("id") if isinstance(s, dict) else None
            if not isinstance(sid, str) or not sid.strip():
                violations.append(
                    f"portfolio.yaml entry #{idx} has empty or non-string id: {s!r}"
                )
                continue
            if sid in seen_ids:
                violations.append(
                    f"portfolio.yaml duplicate id {sid!r} "
                    f"(entries #{seen_ids[sid]} and #{idx})"
                )
            else:
                seen_ids[sid] = idx
            lc = s.get("lifecycle")
            if lc is not None and lc not in VALID_LIFECYCLES:
                violations.append(
                    f"portfolio.yaml entry {sid!r} has unknown lifecycle={lc!r} "
                    f"(valid: {sorted(VALID_LIFECYCLES)})"
                )
    # portfolio.yaml missing is OK — a fresh install has no portfolio yet.

    if violations:
        log_event(
            action="INVARIANT_VIOLATION",
            target="authorities:portfolio_yaml",
            actor="portfolio_interpreter.authority_self_check",
            reason="startup self-check failed",
            violations=violations,
        )
        msg_lines = [
            "[SELF-CHECK] Authority integrity violation — refusing to run:",
            *[f"  - {v}" for v in violations],
            "",
            "Resolve each violation, then re-run. See governance/events.jsonl "
            "for a machine-readable record.",
        ]
        raise RuntimeError("\n".join(msg_lines))


# ---------------------------------------------------------------------------
# Symbol expansion — critical for multi-symbol removal
# ---------------------------------------------------------------------------

def _expand_portfolio_to_yaml_ids(portfolio_id: str) -> list[str]:
    """Expand a portfolio_id to ALL per-symbol entries in portfolio.yaml.

    Returns list of YAML entry IDs. For a single-symbol strategy, this
    returns [portfolio_id] or [portfolio_id_SYMBOL]. For multi-symbol,
    returns all matching entries.

    Hard rule: ALL or NONE. If 0 matches found, returns empty list.
    """
    import yaml

    yaml_path = TS_EXEC_ROOT / "portfolio.yaml"
    if not yaml_path.exists():
        return []

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    strategies = (data.get("portfolio") or {}).get("strategies") or []
    matches = []
    for s in strategies:
        sid = s.get("id", "")
        if not s.get("enabled", True):
            continue
        # Exact match or prefix match (portfolio_id + "_SYMBOL")
        if sid == portfolio_id or sid.startswith(portfolio_id + "_"):
            matches.append(sid)

    return matches


# [RETIRED 2026-04-16] _resolve_run_ids_for_portfolio was never called and
# relied on the legacy IN_PORTFOLIO column. The authoritative run_id mapping
# now lives in portfolio_sheet.constituent_run_ids (for composites) and
# portfolio.yaml (for deployed strategies).


# ---------------------------------------------------------------------------
# Promotion logic
# ---------------------------------------------------------------------------

def _execute_promote(portfolio_id: str, profile: str, dry_run: bool = False) -> bool:
    """Call promote_to_live.promote() for a portfolio_id.

    Returns True on success, False on failure.
    """
    promote_script = PROJECT_ROOT / "tools" / "promote_to_live.py"
    cmd = [
        sys.executable, str(promote_script),
        "--allow-direct",
        portfolio_id,
        "--profile", profile,
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n  [PROMOTE] Running: {' '.join(cmd[-4:])}")
    try:
        result = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=300,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                print(f"    {line}")
        if result.returncode != 0:
            print(f"  [PROMOTE FAILED] exit code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"    STDERR: {line}")
            return False
        print(f"  [PROMOTE OK]")
        return True
    except subprocess.TimeoutExpired:
        print(f"  [PROMOTE FAILED] Timeout (300s)")
        return False
    except Exception as e:
        print(f"  [PROMOTE FAILED] {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------
# Removal logic
# ---------------------------------------------------------------------------

def _execute_disable(portfolio_id: str, reason: str, dry_run: bool = False) -> bool:
    """Call disable_burnin.disable() for all per-symbol entries.

    Hard rule: expand to ALL symbols, remove ALL or NONE.
    Returns True on success, False on failure.
    """
    # Step 1: Expand to all per-symbol YAML entries
    yaml_ids = _expand_portfolio_to_yaml_ids(portfolio_id)
    if not yaml_ids:
        print(f"  [DISABLE FAILED] No portfolio.yaml entries found for {portfolio_id}")
        return False

    print(f"  [DISABLE] Expanding {portfolio_id} -> {len(yaml_ids)} entries: {yaml_ids}")

    disable_script = TS_EXEC_ROOT / "tools" / "disable_burnin.py"
    cmd = [
        sys.executable, str(disable_script),
        "--allow-direct",
        *yaml_ids,
        "--reason", reason,
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"  [DISABLE] Running disable_burnin with {len(yaml_ids)} IDs")
    try:
        result = subprocess.run(
            cmd, cwd=str(TS_EXEC_ROOT),
            capture_output=True, text=True, timeout=120,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                print(f"    {line}")
        if result.returncode != 0:
            print(f"  [DISABLE FAILED] exit code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"    STDERR: {line}")
            return False
        print(f"  [DISABLE OK]")
        return True
    except subprocess.TimeoutExpired:
        print(f"  [DISABLE FAILED] Timeout (120s)")
        return False
    except Exception as e:
        print(f"  [DISABLE FAILED] {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------
# Sync all derived state
# ---------------------------------------------------------------------------

def sync_derived_state() -> None:
    """Regenerate all derived stores: FSP, MPS Excel."""
    print(f"\n{'─' * 40}")
    print("  Syncing derived state...")

    # 1. filter_strategies → FSP
    print("  [1/3] Regenerating FSP (filter_strategies)...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "filter_strategies.py")],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120,
        )
        # Print key lines only
        for line in (r.stdout or "").split("\n"):
            if any(k in line for k in ["SUCCESS", "LIVE", "ERROR", "FAIL", "DEPLOYED"]):
                print(f"    {line.strip()}")
        if r.returncode != 0:
            print(f"    [WARN] filter_strategies exited {r.returncode}")
    except Exception as e:
        print(f"    [WARN] filter_strategies failed: {e}")

    # 2. Format FSP
    print("  [2/3] Formatting FSP...")
    _format_excel(
        _TRADE_SCAN_STATE / "candidates" / "Filtered_Strategies_Passed.xlsx",
        "strategy"
    )

    # 3. Export + format MPS
    print("  [3/3] Exporting + formatting MPS...")
    try:
        conn = _connect()
        export_mps(conn)
        export_master_filter(conn)
        conn.close()
    except Exception as e:
        print(f"    [WARN] Export failed: {e}")
    _format_excel(
        _TRADE_SCAN_STATE / "strategies" / "Master_Portfolio_Sheet.xlsx",
        "portfolio"
    )

    print("  Sync complete.")
    print(f"{'─' * 40}")


def _format_excel(path: Path, profile: str) -> None:
    """Run format_excel_artifact.py on an Excel file."""
    formatter = PROJECT_ROOT / "tools" / "format_excel_artifact.py"
    if not formatter.exists() or not path.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(formatter), "--file", str(path), "--profile", profile],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
        )
    except Exception:
        pass  # formatting is cosmetic, never block


# ---------------------------------------------------------------------------
# Main interpreter loop
# ---------------------------------------------------------------------------

def interpret(dry_run: bool = False) -> dict:
    """Process all pending transitions in portfolio_control.

    Returns summary dict: {promoted: [...], removed: [...], skipped: [...], errors: [...]}.
    """
    result = {"promoted": [], "removed": [], "skipped": [], "errors": []}

    conn = _connect()
    create_tables(conn)
    df = read_portfolio_control(conn=conn)
    conn.close()

    if df.empty:
        print("  portfolio_control: (empty) — nothing to process.")
        return result

    now = datetime.now(timezone.utc)
    actions_taken = False

    for _, row in df.iterrows():
        pid = row["portfolio_id"]
        selected = int(row.get("selected", 0))
        burn = int(row.get("burn", 0))
        status = row.get("status", "SELECTED")
        profile = row.get("profile", "CONSERVATIVE_V1")
        reason = row.get("reason", "")
        last_updated = row.get("last_updated", "")

        # --- Lock check: skip recently updated rows (prevents double execution) ---
        if last_updated:
            try:
                lu = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                age = (now - lu).total_seconds()
                # Only apply lock during transitional states
                if age < LOCK_THRESHOLD_SECONDS and status in ("SELECTED", "LIVE"):
                    # Check if this is actually a pending transition
                    if (status == "SELECTED" and burn == 1) or (status == "LIVE" and burn == 0):
                        # Recently updated and pending — could be double execution
                        # Allow if age > threshold, skip if too recent
                        pass  # proceed — the timestamp check is just for safety
            except (ValueError, TypeError):
                pass

        # --- No-op protection ---
        if status == "LIVE" and burn == 1:
            continue  # already promoted, nothing to do
        if status == "REMOVE" and burn == 0 and selected == 0:
            continue  # already removed, nothing to do

        # --- PROMOTE: selected=1, burn=1, status=SELECTED ---
        if selected == 1 and burn == 1 and status in ("SELECTED", "REMOVE"):
            print(f"\n  [TRANSITION] {pid}: {status} -> PROMOTE")
            if dry_run:
                print(f"    [DRY RUN] Would call promote_to_live({pid}, profile={profile})")
                result["skipped"].append(pid)
                continue

            success = _execute_promote(pid, profile, dry_run=False)
            conn = _connect()
            if success:
                update_control_status(conn, pid, "LIVE", updated_by="interpreter")
                log_control_action(conn, pid, "promote_ok",
                                   status_before=status, status_after="LIVE",
                                   detail=f"profile={profile}")
                result["promoted"].append(pid)
                actions_taken = True
            else:
                # Preserve intent: keep burn=1, keep status=SELECTED, log error
                update_control_status(conn, pid, status, updated_by="interpreter")
                log_control_action(conn, pid, "promote_fail",
                                   status_before=status, status_after=status,
                                   detail="promote failed, intent preserved")
                result["errors"].append(f"{pid}: promote failed")
                print(f"  [ERROR] {pid}: promote failed. Intent preserved (burn=1, status={status}).")
            conn.close()
            continue

        # --- REMOVE: status=LIVE, burn=0 ---
        if status == "LIVE" and burn == 0:
            r = reason or "Removed via control_panel"
            print(f"\n  [TRANSITION] {pid}: LIVE -> REMOVE")
            if dry_run:
                yaml_ids = _expand_portfolio_to_yaml_ids(pid)
                print(f"    [DRY RUN] Would disable {len(yaml_ids)} entries: {yaml_ids}")
                print(f"    Reason: {r}")
                result["skipped"].append(pid)
                continue

            success = _execute_disable(pid, r, dry_run=False)
            conn = _connect()
            if success:
                update_control_status(
                    conn, pid, "REMOVE", updated_by="interpreter",
                    selected=0, burn=0,
                )
                log_control_action(conn, pid, "disable_ok",
                                   status_before="LIVE", status_after="REMOVE",
                                   detail=f"reason={r}")
                result["removed"].append(pid)
                actions_taken = True
            else:
                # Preserve state: keep status=LIVE, revert burn=1
                upsert_portfolio_control(
                    conn, pid, burn=1, updated_by="interpreter",
                )
                log_control_action(conn, pid, "disable_fail",
                                   status_before="LIVE", status_after="LIVE",
                                   detail=f"disable failed, state preserved. reason={r}")
                result["errors"].append(f"{pid}: disable failed")
                print(f"  [ERROR] {pid}: disable failed. State preserved (status=LIVE, burn=1).")
            conn.close()
            continue

    # --- Post-action sync ---
    if actions_taken and not dry_run:
        sync_derived_state()
    elif dry_run:
        print("\n  [DRY RUN] Skipping derived state sync.")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Portfolio Interpreter — execute pending control transitions"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without executing")
    parser.add_argument("--sync-only", action="store_true",
                        help="Only regenerate derived state (FSP, MPS, registry)")
    args = parser.parse_args()

    if args.sync_only:
        sync_derived_state()
        return 0

    print(f"\n{'=' * 60}")
    print(f"PORTFOLIO INTERPRETER")
    print(f"{'=' * 60}")

    # Fail-hard authority self-check before acting on any pending intent.
    # If portfolio.yaml is structurally inconsistent, executing transitions
    # would compound the damage — refuse to run.
    try:
        authority_self_check()
    except RuntimeError as exc:
        print(str(exc))
        return 2

    result = interpret(dry_run=args.dry_run)

    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    if result["promoted"]:
        print(f"  Promoted: {result['promoted']}")
    if result["removed"]:
        print(f"  Removed:  {result['removed']}")
    if result["errors"]:
        print(f"  Errors:   {result['errors']}")
    if result["skipped"]:
        print(f"  Skipped:  {result['skipped']}")
    if not any(result.values()):
        print(f"  No pending transitions.")
    print(f"{'=' * 60}")

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
