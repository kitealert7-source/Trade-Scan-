"""
Trade_Scan Preflight Agent
Status: IMPLEMENTATION
Role: Decision-only governance gate + scope resolver
Authority: SOP_TESTING, SOP_OUTPUT, SOP_AGENT_ENGINE_GOVERNANCE (Supreme)
"""
import os
import re
from pathlib import Path
from typing import Optional
from tools.run_stage1 import parse_directive, get_canonical_hash

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
    
    if skip_vault_check:
        cmd = f"python {integrity_check} --mode workspace"
    else:
        cmd = f"python {integrity_check} --mode strict"

    exit_code = os.system(cmd)
    if exit_code != 0:
        return (
            "BLOCK_EXECUTION",
            "Engine integrity check FAILED. Execution blocked.",
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
    
    # --- CHECK 4: Extract Resolved Scope (Human-Tolerant Parsing) ---
    resolved_scope = {
        "broker": None,
        "symbols": [],
        "timeframe": None,
        "start_date": None,
        "end_date": None
    }
    
    # Helper: Extract value after field name with flexible separators (:, -, =)
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
    
    # Helper: Strip bullet prefixes (*, -, •)
    def strip_bullet(line: str) -> str:
        """Remove leading bullet characters and whitespace."""
        return re.sub(r'^[\s*\-•]+', '', line).strip()

    def normalize_broker(name: str) -> str:
        """Normalize broker name to match directory convention."""
        clean = name.upper().replace(" ", "")
        if clean == "OCTAFX":
            return "OctaFx"
        if clean == "DELTAEXCHANGE":
            return "DeltaExchange"
        return name
    
    lines = directive_content.split('\n')
    in_symbols_block = False
    collected_symbols = set()
    
    for line in lines:
        line_stripped = line.strip()
        line_upper = line_stripped.upper()
        
        # Skip empty lines and comments
        if not line_stripped or line_stripped.startswith('#'):
            continue
        
        # --- Broker extraction ---
        broker_val = extract_field_value(line_stripped, r'broker(?:\s+feed)?')
        if broker_val and not resolved_scope["broker"]:
            resolved_scope["broker"] = normalize_broker(broker_val)
            continue
        
        # --- Timeframe extraction ---
        timeframe_val = extract_field_value(line_stripped, r'time\s*frame')
        if timeframe_val and not resolved_scope["timeframe"]:
            resolved_scope["timeframe"] = timeframe_val
            continue
        
        # --- Start Date extraction ---
        start_date_val = extract_field_value(line_stripped, r'start\s*date')
        if start_date_val and not resolved_scope["start_date"]:
            resolved_scope["start_date"] = start_date_val
            continue
        
        # --- End Date extraction ---
        end_date_val = extract_field_value(line_stripped, r'end\s*date')
        if end_date_val and not resolved_scope["end_date"]:
            resolved_scope["end_date"] = end_date_val
            continue
        
        # --- Symbols extraction ---
        # Check for "Symbol:", "Symbols:", or "Asset:" header
        symbol_header_match = re.match(r'^\s*(?:symbol|asset)s?\s*[:=\-]\s*(.*)$', line_stripped, re.IGNORECASE)
        if symbol_header_match:
            inline_value = symbol_header_match.group(1).strip()
            if inline_value:
                # Inline symbol(s) after header
                cleaned = strip_bullet(inline_value).upper()
                if cleaned and len(cleaned) <= 10:
                    collected_symbols.add(cleaned)
            else:
                # Start of symbols block
                in_symbols_block = True
            continue
        
        # Inside symbols block: collect bulleted items or standalone tickers
        if in_symbols_block:
            # Check if line starts with bullet or is indented
            if re.match(r'^[\s*\-•]', line):
                cleaned = strip_bullet(line_stripped).upper()
                if cleaned and len(cleaned) <= 10:
                    collected_symbols.add(cleaned)
            # Also accept short uppercase-only lines as symbols (e.g., "SPX500" on its own line)
            elif line_stripped and len(line_stripped) <= 10 and re.match(r'^[A-Z0-9]+$', line_stripped):
                collected_symbols.add(line_stripped.upper())
            elif line_stripped and not re.match(r'^[\s*\-•]', line) and not re.match(r'^[A-Z0-9]+$', line_stripped):
                # Non-bulleted, non-ticker line ends the block
                in_symbols_block = False
    
    # De-duplicate and assign symbols
    resolved_scope["symbols"] = list(collected_symbols)
    
    # --- CHECK 5: Validate Resolved Scope ---
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
    if not date_pattern.match(resolved_scope["start_date"]):
        return ("BLOCK_EXECUTION", f"Start Date malformed: {resolved_scope['start_date']}", None)
    
    if not date_pattern.match(resolved_scope["end_date"]):
        return ("BLOCK_EXECUTION", f"End Date must be explicit YYYY-MM-DD, got: {resolved_scope['end_date']}", None)
    
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
