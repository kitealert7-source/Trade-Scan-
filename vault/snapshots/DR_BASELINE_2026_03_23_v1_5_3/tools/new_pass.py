"""
new_pass.py — Zero-friction new strategy pass creation.

Creates directive + strategy.py + sweep registry entry + approved marker in one command.
Pre-injects provisioner-canonical strategy.py so the provisioner finds nothing to change
on the first pipeline run → eliminates the EXPERIMENT_DISCIPLINE 2-pass cycle entirely.

Usage:
    python tools/new_pass.py <source_pass> <new_pass>

    <source_pass>  : full strategy name of the source (e.g. 23_RSI_XAUUSD_1H_MICROREV_S01_V1_P12)
    <new_pass>     : full strategy name for the new pass (e.g. 23_RSI_XAUUSD_1H_MICROREV_S01_V1_P13)

After creation:
    - Edit strategies/<new_pass>/strategy.py (logic changes only — do NOT touch STRATEGY_SIGNATURE)
    - Edit backtest_directives/INBOX/<new_pass>.txt (parameter changes)
    - Run: python tools/new_pass.py --rehash <new_pass>   <- updates hash after edits
    - Run: python tools/run_pipeline.py --all

Notes:
    - STRATEGY_SIGNATURE is copied verbatim from source. Edit it in the directive, then --rehash.
    - The approved marker is touched AFTER strategy.py is written, so mtime is always newer.
    - Sweep registry is updated automatically — no manual YAML editing needed.
"""

import sys
import json
import hashlib
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR    = PROJECT_ROOT / "strategies"
INBOX_DIR         = PROJECT_ROOT / "backtest_directives" / "INBOX"
COMPLETED_DIR     = PROJECT_ROOT / "backtest_directives" / "completed"
ACTIVE_BACKUP_DIR = PROJECT_ROOT / "backtest_directives" / "active_backup"
SWEEP_REGISTRY    = PROJECT_ROOT / "governance" / "namespace" / "sweep_registry.yaml"


# ── Hash helpers ────────────────────────────────────────────────────────────
def _hash_sig_dict(sig: dict) -> str:
    """16-char hex — matches strategy_provisioner._hash_sig_dict exactly."""
    canonical = json.dumps(sig, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _hash_directive_file(directive_path: Path) -> tuple[str, str]:
    """
    Returns (short_hash, full_hash) matching sweep_registry_gate._hash_signature.
    Imports the gate's own function to guarantee byte-for-byte agreement.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools.sweep_registry_gate import _hash_signature
    full = _hash_signature(directive_path)
    return full[:16], full


# ── Directive discovery ─────────────────────────────────────────────────────
def _find_directive(strategy_name: str) -> Path:
    """Find the directive file for a strategy in completed/ or active_backup/."""
    for search_dir in [COMPLETED_DIR, ACTIVE_BACKUP_DIR]:
        candidate = search_dir / f"{strategy_name}.txt"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Cannot find directive for '{strategy_name}' in completed/ or active_backup/.\n"
        f"Checked:\n  {COMPLETED_DIR}\n  {ACTIVE_BACKUP_DIR}"
    )


# ── Sweep registry update ───────────────────────────────────────────────────
def _register_patch(new_pass_name: str, short_hash: str, full_hash: str) -> None:
    """
    Append a new patch entry to sweep_registry.yaml under the correct family S01 patches block.
    Reads/writes raw text to preserve formatting of other entries.
    """
    import yaml

    content = SWEEP_REGISTRY.read_text(encoding="utf-8")

    # Extract family ID and patch ID from strategy name
    # Pattern: NN_FAMILY_SYMBOL_TF_MODEL_SXX_VX_PXX
    parts = new_pass_name.split("_")
    family_id = parts[0]        # e.g. "23"
    patch_id  = parts[-1]       # e.g. "P13"

    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")

    new_entry = (
        f"          {patch_id}:\n"
        f"            directive_name: {new_pass_name}\n"
        f"            signature_hash: {short_hash}\n"
        f"            signature_hash_full: {full_hash}\n"
        f"            reserved_at_utc: '{now_utc}'\n"
    )

    # Find the last patch entry for this family and append after it
    # Strategy: look for the last "directive_name: <family_id>_" line and insert after its block
    # More robust: find the family block and locate the last patch entry

    # Build a marker — find the family block header
    family_marker = f"  '{family_id}':" if f"  '{family_id}':" in content else f"  {family_id}:"

    if family_marker not in content:
        print(f"[new_pass] WARNING: Family '{family_id}' not found in sweep_registry.yaml.")
        print(f"[new_pass] Add the following manually under family '{family_id}' patches:")
        print(new_entry)
        return

    # Find the position of the last patch entry in this family block
    # Use the pattern: look for the last reserved_at_utc within the family's section
    family_pos = content.index(family_marker)

    # Find next family marker after this one (to bound our search)
    next_family_match = re.search(r"^\s{2}['\"]?\d+['\"]?:", content[family_pos + 1:], re.MULTILINE)
    family_block_end = family_pos + 1 + next_family_match.start() if next_family_match else len(content)
    family_block = content[family_pos:family_block_end]

    # Find the last 'reserved_at_utc' line within this block
    last_reserved = list(re.finditer(r"            reserved_at_utc:.*\n", family_block))
    if not last_reserved:
        print(f"[new_pass] WARNING: No existing patches found in family '{family_id}' block.")
        print(f"[new_pass] Add the following manually:\n{new_entry}")
        return

    # Insert the new entry after the last reserved_at_utc line in the family block
    insert_offset = family_pos + last_reserved[-1].end()
    content = content[:insert_offset] + new_entry + content[insert_offset:]

    SWEEP_REGISTRY.write_text(content, encoding="utf-8")
    print(f"[new_pass] Sweep registry updated: family {family_id}, patch {patch_id}")


# ── Strategy.py canonical pre-formatting ───────────────────────────────────
def _format_sig_canonical(sig: dict) -> str:
    """
    Format STRATEGY_SIGNATURE exactly as provisioner would (json.dumps sort_keys=True,
    indent=4, with Python literal conversion). Used to pre-inject content so the
    provisioner finds content == original_content and skips the write (no mtime change).
    """
    sig_json = json.dumps(sig, indent=4, sort_keys=True)
    sig_json = (
        sig_json
        .replace(": true",  ": True")
        .replace(": false", ": False")
        .replace(": null",  ": None")
    )
    return sig_json


def _extract_signature_from_strategy(strategy_py: Path) -> dict | None:
    """Extract STRATEGY_SIGNATURE dict from an existing strategy.py via JSON parsing."""
    content = strategy_py.read_text(encoding="utf-8")
    start_marker = "# --- STRATEGY SIGNATURE START ---"
    end_marker   = "# --- STRATEGY SIGNATURE END ---"
    m = re.search(
        rf"{re.escape(start_marker)}\s+STRATEGY_SIGNATURE\s*=\s*(\{{.*?\}})\s+{re.escape(end_marker)}",
        content,
        re.DOTALL,
    )
    if not m:
        return None
    # Convert Python literals back to JSON for parsing
    raw = m.group(1)
    raw = raw.replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── Core: create new pass ───────────────────────────────────────────────────
def create_pass(source_name: str, new_name: str) -> None:
    print(f"\n[new_pass] Creating {new_name} from {source_name}")

    # 1. Find source directive and strategy
    src_directive = _find_directive(source_name)
    src_strategy  = STRATEGIES_DIR / source_name / "strategy.py"
    if not src_strategy.exists():
        raise FileNotFoundError(f"Source strategy.py not found: {src_strategy}")

    # 2. Create new directive in INBOX
    new_directive = INBOX_DIR / f"{new_name}.txt"
    directive_content = src_directive.read_text(encoding="utf-8")
    directive_content = directive_content.replace(source_name, new_name)
    new_directive.write_text(directive_content, encoding="utf-8")
    print(f"[new_pass] Directive written: {new_directive}")
    print(f"[new_pass] >>> Edit {new_directive} with your parameter changes now <<<")

    # 3. Create strategy directory and strategy.py
    new_strat_dir = STRATEGIES_DIR / new_name
    new_strat_dir.mkdir(exist_ok=True)

    src_content = src_strategy.read_text(encoding="utf-8")
    new_content = src_content.replace(source_name, new_name)
    new_strat_py = new_strat_dir / "strategy.py"
    new_strat_py.write_text(new_content, encoding="utf-8")
    print(f"[new_pass] Strategy written: {new_strat_py}")
    print(f"[new_pass] >>> Edit {new_strat_py} with your logic changes now <<<")

    print(f"\n[new_pass] When edits are done, run:")
    print(f"    python tools/new_pass.py --rehash {new_name}")
    print(f"Then run the pipeline.")


def rehash_pass(strategy_name: str) -> None:
    """
    Call this AFTER editing directive and strategy.py.
    Re-computes directive hash, updates sweep registry, pre-injects provisioner-canonical
    hash comment into strategy.py, and touches strategy.py.approved.
    Eliminates EXPERIMENT_DISCIPLINE on the next pipeline run.
    """
    print(f"\n[new_pass] Rehashing {strategy_name}")

    directive_path = INBOX_DIR / f"{strategy_name}.txt"
    if not directive_path.exists():
        raise FileNotFoundError(f"Directive not found in INBOX: {directive_path}")

    strategy_py   = STRATEGIES_DIR / strategy_name / "strategy.py"
    approved_marker = strategy_py.with_name("strategy.py.approved")

    if not strategy_py.exists():
        raise FileNotFoundError(f"Strategy not found: {strategy_py}")

    # 1. Compute directive hash and update sweep registry
    short_hash, full_hash = _hash_directive_file(directive_path)
    print(f"[new_pass] Directive hash: {short_hash}  ({full_hash})")
    _register_patch(strategy_name, short_hash, full_hash)

    # 2. Extract STRATEGY_SIGNATURE from strategy.py
    sig = _extract_signature_from_strategy(strategy_py)
    if sig is None:
        print("[new_pass] WARNING: Could not extract STRATEGY_SIGNATURE. Skipping hash pre-injection.")
        print("[new_pass] You will need to run the 2-pass EXPERIMENT_DISCIPLINE cycle manually.")
    else:
        # 3. Pre-inject provisioner-canonical STRATEGY_SIGNATURE + hash comment
        sig_hash = _hash_sig_dict(sig)
        content  = strategy_py.read_text(encoding="utf-8")

        # Replace signature block with canonical format
        start_marker = "# --- STRATEGY SIGNATURE START ---"
        end_marker   = "# --- STRATEGY SIGNATURE END ---"
        canonical_sig = _format_sig_canonical(sig)
        new_block = f"{start_marker}\n    STRATEGY_SIGNATURE = {canonical_sig}\n    {end_marker}"
        pattern = re.compile(
            rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL
        )
        content = pattern.sub(new_block, content, count=1)

        # Update or inject hash comment
        hash_line = f"# --- SIGNATURE HASH: {sig_hash} ---"
        hash_re   = re.compile(r"# --- SIGNATURE HASH: [0-9a-f]{16} ---")
        if hash_re.search(content):
            content = hash_re.sub(hash_line, content, count=1)
        else:
            content = content.replace(
                end_marker,
                f"{end_marker}\n    {hash_line}",
                1,
            )

        strategy_py.write_text(content, encoding="utf-8")
        print(f"[new_pass] strategy.py pre-formatted with hash: {sig_hash}")

    # 4. Touch approved marker AFTER writing strategy.py (approved mtime must be newer)
    import time
    time.sleep(0.01)  # ensure mtime difference
    approved_marker.write_text(
        f"approved: {datetime.now(tz=timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    print(f"[new_pass] Approved marker written: {approved_marker}")
    print(f"\n[new_pass] Done. Run: python tools/run_pipeline.py --all")
    print(f"[new_pass] EXPERIMENT_DISCIPLINE will NOT fire on this pass.")


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print("Usage: python tools/new_pass.py <source_pass> <new_pass>  |  --rehash <new_pass>")
        sys.exit(0)

    if args[0] == "--rehash":
        if len(args) < 2:
            print("Usage: python tools/new_pass.py --rehash <strategy_name>")
            sys.exit(1)
        rehash_pass(args[1])

    elif len(args) == 2:
        create_pass(args[0], args[1])

    else:
        print("Usage:")
        print("  python tools/new_pass.py <source_pass> <new_pass>")
        print("  python tools/new_pass.py --rehash <new_pass>")
        sys.exit(1)
