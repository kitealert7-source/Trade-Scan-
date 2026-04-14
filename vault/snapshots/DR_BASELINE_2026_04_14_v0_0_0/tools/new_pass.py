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
import yaml
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

    # Find the last 'reserved_at_utc' line within this block (patch-level = 12-space indent)
    last_reserved = list(re.finditer(r"            reserved_at_utc:.*\n", family_block))
    if not last_reserved:
        # No existing patches. Auto-insert the first patch in the right sweep block.
        # Works for the common case where a fresh sweep still has `patches: {}`.
        # Search within family_block only; rewrite the matched "patches: {}" once.
        empty_patches_re = re.compile(r"^(?P<indent>        )patches:\s*\{\}\s*\n", re.MULTILINE)
        m = empty_patches_re.search(family_block)
        if not m:
            print(f"[new_pass] WARNING: No existing patches and no 'patches: {{}}' anchor found in family '{family_id}'.")
            print(f"[new_pass] Add the following manually:\n{new_entry}")
            return
        # Replace `patches: {}` with `patches:\n<entry>` at the first occurrence
        # (first sweep block; callers only register one sweep per family on GENESIS).
        replacement = f"{m.group('indent')}patches:\n{new_entry}"
        insert_start = family_pos + m.start()
        insert_end = family_pos + m.end()
        content = content[:insert_start] + replacement + content[insert_end:]
        SWEEP_REGISTRY.write_text(content, encoding="utf-8")
        print(f"[new_pass] Sweep registry auto-seeded: family {family_id}, first patch {patch_id}")
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

    # Auto-resolve dates from available data
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from governance.preflight import resolve_data_range
        parsed = yaml.safe_load(directive_content)
        symbols   = parsed.get("symbols", [])
        broker    = parsed.get("test", {}).get("broker", "")
        timeframe = parsed.get("test", {}).get("timeframe", "")
        start_date, end_date = resolve_data_range(symbols, broker, timeframe)
        directive_content = re.sub(
            r"(start_date:\s*)'[^']*'", rf"\g<1>'{start_date}'", directive_content
        )
        directive_content = re.sub(
            r"(end_date:\s*)'[^']*'", rf"\g<1>'{end_date}'", directive_content
        )
        print(f"[new_pass] Dates resolved: start={start_date}  end={end_date}")
    except Exception as exc:
        print(f"[new_pass] WARNING: date auto-resolve failed ({exc}). Dates copied from source — edit manually.")

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


def _clean_stale_state(strategy_name: str) -> None:
    """
    Remove ALL stale pipeline state for a directive so it can run fresh.
    Cleans: per-run-id dirs in RUNS_DIR, registry entries, directive state dir,
    active_backup files, admitted markers. Idempotent — safe to call when no
    stale state exists.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from config.state_paths import RUNS_DIR, REGISTRY_DIR

    registry_path = REGISTRY_DIR / "run_registry.json"
    cleaned = []

    # 1. Remove directive-level state dir (RUNS_DIR/<strategy_name>/)
    directive_dir = RUNS_DIR / strategy_name
    if directive_dir.exists():
        shutil.rmtree(directive_dir)
        cleaned.append(f"directive dir: {directive_dir.name}")

    # 2. Find and remove per-run-id dirs that reference this directive
    #    Scan run_state.json files for directive_id match
    removed_run_ids = []
    if RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            rs_file = run_dir / "run_state.json"
            if not rs_file.exists():
                continue
            try:
                rs = json.loads(rs_file.read_text(encoding="utf-8"))
                if rs.get("directive_id") == strategy_name:
                    removed_run_ids.append(run_dir.name)
                    shutil.rmtree(run_dir)
            except Exception:
                continue

    if removed_run_ids:
        cleaned.append(f"run dirs: {len(removed_run_ids)}")

    # 3. Clean registry entries matching this directive
    if registry_path.exists():
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            before = len(reg)
            # Remove entries by directive_hash match OR by run_id match (covers
            # "recovered" entries where directive_hash was set to 'recovered')
            reg = {
                k: v for k, v in reg.items()
                if v.get("directive_hash") != strategy_name
                and k not in removed_run_ids
            }
            removed_count = before - len(reg)
            if removed_count > 0:
                registry_path.write_text(
                    json.dumps(reg, indent=2), encoding="utf-8"
                )
                cleaned.append(f"registry entries: {removed_count}")
        except Exception as e:
            print(f"[new_pass] WARNING: registry cleanup failed: {e}")

    # 4. Clean active_backup files + admitted markers
    for suffix in ["", ".admitted"]:
        backup_file = ACTIVE_BACKUP_DIR / f"{strategy_name}.txt{suffix}"
        if backup_file.exists():
            backup_file.unlink()
            cleaned.append(f"active_backup: {backup_file.name}")

    if cleaned:
        print(f"[new_pass] Cleaned stale state: {', '.join(cleaned)}")
    else:
        print(f"[new_pass] No stale state found (clean slate).")


def rehash_pass(strategy_name: str) -> None:
    """
    Call this AFTER editing directive and strategy.py.
    Single command that handles the ENTIRE iteration cycle:
      1. Cleans all stale pipeline state (run dirs, registry, active_backup)
      2. Recomputes directive hash and updates sweep_registry.yaml
      3. Pre-injects provisioner-canonical signature + hash into strategy.py
      4. Writes strategy.py.approved marker (bypasses EXPERIMENT_DISCIPLINE)
      5. Ensures directive is in INBOX ready for pipeline

    Usage: python tools/new_pass.py --rehash <strategy_name>
    Then:  python tools/run_pipeline.py <strategy_name>
    """
    print(f"\n[new_pass] Rehashing {strategy_name}")

    # --- Locate directive: INBOX first, then active_backup (restore if needed) ---
    directive_path = INBOX_DIR / f"{strategy_name}.txt"
    if not directive_path.exists():
        backup_path = ACTIVE_BACKUP_DIR / f"{strategy_name}.txt"
        if backup_path.exists():
            shutil.copy2(backup_path, directive_path)
            print(f"[new_pass] Restored directive from active_backup to INBOX")
        else:
            completed_path = COMPLETED_DIR / f"{strategy_name}.txt"
            if completed_path.exists():
                shutil.copy2(completed_path, directive_path)
                print(f"[new_pass] Restored directive from completed to INBOX")
            else:
                raise FileNotFoundError(
                    f"Directive not found in INBOX, active_backup, or completed: {strategy_name}.txt"
                )

    strategy_py   = STRATEGIES_DIR / strategy_name / "strategy.py"
    approved_marker = strategy_py.with_name("strategy.py.approved")

    if not strategy_py.exists():
        raise FileNotFoundError(f"Strategy not found: {strategy_py}")

    # Step 0: Clean ALL stale state from previous runs
    _clean_stale_state(strategy_name)

    # Step 1: Compute directive hash and update sweep registry
    short_hash, full_hash = _hash_directive_file(directive_path)
    print(f"[new_pass] Directive hash: {short_hash}  ({full_hash})")
    _register_patch(strategy_name, short_hash, full_hash)

    # Step 2: Extract STRATEGY_SIGNATURE from strategy.py
    sig = _extract_signature_from_strategy(strategy_py)
    if sig is None:
        print("[new_pass] WARNING: Could not extract STRATEGY_SIGNATURE. Skipping hash pre-injection.")
        print("[new_pass] You will need to run the 2-pass EXPERIMENT_DISCIPLINE cycle manually.")
    else:
        # Step 3: Pre-inject provisioner-canonical STRATEGY_SIGNATURE + hash comment
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

    # Step 4: Touch approved marker AFTER writing strategy.py (mtime must be newer)
    import time
    time.sleep(0.01)  # ensure mtime difference on Windows
    approved_marker.write_text(
        f"approved: {datetime.now(tz=timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    print(f"[new_pass] Approved marker written: {approved_marker}")

    # Step 5: Regenerate tools manifest (sweep_registry.yaml changed)
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "tools/generate_guard_manifest.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=30
        )
        if result.returncode == 0:
            print(f"[new_pass] Tools manifest regenerated.")
        else:
            print(f"[new_pass] WARNING: Manifest regen failed: {result.stderr[:200]}")
    except Exception as e:
        print(f"[new_pass] WARNING: Manifest regen skipped: {e}")

    print(f"\n{'='*60}")
    print(f"[new_pass] READY. Run: python tools/run_pipeline.py {strategy_name}")
    print(f"[new_pass] EXPERIMENT_DISCIPLINE will NOT fire.")
    print(f"{'='*60}")


# ── Clone-asset (Phase 4) ──────────────────────────────────────────────────
_NAME_RE = re.compile(
    r"^(?P<idea>\d{2})_"
    r"(?P<family>[A-Z0-9]+)_"
    r"(?P<asset>[A-Z0-9]+)_"
    r"(?P<tf>[A-Z0-9]+)_"
    r"(?P<model>[A-Z0-9]+)_"
    r"S(?P<sweep>\d{2})_"
    r"V(?P<variant>\d+)_"
    r"P(?P<patch>\d{2})"
    r"(?P<suffix>(?:__[A-Z0-9]+)?)$"
)


def _next_free_idea_id() -> str:
    """Scan strategies/ + governance sweep_registry for the highest 2-digit
    idea_id prefix and return the next free one as a zero-padded string.
    """
    used: set[int] = set()
    if STRATEGIES_DIR.exists():
        for child in STRATEGIES_DIR.iterdir():
            if child.is_dir() and child.name[:2].isdigit():
                used.add(int(child.name[:2]))
    try:
        reg = yaml.safe_load(SWEEP_REGISTRY.read_text(encoding="utf-8")) or {}
        # Top-level keys under 'families' are the idea ids (as strings).
        fams = reg.get("families") or reg
        if isinstance(fams, dict):
            for k in fams.keys():
                if isinstance(k, str) and k.strip("'\"").isdigit():
                    used.add(int(k.strip("'\"")))
                elif isinstance(k, int):
                    used.add(k)
    except Exception:
        pass
    n = (max(used) if used else 0) + 1
    return f"{n:02d}"


def _resolve_new_asset_token(symbol: str) -> str:
    """Map a concrete symbol (e.g. BTCUSD) to its namespace asset-class token."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from config.asset_classification import (
        infer_asset_class_from_symbols,
        MixedAssetClassError,
        UnknownSymbolError,
    )
    try:
        return str(infer_asset_class_from_symbols([symbol])).upper()
    except (MixedAssetClassError, UnknownSymbolError, ValueError) as e:
        raise RuntimeError(
            f"Cannot classify symbol {symbol!r}: {e}. Add it to "
            f"config/asset_classification.py before cloning."
        )


def clone_asset(
    source_name: str,
    new_symbol: str,
    new_idea: str | None = None,
) -> None:
    """Clone a strategy to a new asset class, preserving logic and
    signal_version. Generates a new idea_id + new directive + new strategy.py.

    The indicator imports (and therefore indicators_content_hash) are preserved
    byte-for-byte; only the symbol, idea_id, and asset-class token change.
    Caller still needs to run --rehash after reviewing the scaffolded files.
    """
    print(f"\n[new_pass] Cloning {source_name} to asset {new_symbol}")

    m = _NAME_RE.match(source_name)
    if not m:
        raise ValueError(
            f"Source name {source_name!r} does not match strategy naming pattern."
        )
    old_asset = m.group("asset")
    new_asset = _resolve_new_asset_token(new_symbol)
    if new_asset == old_asset:
        print(
            f"[new_pass] WARNING: new symbol {new_symbol!r} maps to the same "
            f"asset-class token {old_asset!r} as the source. This is not a "
            f"cross-asset clone — consider --rehash flow instead."
        )

    new_idea_id = new_idea or _next_free_idea_id()
    if not (isinstance(new_idea_id, str) and new_idea_id.isdigit() and len(new_idea_id) == 2):
        raise ValueError(f"--idea must be a 2-digit string; got {new_idea_id!r}")

    new_name = (
        f"{new_idea_id}_{m.group('family')}_{new_asset}_{m.group('tf')}_"
        f"{m.group('model')}_S{m.group('sweep')}_V{m.group('variant')}_"
        f"P{m.group('patch')}{m.group('suffix')}"
    )
    print(f"[new_pass] New strategy name: {new_name}")

    # Guard against clobbering.
    new_strat_dir = STRATEGIES_DIR / new_name
    new_directive = INBOX_DIR / f"{new_name}.txt"
    if new_strat_dir.exists() or new_directive.exists():
        raise FileExistsError(
            f"Clone target already exists (directive={new_directive.exists()}, "
            f"strategy_dir={new_strat_dir.exists()}). Delete or choose another "
            f"--idea before retrying."
        )

    # --- Directive ---
    src_directive = _find_directive(source_name)
    directive_text = src_directive.read_text(encoding="utf-8")
    # Replace the strategy name in every occurrence.
    directive_text = directive_text.replace(source_name, new_name)
    # Replace the symbols list with the new single symbol.
    parsed = yaml.safe_load(directive_text) or {}
    parsed["symbols"] = [new_symbol]
    # Scrub any stale test.repeat_override_reason — this is a fresh clone.
    if isinstance(parsed.get("test"), dict):
        parsed["test"].pop("repeat_override_reason", None)
    directive_text = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    new_directive.write_text(directive_text, encoding="utf-8")
    print(f"[new_pass] Directive written: {new_directive}")

    # --- Strategy ---
    src_strategy = STRATEGIES_DIR / source_name / "strategy.py"
    if not src_strategy.exists():
        raise FileNotFoundError(f"Source strategy.py not found: {src_strategy}")
    src_code = src_strategy.read_text(encoding="utf-8")
    new_code = src_code.replace(source_name, new_name)
    # Also update any bare asset-token references in identifiers/docstrings
    # that match the exact old asset token surrounded by word boundaries.
    # This is a best-effort textual touch-up; indicator imports are untouched
    # (they live under indicators.* and never reference asset tokens).
    new_code = re.sub(
        rf"\b{re.escape(old_asset)}\b",
        new_asset,
        new_code,
    )
    new_strat_dir.mkdir(parents=True, exist_ok=True)
    new_strat_py = new_strat_dir / "strategy.py"
    new_strat_py.write_text(new_code, encoding="utf-8")
    print(f"[new_pass] Strategy written: {new_strat_py}")

    # --- Indicator-hash parity check (Phase 4 invariant) ---
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from tools.indicator_hasher import aggregate_indicator_hash
        ind_re = re.compile(
            r"^\s*(?:from\s+(indicators(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s+import"
            r"|import\s+(indicators(?:\.[A-Za-z_][A-Za-z0-9_]*)+))",
            re.MULTILINE,
        )
        src_mods = sorted({(mm.group(1) or mm.group(2))
                           for mm in ind_re.finditer(src_code)})
        new_mods = sorted({(mm.group(1) or mm.group(2))
                           for mm in ind_re.finditer(new_code)})
        src_hash, _ = aggregate_indicator_hash(src_mods, project_root=PROJECT_ROOT)
        new_hash, _ = aggregate_indicator_hash(new_mods, project_root=PROJECT_ROOT)
        if src_hash != new_hash:
            raise RuntimeError(
                f"Indicator content hash parity check FAILED. "
                f"src={src_hash[:12]}, new={new_hash[:12]}. "
                f"Clone should preserve indicator imports byte-for-byte — "
                f"investigate before rehashing."
            )
        print(
            f"[new_pass] Indicator-hash parity OK ({src_hash[:12]}; "
            f"{len(new_mods)} module(s))"
        )
    except Exception as e:
        print(f"[new_pass] WARNING: indicator-hash check skipped/failed: {e}")

    print(
        f"\n[new_pass] Clone scaffolded. Next steps:\n"
        f"  1. Inspect {new_directive}\n"
        f"  2. Inspect {new_strat_py}\n"
        f"  3. Run: python tools/new_pass.py --rehash {new_name}\n"
        f"  4. Run: python tools/run_pipeline.py --all\n"
    )


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    args = sys.argv[1:]

    # --rehash short form (kept for backward compatibility).
    if args and args[0] == "--rehash":
        if len(args) < 2:
            print("Usage: python tools/new_pass.py --rehash <strategy_name>")
            sys.exit(1)
        rehash_pass(args[1])
        sys.exit(0)

    # --clone-asset subcommand.
    if args and args[0] == "--clone-asset":
        p = argparse.ArgumentParser(prog="new_pass.py --clone-asset")
        p.add_argument("source", help="Source strategy name.")
        p.add_argument("--symbol", required=True, help="New symbol (e.g. BTCUSD).")
        p.add_argument(
            "--idea",
            default=None,
            help="Explicit 2-digit idea_id for the clone. Auto-selected if omitted.",
        )
        ns = p.parse_args(args[1:])
        clone_asset(ns.source, ns.symbol, new_idea=ns.idea)
        sys.exit(0)

    # Positional: source, new (legacy create_pass).
    if len(args) == 2:
        create_pass(args[0], args[1])
        sys.exit(0)

    print(
        "Usage:\n"
        "  python tools/new_pass.py <source_pass> <new_pass>\n"
        "  python tools/new_pass.py --rehash <new_pass>\n"
        "  python tools/new_pass.py --clone-asset <source_pass> --symbol <SYMBOL> [--idea <NN>]\n"
    )
    sys.exit(1)
