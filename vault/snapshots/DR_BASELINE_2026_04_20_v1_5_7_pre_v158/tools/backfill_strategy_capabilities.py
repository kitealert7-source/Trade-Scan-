"""
backfill_strategy_capabilities.py — one-time migration tool.

Injects REQUIRED_CAPABILITIES and REQUIRED_CONTRACT_IDS module-level
constants into every strategy.py under strategies/ that lacks them.

Design constraints
------------------
1. Idempotent. Re-running is a no-op for already-populated files
   (correct-value skip) and a rewrite only when the existing constants
   disagree with inference.
2. Signature-hash invariant. The injected constants live OUTSIDE the
   STRATEGY_SIGNATURE dict, so the 16-char signature hash in
   `# --- SIGNATURE HASH: ... ---` MUST remain bit-identical before and
   after backfill. The tool re-reads the hash after write and fails
   loudly if it drifted.
3. Capability inference is the source of truth. We never ask the
   operator to supply the list — `tools.capability_inference` walks
   the AST and derives it deterministically.
4. Contract-id is engine-authored. We read it from the single FROZEN
   engine manifest that satisfies the inferred capability set.
   Ambiguity (multiple satisfying engines) is a hard abort.

Usage
-----
    python tools/backfill_strategy_capabilities.py --dry-run
    python tools/backfill_strategy_capabilities.py --apply
    python tools/backfill_strategy_capabilities.py --apply --strategy <ID>
"""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.capability_inference import (  # noqa: E402
    CAP_BLOCK_END,
    CAP_BLOCK_START,
    infer_capabilities,
    load_catalog,
    read_declared_fields,
    render_capability_block,
    resolve_frozen_contract_id,
)
from tools.engine_resolver import resolve_engine  # noqa: E402

STRATEGIES_DIR = PROJECT_ROOT / "strategies"

HASH_RE = re.compile(r"# --- SIGNATURE HASH: ([0-9a-f]{16}) ---")


def _extract_sig_hash(text: str) -> str | None:
    m = HASH_RE.search(text)
    return m.group(1) if m else None


def _inject_or_replace(text: str, block: str) -> str:
    """
    If the markers exist, replace the block in place. Otherwise append
    at end-of-file. Markers keep the block idempotently locatable.
    """
    pattern = re.compile(
        re.escape(CAP_BLOCK_START) + r".*?" + re.escape(CAP_BLOCK_END) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + "\n" + block


def process_strategy(strategy_py: Path, apply: bool) -> dict:
    """
    Returns a result dict: {status, strategy, inferred, declared,
    contract_id, hash_before, hash_after, note}.
    status ∈ {SKIP_OK, WRITE, WRITE_APPLIED, ERROR}.
    """
    text = strategy_py.read_text(encoding="utf-8")
    hash_before = _extract_sig_hash(text)

    try:
        inferred = infer_capabilities(strategy_py)
    except Exception as e:
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": f"inference failed: {e}"}

    catalog = load_catalog()
    unknown = inferred - set(catalog.keys())
    if unknown:
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": f"inferred tokens not in catalog: {sorted(unknown)}"}

    try:
        contract_id = resolve_frozen_contract_id(inferred)
    except Exception as e:
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": f"contract resolution failed: {e}"}

    existing_caps, existing_contracts = read_declared_fields(strategy_py)
    declared_caps = sorted(inferred)
    declared_contracts = [contract_id]

    if (existing_caps is not None
            and existing_contracts is not None
            and sorted(existing_caps) == declared_caps
            and sorted(existing_contracts) == declared_contracts):
        return {"status": "SKIP_OK", "strategy": strategy_py.parent.name,
                "inferred": declared_caps, "contract_id": contract_id,
                "hash_before": hash_before, "hash_after": hash_before}

    block = render_capability_block(declared_caps, declared_contracts)
    new_text = _inject_or_replace(text, block)

    if not apply:
        return {"status": "WRITE", "strategy": strategy_py.parent.name,
                "inferred": declared_caps, "contract_id": contract_id,
                "hash_before": hash_before, "hash_after": hash_before}

    tmp = strategy_py.with_suffix(".py.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(strategy_py)

    verify_text = strategy_py.read_text(encoding="utf-8")
    hash_after = _extract_sig_hash(verify_text)
    if hash_before != hash_after:
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": f"SIGNATURE HASH DRIFT: {hash_before} -> {hash_after}",
                "hash_before": hash_before, "hash_after": hash_after}

    verify_caps, verify_contracts = read_declared_fields(strategy_py)
    if (verify_caps is None or verify_contracts is None
            or sorted(verify_caps) != declared_caps
            or sorted(verify_contracts) != declared_contracts):
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": "post-write readback mismatch"}

    try:
        resolve_engine(declared_caps, declared_contracts)
    except Exception as e:
        return {"status": "ERROR", "strategy": strategy_py.parent.name,
                "note": f"post-write resolver failed: {e}"}

    return {"status": "WRITE_APPLIED", "strategy": strategy_py.parent.name,
            "inferred": declared_caps, "contract_id": contract_id,
            "hash_before": hash_before, "hash_after": hash_after}


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    ap.add_argument("--strategy", default=None,
                    help="process a single strategy id")
    args = ap.parse_args()

    targets = []
    if args.strategy:
        p = STRATEGIES_DIR / args.strategy / "strategy.py"
        if not p.exists():
            print(f"[FAIL] {p} not found")
            sys.exit(2)
        targets.append(p)
    else:
        for d in sorted(STRATEGIES_DIR.iterdir()):
            sp = d / "strategy.py"
            if sp.exists():
                targets.append(sp)

    counts = {"SKIP_OK": 0, "WRITE": 0, "WRITE_APPLIED": 0, "ERROR": 0}
    errors = []
    for sp in targets:
        r = process_strategy(sp, apply=args.apply)
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        tag = r["status"]
        if tag == "ERROR":
            errors.append(r)
            print(f"[{tag}] {r['strategy']} :: {r.get('note')}")
        elif tag == "SKIP_OK":
            pass
        else:
            print(f"[{tag}] {r['strategy']} caps={r['inferred']} "
                  f"contract={r['contract_id'][:24]}...")

    print()
    print("=" * 60)
    print(f"Total    : {len(targets)}")
    print(f"Skip-OK  : {counts['SKIP_OK']}")
    print(f"Write    : {counts['WRITE']}")
    print(f"Applied  : {counts['WRITE_APPLIED']}")
    print(f"Errors   : {counts['ERROR']}")
    print("=" * 60)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
