"""
Stage-10 Go-Live Package Generator
==================================
Assembles a deterministic deployment package for a strategy/profile pair.

Usage:
    python tools/generate_golive_package.py <STRATEGY_PREFIX> --profile <PROFILE>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

STRATEGIES_ROOT = PROJECT_ROOT / "strategies"
DIRECTIVES_COMPLETED = PROJECT_ROOT / "backtest_directives" / "completed"
DIRECTIVES_ACTIVE = PROJECT_ROOT / "backtest_directives" / "active"
BACKTESTS_ROOT = PROJECT_ROOT / "backtests"
BROKER_SPECS_ROOT = PROJECT_ROOT / "data_access" / "broker_specs" / "OctaFx"
MASTER_DATA_ROOT = PROJECT_ROOT / "data_root" / "MASTER_DATA"

# Engine metadata written into run_manifest.json
ENGINE_NAME = "capital_wrapper"
ENGINE_VERSION = "1.6"

# Import constants from capital_wrapper.
sys.path.insert(0, str(SCRIPT_DIR))
try:
    from capital_wrapper import (  # noqa: E402
        CONVERSION_MAP,
        PROFILES,
        SIMULATION_SEED,
        _parse_fx_currencies,
    )
except ImportError as exc:
    print(f"[ERROR] Cannot import capital_wrapper: {exc}")
    sys.exit(1)


STAGE1_JOIN_FIELDS = [
    "initial_stop_price",
    "atr_entry",
    "r_multiple",
    "volatility_regime",
    "trend_regime",
    "trend_label",
    "raw_pnl_usd",
]


# ===========================================================================
# Utility
# ===========================================================================

def _abort(msg: str) -> None:
    print(f"[ABORT] {msg}", file=sys.stderr)
    sys.exit(1)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [s.strip() for s in raw.split(",") if s.strip()]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        token = str(item).strip()
        if token:
            out.append(token)
    return out


def _directive_sha256(path: Path) -> str:
    return _sha256_file(path)


# ===========================================================================
# Validation helpers
# ===========================================================================

def validate_inputs(strategy_prefix: str, profile: str) -> None:
    if profile not in PROFILES:
        _abort(
            f"Unknown profile '{profile}'. "
            f"Valid profiles: {', '.join(PROFILES)}"
        )
    if not strategy_prefix.strip():
        _abort("strategy_prefix must not be empty.")


def validate_artifacts(deployable_dir: Path, trade_log: Path, metrics_file: Path) -> None:
    if not deployable_dir.exists():
        _abort(f"Deployable directory not found: {deployable_dir}")

    if not trade_log.exists():
        _abort(f"Trade log not found: {trade_log}")

    if not metrics_file.exists():
        _abort(f"Summary metrics file not found: {metrics_file}")

    with trade_log.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            next(reader)  # header
            next(reader)  # first row
        except StopIteration:
            _abort(f"Trade log exists but contains no trades: {trade_log}")


# ===========================================================================
# Data extraction
# ===========================================================================

def load_trade_log(trade_log: Path) -> list[dict[str, str]]:
    with trade_log.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def extract_symbols_from_trade_log(trades: list[dict[str, str]]) -> list[str]:
    symbols = sorted({row["symbol"].strip().upper() for row in trades if row.get("symbol", "").strip()})
    if not symbols:
        _abort("No symbols could be extracted from deployable_trade_log.csv.")
    return symbols


def extract_data_window(trades: list[dict[str, str]]) -> tuple[str, str]:
    timestamps: list[str] = []
    for row in trades:
        if row.get("entry_timestamp"):
            timestamps.append(row["entry_timestamp"].strip())
        if row.get("exit_timestamp"):
            timestamps.append(row["exit_timestamp"].strip())

    if not timestamps:
        _abort("Cannot infer data window: no timestamps found in trade log.")

    timestamps.sort()
    return timestamps[0][:10], timestamps[-1][:10]


def load_summary_metrics(metrics_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(metrics_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _abort(f"summary_metrics.json is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        _abort(f"summary_metrics.json must contain a JSON object: {metrics_file}")
    return payload


def find_directive(strategy_prefix: str) -> Path:
    candidates = []
    if DIRECTIVES_COMPLETED.exists():
        candidates.extend(DIRECTIVES_COMPLETED.glob("*.txt"))
    if DIRECTIVES_ACTIVE.exists():
        candidates.extend(DIRECTIVES_ACTIVE.glob("*.txt"))

    exact = [f for f in candidates if f.stem == strategy_prefix]
    if exact:
        # completed/ exact takes precedence if both exist.
        exact_sorted = sorted(
            exact,
            key=lambda p: (0 if p.parent == DIRECTIVES_COMPLETED else 1, p.name.lower()),
        )
        return exact_sorted[0]

    prefix_lower = strategy_prefix.lower()
    partial = [f for f in candidates if f.stem.lower().startswith(prefix_lower)]
    if partial:
        partial_sorted = sorted(
            partial,
            key=lambda p: (0 if p.parent == DIRECTIVES_COMPLETED else 1, p.name.lower()),
        )
        return partial_sorted[0]

    _abort(
        f"No directive file found for prefix '{strategy_prefix}' "
        f"in {DIRECTIVES_COMPLETED} or {DIRECTIVES_ACTIVE}"
    )


def load_directive(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        _abort(f"Directive YAML parse failed ({path}): {exc}")
    if not isinstance(payload, dict):
        _abort(f"Directive root is not a mapping: {path}")
    return payload


def extract_symbols_from_directive(directive: dict[str, Any]) -> list[str]:
    symbols = _normalize_list(directive.get("symbols"))
    if not symbols and isinstance(directive.get("test"), dict):
        symbols = _normalize_list(directive["test"].get("symbols"))
    symbols = sorted({s.upper() for s in symbols})
    if not symbols:
        _abort("Directive has no symbols list; cannot freeze symbol universe.")
    return symbols


def extract_session_reset(directive: dict[str, Any]) -> tuple[str, str]:
    order = directive.get("order_placement", {})
    if not isinstance(order, dict):
        return "utc_day", "default"

    raw = order.get("session_reset")
    if raw is None or str(raw).strip() == "":
        return "utc_day", "default"
    return str(raw).strip(), "directive"


def extract_execution_timing(directive: dict[str, Any]) -> str:
    order = directive.get("order_placement", {})
    if isinstance(order, dict):
        val = order.get("execution_timing")
        if val is not None and str(val).strip():
            return str(val).strip()
    return "next_bar_open"


def extract_order_type(directive: dict[str, Any]) -> str:
    order = directive.get("order_placement", {})
    if isinstance(order, dict):
        val = order.get("type")
        if val is not None and str(val).strip():
            return str(val).strip()
    return "market"


def validate_trade_log_symbols(
    trade_symbols: list[str],
    directive_symbols: list[str],
) -> None:
    extra = sorted(set(trade_symbols) - set(directive_symbols))
    if extra:
        _abort(
            "Trade log contains symbols outside directive universe: "
            + ", ".join(extra)
        )
    missing = sorted(set(directive_symbols) - set(trade_symbols))
    if missing:
        print(
            "[WARN] Directive symbols with no closed trades in deployable log: "
            + ", ".join(missing)
        )


# ===========================================================================
# Stage-1 join and snapshots
# ===========================================================================

def _build_stage1_trade_index(
    strategy_prefix: str,
    symbols: list[str],
) -> dict[str, dict[str, str]]:
    """
    Build lookup:
      trade_id -> selected Stage-1 fields from results_tradelevel.csv
    where trade_id is strategy_name|parent_trade_id (same as capital_wrapper).
    """
    index: dict[str, dict[str, str]] = {}
    required = {"strategy_name", "parent_trade_id", "pnl_usd", *STAGE1_JOIN_FIELDS[:-1]}

    for sym in symbols:
        run_dir = BACKTESTS_ROOT / f"{strategy_prefix}_{sym}"
        csv_path = run_dir / "raw" / "results_tradelevel.csv"
        if not csv_path.exists():
            _abort(f"Missing Stage-1 trade file for symbol {sym}: {csv_path}")

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = set(reader.fieldnames or [])
            missing = sorted(required - header)
            if missing:
                _abort(f"{csv_path} missing required fields for enrichment: {missing}")

            for row in reader:
                trade_id = f"{row['strategy_name']}|{row['parent_trade_id']}"
                index[trade_id] = {
                    "initial_stop_price": row.get("initial_stop_price", ""),
                    "atr_entry": row.get("atr_entry", ""),
                    "r_multiple": row.get("r_multiple", ""),
                    "volatility_regime": row.get("volatility_regime", ""),
                    "trend_regime": row.get("trend_regime", ""),
                    "trend_label": row.get("trend_label", ""),
                    "raw_pnl_usd": row.get("pnl_usd", ""),
                }
    return index


def write_enriched_trade_log(
    out_dir: Path,
    deployable_rows: list[dict[str, str]],
    stage1_index: dict[str, dict[str, str]],
) -> None:
    if not deployable_rows:
        _abort("Cannot write enriched_trade_log.csv: deployable rows are empty.")

    base_fields = list(deployable_rows[0].keys())
    fields = base_fields + [f for f in STAGE1_JOIN_FIELDS if f not in base_fields]
    fields.append("stage1_join_status")

    out_path = out_dir / "enriched_trade_log.csv"
    missing_count = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in deployable_rows:
            merged = dict(row)
            stage1 = stage1_index.get(row.get("trade_id", ""))
            if stage1 is None:
                missing_count += 1
                for k in STAGE1_JOIN_FIELDS:
                    merged.setdefault(k, "")
                merged["stage1_join_status"] = "MISSING_STAGE1"
            else:
                merged.update(stage1)
                merged["stage1_join_status"] = "OK"
            writer.writerow(merged)

    print(f"[OK] enriched_trade_log.csv ({len(deployable_rows)} rows, missing_stage1={missing_count})")


def write_broker_specs_snapshot(out_dir: Path, symbols: list[str]) -> None:
    snapshot_dir = out_dir / "broker_specs_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files_manifest = []
    for sym in symbols:
        src = BROKER_SPECS_ROOT / f"{sym}.yaml"
        if not src.exists():
            _abort(f"Missing broker spec for symbol '{sym}': {src}")
        dst = snapshot_dir / src.name
        shutil.copy2(src, dst)
        files_manifest.append(
            {
                "symbol": sym,
                "file": dst.name,
                "sha256": _sha256_file(dst),
                "bytes": dst.stat().st_size,
            }
        )

    payload = {
        "broker": "OctaFx",
        "generated_utc": _iso_utc_now(),
        "file_count": len(files_manifest),
        "files": files_manifest,
    }
    _write_json(out_dir / "broker_specs_manifest.json", payload)
    print(f"[OK] broker_specs_snapshot/ ({len(files_manifest)} specs)")


def _conversion_pairs_for_symbols(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    pairs: dict[str, dict[str, Any]] = {}
    non_fx_symbols: list[str] = []

    for sym in symbols:
        _, quote = _parse_fx_currencies(sym)
        if not quote:
            non_fx_symbols.append(sym)
            continue
        mapping = CONVERSION_MAP.get(quote)
        if mapping is None:
            # USD quote requires no conversion.
            continue
        pair_symbol, inverted = mapping
        pairs[pair_symbol] = {
            "quote_currency": quote,
            "inverted": bool(inverted),
        }
    return pairs, sorted(non_fx_symbols)


def _copy_conversion_pair_files(
    out_dir: Path,
    pair_symbol: str,
    quote_currency: str,
    inverted: bool,
    data_root: Path,
) -> dict[str, Any]:
    pattern = f"*{pair_symbol}*1d*RESEARCH.csv"
    matches = sorted(data_root.rglob(pattern))
    if not matches:
        _abort(
            f"Cannot freeze conversion data for {pair_symbol}: "
            f"no files matching '{pattern}' under {data_root}"
        )

    pair_dir = out_dir / "conversion_data_snapshot" / pair_symbol
    pair_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for src in matches:
        dst = pair_dir / src.name
        if dst.exists():
            # Avoid accidental overwrite collisions if same basename appears twice.
            stem = dst.stem
            suffix = dst.suffix
            counter = 2
            while dst.exists():
                dst = pair_dir / f"{stem}__{counter}{suffix}"
                counter += 1
        shutil.copy2(src, dst)
        copied.append(
            {
                "source_relative": str(src.relative_to(data_root)),
                "snapshot_file": str(dst.relative_to(out_dir)).replace("\\", "/"),
                "sha256": _sha256_file(dst),
                "bytes": dst.stat().st_size,
            }
        )

    return {
        "pair_symbol": pair_symbol,
        "quote_currency": quote_currency,
        "inverted": inverted,
        "file_count": len(copied),
        "files": copied,
    }


def write_conversion_snapshot(out_dir: Path, symbols: list[str], data_root: Path) -> None:
    pairs, non_fx_symbols = _conversion_pairs_for_symbols(symbols)

    manifest_entries = []
    for pair_symbol, info in sorted(pairs.items()):
        manifest_entries.append(
            _copy_conversion_pair_files(
                out_dir=out_dir,
                pair_symbol=pair_symbol,
                quote_currency=info["quote_currency"],
                inverted=info["inverted"],
                data_root=data_root,
            )
        )

    payload = {
        "generated_utc": _iso_utc_now(),
        "data_root": str(data_root),
        "pair_count": len(manifest_entries),
        "pairs": manifest_entries,
        "assumptions": {
            "non_fx_usd_quote_assumption": True,
            "non_fx_symbols": non_fx_symbols,
            "usd_quote_pairs_require_no_conversion_file": True,
        },
    }
    _write_json(out_dir / "conversion_data_manifest.json", payload)
    print(
        "[OK] conversion_data_snapshot/ "
        f"({len(manifest_entries)} conversion pairs, non_fx={len(non_fx_symbols)})"
    )


# ===========================================================================
# Artifact writers
# ===========================================================================

def write_run_manifest(
    out_dir: Path,
    strategy_prefix: str,
    profile: str,
    symbols: list[str],
    data_start: str,
    data_end: str,
    directive_hash: str,
    session_reset_value: str,
    session_reset_source: str,
) -> None:
    manifest = {
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "simulation_seed": SIMULATION_SEED,
        "strategy_prefix": strategy_prefix,
        "selected_profile": profile,
        "symbols": symbols,
        "data_start": data_start,
        "data_end": data_end,
        "directive_sha256": directive_hash,
        "execution_defaults": {
            "session_reset": {
                "value": session_reset_value,
                "source": session_reset_source,
            },
            "non_fx_quote_assumption": "USD",
        },
        "generated_utc": _iso_utc_now(),
    }
    _write_json(out_dir / "run_manifest.json", manifest)
    print(f"[OK] run_manifest.json ({len(symbols)} symbols, {data_start} -> {data_end})")


def write_symbols_manifest(out_dir: Path, symbols: list[str]) -> None:
    payload = [{"symbol": s, "broker": "OctaFx"} for s in symbols]
    _write_json(out_dir / "symbols_manifest.json", payload)
    print(f"[OK] symbols_manifest.json ({len(symbols)} entries)")


def write_selected_profile(
    out_dir: Path,
    profile: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    params = PROFILES[profile]

    max_portfolio_risk = params.get("heat_cap")
    max_leverage = params.get("leverage_cap")
    max_open_trades = params.get("concurrency_cap")

    enforcement = {
        "max_portfolio_risk_pct": max_portfolio_risk,
        "max_leverage": max_leverage,
        "max_open_trades": max_open_trades,
    }

    sizing = {
        "starting_capital": params.get("starting_capital"),
        "fixed_risk_usd": params.get("fixed_risk_usd"),
        "risk_per_trade": params.get("risk_per_trade"),
        "min_lot": params.get("min_lot"),
        "lot_step": params.get("lot_step"),
        "min_lot_fallback": params.get("min_lot_fallback", False),
        "max_risk_multiple": params.get("max_risk_multiple"),
        "dynamic_scaling": params.get("dynamic_scaling", False),
        "min_position_pct": params.get("min_position_pct"),
    }

    canonical = json.dumps(
        {"enforcement": enforcement, "sizing": sizing},
        sort_keys=True,
        separators=(",", ":"),
    )
    profile_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    payload = {
        "profile": profile,
        "profile_hash": profile_hash,
        "profile_hash_algo": "sha256",
        "enforcement": enforcement,
        "sizing": sizing,
        "simulation_metrics": {
            "final_equity": metrics.get("final_equity"),
            "cagr_pct": metrics.get("cagr_pct"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "mar": metrics.get("mar"),
        },
        "selected_at_utc": _iso_utc_now(),
    }
    _write_json(out_dir / "selected_profile.json", payload)
    print(
        f"[OK] selected_profile.json "
        f"(heat_cap={max_portfolio_risk}, leverage_cap={max_leverage}, "
        f"concurrency_cap={max_open_trades})"
    )
    return payload


def copy_directive(out_dir: Path, directive_file: Path) -> None:
    dest = out_dir / "directive_snapshot.yaml"
    shutil.copy2(directive_file, dest)
    print(f"[OK] directive_snapshot.yaml (source: {directive_file.name})")


def write_execution_spec(
    out_dir: Path,
    strategy_prefix: str,
    profile: str,
    symbols: list[str],
    directive: dict[str, Any],
    selected_profile: dict[str, Any],
    session_reset_value: str,
    session_reset_source: str,
) -> None:
    order = directive.get("order_placement", {}) if isinstance(directive.get("order_placement"), dict) else {}
    stop_loss = directive.get("execution_rules", {}).get("stop_loss", {}) if isinstance(directive.get("execution_rules"), dict) else {}
    take_profit = directive.get("execution_rules", {}).get("take_profit", {}) if isinstance(directive.get("execution_rules"), dict) else {}
    trailing_stop = directive.get("execution_rules", {}).get("trailing_stop", {}) if isinstance(directive.get("execution_rules"), dict) else {}
    trade_management = directive.get("trade_management", {}) if isinstance(directive.get("trade_management"), dict) else {}

    lines = [
        "# Execution Spec",
        "",
        f"- Strategy: `{strategy_prefix}`",
        f"- Profile: `{profile}`",
        f"- Generated UTC: `{_iso_utc_now()}`",
        "",
        "## Universe",
        "",
        f"- Symbols ({len(symbols)}): {', '.join(symbols)}",
        "",
        "## Entry Execution",
        "",
        f"- Order type: `{extract_order_type(directive)}`",
        f"- Execution timing: `{extract_execution_timing(directive)}`",
        f"- Session reset: `{session_reset_value}` ({session_reset_source})",
        "",
        "## Exit / Risk Rules",
        "",
        f"- Stop loss config: `{json.dumps(stop_loss, sort_keys=True)}`",
        f"- Take profit config: `{json.dumps(take_profit, sort_keys=True)}`",
        f"- Trailing stop config: `{json.dumps(trailing_stop, sort_keys=True)}`",
        f"- Trade management: `{json.dumps(trade_management, sort_keys=True)}`",
        "",
        "## Live Enforcement (Selected Profile)",
        "",
        f"- Enforcement: `{json.dumps(selected_profile.get('enforcement', {}), sort_keys=True)}`",
        f"- Sizing: `{json.dumps(selected_profile.get('sizing', {}), sort_keys=True)}`",
        "",
        "## Explicit Assumptions",
        "",
        "- Non-FX symbols are treated as USD-quoted for conversion in the capital wrapper.",
        "- USD-quote FX pairs require no conversion pair snapshot.",
    ]

    out_path = out_dir / "execution_spec.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[OK] execution_spec.md")


def write_golive_checklist(
    out_dir: Path,
    profile: str,
    symbols: list[str],
) -> None:
    lines = [
        "# Go-Live Checklist",
        "",
        f"- Generated UTC: `{_iso_utc_now()}`",
        f"- Selected profile: `{profile}`",
        f"- Symbol count: `{len(symbols)}`",
        "",
        "## Artifact Integrity",
        "",
        "- [ ] `run_manifest.json` exists and `directive_sha256` matches approved directive.",
        "- [ ] `selected_profile.json` `profile_hash` verified at engine startup.",
        "- [ ] `symbols_manifest.json` equals approved execution universe.",
        "- [ ] `enriched_trade_log.csv` has `stage1_join_status=OK` for all rows.",
        "- [ ] `broker_specs_snapshot/` exists with one YAML per symbol.",
        "- [ ] `conversion_data_manifest.json` exists and pair_count is expected.",
        "",
        "## Operational Readiness",
        "",
        "- [ ] Broker account configuration matches `broker_specs_snapshot` constraints.",
        "- [ ] Signal guard enabled (`signal_hash` verification).",
        "- [ ] Kill-switch thresholds reviewed and accepted.",
        "- [ ] Monitoring/alert channel tested.",
        "- [ ] Dry-run startup completed without warnings.",
        "",
        "## Sign-off",
        "",
        "- [ ] Research sign-off",
        "- [ ] Risk sign-off",
        "- [ ] Operations sign-off",
    ]
    out_path = out_dir / "golive_checklist.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[OK] golive_checklist.md")


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage-10 Go-Live Package Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python tools/generate_golive_package.py "
            "01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00 --profile FIXED_USD_V1"
        ),
    )
    parser.add_argument(
        "strategy_prefix",
        help="Strategy prefix (for example: 01_MR_FX_1H_ULTC_REGFILT_S08_V1_P00)",
    )
    parser.add_argument(
        "--profile",
        required=True,
        help=f"Capital profile to package. Choices: {', '.join(PROFILES)}",
    )
    parser.add_argument(
        "--data-root",
        default=str(MASTER_DATA_ROOT),
        help="MASTER_DATA root path used to freeze conversion files.",
    )
    args = parser.parse_args()

    strategy_prefix = args.strategy_prefix.strip()
    profile = args.profile.strip()
    data_root = Path(args.data_root)

    strategy_dir = STRATEGIES_ROOT / strategy_prefix
    deployable_dir = strategy_dir / "deployable" / profile
    trade_log = deployable_dir / "deployable_trade_log.csv"
    metrics_file = deployable_dir / "summary_metrics.json"
    out_dir = strategy_dir / "golive"

    print()
    print("=" * 64)
    print("  Stage-10 Go-Live Package Generator")
    print("=" * 64)
    print(f"  Strategy : {strategy_prefix}")
    print(f"  Profile  : {profile}")
    print(f"  Output   : {out_dir}")
    print()

    validate_inputs(strategy_prefix, profile)
    validate_artifacts(deployable_dir, trade_log, metrics_file)

    deployable_rows = load_trade_log(trade_log)
    trade_symbols = extract_symbols_from_trade_log(deployable_rows)
    data_start, data_end = extract_data_window(deployable_rows)
    metrics = load_summary_metrics(metrics_file)

    directive_file = find_directive(strategy_prefix)
    directive = load_directive(directive_file)
    directive_symbols = extract_symbols_from_directive(directive)
    validate_trade_log_symbols(trade_symbols, directive_symbols)

    directive_hash = _directive_sha256(directive_file)
    session_reset_value, session_reset_source = extract_session_reset(directive)

    out_dir.mkdir(parents=True, exist_ok=True)

    write_run_manifest(
        out_dir=out_dir,
        strategy_prefix=strategy_prefix,
        profile=profile,
        symbols=directive_symbols,
        data_start=data_start,
        data_end=data_end,
        directive_hash=directive_hash,
        session_reset_value=session_reset_value,
        session_reset_source=session_reset_source,
    )
    write_symbols_manifest(out_dir, directive_symbols)
    selected_profile = write_selected_profile(out_dir, profile, metrics)
    copy_directive(out_dir, directive_file)

    stage1_index = _build_stage1_trade_index(strategy_prefix, directive_symbols)
    write_enriched_trade_log(out_dir, deployable_rows, stage1_index)
    write_broker_specs_snapshot(out_dir, directive_symbols)
    write_conversion_snapshot(out_dir, directive_symbols, data_root=data_root)
    write_execution_spec(
        out_dir=out_dir,
        strategy_prefix=strategy_prefix,
        profile=profile,
        symbols=directive_symbols,
        directive=directive,
        selected_profile=selected_profile,
        session_reset_value=session_reset_value,
        session_reset_source=session_reset_source,
    )
    write_golive_checklist(out_dir, profile=profile, symbols=directive_symbols)

    print()
    print("-" * 64)
    print(f"  Go-live package complete: {out_dir}")
    print("-" * 64)
    print()


if __name__ == "__main__":
    main()
