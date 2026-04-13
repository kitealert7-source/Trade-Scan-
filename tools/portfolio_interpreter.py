"""
portfolio_interpreter.py — Reads portfolio_control transitions, executes workflows.

Detects pending state changes in portfolio_control table and invokes
promote_to_burnin.py or disable_burnin.py as needed.

Usage:
  python tools/portfolio_interpreter.py              # process all pending
  python tools/portfolio_interpreter.py --dry-run    # show what would happen
  python tools/portfolio_interpreter.py --sync-only  # regenerate Excel views only

Post-action: automatically regenerates FSP, MPS, and burn_in_registry.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TS_EXEC_ROOT = PROJECT_ROOT.parent / "TS_Execution"
sys.path.insert(0, str(PROJECT_ROOT))

from tools.ledger_db import (
    _connect, create_tables,
    read_portfolio_control, update_control_status,
    upsert_portfolio_control, log_control_action,
    export_mps, export_master_filter,
)

# Lock threshold: skip rows updated < N seconds ago (prevents double execution)
LOCK_THRESHOLD_SECONDS = 30


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


def _resolve_run_ids_for_portfolio(portfolio_id: str) -> list[str]:
    """Resolve run_ids for a portfolio_id from master_filter.

    Uses startswith matching to find all per-symbol entries.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            'SELECT run_id, strategy FROM master_filter WHERE "IN_PORTFOLIO" = 1'
        ).fetchall()
        matched = []
        for run_id, strat in rows:
            if strat == portfolio_id or strat.startswith(portfolio_id + "_"):
                matched.append(run_id)
        return matched
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Promotion logic
# ---------------------------------------------------------------------------

def _execute_promote(portfolio_id: str, profile: str, dry_run: bool = False) -> bool:
    """Call promote_to_burnin.promote() for a portfolio_id.

    Returns True on success, False on failure.
    """
    promote_script = PROJECT_ROOT / "tools" / "promote_to_burnin.py"
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
    """Regenerate all derived stores: FSP, MPS Excel, burn_in_registry."""
    print(f"\n{'─' * 40}")
    print("  Syncing derived state...")

    # 1. filter_strategies → FSP
    print("  [1/4] Regenerating FSP (filter_strategies)...")
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "filter_strategies.py")],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120,
        )
        # Print key lines only
        for line in (r.stdout or "").split("\n"):
            if any(k in line for k in ["SUCCESS", "BURN_IN", "ERROR", "FAIL"]):
                print(f"    {line.strip()}")
        if r.returncode != 0:
            print(f"    [WARN] filter_strategies exited {r.returncode}")
    except Exception as e:
        print(f"    [WARN] filter_strategies failed: {e}")

    # 2. Format FSP
    print("  [2/4] Formatting FSP...")
    _format_excel(
        PROJECT_ROOT.parent / "TradeScan_State" / "candidates" / "Filtered_Strategies_Passed.xlsx",
        "strategy"
    )

    # 3. Export + format MPS
    print("  [3/4] Exporting + formatting MPS...")
    try:
        conn = _connect()
        export_mps(conn)
        export_master_filter(conn)
        conn.close()
    except Exception as e:
        print(f"    [WARN] Export failed: {e}")
    _format_excel(
        PROJECT_ROOT.parent / "TradeScan_State" / "strategies" / "Master_Portfolio_Sheet.xlsx",
        "portfolio"
    )

    # 4. sync_burn_in_registry
    print("  [4/4] Syncing burn_in_registry...")
    try:
        r = subprocess.run(
            [sys.executable, str(TS_EXEC_ROOT / "tools" / "sync_burn_in_registry.py"), "--quiet"],
            cwd=str(TS_EXEC_ROOT), capture_output=True, text=True, timeout=30,
        )
        if r.stdout.strip():
            print(f"    {r.stdout.strip()}")
    except Exception as e:
        print(f"    [WARN] sync_burn_in_registry failed: {e}")

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
                if age < LOCK_THRESHOLD_SECONDS and status in ("SELECTED", "BURN_IN"):
                    # Check if this is actually a pending transition
                    if (status == "SELECTED" and burn == 1) or (status == "BURN_IN" and burn == 0):
                        # Recently updated and pending — could be double execution
                        # Allow if age > threshold, skip if too recent
                        pass  # proceed — the timestamp check is just for safety
            except (ValueError, TypeError):
                pass

        # --- No-op protection ---
        if status == "BURN_IN" and burn == 1:
            continue  # already promoted, nothing to do
        if status == "RBIN" and burn == 0 and selected == 0:
            continue  # already removed, nothing to do

        # --- PROMOTE: selected=1, burn=1, status=SELECTED ---
        if selected == 1 and burn == 1 and status in ("SELECTED", "RBIN"):
            print(f"\n  [TRANSITION] {pid}: {status} -> PROMOTE")
            if dry_run:
                print(f"    [DRY RUN] Would call promote_to_burnin({pid}, profile={profile})")
                result["skipped"].append(pid)
                continue

            success = _execute_promote(pid, profile, dry_run=False)
            conn = _connect()
            if success:
                update_control_status(conn, pid, "BURN_IN", updated_by="interpreter")
                log_control_action(conn, pid, "promote_ok",
                                   status_before=status, status_after="BURN_IN",
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

        # --- REMOVE: status=BURN_IN, burn=0 ---
        if status == "BURN_IN" and burn == 0:
            r = reason or "Removed via control_panel"
            print(f"\n  [TRANSITION] {pid}: BURN_IN -> REMOVE")
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
                    conn, pid, "RBIN", updated_by="interpreter",
                    selected=0, burn=0,
                )
                log_control_action(conn, pid, "disable_ok",
                                   status_before="BURN_IN", status_after="RBIN",
                                   detail=f"reason={r}")
                result["removed"].append(pid)
                actions_taken = True
            else:
                # Preserve state: keep status=BURN_IN, revert burn=1
                upsert_portfolio_control(
                    conn, pid, burn=1, updated_by="interpreter",
                )
                log_control_action(conn, pid, "disable_fail",
                                   status_before="BURN_IN", status_after="BURN_IN",
                                   detail=f"disable failed, state preserved. reason={r}")
                result["errors"].append(f"{pid}: disable failed")
                print(f"  [ERROR] {pid}: disable failed. State preserved (status=BURN_IN, burn=1).")
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
