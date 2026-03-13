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
            avail_start = pd.to_datetime(df_start[t_col].iloc[0], dayfirst=True, format='mixed')
            avail_end = pd.to_datetime(df_end[t_col].iloc[0], dayfirst=True, format='mixed')
            
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
    try:
        from tools.pipeline_utils import parse_directive as _pd
        _parsed_tmp = _pd(directive_full_path)
        _strategy_name = _parsed_tmp.get("strategy", _parsed_tmp.get("test", {}).get("strategy", ""))
        if _strategy_name:
            _existing_strategy = PROJECT_ROOT / "strategies" / _strategy_name / "strategy.py"
            if _existing_strategy.exists():
                import shutil
                shutil.copy2(str(_existing_strategy), str(_existing_strategy.with_suffix(".py.bak")))
        
        from tools.strategy_provisioner import provision_strategy
        if not provision_strategy(str(directive_full_path)):
             return ("BLOCK_EXECUTION", "Strategy Provisioning Failed.", None)
    except Exception as e:
        return ("BLOCK_EXECUTION", f"Strategy Provisioning Exception: {e}", None)

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
