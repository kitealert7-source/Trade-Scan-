import os
from pathlib import Path
from datetime import datetime, timezone

def log_pipeline_failure(directive_id: str, run_id: str | None, stage: str, error_type: str, message: str):
    """
    Appends a structured failure entry to the centralized pipeline logs.
    Format: timestamp | directive_id | run_id | stage | error_type | message
    """
    try:
        log_dir = Path(r"C:\Users\faraw\Documents\Trade_Scan\outputs\logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / "pipeline_failures.log"
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        safe_run_id = run_id if run_id else "N/A"
        
        # Clean message to avoid newlines breaking the format
        clean_msg = str(message).replace("\n", " ").replace("\r", " ")
        
        log_entry = f"{timestamp} | {directive_id} | {safe_run_id} | {stage} | {error_type} | {clean_msg}\n"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
    except Exception:
        # Logging failure must never crash the pipeline
        pass
