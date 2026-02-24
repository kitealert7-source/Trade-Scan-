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
from pathlib import Path
from typing import Optional
from tools.pipeline_utils import parse_directive, get_canonical_hash

# Project root (relative to this file's location in governance/)
PROJECT_ROOT = Path(__file__).parent.parent

# Required SOPs
REQUIRED_SOPS = [
    "governance/SOP/SOP_TESTING.md",
    "governance/SOP/SOP_OUTPUT.md",
    "governance/SOP/SOP_AGENT_ENGINE_GOVERNANCE.md"
]


def run_preflight(
    directive_path: str,
    engine_name: str,
    engine_version: str,
    skip_vault_check: bool = False
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
    if not skip_vault_check and vault_path.exists():
        pass
    
    # --- CHECK 2.5: Mandatory Engine Integrity Check ---
    integrity_check = PROJECT_ROOT / "tools" / "verify_engine_integrity.py"
    
    if not integrity_check.exists():
        return (
            "HARD_STOP",
            "Engine integrity checker missing: tools/verify_engine_integrity.py",
            None
        )
    
    mode = "workspace" if skip_vault_check else "strict"
    result = subprocess.run(
        [sys.executable, str(integrity_check), "--mode", mode],
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
    # Layered approach: try authoritative YAML parser first, fall back to
    # human-tolerant regex scanner if the directive isn't strict YAML.

    def normalize_broker(name: str) -> str:
        """Normalize broker name to match directory convention."""
        clean = name.upper().replace(" ", "")
        if clean == "OCTAFX":
            return "OctaFx"
        if clean == "DELTAEXCHANGE":
            return "DeltaExchange"
        return name

    resolved_scope = None
    declared_indicators = []

    # --- PRIMARY PATH: Authoritative YAML parser ---
    try:
        from tools.pipeline_utils import parse_directive
        parsed = parse_directive(directive_full_path)

        # Extract symbols — handle list or string
        raw_symbols = parsed.get("symbols", parsed.get("Symbols", []))
        if isinstance(raw_symbols, str):
            raw_symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()]
        elif not isinstance(raw_symbols, list):
            raw_symbols = []
        # Normalize to uppercase
        raw_symbols = [s.upper() for s in raw_symbols]

        raw_broker = parsed.get("broker_feed", parsed.get("broker", parsed.get("Broker Feed", parsed.get("Broker", ""))))
        raw_start = parsed.get("start_date", parsed.get("Start Date", None))
        raw_end = parsed.get("end_date", parsed.get("End Date", None))
        raw_tf = parsed.get("timeframe", parsed.get("Timeframe", None))

        # Coerce dates to string (YAML may parse as datetime)
        if raw_start is not None:
            raw_start = str(raw_start)
        if raw_end is not None:
            raw_end = str(raw_end)
        if raw_tf is not None:
            raw_tf = str(raw_tf)

        resolved_scope = {
            "broker": normalize_broker(str(raw_broker)) if raw_broker else None,
            "symbols": raw_symbols,
            "timeframe": raw_tf,
            "start_date": raw_start,
            "end_date": raw_end,
        }
        # Extract indicators
        raw_indicators = parsed.get("indicators", parsed.get("Indicators", []))
        if isinstance(raw_indicators, list):
            declared_indicators = [str(i) for i in raw_indicators]
        elif isinstance(raw_indicators, str):
            declared_indicators = [raw_indicators]

        print("[PREFLIGHT] Directive parsed via YAML authority.")
    except Exception as yaml_err:
        print(f"[PREFLIGHT] YAML parse failed ({yaml_err}). Falling back to regex scanner.")
        resolved_scope = None  # Signal fallback

    # --- FALLBACK PATH: Human-tolerant regex scanner ---
    if resolved_scope is None:
        resolved_scope = {
            "broker": None,
            "symbols": [],
            "timeframe": None,
            "start_date": None,
            "end_date": None
        }

        def extract_field_value(line: str, field_pattern: str) -> Optional[str]:
            """Extract value from line matching field pattern with :, -, or = separator."""
            match = re.match(
                rf'^\s*{field_pattern}\s*[:=\-]\s*(.+?)\s*$',
                line,
                re.IGNORECASE
            )
            if match:
                return match.group(1).strip()
            return None

        def strip_bullet(line: str) -> str:
            """Remove leading bullet characters and whitespace."""
            return re.sub(r'^[\s*\-•]+', '', line).strip()

        lines = directive_content.split('\n')
        in_symbols_block = False
        collected_symbols = set()

        for line in lines:
            line_stripped = line.strip()

            if not line_stripped or line_stripped.startswith('#'):
                continue

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
                    if cleaned and len(cleaned) <= 10:
                        collected_symbols.add(cleaned)
                else:
                    in_symbols_block = True
                continue

            if in_symbols_block:
                if re.match(r'^[\s*\-•]', line):
                    cleaned = strip_bullet(line_stripped).upper()
                    if cleaned and len(cleaned) <= 10:
                        collected_symbols.add(cleaned)
                elif line_stripped and len(line_stripped) <= 10 and re.match(r'^[A-Z0-9]+$', line_stripped):
                    collected_symbols.add(line_stripped.upper())
                elif line_stripped and not re.match(r'^[\s*\-•]', line) and not re.match(r'^[A-Z0-9]+$', line_stripped):
                    in_symbols_block = False

        resolved_scope["symbols"] = list(collected_symbols)

        # Indicator extraction (regex path)
        declared_indicators = []
        in_indicators_block = False
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'):
                continue
            if re.match(r'^\s*Indicators\s*[:=\-]', line_stripped, re.IGNORECASE):
                in_indicators_block = True
                continue
            if in_indicators_block:
                if ":" in line_stripped and not line_stripped.startswith("-"):
                    in_indicators_block = False
                    continue
                cleaned = re.sub(r'^[\s*\-•]+', '', line_stripped).strip()
                if cleaned:
                    declared_indicators.append(cleaned)

    # --- CHECK 5: Validate Resolved Scope (applies to both YAML and regex paths) ---
    if not resolved_scope["broker"]:
        return ("BLOCK_EXECUTION", "Broker not declared in directive", None)

    if not resolved_scope["symbols"]:
        return ("BLOCK_EXECUTION", "Symbols not declared in directive", None)

    if not resolved_scope["timeframe"]:
        return ("BLOCK_EXECUTION", "Timeframe not declared in directive", None)

    if not resolved_scope["start_date"]:
        return ("BLOCK_EXECUTION", "Start Date not declared in directive", None)

    if not resolved_scope["end_date"]:
        return ("BLOCK_EXECUTION", "End Date not declared in directive", None)

    # Validate date format (simple check)
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if not date_pattern.match(str(resolved_scope["start_date"])):
        return ("BLOCK_EXECUTION", f"Start Date malformed: {resolved_scope['start_date']}", None)

    if not date_pattern.match(str(resolved_scope["end_date"])):
        return ("BLOCK_EXECUTION", f"End Date must be explicit YYYY-MM-DD, got: {resolved_scope['end_date']}", None)

    # Validate Existence
    if declared_indicators:
        indicators_root = PROJECT_ROOT / "indicators"
        for ind_path in declared_indicators:
            # normalize path sep just in case, though usually forward slash in directives
            clean_path = ind_path.replace("\\", "/").replace(".", "/")
            if not clean_path.endswith(".py"):
                clean_path += ".py"
            
            # Remove duplicate 'indicators/' prefix if present
            if clean_path.startswith("indicators/"):
                target_path = clean_path
            else:
                target_path = f"indicators/{clean_path}"
            
            target_file = PROJECT_ROOT / target_path
            
            if not target_file.exists():
                return (
                    "BLOCK_EXECUTION", 
                    f"Preflight Error: Declared indicator not found: {target_path}", 
                    None
                )
    
    # --- CHECK 6: Strategy Provisioning (Directive-Driven Mode) ---
    # Authority: SOP_TESTING (Stage-0 Provisioning)
    # If strategy folder is missing or needs update, provision it now.
    
    from tools.strategy_provisioner import provision_strategy
    
    print(f"[PREFLIGHT] Provisioning Strategy Artifacts for {directive_path}...")
    try:
        if not provision_strategy(str(directive_full_path)):
             return ("BLOCK_EXECUTION", "Strategy Provisioning Failed.", None)
    except Exception as e:
        return ("BLOCK_EXECUTION", f"Strategy Provisioning Exception: {e}", None)

    # --- CHECK 7: Semantic Validation (Stage-0.5) ---
    from tools.semantic_validator import validate_semantic_signature
    
    print(f"[PREFLIGHT] running Semantic Validation (Stage-0.5) on {directive_path}...")
    try:
        validate_semantic_signature(str(directive_full_path))
    except Exception as e:
        if "PROVISION_REQUIRED" in str(e):
            return ("ADMISSION_GATE", str(e), None)
        return ("BLOCK_EXECUTION", f"Semantic Validation Failed: {e}", None)

    # --- Canonical Hash Alignment (Stage-1 Consistency) ---
    parsed_config = parse_directive(directive_full_path)

    resolved_config = dict(parsed_config)
    resolved_config.update({
        "BROKER": resolved_scope["broker"],
        "TIMEFRAME": resolved_scope["timeframe"],
        "START_DATE": resolved_scope["start_date"],
        "END_DATE": resolved_scope["end_date"]
    })

    canonical_hash = get_canonical_hash(resolved_config)
    
    # --- ALL CHECKS PASSED ---
    explanation = (
        f"Preflight passed. Engine={engine_name}:{engine_version}, "
        f"Broker={resolved_scope['broker']}, "
        f"Symbols={len(resolved_scope['symbols'])}, "
        f"CanonicalHash={canonical_hash}, "
        f"Timeframe={resolved_scope['timeframe']}"
    )
    
    return ("ALLOW_EXECUTION", explanation, resolved_scope)
