"""
Generate a workspace system snapshot as SYSTEM_STATE.md.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_DIR = PROJECT_ROOT / "backtest_directives" / "active"
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
RUNS_DIR = PROJECT_ROOT / "runs"
STRATEGY_LEDGER_PATH = BACKTESTS_DIR / "Strategy_Master_Filter.xlsx"
PORTFOLIO_LEDGER_PATH = PROJECT_ROOT / "strategies" / "Master_Portfolio_Sheet.xlsx"
PREFLIGHT_SCRIPT = PROJECT_ROOT / "governance" / "preflight.py"
ENGINE_ROOT = PROJECT_ROOT / "engine_dev" / "universal_research_engine"
DEFAULT_OUTPUT = PROJECT_ROOT / "SYSTEM_STATE.md"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    as_str = str(value).strip().lower()
    return as_str in {"1", "true", "t", "yes", "y"}


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_engine_version(raw_version: str) -> str:
    cleaned = str(raw_version).strip()
    if not cleaned:
        return "UNKNOWN"

    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    normalized = cleaned.replace(".", "_")
    return f"v{normalized}"


def _candidate_engine_dirs(raw_version: str) -> list[Path]:
    normalized = _normalize_engine_version(raw_version)
    candidates: list[str] = []
    if normalized != "UNKNOWN":
        candidates.append(normalized)
    original = str(raw_version).strip()
    if original:
        candidates.append(original)
        if "." in original:
            candidates.append(f"v{original.replace('.', '_')}")
        if original.startswith("v") and "_" in original:
            candidates.append(original[1:].replace("_", "."))
    deduped = []
    seen = set()
    for name in candidates:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return [ENGINE_ROOT / name for name in deduped]


def _resolve_get_engine_version():
    try:
        from tools.pipeline_utils import get_engine_version

        return get_engine_version
    except Exception:
        module_path = PROJECT_ROOT / "tools" / "pipeline_utils.py"
        if not module_path.exists():
            raise RuntimeError(f"Missing pipeline utils at {module_path}")

        spec = importlib.util.spec_from_file_location("pipeline_utils_local", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load pipeline_utils module spec")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        get_engine_version = getattr(module, "get_engine_version", None)
        if get_engine_version is None:
            raise RuntimeError("pipeline_utils.get_engine_version not found")
        return get_engine_version


def collect_engine_status() -> dict[str, str]:
    active_raw = ""
    active_engine = "UNKNOWN"
    detail = ""
    try:
        get_engine_version = _resolve_get_engine_version()
        active_raw = str(get_engine_version()).strip()
        active_engine = _normalize_engine_version(active_raw)
    except Exception as e:
        detail = f"Unable to resolve active engine version: {e}"

    engine_dir = None
    for candidate in _candidate_engine_dirs(active_raw):
        if candidate.exists() and candidate.is_dir():
            engine_dir = candidate
            break

    manifest_path = None
    if engine_dir is not None:
        for candidate_name in ("VALIDATED_ENGINE.manifest.json", "engine_manifest.json"):
            candidate = engine_dir / candidate_name
            if candidate.exists():
                manifest_path = candidate
                break

    manifest_status = "MISSING"
    if manifest_path is not None:
        try:
            _ = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_status = "VALID"
        except Exception:
            manifest_status = "INVALID"

    out = {
        "active_engine": active_engine,
        "manifest_status": manifest_status,
        "manifest_path": "-",
    }
    if manifest_path is not None:
        out["manifest_path"] = str(manifest_path.relative_to(PROJECT_ROOT))
    if detail:
        out["detail"] = detail
    return out


def collect_active_directives() -> list[dict[str, str]]:
    directives: list[dict[str, str]] = []
    if not ACTIVE_DIR.exists():
        return directives

    for directive_file in sorted([p for p in ACTIVE_DIR.iterdir() if p.is_file()]):
        directive_id = directive_file.stem
        state_file = RUNS_DIR / directive_id / "directive_state.json"

        state = "NOT_INITIALIZED"
        last_updated = "-"
        if state_file.exists():
            payload = _safe_load_json(state_file)
            if payload is None:
                state = "STATE_READ_ERROR"
                last_updated = _iso_mtime(state_file)
            else:
                state = str(payload.get("current_state", "UNKNOWN"))
                last_updated = str(payload.get("last_updated") or payload.get("last_transition") or _iso_mtime(state_file))

        directives.append(
            {
                "directive": directive_file.name,
                "state": state,
                "last_updated": last_updated,
                "path": str(directive_file.relative_to(PROJECT_ROOT)),
            }
        )
    return directives


def collect_artifact_health() -> dict[str, Any]:
    required = {
        "results_tradelevel.csv": lambda d: d / "raw" / "results_tradelevel.csv",
        "results_standard.csv": lambda d: d / "raw" / "results_standard.csv",
        "results_risk.csv": lambda d: d / "raw" / "results_risk.csv",
        "run_metadata.json": lambda d: d / "metadata" / "run_metadata.json",
    }

    run_dirs = [d for d in sorted(BACKTESTS_DIR.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    broken: list[dict[str, str]] = []
    missing_counts = {k: 0 for k in required}

    for run_dir in run_dirs:
        missing = []
        for key, fn in required.items():
            target = fn(run_dir)
            if not target.exists():
                missing.append(key)
                missing_counts[key] += 1
        if missing:
            broken.append({"run_dir": run_dir.name, "missing": ", ".join(missing)})

    healthy = len(run_dirs) - len(broken)
    return {
        "total_run_dirs": len(run_dirs),
        "healthy_run_dirs": healthy,
        "broken_run_dirs": len(broken),
        "missing_counts": missing_counts,
        "broken_samples": broken[:25],
    }


def _empty_or_nan(series: pd.Series) -> pd.Series:
    as_str = series.astype(str).str.strip()
    return series.isna() | (as_str == "") | (as_str.str.lower() == "nan")


def collect_ledger_status() -> dict[str, Any]:
    out: dict[str, Any] = {"strategy_master": None, "portfolio_master": None}

    if STRATEGY_LEDGER_PATH.exists():
        try:
            df = pd.read_excel(STRATEGY_LEDGER_PATH)
            columns_lower = {str(c).strip().lower(): c for c in df.columns}
            run_id_col = columns_lower.get("run_id")
            strategy_col = columns_lower.get("strategy")
            in_port_col = columns_lower.get("in_portfolio")

            duplicate_run_ids = 0
            missing_identity_rows = 0
            in_portfolio_true = 0
            orphan_backtest_rows = 0
            strategies_detected = int(len(df))
            strategies_in_portfolio = 0

            if run_id_col:
                run_ids = df[run_id_col].dropna().astype(str).str.strip()
                run_ids = run_ids[run_ids.str.lower() != "nan"]
                duplicate_run_ids = int(run_ids.duplicated().sum())

            if run_id_col and strategy_col:
                missing_identity_rows = int((_empty_or_nan(df[run_id_col]) | _empty_or_nan(df[strategy_col])).sum())

            if in_port_col:
                in_portfolio_true = int(df[in_port_col].apply(_to_bool).sum())
                strategies_in_portfolio = in_portfolio_true

            if strategy_col:
                strat_names = df[strategy_col].dropna().astype(str).str.strip()
                strat_names = strat_names[(strat_names != "") & (strat_names.str.lower() != "nan")]
                orphan_backtest_rows = int(sum(not (BACKTESTS_DIR / s).exists() for s in strat_names))
                strategies_detected = int(strat_names.nunique())

            out["strategy_master"] = {
                "path": str(STRATEGY_LEDGER_PATH.relative_to(PROJECT_ROOT)),
                "exists": True,
                "rows": int(len(df)),
                "columns": int(len(df.columns)),
                "duplicate_run_ids": duplicate_run_ids,
                "missing_identity_rows": missing_identity_rows,
                "in_portfolio_true_rows": in_portfolio_true,
                "strategies_detected": strategies_detected,
                "strategies_in_portfolio": strategies_in_portfolio,
                "orphan_backtest_rows": orphan_backtest_rows,
            }
        except Exception as e:
            out["strategy_master"] = {
                "path": str(STRATEGY_LEDGER_PATH.relative_to(PROJECT_ROOT)),
                "exists": True,
                "error": str(e),
            }
    else:
        out["strategy_master"] = {
            "path": str(STRATEGY_LEDGER_PATH.relative_to(PROJECT_ROOT)),
            "exists": False,
        }

    if PORTFOLIO_LEDGER_PATH.exists():
        try:
            df = pd.read_excel(PORTFOLIO_LEDGER_PATH)
            columns_lower = {str(c).strip().lower(): c for c in df.columns}
            portfolio_id_col = columns_lower.get("portfolio_id")
            realized_col = columns_lower.get("realized_pnl") or columns_lower.get("net_pnl_usd")

            duplicate_portfolio_ids = 0
            missing_portfolio_id_rows = 0
            rows_missing_realized = 0
            missing_strategy_folder_rows = 0

            if portfolio_id_col:
                pids = df[portfolio_id_col].dropna().astype(str).str.strip()
                pids = pids[pids.str.lower() != "nan"]
                duplicate_portfolio_ids = int(pids.duplicated().sum())
                missing_portfolio_id_rows = int(_empty_or_nan(df[portfolio_id_col]).sum())
                missing_strategy_folder_rows = int(
                    sum(
                        not (PROJECT_ROOT / "strategies" / pid).exists()
                        for pid in pids
                    )
                )

            if realized_col:
                rows_missing_realized = int(df[realized_col].isna().sum())

            out["portfolio_master"] = {
                "path": str(PORTFOLIO_LEDGER_PATH.relative_to(PROJECT_ROOT)),
                "exists": True,
                "rows": int(len(df)),
                "columns": int(len(df.columns)),
                "duplicate_portfolio_ids": duplicate_portfolio_ids,
                "missing_portfolio_id_rows": missing_portfolio_id_rows,
                "rows_missing_realized_pnl": rows_missing_realized,
                "missing_strategy_folder_rows": missing_strategy_folder_rows,
            }
        except Exception as e:
            out["portfolio_master"] = {
                "path": str(PORTFOLIO_LEDGER_PATH.relative_to(PROJECT_ROOT)),
                "exists": True,
                "error": str(e),
            }
    else:
        out["portfolio_master"] = {
            "path": str(PORTFOLIO_LEDGER_PATH.relative_to(PROJECT_ROOT)),
            "exists": False,
        }

    strategy = out.get("strategy_master")
    portfolio = out.get("portfolio_master")
    if (
        isinstance(strategy, dict)
        and strategy.get("exists")
        and "error" not in strategy
        and isinstance(portfolio, dict)
        and portfolio.get("exists")
        and "error" not in portfolio
    ):
        strategy["strategies_in_portfolio"] = int(portfolio.get("rows", strategy.get("strategies_in_portfolio", 0)))

    return out


def collect_pipeline_health(skip_preflight: bool) -> dict[str, Any]:
    if skip_preflight:
        return {
            "status": "SKIPPED",
            "detail": "Skipped via --skip-preflight",
            "output_tail": [],
        }

    if not PREFLIGHT_SCRIPT.exists():
        return {
            "status": "NOT_AVAILABLE",
            "detail": f"Missing {PREFLIGHT_SCRIPT.relative_to(PROJECT_ROOT)}",
            "output_tail": [],
        }

    commands = [
        [sys.executable, "-m", "governance.preflight"],
        [sys.executable, str(PREFLIGHT_SCRIPT)],
    ]
    result = None
    last_error = None
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
            break
        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "detail": "Preflight timed out after 300s", "output_tail": []}
        except Exception as e:
            last_error = e
            continue

    if result is None:
        return {"status": "ERROR", "detail": f"Failed to execute preflight: {last_error}", "output_tail": []}

    merged = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    lines = [ln.rstrip() for ln in merged.splitlines() if ln.strip()]
    tail = lines[-20:] if lines else []
    status = "PASS" if result.returncode == 0 else "FAIL"
    detail = f"Exit code: {result.returncode}"
    return {"status": status, "detail": detail, "output_tail": tail}


def render_markdown(
    directives: list[dict[str, str]],
    artifact_health: dict[str, Any],
    ledger_status: dict[str, Any],
    engine_status: dict[str, str],
    pipeline_health: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# SYSTEM STATE")
    lines.append("")

    lines.append("## Active Directives")
    if not directives:
        lines.append("- No files found under `backtest_directives/INBOX`.")
    else:
        lines.append("| Directive | State | Last Updated | Path |")
        lines.append("|---|---|---|---|")
        for row in directives:
            lines.append(
                f"| {row['directive']} | {row['state']} | {row['last_updated']} | `{row['path']}` |"
            )
    lines.append("")

    lines.append("## Artifact Health")
    lines.append(f"- Backtest run directories scanned: **{artifact_health['total_run_dirs']}**")
    lines.append(f"- Healthy directories: **{artifact_health['healthy_run_dirs']}**")
    lines.append(f"- Directories with missing required artifacts: **{artifact_health['broken_run_dirs']}**")
    lines.append("- Missing artifact counts:")
    for key, value in artifact_health["missing_counts"].items():
        lines.append(f"  - `{key}`: {value}")
    if artifact_health["broken_samples"]:
        lines.append("")
        lines.append("Sample broken directories (up to 25):")
        lines.append("")
        lines.append("| Run Directory | Missing Files |")
        lines.append("|---|---|")
        for row in artifact_health["broken_samples"]:
            lines.append(f"| {row['run_dir']} | {row['missing']} |")
    lines.append("")

    lines.append("## Engine Status")
    lines.append(f"- Active Engine: {engine_status['active_engine']}")
    lines.append(f"- Engine Manifest: {engine_status['manifest_status']}")
    lines.append(f"- Manifest Path: `{engine_status['manifest_path']}`")
    if engine_status.get("detail"):
        lines.append(f"- Detail: {engine_status['detail']}")
    lines.append("")

    lines.append("## Ledger Status")
    strategy = ledger_status["strategy_master"]
    portfolio = ledger_status["portfolio_master"]

    lines.append("### Strategy Master Filter")
    if not strategy or not strategy.get("exists"):
        lines.append(f"- Missing: `{STRATEGY_LEDGER_PATH.relative_to(PROJECT_ROOT)}`")
    elif "error" in strategy:
        lines.append(f"- Error reading `{strategy['path']}`: {strategy['error']}")
    else:
        lines.append(f"- Path: `{strategy['path']}`")
        lines.append(f"- Rows: **{strategy['rows']}** | Columns: **{strategy['columns']}**")
        lines.append(f"- Strategies detected: **{strategy['strategies_detected']}**")
        lines.append(f"- Strategies in portfolio: **{strategy['strategies_in_portfolio']}**")
        lines.append(f"- Duplicate `run_id` rows: **{strategy['duplicate_run_ids']}**")
        lines.append(f"- Rows missing run_id/strategy: **{strategy['missing_identity_rows']}**")
        lines.append(f"- `IN_PORTFOLIO = true` rows: **{strategy['in_portfolio_true_rows']}**")
        lines.append(f"- Rows with missing backtest folder: **{strategy['orphan_backtest_rows']}**")
    lines.append("")

    lines.append("### Portfolio Master Sheet")
    if not portfolio or not portfolio.get("exists"):
        lines.append(f"- Missing: `{PORTFOLIO_LEDGER_PATH.relative_to(PROJECT_ROOT)}`")
    elif "error" in portfolio:
        lines.append(f"- Error reading `{portfolio['path']}`: {portfolio['error']}")
    else:
        lines.append(f"- Path: `{portfolio['path']}`")
        lines.append(f"- Rows: **{portfolio['rows']}** | Columns: **{portfolio['columns']}**")
        lines.append(f"- Duplicate `portfolio_id` rows: **{portfolio['duplicate_portfolio_ids']}**")
        lines.append(f"- Rows missing `portfolio_id`: **{portfolio['missing_portfolio_id_rows']}**")
        lines.append(f"- Rows missing `realized_pnl` value: **{portfolio['rows_missing_realized_pnl']}**")
        lines.append(f"- Rows with missing strategy folder: **{portfolio['missing_strategy_folder_rows']}**")
    lines.append("")

    lines.append("## Pipeline Health")
    lines.append(f"- Preflight status: **{pipeline_health['status']}**")
    lines.append(f"- Detail: {pipeline_health['detail']}")
    if pipeline_health["output_tail"]:
        lines.append("")
        lines.append("Preflight output tail:")
        lines.append("")
        lines.append("```text")
        lines.extend(pipeline_health["output_tail"])
        lines.append("```")
    lines.append("")

    lines.append(f"Generated: {_now_utc()}")
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
        help="Skip running governance/preflight.py during pipeline health check",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()

    directives = collect_active_directives()
    artifact_health = collect_artifact_health()
    ledger_status = collect_ledger_status()
    engine_status = collect_engine_status()
    pipeline_health = collect_pipeline_health(skip_preflight=args.skip_preflight)
    markdown = render_markdown(directives, artifact_health, ledger_status, engine_status, pipeline_health)

    output_path.write_text(markdown, encoding="utf-8")
    print(f"[DONE] SYSTEM STATE written: {output_path}")


if __name__ == "__main__":
    main()
