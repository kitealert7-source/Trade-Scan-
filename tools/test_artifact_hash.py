import json
import hashlib
from pathlib import Path

PROJECT_ROOT = Path("C:/Users/faraw/Documents/Trade_Scan")
RUNS_DIR = PROJECT_ROOT / "runs"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "run_registry.json"

def get_file_bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    with open(path, "rb") as f:
        return f.read()

def compute_artifact_hash(data_dir: Path) -> str:
    """Deterministic hash of the trade-level outputs"""
    files = ["results_tradelevel.csv", "results_standard.csv", "equity_curve.csv"]
    hash_contents = [get_file_bytes(data_dir / f) for f in files]
    return hashlib.sha256(b"".join(hash_contents)).hexdigest()

def main():
    if not REGISTRY_PATH.exists():
        print("Registry not found.")
        return

    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)

    test_count = 0
    match_count = 0

    for run_id, data in registry.items():
        if data.get("status") == "complete" and data.get("artifact_hash"):
            data_dir = RUNS_DIR / run_id / "data"
            if data_dir.exists():
                recomputed = compute_artifact_hash(data_dir)
                original = data["artifact_hash"]
                test_count += 1
                if recomputed == original:
                    match_count += 1
                    print(f"[PASS] {run_id}: Hashes match ({recomputed[:16]}...)")
                else:
                    print(f"[FAIL] {run_id}: Hash mismatch!\n  Expected: {original}\n  Got:      {recomputed}")
                    
    print(f"\n{match_count}/{test_count} artifact hashes validated successfully.")

if __name__ == "__main__":
    main()
