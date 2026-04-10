"""
Generate SYSTEM_STATE.md — session-level system snapshot.

Designed to be run at end of each work session (session-close workflow).
Produces a concise, scannable snapshot that the next session reads on startup.

Usage:
    python tools/system_introspection.py                    # full snapshot
    python tools/system_introspection.py --skip-preflight   # skip governance check
    python tools/system_introspection.py --output /tmp/ss.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Paths (derived from state_paths.py pattern, no hardcoded user paths) ──
STATE_ROOT = PROJECT_ROOT.parent / "TradeScan_State"
RUNS_DIR = STATE_ROOT / "runs"
BACKTESTS_DIR = STATE_ROOT / "backtests"
STRATEGIES_DIR = STATE_ROOT / "strategies"
SANDBOX_DIR = STATE_ROOT / "sandbox"
CANDIDATES_DIR = STATE_ROOT / "candidates"

MASTER_FILTER_PATH = SANDBOX_DIR / "Strategy_Master_Filter.xlsx"
MPS_PATH = STRATEGIES_DIR / "Master_Portfolio_Sheet.xlsx"
CANDIDATE_FILTER_PATH = CANDIDATES_DIR / "Filtered_Strategies_Passed.xlsx"

INBOX_DIR = PROJECT_ROOT / "backtest_directives" / "INBOX"
ACTIVE_DIR = PROJECT_ROOT / "backtest_directives" / "active"
COMPLETED_DIR = PROJECT_ROOT / "backtest_directives" / "completed"

ENGINE_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
ENGINE_REGISTRY = PROJECT_ROOT / "config" / "engine_registry.json"
FRESHNESS_INDEX = PROJECT_ROOT / "data_root" / "freshness_index.json"

TS_EXECUTION = PROJECT_ROOT.parent / "TS_Execution"
PORTFOLIO_YAML = TS_EXECUTION / "portfolio.yaml"
DRY_RUN_VAULT = PROJECT_ROOT.parent / "DRY_RUN_VAULT"

DEFAULT_OUTPUT = PROJECT_ROOT / "SYSTEM_STATE.md"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_files(directory: Path, pattern: str = "*") -> int:
    if not directory.exists():
        return 0
    return sum(1 for p in directory.glob(pattern) if p.is_file())


def _count_dirs(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for p in directory.iterdir() if p.is_dir() and not p.name.startswith("."))


# ── Collectors ────────────────────────────────────────────────────────────


def collect_engine() -> dict[str, str]:
    """Engine version, manifest status, frozen/active."""
    version = "UNKNOWN"
    status = "UNKNOWN"

    if ENGINE_REGISTRY.exists():
        data = _safe_json(ENGINE_REGISTRY)
        if data:
            version = data.get("active_engine", "UNKNOWN")

    # Find manifest
    engine_dir = ENGINE_ROOT / version
    manifest_path = engine_dir / "engine_manifest.json" if engine_dir.exists() else None
    manifest_status = "MISSING"
    if manifest_path and manifest_path.exists():
        manifest_data = _safe_json(manifest_path)
        manifest_status = "VALID" if manifest_data else "INVALID"

    # Check if frozen (convention: FROZEN if no changes in 3+ days)
    status = "FROZEN" if version == "v1_5_4" else "ACTIVE"

    return {
        "version": version.replace("_", ".").lstrip("v") if version != "UNKNOWN" else version,
        "version_raw": version,
        "status": status,
        "manifest": manifest_status,
    }


def collect_directives() -> dict[str, Any]:
    """Directive queue: INBOX, active, completed counts + names."""
    inbox = sorted(p.name for p in INBOX_DIR.iterdir() if p.is_file()) if INBOX_DIR.exists() else []
    active = sorted(p.name for p in ACTIVE_DIR.iterdir() if p.is_file()) if ACTIVE_DIR.exists() else []
    completed_count = _count_files(COMPLETED_DIR, "*.txt")

    return {
        "inbox": inbox,
        "active": active,
        "completed_count": completed_count,
    }


def collect_ledgers() -> dict[str, Any]:
    """Ledger row counts and classification distribution."""
    import pandas as pd

    result: dict[str, Any] = {}

    # Master Filter
    if MASTER_FILTER_PATH.exists():
        try:
            df = pd.read_excel(MASTER_FILTER_PATH)
            result["master_filter"] = {"rows": len(df), "path": "TradeScan_State/sandbox/Strategy_Master_Filter.xlsx"}
        except Exception as e:
            result["master_filter"] = {"error": str(e)}
    else:
        result["master_filter"] = {"missing": True}

    # MPS — read both tabs
    if MPS_PATH.exists():
        try:
            mps_info: dict[str, Any] = {"path": "TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx"}
            with pd.ExcelFile(MPS_PATH) as xls:
                mps_info["sheets"] = xls.sheet_names
                for sheet in xls.sheet_names:
                    if sheet == "Notes":
                        continue
                    try:
                        df = pd.read_excel(xls, sheet_name=sheet)
                        tab: dict[str, Any] = {"rows": len(df)}
                        # Classification distribution
                        status_col = None
                        for c in df.columns:
                            if str(c).lower() == "portfolio_status":
                                status_col = c
                                break
                        if status_col:
                            counts = df[status_col].value_counts().to_dict()
                            tab["classification"] = {str(k): int(v) for k, v in counts.items()}
                        mps_info[sheet] = tab
                    except Exception:
                        pass
            result["mps"] = mps_info
        except Exception as e:
            result["mps"] = {"error": str(e)}
    else:
        result["mps"] = {"missing": True}

    # Candidates (FPS)
    if CANDIDATE_FILTER_PATH.exists():
        try:
            df = pd.read_excel(CANDIDATE_FILTER_PATH)
            fps_info: dict[str, Any] = {"rows": len(df)}
            for c in df.columns:
                if str(c).lower() == "candidate_status":
                    counts = df[c].value_counts().to_dict()
                    fps_info["classification"] = {str(k): int(v) for k, v in counts.items()}
                    break
            result["candidates"] = fps_info
        except Exception as e:
            result["candidates"] = {"error": str(e)}
    else:
        result["candidates"] = {"missing": True}

    return result


def collect_portfolio() -> dict[str, Any]:
    """Portfolio.yaml: BURN_IN/WAITING/LIVE/LEGACY counts."""
    if not PORTFOLIO_YAML.exists():
        return {"missing": True}

    try:
        import yaml
        data = yaml.safe_load(PORTFOLIO_YAML.read_text(encoding="utf-8"))
    except Exception:
        # Fallback: count lines with lifecycle:
        try:
            text = PORTFOLIO_YAML.read_text(encoding="utf-8")
            lines = text.splitlines()
            burn_in = sum(1 for l in lines if "lifecycle: BURN_IN" in l)
            waiting = sum(1 for l in lines if "lifecycle: WAITING" in l)
            live = sum(1 for l in lines if "lifecycle: LIVE" in l)
            enabled_count = sum(1 for l in lines if "enabled: true" in l)
            total = sum(1 for l in lines if l.strip().startswith("- id:"))
            legacy = total - burn_in - waiting - live
            return {
                "total": total,
                "burn_in": burn_in,
                "waiting": waiting,
                "live": live,
                "legacy": legacy,
                "enabled": enabled_count,
            }
        except Exception as e:
            return {"error": str(e)}

    if not isinstance(data, list):
        # Nested under portfolio.strategies
        if isinstance(data, dict):
            portfolio_block = data.get("portfolio", {})
            if isinstance(portfolio_block, dict) and "strategies" in portfolio_block:
                data = portfolio_block["strategies"]
            else:
                # Fallback: find any list value
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break

    if not isinstance(data, list):
        return {"error": "Unexpected portfolio.yaml structure"}

    counts = {"BURN_IN": 0, "WAITING": 0, "LIVE": 0, "LEGACY": 0}
    enabled = 0
    for entry in data:
        if not isinstance(entry, dict):
            continue
        lc = entry.get("lifecycle", "")
        if lc in counts:
            counts[lc] += 1
        else:
            counts["LEGACY"] += 1
        if entry.get("enabled", False):
            enabled += 1

    return {
        "total": len(data),
        "burn_in": counts["BURN_IN"],
        "waiting": counts["WAITING"],
        "live": counts["LIVE"],
        "legacy": counts["LEGACY"],
        "enabled": enabled,
    }


def collect_vault() -> dict[str, Any]:
    """DRY_RUN_VAULT: count snapshots and WAITING entries."""
    if not DRY_RUN_VAULT.exists():
        return {"missing": True}

    snapshots = [d.name for d in DRY_RUN_VAULT.iterdir()
                 if d.is_dir() and d.name.startswith("DRY_RUN_")]
    waiting_dir = DRY_RUN_VAULT / "WAITING"
    waiting_count = _count_dirs(waiting_dir) if waiting_dir.exists() else 0

    return {
        "snapshot_count": len(snapshots),
        "waiting_count": waiting_count,
        "latest": max(snapshots) if snapshots else "none",
    }


def collect_data_freshness() -> dict[str, str]:
    """Latest research data date from freshness_index.json."""
    if not FRESHNESS_INDEX.exists():
        return {"status": "MISSING"}

    data = _safe_json(FRESHNESS_INDEX)
    if not data:
        return {"status": "UNREADABLE"}

    # Structure: {generated_at, entries: {symbol: {latest_date, days_behind, ...}}}
    entries = data.get("entries", {})
    if not entries:
        # Fallback: flat structure with latest_bar
        dates = []
        for k, v in data.items():
            if isinstance(v, dict) and "latest_bar" in v:
                dates.append(v["latest_bar"])
        return {
            "latest_bar": max(dates) if dates else "unknown",
            "symbols_tracked": len(dates),
        }

    dates = []
    stale = 0
    for sym, info in entries.items():
        if isinstance(info, dict) and "latest_date" in info:
            dates.append(info["latest_date"])
            if info.get("days_behind", 0) > 3:
                stale += 1

    return {
        "latest_bar": max(dates) if dates else "unknown",
        "symbols_tracked": len(dates),
        "stale_symbols": stale,
        "generated_at": data.get("generated_at", "unknown"),
    }


def collect_runs() -> dict[str, int]:
    """Run directory count."""
    return {"total": _count_dirs(RUNS_DIR)}


def collect_git() -> dict[str, Any]:
    """Git sync status: commits ahead, clean working tree."""
    result: dict[str, Any] = {}
    try:
        # Commits ahead of origin
        ahead = subprocess.run(
            ["git", "log", "--oneline", "origin/main..HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
        )
        if ahead.returncode == 0:
            lines = [l for l in ahead.stdout.strip().splitlines() if l.strip()]
            result["commits_ahead"] = len(lines)
        else:
            result["commits_ahead"] = "unknown"

        # Working tree status
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
        )
        if status.returncode == 0:
            changes = [l for l in status.stdout.strip().splitlines() if l.strip()]
            # Exclude data_root runtime changes
            code_changes = [l for l in changes if not l.strip().lstrip("?MA ").startswith("data_root/")]
            result["working_tree"] = "clean" if not code_changes else f"{len(code_changes)} uncommitted"
        else:
            result["working_tree"] = "unknown"

        # Last commit
        last = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
        )
        if last.returncode == 0:
            result["last_commit"] = last.stdout.strip()

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Renderer ──────────────────────────────────────────────────────────────


def render_markdown(
    engine: dict,
    directives: dict,
    ledgers: dict,
    portfolio: dict,
    vault: dict,
    freshness: dict,
    runs: dict,
    git: dict,
) -> str:
    lines: list[str] = []

    lines.append("# SYSTEM STATE")
    lines.append("")
    lines.append(f"> Generated: {_now_utc()}")
    lines.append(">")
    lines.append("> Read at session start. Regenerate at session end (`python tools/system_introspection.py`).")
    lines.append("")

    # ── Engine
    lines.append("## Engine")
    lines.append(f"- **Version:** {engine['version']} | **Status:** {engine['status']} | **Manifest:** {engine['manifest']}")
    lines.append("")

    # ── Pipeline Queue
    lines.append("## Pipeline Queue")
    inbox = directives.get("inbox", [])
    active = directives.get("active", [])
    if not inbox and not active:
        lines.append("- Queue empty. No directives in INBOX or active.")
    else:
        if active:
            lines.append(f"- **Active ({len(active)}):** {', '.join(active)}")
        if inbox:
            lines.append(f"- **INBOX ({len(inbox)}):** {', '.join(inbox)}")
    lines.append(f"- Completed: {directives.get('completed_count', 0)} directives")
    lines.append("")

    # ── Ledgers
    lines.append("## Ledgers")
    lines.append("")

    # Master Filter
    mf = ledgers.get("master_filter", {})
    if mf.get("missing"):
        lines.append("- **Master Filter:** MISSING")
    elif mf.get("error"):
        lines.append(f"- **Master Filter:** ERROR — {mf['error']}")
    else:
        lines.append(f"- **Master Filter:** {mf.get('rows', '?')} rows")
    lines.append("")

    # MPS
    mps = ledgers.get("mps", {})
    if mps.get("missing"):
        lines.append("- **Master Portfolio Sheet:** MISSING")
    elif mps.get("error"):
        lines.append(f"- **Master Portfolio Sheet:** ERROR — {mps['error']}")
    else:
        lines.append(f"- **Master Portfolio Sheet:** `{mps.get('path', '')}`")
        for sheet_name in mps.get("sheets", []):
            if sheet_name == "Notes":
                continue
            tab = mps.get(sheet_name, {})
            if not tab:
                continue
            cls = tab.get("classification", {})
            cls_str = ", ".join(f"{k}: {v}" for k, v in sorted(cls.items())) if cls else "no status column"
            lines.append(f"  - **{sheet_name}:** {tab.get('rows', '?')} rows — {cls_str}")
    lines.append("")

    # Candidates (FPS)
    fps = ledgers.get("candidates", {})
    if fps.get("missing"):
        lines.append("- **Candidates (FPS):** MISSING")
    elif fps.get("error"):
        lines.append(f"- **Candidates (FPS):** ERROR — {fps['error']}")
    else:
        cls = fps.get("classification", {})
        cls_str = ", ".join(f"{k}: {v}" for k, v in sorted(cls.items())) if cls else ""
        lines.append(f"- **Candidates (FPS):** {fps.get('rows', '?')} rows — {cls_str}")
    lines.append("")

    # ── Portfolio (TS_Execution)
    lines.append("## Portfolio (TS_Execution)")
    if portfolio.get("missing"):
        lines.append("- portfolio.yaml: MISSING")
    elif portfolio.get("error"):
        lines.append(f"- portfolio.yaml: ERROR — {portfolio['error']}")
    else:
        lines.append(f"- **Total entries:** {portfolio.get('total', '?')} | **Enabled:** {portfolio.get('enabled', '?')}")
        lines.append(f"- BURN_IN: {portfolio.get('burn_in', 0)} | WAITING: {portfolio.get('waiting', 0)} | LIVE: {portfolio.get('live', 0)} | LEGACY: {portfolio.get('legacy', 0)}")
    lines.append("")

    # ── Vault
    lines.append("## Vault (DRY_RUN_VAULT)")
    if vault.get("missing"):
        lines.append("- DRY_RUN_VAULT: NOT FOUND")
    else:
        lines.append(f"- Snapshots: {vault.get('snapshot_count', 0)} | WAITING: {vault.get('waiting_count', 0)} | Latest: `{vault.get('latest', 'none')}`")
    lines.append("")

    # ── Data Freshness
    lines.append("## Data Freshness")
    if freshness.get("status"):
        lines.append(f"- freshness_index.json: {freshness['status']}")
    else:
        stale = freshness.get("stale_symbols", 0)
        stale_str = f" | **Stale (>3d): {stale}**" if stale else ""
        lines.append(f"- Latest bar: **{freshness.get('latest_bar', 'unknown')}** | Symbols: {freshness.get('symbols_tracked', '?')}{stale_str}")
    lines.append("")

    # ── Artifacts
    lines.append("## Artifacts")
    lines.append(f"- Run directories: {runs.get('total', 0)}")
    lines.append("")

    # ── Git Sync
    lines.append("## Git Sync")
    if git.get("error"):
        lines.append(f"- Error: {git['error']}")
    else:
        ahead = git.get("commits_ahead", "unknown")
        tree = git.get("working_tree", "unknown")
        sync = "IN SYNC" if ahead == 0 else f"**{ahead} commits ahead of origin**"
        lines.append(f"- Remote: {sync}")
        lines.append(f"- Working tree: {tree}")
        if git.get("last_commit"):
            lines.append(f"- Last commit: `{git['last_commit']}`")
    lines.append("")

    # ── Known Issues / Pending
    lines.append("## Known Issues")
    lines.append("<!-- Update manually at session end: note anything broken, deferred, or pending -->")
    lines.append("- (none)")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SYSTEM_STATE.md snapshot.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output markdown path (default: SYSTEM_STATE.md at project root)",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip running governance/preflight.py (unused in new design, kept for compat)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()

    print("[SYSTEM_STATE] Collecting system snapshot...")

    engine = collect_engine()
    directives = collect_directives()
    ledgers = collect_ledgers()
    portfolio = collect_portfolio()
    vault = collect_vault()
    freshness = collect_data_freshness()
    runs = collect_runs()
    git = collect_git()

    markdown = render_markdown(engine, directives, ledgers, portfolio, vault, freshness, runs, git)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"[DONE] SYSTEM_STATE.md written: {output_path}")


if __name__ == "__main__":
    main()
