import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- Rotation policy ---
_MAX_BYTES    = 5 * 1024 * 1024   # 5 MB primary trigger
_BACKUP_COUNT = 4                  # keep 4 archives (~1 month)
_MAX_AGE_DAYS = 7                  # rotate weekly even if under size

LOG_DIR  = Path(r"C:\Users\faraw\Documents\Trade_Scan\outputs\logs")
LOG_FILE = LOG_DIR / "pipeline_failures.log"


def _get_logger() -> logging.Logger:
    """Return (and lazily configure) the singleton failure logger."""
    logger = logging.getLogger("pipeline_failures")
    if logger.handlers:
        return logger  # already configured

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Weekly time-based rotation: rename existing file if older than 7 days.
    if LOG_FILE.exists():
        age_days = (time.time() - LOG_FILE.stat().st_mtime) / 86400
        if age_days >= _MAX_AGE_DAYS:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d")
            rotated = LOG_FILE.with_name(f"pipeline_failures_{ts}.log")
            try:
                LOG_FILE.rename(rotated)
                print(f"[LOG-ROTATE] Weekly rotation: {rotated.name}")
            except Exception as e:
                print(f"[LOG-ROTATE] Could not rotate log: {e}")

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_pipeline_failure(
    directive_id: str,
    run_id: str | None,
    stage: str,
    error_type: str,
    message: str,
) -> None:
    """
    Appends a structured failure entry to the centralized pipeline log.
    Format: timestamp | directive_id | run_id | stage | error_type | message

    Rotation policy:
      - Size  : rotates at 5 MB  (backupCount=4, ~1 month)
      - Time  : rotates weekly   (even if under size limit)
    """
    try:
        logger    = _get_logger()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        safe_run  = run_id if run_id else "N/A"
        clean_msg = str(message).replace("\n", " ").replace("\r", " ")
        logger.info(
            f"{timestamp} | {directive_id} | {safe_run} | {stage} | {error_type} | {clean_msg}"
        )
    except Exception:
        # Logging failure must never crash the pipeline
        pass
