"""
control_panel.py — CLI for recording portfolio control decisions.

Two orthogonal workflows live here:

  Burn-in / deployment intent (portfolio_control table):
    --select / --burn / --drop / --deselect — the interpreter drains these
    into portfolio.yaml + burn_in_registry.yaml.

  Composite-portfolio-analysis intent (master_filter.Analysis_selection):
    --select-analysis / --deselect-analysis / --clear-analysis /
    --list-analysis / --run-analysis — per-run_id flag driving the next
    composite_portfolio_analysis run. Auto-cleared on successful run.

Usage:
  python tools/control_panel.py --list
  python tools/control_panel.py --status
  python tools/control_panel.py --select <portfolio_id> [--profile X]
  python tools/control_panel.py --burn <portfolio_id>
  python tools/control_panel.py --drop <portfolio_id> --reason "..."
  python tools/control_panel.py --deselect <portfolio_id>
  python tools/control_panel.py --select-analysis <run_id> [<run_id> ...]
  python tools/control_panel.py --deselect-analysis <run_id> [<run_id> ...]
  python tools/control_panel.py --clear-analysis
  python tools/control_panel.py --list-analysis
  python tools/control_panel.py --run-analysis
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.ledger_db import (
    _connect, create_tables,
    upsert_portfolio_control, read_portfolio_control,
    update_control_status, delete_portfolio_control,
    log_control_action, read_control_log,
    read_mps, query_mps, read_master_filter,
    read_analysis_selection, set_analysis_selection,
    clear_analysis_selection,
    LEDGER_DB_PATH,
)

from config.path_authority import TS_EXECUTION as TS_EXEC_ROOT, TRADE_SCAN_STATE, DATA_ROOT

PORTFOLIO_YAML = TS_EXEC_ROOT / "portfolio.yaml"
CANDIDATES_PATH = TRADE_SCAN_STATE / "candidates" / "Filtered_Strategies_Passed.xlsx"
REGISTRY_PATH = TS_EXEC_ROOT / "burn_in_registry.yaml"
USD_SYNTH_CSV = DATA_ROOT / "SYSTEM_FACTORS" / "USD_SYNTH" / "usd_synth_close_d1.csv"


# ---------------------------------------------------------------------------
# USD_SYNTH Z-score status (macro gate for FX mean-reversion strategies)
# ---------------------------------------------------------------------------

def _usd_synth_zscore_line() -> str:
    """
    One-line macro health for FX strategies that gate on usd_synth_zscore.
    Threshold 1.5 (macro_allowed != 0) is from strategy signatures; alerting
    threshold 1.0 warns before strategies come alive.
    """
    if not USD_SYNTH_CSV.exists():
        return f"  USD_SYNTH Z-score:    (data file missing: {USD_SYNTH_CSV})"
    try:
        import pandas as pd
        df = pd.read_csv(USD_SYNTH_CSV, encoding="utf-8")
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        v = df["USD_SYNTH_CLOSE_D1"]
        mean = v.rolling(100).mean()
        std = v.rolling(100).std(ddof=0)
        df["z"] = ((v - mean) / std).shift(1)
        if df["z"].dropna().empty:
            return "  USD_SYNTH Z-score:    (insufficient history — need 100+ days)"
        latest = df.dropna(subset=["z"]).iloc[-1]
        z_now = float(latest["z"])
        z_prev3 = float(df.dropna(subset=["z"]).iloc[-4]["z"]) if len(df.dropna(subset=["z"])) >= 4 else z_now
        delta3 = z_now - z_prev3
        trend = "rising" if delta3 > 0.1 else ("falling" if delta3 < -0.1 else "flat")
        abs_z = abs(z_now)
        distance = 1.5 - abs_z  # distance to macro-gate arm threshold
        # Mechanical bucket — no ambiguity based on direction/magnitude
        if distance <= 0:
            status = "ARMED"  # gate open — FX strategies can fire
        elif distance < 0.2:
            status = "IMMINENT"
        elif distance < 0.5:
            status = "PRE-ACTIVATION"
        elif distance < 0.8:
            status = "EARLY-APPROACH"
        else:
            status = "DEAD-ZONE"
        sign = "+" if z_now >= 0 else ""
        return (f"  USD_SYNTH Z-score:    {sign}{z_now:.2f} ({trend}, 3d delta={delta3:+.2f})  "
                f"distance_to_arm={distance:+.2f}  status={status}  "
                f"[FX gate opens at |Z|>=1.5]")
    except Exception as e:
        return f"  USD_SYNTH Z-score:    (read error: {type(e).__name__}: {e})"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _portfolio_exists_in_mps(portfolio_id: str) -> bool:
    """Check if portfolio_id exists in portfolio_sheet (MPS)."""
    df = read_mps()
    if df.empty:
        return False
    return portfolio_id in df["portfolio_id"].values


def _strategy_exists_in_master_filter(portfolio_id: str) -> bool:
    """Check if portfolio_id matches a strategy in master_filter (exact or prefix)."""
    df = read_master_filter()
    if df.empty or "strategy" not in df.columns:
        return False
    for s in df["strategy"].unique():
        if s == portfolio_id or s.startswith(portfolio_id + "_"):
            return True
    return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list() -> int:
    """Print current control table."""
    df = read_portfolio_control()
    if df.empty:
        print("  portfolio_control: (empty)")
        return 0
    # Format for display
    display_cols = ["portfolio_id", "selected", "burn", "status", "profile", "reason", "last_updated"]
    cols = [c for c in display_cols if c in df.columns]
    print(df[cols].to_string(index=False))
    print(f"\n  Total: {len(df)} entries")
    return 0


def cmd_status() -> int:
    """Health check — two-authority drift detector.

    Authority model (2026-04-16):
      * portfolio.yaml       — every deployed strategy (BURN_IN, WAITING,
                               LIVE, LEGACY, DISABLED lifecycles).
      * burn_in_registry.yaml — archetype projection of BURN_IN entries.

    portfolio_control is USER INTENT (pending promote/disable requests), not
    durable state — the interpreter drains it into the YAMLs. A nonzero row
    count there is informational, not a drift signal.

    The DB leg (legacy ``IN_PORTFOLIO`` column) and the FSP leg are gone:
    IN_PORTFOLIO was retired, and FSP is a read-only projection for human
    consumption — it cannot drift "against" an authority it is derived from.

    Drift rule: every strategy_id in burn_in_registry.yaml must resolve to
    a corresponding ``lifecycle: BURN_IN`` entry in portfolio.yaml. Any
    mismatch is actionable drift.
    """
    import yaml

    errors = []

    # 0. Intent-store snapshot (informational).
    df_ctrl = read_portfolio_control()
    pending = df_ctrl[df_ctrl["status"].isin(["SELECTED", "BURN_IN", "RBIN"])]
    print(f"  portfolio_control:    {len(df_ctrl)} rows "
          f"({len(pending)} with intent)")

    # 1. portfolio.yaml — authority #1.
    yaml_entries: dict[str, dict] = {}
    yaml_burnin_ids: set[str] = set()
    if PORTFOLIO_YAML.exists():
        try:
            with open(PORTFOLIO_YAML, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for s in (data.get("portfolio") or {}).get("strategies") or []:
                sid = s.get("id")
                if not isinstance(sid, str) or not sid.strip():
                    continue
                yaml_entries[sid] = s
                if s.get("lifecycle") == "BURN_IN":
                    yaml_burnin_ids.add(sid)
        except Exception as e:
            errors.append(f"portfolio.yaml read error: {e}")
    print(f"  portfolio.yaml:       {len(yaml_entries)} entries "
          f"({len(yaml_burnin_ids)} BURN_IN)")

    # 2. burn_in_registry.yaml — authority #2 (BURN_IN projection).
    reg_ids: set[str] = set()
    reg_count = 0
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                reg = yaml.safe_load(f) or {}
            for layer in ("primary", "coverage"):
                for entry in (reg.get(layer) or []):
                    eid = entry.get("id") if isinstance(entry, dict) else None
                    if isinstance(eid, str) and eid.strip():
                        reg_ids.add(eid.strip())
                        reg_count += 1
        except Exception as e:
            errors.append(f"burn_in_registry.yaml read error: {e}")
    print(f"  burn_in_registry:     {reg_count} entries "
          f"({len(reg_ids)} unique)")

    # 3. USD_SYNTH macro-gate status (observational — FX strategy diagnostic).
    print(_usd_synth_zscore_line())

    # Drift check — registry ids must embed a BURN_IN portfolio.yaml id.
    # Registry ids are of the form "<strategy_id>_<symbol>", where
    # <strategy_id> is the portfolio.yaml id. Exact match OR
    # registry_id.startswith(yaml_id + "_") counts as matched.
    print()
    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        print("  VERDICT: ERRORS DETECTED")
        return 1

    unmatched_registry: set[str] = set()
    for rid in reg_ids:
        if rid in yaml_burnin_ids:
            continue
        if any(rid == yid or rid.startswith(yid + "_") for yid in yaml_burnin_ids):
            continue
        unmatched_registry.add(rid)

    # Every BURN_IN yaml id should have at least one registry entry under it.
    yaml_burnin_without_registry: set[str] = set()
    for yid in yaml_burnin_ids:
        if any(rid == yid or rid.startswith(yid + "_") for rid in reg_ids):
            continue
        yaml_burnin_without_registry.add(yid)

    if not unmatched_registry and not yaml_burnin_without_registry:
        print(f"  VERDICT: ALIGNED -- portfolio.yaml BURN_IN ({len(yaml_burnin_ids)}) "
              f"and burn_in_registry ({len(reg_ids)}) consistent")
        return 0

    print("  VERDICT: DRIFT DETECTED")
    if unmatched_registry:
        print(f"    burn_in_registry has {len(unmatched_registry)} id(s) "
              f"without a BURN_IN entry in portfolio.yaml:")
        for r in sorted(unmatched_registry):
            print(f"      - {r}")
    if yaml_burnin_without_registry:
        print(f"    portfolio.yaml has {len(yaml_burnin_without_registry)} "
              f"BURN_IN entrie(s) missing from burn_in_registry:")
        for y in sorted(yaml_burnin_without_registry):
            print(f"      - {y}")
    print("  (Fix: re-run TS_Execution/tools/sync_burn_in_registry.py or "
          "verify promote/disable workflow wrote both stores.)")
    return 1


def cmd_select(portfolio_id: str, profile: str) -> int:
    """Mark a portfolio for burn-in consideration."""
    # Validate: must exist in MPS or master_filter
    if not _portfolio_exists_in_mps(portfolio_id) and not _strategy_exists_in_master_filter(portfolio_id):
        print(f"  [ERROR] {portfolio_id} not found in MPS or master_filter.")
        print(f"  Run the pipeline for this strategy first.")
        return 1

    conn = _connect()
    create_tables(conn)
    # Check if already exists
    existing = conn.execute(
        "SELECT status FROM portfolio_control WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()
    if existing:
        status = existing[0]
        if status == "BURN_IN":
            print(f"  [SKIP] {portfolio_id} is already BURN_IN.")
            conn.close()
            return 0
        if status == "SELECTED":
            print(f"  [SKIP] {portfolio_id} is already SELECTED.")
            conn.close()
            return 0

    upsert_portfolio_control(
        conn, portfolio_id,
        selected=1, burn=0,
        status="SELECTED",
        profile=profile,
        updated_by="user",
    )
    log_control_action(conn, portfolio_id, "select",
                       status_before=None, status_after="SELECTED",
                       detail=f"profile={profile}")
    conn.close()
    print(f"  [OK] {portfolio_id} -> SELECTED (profile={profile})")
    return 0


def cmd_burn(portfolio_id: str) -> int:
    """Mark a SELECTED portfolio for burn-in promotion."""
    conn = _connect()
    existing = conn.execute(
        "SELECT status, burn FROM portfolio_control WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()

    if not existing:
        print(f"  [ERROR] {portfolio_id} not in portfolio_control. Run --select first.")
        conn.close()
        return 1

    status = existing[0]
    if status == "BURN_IN":
        print(f"  [SKIP] {portfolio_id} is already BURN_IN.")
        conn.close()
        return 0
    if status not in ("SELECTED", "RBIN"):
        print(f"  [ERROR] {portfolio_id} has status={status}. Must be SELECTED or RBIN.")
        conn.close()
        return 1

    upsert_portfolio_control(
        conn, portfolio_id,
        burn=1, selected=1,
        status=status,  # interpreter will transition to BURN_IN
        updated_by="user",
    )
    log_control_action(conn, portfolio_id, "burn",
                       status_before=status, status_after=status,
                       detail="burn=1, awaiting interpreter")
    conn.close()
    print(f"  [OK] {portfolio_id} -> burn=1 (awaiting interpreter)")
    return 0


def cmd_drop(portfolio_id: str, reason: str) -> int:
    """Mark a BURN_IN portfolio for removal."""
    if not reason:
        print("  [ERROR] --reason is required for --drop.")
        return 1

    conn = _connect()
    existing = conn.execute(
        "SELECT status FROM portfolio_control WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()

    if not existing:
        print(f"  [ERROR] {portfolio_id} not in portfolio_control.")
        conn.close()
        return 1

    status = existing[0]
    if status == "RBIN":
        print(f"  [SKIP] {portfolio_id} is already RBIN.")
        conn.close()
        return 0
    if status != "BURN_IN":
        print(f"  [ERROR] {portfolio_id} has status={status}. Can only drop BURN_IN entries.")
        conn.close()
        return 1

    upsert_portfolio_control(
        conn, portfolio_id,
        burn=0,
        reason=reason,
        updated_by="user",
    )
    log_control_action(conn, portfolio_id, "drop",
                       status_before="BURN_IN", status_after="BURN_IN",
                       detail=f"burn=0, reason={reason}")
    conn.close()
    print(f"  [OK] {portfolio_id} -> burn=0 (awaiting interpreter)")
    print(f"  Reason: {reason}")
    return 0


def cmd_deselect(portfolio_id: str) -> int:
    """Remove from control table. Only if SELECTED (not promoted)."""
    conn = _connect()
    existing = conn.execute(
        "SELECT status FROM portfolio_control WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()

    if not existing:
        print(f"  [SKIP] {portfolio_id} not in portfolio_control.")
        conn.close()
        return 0

    status = existing[0]
    if status != "SELECTED":
        print(f"  [ERROR] {portfolio_id} has status={status}. Can only deselect SELECTED entries.")
        conn.close()
        return 1

    log_control_action(conn, portfolio_id, "deselect",
                       status_before="SELECTED", status_after=None,
                       detail="removed from control table")
    delete_portfolio_control(conn, portfolio_id)
    conn.close()
    print(f"  [OK] {portfolio_id} removed from portfolio_control.")
    return 0


# ---------------------------------------------------------------------------
# Analysis_selection commands — per-run_id intent flag driving the next
# composite_portfolio_analysis invocation. Orthogonal to burn-in promotion.
# ---------------------------------------------------------------------------

def _validate_run_ids_in_mf(run_ids: set[str]) -> tuple[set[str], set[str]]:
    """Split a set of run_ids into (found, missing) against master_filter."""
    df = read_master_filter()
    if df.empty or "run_id" not in df.columns:
        return set(), set(run_ids)
    known = set(df["run_id"].astype(str).unique())
    found = {r for r in run_ids if r in known}
    missing = set(run_ids) - found
    return found, missing


def cmd_select_analysis(run_ids: list[str]) -> int:
    """Add run_ids to the Analysis_selection set (union with current).

    Semantics: 1 (selected) in master_filter for every run_id in the new
    union. Unknown run_ids are reported but not silently dropped.
    """
    new_ids = {r.strip() for r in run_ids if r and r.strip()}
    if not new_ids:
        print("  [ERROR] No run_ids provided.")
        return 1
    found, missing = _validate_run_ids_in_mf(new_ids)
    if missing:
        print(f"  [ERROR] {len(missing)} run_id(s) not found in master_filter:")
        for r in sorted(missing):
            print(f"    - {r}")
        print("  (Refusing to flag run_ids with no corresponding MF row.)")
        return 1
    current = read_analysis_selection()
    union = current | found
    added = found - current
    already = found & current
    synced = set_analysis_selection(union)
    print(f"  [OK] Analysis_selection now has {synced} run_id(s) "
          f"(+{len(added)} new, {len(already)} already selected).")
    return 0


def cmd_deselect_analysis(run_ids: list[str]) -> int:
    """Remove specific run_ids from Analysis_selection.

    To clear everything at once use --clear-analysis.
    """
    drop = {r.strip() for r in run_ids if r and r.strip()}
    if not drop:
        print("  [ERROR] No run_ids provided.")
        return 1
    current = read_analysis_selection()
    if not current:
        print("  [SKIP] Analysis_selection is already empty.")
        return 0
    kept = current - drop
    removed = drop & current
    not_selected = drop - current
    synced = set_analysis_selection(kept)
    print(f"  [OK] Analysis_selection now has {synced} run_id(s) "
          f"(-{len(removed)} removed).")
    if not_selected:
        print(f"  [NOTE] {len(not_selected)} run_id(s) were not currently "
              f"selected: {sorted(not_selected)}")
    return 0


def cmd_clear_analysis() -> int:
    """Wipe all Analysis_selection flags."""
    cleared = clear_analysis_selection()
    print(f"  [OK] Cleared Analysis_selection ({cleared} flag(s) reset).")
    return 0


def cmd_list_analysis() -> int:
    """Print the current Analysis_selection set."""
    selected = read_analysis_selection()
    if not selected:
        print("  Analysis_selection: (empty)")
        return 0
    print(f"  Analysis_selection: {len(selected)} run_id(s)")
    for r in sorted(selected):
        print(f"    - {r}")
    return 0


def cmd_run_analysis() -> int:
    """Run composite_portfolio_analysis against current Analysis_selection.

    Workflow:
      1. Read current Analysis_selection from master_filter.
      2. Refuse if < 2 run_ids (correlation/concurrency need >=2).
      3. Invoke run_portfolio_analysis.py --run-ids <list> as subprocess.
      4. On success, clear Analysis_selection (next session starts fresh).
      5. On failure, leave Analysis_selection intact so the user can adjust.
    """
    import subprocess as _sp

    selected = read_analysis_selection()
    if not selected:
        print("  [ERROR] Analysis_selection is empty. "
              "Use --select-analysis first.")
        return 1
    if len(selected) < 2:
        print(f"  [ERROR] Only {len(selected)} run_id selected. "
              f"Composite portfolio analysis requires >=2 constituents "
              f"(correlation/concurrency need a pair).")
        return 1

    run_ids_sorted = sorted(selected)
    print(f"  Running composite_portfolio_analysis on "
          f"{len(run_ids_sorted)} run_id(s):")
    for r in run_ids_sorted:
        print(f"    - {r}")

    script = Path(__file__).parent / "run_portfolio_analysis.py"
    if not script.exists():
        print(f"  [FATAL] run_portfolio_analysis.py not found at {script}")
        return 1

    cmd = [sys.executable, str(script), "--run-ids", *run_ids_sorted]
    result = _sp.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"  [FAIL] run_portfolio_analysis.py exited "
              f"with code {result.returncode}. "
              f"Analysis_selection preserved for retry.")
        return result.returncode

    cleared = clear_analysis_selection()
    print(f"  [OK] Analysis complete. Cleared {cleared} Analysis_selection "
          f"flag(s) — next session starts fresh.")

    # Regenerate FSP so the human-facing sheet reflects the cleared state
    # immediately (without waiting for the next pipeline pass). Failures
    # here are non-fatal — the DB is the source of truth.
    fsp_script = Path(__file__).parent / "filter_strategies.py"
    if fsp_script.exists():
        try:
            fsp_result = _sp.run(
                [sys.executable, str(fsp_script)],
                cwd=str(PROJECT_ROOT),
                capture_output=True, text=True,
            )
            if fsp_result.returncode == 0:
                print(f"  [OK] FSP regenerated (Analysis_selection column "
                      f"now shows 0 for all rows).")
            else:
                print(f"  [WARN] FSP regeneration returned "
                      f"{fsp_result.returncode}. The DB is cleared; re-run "
                      f"filter_strategies.py manually to refresh the Excel.")
        except Exception as exc:
            print(f"  [WARN] FSP regeneration skipped ({exc}). The DB is "
                  f"cleared; re-run filter_strategies.py manually.")
    return 0


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

def _pick_from_list(items: list[str], prompt: str) -> str | None:
    """Show numbered list, return selected item or None on cancel."""
    if not items:
        print("  (none available)")
        return None
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item}")
    print(f"  0. Cancel")
    try:
        choice = input(f"\n{prompt}: ").strip()
        if not choice or choice == "0":
            return None
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx]
        print("  Invalid choice.")
        return None
    except (ValueError, EOFError):
        return None


def _pick_from_grouped_list(
    portfolios: list[str], singles: list[str], prompt: str,
) -> str | None:
    """Show numbered list grouped by Portfolios / Single-Asset, return selected."""
    combined = []
    print()
    if portfolios:
        print(f"  --- Portfolios ({len(portfolios)}) ---")
        for pid in portfolios:
            combined.append(pid)
            print(f"  {len(combined):>3}. {pid}")
    if singles:
        print(f"\n  --- Single-Asset Composites ({len(singles)}) ---")
        for pid in singles:
            combined.append(pid)
            print(f"  {len(combined):>3}. {pid}")
    if not combined:
        print("  (none available)")
        return None
    print(f"    0. Cancel")
    try:
        choice = input(f"\n  {prompt}: ").strip()
        if not choice or choice == "0":
            return None
        idx = int(choice) - 1
        if 0 <= idx < len(combined):
            return combined[idx]
        print("  Invalid choice.")
        return None
    except (ValueError, EOFError):
        return None


def _confirm(action_desc: str) -> bool:
    """Prompt user for y/n confirmation. Returns True if confirmed."""
    try:
        ans = input(f"\n  Are you sure you want to {action_desc}? (y/n): ").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _run_interpreter(dry_run: bool = False) -> None:
    """Run portfolio_interpreter as subprocess."""
    import subprocess as _sp
    cmd = [sys.executable, str(Path(__file__).parent / "portfolio_interpreter.py")]
    if dry_run:
        cmd.append("--dry-run")
    label = "dry-run" if dry_run else "applying"
    print(f"\n  Running interpreter ({label})...")
    _sp.run(cmd, cwd=str(PROJECT_ROOT))


def interactive_menu() -> int:
    """Interactive control panel — menu-driven, no arguments needed."""
    while True:
        print(f"\n{'=' * 60}")
        print("  PORTFOLIO CONTROL PANEL")
        print(f"{'=' * 60}")
        print("  1. Show portfolio")
        print("  2. System health")
        print("  3. Select strategy")
        print("  4. Promote to burn-in")
        print("  5. Drop from burn-in")
        print("  6. Remove selection")
        print("  7. Apply pending changes")
        print("  8. Dry-run changes")
        print("  9. View audit log")
        print(" 10. Composite portfolio analysis (FSP Analysis_selection)")
        print("  0. Exit")
        print()

        try:
            choice = input("  Choose [0-10]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice == "0":
            return 0

        elif choice == "1":
            cmd_list()

        elif choice == "2":
            cmd_status()

        elif choice == "3":
            # Select — show available strategies grouped by tab
            print("\n  Loading available strategies from MPS...")
            df_ctrl = read_portfolio_control()
            existing = set(df_ctrl["portfolio_id"]) if not df_ctrl.empty else set()

            df_port = query_mps(sheet="Portfolios")
            df_single = query_mps(sheet="Single-Asset Composites")

            port_avail = sorted(
                pid for pid in (df_port["portfolio_id"].unique() if not df_port.empty else [])
                if pid not in existing
            )
            single_avail = sorted(
                pid for pid in (df_single["portfolio_id"].unique() if not df_single.empty else [])
                if pid not in existing
            )

            if not port_avail and not single_avail:
                print("  No new strategies available (all already in control table or MPS empty).")
                continue

            pid = _pick_from_grouped_list(port_avail, single_avail, "Select number")
            if not pid:
                continue

            profile = input("  Profile [CONSERVATIVE_V1]: ").strip() or "CONSERVATIVE_V1"
            cmd_select(pid, profile)

        elif choice == "4":
            # Promote — show SELECTED entries, confirm, set burn=1, auto-run interpreter
            df_ctrl = read_portfolio_control()
            candidates = []
            if not df_ctrl.empty:
                mask = df_ctrl["status"].isin(["SELECTED", "RBIN"])
                candidates = sorted(df_ctrl.loc[mask, "portfolio_id"].tolist())
            if not candidates:
                print("  No SELECTED entries to promote. Use option 3 first.")
                continue

            print(f"\n  SELECTED strategies:")
            pid = _pick_from_list(candidates, "Promote number")
            if not pid:
                continue
            if not _confirm(f"promote {pid}"):
                print("  Cancelled.")
                continue
            cmd_burn(pid)
            _run_interpreter()
            # Auto-refresh: show updated portfolio
            print()
            cmd_list()

        elif choice == "5":
            # Drop — show BURN_IN entries, confirm, set burn=0, auto-run interpreter
            df_ctrl = read_portfolio_control()
            candidates = []
            if not df_ctrl.empty:
                mask = df_ctrl["status"] == "BURN_IN"
                candidates = sorted(df_ctrl.loc[mask, "portfolio_id"].tolist())
            if not candidates:
                print("  No BURN_IN entries to drop.")
                continue

            print(f"\n  BURN_IN strategies:")
            pid = _pick_from_list(candidates, "Drop number")
            if not pid:
                continue
            reason = input("  Reason: ").strip()
            if not reason:
                print("  [ERROR] Reason is required.")
                continue
            if not _confirm(f"drop {pid}"):
                print("  Cancelled.")
                continue
            cmd_drop(pid, reason)
            _run_interpreter()
            # Auto-refresh: show updated portfolio
            print()
            cmd_list()

        elif choice == "6":
            # Deselect — show SELECTED entries
            df_ctrl = read_portfolio_control()
            candidates = []
            if not df_ctrl.empty:
                mask = df_ctrl["status"] == "SELECTED"
                candidates = sorted(df_ctrl.loc[mask, "portfolio_id"].tolist())
            if not candidates:
                print("  No SELECTED entries to deselect.")
                continue

            print(f"\n  SELECTED strategies:")
            pid = _pick_from_list(candidates, "Deselect number")
            if pid:
                cmd_deselect(pid)

        elif choice == "7":
            # Apply pending changes
            _run_interpreter()
            # Auto-refresh
            print()
            cmd_list()

        elif choice == "8":
            # Dry-run
            _run_interpreter(dry_run=True)

        elif choice == "9":
            # Audit log
            df = read_control_log(limit=20)
            if df.empty:
                print("  (no log entries)")
            else:
                display = ["id", "portfolio_id", "action", "status_before", "status_after", "detail", "timestamp"]
                cols = [c for c in display if c in df.columns]
                print(df[cols].to_string(index=False))

        elif choice == "10":
            # Composite portfolio analysis — Analysis_selection submenu.
            while True:
                print(f"\n  --- Composite Portfolio Analysis ---")
                cmd_list_analysis()
                print()
                print("  a. Add run_id(s) to selection")
                print("  r. Remove run_id(s) from selection")
                print("  c. Clear all selections")
                print("  g. Go (run analysis — auto-clears on success)")
                print("  b. Back to main menu")
                try:
                    sub = input("  Choose [a/r/c/g/b]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if sub in ("b", "0", ""):
                    break
                if sub == "a":
                    raw = input("  run_id(s) to add (space-separated): ").strip()
                    if raw:
                        cmd_select_analysis(raw.split())
                elif sub == "r":
                    raw = input("  run_id(s) to remove (space-separated): ").strip()
                    if raw:
                        cmd_deselect_analysis(raw.split())
                elif sub == "c":
                    if _confirm("clear all Analysis_selection flags"):
                        cmd_clear_analysis()
                    else:
                        print("  Cancelled.")
                elif sub == "g":
                    if _confirm("run composite_portfolio_analysis on current selection"):
                        cmd_run_analysis()
                    else:
                        print("  Cancelled.")
                else:
                    print("  Invalid choice.")

        else:
            print("  Invalid choice.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    # If no arguments → interactive menu
    if len(sys.argv) == 1:
        return interactive_menu()

    parser = argparse.ArgumentParser(
        description="Portfolio Control Panel — record intent for promote/disable"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Show control table")
    group.add_argument("--status", action="store_true", help="Health check across all stores")
    group.add_argument("--log", nargs="?", const="__all__", metavar="ID",
                        help="Show audit log (optionally for a specific portfolio_id)")
    group.add_argument("--select", metavar="ID", help="Select portfolio for burn-in consideration")
    group.add_argument("--burn", metavar="ID", help="Mark for burn-in promotion")
    group.add_argument("--drop", metavar="ID", help="Mark for removal from burn-in")
    group.add_argument("--deselect", metavar="ID", help="Remove from control table (SELECTED only)")
    # Analysis_selection — per-run_id intent for composite_portfolio_analysis.
    group.add_argument("--select-analysis", nargs="+", metavar="RUN_ID",
                        help="Add run_id(s) to Analysis_selection")
    group.add_argument("--deselect-analysis", nargs="+", metavar="RUN_ID",
                        help="Remove run_id(s) from Analysis_selection")
    group.add_argument("--clear-analysis", action="store_true",
                        help="Clear all Analysis_selection flags")
    group.add_argument("--list-analysis", action="store_true",
                        help="Show currently selected run_ids")
    group.add_argument("--run-analysis", action="store_true",
                        help="Run composite_portfolio_analysis on current selection (auto-clears on success)")

    parser.add_argument("--profile", default="CONSERVATIVE_V1",
                        help="Deployment profile (default: CONSERVATIVE_V1)")
    parser.add_argument("--reason", default="", help="Reason for drop (required with --drop)")

    args = parser.parse_args()

    if args.list:
        return cmd_list()
    elif args.status:
        return cmd_status()
    elif args.log is not None:
        pid = None if args.log == "__all__" else args.log
        df = read_control_log(portfolio_id=pid)
        if df.empty:
            print("  (no log entries)")
        else:
            display = ["id", "portfolio_id", "action", "status_before", "status_after", "detail", "timestamp"]
            cols = [c for c in display if c in df.columns]
            print(df[cols].to_string(index=False))
        return 0
    elif args.select:
        return cmd_select(args.select, args.profile)
    elif args.burn:
        return cmd_burn(args.burn)
    elif args.drop:
        return cmd_drop(args.drop, args.reason)
    elif args.deselect:
        return cmd_deselect(args.deselect)
    elif args.select_analysis:
        return cmd_select_analysis(args.select_analysis)
    elif args.deselect_analysis:
        return cmd_deselect_analysis(args.deselect_analysis)
    elif args.clear_analysis:
        return cmd_clear_analysis()
    elif args.list_analysis:
        return cmd_list_analysis()
    elif args.run_analysis:
        return cmd_run_analysis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
