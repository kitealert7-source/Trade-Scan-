"""
Convert legacy directives into governed namespace names.

Safety guarantees:
- Backs up originals before any modification.
- Never fabricates sweep IDs (uses sweep_registry_gate only).
- Never overwrites existing target files.
- Aborts run on sweep collision.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.directive_schema import normalize_signature


DEFAULT_SOURCE_DIR = PROJECT_ROOT / "backtest_directives" / "active"
DEFAULT_STRATEGY_ROOT = PROJECT_ROOT / "strategies"
IDEA_REGISTRY_PATH = PROJECT_ROOT / "governance" / "namespace" / "idea_registry.yaml"
SWEEP_GATE_PATH = PROJECT_ROOT / "tools" / "sweep_registry_gate.py"
NAMESPACE_GATE_PATH = PROJECT_ROOT / "tools" / "namespace_gate.py"


class ConversionError(RuntimeError):
    """Raised for non-collision conversion failures."""


class SweepCollisionError(RuntimeError):
    """Raised when sweep registry reports collision."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConversionError(f"Invalid YAML: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ConversionError(f"Expected mapping YAML: {path}")
    return payload


def _read_directive(path: Path) -> dict[str, Any]:
    return _load_yaml(path)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def _signature_hash(directive_data: dict[str, Any]) -> str:
    signature = normalize_signature(_json_safe(directive_data))
    canonical = json.dumps(signature, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_timeframe(raw_tf: Any) -> str:
    token = str(raw_tf or "").strip().upper().replace(" ", "")
    if not token:
        return ""
    m = re.fullmatch(r"(\d+)([A-Z]+)", token)
    if not m:
        return token
    n, unit = m.group(1), m.group(2)
    unit_map = {
        "M": "M",
        "MIN": "M",
        "H": "H",
        "D": "D",
        "W": "W",
    }
    return f"{n}{unit_map.get(unit, unit)}"


def _list_indicators(d: dict[str, Any]) -> list[str]:
    inds = d.get("indicators", [])
    if isinstance(inds, str):
        inds = [inds]
    if not isinstance(inds, list):
        return []
    return [str(x).strip().lower() for x in inds if str(x).strip()]


def _lower_blob(d: dict[str, Any]) -> str:
    return json.dumps(_json_safe(d), sort_keys=True, ensure_ascii=True).lower()


def _detect_family(d: dict[str, Any], legacy_name: str) -> str:
    indicators = _list_indicators(d)
    blob = _lower_blob(d)
    symbols = d.get("symbols", [])
    if isinstance(symbols, str):
        symbols = [symbols]

    if any(k in d for k in ("state_machine", "usd_stress_filter", "polarity_override", "position_management")):
        return "PORT"
    if "portability" in legacy_name.lower() or "portfolio" in blob:
        return "PORT"

    if "mean_reversion_rules" in d:
        return "MR"

    pa_tokens = ("bos", "choch", "sfp", "ibreak", "pinbar", "engulf", "liqgrab")
    if any(any(t in ind for t in pa_tokens) for ind in indicators):
        return "PA"
    if any(t in blob for t in pa_tokens):
        return "PA"

    if "atrbrk" in blob or "atr_brk" in blob or "breakout" in blob:
        return "BRK"

    if any("volatility_regime" in ind or "atr_percentile" in ind for ind in indicators):
        return "VOL"
    if "volatility_filter" in d:
        return "VOL"

    if len(symbols) > 1 and ("fx" in legacy_name.lower() or "port" in legacy_name.lower()):
        return "PORT"
    return "TREND"


def _detect_model(d: dict[str, Any], family: str) -> str:
    indicators = _list_indicators(d)
    blob = _lower_blob(d)

    if family == "PORT":
        return "PORT"

    if family == "PA":
        pa_map = (
            ("CHOCH", "choch"),
            ("BOS", "bos"),
            ("SFP", "sfp"),
            ("IBREAK", "ibreak"),
            ("PINBAR", "pinbar"),
            ("ENGULF", "engulf"),
            ("LIQGRAB", "liqgrab"),
        )
        for model, key in pa_map:
            if key in blob or any(key in ind for ind in indicators):
                return model
        return "BOS"

    if "rolling_zscore" in blob or "zscore" in blob:
        return "ZREV"
    if "atrbrk" in blob or "atr_brk" in blob:
        return "ATRBRK"
    if family == "BRK" and "breakout" in blob:
        return "ATRBRK"
    if family == "VOL":
        return "VOLEXP"
    if "rsi" in blob:
        return "RSIAVG"
    if family in ("MR", "TREND"):
        return "RSIAVG"
    return "PORT"


def _detect_filter(d: dict[str, Any]) -> str:
    indicators = _list_indicators(d)
    blob = _lower_blob(d)
    vol_filter = d.get("volatility_filter", {})

    trend_clue = any(
        (
            "indicators.trend." in ind
            or "ema_slope" in ind
            or "linreg" in ind
            or "kalman" in ind
            or "trend_persistence" in ind
        )
        for ind in indicators
    )
    if trend_clue:
        return "TRENDFILT"

    atr_clue = "atr_percentile" in blob
    if isinstance(vol_filter, dict):
        atr_clue = atr_clue or any("atr" in str(k).lower() for k in vol_filter.keys())
    if atr_clue:
        return "ATRFILT"

    vol_clue = any("volatility_regime" in ind for ind in indicators) or "volatility_filter" in d
    if vol_clue:
        return "VOLFILT"

    return ""


def _normalize_symbol(symbols: Any) -> str:
    if isinstance(symbols, str):
        symbols = [symbols]
    if not isinstance(symbols, list):
        return "FX"
    norm = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if len(norm) == 1:
        return norm[0]
    return "FX"


def _resolve_idea_id(family: str, idea_registry: dict[str, Any]) -> str:
    ideas = idea_registry.get("ideas", {})
    if not isinstance(ideas, dict):
        raise ConversionError("Invalid idea_registry.yaml: missing 'ideas' mapping.")

    family = str(family).upper()
    candidates = []
    for idea_id, payload in ideas.items():
        if not isinstance(payload, dict):
            continue
        rec_family = str(payload.get("family", "")).strip().upper()
        status = str(payload.get("status", "active")).strip().lower()
        if rec_family == family and status == "active":
            candidates.append(str(idea_id))

    if not candidates:
        raise ConversionError(f"No active idea_id found for family '{family}'.")
    if len(candidates) > 1:
        raise ConversionError(
            f"Ambiguous idea_id for family '{family}': {sorted(candidates)}"
        )
    return candidates[0]


def _reserve_sweep_via_gate(idea_id: str, directive_name: str, signature_hash: str) -> str:
    cmd = [
        sys.executable,
        str(SWEEP_GATE_PATH),
        "--idea-id",
        str(idea_id),
        "--directive-name",
        str(directive_name),
        "--signature-hash",
        str(signature_hash),
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        if "SWEEP_COLLISION" in output:
            raise SweepCollisionError(output.strip())
        raise ConversionError(f"Sweep gate failed: {output.strip()}")

    m = re.search(r"sweep=(S\d{2})", output)
    if not m:
        raise ConversionError(f"Sweep gate output missing sweep token: {output.strip()}")
    return m.group(1)


def _namespace_validate(new_name: str, directive_data: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory(prefix="ns_validate_") as tmpd:
        tmp_path = Path(tmpd) / f"{new_name}.txt"
        tmp_path.write_text(
            yaml.safe_dump(directive_data, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        cmd = [sys.executable, str(NAMESPACE_GATE_PATH), str(tmp_path)]
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            raise ConversionError(f"namespace_gate failed: {output.strip()}")


def _backup_files(files: list[Path], backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        dst = backup_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)


def _update_strategy_name_attr(strategy_file: Path, new_name: str) -> None:
    if not strategy_file.exists():
        return
    name_re = re.compile(r'^(\s*)name\s*=\s*["\']([^"\']*)["\']\s*$')
    lines = strategy_file.read_text(encoding="utf-8").splitlines()
    changed = False
    for i, line in enumerate(lines):
        m = name_re.match(line)
        if m:
            indent = m.group(1)
            lines[i] = f'{indent}name = "{new_name}"'
            changed = True
            break
    if changed:
        strategy_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rename_strategy_folder(strategy_root: Path, old_strategy: str, new_strategy: str) -> None:
    if not old_strategy or not new_strategy or old_strategy == new_strategy:
        return
    src = strategy_root / old_strategy
    dst = strategy_root / new_strategy
    if not src.exists():
        return
    if dst.exists():
        raise ConversionError(f"Target strategy folder already exists: {dst}")

    shutil.move(str(src), str(dst))
    try:
        _update_strategy_name_attr(dst / "strategy.py", new_strategy)
    except Exception:
        # Rollback on post-move failure.
        shutil.move(str(dst), str(src))
        raise


def _is_already_namespaced(path: Path, data: dict[str, Any]) -> bool:
    test_block = data.get("test", {})
    if not isinstance(test_block, dict):
        return False
    t_name = str(test_block.get("name", "")).strip()
    t_strategy = str(test_block.get("strategy", "")).strip()
    # Stable identity: filename must match test.strategy (the immutable namespace anchor).
    # test.name may carry an optional __SUFFIX run-context tag (e.g. __E152) — still namespaced.
    if path.stem != t_strategy:
        return False
    if t_name != t_strategy:
        # Allow test.name = test.strategy + '__' + SUFFIX (uppercase alphanum)
        suffix = t_name[len(t_strategy):]
        if not re.fullmatch(r"__[A-Z0-9]+", suffix):
            return False
    return bool(re.fullmatch(r"(C_)?\d{2}_.+", path.stem))


def convert_promoted(
    source_dir: Path,
    backup_dir: Path,
    rename_strategies: bool,
    strategy_root: Path,
) -> None:
    if not source_dir.exists():
        raise ConversionError(f"Missing folder: {source_dir}")

    files = sorted(source_dir.glob("*.txt"))
    _backup_files(files, backup_dir)
    print(f"[CONFIG] source_dir={source_dir}")
    print(f"[CONFIG] backup_dir={backup_dir}")
    print(f"[CONFIG] rename_strategies={rename_strategies}")

    idea_registry = _load_yaml(IDEA_REGISTRY_PATH)

    scanned = 0
    converted = 0
    skipped = 0
    namespace_errors = 0
    sweep_collisions = 0
    aborted_on_collision = False

    for src in files:
        scanned += 1
        print(f"[SCAN] {src.name}")
        try:
            d = _read_directive(src)
            test = d.get("test", {})
            if not isinstance(test, dict):
                raise ConversionError("Missing 'test' block.")

            if _is_already_namespaced(src, d):
                print("[SKIP] already namespaced")
                skipped += 1
                continue

            family = _detect_family(d, src.stem)
            model = _detect_model(d, family)
            filter_token = _detect_filter(d)
            symbol = _normalize_symbol(d.get("symbols", []))
            tf = _normalize_timeframe(test.get("timeframe"))
            if not tf:
                raise ConversionError("Missing test.timeframe.")

            print(
                f"[CLASS] FAMILY={family} MODEL={model} FILTER={filter_token or 'NONE'} "
                f"SYMBOL={symbol} TF={tf}"
            )

            idea_id = _resolve_idea_id(family, idea_registry)
            print(f"[IDEA] idea_id={idea_id}")

            signature_hash = _signature_hash(d)
            base_name = (
                f"{idea_id}_{family}_{symbol}_{tf}_{model}"
                f"{'_' + filter_token if filter_token else ''}_V1_P00"
            )
            sweep_key = _reserve_sweep_via_gate(
                idea_id=idea_id,
                directive_name=base_name,
                signature_hash=signature_hash,
            )
            print(f"[SWEEP] reserved {sweep_key}")

            new_name = (
                f"{idea_id}_{family}_{symbol}_{tf}_{model}"
                f"{'_' + filter_token if filter_token else ''}_{sweep_key}_V1_P00"
            )
            print(f"[NAME] {new_name}")

            updated = _json_safe(json.loads(json.dumps(_json_safe(d))))
            updated_test = updated.get("test", {})
            updated_test["name"] = new_name
            updated_test["strategy"] = new_name
            updated["test"] = updated_test

            _namespace_validate(new_name, updated)
            print("[PASS] namespace_gate")

            target = source_dir / f"{new_name}.txt"
            if target.exists() and target.resolve() != src.resolve():
                raise ConversionError(f"Target file already exists: {target.name}")

            rendered = yaml.safe_dump(updated, sort_keys=False, allow_unicode=False)
            if target.resolve() == src.resolve():
                if rename_strategies:
                    old_strategy = str(test.get("strategy", "")).strip()
                    _rename_strategy_folder(strategy_root, old_strategy, new_name)
                tmp = src.with_suffix(".txt.tmp")
                tmp.write_text(rendered, encoding="utf-8")
                shutil.move(str(tmp), str(src))
                print(f"[WRITE] file updated {src.name}")
            else:
                with open(target, "x", encoding="utf-8") as f:
                    f.write(rendered)
                try:
                    if rename_strategies:
                        old_strategy = str(test.get("strategy", "")).strip()
                        _rename_strategy_folder(strategy_root, old_strategy, new_name)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                src.unlink()
                print(f"[WRITE] file renamed {src.name} -> {target.name}")

            converted += 1
        except SweepCollisionError as exc:
            sweep_collisions += 1
            skipped += 1
            aborted_on_collision = True
            print(f"[ERROR] sweep collision: {exc}")
            print("[ABORT] Conversion stopped due to registry collision.")
            break
        except Exception as exc:
            skipped += 1
            namespace_errors += 1
            print(f"[ERROR] {exc}")

    print("\n=== CONVERSION SUMMARY ===")
    print(f"files scanned: {scanned}")
    print(f"files converted: {converted}")
    print(f"files skipped: {skipped}")
    print(f"namespace errors: {namespace_errors}")
    print(f"sweep collisions: {sweep_collisions}")
    if aborted_on_collision:
        print("status: aborted_on_collision")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert legacy directives to governed namespace names."
    )
    parser.add_argument(
        "--source-dir",
        default=str(DEFAULT_SOURCE_DIR),
        help="Directive folder to migrate (default: backtest_directives/active).",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Backup folder. Default: <source-dir>_backup",
    )
    parser.add_argument(
        "--rename-strategies",
        action="store_true",
        help="Also rename strategies/<old_strategy>/ -> strategies/<new_strategy>/ and patch Strategy.name.",
    )
    parser.add_argument(
        "--strategy-root",
        default=str(DEFAULT_STRATEGY_ROOT),
        help="Strategy root folder (default: strategies).",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    backup_dir = Path(args.backup_dir) if args.backup_dir else Path(f"{source_dir}_backup")
    strategy_root = Path(args.strategy_root)

    try:
        convert_promoted(
            source_dir=source_dir,
            backup_dir=backup_dir,
            rename_strategies=args.rename_strategies,
            strategy_root=strategy_root,
        )
    except Exception as exc:
        print(f"[FATAL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
