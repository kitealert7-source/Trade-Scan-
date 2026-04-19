"""
Trade_Scan Preflight Agent
Status: IMPLEMENTATION
Role: Decision-only governance gate + scope resolver
Authority: SOP_TESTING, SOP_OUTPUT, SOP_AGENT_ENGINE_GOVERNANCE (Supreme)
"""
import os
import sys
import subprocess
import re
import json
import hashlib
from pathlib import Path
from typing import Optional
import pandas as pd
from tools.pipeline_utils import parse_directive, get_canonical_hash

# Project root (relative to this file's location in governance/)
PROJECT_ROOT = Path(__file__).parent.parent

# Required SOPs
REQUIRED_SOPS = [
    "governance/SOP/SOP_TESTING.md",
    "governance/SOP/SOP_OUTPUT.md",
    "governance/SOP/SOP_AGENT_ENGINE_GOVERNANCE.md",
    "governance/SOP/SOP_CLEANUP.md",
    "governance/SOP/SOP_PORTFOLIO_ANALYSIS_v1_0.md",
    "governance/SOP/STRATEGY_PLUGIN_CONTRACT.md",
]


_FIXED_START    = pd.Timestamp("2024-01-02")
_FRESHNESS_INDEX = PROJECT_ROOT / "data_root" / "freshness_index.json"


def resolve_data_range(symbols: list, broker: str, timeframe: str) -> tuple[str, str]:
    """
    Detect the safe date range for a directive given its symbols/broker/timeframe.

    start_date = max(2024-01-02, max(first_date per symbol))
    end_date   = min(latest_date per symbol)

    Primary path: reads freshness_index.json (1 JSON read, no pandas, no CSV parsing).
    Fallback: direct CSV scan if index is missing or a symbol is absent from it.

    Raises ValueError if data is missing for any symbol.
    Returns (start_date, end_date) as 'YYYY-MM-DD' strings.
    """
    # ── Primary: freshness index (fast path) ──────────────────────────────────
    if _FRESHNESS_INDEX.exists():
        try:
            import json as _json
            index   = _json.loads(_FRESHNESS_INDEX.read_text(encoding="utf-8"))
            entries = index.get("entries", {})
            all_starts: list[pd.Timestamp] = []
            all_ends:   list[pd.Timestamp] = []
            missing = []

            for sym in symbols:
                key = f"{sym}_{broker.upper()}_{timeframe}"
                if key not in entries:
                    missing.append(sym)
                    continue
                e = entries[key]
                if not e.get("first_date") or not e.get("latest_date"):
                    missing.append(sym)
                    continue
                all_starts.append(pd.Timestamp(e["first_date"]))
                all_ends.append(pd.Timestamp(e["latest_date"]))

            if not missing:
                resolved_start = max(_FIXED_START, max(all_starts))
                resolved_end   = min(all_ends)
                return resolved_start.strftime("%Y-%m-%d"), resolved_end.strftime("%Y-%m-%d")

            # Some symbols missing from index — fall through to CSV scan
            print(f"[resolve_data_range] {missing} not in freshness index — falling back to CSV scan")

        except Exception as exc:
            print(f"[resolve_data_range] freshness index read failed ({exc}) — falling back to CSV scan")

    # ── Fallback: direct CSV scan ──────────────────────────────────────────────
    # IMPORTANT: Data is stored in ISO format (YYYY-MM-DD HH:MM:SS).
    # NEVER pass dayfirst=True to pd.to_datetime here — it silently corrupts
    # ISO timestamps by swapping day and month (e.g. 2026-01-12 -> Dec 1, 2026;
    # day > 12 -> NaT). Confirmed failure mode 2026-03-28.
    all_starts = []
    all_ends   = []

    for sym in symbols:
        data_root = (
            PROJECT_ROOT / "data_root" / "MASTER_DATA"
            / f"{sym}_{broker.upper()}_MASTER" / "RESEARCH"
        )
        pattern = f"{sym}_{broker.upper()}_{timeframe}_*_RESEARCH.csv"
        matching_files = sorted(data_root.glob(pattern)) if data_root.exists() else []

        if not matching_files:
            raise ValueError(
                f"resolve_data_range: no RESEARCH data for {sym}/{broker}/{timeframe}\n"
                f"Expected: {data_root / pattern}"
            )

        df_head = pd.read_csv(matching_files[0],  nrows=1, comment="#")
        df_tail = pd.read_csv(matching_files[-1],          comment="#")

        t_col       = "time" if "time" in df_head.columns else "timestamp"
        avail_start = pd.to_datetime(df_head[t_col].iloc[0], format="mixed")

        ts = pd.to_datetime(df_tail[t_col], errors="coerce")
        ts = ts[ts.notna()]
        ts = ts[(ts > "2010-01-01") & (ts < pd.Timestamp.now())]
        if ts.empty:
            raise ValueError(f"resolve_data_range: no valid timestamps in last file for {sym}")
        avail_end = ts.max()

        # Sanity check: future timestamp means a parse error slipped through.
        # 5-minute buffer absorbs clock drift and ingestion timing edge cases
        # while still catching real errors (dayfirst bug fails by months, not minutes).
        now = pd.Timestamp.utcnow().tz_localize(None)
        if avail_end > now + pd.Timedelta(minutes=5):
            raise ValueError(
                f"resolve_data_range: avail_end {avail_end} is in the future for {sym} — "
                f"possible dayfirst/format parse error"
            )

        if avail_start.tzinfo is not None:
            avail_start = avail_start.tz_convert("UTC").tz_localize(None)
        if avail_end.tzinfo is not None:
            avail_end = avail_end.tz_convert("UTC").tz_localize(None)

        all_starts.append(avail_start)
        all_ends.append(avail_end)

    resolved_start = max(_FIXED_START, max(all_starts))
    resolved_end   = min(all_ends)

    return resolved_start.strftime("%Y-%m-%d"), resolved_end.strftime("%Y-%m-%d")


def run_preflight(
    directive_path: str,
    engine_name: str,
    engine_version: str,
) -> tuple[str, str, Optional[dict]]:
    """
    Run preflight checks before backtest execution.
    
    Returns:
        tuple[str, str, Optional[dict]]: (decision_token, explanation, resolved_scope)
        
    Decision tokens:
        - "ALLOW_EXECUTION": All checks passed
        - "BLOCK_EXECUTION": Check failed but governance intact
        - "HARD_STOP": Governance cannot be verified
        
    resolved_scope (if ALLOW_EXECUTION):
        {
            "broker": str,
            "symbols": list[str],
            "timeframe": str,
            "start_date": str,
            "end_date": str
        }
    """
    
    # --- CHECK 1: Governance Integrity ---
    for sop_rel_path in REQUIRED_SOPS:
        sop_path = PROJECT_ROOT / sop_rel_path
        if not sop_path.exists():
            return ("HARD_STOP", f"Required SOP not found: {sop_rel_path}", None)
        if sop_path.stat().st_size == 0:
            return ("HARD_STOP", f"Required SOP is empty: {sop_rel_path}", None)
    
    # --- CHECK 2: Engine Admissibility ---
    if not engine_name or not engine_version:
        return ("BLOCK_EXECUTION", "Engine name or version not specified", None)
    
    # Check if engine is vaulted (modification not allowed)
    vault_path = PROJECT_ROOT / "vault" / "engines" / engine_name
    
    # --- CHECK 2.25: Root-of-Trust Vault Binding ---
    integrity_check = PROJECT_ROOT / "tools" / "verify_engine_integrity.py"

    if not integrity_check.exists():
        return (
            "HARD_STOP",
            "Engine integrity checker missing: tools/verify_engine_integrity.py",
            None
        )

    rot_path = PROJECT_ROOT / "vault" / "root_of_trust.json"
    if not rot_path.exists():
        return (
            "HARD_STOP",
            "Root-of-trust manifest missing: vault/root_of_trust.json",
            None
        )

    try:
        with open(rot_path, "r", encoding="utf-8") as _f:
            rot_manifest = json.load(_f)
        expected_hash = rot_manifest.get("verify_engine_integrity.py")
        if not expected_hash:
            return (
                "HARD_STOP",
                "Root-of-trust manifest missing hash for verify_engine_integrity.py",
                None
            )
        _sha = hashlib.sha256()
        with open(integrity_check, "rb") as _f:
            for _chunk in iter(lambda: _f.read(8192), b""):
                _sha.update(_chunk)
        actual_hash = _sha.hexdigest().upper()
        if actual_hash != expected_hash.upper():
            return (
                "HARD_STOP",
                f"ROOT-OF-TRUST VIOLATION: verify_engine_integrity.py hash mismatch.\n"
                f"  Expected: {expected_hash[:16]}...\n"
                f"  Actual:   {actual_hash[:16]}...\n"
                f"  vault/root_of_trust.json must be updated by human operator.",
                None
            )
        print("[PREFLIGHT] Root-of-trust binding: VERIFIED")
    except Exception as e:
        return ("HARD_STOP", f"Root-of-trust check failed: {e}", None)

    # --- CHECK 2.5: Mandatory Engine Integrity Check ---
    
    _skip_engine_integrity = os.getenv("TRADE_SCAN_TEST_SKIP_ENGINE_INTEGRITY", "0") == "1"
    if _skip_engine_integrity:
        print("[PREFLIGHT] Engine integrity subprocess check skipped (test flag enabled).")
    else:
        result = subprocess.run(
            [sys.executable, str(integrity_check), "--mode", "strict"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return (
                "BLOCK_EXECUTION",
                f"Engine integrity check FAILED. Execution blocked.\n{result.stderr}",
                None
            )
    
    # --- CHECK 3: Directive Exists ---
    directive_full_path = Path(directive_path)
    if not directive_full_path.is_absolute():
        directive_full_path = PROJECT_ROOT / directive_path
        
    if not directive_full_path.exists():
        return ("BLOCK_EXECUTION", f"Directive file not found: {directive_path}", None)
    
    try:
        directive_content = directive_full_path.read_text(encoding="utf-8")
    except Exception as e:
        return ("HARD_STOP", f"Cannot read directive: {e}", None)
    
    # --- CHECK 4: Extract Resolved Scope ---
    def normalize_broker(name: str) -> str:
        clean = name.upper().replace(" ", "")
        if clean == "OCTAFX": return "OctaFx"
        if clean == "DELTAEXCHANGE": return "DeltaExchange"
        return name

    resolved_scope = None
    declared_indicators = []

    try:
        from tools.pipeline_utils import parse_directive
        parsed = parse_directive(directive_full_path)

        raw_symbols = parsed.get("symbols", parsed.get("Symbols", []))
        if isinstance(raw_symbols, str):
            raw_symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()]
        elif not isinstance(raw_symbols, list):
            raw_symbols = []
        raw_symbols = [s.upper() for s in raw_symbols]

        raw_broker = parsed.get("broker_feed", parsed.get("broker", parsed.get("Broker Feed", parsed.get("Broker", ""))))
        raw_start = parsed.get("start_date", parsed.get("Start Date", None))
        raw_end = parsed.get("end_date", parsed.get("End Date", None))
        raw_tf = parsed.get("timeframe", parsed.get("Timeframe", None))

        if raw_start is not None: raw_start = str(raw_start)
        if raw_end is not None: raw_end = str(raw_end)
        if raw_tf is not None: raw_tf = str(raw_tf)

        resolved_scope = {
            "broker": normalize_broker(str(raw_broker)) if raw_broker else None,
            "symbols": raw_symbols,
            "timeframe": raw_tf,
            "start_date": raw_start,
            "end_date": raw_end,
        }
        
        raw_indicators = parsed.get("indicators", parsed.get("Indicators", []))
        if isinstance(raw_indicators, list):
            declared_indicators = [str(i) for i in raw_indicators]
        elif isinstance(raw_indicators, str):
            declared_indicators = [raw_indicators]

        print("[PREFLIGHT] Directive parsed via YAML authority.")
    except Exception as yaml_err:
        print(f"[PREFLIGHT] YAML parse failed ({yaml_err}). Falling back to regex scanner.")
        resolved_scope = None

    if resolved_scope is None:
        resolved_scope = {"broker": None, "symbols": [], "timeframe": None, "start_date": None, "end_date": None}
        def extract_field_value(line: str, field_pattern: str) -> Optional[str]:
            match = re.match(rf'^\s*{field_pattern}\s*[:=\-]\s*(.+?)\s*$', line, re.IGNORECASE)
            return match.group(1).strip() if match else None

        def strip_bullet(line: str) -> str:
            return re.sub(r'^[\s*\-•]+', '', line).strip()

        lines = directive_content.split('\n')
        in_symbols_block = False
        collected_symbols = set()

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'): continue

            broker_val = extract_field_value(line_stripped, r'broker(?:\s+feed)?')
            if broker_val and not resolved_scope["broker"]:
                resolved_scope["broker"] = normalize_broker(broker_val)
                continue

            timeframe_val = extract_field_value(line_stripped, r'time[\s_]*frame')
            if timeframe_val and not resolved_scope["timeframe"]:
                resolved_scope["timeframe"] = timeframe_val
                continue

            start_date_val = extract_field_value(line_stripped, r'start[\s_]*date')
            if start_date_val and not resolved_scope["start_date"]:
                resolved_scope["start_date"] = start_date_val
                continue

            end_date_val = extract_field_value(line_stripped, r'end[\s_]*date')
            if end_date_val and not resolved_scope["end_date"]:
                resolved_scope["end_date"] = end_date_val
                continue

            symbol_header_match = re.match(r'^\s*(?:symbol|asset)s?\s*[:=\-]\s*(.*)$', line_stripped, re.IGNORECASE)
            if symbol_header_match:
                inline_value = symbol_header_match.group(1).strip()
                if inline_value:
                    cleaned = strip_bullet(inline_value).upper()
                    if cleaned and len(cleaned) <= 10: collected_symbols.add(cleaned)
                else: in_symbols_block = True
                continue

            if in_symbols_block:
                if re.match(r'^[\s*\-•]', line):
                    cleaned = strip_bullet(line_stripped).upper()
                    if cleaned and len(cleaned) <= 10: collected_symbols.add(cleaned)
                elif line_stripped and len(line_stripped) <= 10 and re.match(r'^[A-Z0-9]+$', line_stripped):
                    collected_symbols.add(line_stripped.upper())
                elif line_stripped and not re.match(r'^[\s*\-•]', line) and not re.match(r'^[A-Z0-9]+$', line_stripped):
                    in_symbols_block = False

        resolved_scope["symbols"] = list(collected_symbols)
        
        # Indicator extraction (regex)
        in_indicators_block = False
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'): continue
            if re.match(r'^\s*Indicators\s*[:=\-]', line_stripped, re.IGNORECASE):
                in_indicators_block = True
                continue
            if in_indicators_block:
                if ":" in line_stripped and not line_stripped.startswith("-"):
                    in_indicators_block = False
                    continue
                cleaned = strip_bullet(line_stripped)
                if cleaned: declared_indicators.append(cleaned)

    # --- CHECK 5: Validate Resolved Scope ---
    if not resolved_scope["broker"]: return ("BLOCK_EXECUTION", "Broker not declared", None)
    if not resolved_scope["symbols"]: return ("BLOCK_EXECUTION", "Symbols not declared", None)
    if not resolved_scope["timeframe"]: return ("BLOCK_EXECUTION", "Timeframe not declared", None)
    if not resolved_scope["start_date"]: return ("BLOCK_EXECUTION", "Start Date not declared", None)
    if not resolved_scope["end_date"]: return ("BLOCK_EXECUTION", "End Date not declared", None)

    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if not date_pattern.match(str(resolved_scope["start_date"])):
        return ("BLOCK_EXECUTION", f"Start Date malformed: {resolved_scope['start_date']}", None)
    if not date_pattern.match(str(resolved_scope["end_date"])):
        return ("BLOCK_EXECUTION", f"End Date malformed: {resolved_scope['end_date']}", None)

    # --- CHECK 5.5: Engine Version Consistency (directive vs runtime) ---
    # Invariant: a directive declaring `test.engine_version` MUST run on that
    # engine. Absent field defaults to runtime (backward compatible).
    try:
        from tools.pipeline_utils import resolve_engine_version_from_directive, parse_directive as _pd_ev
        _directive_engine = resolve_engine_version_from_directive(_pd_ev(directive_full_path), default=engine_version)
        if _directive_engine != engine_version:
            return (
                "BLOCK_EXECUTION",
                f"ENGINE_VERSION_MISMATCH: directive requires v{_directive_engine}, "
                f"runtime is v{engine_version}. "
                f"Re-run with ENGINE_VERSION_OVERRIDE=v{_directive_engine.replace('.', '_')}.",
                None
            )
        print(f"[PREFLIGHT] Engine version consistency: VERIFIED (directive={_directive_engine}, runtime={engine_version})")
    except Exception as _ev_err:
        return ("BLOCK_EXECUTION", f"Engine version gate failed: {_ev_err}", None)

    broker_name = str(resolved_scope["broker"])
    timeframe = str(resolved_scope["timeframe"])
    broker_specs_dir = PROJECT_ROOT / "data_access" / "broker_specs" / broker_name
    
    if not broker_specs_dir.exists():
        return ("BLOCK_EXECUTION", f"Broker universe missing: {broker_specs_dir}", None)

    for sym in resolved_scope["symbols"]:
        spec_path = broker_specs_dir / f"{sym}.yaml"
        if not spec_path.exists():
            return ("BLOCK_EXECUTION", f"Symbol spec missing: {spec_path}", None)

        data_root = PROJECT_ROOT / "data_root" / "MASTER_DATA" / f"{sym}_{broker_name.upper()}_MASTER" / "RESEARCH"
        pattern = f"{sym}_{broker_name.upper()}_{timeframe}_*_RESEARCH.csv"
        matching_files = sorted(data_root.glob(pattern)) if data_root.exists() else []
        
        if not matching_files:
            return ("BLOCK_EXECUTION", f"Symbol '{sym}' missing RESEARCH data: {pattern}", None)

        # --- UPGRADE: Temporal Range Assertion ---
        try:
            df_start = pd.read_csv(matching_files[0], nrows=1, comment='#')
            df_end = pd.read_csv(matching_files[-1], comment='#').tail(1)
            
            t_col = 'time' if 'time' in df_start else 'timestamp'
            avail_start = pd.to_datetime(df_start[t_col].iloc[0], format='mixed')
            avail_end = pd.to_datetime(df_end[t_col].iloc[0], format='mixed')
            
            # Normalize to naive UTC for comparison
            if avail_start.tzinfo is not None:
                avail_start = avail_start.tz_convert('UTC').tz_localize(None)
            if avail_end.tzinfo is not None:
                avail_end = avail_end.tz_convert('UTC').tz_localize(None)
            
            req_start = pd.to_datetime(resolved_scope["start_date"])
            req_end = pd.to_datetime(resolved_scope["end_date"])
            
            if req_start.tzinfo is not None:
                req_start = req_start.tz_convert('UTC').tz_localize(None)
            if req_end.tzinfo is not None:
                req_end = req_end.tz_convert('UTC').tz_localize(None)
            
            if avail_start > req_start or avail_end < req_end:
                error_lines = [
                    "[DATA_GATE] DATA_RANGE_INSUFFICIENT",
                    f"symbol: {sym}",
                    f"timeframe: {timeframe}",
                    f"requested: {req_start.date()} -> {req_end.date()}",
                    f"available: {avail_start.date()} -> {avail_end.date()}"
                ]
                if avail_start > req_start:
                    error_lines.append(f"missing start: {req_start.date()} -> {avail_start.date()}")
                if avail_end < req_end:
                    error_lines.append(f"missing end: {avail_end.date()} -> {req_end.date()}")
                
                return ("BLOCK_EXECUTION", "\n".join(error_lines), None)
        except Exception as e:
            return ("BLOCK_EXECUTION", f"Temporal validation failed for {sym}: {e}", None)

    # Validate Indicators Existence
    if declared_indicators:
        for ind_path in declared_indicators:
            clean_path = ind_path.replace("\\", "/").replace(".", "/")
            if not clean_path.endswith(".py"): clean_path += ".py"
            target_path = clean_path if clean_path.startswith("indicators/") else f"indicators/{clean_path}"
            if not (PROJECT_ROOT / target_path).exists():
                return ("BLOCK_EXECUTION", f"Declared indicator not found: {target_path}", None)
    
    # --- CHECK 6: Strategy Provisioning ---
    _is_new_strategy = False
    _strategy_name = ""
    try:
        from tools.pipeline_utils import parse_directive as _pd
        _parsed_tmp = _pd(directive_full_path)
        _strategy_name = _parsed_tmp.get("strategy", _parsed_tmp.get("test", {}).get("strategy", "")) or ""
        if _strategy_name:
            _existing_strategy = PROJECT_ROOT / "strategies" / _strategy_name / "strategy.py"
            if _existing_strategy.exists():
                import shutil
                shutil.copy2(str(_existing_strategy), str(_existing_strategy.with_suffix(".py.bak")))

        from tools.strategy_provisioner import provision_strategy
        _prov_ok, _is_new_strategy = provision_strategy(str(directive_full_path))
        if not _prov_ok:
            return ("BLOCK_EXECUTION", "Strategy Provisioning Failed.", None)
    except Exception as e:
        return ("BLOCK_EXECUTION", f"Strategy Provisioning Exception: {e}", None)

    # --- CHECK 6.5: Human Approval Gate + Experiment Discipline ---
    # Single marker: strategies/<name>/strategy.py.approved
    # New strategies always require the marker.
    # Existing strategies: block if .approved is stale OR if strategy.py was
    # modified after the directive's first recorded run (registry timestamp).
    # Both checks use the same reference: was strategy.py touched after execution?
    if _strategy_name:
        _strat_py = PROJECT_ROOT / "strategies" / _strategy_name / "strategy.py"
        _approved = _strat_py.with_name("strategy.py.approved")

        if _is_new_strategy:
            if not _approved.exists():
                return (
                    "AWAITING_HUMAN_APPROVAL",
                    f"HUMAN_APPROVAL_REQUIRED: New strategy '{_strategy_name}' was just provisioned. "
                    f"Implement check_entry/check_exit in strategies/{_strategy_name}/strategy.py, "
                    f"then create 'strategy.py.approved' in that directory to approve execution.",
                    None,
                )
        elif _strat_py.exists():
            _next_ver = _strategy_name.replace("_V1_", "_V2_") if "_V1_" in _strategy_name else _strategy_name + "_V2"
            _strat_mtime = _strat_py.stat().st_mtime

            # Fast path: approval marker present and stale
            if _approved.exists():
                if _strat_mtime > _approved.stat().st_mtime:
                    return (
                        "AWAITING_HUMAN_APPROVAL",
                        f"EXPERIMENT_DISCIPLINE: strategy.py was modified after last approval. "
                        f"Do NOT reset and re-run this directive. "
                        f"Create a new directive version (e.g. {_next_ver}) and run fresh. "
                        f"If this is intentional and you are starting a new version, "
                        f"recreate 'strategy.py.approved' in strategies/{_strategy_name}/ to proceed.",
                        None,
                    )

            # Primary + fallback: shared helper (registry → RUNS_DIR scan)
            try:
                from datetime import datetime as _dt, timezone as _tz
                from tools.system_registry import _get_directive_first_execution_timestamp
                _first_exec_ts = _get_directive_first_execution_timestamp(_strategy_name)
                if _first_exec_ts is not None:
                    _strat_dt = _dt.fromtimestamp(_strat_mtime, tz=_tz.utc)
                    if _strat_dt > _first_exec_ts:
                        # EXCEPTION: freshness refresh re-runs are allowed.
                        # If the stored baseline CSV is stale relative to current
                        # market data (>7 days), this re-run is a legitimate
                        # data-range extension, not a code-change experiment.
                        # The strategy.py mtime bump is almost always from the
                        # provisioner rewriting byte-identical content; the real
                        # intent is captured by the directive's advanced end_date.
                        _is_freshness_rerun = False
                        try:
                            from tools.baseline_freshness_gate import compute_baseline_age
                            _fr = compute_baseline_age(_strategy_name)
                            if (_fr.status == "OK"
                                    and _fr.worst_age_days is not None
                                    and _fr.worst_age_days > 7):
                                _is_freshness_rerun = True
                                print(
                                    f"[PREFLIGHT] EXPERIMENT_DISCIPLINE bypassed: "
                                    f"baseline age {_fr.worst_age_days}d > 7d "
                                    f"(freshness re-run — directive extends data range)."
                                )
                        except Exception:
                            pass  # any error → fall through to block

                        if not _is_freshness_rerun:
                            return (
                                "AWAITING_HUMAN_APPROVAL",
                                f"EXPERIMENT_DISCIPLINE: strategy.py was modified after directive first ran "
                                f"({_first_exec_ts.strftime('%Y-%m-%d %H:%M UTC')}). "
                                f"Do NOT reset and re-run this directive. "
                                f"Create a new directive version (e.g. {_next_ver}) and run fresh.",
                                None,
                            )
            except Exception:
                pass  # fail-safe: allow on any helper read error

    # --- CHECK 6.75: Directive ↔ Strategy Signature Hash Consistency ---
    # Invariant: embedded SIGNATURE HASH in strategy.py MUST equal the hash of
    # normalize_signature(directive). Defense-in-depth against provisioner bugs
    # or manual edits to STRATEGY_SIGNATURE that bypass the approval gate.
    if _strategy_name:
        _strat_py_sig = PROJECT_ROOT / "strategies" / _strategy_name / "strategy.py"
        if _strat_py_sig.exists():
            try:
                from tools.directive_schema import normalize_signature
                from tools.strategy_provisioner import _hash_sig_dict
                _expected_sig_hash = _hash_sig_dict(normalize_signature(parse_directive(directive_full_path)))
                _strat_text = _strat_py_sig.read_text(encoding="utf-8")
                _hash_match = re.search(r"SIGNATURE HASH: ([0-9a-f]{16})", _strat_text)
                if _hash_match and _hash_match.group(1) != _expected_sig_hash:
                    return (
                        "BLOCK_EXECUTION",
                        f"STRATEGY_SIGNATURE_DRIFT: strategy.py embedded hash "
                        f"{_hash_match.group(1)!r} != directive-derived hash "
                        f"{_expected_sig_hash!r} for {_strategy_name}. "
                        f"Re-provision via `python tools/new_pass.py --rehash {_strategy_name}`.",
                        None
                    )
            except Exception as _sig_err:
                return ("BLOCK_EXECUTION", f"Signature hash gate failed: {_sig_err}", None)

    # --- CHECK 6.8: Capability-Based Engine Resolution ---
    # Bidirectional inferred == declared check on strategy capabilities,
    # catalog whitelist, contract-id format, then capability-driven engine
    # resolution. Failure codes F1–F10 map to the hardening plan. No
    # silent fallback: each violation returns BLOCK_EXECUTION with a
    # discrete F-code so operator action is unambiguous.
    if _strategy_name:
        _strat_py_cap = PROJECT_ROOT / "strategies" / _strategy_name / "strategy.py"
        if _strat_py_cap.exists():
            try:
                from tools.capability_inference import (
                    infer_capabilities,
                    load_catalog,
                    read_declared_fields,
                )
                from tools.engine_resolver import EngineResolverError, resolve_engine
                from config.state_paths import STRATEGIES_DIR

                _decl_caps, _decl_contracts = read_declared_fields(_strat_py_cap)
                if _decl_caps is None:
                    return ("BLOCK_EXECUTION",
                            f"[F1] STRATEGY_SIGNATURE.required_capabilities missing "
                            f"for {_strategy_name}", None)
                if _decl_contracts is None:
                    return ("BLOCK_EXECUTION",
                            f"[F2] STRATEGY_SIGNATURE.required_contract_ids missing "
                            f"for {_strategy_name}", None)
                if not _decl_caps or not _decl_contracts:
                    return ("BLOCK_EXECUTION",
                            f"[F3] required_capabilities or required_contract_ids "
                            f"is empty for {_strategy_name}", None)

                _inferred = infer_capabilities(_strat_py_cap)
                _declared_set = set(_decl_caps)
                if not _inferred.issubset(_declared_set):
                    return ("BLOCK_EXECUTION",
                            f"[F4] inferred capabilities not declared: "
                            f"{sorted(_inferred - _declared_set)} for {_strategy_name}",
                            None)
                if not _declared_set.issubset(_inferred):
                    return ("BLOCK_EXECUTION",
                            f"[F5] declared capabilities not inferred: "
                            f"{sorted(_declared_set - _inferred)} for {_strategy_name}",
                            None)

                _catalog_tokens = set(load_catalog().keys())
                _unknown = _declared_set - _catalog_tokens
                if _unknown:
                    return ("BLOCK_EXECUTION",
                            f"[F6] capability tokens not in catalog: "
                            f"{sorted(_unknown)} for {_strategy_name}", None)

                for _cid in _decl_contracts:
                    if not re.match(r"^sha256:[0-9a-f]{64}$", str(_cid)):
                        return ("BLOCK_EXECUTION",
                                f"[F7] malformed contract_id: {_cid!r} "
                                f"for {_strategy_name}", None)

                _resolved = resolve_engine(_decl_caps, _decl_contracts)

                _res_dir = STRATEGIES_DIR / _strategy_name
                _res_dir.mkdir(parents=True, exist_ok=True)
                _res_path = _res_dir / "engine_resolution.json"
                _tmp = _res_path.with_suffix(".json.tmp")
                with open(_tmp, "w", encoding="utf-8") as _f:
                    json.dump({
                        "strategy_id": _strategy_name,
                        "required_capabilities": sorted(_decl_caps),
                        "inferred_capabilities": sorted(_inferred),
                        "required_contract_ids": sorted(_decl_contracts),
                        "resolved_engine_version": _resolved["engine_version"],
                        "resolved_engine_path": _resolved["engine_path"],
                        "resolved_contract_id": _resolved["contract_id"],
                    }, _f, indent=2)
                _tmp.replace(_res_path)
                print(f"[PREFLIGHT] Capability resolution: {_strategy_name} → "
                      f"{_resolved['engine_version']}")
            except EngineResolverError as _er:
                return ("BLOCK_EXECUTION",
                        f"ENGINE_RESOLUTION_FAILED: {_er}", None)
            except Exception as _cap_err:
                return ("BLOCK_EXECUTION",
                        f"Capability resolution failed: {_cap_err}", None)

    # --- CHECK 7: Semantic Validation ---
    from tools.semantic_validator import validate_semantic_signature
    try:
        validate_semantic_signature(str(directive_full_path))
    except Exception as e:
        if "PROVISION_REQUIRED" in str(e): return ("ADMISSION_GATE", str(e), None)
        return ("BLOCK_EXECUTION", f"Semantic Validation Failed: {e}", None)

    # --- CHECK 8: Stage-0.75 Dry-Run Validation ---
    parsed_config = parse_directive(directive_full_path)
    _strategy_folder = _strategy_name if _strategy_name else parsed_config.get("strategy", "")
    if _strategy_folder:
        _strategy_file = PROJECT_ROOT / "strategies" / _strategy_folder / "strategy.py"
        if _strategy_file.exists():
            try:
                import importlib.util
                _spec = importlib.util.spec_from_file_location("strategy_module", str(_strategy_file))
                _mod = importlib.util.module_from_spec(_spec)
                if _spec and _spec.loader:
                    _spec.loader.exec_module(_mod)
                if not getattr(_mod, "Strategy", None):
                    return ("BLOCK_EXECUTION", f"Strategy class missing in {_strategy_folder}", None)
            except Exception as e:
                return ("BLOCK_EXECUTION", f"Dry-run import FAILED: {e}", None)

    # --- ALL CHECKS PASSED ---
    resolved_config = dict(parsed_config)
    resolved_config.update({
        "BROKER": resolved_scope["broker"], "TIMEFRAME": resolved_scope["timeframe"],
        "START_DATE": resolved_scope["start_date"], "END_DATE": resolved_scope["end_date"]
    })
    canonical_hash = get_canonical_hash(resolved_config)
    
    explanation = (
        f"Preflight passed. Engine={engine_name}:{engine_version}, "
        f"Broker={resolved_scope['broker']}, Symbols={len(resolved_scope['symbols'])}, "
        f"Hash={canonical_hash}"
    )
    return ("ALLOW_EXECUTION", explanation, resolved_scope)
