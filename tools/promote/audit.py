"""Promote audit log writer (TradeScan_State/logs/promote_audit.jsonl)."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.state_paths import STATE_ROOT


def _write_audit_log(strategy_id: str, profile: str, outcome: str,
                     dry_run: bool = False, vault_id: str = "",
                     run_id: str = "", reason: str = "",
                     quality_gate: dict | None = None) -> None:
    """Append a promote attempt record to TradeScan_State/logs/promote_audit.jsonl."""
    log_dir = STATE_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "promote_audit.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_id": strategy_id,
        "profile": profile,
        "outcome": outcome,
        "dry_run": dry_run,
        "vault_id": vault_id,
        "run_id": run_id,
        "reason": reason,
    }
    if quality_gate:
        entry["quality_gate_metrics"] = quality_gate.get("metrics", {})
        entry["quality_gate_hard_fails"] = quality_gate.get("hard_fails", [])
        entry["quality_gate_warns"] = quality_gate.get("warns", [])

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"  [WARN] Audit log write failed: {e}")
