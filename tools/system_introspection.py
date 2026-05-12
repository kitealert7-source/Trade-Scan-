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
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _find_trade_scan_root() -> Path:
    """Walk up from PROJECT_ROOT to find the real Trade_Scan repo root.

    The deterministic marker is `.git` being a *directory* — in the main
    repo `.git/` is the actual gitdir, but in a worktree `.git` is a
    *file* containing a `gitdir:` pointer to `<repo>/.git/worktrees/<n>`.
    Walking up from the worktree dir until `.git.is_dir()` lands us on
    the real Trade_Scan root regardless of how deep the worktree nests.

    Falls back to PROJECT_ROOT so a non-git checkout (rare) still has
    a usable anchor.
    """
    cur = PROJECT_ROOT
    for _ in range(6):
        git = cur / ".git"
        if git.is_dir():
            return cur
        cur = cur.parent
    return PROJECT_ROOT


_TRADE_SCAN_ROOT = _find_trade_scan_root()


def _resolve_sibling(name: str) -> Path:
    """Sibling repo adjacent to the real Trade_Scan root.

    Worktree-safe via `_TRADE_SCAN_ROOT` — its `.parent` is the user's
    container folder regardless of whether we're invoked from main or
    from `Trade_Scan/.claude/worktrees/<n>/`. Avoids the trap where a
    stale `TradeScan_State/` left inside `.claude/worktrees/` would
    shadow the real one if we naively walked parents.

    The path is returned whether or not it exists on disk so downstream
    callers can surface 'MISSING' meaningfully.
    """
    return _TRADE_SCAN_ROOT.parent / name


# ── Paths (derived from state_paths.py pattern, no hardcoded user paths) ──
STATE_ROOT = _resolve_sibling("TradeScan_State")
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
# data_root is a local-only symlink (not tracked) at the Trade_Scan
# root pointing at Anti_Gravity_DATA_ROOT. Worktrees don't inherit it,
# so anchor on the real repo root rather than PROJECT_ROOT to keep
# freshness reads consistent across worktree and main invocations.
FRESHNESS_INDEX = _TRADE_SCAN_ROOT / "data_root" / "freshness_index.json"

TS_EXECUTION = _resolve_sibling("TS_Execution")
PORTFOLIO_YAML = TS_EXECUTION / "portfolio.yaml"
DRY_RUN_VAULT = _resolve_sibling("DRY_RUN_VAULT")

DEFAULT_OUTPUT = PROJECT_ROOT / "SYSTEM_STATE.md"

# Canonical anchor for the operator-editable Manual section under
# `## Known Issues`. Stable across regen — operator notes added here
# survive a fresh `python tools/system_introspection.py` run.
# Fix landed 2026-05-12; predecessor behavior overwrote on every regen
# despite the SKILL.md contract claiming "entries here persist".
# See outputs/SYSTEM_STATE_MANUAL_PERSIST_AUDIT.md.
_MANUAL_SECTION_HEADER = "### Manual (deferred TDs, operational context)"


def _preserve_manual_section(target_path: Path, regenerated_markdown: str) -> str:
    """Inject the prior file's Manual section into the regenerated markdown.

    Rules (per the 2026-05-12 audit doc):
      1. If `target_path` doesn't exist (first regen, e.g. fresh clone) →
         return `regenerated_markdown` unchanged.
      2. If the prior file has exactly ONE `### Manual (...)` block →
         extract it verbatim (from the header through the next `##`-level
         heading or EOF) and substitute it into the regenerated markdown
         at the same anchor, replacing the default template.
      3. If the prior file has ZERO `### Manual (...)` blocks → return
         `regenerated_markdown` unchanged (no preservation needed).
      4. If the prior file has TWO OR MORE `### Manual (...)` blocks →
         raise `RuntimeError`. Fail closed; never silently pick one.

    The regenerated markdown is also expected to contain a `### Manual`
    section (the renderer's default template). If it doesn't, the
    function returns unchanged — no anchor to substitute at.
    """
    if not target_path.exists():
        return regenerated_markdown

    prior = target_path.read_text(encoding="utf-8")
    prior_manuals = _find_manual_blocks(prior)
    if len(prior_manuals) == 0:
        return regenerated_markdown
    if len(prior_manuals) > 1:
        raise RuntimeError(
            f"SYSTEM_STATE.md has {len(prior_manuals)} `### Manual` sections "
            f"(expected 0 or 1). Resolve manually before regenerating — "
            f"the script will not silently pick one. Path: {target_path}"
        )

    prior_block = prior_manuals[0]
    regen_manuals = _find_manual_blocks(regenerated_markdown)
    if len(regen_manuals) != 1:
        # Renderer didn't emit a Manual anchor in this regen — nothing to
        # substitute at. Return unchanged to avoid silently dropping the
        # operator's notes.
        return regenerated_markdown
    return regenerated_markdown.replace(regen_manuals[0], prior_block, 1)


def _find_manual_blocks(markdown: str) -> list[str]:
    """Return list of Manual-section blocks found in `markdown`. Each block
    runs from the `### Manual` header through (but not including) the next
    same-or-higher-level heading (`## ` or `### `), or to EOF.

    Manual is `###`-level. The extractor must stop at:
      - the next `## ` heading (peer section like `## Engine`), AND
      - the next `### ` heading (sibling subsection, e.g. a DUPLICATE
        `### Manual` block — needed so Case 3 / fail-closed detects
        multiple Manual blocks).

    It does NOT stop at `#### ` or deeper — operator notes can use
    those internally.
    """
    lines = markdown.splitlines(keepends=True)
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(_MANUAL_SECTION_HEADER):
            block_start = i
            j = i + 1
            while j < len(lines):
                # `## ` is level-2; `### ` is level-3; `#### ` and deeper
                # share neither prefix because the 4th char is `#`, not
                # ' '. So these two checks together capture exactly the
                # boundaries we want.
                if lines[j].startswith("## ") or lines[j].startswith("### "):
                    break
                j += 1
            blocks.append("".join(lines[block_start:j]).rstrip("\n"))
            i = j
        else:
            i += 1
    return blocks


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
    """Engine version, manifest status, frozen/active.

    Status is read from the manifest's `engine_status` field (set at
    vault-promotion time). Hardcoding a canonical version here would
    silently mark every successor engine as LEGACY despite its
    manifest reading FROZEN — the bug that flagged v1.5.8 as LEGACY
    when v1.5.6 was the only version the introspection knew about.
    Trust the manifest.
    """
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
    manifest_data: dict | None = None
    if manifest_path and manifest_path.exists():
        manifest_data = _safe_json(manifest_path)
        manifest_status = "VALID" if manifest_data else "INVALID"

    if manifest_data and manifest_data.get("engine_status"):
        status = manifest_data["engine_status"]
    elif version == "UNKNOWN":
        status = "UNKNOWN"
    else:
        # Manifest exists but lacks engine_status field (pre-v1_5_7
        # manifests). Mark as LEGACY to surface the missing metadata.
        status = "LEGACY"

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

    # Master Filter (DB-first, Excel fallback)
    try:
        from tools.ledger_db import read_master_filter, read_mps
        df = read_master_filter()
        if not df.empty:
            result["master_filter"] = {"rows": len(df), "path": "TradeScan_State/sandbox/Strategy_Master_Filter.xlsx"}
        else:
            result["master_filter"] = {"missing": True}
    except Exception as e:
        result["master_filter"] = {"error": str(e)}

    # MPS — read both tabs (DB-first, Excel fallback)
    try:
        mps_info: dict[str, Any] = {"path": "TradeScan_State/strategies/Master_Portfolio_Sheet.xlsx"}
        _sheet_names = ["Portfolios", "Single-Asset Composites"]
        mps_info["sheets"] = _sheet_names
        for sheet in _sheet_names:
            try:
                df = read_mps(sheet=sheet)
                tab: dict[str, Any] = {"rows": len(df)}
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
    """Portfolio.yaml: LIVE/RETIRED/LEGACY counts."""
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
            live = sum(1 for l in lines if "lifecycle: LIVE" in l)
            retired = sum(1 for l in lines if "lifecycle: RETIRED" in l)
            enabled_count = sum(1 for l in lines if "enabled: true" in l)
            total = sum(1 for l in lines if l.strip().startswith("- id:"))
            legacy = total - live - retired
            return {
                "total": total,
                "live": live,
                "retired": retired,
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

    counts = {"LIVE": 0, "RETIRED": 0, "LEGACY": 0}
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
        "live": counts["LIVE"],
        "retired": counts["RETIRED"],
        "legacy": counts["LEGACY"],
        "enabled": enabled,
    }


def collect_vault() -> dict[str, Any]:
    """DRY_RUN_VAULT: count snapshots."""
    if not DRY_RUN_VAULT.exists():
        return {"missing": True}

    snapshots = [d.name for d in DRY_RUN_VAULT.iterdir()
                 if d.is_dir() and d.name.startswith("DRY_RUN_")]

    return {
        "snapshot_count": len(snapshots),
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


def _check_directive_queue_health() -> dict[str, Any]:
    """Detect stale or stranded directives sitting in INBOX.

    Surfaces two failure modes the V1_P00 / 18-stale-PSBRK incident
    (2026-05-06) made visible:

    1. Stale INBOX entry — directive file in INBOX whose
       directive_state.json shows latest_attempt.status ==
       PORTFOLIO_COMPLETE. BootstrapController would gracefully abort
       these on --all (exit 0), but the operator has no early signal
       and burns ~15s of cooldown per file before noticing.

    2. Stranded directive — directive file in INBOX with either:
         - 2+ FAILED attempts in the recent attempt history, OR
         - latest attempt INITIALIZED/IDLE and last_updated > 24h ago.
       Either signals the operator forgot to re-trigger after a fix,
       or that successive runs are dying at the same stage.

    Read-only; cannot affect pipeline correctness. Best-effort: any
    per-directive I/O or parse error is silently skipped — a malformed
    state file should not blank out the whole snapshot.
    """
    from datetime import datetime, timezone, timedelta

    result: dict[str, Any] = {
        "stale_inbox": [],   # list of directive_id strings
        "stranded": [],      # list of {directive_id, fail_count, latest_status, last_updated}
    }

    if not INBOX_DIR.exists():
        return result

    now = datetime.now(timezone.utc)
    idle_threshold = timedelta(hours=24)

    for txt_path in sorted(INBOX_DIR.glob("*.txt")):
        directive_id = txt_path.stem
        state_path = RUNS_DIR / directive_id / "directive_state.json"
        if not state_path.exists():
            continue

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        attempts = state.get("attempts") or {}
        if not isinstance(attempts, dict) or not attempts:
            continue

        sorted_keys = sorted(attempts.keys())
        latest_key = state.get("latest_attempt") or sorted_keys[-1]
        latest = attempts.get(latest_key) or {}
        latest_status = str(latest.get("status", "?"))

        # 1. Stale: PORTFOLIO_COMPLETE in INBOX
        if latest_status == "PORTFOLIO_COMPLETE":
            result["stale_inbox"].append(directive_id)
            continue

        # 2a. Stranded by repeated failure (last 3 attempts)
        recent = [attempts[k] for k in sorted_keys[-3:] if isinstance(attempts.get(k), dict)]
        fail_count = sum(1 for a in recent if a.get("status") == "FAILED")
        repeat_fails = fail_count >= 2

        # 2b. Stranded by stale idle attempt
        last_updated_raw = state.get("last_updated") or ""
        last_updated_dt = None
        if isinstance(last_updated_raw, str) and last_updated_raw:
            try:
                last_updated_dt = datetime.fromisoformat(
                    last_updated_raw.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                last_updated_dt = None

        is_idle_stale = (
            latest_status in {"INITIALIZED", "IDLE"}
            and last_updated_dt is not None
            and (now - last_updated_dt) > idle_threshold
        )

        if repeat_fails or is_idle_stale:
            result["stranded"].append({
                "directive_id": directive_id,
                "fail_count": fail_count,
                "latest_status": latest_status,
                "last_updated": last_updated_raw,
            })

    return result


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


# Gate test suite — same files the pre-commit hook runs. Matches
# tools/hooks/pre-commit. Update both together.
_GATE_TEST_SUITE = (
    "tests/test_idea_evaluation_gate.py",
    "tests/test_namespace_gate_regex.py",
    "tests/test_sweep_registry_gate_regex.py",
    "tests/test_fvg_session_infra_regressions.py",
    "tests/test_sweep_registry_td004_regression.py",
)


def collect_known_issues() -> dict[str, Any]:
    """Auto-populate Known Issues from runtime signals.

    S2 fix (2026-05-04): pre-fix, the Known Issues section defaulted to
    `- (none)` and required manual edit at session-close. The session-
    close skill's truthfulness gate caught the empty-while-broken case
    but couldn't catch the inverse: a real failure that the operator
    forgot to write down. This auto-populator surfaces the same signals
    the gate checks (gate-suite pytest, intent-index audit,
    sweep_registry caveats) so the file is honest by default.
    Manual entries (deferred TDs, operational context) still live in
    a separate subsection that's preserved across regeneration.

    Returns a dict the renderer formats. Best-effort: any subprocess
    or import error surfaces as an `*_error` key, never raises.
    """
    auto: dict[str, Any] = {
        "pytest_failed": 0,
        "pytest_skipped": 0,
        "pytest_passed": 0,
        "pytest_error": None,
        "intent_index_errors": [],
        "sweep_registry_errors": [],
        "directive_queue": {"stale_inbox": [], "stranded": []},
        "directive_queue_error": None,
        "post_merge_watch": None,
        "post_merge_watch_error": None,
    }

    # 1. Gate test suite — fast, fixed roster, the same one the
    # pre-commit hook gates on. Anything failing here is a real
    # blocker the next session inherits.
    try:
        gate_paths = [str(_TRADE_SCAN_ROOT / p) for p in _GATE_TEST_SUITE]
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *gate_paths,
             "-q", "--tb=no", "--no-header"],
            cwd=str(_TRADE_SCAN_ROOT),
            capture_output=True, text=True, timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        m_pass = re.search(r"(\d+)\s+passed", out)
        m_fail = re.search(r"(\d+)\s+failed", out)
        m_skip = re.search(r"(\d+)\s+skipped", out)
        if m_pass:
            auto["pytest_passed"] = int(m_pass.group(1))
        if m_fail:
            auto["pytest_failed"] = int(m_fail.group(1))
        if m_skip:
            auto["pytest_skipped"] = int(m_skip.group(1))
        if not m_pass and not m_fail:
            auto["pytest_error"] = "could not parse pytest output"
    except Exception as e:
        auto["pytest_error"] = str(e)

    # 2. Intent-index audit — read the most recent validation_errors
    # record from the hook's log instead of re-running the audit (the
    # hook itself logs validation issues every UserPromptSubmit).
    try:
        log_path = _TRADE_SCAN_ROOT / ".claude" / "logs" / "intent_matches.jsonl"
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as f:
                tail = f.readlines()[-100:]
            for line in reversed(tail):
                try:
                    rec = json.loads(line.strip())
                except Exception:
                    continue
                if rec.get("msg") == "intent_index_validation":
                    errs = rec.get("errors", []) or []
                    hard_errs = [e for e in errs if e.get("severity") == "hard"]
                    auto["intent_index_errors"] = [
                        f"{e.get('intent', '?')}: {e.get('error', '?')}"
                        for e in hard_errs
                    ]
                    break
    except Exception:
        pass

    # 3. Sweep registry caveats — short/full hash mismatch is a known
    # signal of registry corruption (TD-004 class).
    try:
        import yaml as _yaml
        registry_path = _TRADE_SCAN_ROOT / "governance" / "namespace" / "sweep_registry.yaml"
        if registry_path.exists():
            data = _yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            ideas = data.get("ideas", {}) or {}
            for idea_id, idea_block in ideas.items():
                sweeps = (idea_block or {}).get("sweeps", {}) or {}
                if not isinstance(sweeps, dict):
                    continue
                for sweep_key, payload in sweeps.items():
                    if not isinstance(payload, dict):
                        continue
                    short = str(payload.get("signature_hash") or "").lower()
                    full = str(payload.get("signature_hash_full") or "").lower()
                    if full and short and len(short) == 16 and not full.startswith(short):
                        auto["sweep_registry_errors"].append(
                            f"idea {idea_id} / {sweep_key}: short/full hash mismatch"
                        )
    except Exception:
        pass

    # 4. Directive queue health: stale INBOX + stranded directives.
    # See _check_directive_queue_health docstring for failure modes.
    try:
        auto["directive_queue"] = _check_directive_queue_health()
    except Exception as e:
        auto["directive_queue_error"] = f"{type(e).__name__}: {e}"

    # 5. Post-merge watch (observer reconcile + status).
    # Reconciling here is the enforcement leg: every SYSTEM_STATE.md
    # regeneration scans new Stage1 runs and updates the watch.
    try:
        from tools.post_merge_watch import reconcile_watch
        auto["post_merge_watch"] = reconcile_watch()
    except Exception as e:
        auto["post_merge_watch_error"] = f"{type(e).__name__}: {e}"

    return auto


# ── Session Status ────────────────────────────────────────────────────────


def compute_session_status(
    engine: dict, freshness: dict, git: dict,
) -> tuple[str, list[str]]:
    """
    Derive a single session status from collected data.

    BROKEN if:
      - Engine manifest not VALID or version not resolved
      - Git has unpushed commits (at session close, this means push was skipped)
      - Data completely stale (latest_bar missing or freshness unreadable)

    WARNING if:
      - Any stale symbols (>3 days behind)
      - Working tree not clean (uncommitted code changes)

    OK: everything else.

    Returns (status, reasons).
    """
    reasons: list[str] = []

    # ── BROKEN checks
    if engine.get("manifest") != "VALID":
        reasons.append(f"BROKEN: Engine manifest {engine.get('manifest', 'UNKNOWN')}")
    if engine.get("version", "UNKNOWN") == "UNKNOWN":
        reasons.append("BROKEN: Engine version not resolved")
    if isinstance(git.get("commits_ahead"), int) and git["commits_ahead"] > 0:
        reasons.append(f"BROKEN: {git['commits_ahead']} commits not pushed to origin")
    if git.get("error"):
        reasons.append(f"BROKEN: Git error — {git['error']}")
    if freshness.get("status") in ("MISSING", "UNREADABLE"):
        reasons.append(f"BROKEN: Data freshness {freshness.get('status')}")
    if freshness.get("latest_bar") in ("unknown", None, ""):
        reasons.append("BROKEN: Latest data bar unknown")

    broken = [r for r in reasons if r.startswith("BROKEN")]
    if broken:
        return "BROKEN", reasons

    # ── WARNING checks
    stale = freshness.get("stale_symbols", 0)
    if stale and stale > 0:
        reasons.append(f"WARNING: {stale} symbol(s) stale (>3 days behind)")
    tree = git.get("working_tree", "unknown")
    if tree != "clean":
        reasons.append(f"WARNING: Working tree {tree}")

    warnings = [r for r in reasons if r.startswith("WARNING")]
    if warnings:
        return "WARNING", reasons

    return "OK", []


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
    session_status: tuple[str, list[str]],
    known_issues: dict | None = None,
) -> str:
    lines: list[str] = []
    status, status_reasons = session_status

    lines.append("# SYSTEM STATE")
    lines.append("")
    lines.append(f"## SESSION STATUS: {status}")
    if status_reasons:
        for r in status_reasons:
            lines.append(f"- {r}")
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
        lines.append(f"- LIVE: {portfolio.get('live', 0)} | RETIRED: {portfolio.get('retired', 0)} | LEGACY: {portfolio.get('legacy', 0)}")
    lines.append("")

    # ── Vault
    lines.append("## Vault (DRY_RUN_VAULT)")
    if vault.get("missing"):
        lines.append("- DRY_RUN_VAULT: NOT FOUND")
    else:
        lines.append(f"- Snapshots: {vault.get('snapshot_count', 0)} | Latest: `{vault.get('latest', 'none')}`")
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
            lines.append(f"- Last substantive commit: `{git['last_commit']}`")
    lines.append("")

    # ── Known Issues / Pending
    lines.append("## Known Issues")

    auto = known_issues or {}
    auto_lines: list[str] = []

    pf = int(auto.get("pytest_failed", 0) or 0)
    ps = int(auto.get("pytest_skipped", 0) or 0)
    pp = int(auto.get("pytest_passed", 0) or 0)
    if auto.get("pytest_error"):
        auto_lines.append(f"- **Gate suite: error running pytest** — {auto['pytest_error']}")
    elif pf > 0:
        auto_lines.append(f"- **Gate suite: {pf} failing test(s)** ({pp} pass, {ps} skip) — `python -m pytest tests/` for detail")
    elif ps > 0:
        auto_lines.append(f"- Gate suite: {ps} skipped test(s) ({pp} pass) — review whether quarantines should be resolved")

    for err in auto.get("intent_index_errors", []) or []:
        auto_lines.append(f"- **Intent-index hard error:** {err}")

    for err in auto.get("sweep_registry_errors", []) or []:
        auto_lines.append(f"- **Sweep registry caveat:** {err}")

    if auto.get("directive_queue_error"):
        auto_lines.append(
            f"- Directive queue health: error — {auto['directive_queue_error']}"
        )
    queue = auto.get("directive_queue") or {}
    for did in queue.get("stale_inbox", []) or []:
        auto_lines.append(
            f"- **Stale INBOX entry:** `{did}` — already PORTFOLIO_COMPLETE; "
            f"remove from INBOX or use `tools/reset_directive.py` for a re-run."
        )
    for s in queue.get("stranded", []) or []:
        did = s.get("directive_id", "?")
        fail_n = int(s.get("fail_count", 0) or 0)
        status = s.get("latest_status", "?")
        last = (s.get("last_updated") or "?")[:10]
        if fail_n >= 2:
            detail = f"{fail_n} consecutive FAILED attempt(s); latest {status} since {last}"
        else:
            detail = f"latest attempt {status} idle since {last}"
        auto_lines.append(
            f"- **Stranded directive:** `{did}` — {detail}. "
            f"Inspect `runs/{did}/directive_audit.log`."
        )

    # Post-merge watch surface
    if auto.get("post_merge_watch_error"):
        auto_lines.append(
            f"- Post-merge watch: error — {auto['post_merge_watch_error']}"
        )
    pmw = auto.get("post_merge_watch")
    if pmw:
        status = pmw.get("status", "?")
        target = pmw.get("target_runs", "?")
        observed = len(pmw.get("runs_observed", []) or [])
        commit = (pmw.get("commit_hash") or "?")[:8]
        if status == "ACTIVE":
            auto_lines.append(
                f"- **Post-merge watch:** {observed}/{target} observed; "
                f"status=ACTIVE; commit={commit}."
            )
        elif status == "CLOSED_OK":
            auto_lines.append(
                f"- **Post-merge watch CLOSED_OK:** {observed}/{target} runs clean "
                f"(commit {commit}). Run `python tools/post_merge_watch.py --archive` "
                f"to clear."
            )
        elif status == "CLOSED_FAIL":
            dirty_ids = [
                o.get("run_id", "?") for o in (pmw.get("runs_observed") or [])
                if o.get("status") == "dirty"
            ]
            preview = ", ".join(dirty_ids[:3])
            more = f" (+{len(dirty_ids) - 3} more)" if len(dirty_ids) > 3 else ""
            auto_lines.append(
                f"- **Post-merge watch CLOSED_FAIL:** {len(dirty_ids)}/{target} runs "
                f"showed warmup fallback or crash (commit {commit}). "
                f"Inspect: {preview}{more}. Run `--archive` after investigation."
            )

    if auto_lines:
        lines.append("### Auto-detected (regenerated each run)")
        lines.extend(auto_lines)
        lines.append("")

    lines.append("### Manual (deferred TDs, operational context)")
    lines.append("<!-- Add tech-debt items, deferred work, and operational caveats here. "
                 "Auto-detected entries above regenerate on each run; entries here persist. -->")
    if not auto_lines:
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
    known_issues = collect_known_issues()

    session_status = compute_session_status(engine, freshness, git)
    markdown = render_markdown(engine, directives, ledgers, portfolio, vault, freshness, runs, git, session_status, known_issues)

    # Preserve operator-edited Manual section across regen. Doc/code
    # contract: SKILL.md says "entries here persist" and the
    # collect_known_issues docstring says the same. Before this fix
    # (2026-05-12), the file was unconditionally overwritten. See
    # outputs/SYSTEM_STATE_MANUAL_PERSIST_AUDIT.md.
    markdown = _preserve_manual_section(output_path, markdown)

    output_path.write_text(markdown, encoding="utf-8")

    status_label = session_status[0]
    print(f"[DONE] SYSTEM_STATE.md written: {output_path}")
    print(f"[SESSION STATUS] {status_label}")
    if session_status[1]:
        for reason in session_status[1]:
            print(f"  {reason}")
    if status_label == "BROKEN":
        print("\n[!] SESSION BROKEN — resolve issues before closing.")


if __name__ == "__main__":
    main()
