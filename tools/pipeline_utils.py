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

import yaml
from yaml.loader import SafeLoader
from yaml.resolver import BaseResolver

# ==============================================================================
# CONFIGURATION
# ==============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"

# ==============================================================================
# CANONICAL HASHING & RUN ID
# ==============================================================================



# ---------------------------------------------------------------------------
# Strict Duplicate-Key YAML Loader
# ---------------------------------------------------------------------------

class NoDuplicateSafeLoader(SafeLoader):
    """SafeLoader that raises ValueError on duplicate mapping keys."""
    pass


def _construct_mapping_no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(
                f"DUPLICATE DIRECTIVE KEY DETECTED: '{key}'"
            )
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


NoDuplicateSafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


def parse_directive(file_path: Path) -> dict:
    """
    Load a directive using YAML-safe parsing with strict duplicate-key detection.

    Contract:
    - Fails fast on invalid YAML, duplicate keys, or non-dict root.
    - Preserves full nested YAML structure.
    - Mirrors test: sub-keys into root for backward-compatible access.
      Raises ValueError on collision (never silently overwrites a root key).

    Returns:
        dict: Parsed directive config with test: keys hoisted to root level.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = yaml.load(f, Loader=NoDuplicateSafeLoader)
        except ValueError:
            raise  # Re-raise duplicate key errors verbatim
        except yaml.YAMLError as e:
            raise ValueError(f"INVALID DIRECTIVE STRUCTURE: {e}")

    if not isinstance(data, dict):
        raise ValueError(
            "INVALID DIRECTIVE STRUCTURE: root element must be a YAML mapping"
        )

    # YAML auto-parses bare date literals (e.g. 2024-01-01) as datetime.date
    # objects instead of strings. This breaks json.dumps() in get_canonical_hash()
    # and would cause run ID drift. Convert recursively to ISO string.
    import datetime as _dt

    def _stringify_dates(obj):
        if isinstance(obj, (_dt.date, _dt.datetime)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _stringify_dates(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_stringify_dates(i) for i in obj]
        return obj

    data = _stringify_dates(data)

    # Mirror test: sub-keys into root for backward-compatible downstream access.
    # Collision detection: raises if a root key would be silently overwritten.
    test_block = data.get("test", {})
    if isinstance(test_block, dict):
        for k, v in test_block.items():
            if k in data:
                raise ValueError(
                    f"KEY COLLISION during test: merge: "
                    f"'{k}' already exists at root level"
                )
            data[k] = v

    return data

def get_canonical_hash(parsed_data: dict) -> str:
    """Generate SHA256 hash of canonical JSON representation."""
    canonical_str = json.dumps(parsed_data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical_str.encode()).hexdigest()[:8]

def get_engine_version(engine_path=None):
    """
    Dynamically import engine module and read __version__.
    Default path: engine_dev/universal_research_engine/1.3.0/main.py
    """
    if not engine_path:
        engine_path = PROJECT_ROOT / "engine_dev/universal_research_engine/1.3.0/main.py"
        
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
    # Public parse for downstream field access (correct YAML structure).
    parsed_config = parse_directive(directive_path)

    # Resolve broker/timeframe for the lineage string.
    broker = parsed_config.get("Broker", parsed_config.get("broker", "OctaFx"))
    timeframe = parsed_config.get("Timeframe", parsed_config.get("timeframe", "1d"))

    # -------------------------------------------------------------------------
    # RUN ID HASH — computed from the LEGACY flat-parser output, frozen.
    #
    # ⚠️  DO NOT CHANGE THIS LOGIC. Changing it invalidates ALL existing run IDs,
    #     requiring a full re-run of every directive. The legacy flat parser is
    #     kept here as an internal private function purely for hash stability.
    #     It is NOT used for directive config access anywhere else.
    # -------------------------------------------------------------------------
    def _legacy_flat_parse(file_path: Path) -> dict:
        """Verbatim copy of the original flat key:value parser — hash use only."""
        with open(file_path, 'r', encoding='utf-8') as _f:
            lines = _f.readlines()
        _parsed = {}
        _current_key = None
        for _line in lines:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            if _line.startswith("-") and _current_key:
                _val = _line[1:].strip()
                if not isinstance(_parsed[_current_key], list):
                    _parsed[_current_key] = []
                _parsed[_current_key].append(_val)
                continue
            if ":" in _line:
                _parts = _line.split(":", 1)
                _key = _parts[0].strip()
                _val = _parts[1].strip()
                if not _val:
                    _parsed[_key] = []
                    _current_key = _key
                else:
                    _parsed[_key] = _val
                    _current_key = _key
            else:
                if _current_key and isinstance(_parsed.get(_current_key), list):
                    _parsed[_current_key].append(_line)
        return _parsed

    _legacy_config = _legacy_flat_parse(directive_path)
    _legacy_config.update({
        "BROKER": broker,
        "TIMEFRAME": timeframe,
        "START_DATE": _legacy_config.get("Start Date", _legacy_config.get("start_date", "2015-01-01")),
        "END_DATE": _legacy_config.get("End Date", _legacy_config.get("end_date", "2026-01-31")),
    })
    content_hash = get_canonical_hash(_legacy_config)
    # -------------------------------------------------------------------------

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
                 # Capture old_state BEFORE overwriting current_state so history
                 # records the true prior state (e.g. STAGE_3_COMPLETE → IDLE)
                 # not the post-mutation value (IDLE → IDLE).
                 old_state = existing_data.get("current_state", "UNKNOWN")
                 existing_data["history"].append({
                     "from": old_state,
                     "to": "IDLE",
                     "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                 })
                 existing_data["current_state"] = "IDLE"
                 existing_data["last_updated"] = datetime.now(timezone.utc).isoformat()
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
        Raises RuntimeError on mismatch or missing state file.
        Caller (run_stage1.py) handles failures via its existing try/except.
        """
        if not self.state_file.exists():
            raise RuntimeError(
                f"[FATAL] State file missing: {self.state_file}"
            )

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"[FATAL] Corrupt state file: {e}")

        current = data.get("current_state")

        # Identity Check
        if data.get("run_id") != self.run_id:
            raise RuntimeError(
                f"[FATAL] Run Identity Mismatch. File: {data.get('run_id')} vs Arg: {self.run_id}"
            )

        if current != expected_state:
            # Allow forward states for re-running reports
            if (expected_state == "STAGE_2_COMPLETE" and current in ["STAGE_3_COMPLETE", "STAGE_3A_COMPLETE", "COMPLETE"]) or \
               (expected_state == "STAGE_1_COMPLETE" and current in ["STAGE_2_COMPLETE", "STAGE_3_COMPLETE", "STAGE_3A_COMPLETE", "COMPLETE"]):
                pass
            else:
                raise RuntimeError(
                    f"[FATAL] State Mismatch. Expected: {expected_state}, Found: {current}"
                )

        # print(f"[VERIFIED] State is {current}")

    def get_state_data(self) -> dict:
        """Reads and returns the full state data."""
        if not self.state_file.exists():
            return {"current_state": "IDLE"}
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
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
        except Exception:
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
