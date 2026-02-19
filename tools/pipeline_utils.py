"""
pipeline_utils.py — Shared Logic for Trade_Scan Governance
Purpose: Centralize Run ID generation, Canonical Hashing, and State Management.
Authority: SOP_TESTING, SOP_AGENT_ENGINE_GOVERNANCE
"""

import os
import sys
import json
import hashlib
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
import importlib.util

# ==============================================================================
# CONFIGURATION
# ==============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"

# ==============================================================================
# CANONICAL HASHING & RUN ID
# ==============================================================================

def parse_directive(file_path: Path) -> dict:
    """
    Parse directive text into a structured dictionary for canonical hashing.
    Supports 'Key: Value' and Lists (- item).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    parsed = {}
    current_key = None
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
            
        # List Item (Explicit)
        if line.startswith("-") and current_key:
            val = line[1:].strip()
            if not isinstance(parsed[current_key], list):
                parsed[current_key] = []
            parsed[current_key].append(val)
            continue
            
        # Key-Value
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            if not val:
                # Key with empty value, possibly start of list
                parsed[key] = []
                current_key = key
            else:
                parsed[key] = val
                current_key = key
        else:
            # Implicit List Item
            if current_key and isinstance(parsed.get(current_key), list):
                parsed[current_key].append(line)
            
    return parsed

def get_canonical_hash(parsed_data: dict) -> str:
    """Generate SHA256 hash of canonical JSON representation."""
    canonical_str = json.dumps(parsed_data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical_str.encode()).hexdigest()[:8]

def get_engine_version(engine_path=None):
    """
    Dynamically import engine module and read __version__.
    Default path: engine_dev/universal_research_engine/1.2.0/main.py
    """
    if not engine_path:
        engine_path = PROJECT_ROOT / "engine_dev/universal_research_engine/1.2.0/main.py"
        
    if not engine_path.exists():
        raise RuntimeError(f"Engine main.py not found at {engine_path}")

    spec = importlib.util.spec_from_file_location("universal_research_engine", engine_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load engine spec")
        
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "__version__"):
        raise RuntimeError("Engine module missing __version__ attribute")

    return module.__version__

def generate_run_id(directive_path: Path, symbol: str) -> tuple[str, str]:
    """
    Generate Deterministic Run ID based on Governance Rules.
    Returns: (run_id, content_hash)
    """
    parsed_config = parse_directive(directive_path)
    
    # Resolve Defaults if missing in Directive
    broker = parsed_config.get("Broker", "OctaFx")
    timeframe = parsed_config.get("Timeframe", "1d")
    
    # Clean Config for Hash
    # (Matches run_stage1.py logic logic for consistency)
    resolved_config = dict(parsed_config)
    resolved_config.update({
        "BROKER": broker,
        "TIMEFRAME": timeframe,
        "START_DATE": parsed_config.get("Start Date", "2015-01-01"),
        "END_DATE": parsed_config.get("End Date", "2026-01-31")
    })
    
    content_hash = get_canonical_hash(resolved_config)
    engine_ver = get_engine_version()
    
    # Lineage String
    lineage_str = f"{content_hash}_{symbol}_{timeframe}_{broker}_{engine_ver}"
    run_id = hashlib.sha256(lineage_str.encode()).hexdigest()[:12]
    
    return run_id, content_hash


# ==============================================================================
# STATE MANAGEMENT (SINGLE WRITER, ATOMIC)
# ==============================================================================

class PipelineStateManager:
    """
    Manages the run_state.json file.
    Only the Orchestrator should use the write methods (initialize, transition).
    Stage scripts should use verify_state().
    """
    
    ALLOWED_TRANSITIONS = {
        "IDLE": ["PREFLIGHT_COMPLETE", "FAILED"],
        "PREFLIGHT_COMPLETE": ["PREFLIGHT_COMPLETE_SEMANTICALLY_VALID", "FAILED"],
        "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID": ["STAGE_1_COMPLETE", "FAILED"],
        "STAGE_1_COMPLETE": ["STAGE_2_COMPLETE", "FAILED"],
        "STAGE_2_COMPLETE": ["STAGE_3_COMPLETE", "FAILED"],
        "STAGE_3_COMPLETE": ["STAGE_3A_COMPLETE", "FAILED"],
        "STAGE_3A_COMPLETE": ["COMPLETE", "FAILED"],
        "COMPLETE": [],
        "FAILED": []
    }

    def __init__(self, run_id: str, directive_id: str = None):
        self.run_id = run_id
        self.directive_id = directive_id
        self.run_dir = RUNS_DIR / run_id
        self.state_file = self.run_dir / "run_state.json"
        self.audit_log = self.run_dir / "audit.log"
        
    def _write_atomic(self, data: dict):
        """Atomic Write: Create temp, flush, rename."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        temp_file = self.state_file.with_suffix(".tmp")
        
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
            
        shutil.move(str(temp_file), str(self.state_file))

    def initialize(self):
        """Creates the run directory and initial state file with Audit Log."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. State File
        initial_data = {
            "run_id": self.run_id,
            "directive_id": self.directive_id,
            "current_state": "IDLE",
            "history": [],
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        # Atomic Write (New Runs Only)
        if not self.state_file.exists():
            self._write_atomic(initial_data) # Use existing _write_atomic
        else:
             # Reset to IDLE if re-running (Governance allowed for same run_id/content)
             # This implies updating an existing state file, which _write_atomic does if given the full data.
             # To reset to IDLE, we need to load existing data and update it.
             try:
                 with open(self.state_file, 'r', encoding='utf-8') as f:
                     existing_data = json.load(f)
                 existing_data["current_state"] = "IDLE"
                 existing_data["last_updated"] = datetime.now(timezone.utc).isoformat()
                 existing_data["history"].append({
                     "from": existing_data.get("current_state", "UNKNOWN"),
                     "to": "IDLE",
                     "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                 })
                 self._write_atomic(existing_data)
             except Exception as e:
                 print(f"[WARNING] Could not reset existing state file for {self.run_id}: {e}. Initializing as new.")
                 self._write_atomic(initial_data)


        # 2. Audit Log (Phase 9)
        if not self.audit_log.exists():
            self._append_audit_log("RUN_INITIALIZED", {"initial_state": "IDLE"})

    def _append_audit_log(self, event_type: str, details: dict):
        """Phase 9: Append-Only Immutable Audit Log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "run_id": self.run_id,
            **details
        }
        # Ensure run directory exists for audit log
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # strict append mode
        with open(self.audit_log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def transition_to(self, new_state: str):
        """
        Updates the state machine to new_state if the transition is valid.
        Records history and updates timestamp.
        """
        # Load current
        if not self.state_file.exists():
             raise FileNotFoundError(f"Run state not found: {self.run_id}")
             
        with open(self.state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        old_state = data["current_state"]
        
        # STRICT ENFORCEMENT
        allowed = self.ALLOWED_TRANSITIONS.get(old_state, [])
        if new_state not in allowed:
            # Log failure attempt?
            self._append_audit_log("ILLEGAL_TRANSITION_ATTEMPT", {
                "from": old_state,
                "to": new_state, 
                "allowed": allowed
            })
            raise RuntimeError(f"[FATAL] Illegal State Transition: {old_state} -> {new_state}. Allowed: {allowed}")
            
        # Update
        data["history"].append({
            "from": old_state,
            "to": new_state,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        data["current_state"] = new_state
        data["last_transition"] = datetime.utcnow().isoformat() + "Z"
        
        self._write_atomic(data)
        
        # Phase 9: Audit Log
        self._append_audit_log("STATE_TRANSITION", {
            "from": old_state,
            "to": new_state
        })
        
        print(f"[STATE] Transition {self.run_id}: {old_state} -> {new_state}")

    def verify_state(self, expected_state: str):
        """
        Verify current state matches expected_state.
        Abort/Raise if mismatch or missing.
        """
        if not self.state_file.exists():
            print(f"[FATAL] State file missing: {self.state_file}")
            sys.exit(1)
            
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[FATAL] Corrupt state file: {e}")
            sys.exit(1)
            
        current = data.get("current_state")
        
        # Identity Check
        if data.get("run_id") != self.run_id:
             print(f"[FATAL] Run Identity Mismatch. File: {data.get('run_id')} vs Arg: {self.run_id}")
             sys.exit(1)
             
        if current != expected_state:
            print(f"[FATAL] State Mismatch. Expected: {expected_state}, Found: {current}")
            sys.exit(1)
            
        # print(f"[VERIFIED] State is {current}")

    def get_state_data(self) -> dict:
        """Reads and returns the full state data."""
        if not self.state_file.exists():
            return {"current_state": "IDLE"}
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
             return {"current_state": "IDLE"}

class DirectiveStateManager:
    """
    Manages the high-level lifecycle of a directive execution batch.
    Persists state to runs/<DIRECTIVE_ID>/directive_state.json.
    """
    
    ALLOWED_TRANSITIONS = {
        "INITIALIZED": ["PREFLIGHT_COMPLETE", "FAILED"],
        "PREFLIGHT_COMPLETE": ["PREFLIGHT_COMPLETE_SEMANTICALLY_VALID", "FAILED"],
        "PREFLIGHT_COMPLETE_SEMANTICALLY_VALID": ["SYMBOL_RUNS_COMPLETE", "FAILED"],
        "SYMBOL_RUNS_COMPLETE": ["PORTFOLIO_COMPLETE", "FAILED"],
        "PORTFOLIO_COMPLETE": ["FAILED"], # In case of post-completion failure/invalidation?
        "FAILED": ["INITIALIZED"] # Allow retry/reset with archival
    }

    def __init__(self, directive_id: str):
        self.directive_id = directive_id
        self.directive_dir = RUNS_DIR / directive_id
        self.state_file = self.directive_dir / "directive_state.json"
        self.audit_log = self.directive_dir / "directive_audit.log"

    def _write_atomic(self, data: dict):
        """Atomic Write with fsync for durability."""
        self.directive_dir.mkdir(parents=True, exist_ok=True)
        temp_file = self.state_file.with_suffix(".tmp")
        
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
            
        shutil.move(str(temp_file), str(self.state_file))

    def _archive_current_state(self):
        """Archives current state and log before reset."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        
        # Archive State
        if self.state_file.exists():
            archive_state = self.directive_dir / f"directive_state.json.bak.{timestamp}"
            shutil.move(str(self.state_file), str(archive_state))
            print(f"[ARCHIVE] State moved to {archive_state.name}")

        # Archive Log
        if self.audit_log.exists():
            archive_log = self.directive_dir / f"directive_audit.log.bak.{timestamp}"
            shutil.move(str(self.audit_log), str(archive_log))
            print(f"[ARCHIVE] Log moved to {archive_log.name}")

    def initialize(self):
        """Creates directory and initializes state to INITIALIZED."""
        self.directive_dir.mkdir(parents=True, exist_ok=True)
        
        initial_data = {
            "directive_id": self.directive_id,
            "current_state": "INITIALIZED",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "history": []
        }
        
        # Init State File
        if not self.state_file.exists():
            self._write_atomic(initial_data)
            self._append_audit_log("DIRECTIVE_INITIALIZED", {})
        else:
            # Check if we should reset? pipeline triggers initialize() at start.
            # If it exists, we might be resuming. 
            pass

    def get_state(self) -> str:
        if not self.state_file.exists():
            return "IDLE"
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f).get("current_state", "IDLE")
        except:
            return "IDLE"

    def transition_to(self, new_state: str):
        """Transitions directive state with strict validation and logging."""
        
        # Special Handling: Reset from FAILED -> INITIALIZED
        if new_state == "INITIALIZED":
            current_state = self.get_state()
            if current_state == "FAILED":
                print(f"[RESET] Hard Reset triggered for {self.directive_id}")
                self._archive_current_state()
                self.initialize() # Re-create fresh
                return
            elif current_state == "IDLE":
                self.initialize()
                return

        if not self.state_file.exists():
            raise FileNotFoundError(f"Directive state not found: {self.directive_id}")

        with open(self.state_file, 'r') as f:
            data = json.load(f)
        
        old_state = data.get("current_state", "IDLE")
        
        # Validate
        allowed = self.ALLOWED_TRANSITIONS.get(old_state, [])
        if new_state not in allowed:
            self._append_audit_log("ILLEGAL_TRANSITION_ATTEMPT", {
                "from": old_state, "to": new_state
            })
            raise RuntimeError(f"Illegal Directive Transition: {old_state} -> {new_state}")
            
        # Update
        data["current_state"] = new_state
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["history"].append({
            "from": old_state,
            "to": new_state,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Atomic Write
        self._write_atomic(data)
        
        # Log
        self._append_audit_log("STATE_TRANSITION", {
            "from": old_state, "to": new_state
        })
        print(f"[DIRECTIVE] Transition {self.directive_id}: {old_state} -> {new_state}")

    def _append_audit_log(self, event: str, details: dict):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "directive_id": self.directive_id,
            **details
        }
        with open(self.audit_log, 'a') as f:
            f.write(json.dumps(entry) + "\n")
